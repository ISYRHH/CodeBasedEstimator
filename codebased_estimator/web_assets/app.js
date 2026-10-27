"use strict";

const $ = (id) => document.getElementById(id);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const optionalText = (id, text) => { const element = $(id); if (element) element.textContent = text; };
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const number = (value, digits = 2) => Number.isFinite(value) ? value.toLocaleString("en-US", {minimumFractionDigits:digits, maximumFractionDigits:digits}) : "—";
const human = (value) => ({key_recovery:"Key recovery",msg_recovery:"Message recovery",both:"Both recovery goals",computed:"Computed",not_requested:"Not selected",not_implemented:"Not implemented",not_applicable:"Not applicable",infeasible:"Infeasible",unavailable:"Unavailable",incomparable_units:"Different units",unsupported:"Unsupported",failed:"Failed"}[value] || String(value ?? "").replaceAll("_", " "));
const unit = (value) => ({bit_operations:"bit operations",quantum_bit_operations:"quantum bit operations",bits:"bits",not_estimated:"not estimated"}[value] || value || "unspecified");
const HISTORY_KEY = "codebased-estimator.history.v1";
const JOB_KEY = "codebased-estimator.active-job.v1";
const state = {catalogue:null, mode:"catalogue", busy:false, availability:null, checkingAvailability:false, imported:null, importedKind:null, current:null, active:null, history:[], routeVersion:0, pollTimer:null, toastTimer:null, started:0};

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 4200);
}

function showError(message = "") {
  $("form-error").textContent = message;
  $("form-error").hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options, headers:{"Content-Type":"application/json", ...options.headers}});
  let data;
  try { data = await response.json(); } catch { throw new Error("The engine returned an invalid response. Check the local server."); }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

function connection(online) {
  const element = $("connection");
  if (!element) return;
  element.classList.toggle("offline", !online);
  (element.lastElementChild || element).textContent = online ? "Engine connected" : "Engine unavailable";
}

