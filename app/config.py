"""Central configuration.

All values are overridable through environment variables so the prototype can
run with zero configuration but be re-configured without code changes.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("CRP_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.getenv("CRP_DB_PATH", DATA_DIR / "cybersec.db"))
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Prototype safety limits (see PRD 6.1 FR-D01) -------------------------
MAX_UPLOAD_BYTES = int(os.getenv("CRP_MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
ALLOWED_EXTENSIONS = {".csv", ".json"}
MAX_VALIDATION_ERRORS_SHOWN = 200

# --- Risk model defaults (see PRD 7) --------------------------------------
DEFAULT_CURRENCY = os.getenv("CRP_CURRENCY", "INR")
CURRENCY_SYMBOL = os.getenv("CRP_CURRENCY_SYMBOL", "₹")
TIME_HORIZON_YEARS = 1

# Data freshness thresholds in days (FR-D06)
FRESH_DAYS_GREEN = 7
FRESH_DAYS_AMBER = 30

# Default correlation coefficient for overlapping scenarios (FR-F05)
DEFAULT_CORRELATION_RHO = float(os.getenv("CRP_DEFAULT_RHO", "0.5"))

# Probability cap: a single scenario should not be "more likely than not"
MAX_ANNUAL_PROBABILITY = float(os.getenv("CRP_MAX_P", "0.5"))
PROBABILITY_HARD_CAP = 0.95

# Ceiling on the reduction a stack of controls may claim. Multiplying control
# effectiveness assumes controls fail independently; real control programmes
# share failure modes, so the achievable reduction is capped and the residual
# is reported honestly. See risk.assess().
MAX_CONTROL_MITIGATION = float(os.getenv("CRP_MAX_MITIGATION", "0.90"))

# Optimiser (PRD 9)
EXACT_SEARCH_MAX_ACTIONS = int(os.getenv("CRP_EXACT_MAX", "16"))
DEFAULT_CAPACITY_MAX_ACTIONS = int(os.getenv("CRP_CAPACITY", "6"))

# --- Roles (PRD 3) --------------------------------------------------------
ROLE_ADMIN = "administrator"
ROLE_ANALYST = "analyst"
ROLE_EXEC = "executive"
ALL_ROLES = (ROLE_ADMIN, ROLE_ANALYST, ROLE_EXEC)

# Capabilities matrix. Server-side enforcement only.
CAPABILITIES = {
    ROLE_ADMIN: {
        "data.write", "assumptions.write", "actions.write", "scenario.write",
        "budget.write", "assessment.run", "optimiser.run", "view",
        "ai.ask", "report.export", "users.manage", "audit.read",
    },
    ROLE_ANALYST: {
        "data.write", "assumptions.write", "actions.write", "scenario.write",
        "budget.write", "assessment.run", "optimiser.run", "view",
        "ai.ask", "report.export", "audit.read",
    },
    ROLE_EXEC: {"view", "ai.ask", "report.export", "assessment.run"},
}

# --- Session --------------------------------------------------------------
SESSION_COOKIE = "crp_session"
SESSION_TTL_SECONDS = 8 * 3600

# --- AI (PRD 8) -----------------------------------------------------------
# Optional. When absent the deterministic template engine is used and the UI
# says so. The LLM never supplies numbers - see app/ai.py.
LLM_ENABLED = os.getenv("CRP_LLM_ENABLED", "0") == "1"
LLM_MODEL = os.getenv("CRP_LLM_MODEL", "gpt-4o-mini")
LLM_API_KEY = os.getenv("CRP_LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
LLM_BASE_URL = os.getenv("CRP_LLM_BASE_URL", "https://api.openai.com/v1")
LLM_TIMEOUT = 20

# Report generation
REPORT_FORMAT = "html"
