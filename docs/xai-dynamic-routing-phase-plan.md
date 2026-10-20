# Phase plan and dependencies

**Project:** Explainable AI-Based Dynamic Routing Recommendation System  
**Code:** `projects/xai-dynamic-routing/`  
**Overview:** [xai-dynamic-routing-overview.md](xai-dynamic-routing-overview.md)

Security risk is a numeric link attribute (0–1). No exploit or attack-procedure work.

**Last updated:** see [phase-execution-status.md](phase-execution-status.md) (refresh that board before each commit).

Tick items when they are true in the repo. Do not start a later **critical-path** phase until the previous phase checklist is complete. P2 may start after P1 even if P3 is unfinished.

---

## 1. Phase graph

```mermaid
flowchart LR
  P0[P0 Scaffold]
  P1[P1 Topology and features]
  P2[P2 RIP and OSPF baselines]
  P3[P3 Labels and recommender]
  P4[P4 SHAP and LIME]
  P5[P5 Compare and evaluate]
  P6[P6 Dynamics]
  P7[P7 Heavier data and testbed]

  P0 --> P1
  P1 --> P2
  P1 --> P3
  P2 --> P5
  P3 --> P4
  P3 --> P5
  P4 --> P5
  P4 --> P6
  P5 --> P7
  P6 --> P7
```

**Critical path (first working system):** P0 → P1 → P3 → P4 → P5.

P2 can start as soon as P1 exists; it does **not** wait for the ML model. P6 needs P4 (new explanation each reroute). P7 is last.

| Milestone | After | Meaning | Done |
|-----------|--------|---------|------|
| M0 | P0 | Sample graph loads | [x] |
| M1 | P1 | Candidate paths + feature table | [x] |
| M2 | P2 | RIP path ≠ OSPF path on sample topo | [x] |
| **M3 (demo)** | **P4** | AI path + SHAP/LIME text and figure | [x] |
| M4 | P5 | RIP vs OSPF vs AI comparison table | [x] |
| M5 | P6–P7 | Time-varying routes and/or Topology Zoo | [x] |

---

## 2. Status

Canonical snapshot: [phase-execution-status.md](phase-execution-status.md). Do not let this table lag that board.

| Phase | Status | Effort | Checklist |
|-------|--------|--------|-----------|
| 0 Scaffold | **Done** | — | complete |
| 1 Topology + features | **Done** | — | complete |
| 2 Classical baselines | **Done** | — | complete |
| 3 Labels + recommender | **Done** | — | complete |
| 4 XAI | **Done** | — | complete |
| 5 Compare | **Done** | — | complete |
| 6 Dynamics | **Done** | — | complete (SHAP per reroute; LIME when installed) |
| 7 Datasets / Mininet | **Done** | — | complete; Mininet export generated, not run (needs Linux + root) |

### Standing rules (every phase)

- [x] Bind any local service to `127.0.0.1` (`configs/default.json`)
- [x] Treat `security_risk` as a number on the link, not as an attack to implement
- [x] Print lab-style traces (path, costs, top features) on CLI
- [x] Do not commit `data/raw/` dumps, large CAIDA files, or bulky `models/` weights (`.gitignore`; verified with `git status`)

---

## 3. Phase details, dependencies, and checklists

### Phase 0 — Scaffold

| | |
|--|--|
| **Depends on** | Repo + Title 4 brief |
| **Produces** | Folder tree, `requirements.txt`, `configs/default.json`, `data/samples/sample_topology.json`, `src/topology/load.py` |
| **Python** | `networkx` |
| **Blocks** | Everything else |

**Checklist**

- [x] `projects/xai-dynamic-routing/` matches overview section 12
- [x] `requirements.txt` lists networkx, pandas, numpy, scikit-learn, shap, lime, matplotlib
- [x] Sample topology JSON exists (8 nodes, QoS + `security_risk` on edges)
- [x] `load_graph` returns a NetworkX graph
- [x] Project README documents setup, run, and bind address
- [x] `.gitignore` covers `data/raw`, `models`, generated `outputs`

**Exit:** `python -c "from src.topology.load import load_graph; G = load_graph('data/samples/sample_topology.json'); print(G.number_of_nodes(), G.number_of_edges())"` prints `8 11`.

---

### Phase 1 — Topology + features

| | |
|--|--|
| **Depends on** | P0: `load_graph`, edge attributes on the sample JSON |
| **Produces** | `src/features/path_features.py` — k-candidate paths; hop count, sum/max delay, min bandwidth, max `security_risk`, mean congestion, etc. |
| **Python** | `networkx`, `pandas`, `numpy` |
| **Blocks** | P2, P3 (and thus P4–P5) |

**Checklist**

- [x] Read `k_candidate_paths` and `max_hops` from `configs/default.json`
- [x] Enumerate k candidate paths (Yen or hop-capped search) — `candidate_strategy`: hop-ordered and delay-ordered Yen, interleaved (`mixed`)
- [x] Path features include: hops, sum/max delay, min bandwidth, max `security_risk`, mean congestion, sum/max loss, mean energy, max utilization, max queue, min reliability
- [x] Invalid `src`/`dst` (missing node or no path) fails with a clear message
- [x] CLI or script prints a table of paths and feature vectors
- [x] Feature column names are documented (P4/P5 must reuse them) — [xai-dynamic-routing-methods.md](xai-dynamic-routing-methods.md) §3

