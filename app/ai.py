"""Grounded AI decision support (PRD 8).

Hard rules, enforced in code, not in the prompt:
  1. The LLM never supplies a number. Every figure is computed by risk.py or
     optimize.py and passed in as a frozen context.
  2. Every numeric token in the model's answer must already appear in the
     context. Anything else is rejected and replaced by the deterministic
     template answer. The rejection is an audit event.
  3. If no LLM is configured, the deterministic answer is used and the response
     says so.
  4. Questions outside what the data supports get an explicit refusal, not a
     guess.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from . import config, risk

NUMBER_RE = re.compile(r"(?<![\w.])(\d[\d,]*\.?\d*)\s*(%|percent)?", re.IGNORECASE)
TOLERANCE = 0.005

# Questions the platform cannot answer with the data it holds. Returning a
# confident guess here is the single worst failure mode, so these are refused.
UNSUPPORTED_TOPICS = (
    ("forecast", "2027", "next year", "future risk", "predict", "prediction",
     "will we be attacked", "probability of being attacked next"),
    ("compliance certificate", "certif", "iso 27001 compliance", "are we compliant",
     "pass the audit", "regulatory fine", "penalt"),
    ("benchmark", "compared to industry", "peer average", "competitor"),
    ("breach prediction", "which asset will be breached", "who is the attacker"),
)


class UnsupportedQuestion(Exception):
    pass


@dataclass
class Answer:
    text: str
    source: str                       # llm | template
    grounded: bool
    rejected: bool = False
    refused: bool = False
    reject_reason: str | None = None
    citations: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    context_size: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source": self.source, "grounded": self.grounded,
                "rejected": self.rejected, "refused": self.refused,
                "reject_reason": self.reject_reason,
                "citations": self.citations, "warnings": self.warnings,
                "context_size": self.context_size}


# ---------------------------------------------------------------- context
def build_context(assessment: risk.Assessment, model: dict[str, Any],
                  optimiser_result: dict[str, Any] | None = None) -> dict[str, Any]:
    """The complete set of facts the assistant is allowed to speak about."""
    total = assessment.eal_minor
    ranked = sorted(assessment.scenarios, key=lambda s: -s.eal_minor)
    scenarios = []
    for rank, s in enumerate(ranked, start=1):
        driver = _dominant_driver(s)
        scenarios.append({
            "rank": rank,
            "scenario_code": s.scenario_code,
            "name": s.name,
            "asset_id": s.asset_id,
            "business_unit": s.business_unit,
            "e_role_pct": round(s.eal_minor / total * 100, 2) if total else 0.0,
            "eal": _money(s.eal_minor),
            "p_residual_pct": round(s.p_residual * 100, 3),
            "p_inherent_pct": round(s.p_inherent * 100, 3),
            "mitigation_factor_pct": round(s.mitigation_factor * 100, 2),
            "sle": _money(s.sle_minor),
            "confidence": s.confidence,
            "confidence_band": s.confidence_band,
            "group_id": s.group_id,
            "driver": driver,
            "controls": [{"name": c["name"], "ce_pct": round(c["ce_applied"] * 100, 1)}
                         for c in s.control_detail],
        })
    assets = []
    for asset_id, eal in sorted(assessment.by_asset.items(), key=lambda kv: -kv[1]):
        asset = model["assets"].get(asset_id)
        assets.append({
            "asset_id": asset_id,
            "name": asset.name if asset else asset_id,
            "business_unit": asset.business_unit if asset else "unknown",
            "business_service": asset.business_service if asset else None,
            "criticality": asset.criticality if asset else None,
            "eal": _money(eal),
            "e_role_pct": round(eal / total * 100, 2) if total else 0.0,
        })
    return {
        "generated_from": "deterministic risk engine",
        "currency": assessment.currency,
        "currency_symbol": config.CURRENCY_SYMBOL,
        "headline": {
            "eal": _money(assessment.eal_minor),
            "eal_low": _money(assessment.eal_low_minor),
            "eal_high": _money(assessment.eal_high_minor),
            "confidence": assessment.confidence,
            "confidence_band": assessment.confidence_band,
            "unadjusted_sum": _money(assessment.eal_unadjusted_minor),
            "scenario_count": len(assessment.scenarios),
            "incomplete_scenarios": len(assessment.incomplete),
            "excluded_findings": assessment.excluded_findings,
        },
        "scenarios": scenarios,
        "assets": assets,
        "by_business_unit": {k: _money(v) for k, v in
                             sorted(assessment.by_business_unit.items(), key=lambda kv: -kv[1])},
        "by_actor": {k: _money(v) for k, v in
                     sorted(assessment.by_actor.items(), key=lambda kv: -kv[1])},
        "optimisation": optimiser_result,
        "data_freshness": assessment.freshness,
    }


def _dominant_driver(s: risk.ScenarioResult) -> str:
    """Explain a scenario's EAL in plain terms, using only stored inputs."""
    reasons = []
    if s.control_detail:
        weakest = min(s.control_detail, key=lambda c: c["ce_applied"])
        reasons.append(f"weakest required control is {weakest['name']} at "
                       f"{weakest['ce_applied'] * 100:.0f}% effective")
    breaches = [b for b in s.breakdown if b["amount_minor"] > 0]
    if breaches:
        top = max(breaches, key=lambda b: b["amount_minor"])
        reasons.append(f"largest loss component is {top['component_code'].replace('_', ' ')}")
    if s.p_inherent > 0.05:
        reasons.append(f"inherent annual probability is {s.p_inherent * 100:.1f}%")
    if s.confidence < 55:
        reasons.append(f"confidence is {s.confidence_band} ({s.confidence}/100)")
    return "; ".join(reasons) or "no dominant single driver"


