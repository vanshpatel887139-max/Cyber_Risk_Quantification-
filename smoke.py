"""End-to-end smoke test against a running server (not a unit test).

Usage:
    python3 smoke.py [base_url]     # default http://127.0.0.1:8137
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8137"
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
FAILURES: list[str] = []


def call(path, data=None, method=None, expect=200):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=30) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode()
    if status != expect:
        FAILURES.append(f"{path} -> {status} (expected {expect})")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)


health = call("/api/health")
check("health", health.get("status") == "ok", f"currency={health.get('currency')}")
check("llm disabled by default", health.get("llm") is False)

check("unauthenticated request rejected",
      call("/api/overview", expect=401) is not None)

call("/api/login", {"username": "admin", "password": "admin123"})
me = call("/api/me")
check("login", me.get("username") == "admin", f"role={me.get('role')}")

check("bad password rejected",
      call("/api/login", {"username": "admin", "password": "wrong"}, expect=401) is not None)

call("/api/login", {"username": "admin", "password": "admin123"})
overview = call("/api/overview")
counts = overview.get("counts", {})
check("overview counts", counts.get("assets", 0) > 0, json.dumps(counts))
check("synthetic share reported", overview.get("synthetic_asset_share") == 1.0)

assessment = call("/api/assessment")["assessment"]
eal = assessment["eal_minor"]
check("assessment eal positive", eal > 0, f"₹{eal / 100:,.0f}")
check("uncertainty band brackets eal",
      assessment["eal_low_minor"] <= eal <= assessment["eal_high_minor"],
      f"₹{assessment['eal_low_minor'] / 100:,.0f}–₹{assessment['eal_high_minor'] / 100:,.0f}")
check("confidence reported", 0 < assessment["confidence"] <= 100,
      f"{assessment['confidence_band']} ({assessment['confidence']}/100)")

plan = call("/api/optimise", {"budget_minor": 250_000_000, "max_actions": 5})["plan"]
check("plan within budget", plan["cost_minor"] <= 250_000_000,
      f"cost ₹{plan['cost_minor'] / 100:,.0f}, selected {plan['selected']}")
check("plan reduces risk", plan["plan_eal_minor"] < plan["baseline_eal_minor"],
      f"{plan['reduction_pct']:.1f}% reduction, ROSI {plan['rosi']}")
check("exact search reported optimal", plan["optimal"] is True)

frontier = call("/api/optimise/frontier?budget_max=400000000&steps=5")["frontier"]
eals = [p["plan_eal_minor"] for p in frontier]
check("frontier monotonic", eals == sorted(eals, reverse=True), f"{len(frontier)} points")

bumped = call("/api/scenarios/S1/whatif", {"p0": 0.2})["assessment"]
check("what-if raises exposure", bumped["eal_minor"] > eal,
      f"₹{eal / 100:,.0f} → ₹{bumped['eal_minor'] / 100:,.0f}")
check("unknown scenario 404s", call("/api/scenarios/NOPE/whatif", {"p0": 0.1}, expect=404) is not None)
check("out-of-range p0 rejected", call("/api/scenarios/S1/whatif", {"p0": 9}, expect=422) is not None)

answer = call("/api/ask", {"question": "What is our total expected annual loss?"})
check("ai answers in-scope question", not answer.get("refused") and answer.get("text"))
check("ai answer is grounded", answer.get("grounded") is True, f"source={answer.get('source')}")

refusal = call("/api/ask", {"question": "Will we be attacked next year?"})
check("ai refuses out-of-scope question", refusal.get("refused") is True)

md = call("/api/report/summary.md")
check("markdown report has synthetic banner", "SYNTHETIC" in md.upper())
csv_text = call("/api/report/scenarios.csv")
check("csv report has scenarios", "scenario_code" in csv_text and "S1" in csv_text)
html = call("/api/report/board.html?budget_minor=250000000")
check("html board report renders", "<!doctype html>" in html.lower() and "SYNTHETIC" in html.upper())
actions_csv = call("/api/report/actions.csv?budget_minor=250000000")
check("actions csv lists the plan", "action_code" in actions_csv)

audit = call("/api/audit?limit=20")
actions_logged = {e["action"] for e in audit.get("events", [])}
check("ai interactions audited", "ai.answered" in actions_logged, ", ".join(sorted(actions_logged)))

reset = call("/api/demo/reset?refresh=false", method="POST")
check("demo reset restores D0", reset.get("variant") == "D0",
      f"variant={reset.get('variant')}, counts={json.dumps(reset.get('counts', {}))}")

index = call("/")
check("dashboard html served", "<!doctype html>" in index.lower() and "kpi" in index.lower())
check("dashboard script served", call("/static/app.js") != "")
check("dashboard stylesheet served", call("/static/styles.css") != "")

reset_30 = call("/api/demo/reset?refresh=true", method="POST")
check("demo reset restores D+30", reset_30.get("variant") == "D+30",
      f"findings={reset_30.get('counts', {}).get('findings')}")
call("/api/demo/reset?refresh=false", method="POST")
check("restored back to D0", call("/api/assessment")["assessment"]["confidence"] > 0)

print()
if FAILURES:
    print(f"{len(FAILURES)} CHECK(S) FAILED:")
    for failure in FAILURES:
        print(f"  - {failure}")
    sys.exit(1)
print("ALL SMOKE CHECKS PASSED")