**Exit:** given `R1` → `R8`, a table of candidate paths and numeric features prints.

---

### Phase 2 — RIP / OSPF baselines

| | |
|--|--|
| **Depends on** | P1 graph + edge costs (`delay`, `bandwidth`) |
| **Does not depend on** | ML model or SHAP |
| **Produces** | `src/routing/baselines.py` — hop-count SPF (RIP-like); Dijkstra on delay or `10^8/bandwidth` (OSPF-like) |
| **Python** | `networkx` |
| **Blocks** | P5 comparison columns for RIP/OSPF |

**Checklist**

- [x] RIP-like: Dijkstra with unit hop cost; print path and hop count
- [x] OSPF-like: Dijkstra on `delay` (or `10^8/bandwidth` via config `ospf_cost`)
- [x] Print chosen path and total cost (lab-style)
- [x] Same `src`/`dst` can yield different RIP vs OSPF paths on the sample graph
- [x] Disconnected pair reports no path

**Exit:** `R1` → `R8` shows two traces; paths differ at least once on the sample topology.

---

### Phase 3 — Labels + recommender

| | |
|--|--|
| **Depends on** | P1 feature table; a **label rule** (weighted QoS + security score, or argmin among k paths) |
| **Does not depend on** | P2 (baselines are for comparison, not for training labels unless you choose that) |
| **Produces** | `src/routing/recommender.py`, `scoring.py`, `dataset.py`, `scripts/train.py`, `scripts/infer.py`, weights in `models/` |
| **Python** | `scikit-learn` (Random Forest first); optional `xgboost` later |
| **Blocks** | P4, P5 (AI column), P6 |

**Checklist**

- [x] Document the scalar score (weights for delay, loss, congestion, `security_risk`, …)
- [x] Build a labeled table: each candidate path → score (or best-of-k class) — default label: realized rule cost over the next `horizon_steps` of a simulated traffic trace (F-020); `rule_snapshot` keeps the earlier same-snapshot label
- [x] Train Random Forest (sklearn) on path features + traffic-history features (F-010); skip RL
- [x] Black-box MLP baseline on the same rows/inputs/labels, never explained (F-009)
- [x] `scripts/train.py` writes a model under `models/`
- [x] `scripts/infer.py` prints recommended path for `src` `dst`
- [x] Held-out pairs: model picks a better-scoring path than hop-count more often than chance — 207 better / 348 tie / 46 worse over 601 held-out queries scored by realized future cost (sign test p = 7.2e-26); also reported vs min delay, snapshot rule, black-box MLP, and oracle
- [x] Recommended routes written to `outputs/routes/`

**Exit:** infer on `R1` `R8` prints a path; a model file exists; routes dump exists.

---

### Phase 4 — XAI

| | |
|--|--|
| **Depends on** | P3 fitted tree/linear model; P1 **same feature names** as training |
| **Produces** | `src/xai/explain.py`; SHAP (TreeExplainer) + LIME; files in `outputs/explanations/` and `outputs/figures/` |
| **Python** | `shap`, `lime`, `matplotlib` |
| **Blocks** | P5 explanation row; P6 per-step reason |

**Checklist**

- [x] SHAP TreeExplainer (or KernelExplainer if not a tree) on the trained model
- [x] LIME on the same instance (one path or one src–dst) — verified 2026-10-12 with `python scripts/infer.py --src R1 --dst R8 --explain` and `python scripts/run_tests.py` (`LimeTests` pass)
- [x] Print: path chosen; top features with signed importance (e.g. delay, `security_risk`)
- [x] Feature names in explanations match P1 columns
- [x] Save text/JSON under `outputs/explanations/`
- [x] Save at least one SHAP or LIME figure under `outputs/figures/`
- [x] `scripts/infer.py` (or a flag) prints explanation with the path

**Exit:** one recommendation includes a human-readable feature list plus a saved figure. **M3.**

---

### Phase 5 — Compare and evaluate

| | |
|--|--|
| **Depends on** | P2 + P3 + P4 (all three columns) |
| **Produces** | `src/evaluate/compare.py`, `scripts/compare.py` — delay, loss, max risk, hops |
| **Python** | `pandas`, `matplotlib` |
| **Blocks** | Report tables; P7 “vs classical IGP” story |

**Checklist**

- [x] Same `src`/`dst` (and same graph) for RIP, OSPF-like, and AI
- [x] Metrics: path delay, loss (sum or max), max `security_risk`, hop count
- [x] Include a short explanation snippet for the AI row
- [x] `scripts/compare.py` writes CSV and/or markdown
- [x] At least one comparison figure in `outputs/figures/`
- [x] Run on several pairs, not only `R1`–`R8`

**Exit:** table RIP vs OSPF vs AI is reproducible from one command. **M4.**

---

