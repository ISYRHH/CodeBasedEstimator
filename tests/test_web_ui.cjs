"use strict";

const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync(join(__dirname, "../codebased_estimator/web_assets/app.js"), "utf8");
assert.match(source, /\binitialize\(\);\s*$/);

// Minimal DOM for state, selection and report regressions. Production handlers
// run unchanged; startup is disabled and network responses are mocked.
function workspace() {
  const elements = [];
  const ids = new Map();
  function element(id = "", tag = "div", parent = null, attributes = {}) {
    let value = "", markup = "";
    const listeners = new Map();
    const node = {
      id, tag, parentElement:parent, children:[], hidden:false, disabled:false,
      dataset:{}, attributes:{...attributes}, classes:new Set(), textContent:"",
      get value() { return value; }, set value(next) { value = String(next); },
      get innerHTML() { return markup; },
      set innerHTML(next) {
        markup = String(next);
        for (const child of this.children) child.detached = true;
        this.children = [];
        for (const match of markup.matchAll(/<(input|option)\b([^>]*)>/g)) {
          const attrs = {};
          for (const pair of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) attrs[pair[1]] = pair[2];
          const child = element("", match[1], this, attrs);
          child.value = attrs.value || "";
          const booleanAttributes = match[2].replace(/"[^"]*"/g, '""');
          child.checked = /(?:^|\s)checked(?:\s|$)/.test(booleanAttributes);
          child.disabled = /(?:^|\s)disabled(?:\s|$)/.test(booleanAttributes);
        }
        if (this.tag === "select") this.value = this.children[0]?.value || "";
      },
      addEventListener(type, callback) { listeners.set(type, callback); },
      dispatch(type, event = {}) { return listeners.get(type)?.(event); },
      setAttribute(name, next) { this.attributes[name] = String(next); },
      removeAttribute(name) { delete this.attributes[name]; },
      closest(selector) {
        for (let current = this; current; current = current.parentElement) {
          if (selector.split(",").some((part) => matches(current, part.trim()))) return current;
        }
        return null;
      },
      querySelector(selector) { return this.children.find((child) => matches(child, selector)) || null; },
      after() {}, scrollIntoView() {},
    };
    node.classList = {toggle(name, force) {
      const enabled = force ?? !node.classes.has(name);
      if (enabled) node.classes.add(name); else node.classes.delete(name);
    }};
    if (parent) parent.children.push(node);
    if (id) ids.set(id, node);
    elements.push(node);
    return node;
  }
  function matches(node, selector) {
    if (selector === "[hidden]") return node.hidden;
    if (selector.startsWith("#")) return node.id === selector.slice(1);
    if (selector.startsWith(".")) return node.classes.has(selector.slice(1));
    const data = selector.match(/^\[data-([\w-]+)\]$/);
    if (data) return data[1].replace(/-([a-z])/g, (_, char) => char.toUpperCase()) in node.dataset;
    const attr = selector.match(/^\[([\w-]+)="([^"]*)"\]$/);
    if (attr) return node.attributes[attr[1]] === attr[2];
    const input = selector.match(/^input\[name="([^"]*)"\](:checked)?(:not\(:disabled\))?$/);
    if (input) return node.tag === "input" && node.attributes.name === input[1]
      && (!input[2] || node.checked) && (!input[3] || !node.disabled);
    return node.tag === selector;
  }
  function query(selector) {
    return elements.filter((node) => !node.detached && selector.split(",").some((part) => {
      const tokens = part.trim().split(/\s+/);
      if (!matches(node, tokens.pop())) return false;
      let parent = node.parentElement;
      while (tokens.length) {
        const token = tokens.pop();
        while (parent && !matches(parent, token)) parent = parent.parentElement;
        if (!parent) return false;
        parent = parent.parentElement;
      }
      return true;
    }));
  }
  const body = element("body", "body");
  const get = (id) => ids.get(id) || element(id, "div", body);
  for (const name of ["workspace", "catalogue", "history", "guide"]) get(`view-${name}`).classes.add("view");
  const configuration = element("configuration-fields", "fieldset", get("view-workspace"));
  const catalogue = element("catalogue-fields", "div", configuration);
  const custom = element("custom-fields", "div", configuration);
  for (const id of ["scheme", "parameter-set", "evaluation-scope"]) element(id, "select", catalogue);
  get("evaluation-scope").value = "parameter_set";
  for (const id of ["custom-name", "param-n", "param-k", "param-q"]) element(id, "input", custom);
  element("problem-kind", "select", custom).value = "sd";
  for (const [id, input] of [["weight-field", "param-w"], ["target-field", "targets"], ["solutions-field", "solutions"], ["rank-m", "param-m"], ["rank-r", "param-r"]]) {
    const wrapper = element(id, "div", custom);
    if (id.startsWith("rank-")) wrapper.classes.add("rank-field");
    element(input, "input", wrapper);
  }
  element("instance-json", "textarea", element("json-details", "details", custom));
  const goal = element("goal", "select", configuration);
  element("both-goals", "option", goal, {value:"both"});
  goal.value = "msg_recovery";
  get("param-q").value = 2;
  get("unbalanced").value = "auto";
  const document = {getElementById:get, querySelectorAll:query,
    addEventListener:body.addEventListener.bind(body), createElement:(tag) => element("", tag)};
  const context = vm.createContext({document, structuredClone, URLSearchParams,
    history:{replaceState() {}}, window:{addEventListener() {}, scrollTo() {}},
    setTimeout:() => 1, clearTimeout() {},
    fetch:async () => ({ok:true,json:async () => ({instances:[]})})});
  vm.runInContext(source.replace(/\binitialize\(\);\s*$/, ""), context);
  const evaluate = (code) => vm.runInContext(code, context);
  const plain = (code) => JSON.parse(evaluate(`JSON.stringify(${code})`));
  const load = (input) => { context.input = structuredClone(input); evaluate("loadInstance(input)"); };
  return {get, element, query, evaluate, plain, load, click:(target) => body.dispatch("click", {target}), context};
}

