# Frontend Specification — Cyber Risk Quantification Platform

**Document status:** Draft for review
**Applies to:** `app/static/` (FastAPI-served single-page prototype) and the planned production frontend
**Date:** 2026-09-30
**Related documents:** `docs/TECHNICAL_ARCHITECTURE.md`, `docs/SECURITY_ACCESS_REQUIREMENTS.md`

---

## How to read this document

Every feature claim carries one of four status labels. They are not interchangeable and must not be
upgraded on optimism.

| Status | Meaning | Evidence required |
|---|---|---|
| **Verified Implemented** | Exists in the repository and was read or executed during this review. | A file and line reference, or a reproduced command result. |
| **Proposed MVP** | Should be built; not present today. | None; intent is enough. |
| **Future Scope** | Deliberately deferred. | None. |
| **TBD** | Unknown and not discoverable from the repository. | Stated so nobody guesses. |

Additional honesty rules used throughout:

- **No user research is claimed.** No interviews, surveys, usability sessions, or analytics exist. Where a
  workflow needs justification, it is justified by a stated goal, not by a hypothetical user quote.
- **No measured performance is claimed.** Every millisecond or second figure is a **[proposed]** target
  awaiting measurement. The only real timing in this codebase is the optimiser's own
  `runtime_ms` field, which measures solver time only, not page time.
- **No accessibility audit is claimed.** Contrast ratios in §6 are hand-computed from the CSS values that
  are actually in `styles.css`. No automated or manual audit with assistive technology was performed.
- **No certification or compliance coverage is claimed.** Framework references in the data
  (`framework_iso`, `framework_nist`, `framework_cis`) are catalogue labels attached by the seed data.
  No certification body has assessed this platform. See §17.
- **Every number in the worked examples is illustrative.** All values derive from the seeded
  synthetic dataset, and all money in the API is integer minor units (paise), never floats.

### Verification method used for this document

The API was started on a scratch copy of an empty database and the real responses were captured, so that
field names in §14 are the wire format rather than a guess. Confirmed during this review:

- `GET /api/overview`, `GET /api/catalog`, `GET /api/assessment`,
  `POST /api/optimise`, `GET /api/optimise/frontier`,
  `POST /api/scenarios/{code}/whatif`, `GET /api/ai/status` were called and their keys enumerated.
- `styles.css` tokens were converted to WCAG relative luminance and contrast ratios were computed.
- Full text of `index.html` (178 lines), `app.js` (423 lines) and `styles.css` (152 lines) was read.

---

## 1. System context and current state

### 1.1 What the product is

A single-organisation cyber risk quantification tool. It ingests or seeds an inventory of assets,
scenarios, findings and controls, computes Expected Annual Loss (EAL), lets a practitioner change an
assumption and see the effect, optimises a remediation budget under constraints, and lets an analyst
ask grounded questions in natural language. It also exports board, analyst and committee reports.

The core mental model the interface must make obvious:

1. Money is a distribution, not a point. Show a range and the reason for it.
2. The headline number is *adjusted for correlation* and is therefore **not** the sum of the rows.
3. Financial output is an **estimate, not a prediction**.
4. All data is synthetic, on every screen, without exception.

### 1.2 Actual current stack

The prompt for this specification suggested Streamlit if no frontend stack existed. **A frontend does
exist, and it is not Streamlit.** Selecting Streamlit would be a re-platforming decision, not a
documentation fix, so the real stack is documented here.

| Layer | Actual technology | Evidence |
|---|---|---|
| Delivery | FastAPI serving static files | `app/main.py`, `app/static/` |
| Markup | Hand-written HTML, single document | `app/static/index.html` (178 lines) |
| Logic | Vanilla JavaScript, single IIFE, no build step | `app/static/app.js` (423 lines) |
| Styling | Hand-written CSS with custom properties | `app/static/styles.css` (152 lines) |
| Charts | **None.** No charting library, no `<canvas>`, no `<svg>`. | `grep` for canvas/svg/chart/plotly/d3 returns no drawing code |
| State | One mutable global object, no framework | `app/static/app.js:3` |
| Transport | `fetch` with manual JSON and `await` | `app/static/app.js` `api()` helper |
| Rendering | Direct `innerHTML` string templates | e.g. `app/static/app.js:132-183` |
| Auth | Server-set HTTP-only session cookie | `app/static/app.js` `credentials: "same-origin"` |
| Dependencies | **Zero** front-end runtime dependencies | No `<script src>` to a CDN in `index.html` |

This is a defensible choice for an offline-capable evaluation prototype: no supply chain, no build,
no lockfile, and the whole client is two small text files. The cost is that every capability listed in
§8 as Proposed MVP has to be written by hand.

**React is a Future Scope option**, recorded in §18, not a recommendation for the next milestone. The
immediate work in this document is achievable without a framework, and a judge demo running from a
fresh clone with `pip install -r requirements.txt` is more valuable than a component tree.

### 1.3 Current capability map

Counting the five navigation tabs in `index.html:39-45` against the eleven essential screens this
specification requires:

| Required screen | Current state | Notes |
|---|---|---|
| 1. Login | **Verified Implemented** | `index.html:25-37`. Includes banner and inline demo accounts. |
| 2. Data & Validation | **Partially Verified Implemented** | Upload, dataset table, quarantine table. No templates, rejected-row download, unmatched findings, freshness, demo reset. |
| 3. Executive Dashboard | **Partially Verified Implemented** | KPIs and ranked scenario table. No trend chart, no BU comparison, no top-contributor chart, no drill-down. |
| 4. Risk Explorer | **Partially Verified Implemented** | Asset, control and scenario tables with `details` expansion. No org→BU→asset→scenario→finding navigation. |
| 5. What-if Simulator | **Partially Verified Implemented** | Single `p0` override via `window.prompt`. Not a simulator. See §8.5. |
| 6. Investment Optimizer | **Partially Verified Implemented** | KPIs, selected table, rejected table, frontier table. Frontier is a table with CSS bars, not a curve. |
| 7. Ask | **Verified Implemented** | Question box, answer, grounding, refusal, suggested chips. |
| 8. Compliance Mapping | **Not Implemented** | No UI. `framework_*` fields exist in data but are never surfaced as a coverage view. |
| 9. Reports & Export | **Partially Verified Implemented** | Preview plus four downloads. No error/empty handling and no redaction choice. |
| 10. Assumptions & Settings | **Not Implemented** | No UI. `sle_low_multiplier`, `sle_high_multiplier`, `PROBABILITY_MULT_*`, `rho_used` and currency are not user-editable. |
| 11. Audit Log & Users | **Not Implemented** | `GET /api/audit` exists in `app/main.py:405`; no UI calls it. |

The dominant pattern: **the data exists in the API, and the frontend has not yet been asked for it.**
`by_business_unit`, `by_category`, `by_actor`, `freshness`, `confidence_reasons`, `incomplete`,
`rho_used` and `findings_summary` are all in the assessment response. Most are unrendered. Several
cheap, high-value screens in §8 are therefore mostly rendering work, not new modelling.

---

## 2. Roles, permissions, and the visibility rule

### 2.1 Actual roles

Three roles exist in `app/config.py:52` and `app/db.py:120` and are exposed in the session payload. UI labels are the ones the
user sees; capability is the server's decision.

| Role value | UI label | Intended audience | Home screen |
|---|---|---|---|
| `ciso` | Executive | Board-facing risk owner | Executive Dashboard |
| `analyst` | Analyst | Practitioner doing the modelling | Risk Explorer |
| `administrator` | Admin | Data owner, reviewer, operator | Data & Validation |

### 2.2 The visibility rule

**Hiding a control in the UI is a usability courtesy, never a security control.** Every restricted
screen and control must also be enforced server-side; the correct posture is that the client requests
what it may have and the server refuses what it may not.

**Asking a question is available to all three roles.** `POST /api/ask` is gated on the `ai.ask`
capability, and `app/config.py:58-70` grants `ai.ask` to `ROLE_ADMIN`, `ROLE_ANALYST` and
`ROLE_EXEC` alike. Verified live: a `ciso` session receives `200` with a template answer. An earlier
draft of this document claimed a `403` for the Executive role; that was wrong, and it is corrected
here and in the `FR-G-10` criteria in §10.3. The grant is defensible for a board-facing tool — the
natural-language interface exists precisely so non-technical stakeholders can query it — and the
correct UI behaviour is therefore to show the Ask screen to everyone, while the *content* available to
each role still comes from the same server-side assessment.

The only AI-related refusal the server actually performs today is the **scope** refusal in
`app/ai.py:368` — out-of-scope questions are answered from the deterministic template with
`refused: true`, not a `403`. §8.7 covers that path.

Visibility matrix. Cells marked **[P]** are proposed behaviour; the Ask row is the server's actual grant (`ai.ask` for all three roles), not a UI decision.

| Screen / action | Executive | Analyst | Admin |
|---|---|---|---|
| Executive Dashboard | Yes | Yes | Yes |
| Risk Explorer | View | Edit | Edit |
| What-if Simulator | No | Yes | Yes |
| Investment Optimizer | View | Yes | Yes |
| Ask | **Yes** | Yes | Yes |
| Compliance Mapping | View | Yes | Yes |
| Reports & Export | Board summary only **[P]** | All four | All four |
| Data upload | No | No | Yes |
| Assumptions & Settings | No | View **[P]** | Yes **[P]** |
| Audit Log | No | No | Yes **[P]** |
| User management | No | No | Yes **[P]** |

The `[P]` markers matter. Right now an Executive can reach What-if and Optimise by URL-free tab
clicking, because visibility is not enforced client-side at all. Before the demo, either hide or
disable those tabs per role, or accept the limitation openly and say so in the script.

---

## 3. Information architecture

### 3.1 From five tabs to eleven screens

```
Cyber Risk Quantification
├── (S1) Login ...................................... unauthenticated
└── App shell
    ├── Portfolio group
    │   ├── (S3) Executive Dashboard ............... S1
    │   ├── (S4) Risk Explorer ..................... S1
    │   ├── (S5) What-if Simulator ................. S2
    │   └── (S6) Investment Optimizer .............. S2
    ├── Intelligence group
    │   └── (S7) Ask ................................. S2
    ├── Compliance group
    │   └── (S8) Compliance Mapping ................. S2
    ├── Data group
    │   ├── (S2) Data & Validation ................. S3
    │   └── (S10) Assumptions & Settings ........... S3
    ├── Output group
    │   └── (S9) Reports & Export .................. S1
    └── Governance group
        └── (S11) Audit Log & Users ................. S3
```

Groups are a **proposed** organisational device. A simple flat nav of eleven items, or a left rail
collapsing to a hamburger below 900px, both serve. The group structure exists mainly to justify why
Ask is a peer of the analytics screens rather than a hidden utility.

### 3.2 Navigation principles

1. **The default landing screen depends on role.** Executive lands on S3, Analyst on S4, Admin on S2.
   Landing on a blank Exposure tab and making a CISO find the number is a real cost.
2. **URL-addressable.** Each screen gets a hash route (`#/optimise`), so a judge can deep-link, and
   the browser Back button works. Not implemented today.
3. **No modal dialogs for core flows.** See §8.5; `window.prompt` is the single worst interaction in
   the current build and is replaced by an inline panel.
4. **Cross-screen navigation carries context.** Drilling from S3 to S4 to S5 keeps the selected
   business unit and asset. Losing that context on every hop is what makes dashboards feel shallow.
5. **The tab strip is a tab list, semantically.** `role="tablist"`, `role="tab"`, `aria-selected`,
   `aria-controls`, arrow-key navigation, and a visible focus ring. None of this exists today.

---

## 4. Design system and visual language

### 4.1 The existing visual language is good; keep it

`styles.css` defines a coherent, deliberate dark palette via custom properties. It is consistent,
modern, and appropriate for a security operations tool. **This document proposes extending it, not
replacing it.** A visual rebrand before the demo would cost days and add no persuasive value.

Current tokens, verbatim from `styles.css:1-6`:

```css
--bg: #0d1117;   --panel: #151b24;  --panel-2: #1b232f;  --line: #263041;
--text: #e6edf3; --muted: #8b98a9;  --accent: #4c9ffe;
--good: #3fb950; --warn: #d29922;  --bad: #f85149;
```

Type: `14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`. Tabular numerals
are already applied via `font-variant-numeric: tabular-nums` on `.kpi .value` and `td.num`, which is
the correct choice for a column of rupees and should be preserved.

### 4.2 Proposed additions

| Token | Value | Purpose |
|---|---|---|
| `--focus` | `#79c0ff` | Focus ring, 2px + 2px offset, on every interactive element |
| `--line-strong` | `#3d4a5f` | Replaces `--line` for control boundaries needing 3:1 (§6.2) |
| `--stale` | `#a371f7` | Stale-data indicator, distinct from warn/medium |
| `--radius` | `10px` | Panel radius, already consistent |
| `--space-1..6` | `4 8 12 18 24 32px` | Replace ad-hoc margins |

Colour is never the sole carrier of meaning. Every confidence band, severity and status pill pairs
colour with a text label, and receives an icon in Proposed MVP so it survives greyscale and the common
red-green colour vision deficiencies. The existing `.pill` component already includes the text label,
so this is a small change.

### 4.3 Confirmed and rejected colours

- **Confirmed:** the dark palette, the amber synthetic-data banner, and the three-tier confidence
  pill (`.pill.low`, `.pill.medium`, `.pill.high`).
- **Rejected:** a light theme, a second accent colour competing with `#4c9ffe`, and any red/green
  pairing used without a text label.
- **TBD:** brand logo, brand typeface, and a customer-facing colour palette. The product is currently
  branded `Cyber Risk Quantification` in text only (`index.html:12`).

---

## 5. Currency, number, and date formatting

### 5.1 Money

**Rule: never compute, scale, or convert money in the client.** The API returns integer minor units
and `currency` (`"INR"`) with `symbol` (`"₹"`). The client divides by 100 for display and nothing
else. Division by 100 for display is a unit conversion, not a business calculation, and is the only
arithmetic permitted on a financial field in the client.

Current implementation, verbatim from `app/static/app.js:8-10`:

```js
function money(minor) {
  if (minor === null || minor === undefined) return "n/a";
  return "₹ " + (minor / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
```

This produces correct Indian digit grouping. Note it emits `"₹ "` with a trailing space, so the
abbreviation work in §5.2 must normalise the spacing rather than concatenate onto this string. Verified
against live data: `eal_minor = 1106227077` renders as `₹ 1,10,62,271`, using the lakh/crore grouping
of the 2-2-3 pattern.

