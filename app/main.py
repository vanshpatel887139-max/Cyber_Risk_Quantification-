"""FastAPI application (PRD 10). Thin HTTP layer: every number is computed by
risk.py / optimize.py / ai.py, never here."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai, config, db, demo_data, ingest, optimize, reports, risk

app = FastAPI(title="Cyber Risk Quantification Platform", version="0.1.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json")

STATIC_DIR = config.BASE_DIR / "app" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ------------------------------------------------------------------ startup
@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with db.connect() as conn:
        if db.table_count(conn, "assets") == 0:
            demo_data.seed(conn)


# ------------------------------------------------------------------ auth
def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(config.SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Sign in required")
    with db.connect() as conn:
        row = db.user_for_token(conn, token)
    if row is None:
        raise HTTPException(401, "Session expired or invalid")
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


def requires(capability: str):
    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if not db.has_capability(user["role"], capability):
            raise HTTPException(
                403, f"Role '{user['role']}' is not permitted to perform '{capability}'")
        return user

    return dependency


# ------------------------------------------------------------------ models
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class ScenarioOverride(BaseModel):
    p0: float | None = Field(default=None, gt=0, le=1)
    loss_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)


class OptimiseRequest(BaseModel):
    budget_minor: int = Field(gt=0)
    max_actions: int = Field(default=config.DEFAULT_CAPACITY_MAX_ACTIONS, ge=1, le=50)
    preselected: list[str] = Field(default_factory=list)
    exact: bool = True


# ------------------------------------------------------------------ pages
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html")
    if not html.exists():
        return HTMLResponse("<h1>UI not built</h1>", status_code=500)
    return HTMLResponse(html.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ session
@app.post("/api/login")
def login(body: LoginRequest) -> JSONResponse:
    with db.connect() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (body.username.strip(),)).fetchone()
        if user is None or not db.verify_password(body.password, user["password_hash"]):
            db.audit(conn, "auth.failed", entity="user",
                     detail={"username": body.username}, severity="warning")
            raise HTTPException(401, "Invalid username or password")
        token, _ = db.create_session(conn, user["id"])
        db.audit(conn, "auth.login", entity="user", username=user["username"],
                 role=user["role"])
        response = JSONResponse({"username": user["username"], "role": user["role"],
                                 "capabilities": sorted(config.CAPABILITIES[user["role"]])})
        response.set_cookie(config.SESSION_COOKIE, token, httponly=True, samesite="lax",
                            max_age=config.SESSION_TTL_SECONDS)
        return response


@app.post("/api/logout")
def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(config.SESSION_COOKIE)
    if token:
        with db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response = JSONResponse({"ok": True})
    response.delete_cookie(config.SESSION_COOKIE)
    return response


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"username": user["username"], "role": user["role"],
            "capabilities": sorted(config.CAPABILITIES.get(user["role"], set()))}


# ------------------------------------------------------------------ data
@app.get("/api/overview")
def overview(user: dict[str, Any] = Depends(requires("view"))) -> dict[str, Any]:
    with db.connect() as conn:
        counts = {t: db.table_count(conn, t) for t in
                  ("assets", "findings", "controls", "scenarios", "actions",
                   "datasets", "quarantine")}
        recent = [dict(r) for r in conn.execute(
            """SELECT id, dataset_type, filename, status, rows_total, rows_ok,
                      rows_updated, rows_quarantined, loaded_at, synthetic
               FROM datasets ORDER BY id DESC LIMIT 10""")]
        synthetic = conn.execute(
            "SELECT COUNT(*) FROM assets WHERE synthetic = 1").fetchone()[0]
        total_assets = counts["assets"] or 1
        dataset_json = {}
        for r in conn.execute("SELECT dataset_type, errors_json FROM datasets "
                              "WHERE status = 'committed' ORDER BY id DESC LIMIT 1"):
            dataset_json[r["dataset_type"]] = json.loads(r["errors_json"] or "[]")
    return {"counts": counts, "recent_datasets": recent,
            "synthetic_asset_share": round(synthetic / total_assets, 3),
            "latest_dataset_issues": dataset_json}


@app.post("/api/ingest")
async def upload(
    dataset_type: str = Form(...),
    commit: bool = Form(True),
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(requires("data.write")),
) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds {config.MAX_UPLOAD_BYTES} bytes")
    try:
        with db.connect() as conn:
            result = ingest.ingest(conn, dataset_type, file.filename or "upload.csv", raw,
                                   commit=commit, actor=user)
        return result.as_dict()
    except ingest.IngestError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/quarantine")
def quarantine(limit: int = 200,
               user: dict[str, Any] = Depends(requires("view"))) -> dict[str, Any]:
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT q.id, q.dataset_id, q.row_number, q.reason, q.payload_json,
                      d.dataset_type, d.filename
               FROM quarantine q JOIN datasets d ON d.id = q.dataset_id
               ORDER BY q.id DESC LIMIT ?""", (min(limit, 1000),))]
    for r in rows:
        try:
            r["payload"] = json.loads(r.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            r["payload"] = {}
    return {"count": len(rows), "rows": rows}


@app.get("/api/catalog")
def catalog(user: dict[str, Any] = Depends(requires("view"))) -> dict[str, Any]:
    with db.connect() as conn:
        model = risk.load_model(conn)
    return {
        "assets": [
            {"asset_id": a.asset_id, "name": a.name, "business_unit": a.business_unit,
             "business_service": a.business_service, "criticality": a.criticality,
             "exposure_class": a.exposure_class, "status": a.status,
             "daily_revenue_minor": a.daily_revenue}
            for a in model["assets"].values()],
        "controls": [
            {"control_code": c.control_code, "name": c.name, "domain": c.domain,
             "ce_score": c.ce_score, "ce_source": c.ce_source,
             "ce_evidence_ref": c.ce_evidence_ref, "framework_iso": c.framework_iso,
             "framework_nist": c.framework_nist, "framework_cis": c.framework_cis}
            for c in model["controls"].values()],
        "scenarios": [
            {"scenario_code": s.scenario_code, "name": s.name, "asset_id": s.asset_id,
             "p0": s.p0, "correlation_group_id": s.correlation_group_id,
             "required_controls": s.required_controls}
            for s in model["scenarios"].values()],
        "actions": [
            {"action_code": a.action_code, "name": a.name, "category": a.category,
             "cost_minor": a.cost, "lead_time_days": a.lead_time_days,
             "capacity_group": a.capacity_group, "requires_actions": a.requires_actions,
             "effect_type": a.effect_type, "effect": a.effect, "description": a.description}
            for a in model["actions"].values()],
        "findings_summary": _finding_summary(model),
    }


def _finding_summary(model: dict[str, Any]) -> dict[str, Any]:
    by_sev: dict[str, int] = {}
    open_count = exploitable = unmatched = 0
    for f in model["findings"]:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
        if f.status == "open":
            open_count += 1
            if f.exploitable:
                exploitable += 1
            if f.match_method is None:
                unmatched += 1
    return {"total": len(model["findings"]), "open": open_count,
            "open_exploitable": exploitable, "unmatched": unmatched,
            "by_severity": by_sev}


@app.post("/api/demo/reset")
def demo_reset(refresh: bool = False,
               user: dict[str, Any] = Depends(requires("data.write"))) -> dict[str, Any]:
    """Reload the synthetic dataset. refresh=True loads the D+30 variant."""
    with db.connect() as conn:
        counts = demo_data.seed(conn, refresh=refresh)
        db.audit(conn, "demo.reset", entity="synthetic_bundle",
                 detail={"refresh": refresh, "counts": counts},
                 username=user["username"], role=user["role"])
        model = risk.load_model(conn)
        assessment = risk.assess(model)
    return {"counts": counts, "variant": "D+30" if refresh else "D0",
            "assessment": assessment.as_dict()}


# ------------------------------------------------------------------ assessment
def _assess(params: dict[str, Any], p0_overrides: dict[str, float] | None = None,
            loss_overrides: dict[str, Any] | None = None,
            selected: set[str] | None = None) -> dict[str, Any]:
    with db.connect() as conn:
        model = risk.load_model(conn)
        try:
            assessment = risk.assess(
                model, selected_actions=selected or set(),
                rho_map=params.get("rho_map") or {},
                loss_overrides=loss_overrides or {},
                p0_overrides=p0_overrides or {})
        except risk.RiskError as exc:
            raise HTTPException(400, str(exc)) from exc
        db.audit(conn, "assessment.run", entity="portfolio",
                 detail={"selected": sorted(selected or set()),
                         "p0_overrides": p0_overrides or {},
                         "eal_minor": assessment.eal_minor},
                 username=params.get("username"), role=params.get("role"))
    return {"assessment": assessment.as_dict()}


@app.get("/api/assessment")
def assessment_endpoint(rho: str | None = None,
                        actions: str | None = None,
                        user: dict[str, Any] = Depends(requires("assessment.run"))) -> dict[str, Any]:
    rho_map = _parse_rho(rho)
    selected = {a.strip() for a in (actions or "").split(",") if a.strip()}
    return _assess({**user}, None, None, selected)


def _parse_rho(raw: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in (raw or "").split(","):
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        try:
            out[key.strip()] = max(0.0, min(1.0, float(value)))
        except ValueError:
            continue
    return out


@app.post("/api/scenarios/{code}/whatif")
def what_if(code: str, body: ScenarioOverride,
            user: dict[str, Any] = Depends(requires("assessment.run"))) -> dict[str, Any]:
    with db.connect() as conn:
        known = conn.execute(
            "SELECT 1 FROM scenarios WHERE scenario_code = ?", (code,)).fetchone()
    if known is None:
        raise HTTPException(404, f"Unknown scenario '{code}'")
    p0 = {code: body.p0} if body.p0 is not None else None
    return _assess(user, p0, body.loss_overrides)


@app.post("/api/optimise")
def optimise_endpoint(body: OptimiseRequest,
                      user: dict[str, Any] = Depends(requires("optimiser.run"))) -> dict[str, Any]:
    with db.connect() as conn:
        model = risk.load_model(conn)
        try:
            plan = optimize.optimise(model, body.budget_minor, body.max_actions,
                                     preselected=set(body.preselected), exact=body.exact)
        except risk.RiskError as exc:
            raise HTTPException(400, str(exc)) from exc
        db.audit(conn, "optimiser.run", entity="portfolio",
                 detail={"budget_minor": body.budget_minor, "selected": plan.selected,
                         "optimal": plan.optimal, "reduction_pct": round(plan.reduction_pct, 2)},
                 username=user["username"], role=user["role"])
    return {"plan": plan.as_dict()}


@app.get("/api/optimise/frontier")
def frontier(budget_max: int | None = None, steps: int = 10,
             user: dict[str, Any] = Depends(requires("optimiser.run"))) -> dict[str, Any]:
    with db.connect() as conn:
        model = risk.load_model(conn)
    top = budget_max or max((a.cost for a in model["actions"].values()), default=0) * 3
    points = optimize.frontier(model, top, config.DEFAULT_CAPACITY_MAX_ACTIONS, steps=steps)
    return {"frontier": points, "currency": config.DEFAULT_CURRENCY,
            "symbol": config.CURRENCY_SYMBOL}


# ------------------------------------------------------------------ AI
@app.post("/api/ask")
def ask(body: AskRequest, user: dict[str, Any] = Depends(requires("ai.ask"))) -> dict[str, Any]:
    with db.connect() as conn:
        model = risk.load_model(conn)
        assessment = risk.assess(model)
        answer = ai.ask(body.question, assessment, model, conn=conn)
    return {"question": body.question, **answer.as_dict()}


@app.get("/api/ai/status")
def ai_status(user: dict[str, Any] = Depends(requires("view"))) -> dict[str, Any]:
    return {"llm_enabled": config.LLM_ENABLED and bool(config.LLM_API_KEY),
            "model": config.LLM_MODEL if config.LLM_ENABLED else None,
            "mode": "grounded-llm" if (config.LLM_ENABLED and config.LLM_API_KEY)
                    else "deterministic-template",
            "guarantees": [
                "the model never supplies a number",
                "every numeric token in an answer must already exist in the "
                "computed context or the answer is discarded",
                "questions about forecasts, compliance certification or industry "
                "benchmarks are refused because the platform holds no such data",
            ]}


# ------------------------------------------------------------------ reports
@app.get("/api/report/summary.md", response_class=PlainTextResponse)
def report_markdown(user: dict[str, Any] = Depends(requires("report.export"))) -> str:
    with db.connect() as conn:
        model = risk.load_model(conn)
        assessment = risk.assess(model)
    return reports.summary_markdown(assessment)


@app.get("/api/report/scenarios.csv", response_class=PlainTextResponse)
def report_csv(user: dict[str, Any] = Depends(requires("report.export"))) -> str:
    with db.connect() as conn:
        model = risk.load_model(conn)
        assessment = risk.assess(model)
    return reports.scenarios_csv(assessment)


@app.get("/api/report/actions.csv", response_class=PlainTextResponse)
def report_actions_csv(budget_minor: int | None = None,
                       user: dict[str, Any] = Depends(requires("report.export"))) -> str:
    with db.connect() as conn:
        model = risk.load_model(conn)
    plan = None
    if budget_minor:
        try:
            plan = optimize.optimise(model, budget_minor,
                                     config.DEFAULT_CAPACITY_MAX_ACTIONS).as_dict()
        except risk.RiskError:
            plan = None
    return reports.actions_csv(plan)


@app.get("/api/report/board.html", response_class=HTMLResponse)
def report_html(budget_minor: int | None = None,
                user: dict[str, Any] = Depends(requires("report.export"))) -> str:
    with db.connect() as conn:
        model = risk.load_model(conn)
        assessment = risk.assess(model)
    plan = None
    if budget_minor:
        try:
            plan = optimize.optimise(model, budget_minor,
                                     config.DEFAULT_CAPACITY_MAX_ACTIONS).as_dict()
        except risk.RiskError:
            plan = None
    return reports.html_report(assessment, plan)


# ------------------------------------------------------------------ audit
@app.get("/api/audit")
def audit_log(limit: int = 100,
              user: dict[str, Any] = Depends(requires("audit.read"))) -> dict[str, Any]:
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT id, ts, username, role, action, entity, detail_json, severity
               FROM audit_events ORDER BY id DESC LIMIT ?""", (min(limit, 1000),))]
    for r in rows:
        try:
            r["detail"] = json.loads(r.pop("detail_json") or "{}")
        except json.JSONDecodeError:
            r["detail"] = {}
    return {"count": len(rows), "events": rows}


@app.get("/api/health")
def health() -> Response:
    with db.connect() as conn:
        counts = {t: db.table_count(conn, t) for t in ("assets", "scenarios", "actions")}
    return JSONResponse({"status": "ok", "currency": config.DEFAULT_CURRENCY,
                         "llm": config.LLM_ENABLED, "counts": counts})