### Phase 6 — Dynamics (optional)

| | |
|--|--|
| **Depends on** | P3 + P4; `src/simulate/graph_sim.py` to mutate congestion/loss/risk over time |
| **Produces** | Time-step loop; path change + new SHAP each step |
| **Blocks** | “Dynamic” claim in the title |

**Checklist**

- [x] Each step updates at least congestion, loss, or `security_risk` on some edges — drift, scripted events, and optionally the trained-on traffic model (`"traffic": true`)
- [x] Re-run recommender every step, with each candidate's recent history
- [x] Print path; if it changes, print old vs new
- [x] New SHAP/LIME reason printed on change (and optionally every step) — SHAP + contrast vs previous path; LIME when installed
- [x] 10-step run on sample topology
- [x] At least one reroute occurs in the canned scenario

**Exit:** 10-step log with ≥1 reroute and a printed reason.

---

### Phase 7 — Heavier data / testbed (later)

| | |
|--|--|
| **Depends on** | P5 (evaluation harness); optionally P6 |
| **Produces** | Topology Zoo GML loader; SNDlib-like demand; Mininet/Packet Tracer only after the Python demo works |
| **External data** | Topology Zoo, SNDlib, CAIDA (large → `data/raw/`, gitignored) |

**Checklist**

- [x] M3 demo works on the sample graph first
- [x] Loader for Topology Zoo GML (or one exported topology) — `.gml` and `.graphml`; GÉANT 2012 and Abilene tested; SNDlib native loader too
- [x] Map or fill missing metrics (delay, risk) with documented defaults
- [x] `compare.py` runs on that topology
- [x] CAIDA/SNDlib files stay in `data/raw/` and are gitignored
- [x] Mininet / Packet Tracer only if a live demo is still required (bind `127.0.0.1`) — `scripts/export_mininet.py` generates a Mininet script (not run: needs Linux + root). `scripts/packet_tracer.py` generates PTBuilder build/AI-route scripts, IOS configs, and a tracert verifier, tested against a PT-API mock; not yet run inside Packet Tracer (F-021).

**Exit:** one non-toy topology produces a comparison table.

---

## 4. What can run in parallel

| Track A | Track B | Merge at |
|---------|---------|----------|
| P2 baselines | P3 train/infer | P5 |
| Report text (problem, gap) from overview | Coding P1–P4 | P5 figures |

Do **not** start P4 before P3. Do **not** start Mininet before M3.

---

## 5. File dependency order

```
src/config.py, src/errors.py                  [P0 fixes: validated config, clear errors]
src/topology/load.py                          [P0, validated]  zoo.py, sndlib.py [P7]
        ↓
src/features/path_features.py                 [P1]
        ↓
        ├─→ src/routing/baselines.py          [P2]
        └─→ src/routing/recommender.py        [P3]
                    ↓
            src/xai/explain.py                [P4]
                    ↓
        src/evaluate/compare.py               [P5]  ← also needs baselines
                    ↓
        src/simulate/graph_sim.py, runner.py  [P6]

scripts/features.py → P1      scripts/baselines.py → P2
scripts/train.py  → P3        scripts/infer.py → P3, P4 (--explain)
scripts/compare.py → P5       scripts/simulate.py → P6
scripts/fetch_topology_zoo.py, export_mininet.py → P7
scripts/demo.py (all), scripts/run_tests.py (tests)
```

---

## 6. Python / tool dependencies

| Package | First needed | Role |
|---------|----------------|------|
| `networkx` | P0 | Graph, Dijkstra, k-paths |
| `numpy`, `pandas` | P1 | Feature tables |
| `scikit-learn` | P3 | Random Forest / metrics |
| `shap` | P4 | Global/local feature attributions |
| `lime` | P4 | Local surrogate explanation |
| `matplotlib` | P4 | Explanation and compare plots |
| `xgboost` | Optional P3 | Stronger tree model + TreeSHAP |
| NS-3 / Mininet / Packet Tracer | P7 only | Optional live demo |

Install from `projects/xai-dynamic-routing/requirements.txt`. Bind any later UI to `127.0.0.1` (`configs/default.json`).

---

## 7. Data dependencies

| Data | Phase | Notes |
|------|--------|--------|
| `data/samples/sample_topology.json` | P0–P6 | 8 nodes, 11 edges; enough for M3 |
| Synthetic labels from score function | P3 | No CAIDA required to train v1 |
| Topology Zoo GML | P7 | Real topologies |
| SNDlib | P7 | Traffic instances |
| CAIDA | P7 | Traffic stats; do not commit dumps |

---

## 8. Implementation order (done) and what remains

P1 → P2 → P3 → P4 → P5 → P6 → P7 are implemented and verified (see [phase-execution-status.md](phase-execution-status.md)). Remaining:

1. ~~Install `lime` and verify the LIME checklist item~~ — done 2026-10-12 (F-018).
2. Optional: run the exported Mininet script on a Linux host.
3. Run the Packet Tracer build script inside PT and `verify` a tracert (F-021).

When a phase is finished: tick its checklist, set Status to Done, and tick the matching milestone in section 1.