### 5.2 Proposed lakh/crore abbreviation

The requirement is to abbreviate, and the current formatter does not: a portfolio loss of
₹1,10,62,271 is eight digits and unreadable at a glance. Proposed **MVP** rule:

| Magnitude | Display | Example |
|---|---|---|
| < 1 lakh | full, grouped | `₹45,892` |
| 1 lakh – < 1 crore | two decimals, `L` | `₹34.86 L` |
| 1 crore – < 100 crore | two decimals, `Cr` | `₹1.11 Cr` |
| ≥ 100 crore | integer, `Cr` | `₹248 Cr` |

Worked transformation of verified live values:

| Raw minor units | Full (current) | Abbreviated (proposed) |
|---|---|---|
| `1106227077` | `₹1,10,62,271` | `₹1.11 Cr` |
| `348566177` | `₹34,85,662` | `₹34.86 L` |
| `199099294` | `₹19,90,993` | `₹19.91 L` |
| `440000000` | `₹44,00,000` | `₹44.00 L` |

**Every abbreviated figure must have its exact value available on hover, focus, and in the exported
report.** A judge who cannot expand `₹1.11 Cr` to `₹1,10,62,271` will assume the number is rounded or
invented. Precision is a credibility requirement, not a nicety.

Rounding rule: abbreviate for display only, using half-up to the stated decimals. Never round the
value used in a comparison, a sort, or a "top 5" cut. Rank on the exact integer, abbreviate after.

### 5.3 Percentages and ratios

- `p_inherent`, `p_residual`, `mitigation_factor` are **0..1 floats** in the API. Convert once, at the
  display boundary, to a percentage with 2 decimal places. `app.js` already does this correctly via
  `pct()`.
- ROSI is a unitless ratio (`0.3257` in the verified response). Display 2 decimals, and **always label
  it as a ratio, never a percentage** — `0.33` and `33%` are different claims and conflating them is
  how a board deck misleads.
- `lambda`, `rho_used` are unitless. Display 3 decimals, or hide behind a details disclosure.

### 5.4 Critical correction: the EAL range is not a percentile range

The requirement asks for a range labelled `₹X – ₹Y (P10–P90)`, explicitly conditional on "the model
defines those percentiles".

**The model does not.** `risk.py:635-636` computes the bounds as:

```python
eal_low  = int(round(eal * scenario.sle_low_multiplier * PROBABILITY_MULT_LOW))   # 0.5
eal_high = int(round(eal * scenario.sle_high_multiplier * PROBABILITY_MULT_HIGH)) # 1.5
```

`PROBABILITY_MULT_LOW = 0.5` and `PROBABILITY_MULT_HIGH = 1.5` (`risk.py:35-36`) are fixed constants.
The bounds are a **sensitivity band from an assumed ±50% swing on SLE and a probability multiplier**.
There is no percentile, no Monte Carlo, and no sampling anywhere in the codebase.

Therefore:

- **Forbidden:** any label of the form P10–P90, "90% confidence interval", "5th–95th percentile", or
  "1-in-20 year range". These are false precision and would be the single most damaging claim in the
  demo if challenged.
- **Required label:** `Sensitivity range (SLE ±50%, probability ×0.5–1.5)`, with the source of the
  assumption shown in the disclosure, per `SEC-MOD-01` in `docs/SECURITY_ACCESS_REQUIREMENTS.md`.

Verified live portfolio example: `eal_minor = 1106227077`, `eal_low_minor = 387179477`,
`eal_high_minor = 2157142800`, which displays as `₹1.11 Cr` with sensitivity range
`₹38.72 L – ₹2.16 Cr`. A judge's most likely challenge — "is that a confidence interval?" — must be
answered with "no, it is a sensitivity band on stated multipliers", which is why the label has to
carry the assumption.

### 5.5 Dates and provenance

- Timestamps arrive as ISO-8601 (`loaded_at`, `oldest_observed_at`). Render in the viewer's local
  timezone, with the full ISO value in `title` and in exports. A judge in a different timezone than the
  seed data should not be confused.
- Relative time (`3 days ago`) is a Proposed MVP addition, and must degrade to an absolute date when a
  screen reader or a test harness cannot resolve it.
- Display the current **assessment run time** wherever a figure is shown. Blocker: there is no run
  identifier. The assessment is recomputed on every request and nothing is persisted, which is finding
  **F-1** in the technical architecture document. Until runs are persisted, show "Computed
  <timestamp of this page load>" and do not imply a stored, reproducible run ID.

---

## 6. Accessibility and the measured colour system

### 6.1 Target

**Proposed** target: WCAG 2.1 Level AA. This is a target, not a claim. No automated scan
(axe, Lighthouse) and no manual screen-reader pass has been performed. The contrast figures below are
hand-computed from the actual CSS values; everything else about the current accessibility posture is
unverified.

### 6.2 Contrast: computed results

Ratios computed from the real tokens using the WCAG 2.1 relative-luminance formula.

| Pair | Ratio | Requirement | Result |
|---|---|---|---|
| Body text on background | 16.02 | 4.5:1 | Pass |
| Body text on panel | 14.64 | 4.5:1 | Pass |
| Muted text on background | 6.45 | 4.5:1 | Pass |
| Muted text on panel | 5.90 | 4.5:1 | Pass |
| Muted text on panel-2 | 5.39 | 4.5:1 | Pass |
| Accent text on panel | 6.34 | 4.5:1 | Pass |
| Error text on panel | 5.16 | 4.5:1 | Pass |
| Success text on panel | 6.81 | 4.5:1 | Pass |
| Button label on accent | 6.91 | 4.5:1 | Pass |
| Banner text on banner background | 10.00 | 4.5:1 | Pass |
| Confidence pill — high | 8.38 | 4.5:1 | Pass |
| Confidence pill — medium | 8.20 | 4.5:1 | Pass |
| Confidence pill — low | 8.06 | 4.5:1 | Pass |
| Informational pill | 8.00 | 4.5:1 | Pass |
| **`--line` border on `--panel`** | **1.30** | **3:1** | **Fail** |

**The single confirmed accessibility defect.** `--line: #263041` against `--panel: #151b24` is
1.30:1, far below the 3:1 that WCAG 2.1 SC 1.4.11 requires for the boundary of an interactive control.
Input fields, select elements and ghost buttons are all bounded by `--line`, so their outlines are
effectively invisible; a keyboard user cannot see where focus currently is, because the default focus
ring is the only affordance and it is the same low-contrast hue.

Proposed MVP fix: add `--line-strong: #3d4a5f` (3.02:1 on panel) and apply it to the borders of
`input`, `select`, `button.ghost`, `.tab` and `table` header dividers. Body text contrast needs no
change. This is a two-line CSS change with an outsized effect on the accessibility story, and it is
cheap enough to do before the demo rather than logging as a post-demo ticket.

### 6.3 Structure and keyboard

Current gaps, all Proposed MVP:

- Tabs are `<button>` elements in a `<nav>` with no `role="tablist"`, no `aria-selected`, no
  arrow-key handling, and no `tabindex` management. A screen reader announces a list of buttons, not
  a tab widget.
- No `aria-live` region anywhere. `toast()` at `app.js:42-50` is a visual-only affordance; a
  non-sighted user receives no confirmation that a login, upload or optimise succeeded. This is a
  functional accessibility bug, not a polish item.
- Tables use `<th>` without `scope`, and numeric columns rely on a `.num` class for visual alignment
  with no programmatic indication of direction.
- `<details>`/`<summary>` is used for the "why" confidence disclosure and the loss-component expansion.
  This is genuinely good: it is keyboard operable and correctly announced. Preserve this pattern, and
  adopt it in place of `window.prompt`.
- The login inputs carry correct `autocomplete="username"` and `autocomplete="current-password"`. The
  password field is correctly `type="password"`. Keep these.
- Colour is not the sole indicator anywhere today, because all pills include a text label. Preserve
  that property; see §4.2.

---

## 7. Global interface elements

### 7.1 Elements present on every authenticated screen

| Element | Requirement | Status |
|---|---|---|
| Synthetic data badge | Persistent, not dismissible, on every screen showing data | **Verified Implemented** |
| Signed-in identity and role | Name, role, session expiry | **Verified Implemented** (text only) |
| Logout | Always reachable | **Verified Implemented** |
| Data freshness indicator | Age of the oldest input, with a band | **Proposed MVP** |
| Assessment provenance | Compute time, and run ID once runs persist | **Proposed MVP** (compute time only today) |
| Financial disclaimer | "Estimate, not a prediction" | **Proposed MVP** |
| Global search | Filter across assets and scenarios | **Future Scope** |

The synthetic-data banner at `index.html:18-22` is the strongest existing compliance control in the
frontend and is already correctly worded: it states the data is invented, that it exists for product
evaluation, and that it is not a measurement of any real organisation. It must remain above the fold
on every screen, must not be dismissible, and must not be a one-time dismissible modal.

### 7.2 The freshness gap

`GET /api/assessment` returns a complete freshness block, verified live:

```json
"freshness": {
  "sources": { "SimulatedScanner": { "age_days": 11.93, "band": "aging",
                                     "oldest_observed_at": "2026-09-18T06:00:00+00:00" } },
  "thresholds": { "green_days": 7, "amber_days": 30 }
}
```

`grep` confirms the frontend never references `freshness`, `age_days` or `oldest_observed`. A stale
model is presented with exactly the same authority as a fresh one. Worse, the same assessment response
reveals that `S1`'s top confidence reason is **"Underlying finding data is 12 days old"** — the
information is computed and then thrown away. Note that the `band` value the server returns is
`"aging"`, not `"amber"`; render the server's string and do not re-derive it client-side.

Proposed MVP: a header-level freshness chip, `Data 12 days old · aging`, with a dot in the colour
mapped to the band per §4.2, plus a per-source breakdown in the Data screen. This is a small change to
a screen that already has the data, and it directly supports `SEC-F-02` and the confidence story.

### 7.3 Session and identity

The session chip at `app/static/app.js:68-70` currently renders `` `${username} · ${role}` `` in plain
text. Note that `state.user.role` is the raw server value — `administrator`, not a display label — so
an Admin currently sees the internal role string. Proposed MVP: avatar initials, full display name, the
UI label from §2.1, and a session-expiry countdown when the server supplies one. The cookie is
HTTP-only, which is correct, and the client cannot and should not attempt to read it.

---

## 8. The eleven essential screens

Wireframes are ASCII schematics showing layout and hierarchy, not pixel specifications. Every
requirement below is given a status. Requirement IDs in the form `FR-S3-01` are expanded with
Given/When/Then criteria in §10.

---

### 8.1 Screen S1 — Login

**Purpose.** Establish an authenticated session and set the user's expectation that the data is
synthetic. **Status: Verified Implemented.**

```
+----------------------------------------------------------------------+
|  Cyber Risk Quantification                                            |
|  expected annual loss · budget optimisation · grounded analyst       |
+----------------------------------------------------------------------+
| ####################  Synthetic demonstration data.  ################|
|  Every figure is generated from an invented dataset. Not a           |
|  measurement of any real organisation.                               |
+----------------------------------------------------------------------+
|                                                                      |
|   Sign in                                                            |
|   +---------------------------+  +---------------------------+       |
|   | Username   [analyst     ] |  | Password   [**********] |       |
|   +---------------------------+  +---------------------------+       |
|   [ Sign in ]                                                       |
|                                                                      |
|   Prototype accounts: analyst/analyst123, ciso/ciso123,              |
|   admin/admin123.                                                   |
|   ! Enter a valid username and password.                            |
+----------------------------------------------------------------------+
```

**Data fields.** All local until submit. No server read. On success, the session response supplies
`username`, `role`, and expiry; on boot `GET /api/me` determines whether to show this screen at all.

**Actions and behaviour.**

- `POST /api/login` with `{username, password}`.
- `GET /api/me` on page load; skip this screen entirely when a valid session already exists. **Verified
  Implemented** at `app.js:422-423`.
- Successful login calls `enterApp()`, which issues `overview`, `catalog`, `assessment` and `ai/status`
  in parallel, then routes by role per §3.2.
- Logout is `POST /api/logout`, then hard-navigate to clear all client state. **Verified Implemented.**

**Validation.** Required, non-empty, no client-side format rules. The server owns credential
verification. Empty submit shows an inline error without a network call **[P]**.

**States.** Loading (button disabled, spinner). Error (inline, `role="alert"`, no raw stack). Success.
Locked-out state: after repeated failures show a rate-limit notice, **never** a hint that the username
exists.

**Current defects to fix.**

1. **Credentials are pre-filled in the HTML source** (`index.html:28-30`, `value="analyst"` and
   `value="analyst123"`) and all three accounts are listed in visible text. Pre-filling makes a judge
   think the login is fake; listing passwords is `SEC-AUTH-04`. **Replace with empty inputs and a
   single hint: "Demo credentials are in the README."** Keep the role names, drop the passwords.
2. The banner appears *below* the header but is not announced to assistive technology. Add
   `role="note"` and include it in the landmark structure.

---

### 8.2 Screen S2 — Data & Validation

**Purpose.** Let a data owner load, validate and trust the input, and see precisely what was rejected
and why. **Status: Partially Verified Implemented.**

```
+----------------------------------------------------------------------+
|  Header · Data 12 days old · Amber   [Analyst ▾]  [Log out]           |
+----------------------------------------------------------------------+
|  Data & Validation                                                    |
|                                                                      |
|  Upload                                                              |
|  Dataset type [Assets ▾]  File [Choose file]  [Upload]               |
|  Template: [Download assets template CSV]                            |
|  ! Rejected rows are quarantined, never silently dropped.            |
|                                                                      |
|  Datasets                                                             |
|  | Type   | File          | Status | Total | OK | Updated | Qtn | Loaded  | Synth |
|  | Assets | assets.csv    | ok     | 5     | 5  | 0       | 0   | 12:04   | yes   |
|                                                                      |
|  Unmatched findings                        [Download rejected rows]   |
|  | Finding | Asset | Reason |                         |              |
|  | none                                                       |              |
|                                                                      |
|  Validation issues                                                   |
|  [synthetic_bundle: all 5 assets are synthetic]                      |
|                                                                      |
|  Demo controls                                        [Reset demo]  |
+----------------------------------------------------------------------+
```

**Data fields.** From `GET /api/overview` (verified live): `counts{assets, findings, controls, scenarios,
actions, datasets, quarantine}`, `recent_datasets[]{id, dataset_type, filename, status, rows_total,
rows_ok, rows_updated, rows_quarantined, loaded_at, synthetic}`,
`synthetic_asset_share`, `latest_dataset_issues{synthetic_bundle}`. From `GET /api/catalog`:
`findings_summary{total, open, open_exploitable, unmatched, by_severity{critical, high, medium, low}}`.

