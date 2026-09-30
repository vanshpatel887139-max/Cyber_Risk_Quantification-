"""Synthetic demonstration dataset.

EVERYTHING HERE IS INVENTED. All figures are illustrative and are labelled as
synthetic in the database, the API and every exported report. The dataset
exists so the platform can be demonstrated end to end without access to any
real scanner, SIEM or customer data.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from . import config

SEED = 20260929
NOW = datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------- assets
ASSETS = [
    dict(asset_id="A1-OMS-DB-PROD", name="OMS Production Database",
         asset_type="database", business_unit="Retail",
         business_service="Order Management", criticality=5,
         ip="10.20.4.11", hostname="oms-db-prod.corp.example.com",
         daily_revenue=11_000_000, exposure_class="internet_facing",
         status="active", source_system="ServiceNow CMDB"),
    dict(asset_id="A2-IDP-PROD", name="Corporate Identity Provider",
         asset_type="application", business_unit="Corporate IT",
         business_service="Workforce Access", criticality=4,
         ip="10.20.9.4", hostname="idp.corp.example.com",
         daily_revenue=1_200_000, exposure_class="internet_facing",
         status="active", source_system="ServiceNow CMDB"),
    dict(asset_id="A3-PGW-CONN-01", name="Payment Gateway Connector",
         asset_type="application", business_unit="Payments",
         business_service="Payment Settlement", criticality=5,
         ip="10.30.2.7", hostname="pgw-conn-01.payments.example.com",
         daily_revenue=6_000_000, exposure_class="internet_facing",
         status="active", source_system="ServiceNow CMDB"),
    dict(asset_id="A4-FILE-SRV-07", name="Finance File Share",
         asset_type="storage", business_unit="Finance",
         business_service="Month-End Close", criticality=2,
         ip="10.40.7.19", hostname="fin-file-srv-07.corp.example.com",
         daily_revenue=0, exposure_class="internal",
         status="active", source_system="ServiceNow CMDB"),
    dict(asset_id="A5-AP-EDGE-03", name="Branch Edge Access Point",
         asset_type="network", business_unit="Corporate IT",
         business_service="Branch Connectivity", criticality=2,
         ip="172.16.44.3", hostname="ap-edge-03.corp.example.com",
         daily_revenue=0, exposure_class="external",
         status="active", source_system="ServiceNow CMDB"),
]

# ---------------------------------------------------------------- findings
# (external_id, asset, rule, title, severity, exploitable, status, hints)
FINDINGS = [
    ("F-1001", "A1-OMS-DB-PROD", "CIS-1.2", "Unsupported OpenSSL version on database host",
     "critical", 1, "open", "internet_exposure,unpatched"),
    ("F-1002", "A1-OMS-DB-PROD", "CIS-7.1", "Database service account has no MFA",
     "critical", 1, "open", "identity"),
    ("F-1003", "A1-OMS-DB-PROD", "CIS-12.3", "OMS database reachable from general user VLAN",
     "high", 1, "open", "segmentation"),
    ("F-1004", "A1-OMS-DB-PROD", "CIS-4.6", "Default credentials on backup agent",
     "high", 1, "open", "identity,unpatched"),
    ("F-1005", "A1-OMS-DB-PROD", "CIS-7.5", "Security patch backlog over 90 days",
     "high", 0, "open", "unpatched"),
    ("F-1006", "A1-OMS-DB-PROD", "CIS-2.3", "OS end-of-support in 7 months",
     "medium", 0, "open", "unpatched"),
    ("F-1007", "A1-OMS-DB-PROD", "CIS-8.2", "Verbose error messages leak schema",
     "medium", 0, "open", "misconfiguration"),
    ("F-1008", "A1-OMS-DB-PROD", "CIS-11.2", "Backup job has not been verified in 120 days",
     "medium", 0, "open", "backup"),

    ("F-2001", "A2-IDP-PROD", "CIS-5.4", "Phishing-resistant MFA not enforced for admins",
     "critical", 1, "open", "identity"),
    ("F-2002", "A2-IDP-PROD", "CIS-5.6", "Dormant privileged accounts still enabled (23)",
     "high", 1, "open", "identity"),
    ("F-2003", "A2-IDP-PROD", "CIS-6.5", "Password policy allows 8-character passwords",
     "high", 0, "open", "identity"),
    ("F-2004", "A2-IDP-PROD", "CIS-3.11", "Admin session timeout disabled",
     "medium", 0, "open", "identity"),

    ("F-3001", "A3-PGW-CONN-01", "CIS-4.2", "Gateway connector runs as a local administrator",
     "critical", 1, "open", "identity"),
    ("F-3002", "A3-PGW-CONN-01", "CIS-7.2", "Third-party library with known vulnerable version",
     "high", 1, "open", "unpatched"),
    ("F-3003", "A3-PGW-CONN-01", "CIS-12.2", "No egress filtering on settlement subnet",
     "high", 0, "open", "segmentation"),
    ("F-3004", "A3-PGW-CONN-01", "CIS-8.5", "Security events not forwarded to central logging",
     "medium", 0, "open", "logging"),

    ("F-4001", "A4-FILE-SRV-07", "CIS-6.2", "Finance share readable by all authenticated users",
     "high", 1, "open", "data_exposure"),
    ("F-4002", "A4-FILE-SRV-07", "CIS-6.2", "Payroll export folder has no classification label",
     "high", 0, "open", "data_exposure"),
    ("F-4003", "A4-FILE-SRV-07", "CIS-3.6", "Personal data retained beyond schedule",
     "medium", 0, "open", "data_exposure"),
    ("F-4004", "A4-FILE-SRV-07", "CIS-2.4", "Unmanaged share discovered in inventory sweep",
     "medium", 0, "open", "misconfiguration"),

    ("F-5001", "A5-AP-EDGE-03", "CIS-15.1", "Access point management interface exposed",
     "high", 1, "open", "internet_exposure"),
    ("F-5002", "A5-AP-EDGE-03", "CIS-7.4", "Firmware version below vendor baseline",
     "medium", 0, "open", "unpatched"),
    ("F-5003", "A5-AP-EDGE-03", "CIS-9.2", "No NTP synchronisation on edge devices",
     "low", 0, "open", "logging"),
]

# ---------------------------------------------------------------- controls
CONTROLS = [
    ("C-01", "Network segmentation and boundary protection", "INT-07", 0.20, "assumed",
     None, "A.8.22", "DE.CM", "12, 13"),
    ("C-02", "Endpoint detection and response (EDR)", "INT-05", 0.30, "benchmark",
     "Vendor deployment report 2026-Q2", "A.8.16", "DE.CM", "8, 13, 21"),
    ("C-03", "Offline and immutable backups", "INT-06", 0.10, "assumed",
     None, "A.8.13", "RC.RP", "11"),
    ("C-04", "Multi-factor authentication for privileged accounts", "INT-04", 0.15, "measured",
     "IdP policy export 2026-09-01", "A.8.5", "PR.AA", "6"),
    ("C-05", "Logging, monitoring and alerting", "INT-08", 0.25, "benchmark",
     "SIEM coverage report 2026-Q2", "A.8.15", "DE.CM", "8, 17"),
    ("C-06", "Data classification and protection (DLP)", "INT-12", 0.15, "assumed",
     None, "A.5.12", "PR.DS", "3, 11"),
    ("C-07", "Identity and access management", "INT-03", 0.20, "benchmark",
     "IAM review 2026-Q1", "A.5.15", "PR.AA", "5, 6"),
    ("C-08", "Incident response and business continuity", "INT-09", 0.20, "assumed",
     None, "A.5.24", "RS.MA", "17, 24"),
    ("C-09", "Supplier and third-party risk management", "INT-10", 0.30, "benchmark",
     "Third-party register 2026", "A.5.19", "GV.SC", "15, 26"),
    ("C-10", "Vulnerability and patch management", "INT-02", 0.35, "benchmark",
     "Patch SLA report 2026-08", "A.8.8", "ID.RA", "7, 28"),
    ("C-11", "Asset and configuration management", "INT-01", 0.45, "measured",
     "CMDB reconciliation 2026-09", "A.5.9", "ID.AM", "1, 2, 4"),
    ("C-12", "Security awareness and training", "INT-11", 0.30, "benchmark",
     "Training completion report 2026-08", "A.6.3", "PR.AT", "23"),
]

# ---------------------------------------------------------------- scenarios
# loss components: (code, basis, value, hours, record_count, source_ref)
SCENARIOS = [
    dict(
        scenario_code="S1", name="Ransomware encrypts the OMS production database",
        narrative="An operator gains access to the internet-facing order entry path, "
                  "steals credentials, and deploys ransomware across the OMS database "
                  "tier. Recovery relies on restoring from backups.",
        asset_id="A1-OMS-DB-PROD", threat_actor="Ransomware crew",
        technique="Ransomware", correlation_group_id="G1",
        p0=0.05, exposure_factor=1.2,
        required_controls=["C-01", "C-02", "C-03"],
        loss_components=[
            ("lost_revenue_downtime", "daily_revenue_x_hours", 0, 48, None,
             "ASSUMED - downtime estimated from 3 prior incidents"),
            ("direct_recovery", "fixed_amount", 18_000_000, None, None,
             "ASSUMED - 2 vendor quotes, 2026"),
            ("response_forensics", "fixed_amount", 6_000_000, None, None,
             "ASSUMED - IR retainer schedule"),
            ("legal_regulatory_notification", "fixed_amount", 12_000_000, None, None,
             "ASSUMED - external counsel estimate"),
            ("partner_sla_penalty", "fixed_amount", 40_000_000, None, None,
             "ASSUMED - service credits payable to partner banks during outage"),
        ]),
    dict(
        scenario_code="S2", name="Privileged account takeover via credential stuffing",
        narrative="Stolen credentials are replayed against the corporate identity "
                  "provider; an administrator account is compromised and used to "
                  "change security policy.",
        asset_id="A2-IDP-PROD", threat_actor="Credential-stuffing botnet",
        technique="Credential", correlation_group_id="G2",
        p0=0.18, exposure_factor=1.0,
        required_controls=["C-04", "C-05"],
        loss_components=[
            ("lost_revenue_downtime", "daily_revenue_x_hours", 0, 24, None,
             "ASSUMED - identity outage blocks all digital channels for a day"),
            ("response_forensics", "fixed_amount", 2_500_000, None, None,
             "ASSUMED - IR retainer schedule"),
            ("legal_regulatory_notification", "fixed_amount", 4_000_000, None, None,
             "ASSUMED - external counsel estimate, 12k identity records"),
            ("breach_response", "per_record", 180, None, 12_000,
             "ASSUMED - identity records at risk"),
            ("identity_recovery", "fixed_amount", 5_000_000, None, None,
             "ASSUMED - re-enrolment and support surge cost"),
        ]),
    dict(
        scenario_code="S3", name="Ransomware encrypts the payment gateway connector",
        narrative="A vulnerable third-party library in the settlement connector is "
                  "exploited, halting payment settlement for up to three days.",
        asset_id="A3-PGW-CONN-01", threat_actor="Ransomware crew",
        technique="Ransomware", correlation_group_id="G1",
        p0=0.11, exposure_factor=1.0,
        required_controls=["C-02", "C-03"],
        loss_components=[
            ("lost_revenue_downtime", "daily_revenue_x_hours", 0, 72, None,
             "ASSUMED - 1 prior incident"),
            ("direct_recovery", "fixed_amount", 8_000_000, None, None,
             "ASSUMED - 2 vendor quotes, 2026"),
            ("response_forensics", "fixed_amount", 2_000_000, None, None,
             "ASSUMED - IR retainer schedule"),
            ("legal_regulatory_notification", "fixed_amount", 2_000_000, None, None,
             "ASSUMED - counsel estimate"),
            ("partner_sla_penalty", "fixed_amount", 24_000_000, None, None,
             "ASSUMED - settlement service credits during 3-day halt"),
        ]),
    dict(
        scenario_code="S4", name="Bulk exfiltration of finance and payroll data",
        narrative="Over-permissioned finance share access is used to copy payroll and "
                  "customer records before detection.",
        asset_id="A4-FILE-SRV-07", threat_actor="Opportunistic insider / external",
        technique="Data", correlation_group_id="G3",
        p0=0.10, exposure_factor=1.0,
        required_controls=["C-06", "C-07"],
        loss_components=[
            ("direct_recovery", "fixed_amount", 900_000, None, None,
             "ASSUMED - fixed cleanup cost"),
            ("response_forensics", "fixed_amount", 800_000, None, None,
             "ASSUMED - IR retainer schedule"),
            ("legal_regulatory_notification", "fixed_amount", 800_000, None, None,
             "ASSUMED - counsel estimate"),
            ("breach_response", "per_record", 220, None, 60_000,
             "ASSUMED - payroll and customer records in scope"),
            ("regulatory_action", "fixed_amount", 10_000_000, None, None,
             "ASSUMED - supervisory remediation programme cost"),
        ]),
    dict(
        scenario_code="S5", name="Ransomware on a branch edge device disrupts connectivity",
        narrative="An exposed access point is compromised and used as a pivot, "
                  "interrupting branch connectivity for several hours.",
        asset_id="A5-AP-EDGE-03", threat_actor="Ransomware crew",
        technique="Ransomware", correlation_group_id="G1",
        p0=0.20, exposure_factor=1.0,
        required_controls=["C-02", "C-08"],
        loss_components=[
            ("direct_recovery", "fixed_amount", 2_500_000, None, None,
             "ASSUMED - field service and hardware replacement"),
            ("response_forensics", "fixed_amount", 600_000, None, None,
             "ASSUMED - IR retainer schedule"),
            ("legal_regulatory_notification", "fixed_amount", 300_000, None, None,
             "ASSUMED - counsel estimate"),
            ("connectivity_remediation", "fixed_amount", 1_800_000, None, None,
             "ASSUMED - branch WAN repair and reconfiguration"),
        ]),
    dict(
        scenario_code="S6", name="Business email compromise causes a fraudulent vendor payment",
        narrative="An employee mailbox is taken over and used to instruct a vendor "
                  "to change bank details, redirecting a payment.",
        asset_id="A2-IDP-PROD", threat_actor="BEC fraud ring",
        technique="Social", correlation_group_id="G4",
        p0=0.18, exposure_factor=1.0,
        required_controls=["C-04", "C-10", "C-11"],
        loss_components=[
            ("direct_recovery", "fixed_amount", 8_000_000, None, None,
             "ASSUMED - two diverted vendor payments, recall incomplete"),
            ("response_forensics", "fixed_amount", 1_200_000, None, None,
             "ASSUMED - IR retainer schedule"),
            ("legal_regulatory_notification", "fixed_amount", 3_000_000, None, None,
             "ASSUMED - counsel estimate"),
            ("breach_response", "per_record", 260, None, 5_000,
             "ASSUMED - mailbox records at risk"),
            ("funds_recall", "fixed_amount", 7_000_000, None, None,
             "ASSUMED - unrecovered portion of diverted payments"),
        ]),
]

# ---------------------------------------------------------------- actions
# effect_type / effect_json -> see app/risk.py
ACTIONS = [
    dict(action_code="ACT-1", name="Enforce MFA for all privileged accounts",
         description="Remove SMS-only options and require a second factor for every "
                     "administrative role in the identity provider.",
         category="identity", cost=1_100_000, lead_time_days=45, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-04": 0.70}}),
    dict(action_code="ACT-2", name="Deploy phishing-resistant FIDO2 keys for administrators",
         description="Issue hardware security keys to all administrators and disable "
                     "password fallback for privileged logins.",
         category="identity", cost=800_000, lead_time_days=60, capacity_group=None,
         requires_actions=["ACT-1"], effect_type="control_ce",
         effect={"set_ce": {"C-04": 0.85}}),
    dict(action_code="ACT-3", name="Network micro-segmentation for the payment zone",
         description="Isolate the settlement subnet from general user and server "
                     "networks with policy-based controls.",
         category="network", cost=4_800_000, lead_time_days=120, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-01": 0.45}}),
    dict(action_code="ACT-4", name="Immutable offline backups with verified restore",
         description="Air-gapped immutable backup copies with a quarterly verified "
                     "restore test for tier-1 systems.",
         category="resilience", cost=1_900_000, lead_time_days=75, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-03": 0.55}}),
    dict(action_code="ACT-5", name="Extend EDR coverage to legacy and branch endpoints",
         description="Deploy the existing EDR agent to branch appliances, hypervisors "
                     "and legacy servers that are currently unprotected.",
         category="endpoint", cost=1_600_000, lead_time_days=60, capacity_group="edr",
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-02": 0.50}}),
    dict(action_code="ACT-6", name="Replace legacy EDR platform",
         description="Migrate from the end-of-life endpoint agent to a supported "
                     "platform with behavioural detection.",
         category="endpoint", cost=2_900_000, lead_time_days=150, capacity_group="edr",
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-02": 0.65}}),
    dict(action_code="ACT-7", name="24x7 SIEM monitoring with automated triage",
         description="Add a managed detection and response tier with automated "
                     "enrichment and triage playbooks.",
         category="monitoring", cost=2_400_000, lead_time_days=30, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-05": 0.50}}),
    dict(action_code="ACT-8", name="Privileged access management with session recording",
         description="Broker all privileged access through a vault, rotate credentials "
                     "and record administrative sessions.",
         category="identity", cost=1_400_000, lead_time_days=90, capacity_group=None,
         requires_actions=["ACT-1"], effect_type="control_ce",
         effect={"set_ce": {"C-07": 0.60}}),
    dict(action_code="ACT-9", name="Deploy DLP on the finance file share",
         description="Classify and label finance and payroll data, and block "
                     "exfiltration to unmanaged destinations.",
         category="data", cost=2_100_000, lead_time_days=90, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-06": 0.50}}),
    dict(action_code="ACT-10", name="Quarterly red team and 14-day critical patch SLA",
         description="Continuous validation of exploit paths plus a hard remediation "
                     "deadline for critical and exploitable findings.",
         category="process", cost=1_600_000, lead_time_days=30, capacity_group=None,
         requires_actions=[], effect_type="finding_filter",
         effect={"severity_in": ["critical", "high"], "exploitable_only": True}),
    dict(action_code="ACT-11", name="Out-of-band callback verification for vendor payments",
         description="Require a voice callback on a pre-existing number before any "
                     "change to vendor bank details is released.",
         category="process", cost=700_000, lead_time_days=30, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-10": 0.40}}),
    dict(action_code="ACT-12", name="IR retainer plus annual disaster recovery rehearsal",
         description="Retain an external response team and run a full failover "
                     "rehearsal of the order management stack.",
         category="resilience", cost=1_200_000, lead_time_days=60, capacity_group=None,
         requires_actions=[], effect_type="control_ce",
         effect={"set_ce": {"C-08": 0.50}}),
]


# ---------------------------------------------------------------- generation
def _additional_findings(at: datetime) -> list[tuple]:
    """Findings that only exist in the refreshed (D+30) dataset."""
    return [
        ("F-1008", "A1-OMS-DB-PROD", "CIS-1.4", "Newly disclosed remote code execution in "
         "database driver", "critical", 1, "open", "unpatched,internet_exposure"),
        ("F-3005", "A3-PGW-CONN-01", "CIS-7.6", "Emergency vendor advisory on settlement "
         "connector", "critical", 1, "open", "unpatched"),
        ("F-2005", "A2-IDP-PROD", "CIS-5.2", "New OAuth app granted directory write scope",
         "high", 1, "open", "identity"),
        ("F-4005", "A4-FILE-SRV-07", "CIS-3.9", "Retention exception raised without approval",
         "high", 0, "open", "data_exposure"),
        ("F-5004", "A5-AP-EDGE-03", "CIS-15.3", "Edge device management cert expires in 21 days",
         "medium", 0, "open", "misconfiguration"),
    ]


def build(refresh: bool = False) -> dict[str, list[dict]]:
    """Return the full synthetic dataset.

    refresh=True produces the D+30 variant: five new critical/high findings,
    one asset decommissioned, one control degraded. Same seed, so the
    comparison is deterministic.
    """
    rng = random.Random(SEED + (30 if refresh else 0))
    offset = timedelta(days=30) if refresh else timedelta(0)
    at = _iso(NOW + offset)

    assets = [dict(a, synthetic=1, observed_at=at) for a in ASSETS]
    if refresh:
        for a in assets:
            if a["asset_id"] == "A4-FILE-SRV-07":
                a["status"] = "decommissioned"

    findings: list[dict] = []
    for (fid, asset, rule, title, sev, exploitable, status, hints) in FINDINGS:
        if refresh and fid == "F-4001":
            continue  # resolved in the refresh
        observed = at if refresh else _iso(NOW - timedelta(days=rng.randint(2, 6)))
        findings.append(dict(
            external_finding_id=fid, source_system="SimulatedScanner",
            asset_id=asset, rule_id=rule, title=title, severity=sev,
            exploitable=int(exploitable), status=status, scenario_hints=hints,
            synthetic=1, observed_at=observed,
        ))
    if refresh:
        for (fid, asset, rule, title, sev, exploitable, status, hints) in _additional_findings(
                NOW + offset):
            findings.append(dict(
                external_finding_id=fid, source_system="SimulatedScanner",
                asset_id=asset, rule_id=rule, title=title, severity=sev,
                exploitable=int(exploitable), status=status, scenario_hints=hints,
                synthetic=1, observed_at=_iso(NOW + offset),
            ))

    controls = []
    for code, name, domain, ce, source, ref, iso, nist, cis in CONTROLS:
        ce_eff = ce
        if refresh and code == "C-05":
            ce_eff = 0.18  # alert fatigue: monitoring degraded in the period
        controls.append(dict(control_code=code, name=name, domain=domain, ce_score=ce_eff,
                             ce_source=source, ce_evidence_ref=ref, framework_iso=iso,
                             framework_nist=nist, framework_cis=cis, synthetic=1))

    scenarios = []
    for s in SCENARIOS:
        base = {k: v for k, v in s.items() if k not in ("required_controls", "loss_components")}
        base.update(dict(sle_low_multiplier=0.7, sle_high_multiplier=1.3,
                         expected_events_per_incident=1.0, synthetic=1))
        scenarios.append({**base, "required_controls": list(s["required_controls"]),
                          "loss_components": [dict(zip(
                              ("component_code", "basis", "value", "hours",
                               "record_count", "source_ref"), c))
                              for c in s["loss_components"]]})

    actions = [dict(a, synthetic=1) for a in ACTIONS]

    return {"assets": assets, "findings": findings, "controls": controls,
            "scenarios": scenarios, "actions": actions,
            "loss_components": [dict(c, scenario_code=s["scenario_code"])
                                for s in scenarios for c in s["loss_components"]]}


def seed(conn, refresh: bool = False) -> dict[str, int]:
    """Write the synthetic dataset into the database (idempotent upsert)."""
    from . import db
    data = build(refresh=refresh)
    now = db.utcnow()
    counts: dict[str, int] = {}

    for a in data["assets"]:
        conn.execute(
            """INSERT INTO assets (asset_id,name,asset_type,business_unit,business_service,
               criticality,ip,hostname,daily_revenue,exposure_class,status,source_system,
               synthetic,first_seen,updated_at,observed_at)
               VALUES (:asset_id,:name,:asset_type,:business_unit,:business_service,
               :criticality,:ip,:hostname,:daily_revenue,:exposure_class,:status,
               :source_system,1,:now,:now,:observed_at)
               ON CONFLICT(asset_id) DO UPDATE SET
                 name=excluded.name, asset_type=excluded.asset_type,
                 business_unit=excluded.business_unit,
                 business_service=excluded.business_service,
                 criticality=excluded.criticality, ip=excluded.ip,
                 hostname=excluded.hostname, daily_revenue=excluded.daily_revenue,
                 exposure_class=excluded.exposure_class, status=excluded.status,
                 synthetic=1, updated_at=excluded.updated_at,
                 observed_at=excluded.observed_at""",
            {**a, "daily_revenue": db.to_minor(a["daily_revenue"]), "now": now})
    counts["assets"] = len(data["assets"])

    for f in data["findings"]:
        conn.execute(
            """INSERT INTO findings (source_system,external_finding_id,asset_id,match_method,
               rule_id,title,severity,exploitable,status,scenario_hints,synthetic,
               first_seen,updated_at,observed_at,raw)
               VALUES ('SimulatedScanner',:external_finding_id,:asset_id,'exact',:rule_id,
               :title,:severity,:exploitable,:status,:scenario_hints,1,:now,:now,
               :observed_at,:raw)
               ON CONFLICT(source_system,external_finding_id) DO UPDATE SET
                 asset_id=excluded.asset_id, severity=excluded.severity,
                 exploitable=excluded.exploitable, status=excluded.status,
                 scenario_hints=excluded.scenario_hints, updated_at=excluded.updated_at,
                 observed_at=excluded.observed_at""",
            {**f, "now": now, "raw": json.dumps(f)})
    counts["findings"] = len(data["findings"])

    for c in data["controls"]:
        conn.execute(
            """INSERT INTO controls (control_code,name,domain,ce_score,ce_source,
               ce_evidence_ref,framework_iso,framework_nist,framework_cis,synthetic,updated_at)
               VALUES (:control_code,:name,:domain,:ce_score,:ce_source,:ce_evidence_ref,
               :framework_iso,:framework_nist,:framework_cis,1,:now)
               ON CONFLICT(control_code) DO UPDATE SET
                 name=excluded.name, domain=excluded.domain, ce_score=excluded.ce_score,
                 ce_source=excluded.ce_source, ce_evidence_ref=excluded.ce_evidence_ref,
                 framework_iso=excluded.framework_iso, framework_nist=excluded.framework_nist,
                 framework_cis=excluded.framework_cis, updated_at=excluded.updated_at""",
            {**c, "now": now})
    counts["controls"] = len(data["controls"])

    for s in data["scenarios"]:
        conn.execute(
            """INSERT INTO scenarios (scenario_code,name,narrative,asset_id,threat_actor,
               technique,correlation_group_id,p0,exposure_factor,
               expected_events_per_incident,sle_low_multiplier,sle_high_multiplier,
               synthetic,updated_at)
               VALUES (:scenario_code,:name,:narrative,:asset_id,:threat_actor,:technique,
               :correlation_group_id,:p0,:exposure_factor,:expected_events_per_incident,
               :sle_low_multiplier,:sle_high_multiplier,1,:now)
               ON CONFLICT(scenario_code) DO UPDATE SET
                 name=excluded.name, narrative=excluded.narrative,
                 asset_id=excluded.asset_id, threat_actor=excluded.threat_actor,
                 technique=excluded.technique, correlation_group_id=excluded.correlation_group_id,
                 p0=excluded.p0, exposure_factor=excluded.exposure_factor,
                 expected_events_per_incident=excluded.expected_events_per_incident,
                 sle_low_multiplier=excluded.sle_low_multiplier,
                 sle_high_multiplier=excluded.sle_high_multiplier,
                 updated_at=excluded.updated_at""",
            {**{k: v for k, v in s.items()
                 if k not in ("required_controls", "loss_components")}, "now": now})
        for cc in s["required_controls"]:
            conn.execute(
                "INSERT OR IGNORE INTO scenario_controls (scenario_code, control_code) "
                "VALUES (?,?)", (s["scenario_code"], cc))
    counts["scenarios"] = len(data["scenarios"])

    for c in data["loss_components"]:
        conn.execute(
            """INSERT INTO loss_components (scenario_code,component_code,basis,value,hours,
               record_count,source_ref) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(scenario_code,component_code) DO UPDATE SET
                 basis=excluded.basis, value=excluded.value, hours=excluded.hours,
                 record_count=excluded.record_count, source_ref=excluded.source_ref""",
            (c["scenario_code"], c["component_code"], c["basis"],
             db.to_minor(c["value"]), c["hours"], c["record_count"], c["source_ref"]))
    counts["loss_components"] = len(data["loss_components"])

    for a in data["actions"]:
        conn.execute(
            """INSERT INTO actions (action_code,name,description,category,cost,
               lead_time_days,capacity_group,requires_actions,effect_type,effect_json,
               synthetic,updated_at)
               VALUES (:action_code,:name,:description,:category,:cost,:lead_time_days,
               :capacity_group,:requires_actions,:effect_type,:effect_json,1,:now)
               ON CONFLICT(action_code) DO UPDATE SET
                 name=excluded.name, description=excluded.description,
                 category=excluded.category, cost=excluded.cost,
                 lead_time_days=excluded.lead_time_days,
                 capacity_group=excluded.capacity_group,
                 requires_actions=excluded.requires_actions,
                 effect_type=excluded.effect_type, effect_json=excluded.effect_json,
                 updated_at=excluded.updated_at""",
            {**a, "cost": db.to_minor(a["cost"]),
             "requires_actions": json.dumps(a["requires_actions"]),
             "effect_json": json.dumps(a["effect"]), "now": now})
    counts["actions"] = len(data["actions"])

    conn.execute(
        """INSERT INTO datasets (dataset_type,filename,status,rows_total,rows_ok,
           rows_quarantined,loaded_at,synthetic,synthetic_seed)
           VALUES ('synthetic_bundle',?,'committed',?,?,0,?,1,?)""",
        (f"simulated_feed_{'D+30' if refresh else 'D0'}.json",
         sum(counts.values()), sum(counts.values()), now, SEED + (30 if refresh else 0)))
    counts["total"] = sum(counts.values())
    return counts
