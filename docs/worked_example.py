"""Worked example generator for TECHNICAL_ARCHITECTURE.md sections F and G.
Run: python3 docs/worked_example.py
Every figure quoted in the TAD is emitted by this script from the live engine.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.risk import (assess, Asset, Finding, Control, Scenario, LossComponent, Action)
from app.optimize import optimise, frontier

M = 100
def rs(x): return int(round(x * M))
def r(m): return f"Rs {m/M:,.0f}"

A1 = Asset("A-1", "Payments Platform", "application", "Retail Banking", "Payments",
           5, rs(6_000_000), "internet_facing", "active", ip="10.20.0.11",
           hostname="pay-prod-01", source_system="cmdb", synthetic=True,
           observed_at="2026-09-28")
A2 = Asset("A-2", "Core Ledger", "database", "Retail Banking", "Core Banking",
           5, rs(2_000_000), "internal", "active", ip="10.20.0.12",
           hostname="ledger-prod-01", source_system="cmdb", synthetic=True,
           observed_at="2026-09-28")

def F(fid, asset, sev, ex, hints, obs="2026-09-28"):
    return Finding(fid, "scanner", asset, "R-"+fid, "demo finding", sev, ex,
                   "open", [hints], "exact", obs)

findings = [
    F("F-001","A-1","critical",True,"S-1"),
    F("F-002","A-1","high",True,"S-1"),
    F("F-003","A-1","medium",False,"S-1"),
    F("F-004","A-2","high",False,"S-2"),
    F("F-005","A-2","medium",False,"S-2"),
    F("F-006","A-1","low",False,"S-1","2026-09-20"),
]

controls = {
 "CTL-BK":  Control("CTL-BK","Immutable offline backups","resilience",0.55,"measured","BA-2026-014"),
 "CTL-EDR": Control("CTL-EDR","EDR with tamper protection","detection",0.50,"measured","BA-2026-009"),
 "CTL-SEG": Control("CTL-SEG","Payment-zone segmentation","prevention",0.45,"benchmark","INT-T-003"),
 "CTL-PAM": Control("CTL-PAM","Privileged access management","prevention",0.40,"measured","BA-2026-021"),
}

S1 = Scenario("S-1","Card-data exfiltration via payments edge",
  "Attacker compromises the internet-facing payments tier and exfiltrates card data.",
  "A-1","external_organised","T1185","GRP-CORR",0.35,1.0,1.0,0.7,1.3,
  ["CTL-BK","CTL-EDR","CTL-SEG","CTL-PAM"],
  [LossComponent("downtime","daily_revenue_x_hours",0,8.0,None,"BC-2026-003"),
   LossComponent("forensics","fixed_amount",rs(45_000),None,None,"BC-2026-004"),
   LossComponent("customer_remediation","per_record",rs(500),None,2000,"BC-2026-005")])
S2 = Scenario("S-2","Ledger tampering via privileged insider",
  "Compromised privileged credentials alter core ledger records.",
  "A-2","insider","T1098","GRP-CORR",0.20,1.0,1.0,0.7,1.3,
  ["CTL-PAM","CTL-EDR"],
  [LossComponent("downtime","daily_revenue_x_hours",0,6.0,None,"BC-2026-003"),
   LossComponent("reconciliation","fixed_amount",rs(70_000),None,None,"BC-2026-004")])

actions = {
 "ACT-PATCH": Action("ACT-PATCH","Critical patch campaign","Patch internet-facing criticals.",
    "vulnerability", rs(15_000), 30, None, [], "finding_filter",
    {"severity_in":["critical","high"],"exposure_in":["internet_facing"],"exploitable_only":True}),
 "ACT-EDR-TUNE": Action("ACT-EDR-TUNE","EDR policy hardening","Tighten EDR detection policy.",
    "detection", rs(3_000), 45, None, [], "control_ce", {"set_ce":{"CTL-EDR":0.70}}),
 "ACT-PAM": Action("ACT-PAM","Privileged access management rollout","Vault + JIT for tier-1.",
    "identity", rs(60_000), 90, "identity-tier-1", [], "control_ce", {"set_ce":{"CTL-PAM":0.75}}),
 "ACT-MFA": Action("ACT-MFA","Step-up MFA for payments ops","Step-up auth on payment ops.",
    "identity", rs(12_000), 120, "identity-tier-1", ["ACT-PAM"], "exposure_factor", {"S-1":0.55}),
 "ACT-SEG": Action("ACT-SEG","Payment-zone microsegmentation","Microsegment payment zone.",
    "network", rs(18_000), 120, None, ["ACT-PAM"], "control_ce", {"set_ce":{"CTL-SEG":0.75}}),
}

model = {"assets":{"A-1":A1,"A-2":A2}, "findings":findings, "controls":controls,
         "scenarios":{"S-1":S1,"S-2":S2}, "actions":actions}

RHO = {"GRP-CORR": 0.5}
base = assess(model, set(), RHO)
print("=== BASELINE ===")
print("eal=%d (%s) low=%d high=%d conf=%d/%s unadjusted=%d" % (
    base.eal_minor, r(base.eal_minor), base.eal_low_minor, base.eal_high_minor,
    base.confidence, base.confidence_band, base.eal_unadjusted_minor))
for s in base.scenarios:
    print("  %s sle=%s p_in=%.6f mit=%.6f p_res=%.6f eal=%s conf=%d" % (
        s.scenario_code, r(s.sle_minor), s.p_inherent, s.mitigation_factor,
        s.p_residual, r(s.eal_minor), s.confidence))
    for reason in s.confidence_reasons: print("      reason: " + reason)
    for c in s.breakdown: print("      breakdown: %s = %s" % (c.get("component_code"), c.get("amount_minor")))
print("  by_asset=%s" % {k: v for k,v in base.by_asset.items()})
print("  by_actor=%s" % {k: v for k,v in base.by_actor.items()})
print("  freshness=%s" % base.freshness)
print("  incomplete=%d excluded_findings=%d" % (len(base.incomplete), base.excluded_findings))

print("\n=== VM / SLE per scenario ===")
from app.risk import vulnerability_multiplier
for sc in (S1, S2):
    print("  %s vm=%.6f" % (sc.scenario_code, vulnerability_multiplier(sc.loss_components and [f for f in findings if sc.scenario_code in f.scenario_hints] and [f for f in findings if sc.scenario_code in f.scenario_hints] or [])))

print("\n=== WHAT-IF ===")

for label, kw in [
    ("S-1 p0 0.35->0.10", {"p0_overrides": {"S-1": 0.10}}),
    ("S-1 downtime 8h->24h", {"loss_overrides": {"S-1": {"downtime": {"hours": 24.0}}}}),
]:
    a = assess(model, set(), RHO, **kw)
    s1 = a.scenario("S-1")
    print("  %-24s S1 eal=%-9s total=%-9s delta=%+d  incomplete=%d" % (
        label, r(s1.eal_minor), r(a.eal_minor), a.eal_minor-base.eal_minor, len(a.incomplete)))

print("\n=== OPTIMISE ===")
for bud_rs in (75_000, 80_000, 150_000):
    res = optimise(model, rs(bud_rs), 6, exact=True, rho_map=RHO)
    print("budget=%s -> method=%s optimal=%s selected=%s cost=%s red=%s (%.2f%%) "
          "net=%s rosi=%s eval=%d %dms cap=%d/%d" % (
        r(rs(bud_rs)), res.method, res.optimal, res.selected, r(res.cost_minor),
        r(res.reduction_minor), res.reduction_pct*100 if res.reduction_pct<=1 else res.reduction_pct,
        r(res.net_benefit_minor), res.rosi, res.candidates_evaluated,
        res.runtime_ms, res.capacity_used, res.capacity_max))
    for m in res.marginal_by_action:
        print("    %-13s cost=%-9s m_red=%-9s s_red=%-9s overlap=%-9s m_rosi=%8s s_rosi=%8s" % (
            m["action_code"], r(m["cost_minor"]), r(m["marginal_reduction_minor"]),
            r(m["standalone_reduction_minor"]), r(m["overlap_penalty_minor"]),
            m["marginal_rosi"], m["rosi_standalone"]))
    print("    rejected=%s" % [(x["action_code"], x.get("reason")) for x in res.rejected])
    print("    feasibility=%s" % [(i.code, i.message) for i in res.feasibility])

print("\n=== FRONTIER (budget_max=150k) ===")
for p in frontier(model, rs(150_000), 6, steps=7, rho_map=RHO):
    print("  budget=%-10s cost=%-10s red=%-10s optimal=%s sel=%s" % (
        r(p["budget_minor"]), r(p["cost_minor"]), r(p["reduction_minor"]),
        p["optimal"], p["selected"]))