**Actions.**

- `POST /api/ingest` multipart upload, `POST /api/demo/reset`. **Verified Implemented.**
- Download dataset template **[P]**, download rejected rows **[P]**.

**Validation.** Client checks extension and a **[proposed]** 10 MB cap before upload, purely to give a
fast message. All real validation is server-side and row-level.

**States.** Idle. Uploading with a progress indicator **[P]**. Success with a per-dataset row summary.
Partial success — the important one: 40 uploaded, 37 accepted, 3 quarantined, with the reasons listed
and downloadable. Quarantined-rows warning banner when `quarantine > 0`. Error with the server's
message. Permission denied for Executive and Analyst roles.

**Gaps.**

- `unmatched` is computed in the API and never displayed. An unmatched finding means an uploaded
  finding references an asset the system does not have, so it is silently excluded from every
  calculation. That is exactly the kind of silent data loss this screen exists to surface. **Must
  render.**
- **No freshness display** (§7.2), so "Rows loaded 12 days ago" is invisible.
- No rejected-row download, so a data owner cannot fix and resubmit. **Proposed MVP.**
- No template download, so a first-time uploader has to guess the schema.
- No demo-reset control in the UI, which makes the demo non-repeatable after a messy upload.

---

### 8.3 Screen S3 — Executive Dashboard

**Purpose.** Answer "how much risk does this organisation carry, is it going up, and where should I
spend money?" in ten seconds, with no interaction. **Status: Partially Verified Implemented.**

```
+----------------------------------------------------------------------+
|  Header · Data 12 days old · Amber              [Executive] [Logout] |
+----------------------------------------------------------------------+
|  ###  Synthetic demonstration data                                  |
+----------------------------------------------------------------------+
|  Executive Dashboard                                                 |
|  Portfolio EAL  ₹1.11 Cr  |  Sensitivity ₹38.72 L – ₹2.16 Cr                 |
|  Estimate, not a prediction. Computed 30 Sep 2026 14:22.             |
|                                                                      |
|  +------------+ +------------+ +------------+ +------------+        |
|  | ASSETS     | | SCENARIOS  | | ACTIONS    | | CONFIDENCE |        |
|  | 5          | | 6          | | 12         | | Medium ·61 |        |
|  +------------+ +------------+ +------------+ +------------+        |
|                                                                      |
|  Top contributors                 By business unit                  |
|  | 1 S3 Ransomware · PGW   ████  | Corporate IT ████ ₹35.29 L    |
|  | 2 S1 Ransomware · OMS   ███   | Payments     ███  ₹30.67 L    |
|  | 3 S2 Credential · IDP   ██     | Retail       ███  ₹26.14 L    |
|  | 4 S4 Exfiltration · Fin ██     | Finance      ██   ₹18.52 L    |
|  | 5 S6 BEC · AP           █      |                              |
|                                                                      |
|  Shares are of the unadjusted total (₹1,31,06,394) and sum above    |
|  100% by design; the headline is correlation-adjusted.              |
|  Top 3 account for 72% of portfolio EAL.          View breakdown →  |
+----------------------------------------------------------------------+
```

**Data fields.** `assessment.eal_minor`, `eal_low_minor`, `eal_high_minor`, `eal_unadjusted_minor`,
`currency`, `symbol`, `confidence`, `confidence_band`, `by_asset{}`, `by_business_unit{}`,
`by_category{}`, `by_actor{}`, `rho_used{}`, `incomplete[]`, `excluded_findings`, `freshness{}`.

**Actions.** Drill into S4. Adjust budget → S6. Export board summary → S9. Change assumptions → S10.

**States.** Loading skeleton. Populated. Partially incomplete — show a warning that
`incomplete.length > 0` and that excluded findings are not counted. Low confidence (`band` Low) with a
prominent caveat. Stale data chip. Error with retry.

**Charts — none exist today.** `grep` confirms no charting library, `<canvas>` or `<svg>`. All three
charts above are **Proposed MVP** and need a decision:

**Chart inventory.** The specification requires five specific visualisations. Here is where each one
stands, so none is quietly dropped:

| # | Required chart | Screen | Data available? | Status | Decision |
|---|---|---|---|---|---|
| 1 | Exposure trend, 12 months | S3 | **No.** No time series exists in the model | **Blocked** | Ship the confidence-contribution breakdown instead, or build persistence first (§18.1) |
| 2 | Top-contributor bar chart | S3 | **Yes.** All six `scenarios[]` with `eal_minor` | Proposed MVP | CSS/SVG bars; no dependency needed |
| 3 | Baseline-versus-scenario comparison | S5 | **Yes.** The API returns a full assessment per override | Proposed MVP | Grouped bars; the core of the what-if screen |
| 4 | Investment-versus-risk-reduction curve | S6 | **Yes.** All ten `frontier[]` points | Proposed MVP | SVG polyline; mark the selected budget |
| 5 | Framework coverage by control | S8 | **No.** No requirement catalogue exists | **Forbidden as specified** | Show the measured-versus-assumed control split instead; never a coverage percentage (§8.8) |

**Framework mapping and coverage tracking, proposed scope (not certification-level).** The mapping
data that does exist is `framework_iso`, `framework_nist` and `framework_cis` on each control, and
`ce_source` distinguishing measured from assumed effectiveness. Proposed MVP is therefore: filter
controls by framework, domain and evidence source; show the measured-versus-assumed split; and link
each control to the scenarios it affects. **Out of scope: any clause-level requirement catalogue,
coverage percentage, or compliance verdict.** §8.8 explains why a coverage number is currently
impossible rather than merely unimplemented, and `FR-S8-02` forbids displaying one.

Three of the five are pure rendering work on data that is already returned. One is blocked on the
model. One cannot be built honestly at all, and substituting a fabricated coverage number for it would
be the worst outcome available.

- **Trend:** 12 months of EAL **does not exist**. The model has no time series. This is the single
  largest data gap in the specification. Either build a persistence layer plus a history model, or
  replace the trend panel with something honest — a **confidence-contribution breakdown** (which can be
  computed from `confidence_reasons` today). Shipping a fabricated or single-point "trend" would
  violate the honesty rule at the top of this document. Recorded as a blocker in §18.
- **Top contributors:** rank the top 5 by `eal_minor`. Data is present; only the chart is missing.
  CSS bar glyphs in a `<div>`, consistent with the existing `.bar` component, are sufficient and avoid
  adding a dependency.
- **By business unit:** `by_business_unit` is already in the response and is entirely unrendered. This
  is the cheapest meaningful chart in the product and should be first.

**Mandatory disclosure.** The existing `#overlap-note` (`app.js:180-183`) correctly explains that shares
are of the unadjusted total and therefore sum above 100% while the headline is correlation-adjusted.
**This is exemplary and must be preserved on every view that shows shares.** Keep the wording, and
extend it to any new chart.

---

### 8.4 Screen S4 — Risk Explorer

**Purpose.** Let an analyst find *why* the number is what it is, and trace it to a specific asset and
control. **Status: Partially Verified Implemented.**

```
+----------------------------------------------------------------------+
|  Portfolio › Retail › A1-OMS-DB-PROD › S1            [Reset]         |
+----------------------------------------------------------------------+
|  Filters  BU [All ▾]  Actor [All ▾]  Category [All ▾]  [Search 🔍]  |
|  Showing 6 of 6 scenarios · ranked by EAL                             |
|                                                                      |
|  | # | Scenario         | Asset      | SLE      | p(inh) | p(res) | EAL | Confidence | |
|  | 1 | Ransomware OMS   | A1-OMS-... | ₹9.80 Cr | 7.06%  | 3.56%  |₹34.86L| [Low 54] ▾ |
|  |   | S1 · unknown actor                                            |            |
|  | 2 | ...                                                          |            |
|                                                                      |
|  ▾ S1 — loss components and control detail                           |
|      | component                     | amount | basis              |
|      | lost_revenue_downtime         |₹22.00L| 48h, daily rev     |
|      | partner_sla_penalty           |₹40.00L| service credits    |
|      | control C-01 Network segment. | 20%    | assumed            |
|      | control C-02 Endpoint detect. | 30%    | benchmark          |
|                                                                      |
|  Why is confidence Low?                                               |
|  • At least one required control effectiveness is assumed            |
|  • Underlying finding data is 12 days old                             |
|  Every component above is marked ASSUMED in its source reference.     |
+----------------------------------------------------------------------+
```

**Data fields.** Scenario: `scenario_code`, `name`, `asset_id`, `business_unit`, `sle_minor`,
`sle_low_minor`, `sle_high_minor`, `p_inherent`, `mitigation_factor`, `p_residual`, `lambda`,
`eal_minor`, `eal_low_minor`, `eal_high_minor`, `confidence`, `confidence_band`, `confidence_reasons`,
`group_id`, `group_peers`, `breakdown[]{component_code, basis, value_minor, hours, record_count,
source_ref, amount_minor, unresolved}`, `control_detail[]{control_code, name, domain, ce_base,
ce_applied, changed, ce_source, ce_evidence_ref, framework_iso, framework_nist, framework_cis}`,
`complete`, `incomplete_reasons`. Aggregates: `by_asset`, `by_business_unit`, `by_category`,
`by_actor`. Assets: `asset_id`, `name`, `business_unit`, `business_service`, `criticality`,
`exposure_class`, `status`, `daily_revenue_minor`.

**Actions.** Filter, sort, search, expand, drill to S5, drill to the audit trail of a data point.

**States.** Populated. Filtered-to-zero with a "clear filters" affordance. Loading. Stale. Error.
Low confidence per row.

**What is already good.** The `details`/`summary` disclosure at `app.js:146-147` renders
`confidence_reasons` as a per-row "why" panel. This is exactly the design the requirement asks for and
it is already correct — it surfaces *reasons*, not just a number. Preserve it. The control-detail table
at `app.js:170-178` correctly shows `ce_base` versus `ce_applied` and flags changed controls, which is
how a reviewer audits the model rather than trusting it.

**Confirmed defects.**

1. **`threat_actor` is a dead field.** `app.js:136` renders `esc(s.threat_actor || "unknown actor")`,
   but no scenario object has that key — verified across all six live scenarios. **Every row displays
   "unknown actor"** while the API separately provides a correct `by_actor` aggregate. Either add
   `threat_actor` to the response or remove the column. Showing "unknown actor" six times in a judge
   demo reads as broken.
2. **No drill-down path.** There is no organisation → BU → asset → scenario → finding navigation, and
   no breadcrumb. The three tables (scenario, asset, control) sit side by side and are not connected.
3. No freshness indicator per source.
4. The Asset and Control tables do not cross-link to the selected scenario.

---

### 8.5 Screen S5 — What-if Simulator

**Purpose.** Let an analyst change an assumption and immediately see the effect on portfolio risk,
**without destroying the baseline**. **Status: Partially Verified Implemented — highest-priority fix in
this document.**

```
+----------------------------------------------------------------------+
|  What-if — scenario S1                            [Reset to baseline]|
+----------------------------------------------------------------------+
|  Baseline                                                            |
|  +------------+ +------------+ +------------+ +------------+         |
|  | EAL        | | S1 SLE     | | p inherent | | p residual |         |
|  | ₹1.11 Cr   | | ₹9.80 Cr   | | 7.06%      | | 3.56%      |         |
|  +------------+ +------------+ +------------+ +------------+         |
|                                                                      |
|  Change scenario S1                                                   |
|  Inherent probability p0                                              |
|  [        0.0706        ]  range 0.0001 – 0.50                      |
|  ├────────●───────────────────────┤                                  |
|  Current 0.0706   Stress ×1.5 → 0.1059                               |
|  [Apply]  [Reset]                                                    |
|                                                                      |
|  Projected                                                            |
|  | Metric  | Baseline   | What-if    | Delta                        |
|  | S1 EAL  | ₹34.86 L   | ₹50.02 L   | +₹15.16 L  ▲ +43.5%          |
|  | Portfol.| ₹1.11 Cr   | ₹1.14 Cr   | +₹2.63 L   ▲ +2.4%           |
|  | p res   | 3.56%      | 4.36%      | +0.80 pp  ▲                  |
|  | Conf    | Medium 61  | Medium 60  | -1                                |
|                                                                      |
|  Baseline retained. Reset to return to the as-ingested model.        |
+----------------------------------------------------------------------+
```

**Data fields.** `POST /api/scenarios/{code}/whatif` with `{p0}` returns `{assessment: {...}}` — the
**entire recomputed assessment**, verified live for `S1` with `p0 = 0.2`, which returned
`eal_minor = 2074262894` (₹2.07 Cr), `confidence 58`, `confidence_band "Medium"` and all six
scenarios. The override itself verifiably works: baseline `S1` `p_inherent` is `0.070571` and the
what-if response returns `0.272675`, with `S1` EAL rising from `348566177` to `1346794062`. **The API
contract is sound; the frontend handling of it is what is broken.** Plus the client's stored baseline
for comparison, and `breakdown`, `control_detail` and `confidence_reasons` for the changed scenario.

**Validation.** `p0` must be a finite number in `(0, 0.5]`. The current check at `app.js:199` is
correct — reject non-finite, `<= 0`, `> 0.5` — and must be preserved, with the error surfaced
**inline next to the field** rather than in a transient toast.

**States.** Idle. Applying (inline spinner, controls disabled). Projected. Out-of-range (inline).
Resetting. Error. **Baseline-lost is the state to design against — it should be impossible.**

**Confirmed defects — this is the worst interaction in the build.**

1. **`window.prompt` is used** (`app.js:194-196`). A browser modal is unstyleable, not screen-reader
   friendly, not translatable, blocks the page, and cannot show a slider, a range hint, or a projected
   result. Replace with the inline panel above. No dispute.
2. **The baseline is destroyed with no way back.** `app.js:202-205` overwrites
   `state.assessment` with the what-if result. After one override, the "baseline" figure is gone; the
   only record of the change is a `toast()` that disappears after 3.2 seconds. The Analyst can no
   longer answer "what is our actual exposure?" without a page reload. **This is a correctness bug,
   not a UX preference.** The fix is architectural: keep `state.baseline` immutable and render
   `state.whatif` alongside it, with a persistent "Return to baseline" control.
3. **The suggested value is arbitrary.** `app.js:193` proposes `min(0.5, p0 * 1.5)`, a bare 50% bump
   with no stated meaning. Label it for what it is — "×1.5 stress" — or drop it.
