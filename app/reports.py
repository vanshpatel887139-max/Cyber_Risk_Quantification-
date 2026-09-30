"""Report export (PRD 11): HTML board pack, CSV detail, Markdown summary.

Every exported artefact repeats the synthetic-data banner and the confidence
score. A number that leaves the platform must carry its own caveats.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from html import escape
from typing import Any

from . import ai, config, risk

SYNTHETIC_BANNER = (
    "SYNTHETIC DEMONSTRATION DATA. Every figure below is generated from an "
    "invented dataset for product evaluation. It is not a measurement of any "
    "real organisation and must not be used for a real decision."
)

ASSUMPTION_TEXT = (
    "This is a probabilistic estimate, not a forecast. Expected Annual Loss "
    "(EAL) is the probability weighted average cost of the modelled scenarios "
    "over 12 months. It excludes tail events outside the scenario set, and it "
    "depends on the loss assumptions and control effectiveness scores supplied "
    "to the platform."
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _money(minor: int) -> str:
    return f"{config.CURRENCY_SYMBOL} {minor / 100:,.0f}"


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _correlation_adjustment(assessment: risk.Assessment) -> float:
    """Share of the unadjusted sum removed by the correlation adjustment."""
    unadjusted = assessment.eal_unadjusted_minor
    if not unadjusted:
        return 0.0
    return 1.0 - (assessment.eal_minor / unadjusted)


def _freshness(assessment: risk.Assessment) -> str:
    sources = assessment.freshness.get("sources", {})
    if not sources:
        return "no source timestamps available"
    worst = max(sources.values(), key=lambda s: s.get("age_days") or 0)
    age = worst.get("age_days")
    return (f"oldest source is {age:.1f} days old ({worst.get('band', 'unknown')})"
            if age is not None else "unknown")


# ---------------------------------------------------------------- CSV
def scenarios_csv(assessment: risk.Assessment) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "scenario_code", "scenario_name", "asset_id", "business_unit",
        "correlation_group", "sle", "sle_low", "sle_high",
        "p_inherent_pct", "mitigation_pct", "p_residual_pct",
        "expected_events_per_incident", "eal", "eal_low", "eal_high",
        "confidence_score", "confidence_band", "e_role_pct", "data_sources",
    ])
    total = assessment.eal_unadjusted_minor or 1
    for s in sorted(assessment.scenarios, key=lambda x: -x.eal_minor):
        writer.writerow([
            s.scenario_code, s.name, s.asset_id, s.business_unit, s.group_id or "",
            f"{s.sle_minor / 100:.2f}", f"{s.sle_low_minor / 100:.2f}",
            f"{s.sle_high_minor / 100:.2f}",
            f"{s.p_inherent:.6f}", f"{s.mitigation_factor:.6f}",
            f"{s.p_residual:.6f}", f"{s.lambda_:.2f}",
            f"{s.eal_minor / 100:.2f}", f"{s.eal_low_minor / 100:.2f}",
            f"{s.eal_high_minor / 100:.2f}",
            s.confidence, s.confidence_band,
            f"{s.eal_minor / total * 100:.2f}",
            "; ".join(s.data_sources) if getattr(s, "data_sources", None) else "",
        ])
    return buf.getvalue()


def loss_components_csv(assessment: risk.Assessment) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["scenario_code", "component_code", "basis", "input_value",
                     "hours", "record_count", "amount", "source_reference"])
    for s in sorted(assessment.scenarios, key=lambda x: -x.eal_minor):
        for b in s.breakdown:
            writer.writerow([
                s.scenario_code, b["component_code"], b["basis"],
                f"{b['value_minor'] / 100:.2f}", b["hours"] or "", b["record_count"] or "",
                f"{b['amount_minor'] / 100:.2f}", b["source_ref"] or "",
            ])
    return buf.getvalue()


def actions_csv(plan: dict[str, Any] | None) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["action_code", "name", "selected", "category", "cost",
                     "lead_time_days", "marginal_reduction", "marginal_rosi",
                     "capacity_group", "requires_actions"])
    if not plan:
        return buf.getvalue()
    detail = {d["action_code"]: d for d in plan.get("selected_detail", [])}
    for candidate in plan.get("candidates", []):
        code = candidate["action_code"]
        d = detail.get(code, {})
        writer.writerow([
            code, candidate["name"],
            "yes" if code in plan["selected"] else "no",
            candidate.get("category", ""), f"{candidate['cost_minor'] / 100:.2f}",
            candidate.get("lead_time_days", ""),
            f"{(d.get('marginal_reduction_minor') or 0) / 100:.2f}",
            "" if d.get("marginal_rosi") is None else f"{d['marginal_rosi']:.3f}",
            candidate.get("capacity_group") or "",
            "; ".join(candidate.get("requires_actions") or []),
        ])
    return buf.getvalue()


# ---------------------------------------------------------------- Markdown
def summary_markdown(assessment: risk.Assessment,
                     plan: dict[str, Any] | None = None) -> str:
    total = assessment.eal_minor
    lines = [
        "# Cyber Risk Quantification - Executive Summary",
        "",
        f"_Generated {escape(_now())} by the risk engine. "
        f"Data freshness: {escape(_freshness(assessment))}._",
        "",
        f"> **{SYNTHETIC_BANNER}**",
        "",
        "## Headline",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Expected Annual Loss | **{_money(total)}** |",
        f"| Range (uncertainty) | {_money(assessment.eal_low_minor)} to "
        f"{_money(assessment.eal_high_minor)} |",
        f"| Unadjusted scenario sum | {_money(assessment.eal_unadjusted_minor)} |",
        f"| Scenarios modelled | {len(assessment.scenarios)} |",
        f"| Data confidence | {assessment.confidence_band} "
        f"({assessment.confidence}/100) |",
    ]
    if assessment.incomplete:
        lines.append(f"| Scenarios with unresolved assumptions | "
                     f"{len(assessment.incomplete)} |")
    if assessment.excluded_findings:
        lines.append(f"| Findings excluded (asset not matched) | "
                     f"{assessment.excluded_findings} |")

    lines += ["", "## Top exposures", "",
              "| # | Scenario | Asset | Business unit | EAL | Share | Confidence |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    unadjusted = assessment.eal_unadjusted_minor or 1
    for i, s in enumerate(sorted(assessment.scenarios, key=lambda x: -x.eal_minor)[:5], 1):
        lines.append(
            f"| {i} | {s.name} | {s.asset_id} | {s.business_unit} | "
            f"{_money(s.eal_minor)} | {s.eal_minor / unadjusted * 100:.1f}% | "
            f"{s.confidence_band} |")

    if plan:
        lines += [
            "", f"## Recommended plan within {_money(plan['budget_minor'])}", "",
            f"- Selected {len(plan['selected'])} action(s): "
            + (", ".join(plan["selected"]) or "none"),
            f"- Total cost: {_money(plan['cost_minor'])}",
            f"- EAL after plan: {_money(plan['plan_eal_minor'])} "
            f"({plan['reduction_pct']:.1f}% reduction)",
            f"- ROSI: {plan['rosi'] if plan['rosi'] is not None else 'n/a'}",
            f"- Optimiser: {plan['method']}"
            + ("" if plan.get("optimal") else " (best effort, not proven optimal)"),
        ]

    lines += ["", "## Basis of estimate", "", ASSUMPTION_TEXT, "",
              f"_Correlation adjustment applied with rho: "
              f"{', '.join(f'{g}={r}' for g, r in assessment.rho_used.items()) or 'default'}. "
              f"Currency {assessment.currency}._", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML
_STYLE = """
:root { --bg:#0e1420; --panel:#161f2e; --line:#26324a; --text:#e8edf5;
        --muted:#93a2bb; --accent:#4da3ff; --good:#3ecf8e; --warn:#ffb020;
        --bad:#ff6b6b; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
       font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:32px 24px 64px; }