function view(name, updateHash = true) {
  if (!["workspace","catalogue","history","guide"].includes(name)) name = "workspace";
  $$(".view").forEach((element) => { element.hidden = element.id !== `view-${name}`; });
  $$(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
    if (button.dataset.view === name) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  optionalText("breadcrumb-current", {workspace:"Estimator",catalogue:"Parameter library",history:"Run history",guide:"Model guide"}[name]);
  if (updateHash) history.replaceState(null, "", `#${name}`);
  if (name === "history") renderHistory();
  window.scrollTo(0, 0);
}

function chips(parameters) {
  return Object.entries(parameters || {}).map(([key, value]) => `<span class="parameter-chip">${escapeHTML(key)} <b>${escapeHTML(Array.isArray(value) ? `[${value.join(", ")}]` : value)}</b></span>`).join("");
}

function selectedAlgorithms(family) {
  return $$(`input[name="${family}-algorithm"]:checked`).filter((input) => !input.disabled).map((input) => input.value);
}

function selectAlgorithms(family) {
  const names = $$(`input[name="${family}-algorithm"]`).filter((input) => !input.disabled).map((input) => input.value);
  renderAlgorithms(family === "classical" ? names : undefined, family === "quantum" ? names : undefined);
}

function algorithmFamily() {
  if (state.mode !== "custom") {
    const row = state.catalogue?.parameter_sets.find((entry) => entry.parameter_set === $("parameter-set").value);
    return (row?.parameters.q ?? 2) === 2 ? "binary" : "qary";
  }
  if ($("problem-kind").value === "rank_sd") return "rank";
  return Number($("param-q").value) === 2 ? "binary" : "qary";
}

function renderAlgorithms(classicalSelection, quantumSelection) {
  if (!state.catalogue) return;
  // Keep checked intentions while a new preflight is pending; confirmed
  // unavailable candidates are then unchecked and cannot enter a request.
  const checked = (family) => $$(`input[name="${family}-algorithm"]:checked`).map((input) => input.value);
  const selectedClassical = classicalSelection ?? checked("classical");
  const selectedQuantum = quantumSelection ?? checked("quantum");
  const names = state.catalogue.algorithm_families?.[algorithmFamily()] || state.catalogue.algorithms.classical;
  const common = ["Prange","Stern","Dumer","BJMM","MayOzerov","BothMay","BallCollision","MAGE-Stern","LeeBrickell","GRS","MaxMinors","SupportMinors"].filter((name) => names.includes(name));
  const other = names.filter((name) => !common.includes(name));
  const pill = (name, family, selected) => {
    const info = state.availability?.[family]?.[name];
    const available = name !== "QPrange" && Boolean(info?.available) && !state.checkingAvailability;
    const reason = name === "QPrange" ? "Not implemented." : state.checkingAvailability ? "Checking availability…" : info?.reason || "Availability has not been checked.";
    const isChecked = name !== "QPrange" && selected.includes(name) && (available || state.checkingAvailability);
    return `<label class="algorithm-pill${available ? "" : " unavailable"}" title="${escapeHTML(reason)}"${available ? "" : ` tabindex="0" data-reason="${escapeHTML(reason)}"`}><input type="checkbox" name="${family}-algorithm" value="${escapeHTML(name)}" ${isChecked ? "checked" : ""} ${available ? "" : "disabled"} aria-label="${escapeHTML(name + (available ? "" : `: ${reason}`))}"><span>${escapeHTML(name)}</span></label>`;
  };
  $("classical-algorithms").innerHTML = [...common,...other].map((name) => pill(name, "classical", selectedClassical)).join("");
  $("quantum-algorithms").innerHTML = state.catalogue.algorithms.quantum.map((name) => pill(name,"quantum",selectedQuantum)).join("");
  for (const family of ["classical","quantum"]) {
    $(`select-${family}`).disabled = !$$(`input[name="${family}-algorithm"]`).some((input) => !input.disabled);
    $(`clear-${family}`).disabled = state.checkingAvailability;
  }
  countAlgorithms();
}

function countAlgorithms() {
  optionalText("algorithm-count", `${selectedAlgorithms("classical").length + selectedAlgorithms("quantum").length} selected`);
  $("run-button").disabled = state.busy || !state.catalogue || state.checkingAvailability || !state.availability || ![...selectedAlgorithms("classical"),...selectedAlgorithms("quantum")].length;
}

function syncInputs() {
  $("catalogue-fields").hidden = state.mode !== "catalogue";
  $("custom-fields").hidden = state.mode !== "custom";
  $("doom-field").hidden = state.mode !== "catalogue";
  const kind = $("problem-kind").value;
  const rank = kind === "rank_sd";
  $("weight-field").hidden = rank;
  $$(".rank-field").forEach((field) => { field.hidden = !rank; });
  $("target-field").hidden = !["qcsd","qccf"].includes(kind);
  $("solutions-field").hidden = rank || kind === "qccf";
  $("target-hint").textContent = kind === "qccf" ? "Count of acceptable nonzero codewords; not syndrome targets." : "Usable syndrome targets under the same matrix.";
  $("goal").querySelector('[value="both"]').disabled = state.mode === "custom";
  if (state.mode === "custom" && $("goal").value === "both") $("goal").value = "key_recovery";
  $$("#catalogue-fields input, #catalogue-fields select").forEach((input) => { input.disabled = state.mode !== "catalogue"; });
  $("parameter-set").disabled = state.mode !== "catalogue" || $("evaluation-scope").value === "scheme";
  $$("#custom-fields input, #custom-fields select, #custom-fields textarea").forEach((input) => {
    const localField = input.closest(".rank-field, #weight-field, #target-field, #solutions-field");
    input.disabled = state.mode !== "custom" || Boolean(localField?.hidden);
  });
  if ($("load-example")) $("load-example").disabled = state.busy;
  $("reset-form").disabled = state.busy;
}

function setMode(mode) {
  state.mode = mode;
  $$("[data-mode]").forEach((button) => {
    const selected = button.dataset.mode === mode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  syncInputs();
  updateRoutes();
}

function populateSets(preferred) {
  const rows = state.catalogue.parameter_sets.filter((row) => row.scheme === $("scheme").value);
  $("parameter-set").innerHTML = rows.map((row) => `<option value="${escapeHTML(row.parameter_set)}">${escapeHTML(row.parameter_set)}</option>`).join("");
  if (rows.some((row) => row.parameter_set === preferred)) $("parameter-set").value = preferred;
  sourcePreview();
}

function sourcePreview() {
  const batch = $("evaluation-scope").value === "scheme";
  const rows = state.catalogue.parameter_sets.filter((entry) => entry.scheme === $("scheme").value && (batch || entry.parameter_set === $("parameter-set").value));
  $("source-parameters").innerHTML = rows.map((row) => `<div>${batch ? `<strong>${escapeHTML(row.parameter_set)}</strong><div class="parameter-chips">` : ""}${chips(row.parameters)}${batch ? "</div>" : ""}</div>`).join("");
  optionalText("source-count", batch ? `${rows.length} parameter sets` : rows[0] ? `${Object.keys(rows[0].parameters).length} fields` : "");
  let notes = $("source-notes");
  if (!notes) {
    notes = document.createElement("details"); notes.id = "source-notes"; notes.className = "source-notes";
    $("source-parameters").after(notes);
  }
  notes.innerHTML = rows.length ? `<summary>Source &amp; parameter notes</summary>${[...new Set(rows.flatMap((row) => [...row.references, ...(row.notes || [])]))].map((note) => `<p>${escapeHTML(note)}</p>`).join("")}` : "";
  syncInputs();
  updateRoutes();
}

function readInteger(id, label, minimum = 1) {
  const value = Number($(id).value);
  if (!$(id).value.trim() || !Number.isSafeInteger(value) || value < minimum) throw new Error(`${label} must be an integer of at least ${minimum}.`);
  return value;
}

function customInstance() {
  const kind = $("problem-kind").value;
  const n = readInteger("param-n", "Code length n", 2);
  const k = readInteger("param-k", "Dimension k");
  const q = readInteger("param-q", "Field order q", 2);
  if (k >= n) throw new Error("Dimension k must be smaller than code length n.");
  const parameters = {n,k,q};
  if (kind === "rank_sd") {
    parameters.m = readInteger("param-m", "Extension degree m", 2);
    parameters.r = readInteger("param-r", "Rank weight r");
    if (parameters.r >= parameters.m || parameters.r > n) throw new Error("Rank weight must satisfy r < m and r ≤ n.");
  } else {
    parameters.w = readInteger("param-w", "Weight w");
    if (parameters.w > n-k) throw new Error("Weight w must be no greater than n − k.");
  }
  const preserveModel = state.imported && state.importedKind === kind;
  const problem = {kind:preserveModel ? state.imported.problem.kind : kind === "qcsd" ? "sd" : kind === "qccf" ? "cfp" : kind, parameters};
  if (! ["rank_sd","qccf"].includes(kind) && $("solutions").value.trim()) {
    problem.log2_solutions = Number($("solutions").value);
    if (!Number.isFinite(problem.log2_solutions) || problem.log2_solutions < 0) throw new Error("Solutions per syndrome must be a nonnegative log₂ value.");
  }
  const name = $("custom-name").value.trim();
  if (!name) throw new Error("Enter an instance name.");
  const extra = state.imported ? structuredClone(state.imported) : {};
  const tags = preserveModel ? [...(extra.tags || [])] : (extra.tags || []).filter((tag) => !tag.startsWith("doom"));
  if (!preserveModel && ["qcsd","qccf"].includes(kind)) tags.push(`doom:${kind}`);
  return {...extra, name, goal:$("goal").value, problem, targets:["qcsd","qccf"].includes(kind) ? readInteger("targets", "Usable targets M") : 1, tags};
}

function updateJSONEditor() {
  try { $("instance-json").value = JSON.stringify(customInstance(), null, 2); } catch { /* Keep the last valid JSON while a field is edited. */ }
}

function loadInstance(input) {
  const instance = input.instance || input.reports?.[0]?.instance || input;
  if (!instance || typeof instance !== "object" || Array.isArray(instance) || !instance.problem || !instance.problem.parameters) throw new Error("Expected an attack instance with a problem and parameters object.");
  const p = instance.problem.parameters;
  const tags = instance.tags || [];
  if (!Array.isArray(tags) || tags.some((tag) => typeof tag !== "string")) throw new Error("Instance tags must be a list of strings.");
  if (!["sd","qcsd","qccf","cfp","rank_sd"].includes(instance.problem.kind)) throw new Error("The custom editor supports SD, QCSD, QCCF, and Rank SD instances.");
  if (!["key_recovery","msg_recovery"].includes(instance.goal)) throw new Error("The instance must specify key_recovery or msg_recovery as its goal.");
  if (tags.includes("doom:qccf") && !["cfp","qccf"].includes(instance.problem.kind)) throw new Error("doom:qccf requires a cfp or qccf problem. The imported model has not been changed.");
  if (tags.includes("doom:qcsd") && !["sd","qcsd"].includes(instance.problem.kind)) throw new Error("doom:qcsd requires an sd or qcsd problem. The imported model has not been changed.");
  const kind = tags.includes("doom:qccf") || ["cfp","qccf"].includes(instance.problem.kind) ? "qccf" : tags.includes("doom:qcsd") || instance.problem.kind === "qcsd" ? "qcsd" : instance.problem.kind;
  if (kind === "qccf" && instance.problem.log2_solutions != null) throw new Error("QCCF uses targets for codeword candidates. Remove log2_solutions to avoid double counting.");
  if (!instance.name || typeof instance.name !== "string" || !instance.name.trim()) throw new Error("The instance must have a nonempty name.");
  const fields = kind === "rank_sd" ? ["n","k","q","m","r"] : ["n","k","w"];
  if (fields.some((key) => !Number.isSafeInteger(p[key]) || p[key] < 1)) throw new Error("All required decoding parameters must be positive integers.");
  if (Object.hasOwn(p,"q") && (!Number.isSafeInteger(p.q) || p.q < 2)) throw new Error("Field order q must be an integer of at least 2.");
  if (Object.keys(p).some((key) => ![...fields,"q"].includes(key))) throw new Error("The problem contains unexpected decoding parameters. They have not been removed; review the JSON.");
  if (Object.keys(instance.problem).some((key) => !["kind","parameters","log2_solutions"].includes(key))) throw new Error("The problem contains unknown fields. Review the JSON before applying it.");
  if (p.k >= p.n || (kind !== "rank_sd" && p.w > p.n-p.k)) throw new Error("Require 0 < k < n and 1 ≤ w ≤ n − k.");
  if (kind === "rank_sd" && (p.r >= p.m || p.r > p.n)) throw new Error("Rank weight must satisfy r < m and r ≤ n.");
  if (kind === "rank_sd" && instance.problem.log2_solutions != null) throw new Error("Rank SD does not implement log2_solutions. Remove this field before applying the instance.");
  if (instance.problem.log2_solutions != null && (typeof instance.problem.log2_solutions !== "number" || !Number.isFinite(instance.problem.log2_solutions) || instance.problem.log2_solutions < 0)) throw new Error("log2_solutions must be a finite nonnegative number.");
  if (Object.hasOwn(instance,"targets") && (!Number.isSafeInteger(instance.targets) || instance.targets < 1)) throw new Error("Targets must be a positive integer.");
  if (tags.filter((tag) => tag.startsWith("doom")).length > 1 || tags.some((tag) => tag.startsWith("doom") && !["doom:qcsd","doom:qccf"].includes(tag))) throw new Error("Specify at most one supported DOOM tag.");
  if (instance.problem.kind === "rank_sd" && tags.some((tag) => tag.startsWith("doom"))) throw new Error("Rank SD does not use DOOM tags.");
  if (kind === "sd" && (instance.targets || 1) !== 1) throw new Error("Select a QCSD instance with doom:qcsd to use multiple syndrome targets.");
  if (kind === "rank_sd" && (instance.targets || 1) !== 1) throw new Error("The Rank SD form supports one target. Multi-target Rank SD is not implemented by the estimation engine.");
  state.imported = structuredClone(instance);
  state.importedKind = kind;
  $("custom-name").value = instance.name;
  $("problem-kind").value = kind;
  for (const key of ["n","k","w","q","m","r"]) if (p[key] != null) $(`param-${key}`).value = p[key];
  if (p.q == null) $("param-q").value = 2;
  $("targets").value = instance.targets || 1;
  $("solutions").value = instance.problem.log2_solutions ?? "";
  $("goal").value = instance.goal;
  $("import-note").hidden = false;
  setMode("custom");
  updateJSONEditor();
  showError();
}

function routeCard(instance) {
  const p = instance.problem.parameters;
  const provenance = [...(instance.assumptions || []), ...(instance.references || [])];
  return `<article class="route-card">${instance.parameter_set ? `<p class="muted">${escapeHTML(instance.parameter_set)}</p>` : ""}<div class="route-card-header"><h3>${escapeHTML(human(instance.goal))}<span>${escapeHTML(instance.route_id || "default")}</span></h3><span class="badge neutral">${escapeHTML(instance.problem.kind.toUpperCase())}</span></div><div class="parameter-chips">${chips(p)}<span class="parameter-chip">M <b>${escapeHTML(instance.targets ?? 1)}</b></span></div><p class="route-description">${escapeHTML(instance.route || "Generic decoding")}</p><details class="route-details"><summary>Input, assumptions &amp; sources</summary>${instance.block_profile ? `<p>Block profile: ${escapeHTML(JSON.stringify(instance.block_profile))}</p>` : ""}${instance.problem.log2_solutions != null ? `<p>Solutions per syndrome: 2^${escapeHTML(instance.problem.log2_solutions)}</p>` : ""}<p>Tags: ${escapeHTML((instance.tags || []).join(", ") || "none")}</p>${provenance.map((item) => `<p>${escapeHTML(item)}</p>`).join("")}${instance.cost_proxy ? `<p>Cost proxy: ${escapeHTML(JSON.stringify(instance.cost_proxy))}</p>` : ""}</details></article>`;
}

async function updateRoutes() {
  if (!state.catalogue) return;
  const version = ++state.routeVersion;
  state.checkingAvailability = true;
  state.availability = null;
  renderAlgorithms();
  optionalText("availability-note", "Checking algorithm availability…");
  try {
    let data;
    if (state.mode === "custom") {
      const instance = customInstance();
      data = await api("/api/availability", {method:"POST",body:JSON.stringify({mode:"custom",instance,unbalanced:$("unbalanced").value,options:{classical_algorithms:[],quantum_algorithms:[]}})});
    } else {
      const params = new URLSearchParams({scheme:$("scheme").value,parameter_set:$("parameter-set").value,scope:$("evaluation-scope").value || "parameter_set",goal:$("goal").value,doom:$("doom").value,unbalanced:$("unbalanced").value});
      data = await api(`/api/routes?${params}`);
    }
    if (version !== state.routeVersion) return;
    const {instances,availability} = data;
    state.availability = availability;
    state.checkingAvailability = false;
    renderAlgorithms();
    const selectable = Object.values(availability || {}).some((family) => Object.values(family).some((item) => item.available));
    optionalText("availability-note", selectable ? "Unavailable algorithms are disabled. Hover or focus a disabled option for its reason." : "No algorithms support these recovery routes. Choose another recovery goal or input.");
    optionalText("route-count", `${instances.length} mapped ${instances.length === 1 ? "route" : "routes"}`);
    $("route-preview-content").innerHTML = instances.map(routeCard).join("");
  } catch (error) {
    if (version !== state.routeVersion) return;
    state.checkingAvailability = false;
    state.availability = null;
    renderAlgorithms();
    optionalText("availability-note", `Availability could not be checked: ${error.message}`);
    optionalText("route-count", "Check inputs");
    $("route-preview-content").innerHTML = `<p class="muted">${escapeHTML(error.message)}</p>`;
  }
}

function requestBody() {
  const memory = $("memory-bound").value.trim();
  const options = {classical_algorithms:selectedAlgorithms("classical"),quantum_algorithms:selectedAlgorithms("quantum"),memory_bound_log2_bits:memory ? Number(memory) : null,quantum_matrix_profile:$("matrix-profile").value};
  if (!options.classical_algorithms.length && !options.quantum_algorithms.length) throw new Error("Select at least one classical or quantum algorithm.");
  if (memory && (!Number.isFinite(options.memory_bound_log2_bits) || options.memory_bound_log2_bits < 0)) throw new Error("The memory limit must be a nonnegative log₂ value.");
  const body = {mode:state.mode,unbalanced:$("unbalanced").value,options};
  if (state.mode === "custom") body.instance = customInstance();
  else Object.assign(body, {scheme:$("scheme").value,parameter_set:$("parameter-set").value,scope:$("evaluation-scope").value || "parameter_set",goal:$("goal").value,doom:$("doom").value});
  return body;
}

function setBusy(busy) {
  state.busy = busy;
  $("configuration-fields").disabled = busy;
  countAlgorithms();
  ($("run-button").firstElementChild || $("run-button")).textContent = busy ? "Running…" : "Run estimation";
  $("cancel-button").hidden = !busy;
  $("cancel-button").disabled = false;
  syncInputs();
}

function setStatus(text, style = "neutral") {
  $("result-status").textContent = text;
  $("result-status").className = `badge ${style}`;
}

async function run(event) {
  event.preventDefault();
  if (state.busy || !state.catalogue || state.checkingAvailability || !state.availability) return;
  showError();
  let request;
  try { request = requestBody(); } catch (error) { showError(error.message); return; }
  setBusy(true);
  state.current = null;
  $("completed-results").hidden = true;
  $("result-toolbar").hidden = true;
  $("empty-results").hidden = true;
  $("job-progress").hidden = false;
  $("progress-bar").removeAttribute("value");
  $("progress-title").textContent = "Starting estimation…";
  $("progress-detail").textContent = "Large instances may take several minutes.";
  $("elapsed").textContent = "0s";
  setStatus("Running", "running");
  state.started = Date.now();
  try {
    const job = await api("/api/jobs", {method:"POST",body:JSON.stringify(request)});
    state.active = {id:job.id,request,started:state.started};
    try { sessionStorage.setItem(JOB_KEY, JSON.stringify(state.active)); } catch { /* Storage is optional. */ }
    connection(true);
    pollJob();
  } catch (error) { finishFailed(error.message); }
}

function clearActive() {
  clearTimeout(state.pollTimer);
  state.active = null;
  try { sessionStorage.removeItem(JOB_KEY); } catch { /* Storage is optional. */ }
  setBusy(false);
  $("job-progress").hidden = true;
}

function finishFailed(message, cancelled = false) {
  clearActive();
  setStatus(cancelled ? "Cancelled" : "Run failed", cancelled ? "neutral" : "failed");
  $("empty-results").hidden = false;
  if (!cancelled) showError(message); else toast("Estimation cancelled.");
}

async function pollJob() {
  const active = state.active;
  if (!active) return;
  try {
    const job = await api(`/api/jobs/${encodeURIComponent(active.id)}`);
    if (state.active !== active) return;
    connection(true);
    const seconds = Math.floor((Date.now() - active.started) / 1000);
    $("elapsed").textContent = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds/60)}m ${seconds%60}s`;
    const progress = job.progress || {completed:0,total:1};
    $("progress-title").textContent = job.status === "queued" ? "Waiting for the engine…" : "Estimating costs…";
    $("progress-detail").textContent = `${progress.completed} of ${progress.total} routes complete.`;
    if (progress.completed > 0) { $("progress-bar").max = progress.total; $("progress-bar").value = progress.completed; }
    if (job.status === "completed") {
      const record = {id:job.id,request:active.request,created_at:new Date().toISOString(),duration_ms:Date.now()-active.started,reports:job.reports,comparisons:job.comparisons};
      clearActive();
      state.current = record;
      saveRun(record);
      renderResults(record);
      toast("Estimation complete.");
    } else if (job.status === "failed") finishFailed(job.error || "The estimation failed. Review the input and try again.");
    else if (job.status === "cancelled") finishFailed("", true);
    else state.pollTimer = setTimeout(pollJob, 700);
  } catch (error) {
    if (state.active !== active) return;
    connection(false);
    if (/not found|unknown job/i.test(error.message)) { finishFailed("This job is no longer available. The local server may have restarted; run the estimation again."); return; }
    $("progress-title").textContent = "Reconnecting to the engine…";
    $("progress-detail").textContent = `${error.message} Retrying automatically. Keep the local Python server running.`;
    state.pollTimer = setTimeout(pollJob, 2500);
  }
}

async function cancelJob() {
  if (!state.active) return;
  $("cancel-button").disabled = true;
  try {
    const active = state.active;
    const job = await api(`/api/jobs/${encodeURIComponent(active.id)}`, {method:"DELETE"});
    if (state.active !== active) return;
    if (job.status === "completed") { clearTimeout(state.pollTimer); pollJob(); }
    else finishFailed("", true);
  } catch (error) { showError(`Could not cancel: ${error.message}`); $("cancel-button").disabled = false; }
}

function saveRun(record) {
  state.history = [record, ...state.history.filter((run) => run.id !== record.id)].slice(0,10);
  try { localStorage.setItem(HISTORY_KEY,JSON.stringify(state.history)); }
  catch {
    try { localStorage.setItem(HISTORY_KEY,JSON.stringify(state.history.slice(0,1))); }
    catch { toast("Browser storage is full or unavailable. Export this report to keep it."); }
  }
}

function reportRows(record) {
  return record.reports.flatMap((report) => report.results.map((result) => ({report,result})));
}

function isWinner(report, result) {
  return (report.conclusions?.[result.model]?.best || []).some((best) => best.algorithm === result.algorithm && best.time_log2 === result.time_log2 && best.memory_log2 === result.memory_log2 && best.time_unit === result.time_unit);
}

function comparisons(record) {
  if (record.comparisons?.length) return record.comparisons;
  return record.reports.map((report) => ({parameter_set:report.instance.parameter_set,goal:report.instance.goal,conclusions:Object.fromEntries(Object.entries(report.conclusions).map(([family,c]) => [family,{...c,best:c.best.map((estimate) => ({name:report.instance.name,route_id:report.instance.route_id,estimate}))}]))}));
}

function requestTitle(request, reports = []) {
  return request.scope === "scheme" ? `${request.scheme} · all parameter sets` : request.parameter_set || request.instance?.name || reports[0]?.instance.name || "Estimation";
}

function batchMinimum(conclusion) {
  const best = conclusion.best || [];
  if (!best.length) return `<span title="${escapeHTML(conclusion.reason)}">${escapeHTML(human(conclusion.status))}</span>`;
  return `${number(best[0].estimate.time_log2)}<small>log₂(${escapeHTML(unit(best[0].estimate.time_unit))})</small><small>${best.map((winner) => `${escapeHTML(winner.estimate.algorithm)} · ${escapeHTML(winner.route_id || "default")}`).join("<br>")}</small>`;
}

function renderResults(record) {
  state.current = record;
  $("empty-results").hidden = true;
  $("completed-results").hidden = false;
  $("result-toolbar").hidden = false;
  $("job-progress").hidden = true;
  setStatus("Completed", "success");
  const name = requestTitle(record.request, record.reports);
  const batch = record.request.scope === "scheme";
  $("run-title").textContent = name;
  $("run-meta").textContent = `${human(record.request.goal || record.request.instance?.goal)} · ${record.reports.length} ${record.reports.length === 1 ? "route" : "routes"} · ${new Date(record.created_at).toLocaleString("en-US", {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})}`;
  $("result-summary").classList.toggle("batch-summary", batch);
  $("result-summary").innerHTML = batch ? `<div class="table-scroll" tabindex="0" role="region" aria-label="Minimum costs by parameter set"><table><thead><tr><th>Parameter set / goal</th><th>Classical minimum</th><th>Quantum minimum</th></tr></thead><tbody>${comparisons(record).map((comparison) => `<tr><td>${escapeHTML(comparison.parameter_set)}<small>${escapeHTML(human(comparison.goal))}</small></td><td>${batchMinimum(comparison.conclusions.classical)}</td><td>${batchMinimum(comparison.conclusions.quantum)}</td></tr>`).join("")}</tbody></table></div>` : comparisons(record).flatMap((comparison) => ["classical","quantum"].map((family) => {
    const conclusion = comparison.conclusions[family];
    const best = conclusion.best || [];
    const result = best[0]?.estimate;
    return `<div class="summary-card ${family === "quantum" ? "quantum-summary" : ""}" title="${escapeHTML(conclusion.reason)}"><div class="summary-label"><i class="legend-dot ${family}"></i> ${family === "quantum" ? "Quantum" : "Classical"} minimum</div>${comparisons(record).length > 1 ? `<div class="summary-goal">${escapeHTML(human(comparison.goal))}</div>` : ""}<div class="summary-value ${result ? "" : "is-text"}">${result ? number(result.time_log2) : escapeHTML(human(conclusion.status))}</div><div class="summary-unit">${result ? `log₂(${escapeHTML(unit(result.time_unit))})` : "Among selected candidates"}</div><div class="summary-best">${best.length ? best.map((winner) => `${escapeHTML(winner.estimate.algorithm)} · ${escapeHTML(winner.route_id || "default")}`).join("<br>") : family === "quantum" && conclusion.status === "not_requested" ? "No quantum algorithms selected" : "See individual algorithm statuses"}</div></div>`;
  })).join("");
  const rows = reportRows(record);
  const groups = new Map();
  for (const row of rows) {
    if (row.result.status !== "computed" || !Number.isFinite(row.result.time_log2)) continue;
    const key = `${row.result.model}|${row.result.time_unit}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  $("cost-charts").innerHTML = groups.size ? [...groups.values()].map((group) => {
    const first = group[0].result;
    const minimum = Math.min(0, ...group.map(({result}) => result.time_log2));
    const maximum = Math.max(10, Math.ceil(Math.max(...group.map(({result}) => result.time_log2))/10)*10);
    const width = (value) => Math.max(1, 100*(value-minimum)/(maximum-minimum));
    return `<div class="chart-group ${first.model === "quantum" ? "quantum-chart" : ""}"><div class="chart-group-label"><span>${first.model === "quantum" ? "Quantum" : "Classical"}</span><span>${escapeHTML(unit(first.time_unit))}</span></div>${group.map(({report,result}) => `<div class="chart-row"><div class="chart-label">${escapeHTML(result.algorithm)}${record.reports.length > 1 ? `<small>${batch ? `${escapeHTML(report.instance.parameter_set)} · ` : ""}${escapeHTML(report.instance.route_id || "default")} · ${report.instance.goal === "key_recovery" ? "key" : "message"}</small>` : ""}</div><div class="chart-track"><div class="chart-bar" style="width:${width(result.time_log2)}%" title="${escapeHTML(`${result.algorithm}: ${number(result.time_log2)} log₂ ${unit(result.time_unit)}`)}"></div></div><div class="chart-number">${number(result.time_log2)}</div></div>`).join("")}<div class="chart-axis"><span>${number(minimum,0)}</span><span>${number((maximum+minimum)/2,0)}</span><span>${number(maximum,0)}</span></div></div>`;
  }).join("") : '<p class="chart-empty">No computed costs. See statuses below.</p>';
  $("results-body").innerHTML = rows.map(({report,result}) => `<tr><td><span class="row-family ${result.model === "quantum" ? "quantum-tag" : ""}">${result.model === "quantum" ? "Q" : "C"}</span>${escapeHTML(result.algorithm)}${isWinner(report,result) ? '<span class="best-marker">route min</span>' : ""}<small>${batch ? `${escapeHTML(report.instance.parameter_set)} · ` : ""}${escapeHTML(report.instance.route_id || "default")} · ${escapeHTML(human(report.instance.goal))}</small>${result.reason ? `<details class="row-reason"><summary>Details</summary><p>${escapeHTML(result.reason)}</p></details>` : ""}</td><td><span class="row-status ${result.status !== "computed" ? "unavailable" : ""}">${escapeHTML(human(result.status))}</span></td><td>${number(result.time_log2)}<small>${escapeHTML(unit(result.time_unit))}</small></td><td>${result.memory_unit === "not_estimated" ? "Not estimated" : number(result.memory_log2)}${result.memory_unit !== "not_estimated" ? `<small>${escapeHTML(unit(result.memory_unit))}</small>` : ""}</td></tr>`).join("");
  $("tab-details").innerHTML = record.reports.map((report) => `<article class="detail-report"><h3>${escapeHTML(report.instance.name)}</h3><p>${escapeHTML(report.instance.route)}</p><div class="parameter-chips">${chips(report.instance.problem.parameters)}</div><details><summary>Assumptions &amp; references</summary><ul>${[...new Set([...(report.instance.assumptions || []),...(report.instance.references || []),...report.results.flatMap((result) => [...(result.assumptions || []),...(result.references || [])])])].map((line) => `<li>${escapeHTML(line)}</li>`).join("")}</ul></details><details><summary>Algorithm parameters &amp; model metadata</summary><pre>${escapeHTML(JSON.stringify(report.results,null,2))}</pre></details><details><summary>Full report JSON</summary><pre>${escapeHTML(JSON.stringify(report,null,2))}</pre></details></article>`).join("");
}

function renderLibrary() {
  if (!state.catalogue) return;
  const query = $("library-search").value.toLowerCase().trim();
  const rows = state.catalogue.parameter_sets.filter((row) => `${row.scheme} ${row.parameter_set}`.toLowerCase().includes(query));
  optionalText("library-count", `${rows.length} parameter sets`);
  $("library-body").innerHTML = rows.length ? rows.map((row) => `<tr><td>${escapeHTML(row.parameter_set)}<details><summary>Source &amp; notes</summary>${[...row.references,...(row.notes || [])].map((note) => `<p>${escapeHTML(note)}</p>`).join("")}</details></td><td>${escapeHTML(row.scheme)}</td><td><div class="parameter-chips">${chips(row.parameters)}</div></td><td><button class="button secondary small" data-load-set="${escapeHTML(row.parameter_set)}">Use set</button></td></tr>`).join("") : '<tr><td colspan="4">No matching parameter sets.</td></tr>';
}

function renderHistory() {
  $("clear-history").disabled = !state.history.length;
  $("history-list").innerHTML = state.history.length ? state.history.map((record,index) => `<article class="panel history-card"><div><h2>${escapeHTML(requestTitle(record.request, record.reports))}</h2><p>${escapeHTML(human(record.request.goal || record.request.instance?.goal))} · ${record.reports.length} ${record.reports.length === 1 ? "route" : "routes"} · ${escapeHTML(new Date(record.created_at).toLocaleString("en-US"))}</p></div><button class="button secondary small" data-history-index="${index}">View report</button></article>`).join("") : '<div class="panel history-empty"><p>No saved runs.</p><button class="button secondary" data-view="workspace">Open estimator</button></div>';
}

function download(content, extension, mime) {
  if (!state.current) return;
  const name = requestTitle(state.current.request, state.current.reports).replace(/[^a-zA-Z0-9_-]/g,"-");
  const url = URL.createObjectURL(new Blob([content], {type:mime}));
  const link = document.createElement("a"); link.href = url; link.download = `${name}-report.${extension}`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(`${extension.toUpperCase()} report exported.`);
}

function exportCSV() {
  if (!state.current) return;
  const fields = ["scheme","parameter_set","instance_name","goal","route_id","problem_kind","n","k","w","q","m","r","targets","log2_solutions","model","algorithm","status","time_log2","time_unit","memory_log2","memory_unit","is_route_minimum","effective_targets","reason"];
  const csvCell = (value) => {
    let text = value == null ? "" : String(value);
    if (/^[\s]*[=+@-]/.test(text) && typeof value !== "number") text = `'${text}`;
    return `"${text.replaceAll('"','""')}"`;
  };
  const lines = reportRows(state.current).map(({report,result}) => {
    const i = report.instance;
    const row = {...i.problem.parameters,...result,scheme:i.scheme,parameter_set:i.parameter_set,instance_name:i.name,goal:i.goal,route_id:i.route_id,problem_kind:i.problem.kind,targets:i.targets,log2_solutions:i.problem.log2_solutions,is_route_minimum:isWinner(report,result),effective_targets:result.metadata?.effective_targets ?? result.metadata?.doom?.active_targets ?? result.metadata?.doom?.active_codewords ?? i.targets};
    return fields.map((field) => csvCell(row[field])).join(",");
  });
  download("\uFEFF" + [fields.join(","),...lines].join("\r\n"), "csv", "text/csv;charset=utf-8");
}

function defaults() {
  if (!state.catalogue || state.busy) return;
  const config = state.catalogue.defaults;
  state.imported = null;
  state.importedKind = null;
  $("import-note").hidden = true;
  $("scheme").value = config.scheme;
  $("evaluation-scope").value = "parameter_set";
  $("goal").value = config.goal;
  $("doom").value = config.doom;
  $("unbalanced").value = config.unbalanced;
  $("memory-bound").value = "";
  $("matrix-profile").value = config.options.quantum_matrix_profile;
  $("custom-name").value = "custom-sd";
  $("problem-kind").value = "sd";
  for (const [key,value] of Object.entries({n:40,k:20,w:4,q:2,m:12,r:3})) $(`param-${key}`).value = value;
  $("targets").value = 8;
  $("solutions").value = 0;
  setMode("catalogue");
  populateSets(config.parameter_set);
  renderAlgorithms(config.options.classical_algorithms, config.options.quantum_algorithms);
  showError();
}

function example() {
  if (!state.catalogue || state.busy) return;
  defaults();
  loadInstance({name:"synthetic-sd",goal:"msg_recovery",problem:{kind:"sd",parameters:{n:40,k:20,w:4,q:2},log2_solutions:0}});
  state.imported = null;
  $("import-note").hidden = true;
  renderAlgorithms(["Prange","Stern","Dumer"],["QSS","QMMT+"]);
  view("workspace");
  toast("Example loaded.");
}

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-view]");
  if (nav) view(nav.dataset.view);
  const mode = event.target.closest("[data-mode]");
  if (mode && !state.busy) { setMode(mode.dataset.mode); if (state.mode === "custom") updateJSONEditor(); }
  const tab = event.target.closest("[data-result-tab]");
  if (tab) {
    $$("[data-result-tab]").forEach((button) => { const selected = tab === button; button.classList.toggle("selected",selected); button.setAttribute("aria-selected",String(selected)); button.tabIndex = selected ? 0 : -1; $(`tab-${button.dataset.resultTab}`).hidden = !selected; });
  }
  const load = event.target.closest("[data-load-set]");
  if (load) {
    if (state.busy) { toast("Cancel or finish the active estimation before changing its inputs."); return; }
    const row = state.catalogue.parameter_sets.find((entry) => entry.parameter_set === load.dataset.loadSet);
    $("evaluation-scope").value = "parameter_set";
    $("scheme").value = row.scheme; setMode("catalogue"); populateSets(row.parameter_set); view("workspace");
    toast(`${row.parameter_set} loaded.`);
  }
  const past = event.target.closest("[data-history-index]");
  if (past) {
    if (state.busy) { toast("Finish or cancel the active estimation before opening a saved report."); return; }
    const record = state.history[Number(past.dataset.historyIndex)];
    renderResults(record); view("workspace");
    $("results-heading").scrollIntoView({behavior:"smooth",block:"start"});
  }
});