4. **No baseline-versus-projected comparison.** The API returns a full assessment, so a real delta
   table is possible today. This is the actual value of a what-if screen and it is not on screen.
5. Only **inherent** probability (`p0`) is adjustable. `mitigation_factor`, `sle_*_multiplier` and
   `rho` are not, which limits the simulator to a single dimension. Record as Future Scope.

---

### 8.6 Screen S6 — Investment Optimizer

**Purpose.** Answer "given this budget, what do I buy, what does it save, and what did I leave out and
why?" **Status: Partially Verified Implemented.**

```
+----------------------------------------------------------------------+
|  Investment Optimizer                                                |
|  Budget (₹) [ 5,00,00,000 ]  Max actions [ 5 ]       [ Optimise ]    |
|  _________________________________________________________________  |
|  +------------+ +------------+ +------------+ +------------+         |
|  | EAL AFTER  | | REDUCTION  | | PLAN COST  | | ROSI       |         |
|  | ₹52.29 L   | | 52.73%     | | ₹44.00 L   | | 0.33       |         |
|  | from ₹1.11Cr| ₹58.33 L/yr| of ₹50.00 L | ratio, not % |         |
|  +------------+ +------------+ +------------+ +------------+         |
|  Proven optimal · exact search · 120 plans in 16 ms                  |
|  Capacity 3 of 6 used.   Estimate, not a prediction.                 |
|                                                                      |
|  Budget vs risk reduction                                            |
|  EAL ^                                                                   |
|  ₹1.11C|  *                                                       |
|        |    *--*                                                    |
|   ₹60L |       *---*                                               |
|        |            *------*                                       |
|  ₹52.29L                       *-------*                           |
|      +----------------------------------------->                      |
|        ₹0        ₹15L       ₹30L       ₹50L   budget               |
|                                                                      |
|  Selected actions                                                     |
|  | Action              | Cost      | Marginal gain | ROSI | Lead |      |
|  | Enforce MFA …       | ₹11.00 L  | ₹19.91 L     | 0.81 | 45d  |      |
|                                                                      |
|  Not selected                          (9)                           |
|  | Patch edge appliance | Over budget: costs ₹7,00,000,            |
|  |                        remaining budget ₹25,000                 |
|                                                                      |
|  (overlap note appears only if a penalty is non-zero)                |
+----------------------------------------------------------------------+
```

**Data fields.** `POST /api/optimise` returns `plan{method, optimal, budget_minor, capacity_max,
capacity_used, cost_minor, currency, baseline_eal_minor, plan_eal_minor, reduction_minor, reduction_pct,
net_benefit_minor, rosi, selected[], marginal_by_action[], selected_detail[], candidates[],
rejected[]{action_code, name, category, cost_minor, reason, reason_kind}, feasibility[],
candidates_evaluated, runtime_ms}`. `GET /api/optimise/frontier?steps=10` returns
`frontier[]{budget_minor, cost_minor, reduction_minor, plan_eal_minor, selected[], optimal}` plus
`currency` and `symbol`.

**Verified live result, ₹5 crore budget** (`budget_minor: 500000000`): selected
`ACT-1, ACT-4, ACT-8`; `cost_minor 440000000`; `reduction_pct 52.73`; `rosi 0.3257`;
`net_benefit_minor 143298738`; `candidates_evaluated 120`; `runtime_ms 16`; `method "exact"`;
`optimal true`. `marginal_by_action[0]` carries `marginal_reduction_minor 199099294`,
`standalone_reduction_minor 199099294`, `overlap_penalty_minor 0`, `marginal_rosi 0.81`,
`rosi_standalone 0.81`, `lead_time_days 45`.

**Actions.** Set budget, set max actions, optimise, inspect selected, inspect rejections, inspect
frontier, export plan, save as a scenario **[P]**.

**Validation.** Budget is a **positive number in rupees**, converted once to minor units at the API
boundary. `max_actions` ≥ 1. The conversion at `app.js:212` (`Math.round(value * 100)`) is correct but
the field is labelled only `Budget` with `min="100000"`, so nobody knows the unit. Verified: the
cheapest action in the catalogue costs `70000000` minor units = ₹7.00 L, so the `min` of ₹1,00,000 sits
below any useful value and `step="100000"` (₹1 L) is coarse. **Label the field `Budget (₹)` and set
`min` to the cheapest candidate cost.**

**States.** Idle. Solving. Solved. No affordable action — verified: at `budget_minor 2500000`
(₹25,000) the response has `selected: []`, `marginal_by_action: []`, `selected_detail: []`,
`rosi: null` and every action in `rejected[]` with `reason_kind "budget"`. **This empty state must be
designed, not inherited** — `app.js:247-250` would print "null" for ROSI. Infeasible with unmet
prerequisites or capacity. Partial search (`optimal: false`, `method "heuristic"`) — must be labelled
as best-effort, never as optimal. Error.

**Gaps and one trap.**

- The frontier is a **table with CSS bars**, not the required investment-versus-reduction **curve**.
  All ten points are already in the response, so a real chart is pure rendering work. An SVG line
  chart, no dependency needed.
- `app.js:277` computes frontier ROSI **client-side** as
  `(reduction_minor - cost_minor) / cost_minor`. This is a business calculation in the client, which
  §5.1 forbids. The server does not return `rosi` per frontier point. **Fix: add `rosi` to the
  frontier response in `app/optimize.py` and render it.** The correct plan-level value for the
  ₹5 Cr point is `0.3257`; the client-side formula would report a different number for any frontier
  point whose selected plan differs from the one returned by `POST /api/optimise`.
- `feasibility[]` was **empty** in every run observed, because no action in the app seed data sets
  `capacity_group` or `requires_actions`. The "why not selected" story is therefore entirely
  `budget`-driven in the demo dataset. Note that `capacity_used`/`capacity_max` still reported `3`/`6`
  for a three-action plan, so a capacity figure is being computed against a limit that nothing
  actually consumes — confusing to show without an explanation.
  **The fixture in `docs/worked_example.py` does exercise these paths** and returns a non-zero
  `overlap_penalty_minor`, a `"Mutually exclusive with Privileged access management rollout"`
  rejection, a `reason_kind` of feasibility rather than budget, and a negative ROSI. **Use that
  fixture to test the dependency, overlap and negative-ROSI UI**, because the app seed cannot reach
  them. The demo script must not claim to show constraint behaviour it cannot show.
- The "overlapping actions" note is displayed unconditionally, including when `overlap_penalty_minor`
  is `0` for every action. **Only show it when an overlap penalty actually exists.** Displaying a
  caveat that is not true is the same class of error as labelling a multiplier band a percentile.
- After optimising, `app.js:225` calls `loadAssessment(plan.selected)`, so the Exposure tab silently
  switches to the **post-plan** model with no marker. Verified live: the what-if baseline-equivalent
  figures change after an optimise. Show a persistent "post-plan" badge on every affected figure.

---

### 8.7 Screen S7 — Ask

**Purpose.** Answer questions about the risk model in natural language, grounded in computed figures,
and refuse cleanly when the question is out of scope. **Status: Verified Implemented, with a
material caveat.**

```
+----------------------------------------------------------------------+
|  Ask the model                                                       |
|  Only risk and optimisation questions. No future breach prediction.  |
|                                                                      |
|  [ What is our largest exposure?                            ] [Ask]  |
|                                                                      |
|  Suggested: [Largest exposure] [Top BU] [Cheapest actions]           |
|            [Are we ISO compliant?]  <- must be refused, see below    |
|                                                                      |
|  +----------------------------------------------------------------+  |
|  | Q  What is our largest exposure?                               |  |
|  |                                                                |  |
|  | A  S3 Ransomware on A3-PGW-CONN-01 contributes ₹40.90 L,     |  |
|  |    37.0% of the ₹1.11 Cr portfolio figure, at Low confidence. |  |
|  |                                                                |  |
|  | Grounded in: assessment.risk[0] · catalog.asset[A1-OMS-DB-PROD]|  |
|  | Model: local-extractive · No external data used.               |  |
|  | Estimate, not a prediction.                                    |  |
|  +----------------------------------------------------------------+  |
|                                                                      |
|  ! Not answered: this platform cannot predict whether a breach will  |
|    occur. It quantifies expected loss under stated assumptions.      |
+----------------------------------------------------------------------+
```

**Data fields.** `POST /api/ask` with `{question}`. `GET /api/ai/status` returns `llm_enabled`,
`model`, `mode`, `guarantees[]` — verified live as `mode` with three guarantees and `model: null` when
the LLM is disabled. The response carries the answer, grounding references, the refusal flag, and a
warning set. Current client state: `state.ask` holds the last answer for a repeat-view
**Provenance / Transparency** panel.

**Actions.** Ask, clear, copy answer, re-ask. Suggested questions are chips that populate the input.

**Validation.** Non-empty question, maximum length **[P, proposed 2,000 characters]**, rate limit
surfaced from the server. No client-side content filtering.

**States.** Idle. Asking (disabled input, progress). Answered with grounding. **Refused** — a designed
state with a clear explanation, never an error. Disproved or out-of-scope. Rate-limited. LLM disabled —
`llm_enabled: false` must disable the input and explain why, rather than failing on submit.
Ungrounded response — show a warning that the answer is not backed by the model.

**What is already good, and must be preserved.** `app.js:331-343` renders the grounding references, the
model and mode, and a warning line beneath the answer, plus an explicit disclaimer. Showing *why* an
answer is trustworthy is more persuasive than the answer itself, and it is already implemented. The
three guaranteed disclaimers returned by `/api/ai/status` should be rendered on this screen too.

**Confirmed defect — the suggested questions are the problem.** `app.js:298-299` offers
*"Will we be breached next year?"* and *"Are we compliant with ISO 27001?"* as one-click chips. Both are
out of scope, and the current guard is a **literal substring match**, verified to fail on natural
phrasing:

- Asking "Are we compliant with ISO 27001?" **is not refused** — it produces a hallucinated compliance
  answer, because the guard does not match the natural phrasing.
- Asking "What is the probability our top scenario breaches next year?" **is not refused**.
- Asking "How does this benchmark against industry peers?" **is not refused**.
- Asking "What is the source of this data?" **is not refused**.
- The literal string `predict` **is** refused, which is why the existing test suite passes.

This is finding **F-25** in the technical architecture document and `SEC-AI-01` in the security
requirements. **The UI must not ship suggested chips that the backend cannot refuse**, because a judge
will click the most interesting one. Two independent fixes are required:

1. **Backend:** replace substring matching with intent classification. Blocking on the word `predict`
   is not a safety control; it is a word filter with a demo-shaped test.
2. **Frontend, immediately:** remove the two out-of-scope chips and replace them with in-scope
   questions the model can actually ground. The suggested questions are the *primary* path into the
   weakest part of the system, which is a poor risk to take at a live demo.

---

### 8.8 Screen S8 — Compliance Mapping

**Purpose.** Show which controls exist and how they are used, **without implying certification**.
**Status: Not Implemented.** No UI, no route, no coverage computation.

```
+----------------------------------------------------------------------+
|  Compliance Mapping                                                  |
|  Framework references are catalogue labels. This is not an audit    |
|  and confers no certification.                                       |
|                                                                      |
|  Framework [ISO 27001 ▾]                                             |
|                                                                      |
|  | Control       | Domain   | CE base | CE applied | Scenarios |   |
|  | A.5.15        | Access   | 40%     | 60%        | 4         |           |
|  | A.8.24        | Crypt    | 30%     | 30%        | 2         |           |
|                                                                      |
|  Control effectiveness                                             |
|  Measured      ████████░░  62%   3 controls                        |
|  Assumed        ████░░░░░░  38%   2 controls   <- show this split  |
|                                                                      |
|  No unmatched findings. No gap analysis.                             |
+----------------------------------------------------------------------+
```

**Data fields.** `catalog.controls[]{control_code, name, domain, ce_score, ce_source, ce_evidence_ref,
framework_iso, framework_nist, framework_cis}` — verified live with 12 controls. Per-scenario
`control_detail[]{ce_base, ce_applied, changed, ce_source, ce_evidence_ref}` links a control to the
scenarios it affects. `ce_source` is the important field: it distinguishes a **measured** control
effectiveness from an **assumed** one, and the current data carries at least one assumed value, which
is why `S1`'s confidence is Low.

**Actions.** Filter by framework, domain, `ce_source`, and `ce_evidence_ref`. Jump to the affected
scenario in S4. Export the mapping.

**Validation.** None. This screen is read-only, which makes it the safest screen to demo.

**States.** Populated. No controls for the selected framework. All-assumed (a strong warning). Empty
catalogue. Error.

**Blocker, stated plainly.** A coverage percentage implies a control-to-requirement mapping table.
**The repository contains none.** `framework_iso`, `framework_nist` and `framework_cis` are labels on
the seed rows; there is no requirement catalogue, no clause text, and no assessment against any
published standard. Therefore:

- **Do not display a coverage percentage.** It would be a fabricated compliance claim, and it is the
  kind of claim that ends an evaluation badly.
- **Do not display "compliant", "non-compliant", or a pass/fail verdict.** It would also be false.
- **Do display** what is genuinely known: which controls exist, which scenarios use them, whether
  effectiveness is measured or assumed, and what the evidence reference is.

The distinction the requirement calls for — "framework mapping and coverage tracking" versus
"certification-level mapping" — is exactly the right instinct, and in this repository the honest
answer is that only the first half is even partially available. Building a real clause-level
requirement catalogue is **Future Scope** and needs a licensing and content decision, recorded in §18.

---

### 8.9 Screen S9 — Reports & Export

**Purpose.** Produce a shareable artefact for a board, analyst or committee audience, with the
synthetic-data and estimate disclaimers intact. **Status: Partially Verified Implemented.**

```
+----------------------------------------------------------------------+
|  Reports & Export                                                    |
|  All outputs are generated from synthetic demonstration data.        |
|  Figures are estimates, not predictions.                             |
|                                                                      |
|  Format        Audience        File              [Download]          |
|  Markdown      Analyst         report.md         [Download]          |
|  CSV           Analyst         scenarios.csv     [Download]          |
|  CSV           Committee       actions.csv       [Download]          |
|  HTML          Board           board.html        [Download]          |
|                                                                      |
|  Include findings appendix?  [x] Yes  [ ] No                        |
|  Redact asset identifiers?    [ ] Yes  [ ] No      [P]              |
|                                                                      |
|  Preview                                                              |
|  | # Cyber Risk Quantification Report                                |
|  | ## Portfolio expected annual loss                                 |
|  | ₹1.11 Cr (sensitivity range ₹38.72 L – ₹2.16 Cr)                 |
|  | Synthetic demonstration data. Estimate, not a prediction.        |
|                                                                      |
|  Content-Security-Policy: default-src 'self'  <- headers verified    |
+----------------------------------------------------------------------+
```