h1 { font-size:26px; margin:0 0 4px; }
h2 { font-size:18px; margin:32px 0 12px; border-bottom:1px solid var(--line);
     padding-bottom:8px; }
.sub { color:var(--muted); margin:0 0 20px; }
.banner { background:#3a2410; border:1px solid #7a4a12; color:#ffd9a0;
          padding:12px 16px; border-radius:8px; font-size:14px; margin-bottom:24px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
        gap:14px; margin-bottom:8px; }
.kpi { background:var(--panel); border:1px solid var(--line); border-radius:10px;
       padding:16px 18px; }
.kpi .label { color:var(--muted); font-size:12px; text-transform:uppercase;
              letter-spacing:.06em; }
.kpi .value { font-size:26px; font-weight:650; margin-top:6px; }
.kpi .note { color:var(--muted); font-size:12px; margin-top:4px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--line);
        vertical-align:top; }
th { color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase;
     letter-spacing:.05em; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px;
        font-weight:600; }
.high { background:#4a1f1f; color:#ffb3b3; }
.medium { background:#4a3a12; color:#ffd98f; }
.low { background:#123a2a; color:#9ff0c9; }
.bar { height:8px; border-radius:4px; background:var(--line); overflow:hidden;
       min-width:80px; }
.bar > span { display:block; height:100%; background:var(--accent); }
footer { color:var(--muted); font-size:12px; margin-top:40px;
         border-top:1px solid var(--line); padding-top:16px; }
"""


def _band_pill(band: str) -> str:
    cls = {"High": "high", "Medium": "medium", "Low": "low"}.get(band, "medium")
    return f'<span class="pill {cls}">{escape(band)}</span>'


def html_report(assessment: risk.Assessment, plan: dict[str, Any] | None = None,
                answers: list[dict[str, Any]] | None = None) -> str:
    total = assessment.eal_minor or 1
    ranked = sorted(assessment.scenarios, key=lambda s: -s.eal_minor)
    max_eal = ranked[0].eal_minor if ranked else 1
    unadjusted = assessment.eal_unadjusted_minor or 1

    parts: list[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Cyber Risk Quantification - Board Summary</title>",
        f"<style>{_STYLE}</style></head><body><div class='wrap'>",
        "<h1>Cyber Risk Quantification</h1>",
        f"<p class='sub'>Board summary generated {_now()} &middot; "
        f"data confidence <strong>{escape(assessment.confidence_band)}</strong> "
        f"({assessment.confidence}/100) &middot; currency {assessment.currency}</p>",
        f"<div class='banner'><strong>Demonstration data.</strong> {SYNTHETIC_BANNER}</div>",
        "<div class='kpis'>",
        f"<div class='kpi'><div class='label'>Expected annual loss</div>"
        f"<div class='value'>{_money(assessment.eal_minor)}</div>"
        f"<div class='note'>{_money(assessment.eal_low_minor)} to "
        f"{_money(assessment.eal_high_minor)}</div></div>",
        f"<div class='kpi'><div class='label'>Scenarios modelled</div>"
        f"<div class='value'>{len(assessment.scenarios)}</div>"
        f"<div class='note'>{_pct(_correlation_adjustment(assessment))} "
        f"correlation adjustment</div></div>",
        f"<div class='kpi'><div class='label'>Largest single exposure</div>"
        f"<div class='value'>{_money(ranked[0].eal_minor) if ranked else 'n/a'}</div>"
        f"<div class='note'>{escape(ranked[0].scenario_code) if ranked else ''}</div></div>",
    ]
    if plan:
        parts.append(
            f"<div class='kpi'><div class='label'>EAL after recommended plan</div>"
            f"<div class='value'>{_money(plan['plan_eal_minor'])}</div>"
            f"<div class='note'>{plan['reduction_pct']:.1f}% lower for "
            f"{_money(plan['cost_minor'])}</div></div>")
    parts.append("</div>")

    parts.append("<h2>Scenarios ranked by expected annual loss</h2><table>"
                 "<tr><th>#</th><th>Scenario</th><th>Asset</th><th class='num'>SLE</th>"
                 "<th class='num'>P(residual)</th><th class='num'>EAL</th>"
                 "<th class='num'>Share</th><th>Confidence</th></tr>")
    for i, s in enumerate(ranked, 1):
        parts.append(
            f"<tr><td>{i}</td><td>{escape(s.name)}"
            f"<div class='sub' style='margin:2px 0 0'>{escape(s.scenario_code)} &middot; "
            f"{escape(s.business_unit)}</div></td>"
            f"<td>{escape(s.asset_id)}</td>"
            f"<td class='num'>{_money(s.sle_minor)}</td>"
            f"<td class='num'>{_pct(s.p_residual)}</td>"
            f"<td class='num'>{_money(s.eal_minor)}</td>"
            f"<td class='num'><div class='bar'><span style='width:"
            f"{min(100, s.eal_minor / max_eal * 100):.0f}%'></span></div>"
            f"{s.eal_minor / unadjusted * 100:.1f}%</td>"
            f"<td>{_band_pill(s.confidence_band)}</td></tr>")
    parts.append("</table>")

    if assessment.incomplete:
        parts.append("<h2>Scenarios with unresolved assumptions</h2><table>"
                     "<tr><th>Scenario</th><th>Reason</th></tr>")
        for item in assessment.incomplete:
            parts.append(f"<tr><td>{escape(str(item.get('scenario_code')))}</td>"
                         f"<td>{escape('; '.join(item.get('reasons', [])))}</td></tr>")
        parts.append("</table>")

    if plan:
        parts.append(f"<h2>Recommended plan within {_money(plan['budget_minor'])}</h2>")
        parts.append(
            f"<p class='sub'>{len(plan['selected'])} action(s) selected by the "
            f"{escape(plan['method'])} optimiser"
            f"{'' if plan.get('optimal') else ' (best effort, not proven optimal)'}. "
            f"Cost {_money(plan['cost_minor'])}; EAL falls from "
            f"{_money(plan['baseline_eal_minor'])} to {_money(plan['plan_eal_minor'])} "
            f"({plan['reduction_pct']:.1f}% reduction); ROSI "
            f"{plan['rosi'] if plan['rosi'] is not None else 'n/a'}.</p>")
        parts.append("<table><tr><th>Action</th><th class='num'>Cost</th>"
                     "<th class='num'>Marginal reduction</th>"
                     "<th class='num'>Marginal ROSI</th></tr>")
        for d in plan.get("selected_detail", []):
            parts.append(
                f"<tr><td>{escape(d['name'])}"
                f"<div class='sub' style='margin:2px 0 0'>{escape(d['action_code'])}</div></td>"
                f"<td class='num'>{_money(d['cost_minor'])}</td>"
                f"<td class='num'>{_money(d.get('marginal_reduction_minor') or 0)}</td>"
                f"<td class='num'>{'' if d.get('marginal_rosi') is None else format(d['marginal_rosi'], '.2f')}</td></tr>")
        parts.append("</table>")

    if answers:
        parts.append("<h2>Analyst Q&amp;A</h2>")
        for a in answers:
            parts.append(
                f"<div class='kpi' style='margin-bottom:10px'>"
                f"<div class='label'>{escape(a.get('question', ''))}</div>"
                f"<div>{escape(a.get('text', ''))}</div>"
                f"<div class='note'>source: {escape(a.get('source', ''))} &middot; "
                f"grounded: {'yes' if a.get('grounded') else 'no'}</div></div>")

    parts.append(
        f"<footer>{escape(ASSUMPTION_TEXT)}<br><br>"
        f"{escape(SYNTHETIC_BANNER)}</footer></div></body></html>")
    return "".join(parts)


def ai_context_json(assessment: risk.Assessment, model: dict[str, Any],
                    plan: dict[str, Any] | None = None) -> str:
    """The exact context the assistant is allowed to use, for audit."""
    import json
    return json.dumps(ai.build_context(assessment, model, plan), indent=2)
