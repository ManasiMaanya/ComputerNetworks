# Webpage evolution by phase

**Demo URL (when Docker is up):** `http://127.0.0.1:8765/`  
**API usage and example JSON:** [api.md](api.md)  
**Ops (install, start, debug, test):** [backend-docker.md](backend-docker.md)  
**Routing phases:** [../xai-dynamic-routing-phase-plan.md](../xai-dynamic-routing-phase-plan.md)

The page is a **lab demo**, not a production NOC. Each software phase must add a **use-case panel** (what an operator would do) and an **enhancement panel** (what RIP/OSPF cannot do yet, or what this phase adds). Hide or mark “not built” for future tabs so the UI never pretends a phase is done.

Bind stays **`127.0.0.1:8765`** on the host. See backend-docker.md for why the container listens on `0.0.0.0` internally.

---

## Product story

| Role | Goal on the webpage |
|------|---------------------|
| Student / viva | Show topology, paths, and *why* the AI picked a path |
| Operator (story) | Inspect QoS + security risk, compare with RIP/OSPF, see reroutes |

Do **not** add attack simulators, exploit UIs, or scans. Security is a **numeric link attribute**.

---

## UI map (tabs grow over time)

| Tab | First appears | Locked until |
|-----|----------------|--------------|
| Topology | P0 | — |
| Path features | P1 | P1 code |
| RIP / OSPF | P2 | P2 code |
| AI recommend | P3 | P3 model |
| Explanation | P4 | P4 SHAP/LIME |
| Compare | P5 | P5 compare |
| Timeline | P6 | P6 sim |
| Larger topo | P7 | P7 loader |

---

## Phase 0 — Topology (current target)

**Use-case.** Open the demo. See R1–R8 as a graph. Click a link to read delay, bandwidth, congestion, loss, energy, `security_risk`, utilization, queue, reliability. Confirms the lab “network” loaded.

**Enhancement (message only).** RIP/OSPF/AI tabs show “comes in later phases.” Operator cannot yet choose a path.

**Backend.** `GET /health`, `GET /api/topology` (nodes, edges, attributes). Static page from `/`.

**Done when.** Browser on `http://127.0.0.1:8765/` shows 8 nodes / 11 edges; health script returns OK.

---

## Phase 1 — Path features

**Use-case.** Pick source and destination (default R1 → R8). Table of k candidate paths and feature columns (hops, sum delay, max risk, …).

**Enhancement.** RIP only shows hop count; this table shows **multi-metric** vectors before any AI.

**Backend.** `GET /api/paths?src=&dst=` → list of paths + features. Reuse `path_features.py`.

**Page.** Enable **Path features** tab; draw selected path on the graph (highlight edges).

---

## Phase 2 — RIP vs OSPF

**Use-case.** Same src/dst. Two traces: RIP-like (hops) and OSPF-like (Dijkstra on delay or `10^8/bw`). Print path and cost like a lab record.

**Enhancement.** Side-by-side: *same hop count, different delay* when it happens on the sample graph.

**Backend.** `GET /api/baselines?src=&dst=`.

**Page.** Two colored paths on the graph + cost lines. If paths are identical, show a note (honest demo).

---

## Phase 3 — AI recommendation

**Use-case.** After train, **Recommend** loads the model and highlights the AI path. Download/link to `outputs/routes/` optional.

**Enhancement.** Path can differ from RIP and OSPF because of the **score** (QoS + security), not a single IGP metric.

**Backend.** `POST /api/infer` `{src, dst}` → path + score. 503 if no model file.

**Page.** Third color on the graph. Banner if model missing: run `train.py` first.

---

## Phase 4 — Explanation (M3 demo)

**Use-case.** With the AI path, show **top features** (SHAP bars) and a LIME sentence. Operator answers “why this path?”

**Enhancement.** Classical IGPs have no feature-importance panel. This is the title’s XAI requirement on the webpage.

**Backend.** `GET /api/explain?src=&dst=` → attributions + optional figure URL from `outputs/figures/`.

**Page.** **Explanation** tab: bar chart (canvas or static PNG) + text. Must use **same feature names** as P1.

---

## Phase 5 — Compare

**Use-case.** One table: RIP vs OSPF vs AI for several pairs (not only R1–R8). Metrics: delay, loss, max risk, hops. AI row includes a short explanation snippet.

**Enhancement.** Report-ready screenshot: intelligent + **transparent** vs hop-count/SPF.

**Backend.** `GET /api/compare` → JSON/CSV same as `scripts/compare.py`.

**Page.** Table + one chart. Export button optional.

---

## Phase 6 — Dynamic reroute

**Use-case.** Play 10 time steps. Congestion/loss/risk on some edges change. Path highlight **moves**; on change, show new SHAP line.

**Enhancement.** Static OSPF cost does not tell this story; the page shows **adaptation**.

**Backend.** `POST /api/simulate/step` or `GET /api/simulate?steps=10`.

**Page.** **Timeline** slider + play. Do not imply packet attacks.

---

## Phase 7 — Larger topology

**Use-case.** Load a Topology Zoo (or documented subset). Run compare on one non-toy graph.

**Enhancement.** “Not just the 8-node lab.”

**Backend.** `POST /api/topology/upload` or query param `name=`. Files stay in `data/raw/` (gitignored).

**Page.** Dropdown of loaded graphs; warn if layout is messy (large graphs).

---

## Use-case vs enhancement (summary)

| Phase | Use-case on the page | Enhancement vs RIP/OSPF |
|-------|----------------------|-------------------------|
| 0 | See the network and link metrics | Honesty: routing not implemented yet |
| 1 | Inspect candidate path vectors | Multi-metric, not hop-only |
| 2 | Lab traces for two IGPs | Visual difference when costs disagree |
| 3 | One recommended path | Learned multi-criteria path |
| 4 | Why the model chose it | Explanations IGPs do not give |
| 5 | One comparison table | Viva/report demo |
| 6 | Path changes over time | Dynamic in the title |
| 7 | Bigger map | Scale beyond the sample |

---

## Implementation rule

When a phase is coded:

1. Add/extend API as in this file.  
2. Unlock the matching tab; do not fake data.  
3. Add a row to [../execution-plan.md](../execution-plan.md) and a check in [backend-docker.md](backend-docker.md) test section.  
4. Update [../phase-execution-status.md](../phase-execution-status.md) before commit.
