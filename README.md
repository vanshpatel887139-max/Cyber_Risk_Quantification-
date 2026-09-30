# Cyber Risk Quantification Platform

An AI-powered platform that continuously estimates cyber risk in monetary terms,
identifies key security weaknesses, and recommends cost-effective fixes. It helps
organisations compare mitigation scenarios and allocate security budgets to
maximise estimated risk reduction.

A working prototype that turns a synthetic cyber-risk dataset into a defensible
number, then uses that number to decide where to spend a mitigation budget.

Synthetic data throughout. Every figure is generated from an invented dataset
for product evaluation, and every API response, dashboard panel, and exported
report carries that caveat. This is not a measurement of any real organisation.

## What it does

1. **Ingest** asset inventory, findings, control effectiveness, scenarios, loss
   components, and candidate actions from CSV or JSON. Bad rows are quarantined
   individually instead of failing the whole file.
2. **Quantify** risk as Expected Annual Loss (EAL) per scenario, with an
   uncertainty range, a correlation adjustment, and a data-confidence score.
3. **What-if** change a scenario probability and see the portfolio EAL move.
4. **Optimise** a mitigation budget subject to dependencies, capacity limits,
   and mutually exclusive capacity groups, reporting ROSI per action.
5. **Explain** results through an assistant that may only restate numbers that
   already exist in the computed context.
6. **Export** a Markdown summary, scenario/asset/action CSVs, and a board-ready
   HTML pack.

## Quick start

```bash
git clone https://github.com/vanshpatel887139-max/Cyber_Risk_Quantification-
cd Cyber_Risk_Quantification-
python3 -m pip install -r requirements.txt
./run.sh                 # http://127.0.0.1:8000
```

Or run the server directly:

```bash
python3 -m uvicorn app.main:app --port 8000
```

Requires Python 3.13+ and SQLite. No external services are needed. The assistant
works fully offline; an LLM is optional and off by default.

Sign in with one of the seeded accounts:

| Username  | Password     | Role          | Can do |
|-----------|--------------|---------------|--------|
| `admin`   | `admin123`   | administrator | ingest, model, optimise, ask, export, read audit |
| `analyst` | `analyst123` | analyst       | load data, run the model, optimise, ask, export, read audit |
| `ciso`    | `ciso123`    | executive     | view, run the model, ask, export — no ingest, no optimise, no audit |

These are development defaults. Change them before putting the app anywhere
reachable by anyone else. Note the `admin` account is declared as the user
manager but there is no user-management API yet, so accounts are created by
editing the database directly.

The database is created and seeded with the D0 dataset on first start.

## Tests

```bash
python3 -m unittest discover -s tests -t tests   # 174 unit + HTTP tests
./run.sh --test                                 # same thing
```

For an end-to-end pass against a running server:

```bash
./run.sh --port 8137 &
python3 smoke.py http://127.0.0.1:8137
```

## How the numbers are calculated

For each scenario:

```
SLE            = sum of loss components
m              = exposure_factor x vulnerability_multiplier
P_inherent     = 1 - (1 - p0) ^ m
mitigation     = max( product(1 - CE_i) over required controls,
                      1 - CRP_MAX_MITIGATION )
P_residual     = P_inherent x mitigation
EAL            = P_residual x SLE x expected_events_per_incident
```

Controls stack multiplicatively, which is why a ceiling matters. Several
effective controls would otherwise drive residual probability to nearly zero
and understate the risk. `CRP_MAX_MITIGATION` (default `0.90`) caps the total
mitigation, and the cap is reported as a confidence reason rather than hidden.

Correlated scenarios are combined so the portfolio total is not the naive sum:

```
EAL_group = (1 - rho) * sum(EAL) + rho * max(EAL)
```

Loss components are derived three ways, so a number is always traceable to an
input: `fixed_amount` (a stated figure), `daily_revenue_x_hours` (downtime
priced from the asset's daily revenue), and `per_record` (records lost times a
per-record cost). A scenario missing a required input is reported as incomplete
rather than quietly scored as zero.