document.addEventListener("keydown", (event) => {
  const tab = event.target.closest("[data-result-tab]");
  if (!tab || !["ArrowLeft","ArrowRight","Home","End"].includes(event.key)) return;
  event.preventDefault();
  const tabs = $$("[data-result-tab]");
  const index = tabs.indexOf(tab);
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length-1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].click();
  tabs[next].focus();
});

$("estimate-form").addEventListener("submit",run);
$("cancel-button").addEventListener("click",cancelJob);
$("reset-form").addEventListener("click",defaults);
$("load-example")?.addEventListener("click",example);
$("scheme").addEventListener("change",() => populateSets());
$("parameter-set").addEventListener("change",sourcePreview);
$("evaluation-scope").addEventListener("change",sourcePreview);
$("library-search").addEventListener("input",renderLibrary);
$("select-classical").addEventListener("click",() => selectAlgorithms("classical"));
$("select-quantum").addEventListener("click",() => selectAlgorithms("quantum"));
$("clear-classical").addEventListener("click",() => renderAlgorithms([],selectedAlgorithms("quantum")));
$("clear-quantum").addEventListener("click",() => renderAlgorithms(selectedAlgorithms("classical"),[]));
$("configuration-fields").addEventListener("change",(event) => {
  showError();
  if (["problem-kind","param-q"].includes(event.target.id)) { syncInputs(); renderAlgorithms(); }
  if (event.target.name?.endsWith("-algorithm")) countAlgorithms();
  else if (!["scheme","parameter-set","evaluation-scope","instance-json"].includes(event.target.id)) { updateRoutes(); if (state.mode === "custom") updateJSONEditor(); }
});
$("instance-json").parentElement.addEventListener("toggle",(event) => { if (event.target.open) updateJSONEditor(); });
$("import-button").addEventListener("click",() => $("json-file").click());
$("json-file").addEventListener("change",async (event) => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 1024*1024) throw new Error("Choose a JSON file smaller than 1 MB.");
    loadInstance(JSON.parse(await file.text()));
    toast("Instance imported.");
  } catch (error) { showError(`Import failed: ${error.message}`); }
  finally { event.target.value = ""; }
});
$("apply-json").addEventListener("click",() => {
  try { loadInstance(JSON.parse($("instance-json").value)); toast("JSON instance applied."); }
  catch (error) { showError(`Invalid instance: ${error.message}`); }
});
$("export-json").addEventListener("click",() => { if (state.current) download(JSON.stringify(state.current,null,2),"json","application/json"); });
$("export-csv").addEventListener("click",exportCSV);
$("clear-history").addEventListener("click",() => { state.history = []; try { localStorage.removeItem(HISTORY_KEY); } catch { /* Storage is optional. */ } renderHistory(); toast("History cleared."); });
window.addEventListener("hashchange",() => view(location.hash.slice(1),false));