function instance(kind = "sd", extra = {}) {
  return {name:"import-test", goal:"msg_recovery", problem:{kind, parameters:{n:40,k:20,w:4,q:2}}, ...extra};
}

const catalogue = {
  parameter_sets:[
    {scheme:"Binary",parameter_set:"Binary-1",parameters:{n:40},references:[]},
    {scheme:"Qary",parameter_set:"Qary-1",parameters:{n:40,q:3},references:[]},
  ],
  algorithm_families:{binary:["Prange","Stern","Dumer","BJMM","MAGE-Stern"],qary:["Prange","Stern","LeeBrickell"],rank:["GRS","MaxMinors"]},
  algorithms:{classical:["Prange","Stern","Dumer","BJMM","MAGE-Stern","LeeBrickell","GRS","MaxMinors"],quantum:["QPrange","QSS","QMMT+"]},
};

function catalogueWorkspace() {
  const ui = workspace();
  ui.context.catalogueFixture = catalogue;
  ui.get("scheme").value = "Binary";
  ui.get("parameter-set").value = "Binary-1";
  ui.evaluate("state.catalogue = catalogueFixture");
  return ui;
}

test("library loading keeps the visible source controls enabled despite a hidden workspace", () => {
  const ui = catalogueWorkspace();
  ui.evaluate("view('catalogue'); setMode('custom')");
  assert.equal(ui.get("view-workspace").hidden, true);
  assert.equal(ui.get("scheme").disabled, true);
  assert.equal(ui.get("param-n").disabled, false);
  const load = ui.element();
  load.dataset.loadSet = "Qary-1";
  ui.click(load);
  assert.equal(ui.get("view-workspace").hidden, false);
  assert.equal(ui.get("scheme").value, "Qary");
  assert.equal(ui.get("parameter-set").value, "Qary-1");
  assert.equal(ui.get("scheme").disabled, false);
  assert.equal(ui.get("parameter-set").disabled, false);
  assert.equal(ui.get("param-n").disabled, true);
});