**Data fields.** The report contents themselves. Verified response headers on the current endpoints:
`Content-Disposition: attachment; filename=…` and `Content-Security-Policy: default-src 'self'` are
both set, plus `X-Content-Type-Options: nosniff`. The Markdown report leads with the synthetic-data
banner and the estimate disclaimer, which is correct and must not be removed to save page space.

**Actions.** Preview and download each of the four formats. Toggle the findings appendix. Toggle
redaction **[P]**. Copy a shareable link **[Future Scope]**.

**Validation.** Server-side generation only. The client never composes report text.

**States.** Not yet generated. Generating. Ready with preview. Download in progress. Error with a
retry. **Blocked when the LLM is disabled** — the board HTML report embeds AI commentary, so the UI
must show that specific cause and offer the Markdown or CSV alternative rather than showing a generic
failure.

**Gaps and a security requirement.**

- The preview is loaded lazily on first tab click and guarded by a `textContent` emptiness check
  (`app.js:415-419`), so it never refreshes after the model changes. Proposed MVP: a "Regenerate
  preview" control and a timestamp on the preview.
- `Content-Disposition` is set, which prevents a CSV from rendering as HTML. **However, the underlying
  finding `F-26` / `SEC-RPT-01` remains: CSV cells are written verbatim, so a value beginning with
  `=`, `+`, `-` or `@` is preserved as a live formula when the file is opened in Excel.** This is not
  fixable in the CSS layer of the frontend. The requirements are: (a) fix the escaping in
  `app/reports.py`; and (b) until it is fixed, the UI must not present a user-supplied CSV as a
  sanitised export, and should warn that exports contain uploaded data.
- No redaction option. A board report that lists asset hostnames from an uploaded inventory is a real
  disclosure risk, and a redaction toggle is cheap to add.
- No per-format "what is included" description, so a user does not know what the findings appendix
  contains before sending it to a board.

---

### 8.10 Screen S10 — Assumptions & Settings

**Purpose.** Make every assumption that drives the numbers inspectable and adjustable, so the model is
auditable rather than a black box. **Status: Not Implemented.**

```
+----------------------------------------------------------------------+
|  Assumptions & Settings                                              |
|  Editing these values changes every figure in the application.       |
+----------------------------------------------------------------------+
|  Loss estimation                                                     |
|  | Setting              | Value  | Source      | Applies to   |      |
|  | SLE low multiplier   | 0.50   | Assumption  | All scenarios| [Edit]|
|  | SLE high multiplier  | 1.50   | Assumption  | All scenarios| [Edit]|
|  | Probability low mult | 0.50   | Assumption  | All scenarios| [Edit]|
|  | Probability high mult| 1.50   | Assumption  | All scenarios| [Edit]|
|  | Currency             | INR    | Config      | Global       | [Edit]|
|                                                                      |
|  Scenario-level sensitivity                                          |
|  | Scenario | Name      | SLE low | SLE high | Confidence    |      |
|  | S1       | Ransomware…| 0.70    | 1.30     | Low · 54      | [Edit]|
|                                                                      |
|  Correlation (ρ) by group — shown for transparency, Admin only      |
|  | G1  0.15   | G2  0.10   | G3  0.20   | G4  0.05      |      |
|                                                                      |
|  Display                                                              |
|  Abbreviate large amounts  [x]  Currency symbol  [₹]                  |
+----------------------------------------------------------------------+
```

**Data fields.** `risk.py:121-122` defines `sle_low_multiplier` and `sle_high_multiplier` per scenario.
`risk.py:35-36` defines the global `PROBABILITY_MULT_LOW` and `PROBABILITY_MULT_HIGH`. The assessment
response returns the active `rho_used{G1: 0.15, G2: 0.10, G3: 0.20, G4: 0.05}` — verified live.
Currency is `INR` with symbol `₹`. The Data screen's `latest_dataset_issues` names the active issue set,
for example `synthetic_bundle`.

**Actions.** Edit a multiplier, reset to defaults, view the correlation matrix, toggle display
preferences. Editing a multiplier is effectively a what-if on the model itself, so **any change here
must be recoverable** and must never silently rewrite the as-ingested scenario rows.

**Validation.** Multipliers bounded to `(0, 5]` per the schema, which is a wide range and should be
narrowed **[P]** to something defensible such as `0.5 – 2.0`. The global probability multipliers should
be constrained so `low < 1 < high` and the two are ordered. Changes require an explicit confirmation
showing the before and after portfolio EAL.

**States.** Default. Modified with unsaved changes. Modified and saved. Invalid input. Admin-only for
global values — an Analyst sees them read-only, which matches the matrix in §2.2.

**Why this screen matters more than its size suggests.** The four multipliers are currently invisible
constants, yet they determine the entire sensitivity range that appears on the Executive Dashboard. A
model whose bounds are hard-coded and undisclosed is the thing a technical judge will attack, and the
fix is a small table. The `Source` column must distinguish a hard-coded constant from an
organisation-supplied value from an external benchmark. Right now every multiplier is an assumption,
and the screen should say so plainly rather than presenting them as tuned parameters.

---

### 8.11 Screen S11 — Audit Log & Users

**Purpose.** Make the system accountable: who did what, when, and who can access what. **Status: Not
Implemented — the API exists, the UI does not.**

```
+----------------------------------------------------------------------+
|  Audit Log & Users                                       [Admin]     |
+----------------------------------------------------------------------+
|  Recent activity                                                     |
|  | Time (local)   | Actor    | Action        | Resource   | Detail |  |
|  | 30 Sep 14:22:04| analyst  | assessment.get| —         | ok     |  |
|  | 30 Sep 14:21:58| analyst  | ingest        | assets.csv| 5 rows |  |
|  | 30 Sep 14:21:41| 10.0.0.1 | auth.failed   | —         | 401    |  |
|  |                                                                    |
|  | 30 Sep 14:19:10| ciso     | report.html  | board     | ok      |  |
|  |                                                                    |
|  [ Previous ]  Page 1 of 1  [ Next ]     Filter [action ▾] [actor ▾]  |
|                                                                      |
|  Users                                                               |
|  | User    | Role      | Created      | Last seen   | Actions |  |
|  | analyst | analyst   | 01 Sep 2026  | 30 Sep 14:22| [Reset] |  |
|  | ciso    | ciso      | 01 Sep 2026  | 30 Sep 14:19|         |  |
+----------------------------------------------------------------------+
```

**Data fields.** `GET /api/audit` exists at `app/main.py:405` and returns paginated, filtered audit
entries. User records are sourced from the auth store. The verified live `auth.failed` finding matters
here: **five consecutive failed logins produce zero persisted `auth.failed` rows**, because the audit
write is rolled back with the failed transaction (finding `F-28`, requirement `SEC-AUD-01`).

**Actions.** Filter by action, actor, resource and time range. Paginate. View one entry in full.
Reset a user's password **[Future Scope]**. Create, deactivate or change a user's role **[Future
Scope]**.

**Validation.** Admin-only. Server-enforced regardless of what the client renders, per §2.2.

**States.** Populated. Empty — with the message "no activity recorded", not a blank table. Filtered to
zero. Page beyond the end. Error. **Audit-write unavailable** — a persistent, visible warning that
failed-login auditing is known not to be recording, rather than a screen that looks complete while
silently dropping the events an auditor most wants to see.

**The honesty requirement.** A log screen that appears to work but omits failed logins is worse than no
log screen, because it creates false assurance. Until `F-28` is fixed, this screen must carry a visible
banner. After it is fixed, that banner goes away and the requirement ID appears in the test plan.

---

## 9. Reusable components

`COMP-*` identifiers are referenced from the requirements in §10. Status reflects the current codebase.

| ID | Component | Status | Purpose and notes |
|---|---|---|---|
| `COMP-01` | App header | **Verified Implemented** | Brand, session chip, logout. Add freshness and provenance. |
| `COMP-02` | Synthetic data banner | **Verified Implemented** | Persistent, non-dismissible. Wording is good; do not rewrite casually. |
| `COMP-03` | KPI tile | **Verified Implemented** | `.kpi` with `.label`, `.value`, `.note`. Tabular numerals already applied. |
| `COMP-04` | Data table | **Verified Implemented** | `.num` right-alignment, sticky header **[P]**, column sort **[P]**, row density toggle **[P]**. |
| `COMP-05` | Status pill | **Verified Implemented** | Confidence and severity. Text label always present; add an icon **[P]**. |
| `COMP-06` | Inline bar glyph | **Verified Implemented** | `.bar > span`, used for shares. Keep for lists; use a real chart for curves. |
| `COMP-07` | Disclosure | **Verified Implemented** | `<details>`/`<summary>` for "why" and loss components. Correct pattern; reuse in S5. |
| `COMP-08` | Toast | **Verified Implemented** | **Add an `aria-live` region and a dismiss control.** Currently visual-only. |
| `COMP-09` | Empty state | **Proposed MVP** | Icon-free, one sentence, one action. Never a bare "No data". |
| `COMP-10` | Error panel | **Proposed MVP** | Plain-language cause, requirement or incident reference, retry. No stack traces. |
| `COMP-11` | Loading skeleton | **Proposed MVP** | Reserve layout height to prevent reflow. No spinner-only screens. |
| `COMP-12` | Stale-data chip | **Proposed MVP** | Age plus band, from `freshness`. See §7.2. |
| `COMP-13` | Stacked bar chart | **Proposed MVP** | Category and business-unit composition. Pure CSS/SVG, no dependency. |
| `COMP-14` | Sensitivity range bar | **Proposed MVP** | Point estimate with a labelled band. Must say "sensitivity", never "P10–P90" (§5.4). |
| `COMP-15` | Budget-versus-reduction curve | **Proposed MVP** | SVG polyline over `frontier[]`, with the selected budget marked. |
| `COMP-16` | Inline numeric input | **Proposed MVP** | Slider plus numeric entry, live range hint, inline error. Replaces `window.prompt`. |
| `COMP-17` | Filter bar | **Proposed MVP** | Business unit, actor, category, search, active-filter count, clear-all. |
| `COMP-18` | Breadcrumb | **Proposed MVP** | `Portfolio › Retail › A1-OMS-DB-PROD › S1`, each segment a control. |
| `COMP-19` | Grounding panel | **Verified Implemented** | `app.js:331-343`. Answer provenance. Strong; keep. |
| `COMP-20` | Role-gated control | **Proposed MVP** | Disabled with an explanation, never silently hidden without a reason. |
| `COMP-21` | Download button | **Verified Implemented** | Add progress, and a note when the LLM is disabled (§8.9). |
| `COMP-22` | Money cell | **Verified Implemented** | Abbreviation per §5.2, with the exact value on hover, focus and in exports. |

**A note on the existing `esc()` helper.** `app.js:20-23` escapes `&`, `<` and `>` but **not quotes**.
It is used at `app.js:148` to build `data-scenario="${esc(s.scenario_code)}"`, so an uploaded
`scenario_code` containing a double quote escapes the attribute and injects markup. This is finding
**F-3** / `SEC-F-01`, rated Medium, and it was confirmed against a live server during this review.
**Fix in the client: stop building HTML strings for attributes.** Use `element.setAttribute`, or render
via `textContent` and attach listeners, so no escaping strategy can be bypassed. Every `innerHTML`
template in `app.js` is a re-audit target, and `app.js:331-343` is the other one to check, since
scenario names flow into the AI answer block. Escaping quote characters alone would close this
instance and leave the pattern in place.

---

## 10. Functional requirements

Every **Must** is testable. Given/When/Then criteria are written to be executable against the API and
the DOM without a human judgement call. Requirements marked *Security* trace to
`docs/SECURITY_ACCESS_REQUIREMENTS.md`; the canonical requirement there remains authoritative and this
list does not restate or weaken it.

### 10.1 Global (FR-G-*)

| ID | Requirement | Priority | Status |
|---|---|---|---|
| `FR-G-01` | Show the synthetic-data banner on every screen that displays data, non-dismissible. | Must | Verified Implemented |
| `FR-G-02` | Show "Estimate, not a prediction" adjacent to every aggregate money figure. | Must | Proposed MVP |
| `FR-G-03` | Show a freshness chip with source age and band on every screen showing computed figures. | Must | Proposed MVP |
| `FR-G-04` | Render all money in `₹` with Indian digit grouping, abbreviating to lakh/crore per §5.2. | Must | Partial — grouping verified, abbreviation Proposed MVP |
| `FR-G-05` | Expose the exact unabbreviated value on hover, focus and in every export. | Must | Proposed MVP |
| `FR-G-06` | Never label the EAL band as a percentile or confidence interval. | Must | Proposed MVP — see §5.4 |
| `FR-G-07` | Enforce role visibility client-side for convenience and server-side for security. | Must | Partial — server-side verified, client-side Proposed MVP |
| `FR-G-08` | Provide a visible focus indicator on every interactive element, minimum 3:1. | Must | Proposed MVP |
| `FR-G-09` | Announce asynchronous results through an `aria-live` region. | Must | Proposed MVP |
| `FR-G-10` | Show a permission-denied explanation, never a generic failure. | Must | Proposed MVP |
| `FR-G-11` | Provide loading, empty, error and stale states for every data region. | Must | Proposed MVP |
| `FR-G-12` | Do not compute, scale, convert or round money in the client beyond display-unit conversion. | Must | Proposed MVP — see the frontier ROSI defect in §8.6 |
| `FR-G-13` | Support deep-linking to every screen and browser Back navigation. | Should | Proposed MVP |
| `FR-G-14` | Provide a CSV of current table data for every table. | Should | Future Scope |
| `FR-G-15` | Keyboard-only operation of all flows, with no `window.prompt`. | Must | Proposed MVP |

**`FR-G-01`** — Given an authenticated user, when any screen renders data, then the synthetic-data
banner is present in the accessibility tree and cannot be dismissed.

**`FR-G-02`** — Given a screen showing portfolio EAL, when the figure renders, then the text
"Estimate, not a prediction" appears within the same visual region.

**`FR-G-03`** — Given `freshness.sources.SimulatedScanner.age_days = 11.93`, `band = "aging"` and
`thresholds = {green_days: 7, amber_days: 30}`, when any screen displays computed figures, then a
chip reads "Data 12 days old · aging", rendering the server's `band` string rather than re-deriving it.