async function initialize() {
  view(location.hash.slice(1) || "workspace",false);
  try {
    const stored = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (Array.isArray(stored)) state.history = stored.filter((record) => record?.request && Array.isArray(record.reports) && record.created_at).slice(0,10);
  } catch { /* A browser may disable local storage. */ }
  renderHistory();
  try {
    state.catalogue = await api("/api/catalogue");
    $("scheme").innerHTML = state.catalogue.schemes.map((name) => `<option value="${escapeHTML(name)}">${escapeHTML(name)}</option>`).join("");
    $("matrix-profile").innerHTML = state.catalogue.matrix_profiles.map((name) => `<option value="${escapeHTML(name)}">${name.includes("m4ri") ? "Partial M4RI · aggregate v1" : "Partial Gaussian elimination · aggregate v1"}</option>`).join("");
    optionalText("scheme-count", state.catalogue.schemes.length);
    optionalText("parameter-count", state.catalogue.parameter_sets.length);
    optionalText("nav-count", state.catalogue.parameter_sets.length);
    defaults(); renderLibrary(); connection(true); setBusy(false);
    try { state.active = JSON.parse(sessionStorage.getItem(JOB_KEY) || "null"); } catch { state.active = null; }
    if (state.active?.id && state.active.request && Number.isFinite(state.active.started)) {
      setBusy(true); $("empty-results").hidden = true; $("job-progress").hidden = false; setStatus("Running", "running"); pollJob();
    }
  } catch (error) {
    connection(false);
    showError(`${error.message} Start the server with: python -m codebased_estimator.web. Reload this page after the engine is available.`);
    if ($("load-example")) $("load-example").disabled = true;
  }
}
initialize();