test("HQC library entries load as estimator examples for individual sets and scheme batches", () => {
  const ui = catalogueWorkspace();
  ui.context.hqcCatalogue = {
    ...catalogue,
    parameter_sets:[...catalogue.parameter_sets, ...[1,3,5].map((level) => ({
      scheme:"HQC",parameter_set:`HQC-${level}`,usage:"example",parameters:{r:17669},
      references:["HQC specification 2026-10-12"],notes:["Estimator example."],
    }))],
  };
  ui.evaluate("state.catalogue = hqcCatalogue; renderLibrary()");
  assert.equal((ui.get("library-body").innerHTML.match(/class="badge example-badge"/g) || []).length, 3);
  for (const level of [1,3,5]) {
    const load = ui.element();
    load.dataset.loadSet = `HQC-${level}`;
    ui.click(load);
    assert.equal(ui.get("scheme").value, "HQC");
    assert.equal(ui.get("parameter-set").value, `HQC-${level}`);
    assert.equal(ui.get("source-usage").hidden, false);
    assert.equal(ui.evaluate("algorithmFamily()"), "binary");
  }
  ui.get("evaluation-scope").value = "scheme";
  ui.evaluate("sourcePreview()");
  assert.equal(ui.get("source-usage").hidden, false);
  assert.equal(ui.get("source-count").textContent, "3 parameter sets");
  ui.get("scheme").value = "Binary";
  ui.evaluate("populateSets('Binary-1')");
  assert.equal(ui.get("source-usage").hidden, true);
});

test("custom input visibility disables only irrelevant problem fields", () => {
  const ui = workspace();
  ui.evaluate("view('history'); setMode('custom')");
  assert.equal(ui.get("param-n").disabled, false);
  assert.equal(ui.get("param-w").disabled, false);
  assert.equal(ui.get("param-m").disabled, true);
  assert.equal(ui.get("targets").disabled, true);
  ui.get("problem-kind").value = "rank_sd";
  ui.evaluate("syncInputs()");
  assert.equal(ui.get("param-w").disabled, true);
  assert.equal(ui.get("solutions").disabled, true);
  assert.equal(ui.get("param-m").disabled, false);
  assert.equal(ui.get("param-r").disabled, false);
});

for (const [kind, tags] of [["cfp", []], ["qccf", ["doom:qccf"]], ["qcsd", ["doom:qcsd"]], ["sd", ["doom:qcsd"]]]) {
  test(`import preserves the ${kind} model and ${tags.join(",") || "absent DOOM tag"}`, () => {
    const ui = workspace();
    const input = instance(kind, {tags, targets:8, assumptions:["Keep this reduction."], structure:["shared support"],
      block_profile:{lengths:[20,20],weights:[2,2]}, cost_proxy:{name:"explicit proxy"}});
    ui.load(input);
    const result = ui.plain("customInstance()");
    assert.deepEqual(result, input);
    ui.get("param-w").value = 5;
    assert.equal(ui.plain("customInstance()").problem.kind, kind);
    assert.deepEqual(ui.plain("customInstance()").tags, tags);
  });
}

test("invalid imported models fail atomically instead of being normalized", () => {
  const ui = workspace();
  const original = instance("sd", {tags:[], targets:1});
  ui.load(original);
  const invalid = [
    [instance("sd", {tags:["doom:qccf"]}), /doom:qccf requires/],
    [instance("rank_sd", {problem:{kind:"rank_sd",parameters:{q:2,m:8,n:8,k:4,r:2},log2_solutions:10}}), /Rank SD does not implement/],
    [instance("rank_sd", {problem:{kind:"rank_sd",parameters:{q:2,m:8,n:8,k:4,r:2}},targets:8}), /Rank SD form supports one target/],
    [instance("sd", {problem:{kind:"sd",parameters:{n:40,k:20,w:4,q:null}}}), /Field order q/],
    [instance("sd", {targets:null}), /Targets must be a positive integer/],
    [instance("sd", {problem:{kind:"sd",parameters:{n:40,k:20,w:4,q:2,unknown:1}}}), /unexpected decoding parameters/],
    [instance("sd", {problem:{kind:"sd",parameters:{n:40,k:20,w:4,q:2},unknown:1}}), /unknown fields/],
  ];
  for (const [input, message] of invalid) {
    assert.throws(() => ui.load(input), message);
    assert.deepEqual(ui.plain("customInstance()"), original);
    assert.equal(ui.get("custom-name").value, original.name);
  }
});

