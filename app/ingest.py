"""Data ingestion and normalisation (PRD 6.1).

Pipeline: parse -> validate -> preview -> commit (transactional) -> match ->
quarantine unmatched. Implements FR-D01..FR-D07.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import config, db

TIMESTAMP_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)

SEVERITIES = {"critical", "high", "medium", "low", "info"}
EXPOSURE_CLASSES = {"internet_facing", "internal", "external", "dmz", "restricted"}
CE_SOURCES = {"measured", "benchmark", "assumed"}
EFFECT_TYPES = {"control_ce", "finding_filter", "loss_component", "exposure_factor"}

# Uploaded monetary fields are expressed in whole rupees (major units) and are
# converted to the integer minor units the database stores.
MONEY_COLUMNS: dict[str, tuple[str, ...]] = {
    "assets": ("daily_revenue",),
    "actions": ("cost",),
    "loss_components": ("value",),
}


class ValidationError:
    __slots__ = ("row_number", "column", "code", "message", "severity", "value")

    def __init__(self, row_number: int, column: str, code: str, message: str,
                 severity: str = "error", value: Any = None):
        self.row_number = row_number
        self.column = column
        self.code = code
        self.message = message
        self.severity = severity
        self.value = value

    def as_dict(self) -> dict[str, Any]:
        return {"row_number": self.row_number, "column": self.column, "code": self.code,
                "message": self.message, "severity": self.severity, "value": self.value}


class IngestError(Exception):
    pass


# ---------------------------------------------------------------- schemas
@dataclass
class FieldSpec:
    name: str
    required: bool = False
    kind: str = "string"           # string|int|float|bool|enum|ts|date
    enum: set[str] | None = None
    low: float | None = None
    high: float | None = None
    natural_key: bool = False


DATASET_SCHEMAS: dict[str, list[FieldSpec]] = {
    "assets": [
        FieldSpec("asset_id", True, "string", natural_key=True),
        FieldSpec("name", True, "string"),
        FieldSpec("asset_type", True, "string"),
        FieldSpec("business_unit", True, "string"),
        FieldSpec("business_service", kind="string"),
        FieldSpec("criticality", True, "int", low=1, high=5),
        FieldSpec("ip", kind="string"),
        FieldSpec("hostname", kind="string"),
        FieldSpec("daily_revenue", False, "int", low=0),
        FieldSpec("exposure_class", False, "enum", enum=EXPOSURE_CLASSES),
        FieldSpec("status", False, "enum", enum={"active", "decommissioned", "retired"}),
        FieldSpec("source_system", kind="string"),
        FieldSpec("observed_at", False, "ts"),
    ],
    "findings": [
        FieldSpec("external_finding_id", True, "string", natural_key=True),
        FieldSpec("source_system", True, "string"),
        FieldSpec("asset_id", False, "string"),
        FieldSpec("ip", kind="string"),
        FieldSpec("hostname", kind="string"),
        FieldSpec("rule_id", False, "string"),
        FieldSpec("title", False, "string"),
        FieldSpec("severity", True, "enum", enum=SEVERITIES),
        FieldSpec("cvss_base", False, "float", low=0, high=10),
        FieldSpec("exploitable", False, "bool"),
        FieldSpec("status", False, "enum", enum={"open", "remediated", "accepted", "false_positive"}),
        FieldSpec("scenario_hints", kind="string"),
        FieldSpec("observed_at", False, "ts"),
    ],
    "controls": [
        FieldSpec("control_code", True, "string", natural_key=True),
        FieldSpec("name", True, "string"),
        FieldSpec("domain", False, "string"),
        FieldSpec("ce_score", True, "float", low=0, high=0.99),
        FieldSpec("ce_source", False, "enum", enum=CE_SOURCES),
        FieldSpec("ce_evidence_ref", kind="string"),
        FieldSpec("framework_iso", kind="string"),
        FieldSpec("framework_nist", kind="string"),
        FieldSpec("framework_cis", kind="string"),
    ],
    "scenarios": [
        FieldSpec("scenario_code", True, "string", natural_key=True),
        FieldSpec("name", True, "string"),
        FieldSpec("narrative", kind="string"),
        FieldSpec("asset_id", True, "string"),
        FieldSpec("threat_actor", kind="string"),
        FieldSpec("technique", kind="string"),
        FieldSpec("correlation_group_id", kind="string"),
        FieldSpec("p0", True, "float", low=0.0001,
                  high=config.MAX_ANNUAL_PROBABILITY),
        FieldSpec("exposure_factor", False, "float", low=0, high=2),
        FieldSpec("expected_events_per_incident", False, "float", low=1, high=10),
        FieldSpec("sle_low_multiplier", False, "float", low=0, high=1),
        FieldSpec("sle_high_multiplier", False, "float", low=1, high=5),
        FieldSpec("required_controls", kind="string"),
    ],
    "actions": [
        FieldSpec("action_code", True, "string", natural_key=True),
        FieldSpec("name", True, "string"),
        FieldSpec("description", kind="string"),
        FieldSpec("category", False, "string"),
        FieldSpec("cost", True, "int", low=0),
        FieldSpec("lead_time_days", False, "int", low=0, high=1000),
        FieldSpec("capacity_group", kind="string"),
        FieldSpec("requires_actions", kind="string"),
        FieldSpec("effect_type", True, "enum", enum=EFFECT_TYPES),
        FieldSpec("effect_json", True, "string"),
    ],
    "loss_components": [
        FieldSpec("scenario_code", True, "string"),
        FieldSpec("component_code", True, "string", natural_key=True),
        FieldSpec("basis", True, "enum",
                  enum={"fixed_amount", "daily_revenue_x_hours", "per_record"}),
        FieldSpec("value", False, "int", low=0),
        FieldSpec("hours", kind="float"),
        FieldSpec("record_count", kind="int"),
        FieldSpec("source_ref", kind="string"),
    ],
}


# ---------------------------------------------------------------- parsing
def parse_upload(filename: str, raw: bytes) -> list[dict[str, Any]]:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in config.ALLOWED_EXTENSIONS:
        raise IngestError(
            f"Unsupported file type '{ext or 'unknown'}'. Allowed: "
            + ", ".join(sorted(config.ALLOWED_EXTENSIONS)))
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise IngestError(
            f"File is {len(raw) / 1024 / 1024:.1f} MB. Maximum is "
            f"{config.MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB.")

    text = raw.decode("utf-8-sig", errors="strict") if raw else ""
    if not text.strip():
        raise IngestError("File is empty")

    if ext == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise IngestError(f"Invalid JSON at line {exc.lineno}: {exc.msg}") from exc
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            for key in ("rows", "data", "records", "items"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
            else:
                raise IngestError(
                    "JSON must be a list of rows, or an object with a 'rows' list")
        else:
            raise IngestError("JSON must be a list or an object containing a list")
        out = []
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise IngestError(f"Row {i} is not a JSON object")
            out.append({str(k).strip(): v for k, v in row.items()})
        return out

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise IngestError("CSV has no header row")
    headers = [h.strip() for h in reader.fieldnames]
    if len(set(h.lower() for h in headers)) != len(headers):
        raise IngestError("CSV header contains duplicate column names")
    rows = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        clean = {}
        for key, value in row.items():
            if key is None:
                continue
            clean[key.strip()] = value.strip() if isinstance(value, str) else value
        # An empty row is kept so the user is told it was rejected rather than
        # silently losing it; it will be quarantined with a missing-field reason.
        clean["__line__"] = i
        rows.append(clean)
    if not rows or all(all(v in (None, "") for k, v in row.items() if k != "__line__")
                       for row in rows):
        raise IngestError("File contains no data rows")
    return rows


# ---------------------------------------------------------------- validation
def _parse_ts(value: Any) -> str:
    if value in (None, ""):
        raise ValueError("empty timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="seconds")
    text = str(value).strip()
    if re.fullmatch(r"\d{9,13}", text):
        seconds = int(text) / (1000 if len(text) == 13 else 1)
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")
    for fmt in TIMESTAMP_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    raise ValueError("unrecognised timestamp format")


def _coerce(value: Any, spec: FieldSpec, errors: list[ValidationError],
            row_number: int) -> Any:
    if value in (None, ""):
        if spec.required:
            errors.append(ValidationError(row_number, spec.name, "MISSING_REQUIRED_FIELD",
                                          f"'{spec.name}' is required"))
        return None
    text = str(value).strip() if not isinstance(value, (int, float)) else value

    if spec.kind in ("string",):
        if isinstance(text, (dict, list)):
            errors.append(ValidationError(row_number, spec.name, "TYPE_MISMATCH",
                                          f"'{spec.name}' must be text"))
            return None
        return str(text)
    if spec.kind == "int":
        try:
            number = int(float(str(text).replace(",", "")))
        except (TypeError, ValueError):
            errors.append(ValidationError(row_number, spec.name, "TYPE_MISMATCH",
                                          f"'{spec.name}' must be a whole number",
                                          value=text))
            return None
        if spec.low is not None and number < spec.low:
            errors.append(ValidationError(row_number, spec.name, "OUT_OF_RANGE",
                                          f"'{spec.name}' must be >= {spec.low:g}",
                                          value=text))
        if spec.high is not None and number > spec.high:
            errors.append(ValidationError(row_number, spec.name, "OUT_OF_RANGE",
                                          f"'{spec.name}' must be <= {spec.high:g}",
                                          value=text))
        return number
    if spec.kind == "float":
        try:
            number = float(str(text).replace(",", ""))
        except (TypeError, ValueError):
            errors.append(ValidationError(row_number, spec.name, "TYPE_MISMATCH",
                                          f"'{spec.name}' must be a number", value=text))
            return None
        if spec.low is not None and number < spec.low:
            errors.append(ValidationError(row_number, spec.name, "OUT_OF_RANGE",
                                          f"'{spec.name}' must be >= {spec.low:g}", value=text))
        if spec.high is not None and number > spec.high:
            errors.append(ValidationError(row_number, spec.name, "OUT_OF_RANGE",
                                          f"'{spec.name}' must be <= {spec.high:g}", value=text))
        return number
    if spec.kind == "bool":
        lowered = str(text).lower()
        if lowered in {"1", "true", "yes", "y", "t"}:
            return 1
        if lowered in {"0", "false", "no", "n", "f"}:
            return 0
        errors.append(ValidationError(row_number, spec.name, "TYPE_MISMATCH",
                                      f"'{spec.name}' must be true/false or 1/0", value=text))
        return None
    if spec.kind == "enum":
        if spec.enum and str(text).lower() not in spec.enum:
            errors.append(ValidationError(row_number, spec.name, "UNKNOWN_ENUM_VALUE",
                                          f"'{spec.name}' must be one of: "
                                          + ", ".join(sorted(spec.enum)), value=text))
            return None
        return str(text).lower()
    if spec.kind in ("ts", "date"):
        try:
            return _parse_ts(text)
        except (ValueError, OSError, OverflowError):
            errors.append(ValidationError(row_number, spec.name, "BAD_TIMESTAMP",
                                          f"'{spec.name}' is not a recognised timestamp "
                                          "(use ISO-8601, e.g. 2026-09-20T06:00:00Z)",
                                          value=text))
            return None
    return text


def validate(dataset_type: str,
             rows: list[dict[str, Any]]) -> tuple[list[dict], list[ValidationError],
                                                   list[tuple[dict, str]]]:
    """Split rows into (accepted, errors, quarantined).

    A row with a field level problem is quarantined with its reason rather than
    rejecting the whole file. That is the point of the quarantine table: one
    bad record must not stop a 5,000 row feed from loading.
    """
    spec = DATASET_SCHEMAS.get(dataset_type)
    if spec is None:
        raise IngestError(
            f"Unknown dataset type '{dataset_type}'. Supported: "
            + ", ".join(sorted(DATASET_SCHEMAS)))

    errors: list[ValidationError] = []
    known = {f.name for f in spec}
    cleaned: list[dict[str, Any]] = []
    invalid: list[tuple[dict, str]] = []
    present = {k for row in rows for k in row if not k.startswith("__")}
    unknown_cols = sorted(present - known)
    if unknown_cols:
        errors.append(ValidationError(0, ", ".join(unknown_cols[:6]), "UNKNOWN_COLUMN",
                                      "Columns not in the schema were ignored: "
                                      + ", ".join(unknown_cols), severity="warning"))

    for row in rows:
        line = row.get("__line__") or 0
        before = len(errors)
        record: dict[str, Any] = {}
        for field_spec in spec:
            record[field_spec.name] = _coerce(
                row.get(field_spec.name), field_spec, errors, line)
        extra = {k: v for k, v in row.items() if k not in known and not k.startswith("__")}
        if extra:
            record["_extra"] = extra
        if len(errors) == before:
            record["__line__"] = line
            cleaned.append(record)
        else:
            invalid.append((row, _summarise([e for e in errors[before:] if e.severity == "error"])))

    # dataset-level cross-field checks. A row that fails these is quarantined
    # too, so rows_ok never counts a row we cannot write.
    if dataset_type == "actions":
        keep = []
        for record in cleaned:
            try:
                json.loads(record.get("effect_json") or "{}")
            except json.JSONDecodeError as exc:
                errors.append(ValidationError(record["__line__"], "effect_json",
                                              "TYPE_MISMATCH",
                                              f"effect_json is not valid JSON: {exc.msg}"))
                invalid.append((record, f"effect_json is not valid JSON: {exc.msg}"))
                continue
            keep.append(record)
        cleaned = keep

    for column in MONEY_COLUMNS.get(dataset_type, ()):
        for record in cleaned:
            if record.get(column) is None:
                record[column] = 0
            else:
                record[column] = db.to_minor(float(record[column]))
    return cleaned, errors, invalid


def _summarise(row_errors: list[ValidationError]) -> str:
    if not row_errors:
        return "failed validation"
    parts = [f"{e.column} ({e.code})" for e in row_errors[:4]]
    text = ", ".join(parts)
    if len(row_errors) > 4:
        text += f", +{len(row_errors) - 4} more"
    return text


# ---------------------------------------------------------------- matching
def _normalise_host(value: str) -> str:
    return value.strip().lower().rstrip(".")


def build_asset_indexes(conn) -> dict[str, dict[str, str]]:
    by_id: dict[str, str] = {}
    by_host: dict[str, str] = {}
    by_ip: dict[str, str] = {}
    for row in conn.execute("SELECT asset_id, ip, hostname FROM assets"):
        by_id[row["asset_id"]] = row["asset_id"]
        if row["hostname"]:
            by_host[_normalise_host(row["hostname"])] = row["asset_id"]
        if row["ip"]:
            by_ip[row["ip"].split("/")[0]] = row["asset_id"]
    return {"id": by_id, "host": by_host, "ip": by_ip}


def match_finding(row: dict[str, Any], indexes: dict[str, dict[str, str]]) -> tuple[str | None, str | None]:
    """Three-tier match in fixed order: exact id, hostname, ip (FR-D03)."""
    if row.get("asset_id") and row["asset_id"] in indexes["id"]:
        return row["asset_id"], "exact"
    if row.get("hostname"):
        host = _normalise_host(row["hostname"])
        if host in indexes["host"]:
            return indexes["host"][host], "hostname"
        for known, asset_id in indexes["host"].items():
            if host.endswith("." + known) or known.endswith("." + host):
                return asset_id, "hostname"
    if row.get("ip"):
        ip = str(row["ip"]).split("/")[0]
        if ip in indexes["ip"]:
            return indexes["ip"][ip], "ip"
    return None, None


# ---------------------------------------------------------------- commit
@dataclass
class IngestResult:
    dataset_id: int
    dataset_type: str
    status: str
    rows_total: int
    rows_ok: int
    rows_updated: int
    rows_quarantined: int
    errors: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"dataset_id": self.dataset_id, "dataset_type": self.dataset_type,
                "status": self.status, "rows_total": self.rows_total,
                "rows_ok": self.rows_ok, "rows_updated": self.rows_updated,
                "rows_quarantined": self.rows_quarantined, "errors": self.errors,
                "message": self.message}


def ingest(conn, dataset_type: str, filename: str, raw: bytes, *, commit: bool = True,
           actor: dict | None = None, synthetic: bool = False,
           synthetic_seed: int | None = None) -> IngestResult:
    actor = actor or {}
    now = db.utcnow()

    try:
        rows = parse_upload(filename, raw)
    except (IngestError, UnicodeDecodeError) as exc:
        conn.execute(
            """INSERT INTO datasets (dataset_type,filename,status,rows_total,rows_ok,
               rows_updated,rows_quarantined,errors_json,synthetic,synthetic_seed)
               VALUES (?,?,'rejected',0,0,0,0,?,?,?)""",
            (dataset_type, filename, json.dumps([{
                "row_number": 0, "column": "-", "code": "PARSE_ERROR", "severity": "error",
                "message": str(exc)}]), int(synthetic), synthetic_seed))
        db.audit(conn, "ingest.rejected", entity=dataset_type,
                 detail={"filename": filename, "error": str(exc)},
                 username=actor.get("username"), role=actor.get("role"), severity="warning")
        return IngestResult(0, dataset_type, "rejected", 0, 0, 0, 0,
                            [{"row_number": 0, "column": "-", "code": "PARSE_ERROR",
                              "message": str(exc), "severity": "error"}],
                            message=str(exc))

    cleaned, errors, invalid = validate(dataset_type, rows)

    shown = errors[: config.MAX_VALIDATION_ERRORS_SHOWN]
    errors_payload = [e.as_dict() for e in shown]
    if len(errors) > len(shown):
        errors_payload.append({
            "row_number": 0, "column": "-", "code": "TRUNCATED",
            "severity": "warning",
            "message": f"{len(errors)} problems found (showing first {len(shown)})"})

    if not cleaned:
        dataset_id = conn.execute(
            """INSERT INTO datasets (dataset_type,filename,status,rows_total,rows_ok,
               rows_updated,rows_quarantined,errors_json,synthetic,synthetic_seed)
               VALUES (?,?,'rejected',?,0,0,?,?,?,?)""",
            (dataset_type, filename, len(rows), len(invalid),
             json.dumps(errors_payload), int(synthetic), synthetic_seed)).lastrowid
        for record, reason in invalid:
            conn.execute(
                "INSERT INTO quarantine (dataset_id, row_number, reason, payload_json) "
                "VALUES (?,?,?,?)",
                (dataset_id, record.get("__line__"), reason, json.dumps(record, default=str)))
        db.audit(conn, "ingest.rejected", entity=dataset_type,
                 detail={"filename": filename, "rows": len(rows), "quarantined": len(invalid)},
                 username=actor.get("username"), role=actor.get("role"), severity="warning")
        return IngestResult(dataset_id, dataset_type, "rejected", len(rows), 0, 0, len(invalid),
                            errors_payload,
                            f"No rows passed validation. {len(invalid)} row(s) quarantined.")

    if not commit:
        dataset_id = conn.execute(
            """INSERT INTO datasets (dataset_type,filename,status,rows_total,rows_ok,
               rows_updated,rows_quarantined,errors_json,synthetic,synthetic_seed)
               VALUES (?,?,'validated',?,?,0,?,?,?,?)""",
            (dataset_type, filename, len(rows), len(cleaned), len(invalid),
             json.dumps(errors_payload), int(synthetic), synthetic_seed)).lastrowid
        return IngestResult(dataset_id, dataset_type, "validated", len(rows), len(cleaned),
                            0, len(invalid), errors_payload,
                            f"Dry run: {len(cleaned)} row(s) would load, "
                            f"{len(invalid)} would be quarantined. Nothing was written.")

    written, updated, quarantined = _write(conn, dataset_type, cleaned, now, synthetic)
    quarantined = list(quarantined) + list(invalid)
    payload = json.dumps(errors_payload)
    if quarantined:
        payload = json.dumps(errors_payload + [{
            "row_number": 0, "column": "-", "code": "QUARANTINED",
            "severity": "warning",
            "message": f"{len(quarantined)} row(s) quarantined and excluded from all risk "
                       "figures. See the quarantine list."}])

    dataset_id = conn.execute(
        """INSERT INTO datasets (dataset_type,filename,status,rows_total,rows_ok,
           rows_updated,rows_quarantined,errors_json,loaded_at,synthetic,synthetic_seed)
           VALUES (?,?,'committed',?,?,?,?,?,?,?,?)""",
        (dataset_type, filename, len(rows), written, updated, len(quarantined), payload,
         now, int(synthetic), synthetic_seed)).lastrowid

    for record, reason in quarantined:
        conn.execute(
            "INSERT INTO quarantine (dataset_id, row_number, reason, payload_json) "
            "VALUES (?,?,?,?)",
            (dataset_id, record.get("__line__"), reason, json.dumps(record, default=str)))

    db.audit(conn, "ingest.committed", entity=dataset_type,
             detail={"filename": filename, "rows": written, "updated": updated,
                     "quarantined": len(quarantined)},
             username=actor.get("username"), role=actor.get("role"))
    return IngestResult(dataset_id, dataset_type, "committed", len(rows), written,
                        updated, len(quarantined), errors_payload,
                        f"Loaded {written} row(s); {len(quarantined)} quarantined.")


def _write(conn, dataset_type: str, cleaned: list[dict], now: str,
           synthetic: bool) -> tuple[int, int, list[tuple[dict, str]]]:
    """Returns (rows_written, rows_updated, quarantined)."""
    written = 0
    updated = 0
    quarantined: list[tuple[dict, str]] = []

    if dataset_type == "assets":
        for row in cleaned:
            exists = conn.execute("SELECT 1 FROM assets WHERE asset_id = ?",
                                  (row["asset_id"],)).fetchone()
            conn.execute(
                """INSERT INTO assets (asset_id,name,asset_type,business_unit,
                   business_service,criticality,ip,hostname,daily_revenue,exposure_class,
                   status,source_system,synthetic,first_seen,updated_at,observed_at)
                   VALUES (:asset_id,:name,:asset_type,:business_unit,:business_service,
                   :criticality,:ip,:hostname,:daily_revenue,:exposure_class,:status,
                   :source_system,:syn,:now,:now,:observed_at)
                   ON CONFLICT(asset_id) DO UPDATE SET
                     name=excluded.name, asset_type=excluded.asset_type,
                     business_unit=excluded.business_unit,
                     business_service=excluded.business_service,
                     criticality=excluded.criticality, ip=excluded.ip,
                     hostname=excluded.hostname, daily_revenue=excluded.daily_revenue,
                     exposure_class=excluded.exposure_class, status=excluded.status,
                     source_system=excluded.source_system, synthetic=excluded.synthetic,
                     updated_at=excluded.updated_at, observed_at=excluded.observed_at""",
                {**row, "exposure_class": row.get("exposure_class") or "internal",
                 "status": row.get("status") or "active",
                 "daily_revenue": row.get("daily_revenue") or 0,
                 "syn": int(synthetic), "now": now})
            written += 1
            updated += 1 if exists else 0

    elif dataset_type == "findings":
        indexes = build_asset_indexes(conn)
        for row in cleaned:
            asset_id, method = match_finding(row, indexes)
            exists = conn.execute(
                "SELECT 1 FROM findings WHERE source_system = ? AND external_finding_id = ?",
                (row["source_system"], row["external_finding_id"])).fetchone()
            if asset_id is None:
                quarantined.append((row, "unmatched_asset"))
                continue
            conn.execute(
                """INSERT INTO findings (source_system,external_finding_id,asset_id,
                   match_method,rule_id,title,severity,cvss_base,exploitable,status,
                   scenario_hints,synthetic,first_seen,updated_at,observed_at,raw)
                   VALUES (:source_system,:external_finding_id,:asset_id,:method,:rule_id,
                   :title,:severity,:cvss_base,:exploitable,:status,:scenario_hints,:syn,
                   :now,:now,:observed_at,:raw)
                   ON CONFLICT(source_system,external_finding_id) DO UPDATE SET
                     asset_id=excluded.asset_id, match_method=excluded.match_method,
                     rule_id=excluded.rule_id, title=excluded.title,
                     severity=excluded.severity, cvss_base=excluded.cvss_base,
                     exploitable=excluded.exploitable, status=excluded.status,
                     scenario_hints=excluded.scenario_hints,
                     updated_at=excluded.updated_at, observed_at=excluded.observed_at""",
                {**row, "asset_id": asset_id, "method": method,
                 "status": row.get("status") or "open",
                 "exploitable": row.get("exploitable") or 0,
                 "syn": int(synthetic), "now": now,
                 "raw": json.dumps(row, default=str)})
            written += 1
            updated += 1 if exists else 0

    elif dataset_type == "controls":
        for row in cleaned:
            exists = conn.execute("SELECT 1 FROM controls WHERE control_code = ?",
                                  (row["control_code"],)).fetchone()
            conn.execute(
                """INSERT INTO controls (control_code,name,domain,ce_score,ce_source,
                   ce_evidence_ref,framework_iso,framework_nist,framework_cis,synthetic,
                   updated_at) VALUES (:control_code,:name,:domain,:ce_score,:ce_source,
                   :ce_evidence_ref,:framework_iso,:framework_nist,:framework_cis,:syn,:now)
                   ON CONFLICT(control_code) DO UPDATE SET
                     name=excluded.name, domain=excluded.domain, ce_score=excluded.ce_score,
                     ce_source=excluded.ce_source, ce_evidence_ref=excluded.ce_evidence_ref,
                     framework_iso=excluded.framework_iso,
                     framework_nist=excluded.framework_nist,
                     framework_cis=excluded.framework_cis, updated_at=excluded.updated_at""",
                {**row, "domain": row.get("domain") or "INT-01",
                 "ce_source": row.get("ce_source") or "assumed", "syn": int(synthetic),
                 "now": now})
            written += 1
            updated += 1 if exists else 0

    elif dataset_type == "scenarios":
        for row in cleaned:
            if not conn.execute("SELECT 1 FROM assets WHERE asset_id = ?",
                                (row["asset_id"],)).fetchone():
                quarantined.append((row, f"unknown asset '{row['asset_id']}'"))
                continue
            exists = conn.execute("SELECT 1 FROM scenarios WHERE scenario_code = ?",
                                  (row["scenario_code"],)).fetchone()
            conn.execute(
                """INSERT INTO scenarios (scenario_code,name,narrative,asset_id,
                   threat_actor,technique,correlation_group_id,p0,exposure_factor,
                   expected_events_per_incident,sle_low_multiplier,sle_high_multiplier,
                   synthetic,updated_at)
                   VALUES (:scenario_code,:name,:narrative,:asset_id,:threat_actor,:technique,
                   :correlation_group_id,:p0,:exposure_factor,:expected_events_per_incident,
                   :slo,:shi,:syn,:now)
                   ON CONFLICT(scenario_code) DO UPDATE SET
                     name=excluded.name, narrative=excluded.narrative,
                     asset_id=excluded.asset_id, threat_actor=excluded.threat_actor,
                     technique=excluded.technique,
                     correlation_group_id=excluded.correlation_group_id, p0=excluded.p0,
                     exposure_factor=excluded.exposure_factor,
                     expected_events_per_incident=excluded.expected_events_per_incident,
                     sle_low_multiplier=excluded.sle_low_multiplier,
                     sle_high_multiplier=excluded.sle_high_multiplier,
                     updated_at=excluded.updated_at""",
                {**row, "slo": row.get("sle_low_multiplier") or 0.7,
                 "shi": row.get("sle_high_multiplier") or 1.3,
                 "exposure_factor": row.get("exposure_factor") or 1.0,
                 "expected_events_per_incident": row.get("expected_events_per_incident") or 1.0,
                 "syn": int(synthetic), "now": now})
            for code in [c.strip() for c in (row.get("required_controls") or "").split(",")
                         if c.strip()]:
                conn.execute(
                    "INSERT OR IGNORE INTO scenario_controls (scenario_code, control_code) "
                    "VALUES (?,?)", (row["scenario_code"], code))
            written += 1
            updated += 1 if exists else 0

    elif dataset_type == "actions":
        codes = {r["action_code"] for r in cleaned}
        for row in cleaned:
            try:
                effect = json.loads(row["effect_json"] or "{}")
            except json.JSONDecodeError:
                quarantined.append((row, "effect_json is not valid JSON"))
                continue
            req = [c.strip() for c in (row.get("requires_actions") or "").split(",")
                   if c.strip()]
            missing = [r for r in req if r not in codes and r not in {
                x["action_code"] for x in conn.execute("SELECT action_code FROM actions")}]
            if missing:
                quarantined.append((row, f"unknown prerequisite action(s): {', '.join(missing)}"))
                continue
            exists = conn.execute("SELECT 1 FROM actions WHERE action_code = ?",
                                  (row["action_code"],)).fetchone()
            conn.execute(
                """INSERT INTO actions (action_code,name,description,category,cost,
                   lead_time_days,capacity_group,requires_actions,effect_type,effect_json,
                   synthetic,updated_at) VALUES (:action_code,:name,:description,:category,
                   :cost,:lead_time_days,:capacity_group,:requires_actions,:effect_type,
                   :effect_json,:syn,:now)
                   ON CONFLICT(action_code) DO UPDATE SET
                     name=excluded.name, description=excluded.description,
                     category=excluded.category, cost=excluded.cost,
                     lead_time_days=excluded.lead_time_days,
                     capacity_group=excluded.capacity_group,
                     requires_actions=excluded.requires_actions,
                     effect_type=excluded.effect_type, effect_json=excluded.effect_json,
                     updated_at=excluded.updated_at""",
                {**row, "category": row.get("category") or "other",
                 "lead_time_days": row.get("lead_time_days") or 0,
                 "requires_actions": json.dumps(req),
                 "effect_json": json.dumps(effect), "syn": int(synthetic), "now": now})
            written += 1
            updated += 1 if exists else 0

    elif dataset_type == "loss_components":
        for row in cleaned:
            if not conn.execute("SELECT 1 FROM scenarios WHERE scenario_code = ?",
                                (row["scenario_code"],)).fetchone():
                quarantined.append((row, f"unknown scenario '{row['scenario_code']}'"))
                continue
            conn.execute(
                """INSERT INTO loss_components (scenario_code,component_code,basis,value,
                   hours,record_count,source_ref) VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(scenario_code,component_code) DO UPDATE SET
                     basis=excluded.basis, value=excluded.value, hours=excluded.hours,
                     record_count=excluded.record_count, source_ref=excluded.source_ref""",
                (row["scenario_code"], row["component_code"], row["basis"],
                 row.get("value") or 0, row.get("hours"), row.get("record_count"),
                 row.get("source_ref")))
            written += 1
            updated += 1
    else:
        raise IngestError(f"No writer for dataset type '{dataset_type}'")

    return written, updated, quarantined