**`FR-G-04`** — Given `eal_minor = 1106227077` and `currency = "INR"`, when the figure renders, then
the display is `₹1.11 Cr`; given `348566177`, then `₹34.86 L`; given `199099294`, then `₹19.91 L`;
given `4589196`, then `₹45,892`.

**`FR-G-06`** — Given any rendered range, when a judge greps the DOM and the exported report, then
neither contains "P10", "P90", "percentile", or "confidence interval" in reference to the EAL band.

**`FR-G-08`** — Given any focusable element, when it receives keyboard focus, then an indicator of at
least 3:1 contrast is visible; given the `--line` border token, then its ratio against `--panel` is
raised from the current 1.30:1 to at least 3:1 (§6.2).

**`FR-G-09`** — Given a successful login, upload, optimise or export, when it completes, then the
outcome is announced in an `aria-live="polite"` region, not only in a visual toast.

**`FR-G-12`** — Given a frontier point, when ROSI renders, then the value came from the
`optimise/frontier` response; the client must not compute
`(reduction_minor - cost_minor) / cost_minor`.

**`FR-G-15`** — Given the What-if screen, when a user changes `p0`, then no browser modal dialog
appears and the entire flow is completable with Tab, arrows and Enter.

### 10.2 Screen-specific (FR-S<screen>-*)

| ID | Requirement | Priority | Screen | Status |
|---|---|---|---|---|
| `FR-S1-01` | Authenticate with `POST /api/login`; skip the screen when `GET /api/me` returns a valid session. | Must | S1 | Verified Implemented |
| `FR-S1-02` | Ship **empty** username and password fields. | Must | S1 | Proposed MVP — see the defect in §8.1 |
| `FR-S1-03` | Do not render any password in visible text. | Must | S1 | Proposed MVP — `SEC-AUTH-04` |
| `FR-S1-04` | Show an inline `role="alert"` error without a network call for an empty submit. | Should | S1 | Proposed MVP |
| `FR-S1-05` | Never reveal whether a username exists. | Must | S1 | Proposed MVP — Security |
| `FR-S2-01` | Upload with `POST /api/ingest` and summarise the result per dataset. | Must | S2 | Verified Implemented |
| `FR-S2-02` | Display `quarantine` count and a downloadable list of rejected rows with reasons. | Must | S2 | Proposed MVP |
| `FR-S2-03` | Display `findings_summary.unmatched` and explain that unmatched findings are excluded from calculations. | Must | S2 | Proposed MVP |
| `FR-S2-04` | Provide a dataset template download per dataset type. | Should | S2 | Proposed MVP |
| `FR-S2-05` | Provide an Admin-only demo reset. | Should | S2 | Proposed MVP |
| `FR-S3-01` | Show portfolio EAL, the sensitivity band, confidence and asset count above the fold. | Must | S3 | Partial — verified, band label Proposed MVP |
| `FR-S3-02` | Render the top-5 contributor list ranked by `eal_minor`. | Must | S3 | Proposed MVP — data present, chart missing |
| `FR-S3-03` | Render the business-unit composition from `by_business_unit`. | Must | S3 | Proposed MVP — data present, entirely unrendered |
| `FR-S3-04` | Do not render a 12-month trend until time-series data exists. | Must | S3 | Proposed MVP — blocker in §18 |
| `FR-S3-05` | Display the correlation-adjustment explanation wherever shares are shown. | Must | S3 | Verified Implemented — preserve |
| `FR-S3-06` | Show a warning when `incomplete.length > 0`, listing `incomplete_reasons` and `excluded_findings`. | Should | S3 | Proposed MVP |
| `FR-S3-07` | Land here by default for the `ciso` role. | Should | S3 | Proposed MVP |
| `FR-S4-01` | Provide a filter bar over business unit, actor and category, plus search and clear-all. | Must | S4 | Proposed MVP |
| `FR-S4-02` | Render per-row confidence with reasons, using a disclosure. | Must | S4 | Verified Implemented — preserve |
| `FR-S4-03` | Support Portfolio → BU → Asset → Scenario → Finding navigation with a breadcrumb. | Must | S4 | Proposed MVP |
| `FR-S4-04` | Do not render a `threat_actor` column until the field exists in the response. | Must | S4 | Proposed MVP — confirmed defect |
| `FR-S4-05` | Show `ce_base` versus `ce_applied` and flag changed controls. | Must | S4 | Verified Implemented |
| `FR-S4-06` | Show an explicit empty state with a clear-filters action when filters match nothing. | Must | S4 | Proposed MVP |
| `FR-S5-01` | Adjust `p0` via an inline control; never `window.prompt`. | Must | S5 | Proposed MVP |
| `FR-S5-02` | **Preserve the baseline.** Render baseline and what-if side by side, and never overwrite the ingested assessment. | Must | S5 | Proposed MVP — **correctness bug** |
| `FR-S5-03` | Validate `p0` in `(0, 0.5]` inline, not in a toast. | Must | S5 | Partial — range check verified, placement Proposed MVP |
| `FR-S5-04` | Provide a persistent "Return to baseline" control. | Must | S5 | Proposed MVP |
| `FR-S5-05` | Label the suggested value for what it is, or omit it. | Should | S5 | Proposed MVP |
| `FR-S5-06` | Show the confidence delta, not only the EAL delta. | Should | S5 | Proposed MVP |
| `FR-S5-07` | Reflect a what-if result in the URL so it is shareable. | Should | S5 | Future Scope |
| `FR-S6-01` | Accept a budget in rupees and convert to minor units once, at the API boundary. | Must | S6 | Partial — conversion verified, labelling Proposed MVP |
| `FR-S6-02` | Label the budget field with its unit and set `min` to the cheapest candidate cost. | Must | S6 | Proposed MVP |
| `FR-S6-03` | Show EAL after plan, reduction, plan cost and ROSI, labelling ROSI as a ratio. | Must | S6 | Partial — verified, ratio labelling Proposed MVP |
| `FR-S6-04` | Render the budget-versus-reduction curve from `frontier[]`. | Must | S6 | Proposed MVP |
| `FR-S6-05` | List every unselected action with its `reason` and `reason_kind`. | Must | S6 | Verified Implemented — preserve |
| `FR-S6-06` | Design the no-affordable-action state; never display `null` for ROSI. | Must | S6 | Proposed MVP |
| `FR-S6-07` | Render ROSI from the API for every frontier point. | Must | S6 | Proposed MVP — client-side calculation defect |
| `FR-S6-08` | Show the overlap caveat only when a non-zero `overlap_penalty_minor` exists. | Must | S6 | Proposed MVP |
| `FR-S6-09` | Badge every figure affected by a post-plan model. | Must | S6 | Proposed MVP |
| `FR-S6-10` | Label a partial result as best-effort when `optimal` is false. | Must | S6 | Proposed MVP |
| `FR-S6-11` | Export the selected plan. | Should | S6 | Proposed MVP |
| `FR-S7-01` | Answer only from the computed model, with grounding references displayed. | Must | S7 | Verified Implemented |
| `FR-S7-02` | **Offer no suggested question the backend cannot refuse.** | Must | S7 | Proposed MVP — **remove the two failing chips** |
| `FR-S7-03` | Refuse out-of-scope questions with an explanation, not an error. | Must | S7 | Partial — server-side partial, `SEC-AI-01` |
| `FR-S7-04` | Display the model name, mode and guaranteed disclaimers. | Must | S7 | Verified Implemented |
| `FR-S7-05` | Disable the input and explain when `llm_enabled` is false. | Must | S7 | Proposed MVP |
| `FR-S7-06` | Mark an answer that is not grounded in the model. | Must | S7 | Proposed MVP |
| `FR-S8-01` | List controls with framework labels, `ce_source` and `ce_evidence_ref`. | Must | S8 | Proposed MVP |
| `FR-S8-02` | **Never display a coverage percentage, "compliant" or a pass/fail verdict.** | Must | S8 | Proposed MVP — no mapping table exists |
| `FR-S8-03` | Display the measured-versus-assumed control-effectiveness split. | Must | S8 | Proposed MVP |
| `FR-S8-04` | Link a control to the scenarios it affects. | Should | S8 | Proposed MVP |
| `FR-S8-05` | State on screen that framework references confer no certification. | Must | S8 | Proposed MVP |
| `FR-S9-01` | Offer Markdown, scenario CSV, action CSV and board HTML, with an audience label each. | Must | S9 | Verified Implemented |
| `FR-S9-02` | Preview report content and allow regeneration after the model changes. | Must | S9 | Proposed MVP |
| `FR-S9-03` | Retain synthetic-data and estimate disclaimers in every exported format. | Must | S9 | Verified Implemented — Security |
| `FR-S9-04` | Provide a redaction toggle for asset identifiers. | Should | S9 | Proposed MVP |
| `FR-S9-05` | Describe the contents of each format before download. | Should | S9 | Proposed MVP |
| `FR-S9-06` | Explain that the board HTML report is unavailable when the LLM is disabled. | Must | S9 | Proposed MVP |
| `FR-S10-01` | Display every multiplier with its value, source and scope. | Must | S10 | Proposed MVP |
| `FR-S10-02` | Distinguish hard-coded constants from supplied values and external benchmarks. | Must | S10 | Proposed MVP |
| `FR-S10-03` | Bound multiplier edits and require confirmation showing the EAL before and after. | Must | S10 | Proposed MVP |
| `FR-S10-04` | Restrict global multiplier editing to Admin; Analyst read-only. | Must | S10 | Proposed MVP |
| `FR-S10-05` | Display the active correlation matrix `rho_used`, read-only. | Should | S10 | Proposed MVP |
| `FR-S11-01` | Render audit entries from `GET /api/audit` with actor, action, resource and detail. | Must | S11 | Proposed MVP |
| `FR-S11-02` | Restrict the screen to Admin, enforced server-side. | Must | S11 | Partial — server-side verified, no UI |
| `FR-S11-03` | **Display a visible banner that failed-login auditing is not recording until `F-28` is fixed.** | Must | S11 | Proposed MVP — `SEC-AUD-01` |
| `FR-S11-04` | Filter by action, actor, resource and time; paginate. | Must | S11 | Proposed MVP |
| `FR-S11-05` | Show users with role, created date and last-seen time. | Should | S11 | Proposed MVP |

Selected acceptance criteria:

**`FR-S5-02`** — Given the ingested assessment with `eal_minor = 1106227077`, when a user applies
`p0 = 0.1059` to `S1`, then both the baseline `₹1.11 Cr` and the what-if figure remain visible in a
persistent comparison, and after pressing "Return to baseline" the displayed portfolio EAL equals
`1106227077` again without a page reload.

**`FR-S6-06`** — Given `POST /api/optimise` with `budget_minor = 2500000` returning `selected: []` and
`rosi: null`, when the result renders, then the empty state explains that no action is affordable, and
the string "null" does not appear anywhere in the DOM.

**`FR-S6-07`** — Given a `frontier[]` point, when ROSI renders, then the value is byte-identical to
the `rosi` field of the same point in the `optimise/frontier` response.

**`FR-S6-08`** — Given every `overlap_penalty_minor` equals `0`, when the plan renders, then the
overlapping-actions caveat is absent from the DOM.

**`FR-S7-02`** — Given the Ask screen, when it loads, then every suggested chip maps to a question the
server refuses or grounds; the phrases "breached next year" and "Are we compliant with ISO 27001" do
not appear as suggestions.

**`FR-S8-02`** — Given the Compliance screen, when it renders, then the DOM contains no occurrence of
"compliant", "non-compliant", "coverage %" or a pass/fail verdict.

**`FR-S11-03`** — Given `F-28` is unfixed, when an Admin opens the audit screen, then a banner states
that failed-login events are not being recorded, and cites `SEC-AUD-01`.

**`FR-S2-03`** — Given `findings_summary.unmatched > 0`, when the Data screen renders, then a warning
names the count and states that those findings are excluded from all risk calculations.

### 10.3 Remaining Must acceptance criteria

The blocks above cover the highest-risk requirements. The remainder are given here in compact
Given/When/Then form so that **every Must in §10.1 and §10.2 is testable**, as required.

**Global**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-G-05` | An abbreviated figure such as `₹1.11 Cr` | the user hovers, focuses, or exports | the exact `₹1,10,62,271` is available in all three |
| `FR-G-07` | A user with role `ciso` | they request `/api/optimise` | the server returns `403` regardless of whether the control was hidden |
| `FR-G-10` | An out-of-scope question returns `refused: true` from `/api/ask` | the Ask screen renders | the refusal text names what the platform does and does not hold; no stack trace or raw error body |
| `FR-G-11` | Any data region | its request is pending, empty, failed, or stale | the matching state from §16 renders in that region |

**S1 Login**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S1-01` | A valid session cookie | the page loads | `/api/me` succeeds and the login panel stays hidden |
| `FR-S1-02` | The served `index.html` | the source is inspected | no `value=` attribute contains a username or password |
| `FR-S1-03` | The rendered login screen | the page is read | no password string appears in visible text |
| `FR-S1-05` | A login attempt with a valid username and wrong password | the error renders | it is byte-identical to the error for a non-existent username |

**S2 Data**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S2-01` | A CSV with 40 rows, 3 invalid | it is uploaded | the response shows 37 accepted, 3 quarantined, and the dataset row reflects it |
| `FR-S2-02` | `quarantine = 3` | the Data screen renders | the count and a download of the three rejected rows with reasons are present |

**S3 Dashboard**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S3-01` | The assessment response | the screen renders | EAL, sensitivity band, confidence and asset count are all above the fold |
| `FR-S3-02` | Six scenarios with `eal_minor` | the chart renders | exactly five rows, ordered by exact `eal_minor` descending before abbreviation |
| `FR-S3-03` | `by_business_unit` with four units | the chart renders | all four units appear with values summing to `eal_minor` after correlation |
| `FR-S3-04` | No historical data in the response | the dashboard renders | no trend chart and no time axis is drawn |
| `FR-S3-05` | A view showing scenario shares | it renders | the correlation-adjustment note is present and shares are labelled as of the unadjusted total |