test("catalogue and custom field order select only the matching classical algorithm family", () => {
  const ui = catalogueWorkspace();
  ui.get("scheme").value = "Qary";
  ui.evaluate("populateSets('Qary-1')");
  assert.equal(ui.evaluate("algorithmFamily()"), "qary");
  assert.match(ui.get("classical-algorithms").innerHTML, /LeeBrickell/);
  assert.doesNotMatch(ui.get("classical-algorithms").innerHTML, /Dumer|MAGE-Stern/);
  ui.evaluate("setMode('custom')");
  assert.equal(ui.evaluate("algorithmFamily()"), "binary");
  ui.get("param-q").value = 3;
  ui.evaluate("renderAlgorithms()");
  assert.equal(ui.evaluate("algorithmFamily()"), "qary");
  assert.doesNotMatch(ui.get("classical-algorithms").innerHTML, /Dumer|MAGE-Stern/);
  ui.get("problem-kind").value = "rank_sd";
  assert.equal(ui.evaluate("algorithmFamily()"), "rank");
});

test("Rank schemes use their declared algorithm family and keep supported selections across routes", async () => {
  const ui = catalogueWorkspace();
  ui.context.rankCatalogue = {
    ...catalogue,
    parameter_sets:[...catalogue.parameter_sets,
      {scheme:"BAG-Loong",parameter_set:"BAG-Loong-128",algorithm_family:"rank_scheme",parameters:{q:2,m:47,n:42},references:[]},
      {scheme:"BRA",parameter_set:"BRA-128",algorithm_family:"rank_scheme",parameters:{q:2,m:67,k:121},references:[]},
    ],
    algorithm_families:{...catalogue.algorithm_families,rank_scheme:["Rank-OJ","Rank-PRR","Rank-MM","Rank-AGHT"]},
    algorithms:{classical:[...catalogue.algorithms.classical,"Rank-OJ","Rank-PRR","Rank-MM","Rank-AGHT"],quantum:[...catalogue.algorithms.quantum,"Rank-WT23"]},
  };
  ui.evaluate("state.catalogue = rankCatalogue");
  ui.get("scheme").value = "BAG-Loong";
  ui.get("parameter-set").value = "BAG-Loong-128";
  ui.context.fetch = async () => ({ok:true,json:async () => ({instances:[],availability:{
    classical:{"Rank-OJ":{available:true},"Rank-PRR":{available:true},"Rank-MM":{available:true},"Rank-AGHT":{available:false}},
    quantum:{"Rank-WT23":{available:false}},
  }})});
  ui.evaluate("syncInputs()");
  await ui.evaluate("updateRoutes()");
  assert.equal(ui.evaluate("algorithmFamily()"), "rank_scheme");
  assert.match(ui.evaluate("chips({A:[[5,5],4]})"), /\[\[5,5\],4\]/);
  assert.match(ui.get("classical-algorithms").innerHTML, /Rank-OJ/);
  assert.doesNotMatch(ui.get("classical-algorithms").innerHTML, /Prange|Stern|GRS/);
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), []);
  assert.equal(ui.get("quantum-family").hidden, true);
  assert.equal(ui.get("quantum-algorithms").children.length, 0);
  assert.equal(ui.get("matrix-profile-field").hidden, true);
  assert.equal(ui.get("matrix-profile").disabled, true);
  assert.equal(ui.get("doom-field").hidden, true);
  assert.equal(ui.get("doom").disabled, true);
  assert.equal(ui.get("unbalanced-field").hidden, true);
  assert.equal(ui.get("unbalanced").disabled, true);
  ui.evaluate("renderAlgorithms(['Rank-OJ'], [])");
  assert.deepEqual(ui.plain("requestBody()").options.classical_algorithms, ["Rank-OJ"]);
  assert.deepEqual(ui.plain("requestBody()").options.quantum_algorithms, []);

  ui.get("scheme").value = "BRA";
  ui.get("parameter-set").value = "BRA-128";
  await ui.evaluate("updateRoutes()");
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), ["Rank-OJ"]);
  ui.get("scheme").value = "Binary";
  ui.get("parameter-set").value = "Binary-1";
  ui.evaluate("syncInputs(); renderAlgorithms()");
  assert.equal(ui.get("doom-field").hidden, false);
  assert.equal(ui.get("doom").disabled, false);
  assert.equal(ui.get("unbalanced").disabled, false);
  assert.equal(ui.get("quantum-family").hidden, false);
  assert.equal(ui.get("matrix-profile-field").hidden, false);
  assert.equal(ui.get("matrix-profile").disabled, false);
  assert.match(ui.get("quantum-algorithms").innerHTML, /QPrange/);
  assert.doesNotMatch(ui.get("quantum-algorithms").innerHTML, /Rank-WT23/);
  ui.evaluate(`state.availability.quantum.QSS = {available:true}; renderAlgorithms([], ['QSS']);
    state.mode = 'custom'; $('problem-kind').value = 'rank_sd'; renderAlgorithms()`);
  assert.equal(ui.get("quantum-family").hidden, true);
  assert.equal(ui.get("quantum-algorithms").children.length, 0);
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')"), []);
  assert.doesNotMatch(ui.get("classical-algorithms").innerHTML, /Rank-OJ/);
});