Uncertainty comes from the low/high multipliers on the SLE. Confidence is scored
from four weighted inputs: data completeness, evidence quality for control
effectiveness, data freshness, and whether each loss component cites a real
source. A Low confidence score means the number is weak, not that the risk is
small.

## Money

All amounts are INR. The database stores integer minor units (paise) to avoid
floating point drift. Uploaded monetary fields are expressed in whole rupees
and converted on ingest, matching the seeded dataset:

| Dataset           | Monetary field  | Meaning |
|-------------------|-----------------|---------|
| `assets`          | `daily_revenue` | revenue at risk per day |
| `loss_components` | `value`         | the per-unit or fixed amount |
| `actions`         | `cost`          | one-off implementation cost |

API responses expose the integer `*_minor` fields for arithmetic, alongside
`currency` and `symbol` for formatting. **Do not format minor units as rupees in
the UI** — divide by 100 first. There is no server-side `*_display` field; the
formatting happens in the client and in the report writers.

## Optimisation

Exact enumeration is used when the candidate pool is at or below
`CRP_EXACT_MAX`; beyond that a greedy heuristic runs and the
result is explicitly labelled `optimal: false`. A heuristic answer is never
presented as proven optimal.

`ROSI = (risk reduction - cost) / cost`, computed on marginal reduction
obtained by removing each action from the completed plan. Marginal values do
not sum to the total reduction, because controls overlap. Both the marginal
and the standalone figure are reported, along with the overlap penalty, so the
double counting is visible rather than hidden.

## The assistant

The assistant is constrained by code, not by prompt wording:

1. The LLM never computes a number. It receives a frozen JSON context and may
   only restate what is in it.
2. Every numeric token in a model response is checked against the set of
   numbers in that context. Anything unrecognised is rejected, the answer is
   discarded, and the deterministic template answer is returned instead.
3. Questions the platform cannot answer with the data it holds are refused
   explicitly. A confident wrong answer here is the worst possible failure, so
   forecasts, compliance certificates, and industry benchmarks all refuse.
4. With no API key configured, the deterministic template engine answers and
   says so.

Every interaction, including refusals, is written to the audit log.

To enable an LLM:

```bash
export CRP_LLM_ENABLED=1
export CRP_LLM_API_KEY=sk-...
export CRP_LLM_BASE_URL=https://api.openai.com/v1   # or any compatible endpoint
export CRP_LLM_MODEL=gpt-4o-mini
```

If the call fails or returns an ungrounded number, the response falls back to
the template and records why.

## Uploading data

`POST /api/ingest` as multipart form data with `dataset_type` and `file`. Set
`commit=false` to validate without writing.

Supported `dataset_type` values: `assets`, `findings`, `controls`, `scenarios`,
`actions`, `loss_components`.

Validation is per row. A row with a missing required field, an out-of-range
number, a bad enum, or unparseable JSON is written to the `quarantine` table
with its source line number and reason; the rest of the file still loads. The
response reports `rows_total`, `rows_ok`, `rows_updated`, and
`rows_quarantined`, and `GET /api/quarantine` lists the rejects.

Findings are matched to assets by `asset_id`, then hostname, then IP. A finding
that matches nothing is quarantined as `unmatched_asset` rather than being
assigned to an arbitrary asset.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | liveness, currency, row counts, LLM state |
| GET | `/api/docs`, `/api/openapi.json` | interactive API reference |
| POST | `/api/login` / `/api/logout` | session cookie |
| GET | `/api/me` | current user |
| GET | `/api/overview` | counts, synthetic share, recent loads |
| POST | `/api/ingest` | upload a dataset |
| GET | `/api/quarantine` | rejected rows |
| GET | `/api/catalog` | assets, controls, actions for pickers |
| POST | `/api/demo/reset?refresh=` | reload D0 or D+30 synthetic data |
| GET | `/api/assessment` | baseline EAL; `rho=` and `actions=` supported |
| POST | `/api/scenarios/{code}/whatif` | override `p0` or a loss component |
| POST | `/api/optimise` | budget-constrained plan |
| GET | `/api/optimise/frontier` | reduction across a budget range |
| POST | `/api/ask` | grounded assistant |
| GET | `/api/ai/status` | LLM state and guarantees |
| GET | `/api/report/summary.md` | executive summary |
| GET | `/api/report/scenarios.csv` | scenario detail |
| GET | `/api/report/actions.csv` | plan and rejected actions |
| GET | `/api/report/board.html` | board pack; `budget_minor=` optional |
| GET | `/api/audit` | audit log |

