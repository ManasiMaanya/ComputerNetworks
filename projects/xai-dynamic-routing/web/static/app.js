"use strict";

/* XAI routing demo page: one shared graph view plus one tab per project phase (P0-P7).
   Every number shown comes from the API (web/app.py), which reuses the project modules. */

const SVG_NS = "http://www.w3.org/2000/svg";
const COLORS = { ai: "#f87171", bb: "#fbbf24", rip: "#a3a3a3", ospf: "#38bdf8", ospfbw: "#34d399",
                 runner: "#c084fc", prev: "#c084fc", cand: "#38bdf8" };

const state = {
  topology: "sample",
  topo: null,          // /api/topology response
  catalog: [],
  tab: "topology",
  highlights: [],      // [{nodes, color, label, width, dash}]
  sim: null,           // last /api/simulate response
  simTimer: null,
};

/* ---------------------------------------------------------------- helpers */

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/* Replace an element's children, skipping null/undefined/false (replaceChildren would print "null"). */
function fill(el, ...children) {
  el.replaceChildren(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

function s(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

function fmt(v, digits = 4) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return String(v);
  return Number(v.toPrecision(digits)).toString();
}

const route = (nodes) => (nodes || []).join(" → ");

function setStatus(text, error = false) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = error ? "error" : "";
}

async function api(path, options) {
  const res = await fetch(path, options);
  let body;
  try { body = await res.json(); } catch { body = {}; }
  if (!res.ok) {
    const err = new Error(body.detail || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

function q(params) {
  return new URLSearchParams(Object.entries(params).filter(([, v]) => v !== null && v !== undefined)).toString();
}

function content() { return document.getElementById("content"); }

function errorBox(err) {
  const hint = err.status === 503 ? " Train the model first: python scripts/train.py" : "";
  return h("div", { class: "callout err" }, String(err.message || err) + hint);
}

function loading(text = "Computing…") { fill(content(), h("p", { class: "muted" }, text)); }

function srcDst() {
  return { src: document.getElementById("src").value, dst: document.getElementById("dst").value };
}

/* ---------------------------------------------------------------- graph */

function metricColor(value, metric, edges) {
  const vals = edges.map((e) => e[metric]).filter((v) => typeof v === "number");
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const t = hi > lo ? (value - lo) / (hi - lo) : 0;
  const r = Math.round(56 + t * (248 - 56)), g = Math.round(189 - t * (189 - 113)), b = Math.round(248 - t * (248 - 113));
  return `rgb(${r},${g},${b})`;
}

function drawGraph() {
  const svg = document.getElementById("graph");
  fill(svg);
  const topo = state.topo;
  if (!topo) return;
  const [w, hgt] = topo.viewbox;
  svg.setAttribute("viewBox", `0 0 ${w} ${hgt}`);
  const pos = Object.fromEntries(topo.nodes.map((n) => [n.id, [n.x, n.y]]));
  const n = topo.nodes.length;
  const radius = n <= 12 ? 17 : n <= 30 ? 12 : n <= 60 ? 8 : 5;
  const font = n <= 12 ? 13 : n <= 30 ? 10 : 8;
  const colorBy = document.getElementById("color-by").value;

  for (const e of topo.edges) {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) continue;
    const stroke = colorBy && typeof e[colorBy] === "number" ? metricColor(e[colorBy], colorBy, topo.edges) : "#334155";
    const line = s("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke, "stroke-width": 3,
                             "stroke-linecap": "round", class: "edge" });
    line.addEventListener("click", () => showEdge(e));
    svg.appendChild(line);
  }
  // highlighted paths, widest first so overlapping routes stay visible
  state.highlights.forEach((hl, i) => {
    const pts = hl.nodes.map((id) => pos[id]).filter(Boolean);
    if (pts.length < 2) return;
    const width = hl.width || Math.max(3, 11 - i * 3);
    svg.appendChild(s("polyline", { points: pts.map((p) => p.join(",")).join(" "), fill: "none",
      stroke: hl.color, "stroke-width": width, "stroke-linecap": "round", "stroke-linejoin": "round",
      "stroke-dasharray": hl.dash || "", opacity: 0.85 }));
  });
  const ends = new Set([document.getElementById("src").value, document.getElementById("dst").value]);
  for (const node of topo.nodes) {
    const [x, y] = pos[node.id];
    const isEnd = ends.has(node.id);
    svg.appendChild(s("circle", { cx: x, cy: y, r: isEnd ? radius + 3 : radius,
      fill: isEnd ? "#0c4a6e" : "#1e293b", stroke: isEnd ? "#38bdf8" : "#e2e8f0", "stroke-width": 2 }));
    if (n <= 60) {
      const t = s("text", { x, y: n <= 12 ? y + 4 : y - radius - 3, "text-anchor": "middle", fill: "#e2e8f0",
                            "font-size": font });
      t.textContent = node.label.length > 14 ? node.label.slice(0, 13) + "…" : node.label;
      svg.appendChild(t);
    }
  }
  const legend = document.getElementById("legend");
  fill(legend, ...state.highlights.map((hl) =>
    h("span", {}, h("span", { class: "sw", style: `background:${hl.color}` }), hl.label)));
  if (colorBy) legend.appendChild(h("span", {}, `links: low → high ${colorBy} (blue → red)`));
}

function highlight(list) { state.highlights = list.filter((x) => x && x.nodes && x.nodes.length > 1); drawGraph(); }

function showEdge(e) {
  const lines = [`${e.source} — ${e.target}`];
  for (const k of ["delay", "bandwidth", "congestion", "loss", "energy", "security_risk", "utilization", "queue", "reliability"]) {
    if (k in e) lines.push(`  ${k.padEnd(14)} ${fmt(e[k])}${e.metric_source ? `   (${e.metric_source[k]})` : ""}`);
  }
  document.getElementById("detail").textContent = lines.join("\n");
}

/* ---------------------------------------------------------------- topology */

async function loadCatalog() {
  const data = await api("/api/topologies");
  state.catalog = data.topologies;
  const sel = document.getElementById("topology");
  fill(sel);
  const groups = {};
  for (const t of data.topologies) (groups[t.group] = groups[t.group] || []).push(t);
  for (const [group, items] of Object.entries(groups)) {
    const og = h("optgroup", { label: `${group} (${items.length})` });
    for (const t of items) og.appendChild(h("option", { value: t.id }, t.label));
    sel.appendChild(og);
  }
  sel.value = data.default;
}

async function loadTopology(id, render = true) {
  setStatus("Loading topology…");
  try {
    state.topo = await api("/api/topology?" + q({ topology: id }));
  } catch (err) {
    setStatus("Could not load topology: " + err.message, true);
    return;
  }
  state.topology = id;
  document.getElementById("topology").value = id;
  const nodes = state.topo.nodes.map((n) => n.id).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  for (const [selId, pick] of [["src", 0], ["dst", nodes.length - 1]]) {
    const sel = document.getElementById(selId);
    fill(sel, ...nodes.map((n) => h("option", { value: n }, n)));
    sel.value = nodes[pick];
  }
  if (id === "sample") { document.getElementById("src").value = "R1"; document.getElementById("dst").value = "R8"; }
  const t = state.topo;
  document.getElementById("graph-title").textContent = `${t.name}: ${t.node_count} nodes, ${t.edge_count} links`;
  setStatus(`Loaded ${t.file}`);
  document.getElementById("detail").textContent = "Click a link to read its metrics.";
  highlight([]);
  if (render) renderTab();
}

/* ---------------------------------------------------------------- tabs */

const TABS = {
  topology: {
    usecase: "Open the demo and inspect the network as a graph. Click a link to read its delay, bandwidth, congestion, loss, energy, security_risk, utilization, queue and reliability. Colour links by a metric to spot hot spots.",
    enhancement: "RIP and OSPF each look at one number per link (hop count or a configured cost). This network carries nine QoS and security metrics per link, which the later tabs use together.",
    render: renderTopologyTab,
  },
  paths: {
    usecase: "Pick a source and destination to list the k candidate paths (fewest-hop and lowest-delay paths interleaved) and their 12 aggregated features. Click a row to draw that path.",
    enhancement: "RIP only knows hop count; here every candidate is a multi-metric vector (delay, bottleneck bandwidth, worst-link risk, loss, congestion…) plus the configured rule cost.",
    render: renderPaths,
  },
  baselines: {
    usecase: "See the paths RIP (fewest hops) and OSPF (Dijkstra on delay, or on 10^8 / bandwidth) would choose, with lab-style costs.",
    enhancement: "Side by side, the classic protocols can disagree: same hop count, different delay, or a short path over a risky link.",
    render: renderBaselines,
  },
  infer: {
    usecase: "Ask the trained model for a route. It scores every candidate's expected cost (QoS + security) and recommends the lowest. The black-box MLP's pick is shown for comparison.",
    enhancement: "The recommendation can differ from both RIP and OSPF because it weighs delay, loss, congestion, energy and security risk together instead of one metric.",
    render: renderInfer,
  },
  explain: {
    usecase: "Answer \"why this path?\": SHAP contributions for the recommended path, why it beat the runner-up, an optional LIME check, and a one-sentence summary.",
    enhancement: "Classical IGPs give no reasons. Here every decision comes with feature-level explanations an operator can check.",
    render: renderExplain,
  },
  compare: {
    usecase: "One table: RIP vs OSPF vs AI (explained) vs AI (black-box) on several pairs, with delay, loss, worst-link risk and hops, plus the held-out evaluation from training.",
    enhancement: "A report-ready comparison: the AI trades a little delay for lower risk and loss, and the held-out table scores every method by the cost it actually experienced.",
    render: renderCompare,
  },
  timeline: {
    usecase: "Play a scenario step by step: link metrics change (scripted incidents or simulated traffic), the model re-recommends every step, and each reroute shows what changed and why.",
    enhancement: "OSPF's static costs ignore congestion and risk changes; the recommender adapts and explains each reroute.",
    render: renderTimeline,
  },
  larger: {
    usecase: "Load a real network (Topology Zoo or SNDlib) and run the same analysis on it. Every metric is labelled as documented, estimated or synthetic.",
    enhancement: "Not just the 8-router lab: the same pipeline runs on real ISP and research backbones.",
    render: renderLarger,
  },
};

function renderTab() {
  const tab = TABS[state.tab];
  document.getElementById("usecase").textContent = tab.usecase;
  document.getElementById("enhancement").textContent = tab.enhancement;
  for (const b of document.querySelectorAll("#tabs .tab")) b.classList.toggle("on", b.dataset.tab === state.tab);
  if (state.tab !== "timeline") stopPlay();
  tab.render();
}

/* P0 */
function renderTopologyTab() {
  highlight([]);
  const t = state.topo;
  if (!t) return;
  const rows = [["File", t.file], ["Nodes", t.node_count], ["Links", t.edge_count], ["Connected components", t.components]];
  const out = [h("table", {}, ...rows.map(([k, v]) => h("tr", {}, h("th", { class: "left" }, k), h("td", { class: "left" }, String(v)))))];
  if (t.provenance && Object.keys(t.provenance).length) out.push(provenanceTable(t.provenance));
  out.push(h("p", { class: "muted small" }, "Tip: use “Color links by” above the graph, and click any link for its values."));
  fill(content(), ...out);
}

function provenanceTable(prov) {
  const kinds = ["documented", "estimated", "synthetic", "default"];
  return h("div", {},
    h("h3", {}, "Where each metric comes from (number of links)"),
    h("div", { class: "table-wrap" }, h("table", {},
      h("tr", {}, h("th", { class: "left" }, "metric"), ...kinds.map((k) => h("th", {}, k))),
      ...Object.entries(prov).map(([m, counts]) =>
        h("tr", {}, h("td", { class: "left" }, m), ...kinds.map((k) => h("td", {}, counts[k] || "")))))),
    h("p", { class: "muted small" }, "documented = from the source file; estimated = derived (e.g. delay from distance); synthetic/default = filled in and labelled, not measured."));
}

/* P1 */
async function renderPaths() {
  const { src, dst } = srcDst();
  loading();
  try {
    const data = await api("/api/paths?" + q({ topology: state.topology, src, dst }));
    const cols = ["hops", "sum_delay", "min_bandwidth", "max_security_risk", "mean_congestion", "sum_loss", "path_loss", "min_reliability", "mean_energy"];
    let selected = null;
    const rows = data.candidates.map((c) => {
      const tr = h("tr", { class: "clickable" }, h("td", {}, c.path_id), h("td", { class: "path" }, route(c.nodes)),
        ...cols.map((k) => h("td", {}, fmt(c.features[k] ?? c[k]))), h("td", {}, fmt(c.rule_cost)));
      tr.addEventListener("click", () => {
        if (selected) selected.classList.remove("sel");
        tr.classList.add("sel"); selected = tr;
        highlight([{ nodes: c.nodes, color: COLORS.cand, label: `candidate ${c.path_id}` }]);
      });
      return tr;
    });
    const best = data.candidates.reduce((a, b) => (b.rule_cost < a.rule_cost ? b : a));
    highlight([{ nodes: best.nodes, color: COLORS.cand, label: `lowest rule cost (candidate ${best.path_id})` }]);
    fill(content(), 
      h("p", {}, `${data.candidates.length} candidates for ${src} → ${dst} (strategy “${data.strategy}”, k = ${data.k}).`),
      h("div", { class: "table-wrap" }, h("table", {},
        h("tr", {}, h("th", {}, "#"), h("th", { class: "path" }, "path"), ...cols.map((k) => h("th", { title: data.units[k] || "" }, k)), h("th", {}, "rule cost")),
        ...rows)),
      h("p", { class: "muted small" }, "Rule cost = the configured weighted objective (lower is better); hover a column header for units. path_loss = 1 − Π(1 − loss)."));
  } catch (err) { fill(content(), errorBox(err)); highlight([]); }
}

/* P2 */
async function renderBaselines() {
  const { src, dst } = srcDst();
  loading();
  try {
    const data = await api("/api/baselines?" + q({ topology: state.topology, src, dst }));
    const items = [["RIP-like (hop count)", data.rip, COLORS.rip], ["OSPF-like (delay)", data.ospf_delay, COLORS.ospf],
                   ["OSPF-like (10^8 / bandwidth)", data.ospf_inverse_bandwidth, COLORS.ospfbw]];
    highlight(items.map(([label, r, color], i) => ({ nodes: r.nodes, color, label, dash: i === 2 ? "10 6" : "" })));
    const same = route(data.rip.nodes) === route(data.ospf_delay.nodes);
    fill(content(), 
      h("div", { class: "cards" }, ...items.map(([label, r, color]) => h("div", { class: "card", style: `border-top-color:${color}` },
        h("strong", {}, label), h("div", { class: "route" }, route(r.nodes)),
        h("dl", {}, h("dt", {}, `cost (${r.cost_metric})`), h("dd", {}, fmt(r.cost)), h("dt", {}, "hops"), h("dd", {}, r.hops),
          h("dt", {}, "delay (ms)"), h("dd", {}, fmt(r.metrics.sum_delay)), h("dt", {}, "path loss"), h("dd", {}, fmt(r.metrics.path_loss)),
          h("dt", {}, "max risk"), h("dd", {}, fmt(r.metrics.max_security_risk)), h("dt", {}, "rule cost"), h("dd", {}, fmt(r.metrics.rule_cost)))))),
      h("div", { class: "callout" + (same ? " warn" : "") }, same
        ? `RIP and OSPF (delay) agree on ${src} → ${dst}. Try another pair (e.g. R1 → R7 or R2 → R5) to see them diverge.`
        : `RIP and OSPF disagree on ${src} → ${dst}: one metric per protocol gives different “shortest” paths.`),
      h("p", { class: "muted small" }, `The project's configured OSPF cost is “${data.configured_ospf_cost}”.`));
  } catch (err) { fill(content(), errorBox(err)); highlight([]); }
}

/* P3 */
async function renderInfer() {
  const { src, dst } = srcDst();
  loading("Asking the model…");
  try {
    const [ai, base] = await Promise.all([
      api("/api/infer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topology: state.topology, src, dst }) }),
      api("/api/baselines?" + q({ topology: state.topology, src, dst })),
    ]);
    const hl = [{ nodes: ai.path, color: COLORS.ai, label: "AI (explained RF)" }];
    if (ai.blackbox) hl.push({ nodes: ai.blackbox.path, color: COLORS.bb, label: "AI black-box (MLP)", width: 4, dash: "10 6" });
    hl.push({ nodes: base.ospf_delay.nodes, color: COLORS.ospf, label: "OSPF-like (delay)", width: 3, dash: "3 6" });
    highlight(hl);
    const differs = [];
    if (route(ai.path) !== route(base.rip.nodes)) differs.push("RIP");
    if (route(ai.path) !== route(base.ospf_delay.nodes)) differs.push("OSPF");
    fill(content(), 
      h("div", { class: "callout" }, h("strong", {}, "Recommended: "), route(ai.path),
        h("br"), differs.length ? `Differs from ${differs.join(" and ")}.` : "Same as RIP and OSPF for this pair.",
        ai.blackbox ? h("span", {}, h("br"), `Black-box MLP picks: ${route(ai.blackbox.path)}.`) : null),
      ai.stale_scoring ? h("div", { class: "callout warn" }, "The scoring config changed since training; retrain for consistent results.") : null,
      h("h3", {}, "Candidates ranked by predicted cost"),
      h("div", { class: "table-wrap" }, h("table", {},
        h("tr", {}, h("th", {}, "rank"), h("th", { class: "path" }, "path"), h("th", {}, "predicted cost"), h("th", {}, "rule cost now"),
          h("th", {}, "hops"), h("th", {}, "delay"), h("th", {}, "max risk"), h("th", {}, "sum loss")),
        ...ai.candidates.map((c) => h("tr", { class: c.rank === 1 ? "sel" : "" }, h("td", {}, c.rank), h("td", { class: "path" }, route(c.nodes)),
          h("td", {}, fmt(c.predicted_cost)), h("td", {}, fmt(c.rule_cost)), h("td", {}, fmt(c.hops)), h("td", {}, fmt(c.sum_delay)),
          h("td", {}, fmt(c.max_security_risk)), h("td", {}, fmt(c.sum_loss)))))),
      h("p", { class: "muted small" }, `Model target: ${ai.target}. Note: ${ai.note}.`));
  } catch (err) { fill(content(), errorBox(err)); highlight([]); }
}

/* P4 */
function bars(rows, valueKey = "contribution", labelFn = (r) => `${r.feature} = ${fmt(r.value, 3)}`, limit = 10) {
  const top = rows.slice(0, limit);
  const max = Math.max(...top.map((r) => Math.abs(r[valueKey])), 1e-9);
  return h("div", { class: "bars" }, ...top.map((r) => {
    const v = r[valueKey], pct = (Math.abs(v) / max) * 50;
    const bar = h("div", { class: "bar " + (v < 0 ? "neg" : "pos"), style: v < 0 ? `right:50%;width:${pct}%` : `left:50%;width:${pct}%` });
    return h("div", { class: "bar-row" }, h("span", { class: "name", title: labelFn(r) }, labelFn(r)),
      h("div", { class: "bar-track" }, h("div", { class: "mid" }), bar), h("span", { class: "val" }, (v > 0 ? "+" : "") + fmt(v, 3)));
  }));
}

async function renderExplain(withLime = false) {
  const { src, dst } = srcDst();
  loading(withLime ? "Running SHAP and LIME…" : "Running SHAP…");
  try {
    const data = await api("/api/explain?" + q({ topology: state.topology, src, dst, lime: withLime }));
    highlight([{ nodes: data.path, color: COLORS.ai, label: "recommended" },
               data.contrast_path ? { nodes: data.contrast_path, color: COLORS.runner, label: "runner-up", dash: "10 6" } : null]);
    const shap = data.shap;
    const parts = [
      h("div", { class: "callout" }, data.summary),
      h("h3", {}, "SHAP: contribution of each input to the predicted cost"),
      h("p", { class: "muted small" }, `Base value ${fmt(shap.base_value)} + contributions = prediction ${fmt(shap.prediction)} (additivity error ${shap.additivity_error.toExponential(1)}). Blue lowers the cost (argues for the path), red raises it.`),
      bars(shap.contributions),
    ];
    if (shap.contrast) {
      parts.push(h("h3", {}, `Why not the runner-up (${route(data.contrast_path)})?`),
        h("p", { class: "muted small" }, `SHAP(chosen) − SHAP(runner-up); the bars sum to the predicted-cost gap ${fmt(shap.contrast.predicted_cost_gap)}.`),
        bars(shap.contrast.contributions, "contribution", (r) => `${r.feature}: ${fmt(r.value, 3)} vs ${fmt(r.contrast_value, 3)}`, 6));
    }
    const limeBox = h("div", {});
    if (data.lime.available) {
      limeBox.append(h("h3", {}, "LIME: local linear surrogate (same instance)"),
        h("p", { class: "muted small" }, `Surrogate R² ${fmt(data.lime.surrogate_r2, 3)}, local prediction ${fmt(data.lime.local_prediction)} vs model ${fmt(data.lime.model_prediction)}. A low R² means the linear surrogate fits this neighbourhood poorly; trust signs more than sizes.`),
        bars(data.lime.weights, "weight", (r) => r.condition, 8));
    } else {
      limeBox.append(h("div", { class: "row" }, h("button", { onclick: () => renderExplain(true) }, "Include LIME (≈1 s)"),
        h("span", { class: "muted small" }, data.lime.reason)));
    }
    parts.push(limeBox, h("p", { class: "muted small" }, "These explain the model's prediction, not causation in the network."));
    fill(content(), ...parts);
  } catch (err) { fill(content(), errorBox(err)); highlight([]); }
}

/* P5 */
async function renderCompare(pairsText = null, randomPairs = null) {
  const input = h("input", { placeholder: "e.g. R1:R8,R2:R5 (blank = default pairs)", value: pairsText || "", style: "flex:1;min-width:12rem" });
  const header = h("div", { class: "row" }, input,
    h("button", { class: "primary", onclick: () => renderCompare(input.value.trim() || null) }, "Run comparison"));
  fill(content(), header, h("p", { class: "muted" }, "Comparing… (a few seconds; SHAP runs for every pair)"));
  try {
    const [cmp, evalData] = await Promise.all([
      api("/api/compare?" + q({ topology: state.topology, pairs: pairsText, random_pairs: randomPairs })),
      api("/api/evaluation").catch(() => null),
    ]);
    const methods = ["RIP", "OSPF", "AI", "AI-BB"].filter((m) => cmp.rows.some((r) => r.method === m));
    const colorOf = { RIP: COLORS.rip, OSPF: COLORS.ospf, AI: COLORS.ai, "AI-BB": COLORS.bb };
    const byPair = {};
    for (const r of cmp.rows) (byPair[`${r.src}>${r.dst}`] = byPair[`${r.src}>${r.dst}`] || []).push(r);
    const showPair = (key) => highlight((byPair[key] || []).filter((r) => r.status === "ok").map((r, i) => ({
      nodes: r.path.split("-"), color: colorOf[r.method], label: r.method,
      dash: r.method === "AI-BB" ? "10 6" : "", width: r.method === "AI-BB" ? 4 : undefined })));
    let selected = null;
    const pairRows = Object.entries(byPair).map(([key, rows]) => {
      const [a, b] = key.split(">");
      const cell = (m) => { const r = rows.find((x) => x.method === m); return r ? (r.status === "ok" ? `${r.path.replaceAll("-", "→")}  (${fmt(r.sum_delay, 3)} ms, risk ${fmt(r.max_security_risk, 2)})` : r.status) : "–"; };
      const tr = h("tr", { class: "clickable" }, h("td", { class: "left" }, `${a} → ${b}`), ...methods.map((m) => h("td", { class: "path" }, cell(m))));
      tr.addEventListener("click", () => { if (selected) selected.classList.remove("sel"); tr.classList.add("sel"); selected = tr; showPair(key); });
      return tr;
    });
    const parts = [header];
    if (cmp.summary.length) {
      parts.push(h("h3", {}, `Mean over ${cmp.summary[0].pairs} pairs where every method found a path`),
        h("div", { class: "table-wrap" }, h("table", {},
          h("tr", {}, h("th", { class: "left" }, "method"), ...["sum_delay", "sum_loss", "path_loss", "max_security_risk", "hops", "rule_cost"].map((k) => h("th", {}, k))),
          ...cmp.summary.map((r) => h("tr", {}, h("td", { class: "left", style: `color:${colorOf[r.method]}` }, r.method),
            ...["sum_delay", "sum_loss", "path_loss", "max_security_risk", "hops", "rule_cost"].map((k) => h("td", {}, fmt(r[k]))))))));
    }
    parts.push(h("h3", {}, "Per pair (click a row to draw it)"),
      h("div", { class: "table-wrap" }, h("table", {}, h("tr", {}, h("th", { class: "left" }, "pair"), ...methods.map((m) => h("th", { class: "path" }, m))), ...pairRows)),
      h("p", { class: "muted small" }, "rule_cost is the AI's own objective, shown for reference; delay, loss, risk and hops are method-neutral."));
    if (evalData && evalData.methods) {
      const names = { hop_count: "Hop count (RIP-like)", min_delay: "Min delay (OSPF-like)", snapshot_rule: "Snapshot rule", blackbox: "AI black-box (MLP)", model: "AI explained (RF)", oracle: "Oracle (hindsight)" };
      parts.push(h("h3", {}, "Held-out evaluation (from training)"),
        h("p", { class: "muted small" }, `${evalData.queries} held-out decisions; each pick is scored by the true label: ${evalData.target}.`),
        h("table", {}, h("tr", {}, h("th", { class: "left" }, "method"), h("th", {}, "best pick (top-1)"), h("th", {}, "mean regret"), h("th", {}, "mean true cost")),
          ...Object.entries(names).filter(([k]) => evalData.methods[k]).map(([k, label]) => h("tr", {}, h("td", { class: "left" }, label),
            h("td", {}, (100 * evalData.methods[k].top1).toFixed(1) + "%"), h("td", {}, fmt(evalData.methods[k].mean_regret, 3)), h("td", {}, fmt(evalData.methods[k].mean_true_cost, 3))))),
        h("p", { class: "muted small" }, `AI vs snapshot rule: ${evalData.vs_snapshot_rule.model_better} better / ${evalData.vs_snapshot_rule.tie} same / ${evalData.vs_snapshot_rule.snapshot_rule_better} worse. Results come from a simulated traffic model, not measured traffic.`));
    }
    fill(content(), ...parts);
    const first = Object.keys(byPair)[0];
    if (first) { pairRows[0].classList.add("sel"); selected = pairRows[0]; showPair(first); }
  } catch (err) { fill(content(), header, errorBox(err)); highlight([]); }
}

/* P6 */
function stopPlay() { if (state.simTimer) { clearInterval(state.simTimer); state.simTimer = null; } }

async function renderTimeline() {
  let list;
  try { list = await api("/api/scenarios"); } catch (err) { fill(content(), errorBox(err)); return; }
  const sel = h("select", {}, ...list.scenarios.map((sc) => h("option", { value: sc.id }, `${sc.name} (${sc.src}→${sc.dst}, ${sc.steps} steps${sc.traffic ? ", traffic" : ""})`)));
  sel.value = state.sim ? state.sim.id : list.default;
  const desc = h("p", { class: "muted small" });
  const setDesc = () => { const sc = list.scenarios.find((x) => x.id === sel.value); desc.textContent = sc ? sc.description : ""; };
  sel.addEventListener("change", setDesc); setDesc();
  const body = h("div", {});
  fill(content(), h("div", { class: "row" }, sel, h("button", { class: "primary", onclick: () => runScenario(sel.value, body) }, "Run scenario")), desc, body);
  if (state.sim && state.sim.id === sel.value) showSim(body);
}

async function runScenario(id, body) {
  stopPlay();
  fill(body, h("p", { class: "muted" }, "Simulating… (re-recommends every step)"));
  try {
    const data = await api("/api/simulate?" + q({ scenario: id }));
    data.id = id;
    state.sim = data;
    if (data.topology && data.topology !== state.topology) await loadTopology(data.topology, false);
    document.getElementById("src").value = data.src;
    document.getElementById("dst").value = data.dst;
    showSim(body);
  } catch (err) { fill(body, errorBox(err)); }
}

function costChart(steps, current) {
  const w = 460, hgt = 90, pad = 8;
  const vals = steps.map((st) => st.predicted_cost);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const x = (i) => pad + (i * (w - 2 * pad)) / Math.max(steps.length - 1, 1);
  const y = (v) => hgt - pad - ((v - lo) / ((hi - lo) || 1)) * (hgt - 2 * pad);
  const svg = s("svg", { viewBox: `0 0 ${w} ${hgt}`, width: "100%", style: "background:#0b1324;border-radius:6px" });
  steps.forEach((st, i) => { if (st.rerouted) svg.appendChild(s("line", { x1: x(i), x2: x(i), y1: 0, y2: hgt, stroke: "#7f1d1d", "stroke-width": 2 })); });
  svg.appendChild(s("polyline", { points: steps.map((st, i) => `${x(i)},${y(st.predicted_cost)}`).join(" "), fill: "none", stroke: COLORS.ai, "stroke-width": 2 }));
  svg.appendChild(s("circle", { cx: x(current), cy: y(steps[current].predicted_cost), r: 5, fill: "#fff" }));
  return svg;
}

function showSim(body) {
  const sim = state.sim;
  const slider = h("input", { type: "range", min: 0, max: sim.steps.length - 1, value: 0 });
  const info = h("div", { class: "step-info" });
  const chart = h("div", {});
  const playBtn = h("button", {}, "▶ Play");
  const show = (i) => {
    const st = sim.steps[i];
    slider.value = i;
    highlight([{ nodes: st.path, color: COLORS.ai, label: "AI path" },
               st.rerouted ? { nodes: st.previous_path, color: COLORS.prev, label: "previous path", dash: "10 6" } : null,
               { nodes: st.ospf_path, color: COLORS.ospf, label: "OSPF-like", width: 3, dash: "3 6" }]);
    fill(chart, h("p", { class: "muted small" }, "Predicted cost of the chosen path per step (red lines = reroutes)"), costChart(sim.steps, i));
    const parts = [
      h("div", {}, h("strong", {}, `Step ${st.step}`), " ", st.rerouted ? h("span", { class: "tag reroute" }, "REROUTE") : null,
        ...st.events.map((ev) => h("span", { class: "tag" }, ev))),
      h("div", {}, "AI path: ", h("strong", {}, route(st.path)), `  (predicted ${fmt(st.predicted_cost)}, rule ${fmt(st.rule_cost)})`),
      st.rerouted ? h("div", { class: "muted" }, "was: ", route(st.previous_path)) : null,
      h("div", { class: "muted" }, `RIP-like ${route(st.rip_path)}  ·  OSPF-like ${route(st.ospf_path)}`),
    ];
    const watched = Object.entries(st.watched);
    if (watched.length) parts.push(h("div", { class: "muted small" }, "Watched link: " + watched.map(([k, v]) => `${k} = ${fmt(v, 3)}`).join(", ")));
    if (st.changes && st.changes.length) {
      parts.push(h("h3", {}, "What changed on the old / new path"),
        h("ul", {}, ...st.changes.map((c) => h("li", {}, `${c.edge} ${c.metric}: ${fmt(c.old, 3)} → ${fmt(c.new, 3)} (${c.cause}; on ${c.on_path} path)`))));
    }
    if (st.explanation) {
      const ex = st.explanation;
      parts.push(h("h3", {}, ex.contrast && ex.contrast.length ? `Why this path instead of the ${ex.contrast_reason}` : "Top SHAP contributions"),
        ex.contrast && ex.contrast.length
          ? bars(ex.contrast, "contribution", (r) => `${r.feature}: ${fmt(r.value, 3)} vs ${fmt(r.contrast_value, 3)}`, 4)
          : bars(ex.top, "contribution", undefined, 4));
    }
    fill(info, ...parts);
  };
  slider.addEventListener("input", () => { stopPlay(); playBtn.textContent = "▶ Play"; show(Number(slider.value)); });
  playBtn.addEventListener("click", () => {
    if (state.simTimer) { stopPlay(); playBtn.textContent = "▶ Play"; return; }
    playBtn.textContent = "⏸ Pause";
    if (Number(slider.value) >= sim.steps.length - 1) show(0);
    state.simTimer = setInterval(() => {
      const next = Number(slider.value) + 1;
      if (next >= sim.steps.length) { stopPlay(); playBtn.textContent = "▶ Play"; return; }
      show(next);
    }, 900);
  });
  fill(body, 
    h("div", { class: "callout" }, `${sim.scenario}: ${sim.reroutes} reroute(s) in ${sim.steps.length} steps for ${sim.src} → ${sim.dst}.`),
    h("div", { class: "row timeline-controls" }, playBtn, slider), chart, info);
  show(0);
}

/* P7 */
function renderLarger() {
  const t = state.topo;
  const search = h("input", { id: "zoo-search", placeholder: "Search 300+ real topologies (e.g. Abilene, Geant, Cogent)…" });
  const list = h("div", { class: "catalog" });
  const refresh = () => {
    const term = search.value.toLowerCase();
    const items = state.catalog.filter((x) => x.group !== "Sample" && (x.label.toLowerCase().includes(term) || x.group.toLowerCase().includes(term))).slice(0, 80);
    fill(list, ...items.map((x) => h("button", { onclick: () => loadTopology(x.id) }, `${x.label}  ·  ${x.group}`)));
    if (!items.length) fill(list, h("p", { class: "muted small" }, "No match. Real topologies live in data/raw (run scripts/fetch_topology_zoo.py)."));
  };
  search.addEventListener("input", refresh); refresh();
  const parts = [search, list, h("h3", {}, `Current: ${t.name}`),
    h("p", {}, `${t.node_count} nodes, ${t.edge_count} links, ${t.components} component(s). File: ${t.file}`)];
  if (t.node_count > 60) parts.push(h("div", { class: "callout warn" }, "Large graph: labels are hidden and the layout can be dense. Hover is not needed — pick a pair with the Source / Destination selectors."));
  if (t.provenance && Object.keys(t.provenance).length) parts.push(provenanceTable(t.provenance));
  else parts.push(h("p", { class: "muted small" }, "This topology carries all metrics in its source file (no estimates)."));
  parts.push(h("div", { class: "row" },
    h("button", { class: "primary", onclick: () => { state.tab = "compare"; renderTabWith(() => renderCompare(null, 12)); } }, "Compare 12 random pairs on this topology"),
    h("button", { onclick: () => { state.tab = "infer"; renderTab(); } }, "Recommend for the selected pair")));
  fill(content(), ...parts);
}

function renderTabWith(fn) {
  const tab = TABS[state.tab];
  document.getElementById("usecase").textContent = tab.usecase;
  document.getElementById("enhancement").textContent = tab.enhancement;
  for (const b of document.querySelectorAll("#tabs .tab")) b.classList.toggle("on", b.dataset.tab === state.tab);
  fn();
}

/* ---------------------------------------------------------------- wiring */

async function main() {
  for (const b of document.querySelectorAll("#tabs .tab")) {
    b.addEventListener("click", () => { state.tab = b.dataset.tab; renderTab(); });
  }
  document.getElementById("topology").addEventListener("change", (e) => loadTopology(e.target.value));
  for (const id of ["src", "dst"]) document.getElementById(id).addEventListener("change", () => { drawGraph(); renderTab(); });
  document.getElementById("color-by").addEventListener("change", drawGraph);
  try {
    await loadCatalog();
    await loadTopology("sample");
  } catch (err) {
    setStatus("Failed to start: " + err.message, true);
  }
}

main();