test("QPrange selection follows backend availability alongside other algorithms", () => {
  const ui = catalogueWorkspace();
  ui.evaluate(`state.availability = {
    classical: Object.fromEntries(state.catalogue.algorithm_families.binary.map(name => [name,{available:true}])),
    quantum: {QPrange:{available:true},QSS:{available:true},'QMMT+':{available:true}}
  }; renderAlgorithms(['BJMM'], ['QPrange','QSS'])`);
  const visible = ui.get("classical-algorithms").children.map((input) => input.value);
  assert.deepEqual(visible.sort(), [...catalogue.algorithm_families.binary].sort());
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), ["BJMM"]);
  const qprange = ui.query('input[name="quantum-algorithm"]').find((input) => input.value === "QPrange");
  assert.equal(qprange.disabled, false);
  assert.equal(qprange.checked, true);
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')"), ["QPrange", "QSS"]);
  assert.deepEqual(ui.plain("requestBody()").options.quantum_algorithms, ["QPrange", "QSS"]);
  ui.evaluate(`state.availability.quantum.QPrange = {available:false, reason:'Unsupported recovery route.'};
    renderAlgorithms()`);
  const unavailable = ui.query('input[name="quantum-algorithm"]').find((input) => input.value === "QPrange");
  assert.equal(unavailable.disabled, true);
  assert.equal(unavailable.checked, false);
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')"), ["QSS"]);
});

test("unavailable algorithms are unchecked and cannot leak into a request", () => {
  const ui = catalogueWorkspace();
  ui.evaluate(`state.availability = {
    classical: {Prange:{available:true},Stern:{available:false,reason:'No supported route.'}},
    quantum: {QSS:{available:false,reason:'Unsupported field.'},'QMMT+':{available:true}}
  }; renderAlgorithms(['Prange','Stern'], ['QSS','QMMT+'])`);
  const unavailable = ui.query('input[name="classical-algorithm"]').find((input) => input.value === "Stern");
  assert.equal(unavailable.disabled, true);
  assert.equal(unavailable.checked, false);
  assert.match(ui.get("classical-algorithms").innerHTML, /No supported route\./);
  // Disabled nodes must stay excluded even if a stale checked flag survives.
  unavailable.checked = true;
  const body = ui.plain("requestBody()");
  assert.deepEqual(body.options.classical_algorithms, ["Prange"]);
  assert.deepEqual(body.options.quantum_algorithms, ["QMMT+"]);
});

test("select all and clear affect only their own family and skip unavailable candidates", () => {
  const ui = catalogueWorkspace();
  ui.evaluate(`state.availability = {
    classical: {Prange:{available:true},Stern:{available:false},BJMM:{available:true}},
    quantum: {QSS:{available:true},'QMMT+':{available:true}}
  }; renderAlgorithms(['Prange'], ['QSS']); selectAlgorithms('classical')`);
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')").sort(), ["BJMM","Prange"]);
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')"), ["QSS"]);
  ui.evaluate("selectAlgorithms('quantum')");
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')").sort(), ["QMMT+","QSS"]);
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')").sort(), ["BJMM","Prange"]);
  ui.get("clear-classical").dispatch("click");
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), []);
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')").sort(), ["QMMT+","QSS"]);
  ui.evaluate("selectAlgorithms('classical')");
  ui.get("clear-quantum").dispatch("click");
  assert.deepEqual(ui.plain("selectedAlgorithms('quantum')"), []);
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')").sort(), ["BJMM","Prange"]);
});