`reports.py` also contains `loss_components_csv` and `ai_context_json` writers
that no route exposes yet, so they are not reachable over HTTP.

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `CRP_DATA_DIR` | `./data` | SQLite database and uploads |
| `CRP_LLM_ENABLED` | `0` | enable the LLM narrative path |
| `CRP_LLM_API_KEY` | – | API key for the LLM |
| `CRP_LLM_BASE_URL` | OpenAI | compatible endpoint base URL |
| `CRP_LLM_MODEL` | `gpt-4o-mini` | model name |
| `CRP_MAX_MITIGATION` | `0.90` | ceiling on stacked control effect |
| `CRP_EXACT_MAX` | `16` | pool size for exact search |
| `CRP_CAPACITY` | `6` | default action cap |
| `CRP_MAX_UPLOAD_BYTES` | `5242880` | upload size limit (5 MiB) |

## Layout

```
app/
  config.py       settings, roles, capability matrix
  schema.sql      SQLite schema
  db.py           connections, sessions, passwords, audit
  risk.py         SLE, P_inherent, P_residual, EAL, correlation, confidence
  demo_data.py    deterministic D0 and D+30 synthetic datasets
  ingest.py       parsing, coercion, per-row quarantine
  optimize.py     exact and heuristic search, ROSI, frontier
  ai.py           context, grounding guard, refusals
  reports.py      Markdown, CSV, HTML exports
  main.py         FastAPI routes
  static/         dashboard
tests/            174 tests across risk, optimise, ingest, ai, reports, db, api
smoke.py          end-to-end check against a running server
docs/
  TECHNICAL_ARCHITECTURE.md       full design, formulas, and known limitations
  SECURITY_ACCESS_REQUIREMENTS.md  threat model, access control, and security test plan
  FRONTEND_SPECIFICATION.md        UI specification: 11 screens, components, requirements
  AI_LLM_SPECIFICATION.md          AI layer: intents, grounding, prompts, evaluation, safeguards
  worked_example.py               regenerates every figure quoted in the design doc
```

## Limitations

- The dataset is synthetic. No real organisation's risk has been measured.
- The model is a **deterministic closed-form expected-loss calculation, not a
  simulation.** There is no Monte Carlo sampling, no probability distribution over
  loss severity, and no stochastic simulation of any kind. Every coefficient is a
  hand-chosen, documented constant, and the same inputs always produce the same
  number. It also does not model tail events outside the scenario set.
- The vulnerability multiplier is a stated prior, not a learned model. Its
  coefficient and the finding-severity weights are auditable constants, not
  parameters fitted to incident history.
- Control effectiveness scores are inputs, not measurements. A 70% CE means
  "assume 70% effective", and the confidence score reflects whether that
  assumption is evidenced.
- Loss components are estimates. Change them and the answer changes; that is
  the point of the what-if endpoint.
- The LLM adds explanation only. It cannot change a number.
- Single-process SQLite with no migrations, background jobs, or multi-tenancy.
- Assessments are **not yet recorded**. The `runs` and `snapshots` tables exist but
  nothing writes to them, so a figure cannot be reproduced after the next upload.
  See section D.2 of the design document.
- Exact optimisation is exhaustive up to `CRP_EXACT_MAX` candidates with no time
  limit, so a large candidate pool can make one request slow.

## Design documentation

`docs/TECHNICAL_ARCHITECTURE.md` covers the architecture, the full formula set
with a verified worked example, the proposed production schema, a 22-item
findings register, and a phased implementation plan. Every number in it is
regenerated by `python3 docs/worked_example.py`.