**S4 Explorer**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S4-01` | Six scenarios across three units | a unit filter is applied | only matching rows remain and the result count updates |
| `FR-S4-02` | `confidence_reasons` has three entries | the row renders | all three appear inside the "why" disclosure, verbatim |
| `FR-S4-03` | The S3 contributor list | a scenario is clicked | the breadcrumb reads Portfolio › unit › asset › scenario and the S4 view is filtered to it |
| `FR-S4-04` | The API response has no `threat_actor` | S4 renders | no threat-actor column and no "unknown actor" text appears |
| `FR-S4-05` | A control with `ce_base 0.2` and `ce_applied 0.2` | the control table renders | both values and `ce_source` are shown; `changed` is false |
| `FR-S4-06` | Filters matching zero scenarios | the table renders | an empty state with a clear-filters action replaces the table body |

**S5 What-if**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S5-01` | The What-if screen | `p0` is changed | an inline control is used; no browser modal appears at any point |
| `FR-S5-03` | `p0 = 0.6` | Apply is pressed | an inline error appears next to the field; no request is sent |
| `FR-S5-04` | A what-if is active | the page is read | a persistent "Return to baseline" control is present |

**S6 Optimizer**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S6-01` | A budget of `500000000` minor | the form submits | the request body carries `budget_minor = 500000000` exactly once, with no further conversion |
| `FR-S6-02` | The cheapest action costs `70000000` minor | the budget field renders | it is labelled `Budget (₹)` and `min` equals `700000` rupees |
| `FR-S6-03` | `rosi = 0.3257` | the KPI renders | it displays `0.33` and is labelled a ratio, not a percentage |
| `FR-S6-04` | `frontier[]` has ten points | the curve renders | all ten are plotted and the selected budget is marked |
| `FR-S6-05` | Nine actions are rejected | the rejected list renders | each shows its `reason` and `reason_kind` |
| `FR-S6-09` | A plan is applied | the user opens S3 | affected figures carry a visible post-plan marker |
| `FR-S6-10` | `optimal = false`, `method = "heuristic"` | the result renders | the wording is "best effort"; the word "optimal" does not appear |

**S7 Ask**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S7-01` | A grounded answer | it renders | grounding references name the model fields used |
| `FR-S7-03` | An out-of-scope question | the response returns `rejected` | the refusal is explained in plain language and is not styled as an error |
| `FR-S7-04` | `/api/ai/status` returns a model and guarantees | the screen renders | the model name, mode and every guarantee are shown |
| `FR-S7-05` | `llm_enabled = false` | the screen renders | the input is disabled and the reason is shown; submitting is impossible |
| `FR-S7-06` | `grounded = false` | the answer renders | a warning states the answer is not backed by the model |

**S8 Compliance**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S8-01` | 12 controls with `ce_source` | the screen renders | code, name, domain, framework labels, source and evidence reference are all shown |
| `FR-S8-03` | 2 assumed and 1 measured `ce_source` | the screen renders | the split shows 1 measured and 2 assumed |
| `FR-S8-05` | The screen is open | it is read | a statement says framework references confer no certification |

**S9 Reports**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S9-01` | An authenticated user | the screen renders | four formats are offered, each with an audience label |
| `FR-S9-02` | The model changes after a preview | the user clicks "Regenerate" | the preview updates and shows a new timestamp |
| `FR-S9-03` | Any format is downloaded | the file is opened | it contains the synthetic-data statement and the estimate disclaimer |
| `FR-S9-06` | `llm_enabled = false` | the user clicks the board HTML download | the screen explains the cause and offers Markdown or CSV instead |

