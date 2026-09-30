"use strict";

const state = { user: null, assessment: null, catalog: null, plan: null };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function money(minor) {
  if (minor === null || minor === undefined) return "n/a";
  return "₹ " + (minor / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function pct(value, digits = 1) {
  if (value === null || value === undefined) return "n/a";
  return (value * 100).toFixed(digits) + "%";
}
function num(value, digits = 3) {
  if (value === null || value === undefined) return "n/a";
  return Number(value).toFixed(digits);
}
function esc(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  const text = await response.text();
  let payload = {};
  try { payload = text ? JSON.parse(text) : {}; } catch (err) { payload = { detail: text }; }
  if (!response.ok) {
    throw new Error(typeof payload.detail === "string" ? payload.detail
                    : JSON.stringify(payload.detail || payload));
  }
  return payload;
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.hidden = true; }, 3200);
}

// ----------------------------------------------------------------- session
$("#login-btn").addEventListener("click", async () => {
  $("#login-error").textContent = "";
  try {
    const body = {
      username: $("#username").value.trim(),
      password: $("#password").value,
    };
    state.user = await api("/api/login", { method: "POST", body: JSON.stringify(body) });
    await enterApp();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

async function enterApp() {
  $("#login-panel").hidden = true;
  $("#app").hidden = false;
  $("#session").innerHTML =
    `${esc(state.user.username)} &middot; ${esc(state.user.role)} ` +
    `<button class="ghost" id="logout-btn">Sign out</button>`;
  $("#logout-btn").addEventListener("click", async () => {
    await api("/api/logout", { method: "POST" });
    location.reload();
  });
  await Promise.all([loadOverview(), loadCatalog(), loadAssessment(), loadData()]);
  loadAIStatus();
}

$$(".tab").forEach((tab) => tab.addEventListener("click", () => {
  $$(".tab").forEach((t) => t.classList.remove("active"));
  $$(".tabpanel").forEach((p) => p.classList.remove("active"));
  tab.classList.add("active");
  $("#tab-" + tab.dataset.tab).classList.add("active");
}));

// ----------------------------------------------------------------- exposure
async function loadOverview() {
  const data = await api("/api/overview");
  const c = data.counts;
  $("#kpis").innerHTML = `
    <div class="kpi"><div class="label">Assets</div><div class="value">${c.assets}</div>
      <div class="note">${c.findings} findings, ${c.quarantine} quarantined rows</div></div>
    <div class="kpi"><div class="label">Scenarios</div><div class="value">${c.scenarios}</div>
      <div class="note">${c.controls} controls, ${c.actions} candidate actions</div></div>
    <div class="kpi"><div class="label">Data loads</div><div class="value">${c.datasets}</div>
      <div class="note">${pct(data.synthetic_asset_share, 0)} of assets are synthetic</div></div>`;
}

async function loadCatalog() {
  state.catalog = await api("/api/catalog");
}

async function loadAssessment(actions) {
  const query = actions && actions.length ? "?actions=" + encodeURIComponent(actions.join(",")) : "";
  const data = await api("/api/assessment" + query);
  state.assessment = data.assessment;
  renderExposure();
}

function renderExposure() {
  const a = state.assessment;
  const ranked = [...a.scenarios].sort((x, y) => y.eal_minor - x.eal_minor);
  const maxEal = ranked.length ? ranked[0].eal_minor : 1;
  const unadjusted = a.eal_unadjusted_minor || 1;
  const adjustment = unadjusted ? (1 - a.eal_minor / unadjusted) : 0;

  const top = ranked[0];
  $("#exposure-kpis").innerHTML = `
    <div class="kpi"><div class="label">Expected annual loss</div>
      <div class="value">${money(a.eal_minor)}</div>
      <div class="note">${money(a.eal_low_minor)} to ${money(a.eal_high_minor)}</div></div>
    <div class="kpi"><div class="label">Largest scenario</div>
      <div class="value">${top ? money(top.eal_minor) : "n/a"}</div>
      <div class="note">${top ? esc(top.scenario_code) + " · " + esc(top.business_unit) : ""}</div></div>
    <div class="kpi"><div class="label">Correlation adjustment</div>
      <div class="value">${pct(-adjustment)}</div>
      <div class="note">unadjusted ${money(unadjusted)}</div></div>
    <div class="kpi"><div class="label">Data confidence</div>
      <div class="value">${esc(a.confidence_band)}</div>
      <div class="note">${a.confidence}/100</div></div>`;

  $("#scenario-table tbody").innerHTML = ranked.map((s, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${esc(s.name)}<div class="muted">${esc(s.scenario_code)} ·
        ${esc(s.threat_actor || "unknown actor")}</div></td>
      <td>${esc(s.asset_id)}<div class="muted">${esc(s.business_unit)}</div></td>
      <td class="num">${money(s.sle_minor)}</td>
      <td class="num">${pct(s.p_inherent, 2)}</td>
      <td class="num">${pct(s.mitigation_factor, 1)}</td>
      <td class="num">${pct(s.p_residual, 2)}</td>
      <td class="num">${money(s.eal_minor)}</td>
      <td class="num"><div class="bar"><span style="width:${Math.min(100, s.eal_minor / maxEal * 100)}%"></span></div>
        ${pct(s.eal_minor / unadjusted, 1)}</td>
      <td><span class="pill ${s.confidence_band.toLowerCase()}">${esc(s.confidence_band)}</span>
        <details><summary>why</summary><ul>${(s.confidence_reasons || [])
          .map((r) => `<li>${esc(r)}</li>`).join("")}</ul></details></td>
      <td><button class="ghost" data-scenario="${esc(s.scenario_code)}">what-if</button></td>
    </tr>
    <tr><td></td><td colspan="10" class="muted">
      <details><summary>loss components and control detail</summary>
        <table><thead><tr><th>component</th><th class="num">amount</th><th>source</th>
          <th>control</th><th class="num">CE applied</th></tr></thead><tbody>
        ${(s.breakdown || []).map((b) => `<tr><td>${esc(b.component_code)}</td>
            <td class="num">${money(b.amount_minor)}</td>
            <td class="muted">${esc(b.source_ref || "unsourced")}</td><td></td><td></td></tr>`).join("")}
        ${(s.control_detail || []).map((c) => `<tr><td></td><td></td><td></td>
            <td>${esc(c.name)}${c.changed ? ' <span class="pill info">changed</span>' : ""}</td>
            <td class="num">${pct(c.ce_applied, 0)}</td></tr>`).join("")}
        </tbody></table></details></td></tr>`).join("");

  const assets = Object.entries(a.by_asset).sort((x, y) => y[1] - x[1]);
  const byId = Object.fromEntries((state.catalog?.assets || []).map((x) => [x.asset_id, x]));
  $("#asset-table tbody").innerHTML = assets.map(([id, eal]) => `
    <tr><td>${esc(id)}<div class="muted">${esc(byId[id]?.name || "")}</div></td>
      <td>${esc(byId[id]?.business_unit || "")}</td>
      <td class="num">${money(eal)}</td>
      <td class="num">${pct(eal / (a.eal_minor || 1), 1)}</td></tr>`).join("");

  $("#control-table tbody").innerHTML = ranked.flatMap((s) =>
    (s.control_detail || []).map((c) => `
      <tr><td>${esc(s.scenario_code)}</td>
        <td>${esc(c.name)} <span class="muted">${esc(c.control_code)}</span></td>
        <td class="num">${pct(c.ce_base, 0)}</td>
        <td class="num">${pct(c.ce_applied, 0)}</td>
        <td class="muted">${esc(c.ce_source)}${c.ce_evidence_ref ? " · " + esc(c.ce_evidence_ref) : ""}</td>
        <td class="muted">ISO ${esc(c.framework_iso || "n/a")} · NIST ${esc(c.framework_nist || "n/a")}
          · CIS ${esc(c.framework_cis || "n/a")}</td></tr>`)).join("");

  $("#overlap-note").textContent =
    `Shares are of the unadjusted scenario total (${money(unadjusted)}). Correlated ` +
    `scenarios overlap by design, so the shares sum to more than 100% while the ` +
    `headline figure is ${money(a.eal_minor)} after correlation adjustment.`;

}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-scenario]");
  if (!button) return;
  const code = button.dataset.scenario;
  const scenario = state.assessment.scenarios.find((s) => s.scenario_code === code);
  const current = scenario.p_inherent;
  const suggested = Math.min(0.5, current * 1.5);
  const answer = window.prompt(
    `Residual annual probability for ${code} is ${pct(scenario.p_residual, 2)}.\n` +
    `Enter a new inherent p0 (0-0.5), currently ${num(scenario.p_inherent, 4)}:`, suggested);
  if (answer === null) return;
  const p0 = Number(answer);
  if (!Number.isFinite(p0) || p0 <= 0 || p0 > 0.5) { toast("p0 must be between 0 and 0.5"); return; }
  const data = await api(`/api/scenarios/${encodeURIComponent(code)}/whatif`,
    { method: "POST", body: JSON.stringify({ p0 }) });
  const before = state.assessment.eal_minor;
  state.assessment = data.assessment;
  renderExposure();
  toast(`${code}: portfolio EAL ${money(before)} → ${money(data.assessment.eal_minor)}`);
});

// ----------------------------------------------------------------- optimise
$("#optimise-btn").addEventListener("click", runOptimise);

async function runOptimise() {
  const budget = Math.round(Number($("#budget").value) * 100);
  const maxActions = Number($("#max-actions").value);
  if (!Number.isFinite(budget) || budget <= 0) { toast("Enter a budget"); return; }
  const button = $("#optimise-btn");
  button.disabled = true;
  button.textContent = "Optimising…";
  try {
    const data = await api("/api/optimise", {
      method: "POST",
      body: JSON.stringify({ budget_minor: budget, max_actions: maxActions, exact: true }),
    });
    state.plan = data.plan;
    renderPlan();
    await loadAssessment(data.plan.selected);
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
    button.textContent = "Optimise";
  }
}

function renderPlan() {
  const p = state.plan;
  $("#plan-kpis").innerHTML = `
    <div class="kpi"><div class="label">EAL after plan</div>
      <div class="value">${money(p.plan_eal_minor)}</div>
      <div class="note">from ${money(p.baseline_eal_minor)}</div></div>
    <div class="kpi"><div class="label">Reduction</div>
      <div class="value">${pct(p.reduction_pct / 100, 1)}</div>
      <div class="note">${money(p.reduction_minor)} per year</div></div>
    <div class="kpi"><div class="label">Plan cost</div>
      <div class="value">${money(p.cost_minor)}</div>
      <div class="note">budget ${money(p.budget_minor)} ·
        ${p.capacity_used}/${p.capacity_max} actions</div></div>
    <div class="kpi"><div class="label">ROSI</div>
      <div class="value">${num(p.rosi, 2)}</div>
      <div class="note">${p.optimal ? "proven optimal" : "best effort"} ·
        ${p.method}, ${p.candidates_evaluated} plans in ${p.runtime_ms} ms</div></div>`;

  $("#plan-table tbody").innerHTML = (p.selected_detail || []).map((d) => `
    <tr><td>${esc(d.name)}<div class="muted">${esc(d.action_code)}</div></td>
      <td class="num">${money(d.cost_minor)}</td>
      <td class="num">${money(d.marginal_reduction_minor)}
        <div class="muted">standalone ${money(d.standalone_reduction_minor)}</div></td>
      <td class="num">${num(d.marginal_rosi, 2)}</td>
      <td>${d.lead_time_days}d</td></tr>`).join("");

  $("#reject-table tbody").innerHTML = (p.rejected || []).map((r) => `
    <tr><td>${esc(r.name)}<div class="muted">${esc(r.action_code)} ·
      ${money(r.cost_minor)}</div></td><td class="muted">${esc(r.reason)}</td></tr>`).join("");

  renderFrontier();
}

async function renderFrontier() {
  const data = await api("/api/optimise/frontier?steps=10");
  const points = data.frontier;
  const maxReduction = Math.max(...points.map((p) => p.reduction_minor), 1);
  const width = 100 / Math.max(points.length - 1, 1);
  $("#frontier").innerHTML = `
    <table><thead><tr><th class="num">Budget</th><th class="num">Plan cost</th>
      <th class="num">EAL after plan</th><th class="num">Reduction</th>
      <th class="num">ROSI</th><th>Selected</th></tr></thead><tbody>
    ${points.map((p) => {
      const rosi = p.cost_minor ? (p.reduction_minor - p.cost_minor) / p.cost_minor : null;
      return `<tr><td class="num">${money(p.budget_minor)}</td>
        <td class="num">${money(p.cost_minor)}</td>
        <td class="num">${money(p.plan_eal_minor)}</td>
        <td class="num">${money(p.reduction_minor)}
          <div class="bar"><span style="width:${p.reduction_minor / maxReduction * 100}%"></span></div></td>
        <td class="num">${num(rosi, 2)}</td>
        <td class="muted">${esc(p.selected.join(", ") || "none")}</td></tr>`;
    }).join("")}</tbody></table>
    <p class="muted">Marginal ROSI turns negative where a budget step buys almost no
      additional reduction. That is the signal that the plan is over-funded, not that
      the optimiser failed.</p>`;
}

// ----------------------------------------------------------------- AI
const SUGGESTIONS = [
  "Which scenario is the largest and why?",
  "What is our total exposure?",
  "Which asset should we worry about?",
  "How confident are these numbers?",
  "What if S1 probability doubled?",
  "Will we be breached next year?",
  "Are we compliant with ISO 27001?",
];
$("#suggestions").innerHTML = SUGGESTIONS
  .map((q) => `<span class="chip" data-q="${esc(q)}">${esc(q)}</span>`).join("");
$("#suggestions").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  $("#question").value = chip.dataset.q;
  $("#ask-btn").click();
});
$("#ask-btn").addEventListener("click", askQuestion);
$("#question").addEventListener("keydown", (e) => {
  if (e.key === "Enter") askQuestion();
});

async function askQuestion() {
  const question = $("#question").value.trim();
  if (!question) return;
  const button = $("#ask-btn");
  button.disabled = true;
  try {
    const answer = await api("/api/ask", {
      method: "POST", body: JSON.stringify({ question }),
    });
    renderAnswer(answer);
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
  }
}

function renderAnswer(answer) {
  const el = document.createElement("div");
  el.className = "answer";
  const warnings = (answer.warnings || []).map((w) => `<div>${esc(w)}</div>`).join("");
  const rejected = answer.rejected
    ? `<div class="meta rejected">rejected: ${esc(answer.reject_reason || "")}</div>` : "";
  el.innerHTML = `
    <div class="q">${esc(answer.question)}</div>
    <div class="a">${esc(answer.text)}</div>
    <div class="meta">source: ${esc(answer.source)} · grounded: ${answer.grounded ? "yes" : "no"}
      · context ${answer.context_size} bytes</div>${rejected}${warnings}`;
  $("#answers").prepend(el);
}

async function loadAIStatus() {
  const data = await api("/api/ai/status");
  $("#ai-rules").innerHTML = data.guarantees.map((g) => `<li>${esc(g)}</li>`).join("");
  if (!data.llm_enabled) {
    $("#suggestions").insertAdjacentHTML("afterbegin",
      `<span class="muted">mode: deterministic template (no LLM key configured)</span>`);
  }
}

// ----------------------------------------------------------------- data
$("#upload-btn").addEventListener("click", async () => {
  const input = $("#upload-file");
  if (!input.files.length) { toast("Choose a CSV or JSON file"); return; }
  const form = new FormData();
  form.append("dataset_type", $("#dataset-type").value);
  form.append("commit", $("#commit").checked ? "true" : "false");
  form.append("file", input.files[0]);
  try {
    const result = await api("/api/ingest", { method: "POST", body: form });
    const codes = (result.errors || []).map((e) => e.code);
    $("#upload-result").innerHTML =
      `<strong>${esc(result.status)}</strong> — ${esc(result.message)} ` +
      `(${result.rows_ok} ok, ${result.rows_quarantined} quarantined` +
      `${codes.length ? ", issues: " + esc([...new Set(codes)].join(", ")) : ""})`;
    await Promise.all([loadOverview(), loadAssessment(), loadData()]);
  } catch (err) {
    $("#upload-result").textContent = err.message;
  }
});

$("#demo-d0").addEventListener("click", () => resetDemo(false));
$("#demo-d30").addEventListener("click", () => resetDemo(true));

async function resetDemo(refresh) {
  try {
    const data = await api(`/api/demo/reset?refresh=${refresh}`, { method: "POST" });
    toast(`synthetic ${data.variant} loaded: ${JSON.stringify(data.counts)}`);
    state.assessment = data.assessment;
    renderExposure();
    await Promise.all([loadOverview(), loadCatalog(), loadData()]);
  } catch (err) {
    toast(err.message);
  }
}

async function loadData() {
  const [overview, quarantine] = await Promise.all([
    api("/api/overview"),
    api("/api/quarantine?limit=50").catch(() => ({ rows: [] })),
  ]);
  $("#dataset-table tbody").innerHTML = (overview.recent_datasets || []).map((d) => `
    <tr><td>${esc(d.dataset_type)}${d.synthetic ? ' <span class="pill info">synthetic</span>' : ""}</td>
      <td class="muted">${esc(d.filename)}</td><td>${esc(d.status)}</td>
      <td class="num">${d.rows_total}</td><td class="num">${d.rows_ok}</td>
      <td class="num">${d.rows_updated}</td><td class="num">${d.rows_quarantined}</td>
      <td class="muted">${esc((d.loaded_at || "not committed").slice(0, 19))}</td></tr>`).join("");
  $("#quarantine-table tbody").innerHTML = (quarantine.rows || []).map((r) => `
    <tr><td class="muted">${esc(r.dataset_type)} / ${esc(r.filename)}</td>
      <td class="num">${r.row_number}</td><td>${esc(r.reason)}</td></tr>`).join("")
    || '<tr><td colspan="3" class="muted">nothing quarantined</td></tr>';
}

// ----------------------------------------------------------------- report
$("#dl-html").addEventListener("click", (event) => {
  const budget = Number($("#budget").value) * 100;
  if (Number.isFinite(budget) && budget > 0) {
    event.target.href = `/api/report/board.html?budget_minor=${Math.round(budget)}`;
  }
});

$("#tab-report").addEventListener("click", async () => {
  if ($("#report-preview").textContent) return;
  const response = await fetch("/api/report/summary.md", { credentials: "same-origin" });
  $("#report-preview").textContent = await response.text();
}, { once: true });

// ----------------------------------------------------------------- boot
api("/api/me").then((user) => { state.user = user; return enterApp(); })
  .catch(() => { $("#login-panel").hidden = false; });