def _money(minor: int) -> str:
    """Format as a plain readable string. The LLM may echo this verbatim."""
    return f"{config.CURRENCY_SYMBOL} {minor / 100:,.2f}"


# ---------------------------------------------------------------- guard
def allowed_numbers(context: dict[str, Any]) -> set[float]:
    values: set[float] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            values.add(round(float(node), 6))
        elif isinstance(node, str):
            for match in NUMBER_RE.finditer(node):
                raw = match.group(1).replace(",", "")
                try:
                    values.add(round(float(raw), 6))
                except ValueError:
                    continue
                if match.group(2):
                    values.add(round(float(raw) * 100, 6))

    walk(context)
    # Percentages and ratios the narrative form may legitimately restate.
    for v in list(values):
        values.add(round(v * 100, 6))
        values.add(round(v / 100, 6))
    return values


def check_grounding(text: str, context: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (grounded, offending_tokens). Every number must exist upstream."""
    allowed = allowed_numbers(context)
    offenders: list[str] = []
    for match in NUMBER_RE.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            value = round(float(raw), 6)
        except ValueError:
            continue
        multiplier = 100.0 if match.group(2) else 1.0
        candidates = {value, round(value * multiplier, 6),
                      round(value / multiplier, 6) if multiplier else value}
        if not any(any(abs(c - a) <= TOLERANCE * max(1.0, abs(a))
                       for a in allowed) for c in candidates):
            offenders.append(match.group(0).strip())
    return (not offenders), offenders


# ---------------------------------------------------------------- templates
def _fmt_int(value: int) -> str:
    return f"{value:,}"


def template_answer(question: str, assessment: risk.Assessment, context: dict[str, Any],
                    optimiser_result: dict[str, Any] | None = None) -> str:
    """Deterministic narrative. Always available, even with no LLM configured."""
    q = question.lower()
    total = assessment.eal_minor
    sym = config.CURRENCY_SYMBOL
    ranked = sorted(assessment.scenarios, key=lambda s: -s.eal_minor)
    top = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None

    if optimiser_result:
        sel = ", ".join(optimiser_result["selected"]) or "no actions"
        return (
            f"At a budget of {sym}{optimiser_result['budget_minor'] / 100:,.0f}, the "
            f"optimiser selects {sel} (total cost "
            f"{sym}{optimiser_result['cost_minor'] / 100:,.0f}). Estimated annual loss falls "
            f"from {sym}{optimiser_result['baseline_eal_minor'] / 100:,.0f} to "
            f"{sym}{optimiser_result['plan_eal_minor'] / 100:,.0f}, a reduction of "
            f"{sym}{optimiser_result['reduction_minor'] / 100:,.0f} "
            f"({optimiser_result['reduction_pct']}%). Plan ROSI is "
            f"{optimiser_result['rosi']}."
        )

    if any(topic in q for topic in ("why", "driver", "reason", "because")) and top:
        parts = [f"'{top.name}' is the largest exposure at {sym}{top.eal_minor / 100:,.0f} "
                 f"per year."]
        if top.control_detail:
            weakest = min(top.control_detail, key=lambda c: c["ce_applied"])
            strongest = max(top.control_detail, key=lambda c: c["ce_applied"])
            parts.append(
                f"Its required controls range from {weakest['ce_applied'] * 100:.0f}% effective "
                f"({weakest['name']}) to {strongest['ce_applied'] * 100:.0f}% "
                f"({strongest['name']}), which leaves a residual annual probability of "
                f"{top.p_residual * 100:.2f}%.")
        breach = max((b for b in top.breakdown if b["amount_minor"] > 0),
                     key=lambda b: b["amount_minor"], default=None)
        if breach:
            parts.append(f"The largest loss component is {breach['component_code']} at "
                         f"{sym}{breach['amount_minor'] / 100:,.0f} of a single-event loss of "
                         f"{sym}{top.sle_minor / 100:,.0f}.")
        if top.confidence < 55:
            parts.append(f"Confidence in this figure is {top.confidence_band} "
                         f"({top.confidence}/100), so treat it as indicative.")
        return " ".join(parts)

    if any(topic in q for topic in ("second", "runner", "next largest", "2nd")) and second:
        return (f"After '{top.name if top else 'n/a'}', the next largest exposure is "
                f"'{second.name}' on asset {second.asset_id} at "
                f"{sym}{second.eal_minor / 100:,.0f} per year "
                f"({second.eal_minor / total * 100:.1f}% of total exposure). "
                f"{_dominant_driver(second).capitalize()}.")

    if any(topic in q for topic in ("total", "exposure", "how much", "overall", "summary")):
        return (f"Estimated expected annual loss is {sym}{total / 100:,.0f} "
                f"(range {sym}{assessment.eal_low_minor / 100:,.0f} to "
                f"{sym}{assessment.eal_high_minor / 100:,.0f}) across "
                f"{len(assessment.scenarios)} scenarios. Overall data confidence is "
                f"{assessment.confidence_band} ({assessment.confidence}/100). "
                f"Before correlation adjustment the unadjusted sum is "
                f"{sym}{assessment.eal_unadjusted_minor / 100:,.0f}.")

    if any(topic in q for topic in ("asset", "which system", "infrastructure")) \
            and assessment.by_asset:
        worst_asset_id, worst_eal = max(assessment.by_asset.items(), key=lambda kv: kv[1])
        known = {a["asset_id"]: a for a in context.get("assets", [])}
        asset = known.get(worst_asset_id)
        return (f"The largest asset-level exposure is {worst_asset_id}"
                + (f" ({asset['name']}, {asset['business_unit']})" if asset else "")
                + f" at {sym}{worst_eal / 100:,.0f} per year.")

    if any(topic in q for topic in ("scenario", "largest", "top", "biggest", "worst")) and top:
        return (f"The largest single scenario is '{top.name}' ({top.scenario_code}) on "
                f"{top.asset_id} "
                f"({top.business_unit}) at {sym}{top.eal_minor / 100:,.0f} per year, "
                f"{top.eal_minor / total * 100:.1f}% of the total. "
                f"Residual annual probability {top.p_residual * 100:.2f}%, single-event loss "
                f"{sym}{top.sle_minor / 100:,.0f}.")

    if any(topic in q for topic in ("confiden", "trust", "reliab", "quality",
                                    "assumption", "accurate")):
        return (f"Overall data confidence is {assessment.confidence_band} "
                f"({assessment.confidence}/100). "
                + (f"{len(assessment.incomplete)} scenario(s) have unresolved assumptions. "
                   if assessment.incomplete else "All scenarios have complete loss assumptions. ")
                + (f"{assessment.excluded_findings} finding(s) were excluded because they could "
                   "not be matched to an asset. " if assessment.excluded_findings else ""))

    # Default: summarise what the platform does know, in ranked order.
    lines = [f"Estimated expected annual loss is {sym}{total / 100:,.0f} per year across "
             f"{len(assessment.scenarios)} scenarios. Top contributors:"]
    for rank, s in enumerate(ranked[:3], start=1):
        lines.append(f"  {rank}. {s.name} ({s.asset_id}) - {sym}{s.eal_minor / 100:,.0f} "
                     f"({s.eal_minor / total * 100:.1f}%)")
    lines.append("Ask about a specific scenario, asset, business unit, driver or budget "
                 "allocation for a focused answer.")
    return "\n".join(lines)


def refusal(assessment: risk.Assessment) -> str:
    sym = config.CURRENCY_SYMBOL
    return (
        "I cannot answer that with the data this platform holds. The prototype stores asset "
        "inventory, security findings, control effectiveness, loss assumptions and risk "
        "scenarios - it does not store incident history, threat forecasts, compliance "
        "evidence or industry benchmarks, so any answer to that question would be invented.\n\n"
        f"What I can answer from real data: total exposure of "
        f"{sym}{assessment.eal_minor / 100:,.0f} per year, which scenarios or assets drive "
        f"it, how a mitigation changes it, and which actions fit a given budget."
    )


# ---------------------------------------------------------------- LLM
def _call_llm(question: str, context: dict[str, Any]) -> str:
    system = (
        "You are the analyst assistant inside a cyber risk quantification tool.\n"
        "STRICT RULES:\n"
        "1. Use ONLY the JSON context provided. It is the complete set of facts.\n"
        "2. Never invent, estimate, round differently, or derive a number that is not in the "
        "context. Copy numbers verbatim, character for character.\n"
        "3. Never state a probability, loss, control effectiveness, ROSI or total that is not "
        "present in the context.\n"
        "4. If the context does not contain the answer, say so plainly and name what is "
        "missing.\n"
        "5. Answer in 3 to 6 sentences. Plain text, no markdown, no bullet symbols.\n"
        "6. Always note that figures are estimates, not guarantees."
    )
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"CONTEXT:\n{json.dumps(context, indent=2)}\n\n"
                                         f"QUESTION: {question}"},
        ],
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        f"{config.LLM_BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.LLM_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT) as resp:
        body = json.loads(resp.read().decode())
    return body["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------- entry point
def ask(question: str, assessment: risk.Assessment, model: dict[str, Any],
        optimiser_result: dict[str, Any] | None = None,
        conn=None) -> Answer:
    question = (question or "").strip()
    if not question:
        return Answer("Ask a question about the risk data.", "template", True,
                      warnings=["Empty question"])

    context = build_context(assessment, model, optimiser_result)
    size = len(json.dumps(context))

    lowered = question.lower()
    if any(topic in lowered for group in UNSUPPORTED_TOPICS for topic in group):
        text = refusal(assessment)
        _audit(conn, "ai.refused", {"question": question}, severity="warning")
        return Answer(text, "template", True, refused=True, context_size=size,
                      warnings=["Question outside supported scope"])

    fallback = template_answer(question, assessment, context, optimiser_result)

    if not (config.LLM_ENABLED and config.LLM_API_KEY):
        _audit(conn, "ai.answered", {"question": question, "source": "template"})
        return Answer(fallback, "template", True, context_size=size,
                      warnings=["AI narrative disabled (CRP_LLM_ENABLED=0). "
                                "Showing the deterministic generated summary."])

    try:
        text = _call_llm(question, context)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
        _audit(conn, "ai.unavailable", {"error": str(exc)}, severity="warning")
        return Answer(fallback, "template", True, context_size=size,
                      warnings=[f"AI service unavailable ({type(exc).__name__}). "
                                "Showing the deterministic generated summary."])

    grounded, offenders = check_grounding(text, context)
    if not grounded:
        _audit(conn, "ai.rejected_ungrounded",
               {"question": question, "offending_tokens": offenders},
               severity="alert")
        return Answer(fallback, "template", True, rejected=True,
                      reject_reason="The assistant produced a figure that is not present in "
                                    "the underlying data. That answer was discarded and the "
                                    "generated summary is shown instead.",
                      context_size=size,
                      warnings=[f"Numeric grounding guard blocked: {', '.join(offenders[:5])}"])

    _audit(conn, "ai.answered", {"question": question, "source": "llm"})
    return Answer(text, "llm", True, context_size=size)


def _audit(conn, action: str, detail: dict[str, Any], severity: str = "info") -> None:
    if conn is None:
        return
    from . import db
    db.audit(conn, action, entity="ai", detail=detail, severity=severity)