test("catalogue scope requests retain the selected set and mark whole-scheme batches", () => {
  const ui = catalogueWorkspace();
  ui.evaluate("state.availability = {classical:{Prange:{available:true}},quantum:{}}; renderAlgorithms(['Prange'], [])");
  const single = ui.plain("requestBody()");
  assert.equal(single.scope, "parameter_set");
  assert.equal(single.parameter_set, "Binary-1");
  ui.get("evaluation-scope").value = "scheme";
  ui.evaluate("syncInputs()");
  assert.equal(ui.get("parameter-set").disabled, true);
  const batch = ui.plain("requestBody()");
  assert.equal(batch.scope, "scheme");
  assert.equal(batch.scheme, "Binary");
  assert.equal(batch.parameter_set, "Binary-1");
  assert.deepEqual(batch.options.classical_algorithms, ["Prange"]);
  ui.get("evaluation-scope").value = "parameter_set";
  ui.evaluate("syncInputs()");
  assert.equal(ui.get("parameter-set").disabled, false);
});

test("a late availability response cannot replace a newer route or selection", async () => {
  const ui = catalogueWorkspace();
  const pending = [];
  ui.context.fetch = () => new Promise((resolve) => pending.push((data) => resolve({ok:true,json:async () => data})));
  ui.evaluate("state.availability = {classical:{Prange:{available:true}},quantum:{}}; renderAlgorithms(['Prange'], [])");
  const first = ui.evaluate("updateRoutes()");
  assert.equal(ui.get("run-button").disabled, true);
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), []);
  assert.equal(ui.query('input[name="classical-algorithm"]').find((input) => input.value === "Prange").checked, true);
  ui.get("goal").value = "key_recovery";
  const second = ui.evaluate("updateRoutes()");
  assert.equal(pending.length, 2);
  const newestAvailability = {classical:{Prange:{available:true},Stern:{available:false}},quantum:{}};
  pending[1]({instances:[instance("sd", {route:"Newest route"})],availability:newestAvailability});
  await second;
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), ["Prange"]);
  assert.equal(ui.get("run-button").disabled, false);
  pending[0]({instances:[instance("sd", {route:"Stale route"})],availability:{classical:{Prange:{available:false},Stern:{available:true}},quantum:{}}});
  await first;
  assert.deepEqual(ui.plain("state.availability"), newestAvailability);
  assert.deepEqual(ui.plain("selectedAlgorithms('classical')"), ["Prange"]);
  assert.match(ui.get("route-preview-content").innerHTML, /Newest route/);
  assert.doesNotMatch(ui.get("route-preview-content").innerHTML, /Stale route/);
});

test("batch report and history retain separate minima and identities for each parameter set", () => {
  const ui = workspace();
  const makeReport = (parameter_set, costs, winner) => {
    const results = ["Prange","Stern"].map((algorithm,index) => ({algorithm,model:"classical",status:"computed",
      time_log2:costs[index],memory_log2:10,time_unit:"bit_operations",memory_unit:"bits"}));
    return {instance:instance("sd", {scheme:"Binary",parameter_set,name:`${parameter_set}/message`,route_id:"default"}),
      results,conclusions:{classical:{status:"computed",best:[results[winner]],reason:"Evaluated candidates only."},
        quantum:{status:"not_requested",best:[],reason:"No quantum algorithms selected."}}};
  };
  const reports = [makeReport("Binary-1", [20,25], 0),makeReport("Binary-2", [80,70], 1)];
  ui.context.recordFixture = {created_at:"2026-10-27T00:00:00Z",reports,
    request:{scope:"scheme",scheme:"Binary",parameter_set:"Binary-1",goal:"msg_recovery"},
    comparisons:reports.map((report) => ({parameter_set:report.instance.parameter_set,goal:report.instance.goal,
      conclusions:Object.fromEntries(Object.entries(report.conclusions).map(([family,conclusion]) => [family,{...conclusion,
        best:conclusion.best.map((estimate) => ({name:report.instance.name,route_id:"default",estimate}))}]))}))};
  ui.evaluate("renderResults(recordFixture); state.history = [recordFixture]; renderHistory()");
  assert.equal(ui.get("run-title").textContent, "Binary · all parameter sets");
  assert.match(ui.get("history-list").innerHTML, /<h2>Binary · all parameter sets<\/h2>/);
  const body = ui.get("result-summary").innerHTML.match(/<tbody>([\s\S]*?)<\/tbody>/)[1];
  const rows = body.match(/<tr>[\s\S]*?<\/tr>/g);
  assert.equal(rows.length, 2);
  assert.match(rows[0], /Binary-1[\s\S]*20\.00[\s\S]*Prange/);
  assert.match(rows[1], /Binary-2[\s\S]*70\.00[\s\S]*Stern/);
  assert.doesNotMatch(rows[1], /20\.00|Prange/);
  for (const id of ["cost-charts","results-body"]) {
    assert.match(ui.get(id).innerHTML, /Binary-1/);
    assert.match(ui.get(id).innerHTML, /Binary-2/);
  }
  assert.equal(ui.evaluate("requestTitle({parameter_set:'Binary-1'})"), "Binary-1");
  assert.equal(ui.evaluate("requestTitle({instance:{name:'custom test'}})"), "custom test");
});

