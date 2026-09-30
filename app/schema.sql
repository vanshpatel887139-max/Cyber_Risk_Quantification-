-- Prototype schema. SQLite, no ORM. Money is stored as INTEGER in the
-- smallest unit of CURRENCY (paise for INR) to avoid float drift.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    role          TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- ---------------------------------------------------------------- inputs
CREATE TABLE IF NOT EXISTS assets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id           TEXT NOT NULL UNIQUE,   -- natural key (FR-D04)
    name               TEXT NOT NULL,
    asset_type         TEXT NOT NULL,
    business_unit      TEXT NOT NULL,
    business_service   TEXT,
    criticality        INTEGER NOT NULL,       -- 1..5
    ip                 TEXT,
    hostname           TEXT,
    daily_revenue      INTEGER NOT NULL DEFAULT 0,   -- minor units
    exposure_class     TEXT NOT NULL DEFAULT 'internal',
    status             TEXT NOT NULL DEFAULT 'active',
    source_system      TEXT,
    synthetic          INTEGER NOT NULL DEFAULT 0,
    first_seen         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    observed_at        TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_system       TEXT NOT NULL,
    external_finding_id TEXT NOT NULL,
    asset_id            TEXT,
    match_method        TEXT,                  -- exact|hostname|ip|null
    rule_id             TEXT,
    title               TEXT,
    severity            TEXT,                  -- critical|high|medium|low|info
    cvss_base           REAL,
    exploitable         INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'open',
    scenario_hints      TEXT,                  -- comma separated
    synthetic           INTEGER NOT NULL DEFAULT 0,
    first_seen          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    observed_at         TEXT,
    raw                 TEXT,
    UNIQUE (source_system, external_finding_id)
);
CREATE INDEX IF NOT EXISTS idx_findings_asset ON findings(asset_id);

CREATE TABLE IF NOT EXISTS controls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    control_code   TEXT NOT NULL UNIQUE,       -- natural key
    name           TEXT NOT NULL,
    domain         TEXT NOT NULL,              -- INT-01..INT-12 (PRD 4.7)
    ce_score       REAL NOT NULL,
    ce_source      TEXT NOT NULL DEFAULT 'assumed',  -- measured|benchmark|assumed
    ce_evidence_ref TEXT,
    framework_iso  TEXT, framework_nist TEXT, framework_cis TEXT,
    synthetic      INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenarios (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_code             TEXT NOT NULL UNIQUE,
    name                      TEXT NOT NULL,
    narrative                 TEXT,
    asset_id                  TEXT NOT NULL REFERENCES assets(asset_id),
    threat_actor              TEXT,
    technique                 TEXT,
    correlation_group_id      TEXT,
    p0                        REAL NOT NULL,   -- baseline annual probability
    exposure_factor           REAL NOT NULL DEFAULT 1.0,
    expected_events_per_incident REAL NOT NULL DEFAULT 1.0,
    sle_low_multiplier        REAL NOT NULL DEFAULT 0.7,
    sle_high_multiplier       REAL NOT NULL DEFAULT 1.3,
    synthetic                 INTEGER NOT NULL DEFAULT 0,
    updated_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scenario_controls (
    scenario_code TEXT NOT NULL REFERENCES scenarios(scenario_code) ON DELETE CASCADE,
    control_code  TEXT NOT NULL REFERENCES controls(control_code) ON DELETE CASCADE,
    PRIMARY KEY (scenario_code, control_code)
);

CREATE TABLE IF NOT EXISTS loss_components (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_code   TEXT NOT NULL REFERENCES scenarios(scenario_code) ON DELETE CASCADE,
    component_code  TEXT NOT NULL,
    basis           TEXT NOT NULL,   -- fixed_amount|daily_revenue_x_hours|per_record
    value           INTEGER NOT NULL DEFAULT 0,   -- minor units
    hours           REAL,
    record_count    INTEGER,
    source_ref      TEXT,            -- document ref, incident ref, or ASSUMED
    UNIQUE (scenario_code, component_code)
);

CREATE TABLE IF NOT EXISTS actions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    action_code         TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    description         TEXT,
    category            TEXT,
    cost                INTEGER NOT NULL,        -- minor units, one-time
    lead_time_days      INTEGER NOT NULL DEFAULT 0,
    capacity_group      TEXT,
    requires_actions    TEXT NOT NULL DEFAULT '[]',   -- JSON array
    effect_type         TEXT NOT NULL,   -- control_ce|finding_filter|loss_component|exposure_factor
    effect_json         TEXT NOT NULL,   -- JSON object, see app/risk.py
    synthetic           INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------- process
CREATE TABLE IF NOT EXISTS datasets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_type      TEXT NOT NULL,
    filename          TEXT,
    status            TEXT NOT NULL,      -- rejected|validated|committed
    rows_total        INTEGER DEFAULT 0,
    rows_ok           INTEGER DEFAULT 0,
    rows_updated      INTEGER DEFAULT 0,
    rows_quarantined  INTEGER DEFAULT 0,
    errors_json       TEXT,
    loaded_at         TEXT,
    load_run_id       INTEGER,
    synthetic         INTEGER NOT NULL DEFAULT 0,
    synthetic_seed    INTEGER
);

CREATE TABLE IF NOT EXISTS quarantine (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id   INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    row_number   INTEGER,
    reason       TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type     TEXT NOT NULL,       -- baseline|scenario|optimiser
    label        TEXT,
    params_json  TEXT,
    result_json  TEXT,
    created_at   TEXT NOT NULL,
    created_by   TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    label        TEXT NOT NULL,
    eal_minor    INTEGER NOT NULL,
    eal_low      INTEGER NOT NULL,
    eal_high     INTEGER NOT NULL,
    confidence   INTEGER NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    username  TEXT,
    role      TEXT,
    action    TEXT NOT NULL,
    entity    TEXT,
    detail_json TEXT,
    severity  TEXT NOT NULL DEFAULT 'info'   -- info|warning|alert
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts DESC);