**S10 Settings**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S10-01` | Four multipliers are active | the screen renders | each shows its value, source and scope |
| `FR-S10-02` | `PROBABILITY_MULT_LOW` is a code constant | the screen renders | it is labelled as a hard-coded constant, not as a tuned parameter |
| `FR-S10-03` | A multiplier is edited | the user confirms | the dialog shows portfolio EAL before and after, and a cancel path exists |
| `FR-S10-04` | An `analyst` opens the screen | they attempt an edit | the field is read-only and the reason is stated |

**S11 Audit**

| ID | Given | When | Then |
|---|---|---|---|
| `FR-S11-01` | Audit entries exist | the screen renders | actor, action, resource, time and detail are shown for each |
| `FR-S11-02` | A `ciso` requests `/api/audit` | the server responds | `403` is returned even if the screen is hidden |
| `FR-S11-04` | More entries than one page | the user filters and paginates | only matching entries appear and the page indicator is correct |

---

## 11. Data contract: field-to-screen mapping

The field names below are the actual wire format, captured from a running server during this review.
This is the section to re-verify first when the API changes.

| Field | Type | Screens | Display rule |
|---|---|---|---|
| `eal_minor` | int minor | S3, S4, S5, S6, S9 | `₹` + lakh/crore, exact on hover |
| `eal_low_minor`, `eal_high_minor` | int minor | S3, S4, S5 | Labelled **sensitivity range**, never percentiles |
| `eal_unadjusted_minor` | int minor | S3 | Sum of scenarios before correlation; explain the difference |
| `currency`, `symbol` | str | all money | Never hard-code `₹`; read from the response |
| `confidence`, `confidence_band` | int, str | S3, S4, S5 | Pill plus the "why" disclosure |
| `confidence_reasons[]` | list[str] | S4, S5 | **Verified Implemented**; render verbatim |
| `by_business_unit{}` | map[str,int] | S3, S4 | Unrendered today; cheap win |
| `by_category{}`, `by_actor{}` | map[str,int] | S3, S4 | Unrendered today |
| `by_asset{}` | map[str,int] | S3, S4 | Rendered in the asset table |
| `rho_used{}` | map[str,float] | S3, S10 | Read-only correlation matrix |
| `freshness.sources{}.{age_days, band, oldest_observed_at}` | float, str | S2, S3, all | Unrendered today; **must add** |
| `freshness.thresholds.{green_days, amber_days}` | int | S2, S3 | Drives the band |
| `incomplete[]`, `incomplete_reasons[]` | list[str] | S3, S4 | Warning banner |
| `excluded_findings` | int | S3, S4 | State what is not counted |
| `breakdown[].{component_code, amount_minor, source_ref, unresolved}` | list[obj] | S4, S5 | **Verified Implemented**; keep `unresolved` visible |
| `control_detail[].{ce_base, ce_applied, changed, ce_source, ce_evidence_ref}` | list[obj] | S4, S8 | **Verified Implemented**; drives the S8 split |
| `framework_iso`, `framework_nist`, `framework_cis` | str | S4, S8 | Labels only; never a verdict |
| `plan.{optimal, method, runtime_ms, candidates_evaluated}` | bool, str, int | S6 | Show the solver honestly |
| `plan.rosi` | float/null | S6 | **Ratio, not a percentage**; may be `null` |
| `marginal_by_action[].{marginal_rosi, rosi_standalone, overlap_penalty_minor, standalone_reduction_minor}` | list[obj] | S6 | Drives the overlap caveat |
| `rejected[].{reason, reason_kind}` | str | S6 | **Verified Implemented**; preserve verbatim |
| `feasibility[]` | list[obj] | S6 | Handle non-empty even though the seed data never produces it |
| `frontier[].{budget_minor, cost_minor, reduction_minor, plan_eal_minor, selected, optimal}` | list[obj] | S6 | Curve source; no per-point `rosi` today |
| `counts{synthetic_asset_share, latest_dataset_issues}` | various | S2 | Show the synthetic share |
| `recent_datasets[].{status, rows_total, rows_ok, rows_updated, rows_quarantined, synthetic}` | various | S2 | Partial-success summary |
| `findings_summary.unmatched` | int | S2, S8 | **Unrendered; must display** |
| `ai_status.{llm_enabled, model, mode, guarantees[]}` | various | S7, S9 | Disable input and explain; **Verified Implemented** |
| `threat_actor` | — | S4 | **Not present in the API. Do not render** |

---

## 12. Security, privacy, and trust in the interface

Controls live in `docs/SECURITY_ACCESS_REQUIREMENTS.md`; the requirements are canonical. This section
covers the interface obligations that arise from them.

**Output encoding.** `F-3` / `SEC-F-01` is the item to fix. `esc()` does not escape quotes and is
interpolated into an HTML attribute at `app.js:148`. Confirmed live with a quote-bearing
`scenario_code`. The structural fix is to stop generating HTML strings for user-supplied data; use
`textContent` and `setAttribute`. Audit every `innerHTML` template in `app.js` in one pass, not only
the line that broke.

**AI refusal.** `F-25` / `SEC-AI-01`. The literal-substring guard is not a control, and the two
suggested chips at `app.js:298-299` point directly at the gap. The frontend obligation is `FR-S7-02`:
never surface a question the system cannot answer. The backend obligation is intent classification
rather than keyword matching.

**CSV formula injection.** `F-26` / `SEC-RPT-01`. Cells beginning `=`, `+`, `-`, `@` are preserved
verbatim, so an uploaded field becomes a live formula on open. `Content-Disposition: attachment` and
`Content-Security-Policy: default-src 'self'` are both correctly set and mitigate the HTML-rendering
path, but neither neutralises a formula payload. The escape belongs in `app/reports.py`; until then the
UI must not describe an export as sanitised.

**Failed-login auditing.** `F-28` / `SEC-AUD-01`. Five failed logins produce zero `auth.failed` rows.
The audit screen must disclose this per `FR-S11-03` rather than implying complete coverage.

**Credential hygiene.** `F-04` / `SEC-AUTH-04`. The login form ships with `value="analyst"` and
`value="analyst123"` in the HTML source, and all three passwords are printed in visible text. Clear
both per `FR-S1-02` and `FR-S1-03`.

**AI disclosure.** `AI-disclosure`: whenever a generated sentence is rendered, show the model name,
the mode, whether external data was used, and the guarantee list from `/api/ai/status`. **Verified
Implemented** at `app.js:331-343`; preserve it and extend it to the board HTML report.

**Privacy.** No personal data beyond usernames, roles and action timestamps. The redaction toggle in
`FR-S9-04` addresses asset identifiers, not personal data. No analytics, telemetry, third-party fonts or
CDN scripts are used, so there is no third-party data flow to disclose — a genuine strength worth
stating in the demo.

**Disclaimer integrity.** The synthetic-data banner and the estimate disclaimer must survive every
export format, every chart, and every screenshot. Verified present in the Markdown report today. If
an abbreviation, a rounded percentage or a cropped chart ever removes a disclaimer, that is a defect.

---

## 13. Accessibility

Target **WCAG 2.1 AA**, as a **proposed** goal. No audit performed. Contrast results in §6.2 are the
only verified measurements.

**Verified to comply today:** text contrast on all backgrounds and pills; the text label on every
status pill, so colour is never the sole indicator; `<details>` disclosure on confidence reasons;
correct `autocomplete` attributes and `type="password"`.

**Confirmed defect:** control borders at 1.30:1 (§6.2). Fix with `--line-strong`.

**Proposed MVP, in priority order.**

1. Visible focus indicator on every interactive element (`--focus`, 2px with 2px offset).
2. `aria-live` regions for async outcomes; `COMP-08` is currently visual-only.
3. Proper tab semantics: `role="tablist"`, `aria-selected`, `aria-controls`, arrow-key navigation.
4. `scope` on every `<th>`; a programmatic indication of numeric column direction.
5. Remove `window.prompt` (`FR-S5-01`) — browser modals are a keyboard and screen-reader dead end.
6. Text equivalents for every chart, including the underlying values in a table.
7. Landmarks: `header`, `nav`, `main`, and a per-screen `h1`; today `h2`/`h3` start the hierarchy.
8. Respect `prefers-reduced-motion` for any chart or transition animation added later.
9. Minimum 16px input text on touch to prevent iOS zoom-on-focus. **This is a real current defect:**
   `styles.css` sets `input, select { font-size: 14px }`, and iOS Safari zooms on focus below 16px.

---

## 14. Responsive design and platform support

Current behaviour, from `styles.css`: `main` is capped at 1280px; `.kpis` is a
`repeat(auto-fit, minmax(200px, 1fr))` grid; `.two-col` collapses to one column below 900px; the tab
strip wraps. That is a reasonable foundation.

**Target devices [TBD].** No device analytics, no user device survey, and no stated target. Proposed
support matrix:

| Class | Viewport | Treatment |
|---|---|---|
| Desktop primary | ≥1280px | Full layout, side-by-side comparison columns |
| Laptop | 1024–1279px | Two-column grids hold; reduce table density |
| Tablet | 768–1023px | Single column; tables scroll horizontally with a sticky first column |
| Mobile | 320–767px | **Read-only demo support only.** Cards instead of wide tables; a full risk-modelling workflow is not a mobile task |

**Do not claim mobile support without testing.** No responsive test has been run. The honest
statement is "designed for desktop, degrades to a readable single column, not verified on mobile".

**Browser support [TBD].** No `browserslist`, no build step, no polyfills. Proposed: the two most
recent versions of Chrome, Edge, Firefox and Safari, plus iOS Safari. The client uses
`fetch`, `Promise`, optional-chaining-free ES2017 syntax, `toLocaleString("en-IN")` and CSS custom
properties. **Note:** `toLocaleString("en-IN")` output is ICU-dependent, so lakh/crore grouping must
be regression-tested on each target browser rather than assumed. Abbreviation per §5.2 must therefore
be implemented manually rather than delegated to `Intl.NumberFormat` notation support, whose
availability varies.

---

## 15. Performance

**No performance measurement exists.** The figures below are **proposed** targets. `plan.runtime_ms`
is real but measures the solver only — 16 ms for 120 candidate plans in the verified run — and says
nothing about page load, render or network time.

| Metric | Proposed target | Status |
|---|---|---|
| First contentful paint | < 1.0 s | Proposed, unmeasured |
| Largest contentful paint | < 2.0 s | Proposed, unmeasured |
| Interaction to next paint | < 200 ms | Proposed, unmeasured |
| Tab switch, data already loaded | < 150 ms | Proposed, unmeasured |
| Full assessment recompute | < 1.0 s | Proposed, unmeasured |
| `POST /api/optimise`, 12 actions, exact | < 500 ms | Solver measured at 16 ms; end-to-end unmeasured |
| `POST /api/ask` | < 5 s | Unmeasured, depends on provider |
| Cumulative JS transferred | < 100 KB | Proposed; `app.js` is ~16 KB today, plus zero dependencies |

**Known optimisations, all low-risk.** `enterApp()` already loads four endpoints in parallel, which is
right. The report preview is already lazy-loaded on first click. The highest-value additions are
virtualisation or pagination on the scenario and audit tables, and caching the assessment for the
duration of a session so switching tabs does not refetch.

**A caution on perceived performance.** The optimiser is fast, and that is worth showing. But the
`runtime_ms` label must not become a substitute for real page timing, and no claim in the demo should
state a load time that has not been measured.

---

## 16. Error, empty, loading, and edge states

| State | Requirement | Present today |
|---|---|---|
| Initial load | Skeleton reserving layout height; no spinner-only screen | No |
| Tab switch, cached data | No spinner, no reflow | No |
| Background refresh | Non-blocking indicator; do not clear existing data | No |
| Slow request (>3 s) | Progress message with a cancel affordance | No |
| Network failure | Plain-language cause plus retry; preserve user input | Partial — `toast(err.message)` only |
| Validation error | Inline, next to the field, `aria-describedby` wired | Partial — `toast` only |
| Empty result set | One sentence, one action, never a bare table | No |
| Zero affordable actions | Explain, suggest a larger budget, show the cheapest action's cost | No |
| Permission denied | Name the role required and who to contact | Partial — server message only |
| Stale data | Amber chip, non-blocking, with the age | No |
| Low confidence | Inline caveat plus the "why" disclosure | Partial — disclosure only |
| Incomplete model | Warning listing `incomplete_reasons` and `excluded_findings` | No |
| LLM disabled | Disable Ask, explain, offer alternatives on the report screen | No |
| Quarantined rows | Warning with a download of the rejected rows | Partial — count only |
| `rosi` null | Never render `null` | No — renders the string "null" |
| API error body | Never display a stack trace or internal path | Not verified |

**The universal rule:** a state that is not designed is a state that will be seen during the demo,
because demos are run on unfamiliar machines with unfamiliar data. Every row in this table is a
plausible demo failure, and the empty-result and null-ROSI rows in particular are **verified reachable
with the shipped seed data** at a ₹25,000 budget.

---

## 17. Test plan and demo validation

### 17.1 Frontend test layers

1. **Contract tests** — extend the existing `tests/test_api.py` to assert that every field named in
   §11 is present in the response. A field the UI renders but the API omits is the `threat_actor`
   failure in §8.4, and it should have been caught automatically.
2. **Rendering tests** — for each screen, assert the populated, empty, error, stale and
   permission-denied states from §16. `null` and `undefined` must never reach the DOM.
3. **Security regression tests** — every finding referenced in this document gets a test:
   `F-3` quote-bearing `scenario_code`; `F-25` natural-phrasing refusals for compliance, benchmark,
   attribution and prediction questions; `F-26` CSV formula payloads; `F-28` five failed logins
   producing persisted `auth.failed` rows. `SEC-F-01`, `SEC-AI-01`, `SEC-RPT-01` and `SEC-AUD-01` in
   `docs/SECURITY_ACCESS_REQUIREMENTS.md` remain canonical.
4. **Accessibility tests** — automated contrast assertions over the tokens in §4, plus a keyboard-only
   walk of S1 → S5 → S6. Automated tooling catches roughly a third of WCAG issues; the keyboard walk is
   manual and is not optional.
5. **Visual regression** — golden screenshots per screen per state, per role. **Not started; there is
   no existing baseline.**
6. **Performance** — measure the §15 targets and replace each "proposed" with a measurement or an
   explicit target. Until then the document keeps saying "proposed".

### 17.2 Golden examples for UI and core parity

**There are two distinct fixtures in this repository, and they are not interchangeable.** Conflating
them is the easiest way to publish a wrong number, so both are recorded here with the figures each one
actually produces.

#### Fixture A — `docs/worked_example.py` (self-contained worked example)

Used for the model walkthrough and for testing the optimiser's constraint, overlap and negative-ROSI
paths that the app seed cannot reach.

| Check | Expected |
|---|---|
| Portfolio EAL | `13111990` minor → ₹1,31,120 |
| EAL sensitivity range | `4589196` – `25568380` → ₹45,892 – ₹2,55,684 |
| Confidence | 95, band High |
| Scenarios | `S-1` (₹1,13,609), `S-2` (₹35,022) |
| Assets | `A-1`, `A-2` |
| Freshness | source `scanner`, `age_days 2.18`, band `fresh` |
| What-if `S-1` `p0 0.35 → 0.10` | total ₹51,454, delta −₹79,66,581 |
| Optimise, ₹1,50,000 | `ACT-EDR-TUNE, ACT-PAM, ACT-PATCH`, cost ₹78,000, ROSI −0.773, `overlap_penalty` ₹5,545 |
| Rejection reasons present | `"Mutually exclusive with Privileged access management rollout"`, `"Feasible, but estimated risk reduction is lower than actions in the plan"` |

#### Fixture B — the running application seed data

Used for the demo and for the UI acceptance tests. Every figure below was captured from a live server
during this review.

| Check | Expected |
|---|---|
| Portfolio EAL | `1106227077` minor → ₹1,10,62,271 (₹1.11 Cr abbreviated) |
| Portfolio sensitivity range | `387179477` – `2157142800` → ₹38.72 L – ₹2.16 Cr |
| Unadjusted scenario total | `1310639446` → ₹1,31,06,394 |
| Confidence | 61, band Medium |
| Top scenario | `S3` ₹40,89,503 (₹40.90 L), confidence 54 Low |
| `S1` | SLE ₹9,80,00,000, `p_inherent` 7.06%, `p_residual` 3.56%, EAL ₹34,85,662, confidence 54 Low |
| `S1` confidence reasons | assumed control effectiveness; finding data 12 days old; capped at Medium |
| Business units | Corporate IT ₹35,28,951; Payments ₹30,67,284; Retail ₹26,14,380; Finance ₹18,51,655 |
| Freshness | source `SimulatedScanner`, `age_days 11.93`, band `aging` |
| Synthetic share | 100% of assets |
| Optimise, ₹5,00,00,000 | `ACT-1, ACT-4, ACT-8`, cost ₹44,00,000, reduction 52.73%, ROSI `0.3257`, 120 plans, 16 ms |
| Currency | INR, symbol ₹ |

**Label every one of these "illustrative" wherever it appears.** They are seed-data outputs, not
observed measurements, and the two fixtures disagree by roughly four orders of magnitude.

### 17.3 Manual acceptance checklist

Per screen: correct data; correct role visibility; banner present; disclaimer present; freshness chip
present; loading, empty, error and stale states handled; keyboard-only operable; no `null` or
`undefined` in the DOM; no color-only meaning; no client-side business calculation; no console errors;
export matches what is on screen.

### 17.4 Demo script

1. Sign in as `ciso`. The dashboard loads with no interaction, and the banner is visible.
2. Read the headline: `₹1.11 Cr`, the sensitivity band `₹38.72 L – ₹2.16 Cr`, confidence Medium 61, and
   the estimate disclaimer.
3. Open the "why" disclosure on the lowest-confidence scenario. **Read the reasons aloud** — "at least
   one control effectiveness is assumed", "finding data is 12 days old". This is the strongest
   credibility moment in the product and it is already implemented.
4. Note the correlation-adjustment explanation, and that shares sum above 100% by design.
5. Filter by business unit. Drill Retail → `A1-OMS-DB-PROD` → `S1` via the breadcrumb.
6. In What-if, move `p0` with the slider. **Show the baseline and the projection side by side, then
   return to baseline.** This is the fix in `FR-S5-02` and it should be the centrepiece.
7. In Optimizer, set ₹5 crore. Expect `ACT-1, ACT-4, ACT-8`, cost ₹44.00 L, reduction 52.73%, ROSI 0.33,
   "proven optimal · exact search · 120 plans". Read the rejected list and **its reasons**.
8. Ask: "What is our largest exposure?" Read the grounding references. Then ask an out-of-scope
   question and **show the clean refusal**. Do not click a chip that the system cannot refuse.
9. Download the board report. Confirm the synthetic-data banner and the estimate disclaimer survived
   into the file.
10. Sign in as `admin` and open Data & Validation, then Audit Log & Users. **State the `SEC-AUD-01`
    limitation out loud** if the audit screen still carries its banner.

**Claim discipline for the demo.** Say "the model quantifies expected loss under these assumptions."
Do not say it predicts breaches. Do not say the numbers are a percentile range. Do not say the system
is compliant with any framework. Do not quote a load time that has not been measured. Each of those
four claims is currently false, and the first three are the ones a technical judge will test.

### 17.5 Official-source verification

Framework references in this document and in the data are **catalogue labels from the seed dataset**.
No mapping against a published standard, and no certification claim, is asserted anywhere in the
product. Any such claim would need verification against the official framework text and appropriate
licensing, and is Future Scope in §18.

---

## 18. Out of scope, future scope, and known blockers

### 18.1 Blockers, stated plainly

1. **No time-series data exists.** The 12-month EAL trend required on the Executive Dashboard cannot be
   built without a persistence layer and a historical model. The trend panel is the one chart in this
   specification that is blocked on modelling, not on rendering. Until then, ship the confidence
   breakdown in its place.
2. **No framework requirement catalogue exists.** There is no clause-level mapping data, so a genuine
   coverage percentage is impossible. `FR-S8-02` forbids faking one.
3. **No run persistence.** Nothing is stored, so there is no run ID to display, and a report cannot
   reference the exact run that produced it. This is finding `F-1`.
4. **Feasibility constraints are not exercised by the app seed data.** No action sets
   `capacity_group` or `requires_actions`, so `feasibility[]` is always empty and no overlap penalty
   is ever non-zero. The dependency, overlap and negative-ROSI UI must be built and unit-tested
   against the `docs/worked_example.py` fixture in §17.2, which does exercise them. The demo script
   must not claim to show constraint behaviour the seed data cannot produce.
5. **No LLM provider is configured.** `GET /api/ai/status` returns `model: null` when disabled. Every
   Ask and board-HTML state must be designed and tested in the disabled configuration, which is
   currently the default.

### 18.2 Future Scope

- React migration, with a build step, if a component model and client-side routing become worth their
  cost. Not required for any requirement in this document.
- Portfolio-versus-portfolio comparison.
- Sensitivity or Monte Carlo analysis, which would make a genuine percentile range possible and would
  change the labelling rules in §5.4.
- Collaboration: saved scenarios, comments, review workflow, approvals.
- Notification and alerting on stale data or on a threshold breach.
- Scheduled scans and continuous ingestion.
- Localisation. Note that `toLocaleString("en-IN")` output and the lakh/crore abbreviations are
  India-specific by design, per the stated requirement.
- A real clause-level compliance catalogue, subject to licensing.
- Multi-organisation tenancy, which is a data-model change and not a frontend change.
- Native mobile applications. Out of scope; the responsive site is read-only support.

### 18.3 Explicitly not doing

- Not claiming certification, compliance or audit status.
- Not predicting or forecasting breaches.
- Not presenting the sensitivity band as a statistical confidence interval.
- Not claiming any measured performance, accessibility conformance level, or usability validation.
- Not adding a front-end framework, charting dependency, CDN script, web font or analytics tag before
  the demo. Zero dependencies is a genuine strength of the current build.

---

## Screen-by-screen quick reference

One line per screen. This is the section to read before a demo or a code review.

| # | Screen | Primary purpose | Role | Key data | Current state | Highest-priority change |
|---|---|---|---|---|---|---|
| S1 | **Login** | Start an authenticated session | All | Session payload | **Verified Implemented** | Ship empty fields; remove visible passwords (`FR-S1-02`, `FR-S1-03`) |
| S2 | **Data & Validation** | Load, validate, trust the input | Admin | `counts`, `recent_datasets`, `findings_summary` | Partial | Surface `unmatched` and rejected rows; add freshness, template, reset (`FR-S2-02`, `FR-S2-03`) |
| S3 | **Executive Dashboard** | Portfolio risk in ten seconds | Executive | `eal_minor`, band, `by_business_unit` | Partial | Render BU and contributor charts from data already present; **no trend until history exists** (`FR-S3-03`, `FR-S3-04`) |
| S4 | **Risk Explorer** | Trace the number to its cause | Analyst | Scenario, `breakdown`, `control_detail`, `confidence_reasons` | Partial | Remove the dead `threat_actor` column; add filters and drill-down breadcrumb (`FR-S4-03`, `FR-S4-04`) |
| S5 | **What-if Simulator** | Change an assumption, keep the baseline | Analyst | `p0` override, full assessment | Partial | **Stop destroying the baseline; remove `window.prompt`** (`FR-S5-01`, `FR-S5-02`) |
| S6 | **Investment Optimizer** | Best plan for a budget, and why | Analyst | `plan`, `rejected`, `frontier` | Partial | Draw the real curve; move frontier ROSI server-side; design the empty state (`FR-S6-04`, `FR-S6-07`) |
| S7 | **Ask** | Grounded natural-language answers | All three | Answer, grounding, guarantees | Implemented, with a caveat | **Remove the two suggested chips the backend cannot refuse** (`FR-S7-02`) |
| S8 | **Compliance Mapping** | Controls and their use, without claiming certification | Analyst | `controls`, `ce_source` | Not implemented | Build the list; **never a coverage % or a verdict** (`FR-S8-01`, `FR-S8-02`) |
| S9 | **Reports & Export** | Shareable artefact with disclaimers intact | All | Report contents, headers | Partial | Add redaction, per-format contents, LLM-disabled explanation (`FR-S9-04`, `FR-S9-06`) |
| S10 | **Assumptions & Settings** | Make every constant inspectable | Admin | Multipliers, `rho_used`, currency | Not implemented | Show all four multipliers with their source; confirm before apply (`FR-S10-01`, `FR-S10-02`) |
| S11 | **Audit Log & Users** | Accountability | Admin | `/api/audit`, users | Not implemented (API exists) | Build the screen; **disclose the `F-28` failed-login gap** (`FR-S11-03`) |

### The five things to fix first

| Order | Fix | Requirement | Why it is first |
|---|---|---|---|
| 1 | Stop overwriting the baseline in What-if | `FR-S5-02` | A correctness bug. After one override the analyst cannot see real exposure. |
| 2 | Remove the two out-of-scope Ask chips | `FR-S7-02` | They lead a judge straight into the verified `F-25` refusal bypass. |
| 3 | Fix the 1.30:1 control borders | `FR-G-08` | The only confirmed accessibility defect; a two-line CSS change. |
| 4 | Remove the pre-filled credentials and visible passwords | `FR-S1-02`, `FR-S1-03` | Ships `SEC-AUTH-04` in the HTML source; undermines the login in the first five seconds. |
| 5 | Render `by_business_unit` and freshness | `FR-S3-03`, `FR-G-03` | Both are already in the API; the highest value per line of code in this document. |

### Labels used in this document

**Verified Implemented** — read or executed in the repository, with a file:line or a command result.
**Proposed MVP** — should be built, not present today. **Future Scope** — deliberately deferred.
**TBD** — unknown and not discoverable from the repository. **[P]** — proposed behaviour. **[proposed]**
— a target awaiting measurement. **Illustrative** — a seeded synthetic value, not a measurement.
