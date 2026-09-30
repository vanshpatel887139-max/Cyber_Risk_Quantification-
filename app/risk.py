"""Deterministic cyber risk quantification engine.

Every currency figure the product displays originates here. The LLM layer
(ai.py) may narrate these numbers but may never produce them.

Method (PRD 7)
--------------
  SLE  = sum(loss components)                     single loss expectancy
  m    = exposure_factor x vulnerability_multiplier
  P_in = 1 - (1 - p0) ** m                       annual probability, inherent
  mit  = product(1 - CE_c) over required controls
  P_res= P_in x mit                               annual probability, residual
  EAL  = P_res x SLE x lambda                     expected annual loss

  Group aggregation:  EAL_g = (1-rho) x sum + rho x max   (no double counting)
  Uncertainty band:   low = EAL x sl x pl,  high = EAL x sh x ph
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import config, db

SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.6, "medium": 0.3, "low": 0.1, "info": 0.0}
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]

# A finding with a known working exploit is treated as more likely to be used
# than the same severity without one.
EXPLOITABLE_MULTIPLIER = 1.5

PROBABILITY_MULT_LOW = 0.5
PROBABILITY_MULT_HIGH = 1.5

# Confidence rubric (PRD 4.2 F7). Each sub-score is 0..1, then weighted.
CONFIDENCE_WEIGHTS = {
    "completeness": 0.35,
    "evidence": 0.25,
    "freshness": 0.25,
    "provenance": 0.15,
}


class RiskError(Exception):
    """Raised when inputs make a risk calculation impossible."""


# ---------------------------------------------------------------- dataclasses
@dataclass
class Finding:
    external_finding_id: str
    source_system: str
    asset_id: str | None
    rule_id: str
    title: str
    severity: str
    exploitable: bool
    status: str
    scenario_hints: list[str]
    match_method: str | None
    observed_at: str | None


@dataclass
class Asset:
    asset_id: str
    name: str
    asset_type: str
    business_unit: str
    business_service: str | None
    criticality: int
    daily_revenue: int
    exposure_class: str
    status: str
    ip: str | None = None
    hostname: str | None = None
    source_system: str | None = None
    synthetic: bool = False
    observed_at: str | None = None


@dataclass
class Control:
    control_code: str
    name: str
    domain: str
    ce_score: float
    ce_source: str
    ce_evidence_ref: str | None
    framework_iso: str | None = None
    framework_nist: str | None = None
    framework_cis: str | None = None
    updated_at: str = ""


@dataclass
class LossComponent:
    component_code: str
    basis: str
    value: int
    hours: float | None
    record_count: int | None
    source_ref: str | None


@dataclass
class Scenario:
    scenario_code: str
    name: str
    narrative: str | None
    asset_id: str
    threat_actor: str | None
    technique: str | None
    correlation_group_id: str | None
    p0: float
    exposure_factor: float
    expected_events_per_incident: float
    sle_low_multiplier: float
    sle_high_multiplier: float
    required_controls: list[str] = field(default_factory=list)
    loss_components: list[LossComponent] = field(default_factory=list)


@dataclass
class Action:
    action_code: str
    name: str
    description: str
    category: str
    cost: int
    lead_time_days: int
    capacity_group: str | None
    requires_actions: list[str]
    effect_type: str
    effect: dict[str, Any]
    synthetic: bool = False

    @property
    def impacts_scenarios(self) -> bool:
        """True if the effect is global to the model rather than a single scenario."""
        return self.effect_type in {"control_ce", "finding_filter"}


@dataclass
class ScenarioResult:
    scenario_code: str
    name: str
    asset_id: str
    business_unit: str
    sle_minor: int
    sle_low_minor: int
    sle_high_minor: int
    p_inherent: float
    mitigation_factor: float
    p_residual: float
    lambda_: float
    eal_minor: int
    eal_low_minor: int
    eal_high_minor: int
    confidence: int
    confidence_band: str
    confidence_reasons: list[str]
    group_id: str | None
    group_peers: list[str] = field(default_factory=list)
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    control_detail: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True
    incomplete_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario_code": self.scenario_code,
            "name": self.name,
            "asset_id": self.asset_id,
            "business_unit": self.business_unit,
            "sle_minor": self.sle_minor,
            "sle_low_minor": self.sle_low_minor,
            "sle_high_minor": self.sle_high_minor,
            "p_inherent": round(self.p_inherent, 6),
            "mitigation_factor": round(self.mitigation_factor, 6),
            "p_residual": round(self.p_residual, 6),
            "lambda": self.lambda_,
            "eal_minor": self.eal_minor,
            "eal_low_minor": self.eal_low_minor,
            "eal_high_minor": self.eal_high_minor,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band,
            "confidence_reasons": self.confidence_reasons,
            "group_id": self.group_id,
            "group_peers": self.group_peers,
            "breakdown": self.breakdown,
            "control_detail": self.control_detail,
            "complete": self.complete,
            "incomplete_reasons": self.incomplete_reasons,
        }


@dataclass
class Assessment:
    eal_minor: int
    eal_low_minor: int
    eal_high_minor: int
    eal_unadjusted_minor: int
    confidence: int
    confidence_band: str
    scenarios: list[ScenarioResult]
    by_asset: dict[str, int]
    by_business_unit: dict[str, int]
    by_category: dict[str, int]
    by_actor: dict[str, int]
    freshness: dict[str, Any]
    incomplete: list[dict[str, Any]]
    currency: str
    rho_used: dict[str, float]
    excluded_findings: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "eal_minor": self.eal_minor,
            "eal_low_minor": self.eal_low_minor,
            "eal_high_minor": self.eal_high_minor,
            "eal_unadjusted_minor": self.eal_unadjusted_minor,
            "currency": self.currency,
            "symbol": config.CURRENCY_SYMBOL,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band,
            "scenarios": [s.as_dict() for s in self.scenarios],
            "by_asset": self.by_asset,
            "by_business_unit": self.by_business_unit,
            "by_category": self.by_category,
            "by_actor": self.by_actor,
            "freshness": self.freshness,
            "incomplete": self.incomplete,
            "rho_used": self.rho_used,
            "excluded_findings": self.excluded_findings,
        }

    def scenario(self, code: str) -> ScenarioResult | None:
        return next((s for s in self.scenarios if s.scenario_code == code), None)


# ---------------------------------------------------------------- loading
def load_model(conn) -> dict[str, Any]:
    """Read the whole input model out of the database into dataclasses."""
    assets: dict[str, Asset] = {}
    for row in conn.execute("SELECT * FROM assets"):
        assets[row["asset_id"]] = Asset(
            asset_id=row["asset_id"], name=row["name"], asset_type=row["asset_type"],
            business_unit=row["business_unit"], business_service=row["business_service"],
            criticality=row["criticality"], daily_revenue=row["daily_revenue"],
            exposure_class=row["exposure_class"], status=row["status"], ip=row["ip"],
            hostname=row["hostname"], source_system=row["source_system"],
            synthetic=bool(row["synthetic"]), observed_at=row["observed_at"],
        )

    findings: list[Finding] = []
    for row in conn.execute("SELECT * FROM findings"):
        findings.append(Finding(
            external_finding_id=row["external_finding_id"],
            source_system=row["source_system"], asset_id=row["asset_id"],
            rule_id=row["rule_id"] or "", title=row["title"] or "",
            severity=(row["severity"] or "info").lower(), exploitable=bool(row["exploitable"]),
            status=row["status"],
            scenario_hints=[h.strip() for h in (row["scenario_hints"] or "").split(",") if h.strip()],
            match_method=row["match_method"], observed_at=row["observed_at"],
        ))

    controls: dict[str, Control] = {}
    for row in conn.execute("SELECT * FROM controls"):
        controls[row["control_code"]] = Control(
            control_code=row["control_code"], name=row["name"], domain=row["domain"],
            ce_score=row["ce_score"], ce_source=row["ce_source"],
            ce_evidence_ref=row["ce_evidence_ref"], framework_iso=row["framework_iso"],
            framework_nist=row["framework_nist"], framework_cis=row["framework_cis"],
            updated_at=row["updated_at"],
        )

    comp_rows: dict[str, list[LossComponent]] = {}
    for row in conn.execute("SELECT * FROM loss_components"):
        comp_rows.setdefault(row["scenario_code"], []).append(LossComponent(
            component_code=row["component_code"], basis=row["basis"], value=row["value"],
            hours=row["hours"], record_count=row["record_count"], source_ref=row["source_ref"],
        ))

    req: dict[str, list[str]] = {}
    for row in conn.execute("SELECT * FROM scenario_controls"):
        req.setdefault(row["scenario_code"], []).append(row["control_code"])

    scenarios: dict[str, Scenario] = {}
    for row in conn.execute("SELECT * FROM scenarios"):
        code = row["scenario_code"]
        scenarios[code] = Scenario(
            scenario_code=code, name=row["name"], narrative=row["narrative"],
            asset_id=row["asset_id"], threat_actor=row["threat_actor"],
            technique=row["technique"], correlation_group_id=row["correlation_group_id"],
            p0=row["p0"], exposure_factor=row["exposure_factor"],
            expected_events_per_incident=row["expected_events_per_incident"],
            sle_low_multiplier=row["sle_low_multiplier"],
            sle_high_multiplier=row["sle_high_multiplier"],
            required_controls=sorted(req.get(code, [])),
            loss_components=comp_rows.get(code, []),
        )

    actions: dict[str, Action] = {}
    for row in conn.execute("SELECT * FROM actions"):
        actions[row["action_code"]] = Action(
            action_code=row["action_code"], name=row["name"],
            description=row["description"] or "", category=row["category"] or "other",
            cost=row["cost"], lead_time_days=row["lead_time_days"],
            capacity_group=row["capacity_group"],
            requires_actions=json.loads(row["requires_actions"] or "[]"),
            effect_type=row["effect_type"], effect=json.loads(row["effect_json"] or "{}"),
            synthetic=bool(row["synthetic"]),
        )

    return {"assets": assets, "findings": findings, "controls": controls,
            "scenarios": scenarios, "actions": actions}


# ---------------------------------------------------------------- effects
def vulnerability_multiplier(findings: Iterable[Finding]) -> float:
    """Open, exploitable findings raise the inherent probability.

    1 + 0.03 * sum(severity weights), capped at 3.0. This is a transparent,
    hand-auditable prior - NOT a learned model. See PRD 8.5.
    """
    total = 0.0
    for f in findings:
        if f.status != "open":
            continue
        weight = SEVERITY_WEIGHT.get(f.severity, 0.0)
        if f.exploitable:
            weight *= EXPLOITABLE_MULTIPLIER
        total += weight
    return min(3.0, 1.0 + 0.03 * total)


def _findings_for_scenario(findings: list[Finding], scenario: Scenario,
                           patched: set[str] | None, only_hints: bool) -> list[Finding]:
    out = []
    for f in findings:
        if f.asset_id != scenario.asset_id:
            continue
        if patched and f.external_finding_id in patched:
            continue
        if only_hints and f.scenario_hints:
            # Scoped actions only affect findings that name this scenario.
            hints = set(f.scenario_hints)
            if scenario.scenario_code not in hints and f.rule_id not in hints \
                    and f.external_finding_id not in hints:
                continue
        out.append(f)
    return out


def _component_value(component: LossComponent, asset: Asset | None,
                     overrides: dict[str, Any]) -> tuple[int, str | None]:
    """Return (amount_minor, incomplete_reason)."""
    override = overrides.get(component.component_code)
    basis = component.basis
    value = component.value
    hours = component.hours
    record_count = component.record_count

    if override:
        basis = override.get("basis", basis)
        if "value" in override:
            value = override["value"]
        if "hours" in override:
            hours = override["hours"]
        if "record_count" in override:
            record_count = override["record_count"]

    if basis == "fixed_amount":
        return int(value), None
    if basis == "daily_revenue_x_hours":
        if asset is None:
            return 0, "asset missing for daily-revenue loss component"
        if hours is None:
            return 0, f"loss component '{component.component_code}' has no hours set"
        if asset.daily_revenue <= 0:
            return 0, (f"asset {asset.asset_id} has no daily_revenue, required by "
                       f"'{component.component_code}'")
        return int(round(asset.daily_revenue * float(hours) / 24.0)), None
    if basis == "per_record":
        if record_count is None:
            return 0, f"loss component '{component.component_code}' has no record_count set"
        return int(value) * int(record_count), None
    return 0, f"unknown loss basis '{basis}'"


def _confidence_for_scenario(
    scenario: Scenario, controls: list[Control], components: list[dict[str, Any]],
    has_required_controls: bool, fresh_days: float | None, source_ages: dict[str, float | None],
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    scores: dict[str, float] = {}

    if not has_required_controls:
        scores["completeness"] = 0.0
        reasons.append("No required controls mapped - scenario is unmitigated by design")
    else:
        scores["completeness"] = 1.0

    if any(c.ce_source == "assumed" for c in controls):
        scores["evidence"] = 0.4
        reasons.append("At least one required control effectiveness is assumed, not measured")
    elif any(c.ce_source == "benchmark" for c in controls):
        scores["evidence"] = 0.75
        reasons.append("Control effectiveness partly benchmarked")
    elif not controls:
        scores["evidence"] = 0.4
        reasons.append("No control evidence available")
    else:
        scores["evidence"] = 1.0

    if fresh_days is None:
        scores["freshness"] = 0.5
        reasons.append("Finding data has no observation timestamp")
    elif fresh_days <= config.FRESH_DAYS_GREEN:
        scores["freshness"] = 1.0
    elif fresh_days <= config.FRESH_DAYS_AMBER:
        scores["freshness"] = 0.6
        reasons.append(f"Underlying finding data is {fresh_days:.0f} days old")
    else:
        scores["freshness"] = 0.25
        reasons.append(f"Underlying finding data is {fresh_days:.0f} days old (stale)")

    sourced = sum(1 for c in components if c.get("source_ref")
                  and c["source_ref"].strip().upper() != "ASSUMED")
    if not components:
        scores["provenance"] = 0.0
    else:
        scores["provenance"] = sourced / len(components)
        if scores["provenance"] < 1.0:
            reasons.append(f"{len(components) - sourced} of {len(components)} loss components "
                           "have no documented source")

    total = sum(CONFIDENCE_WEIGHTS[k] * scores.get(k, 0.0) for k in CONFIDENCE_WEIGHTS)
    return max(0, min(100, int(round(total * 100)))), reasons


def _band(value: int) -> str:
    if value >= 80:
        return "High"
    if value >= 55:
        return "Medium"
    return "Low"


# ---------------------------------------------------------------- aggregation
def aggregate_groups(results: list[ScenarioResult], rho_map: dict[str, float],
                     default_rho: float) -> tuple[int, int, int, dict[str, float]]:
    """Correlate scenarios sharing a group id. Returns (total, low, high, rho_used).

    EAL_g = (1 - rho) * sum(g) + rho * max(g)
    rho = 0 -> independent (plain sum); rho = 1 -> fully nested (largest only).
    """
    groups: dict[str | None, list[ScenarioResult]] = {}
    for r in results:
        groups.setdefault(r.group_id, []).append(r)

    total = low = high = 0
    rho_used: dict[str, float] = {}
    for gid, members in groups.items():
        if len(members) == 1:
            only = members[0]
            total += only.eal_minor
            low += only.eal_low_minor
            high += only.eal_high_minor
            if gid:
                rho_used[gid] = 0.0
            continue
        rho = rho_map.get(gid or "", default_rho)
        rho_used[gid or ""] = rho
        total += int(round((1 - rho) * sum(m.eal_minor for m in members)
                           + rho * max(m.eal_minor for m in members)))
        low += int(round((1 - rho) * sum(m.eal_low_minor for m in members)
                         + rho * max(m.eal_low_minor for m in members)))
        high += int(round((1 - rho) * sum(m.eal_high_minor for m in members)
                          + rho * max(m.eal_high_minor for m in members)))
    return total, low, high, rho_used


# ---------------------------------------------------------------- main entry
def assess(model: dict[str, Any], selected_actions: set[str] | None = None,
           rho_map: dict[str, float] | None = None,
           loss_overrides: dict[str, dict[str, Any]] | None = None,
           patched_finding_ids: set[str] | None = None,
           p0_overrides: dict[str, float] | None = None) -> Assessment:
    """Evaluate the model under a set of selected actions.

    selected_actions  action codes whose effects are applied
    loss_overrides    {scenario_code: {component_code: {basis|value|hours|record_count}}}
    patched_finding_ids finding ids treated as remediated
    p0_overrides      {scenario_code: baseline annual probability}
    """
    selected_actions = selected_actions or set()
    rho_map = rho_map or {}
    loss_overrides = loss_overrides or {}
    p0_overrides = p0_overrides or {}

    assets: dict[str, Asset] = model["assets"]
    findings: list[Finding] = model["findings"]
    controls: dict[str, Control] = model["controls"]
    scenarios: dict[str, Scenario] = model["scenarios"]
    actions: dict[str, Action] = model["actions"]

    # ---- resolve control CE after actions
    ce_overrides: dict[str, float] = {}
    for code in sorted(selected_actions):
        action = actions.get(code)
        if action is None:
            raise RiskError(f"unknown action '{code}'")
        if action.effect_type == "control_ce":
            for ccode, value in action.effect.get("set_ce", {}).items():
                current = ce_overrides.get(ccode)
                base = current if current is not None else (
                    controls[ccode].ce_score if ccode in controls else 0.0)
                ce_overrides[ccode] = max(base, float(value))

    # ---- patched findings from finding_filter actions
    patched = set(patched_finding_ids or set())
    for code in sorted(selected_actions):
        action = actions[code]
        if action.effect_type == "finding_filter":
            spec = action.effect
            patched.update(_match_filtered(findings, assets, spec, patched))

    # ---- source ages for freshness scoring
    source_ages: dict[str, float | None] = {}
    for src in sorted({f.source_system for f in findings}):
        observed = [f.observed_at for f in findings if f.source_system == src and f.observed_at]
        if observed:
            source_ages[src] = min((db.age_days(o) or 0.0) for o in observed)
        else:
            source_ages[src] = None
    fresh_days = min((v for v in source_ages.values() if v is not None), default=None)

    excluded = sum(1 for f in findings if f.match_method is None and f.status == "open")

    results: list[ScenarioResult] = []
    incomplete: list[dict[str, Any]] = []

    for code in sorted(scenarios):
        scenario = scenarios[code]
        asset = assets.get(scenario.asset_id)
        if asset is None:
            incomplete.append({"scenario_code": code,
                               "reasons": [f"asset {scenario.asset_id} not found"]})
            continue
        if asset.status != "active":
            incomplete.append({"scenario_code": code,
                               "reasons": [f"asset {asset.asset_id} is {asset.status}"]})
            continue

        ov = loss_overrides.get(code, {})

        # --- SLE
        breakdown: list[dict[str, Any]] = []
        sle = 0
        reasons: list[str] = []
        for component in scenario.loss_components:
            amount, why = _component_value(component, asset, ov)
            if why:
                reasons.append(why)
            sle += amount
            breakdown.append({
                "component_code": component.component_code,
                "basis": component.basis,
                "value_minor": component.value,
                "hours": component.hours,
                "record_count": component.record_count,
                "source_ref": component.source_ref,
                "amount_minor": amount,
                "unresolved": why,
            })
        if not scenario.loss_components:
            reasons.append("scenario has no loss components defined")
        if sle <= 0:
            reasons.append("single loss expectancy is zero")

        # --- probability
        only_hints = any(a.effect_type == "finding_filter" and a.effect.get("only_hints")
                         for a in (actions[c] for c in selected_actions if c in actions))
        scenario_findings = _findings_for_scenario(findings, scenario, patched, only_hints)
        vmul = vulnerability_multiplier(scenario_findings)

        p0 = float(p0_overrides.get(code, scenario.p0))
        if not 0 < p0 <= config.MAX_ANNUAL_PROBABILITY:
            raise RiskError(f"scenario {code}: p0 must be in (0, {config.MAX_ANNUAL_PROBABILITY}]")

        exposure = scenario.exposure_factor
        for a_code in selected_actions:
            a = actions[a_code]
            if a.effect_type == "exposure_factor" and a.effect.get("scenario_code") == code:
                exposure = float(a.effect["factor"])

        m = exposure * vmul
        p_in = 1.0 - math.pow(1.0 - p0, m)
        p_in = min(p_in, config.PROBABILITY_HARD_CAP)

        # --- controls
        required = [controls[c] for c in scenario.required_controls if c in controls]
        missing = [c for c in scenario.required_controls if c not in controls]
        if missing:
            reasons.append(f"required control(s) not defined: {', '.join(missing)}")
        mit_raw = 1.0
        control_detail: list[dict[str, Any]] = []
        for c in required:
            ce = max(0.0, min(0.99, ce_overrides.get(c.control_code, c.ce_score)))
            mit_raw *= (1.0 - ce)
            control_detail.append({
                "control_code": c.control_code, "name": c.name, "domain": c.domain,
                "ce_base": c.ce_score, "ce_applied": ce,
                "changed": c.control_code in ce_overrides,
                "ce_source": c.ce_source, "ce_evidence_ref": c.ce_evidence_ref,
                "framework_iso": c.framework_iso, "framework_nist": c.framework_nist,
                "framework_cis": c.framework_cis,
            })
        # Multiplying independent control effects assumes the controls fail
        # independently. In practice they share failure modes (same team, same
        # platform, same configuration drift), so the achievable reduction is
        # capped. Without this the model happily returns a 99% risk reduction,
        # which no control programme can deliver.
        mit = max(mit_raw, 1.0 - config.MAX_CONTROL_MITIGATION)
        cap_applied = mit_raw < mit
        p_res = p_in * mit

        lam = scenario.expected_events_per_incident
        eal = int(round(p_res * sle * lam))
        eal_low = int(round(eal * scenario.sle_low_multiplier * PROBABILITY_MULT_LOW))
        eal_high = int(round(eal * scenario.sle_high_multiplier * PROBABILITY_MULT_HIGH))

        conf, conf_reasons = _confidence_for_scenario(
            scenario, required, breakdown, bool(scenario.required_controls),
            fresh_days, source_ages)
        if cap_applied:
            conf_reasons.append(
                f"stacked control effectiveness implies a {1 - mit_raw:.1%} reduction, "
                f"capped at {config.MAX_CONTROL_MITIGATION:.0%} to allow for correlated "
                "control failure")
        if any(c.ce_source == "assumed" for c in required):
            conf = min(conf, 54)
            conf_reasons.append("Confidence capped at Medium because control effectiveness is assumed")
            conf_reasons = list(dict.fromkeys(conf_reasons))

        results.append(ScenarioResult(
            scenario_code=code, name=scenario.name, asset_id=asset.asset_id,
            business_unit=asset.business_unit, sle_minor=sle,
            sle_low_minor=int(round(sle * scenario.sle_low_multiplier)),
            sle_high_minor=int(round(sle * scenario.sle_high_multiplier)),
            p_inherent=p_in, mitigation_factor=mit, p_residual=p_res, lambda_=lam,
            eal_minor=eal, eal_low_minor=eal_low, eal_high_minor=eal_high,
            confidence=conf, confidence_band=_band(conf), confidence_reasons=conf_reasons,
            group_id=scenario.correlation_group_id, breakdown=breakdown,
            control_detail=control_detail, complete=not reasons,
            incomplete_reasons=reasons,
        ))
        if reasons:
            incomplete.append({"scenario_code": code, "name": scenario.name, "reasons": reasons})

    total, low, high, rho_used = aggregate_groups(
        results, rho_map, config.DEFAULT_CORRELATION_RHO)

    # Risk-driver decomposition: how much of EAL each scenario carries after
    # correlation adjustment. Groups are split pro-rata to keep the parts
    # summing to the headline number.
    by_asset: dict[str, int] = {}
    by_bu: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_actor: dict[str, int] = {}
    groups: dict[str | None, list[ScenarioResult]] = {}
    for r in results:
        groups.setdefault(r.group_id, []).append(r)
    for r in results:
        members = groups[r.group_id] or [r]
        if len(members) == 1:
            group_total = r.eal_minor
        else:
            rho = rho_used.get(r.group_id or "", config.DEFAULT_CORRELATION_RHO)
            group_total = int(round((1 - rho) * sum(m.eal_minor for m in members)
                                    + rho * max(m.eal_minor for m in members)))
        share = (r.eal_minor / sum(m.eal_minor for m in members)) if members else 0.0
        contribution = int(round(group_total * share))
        by_asset[r.asset_id] = by_asset.get(r.asset_id, 0) + contribution
        by_bu[r.business_unit] = by_bu.get(r.business_unit, 0) + contribution
        sc = scenarios[r.scenario_code]
        cat = (sc.technique or "unclassified").split(" ")[0].title()
        by_category[cat] = by_category.get(cat, 0) + contribution
        actor = sc.threat_actor or "Unknown actor"
        by_actor[actor] = by_actor.get(actor, 0) + contribution

    unadjusted = sum(r.eal_minor for r in results)
    low_sum = sum(r.eal_low_minor for r in results)
    high_sum = sum(r.eal_high_minor for r in results)

    if results:
        weight = sum(r.eal_minor for r in results) or 1
        confidence = int(round(sum(r.eal_minor * r.confidence for r in results) / weight))
    else:
        confidence = 0

    return Assessment(
        eal_minor=total, eal_low_minor=low, eal_high_minor=high,
        eal_unadjusted_minor=unadjusted, confidence=confidence,
        confidence_band=_band(confidence), scenarios=results,
        by_asset=by_asset, by_business_unit=by_bu, by_category=by_category,
        by_actor=by_actor, freshness=_freshness_block(conn_placeholder=None, model=model),
        incomplete=incomplete, currency=config.DEFAULT_CURRENCY, rho_used=rho_used,
        excluded_findings=excluded,
    )


def _match_filtered(findings: list[Finding], assets: dict[str, Asset],
                    spec: dict[str, Any], already: set[str]) -> set[str]:
    """Resolve a finding_filter action into a set of finding ids."""
    severities = set(spec.get("severity_in", []))
    min_cvss = spec.get("min_cvss")
    exposure_classes = set(spec.get("exposure_in", []))
    exploitable_only = bool(spec.get("exploitable_only", False))
    out: set[str] = set()
    for f in findings:
        if f.status != "open" or f.asset_id is None:
            continue
        if severities and f.severity not in severities:
            continue
        if min_cvss is not None:
            weight = SEVERITY_WEIGHT.get(f.severity, 0.0)
            if weight * 10 < float(min_cvss):
                continue
        if exposure_classes:
            asset = assets.get(f.asset_id)
            if asset is None or asset.exposure_class not in exposure_classes:
                continue
        if exploitable_only and not f.exploitable:
            continue
        out.add(f.external_finding_id)
    return out


def _freshness_block(conn_placeholder=None, model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Freshness summary. Built from findings' observed_at (model) plus dataset
    load times are attached by the API layer."""
    sources: dict[str, Any] = {}
    if model:
        by_source: dict[str, list[str]] = {}
        for f in model["findings"]:
            by_source.setdefault(f.source_system, []).append(f.observed_at or "")
        for src, stamps in by_source.items():
            valid = [s for s in stamps if s]
            if not valid:
                sources[src] = {"age_days": None, "band": "unknown"}
                continue
            age = min((db.age_days(s) or 0.0) for s in valid)
            sources[src] = {"age_days": age, "band": freshness_band(age),
                            "oldest_observed_at": max(valid)}
    return {"sources": sources, "thresholds": {
        "green_days": config.FRESH_DAYS_GREEN, "amber_days": config.FRESH_DAYS_AMBER}}


def freshness_band(age_days: float | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= config.FRESH_DAYS_GREEN:
        return "fresh"
    if age_days <= config.FRESH_DAYS_AMBER:
        return "aging"
    return "stale"