test("CSV export retains units, missing quantum memory, effective targets and escaped text", () => {
  const ui = workspace();
  const classical = {algorithm:"Stern",model:"classical",status:"computed",time_log2:20,
    memory_log2:0,time_unit:"bit_operations",memory_unit:"bits",metadata:{effective_targets:1}};
  const quantum = {algorithm:"QSS",model:"quantum",status:"computed",time_log2:18,
    memory_log2:null,time_unit:"quantum_bit_operations",memory_unit:"not_estimated"};
  const input = instance("sd", {name:'=SUM(1,2) "quoted"',targets:8,tags:["doom:qcsd"]});
  ui.context.recordFixture = {request:{instance:input}, reports:[{instance:input,
    results:[classical,quantum],conclusions:{classical:{best:[classical]},quantum:{best:[quantum]}}}]};
  ui.evaluate("state.current = recordFixture; download = (content, extension, mime) => { globalThis.exported = {content, extension, mime}; }; exportCSV()");
  const exported = ui.context.exported;
  assert.equal(exported.extension, "csv");
  assert.equal(exported.mime, "text/csv;charset=utf-8");
  const [header, ...lines] = exported.content.replace(/^\uFEFF/, "").split("\r\n");
  const fields = header.split(",");
  const rows = lines.map((line) => {
    const values = [...line.matchAll(/"((?:[^"]|"")*)"(?:,|$)/g)].map((match) => match[1].replaceAll('""', '"'));
    assert.equal(values.length, fields.length);
    return Object.fromEntries(fields.map((field,index) => [field,values[index]]));
  });
  assert.equal(rows.length, 2);
  assert.equal(rows[0].instance_name, `'${input.name}`);
  assert.equal(rows[0].time_unit, "bit_operations");
  assert.equal(rows[0].memory_log2, "0");
  assert.equal(rows[0].memory_unit, "bits");
  assert.equal(rows[0].effective_targets, "1");
  assert.equal(rows[1].time_unit, "quantum_bit_operations");
  assert.equal(rows[1].memory_log2, "");
  assert.equal(rows[1].memory_unit, "not_estimated");
  assert.equal(rows[1].is_route_minimum, "true");
});

test("assumptions retain algorithm scope while deduplicating shared notes and separating references", () => {
  const ui = workspace();
  ui.context.reportFixture = {
    instance:{assumptions:["A usable orbit is supplied.","A usable orbit is supplied."],references:["Parameter source"]},
    results:[
      {model:"classical",algorithm:"Prange",assumptions:["A usable orbit is supplied.","Random-matrix cost proxy.","Multiple syndromes are processed."],references:["Model source"]},
      {model:"classical",algorithm:"Stern",assumptions:["Random-matrix cost proxy.","Multiple syndromes are processed."],references:["Model source"]},
      {model:"quantum",algorithm:"QSS",assumptions:["Random-matrix cost proxy.","Only one syndrome is processed.","Costs < gate counts are not claimed."],references:[]},
    ],
  };
  const groups = ui.plain("assumptionGroups(reportFixture)");
  assert.deepEqual(groups, [
    {label:"Recovery route",items:["A usable orbit is supplied."]},
    {label:"Classical: Prange, Stern; Quantum: QSS",items:["Random-matrix cost proxy."]},
    {label:"Classical: Prange, Stern",items:["Multiple syndromes are processed."]},
    {label:"Quantum: QSS",items:["Only one syndrome is processed.","Costs < gate counts are not claimed."]},
  ]);
  const html = ui.evaluate("reportAssumptions(reportFixture)");
  for (const note of ["A usable orbit is supplied.","Random-matrix cost proxy.","Model source"]) {
    assert.equal(html.split(note).length - 1, 1);
  }
  assert.match(html, /<strong>References<\/strong>[\s\S]*Parameter source[\s\S]*Model source/);
  assert.match(html, /Costs &lt; gate counts/);
});
