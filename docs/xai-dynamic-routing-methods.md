# Methods and reference: XAI dynamic routing

Technical reference for `projects/xai-dynamic-routing/`. It covers what each phase computes, the units and aggregation rules, how labels and the model are built, what SHAP and LIME explain, and the limits of each result. Commands are in [execution-plan.md](execution-plan.md). Status and measured results are in [phase-execution-status.md](phase-execution-status.md).

---

## 1. Architecture

```
configs/default.json ──► src/config.py (validated config, project-root path resolution)
data/samples/*.json  ──► src/topology/load.py      JSON loader + metric validation      [P0]
data/raw/*.gml|graphml ► src/topology/zoo.py       Topology Zoo import + provenance     [P7]
data/raw/*.txt       ──► src/topology/sndlib.py    SNDlib native import + demands       [P7]
data/raw/sndlib/traffic-matrices/*  ──► sndlib.py::load_demand_matrix  real traffic [P7]
                          │
                          ▼
              src/features/path_features.py        candidates + 12 path features        [P1]
              src/features/history.py              + 6 traffic-history features (F-010) [P3]
              src/simulate/traffic.py              traffic model: labels + scenarios    [P3/P6]
                          │
          ┌───────────────┼──────────────────────────────┐
          ▼               ▼                              ▼
 src/routing/baselines.py  src/routing/scoring.py   src/routing/dataset.py
 RIP-like, OSPF-like [P2]  rule cost (objective)[P3] outcome labels, group+time split [P3]
 src/routing/qrouting.py
 Q-routing baseline [P5]
          │               └──────────────┬───────────────┘
          │                              ▼
          │               src/routing/recommender.py  Random Forest + black-box MLP, eval [P3]
          │                              │
          │                              ▼
          │               src/xai/explain.py           SHAP + LIME, JSON, figures      [P4]
          ▼                              │
 src/evaluate/compare.py ◄───────────────┤             RIP vs OSPF vs Q-routing vs AI   [P5]
                                         ▼
 src/simulate/graph_sim.py + runner.py                 time steps, reroutes            [P6]
 src/simulate/real_traffic.py          real-traffic-driven steps, real_traffic_dir [P6/P7]
 src/simulate/mininet_export.py                        Mininet script export           [P7]
 src/packet_tracer/                                    Packet Tracer build + verify    [P7]
```

Scripts in `scripts/` are thin CLIs over these modules. Every script adds the project root to `sys.path`, resolves relative paths against the project root, and works from any working directory. Package code uses relative imports only. Expected errors (`src/errors.py`) print as one `error: ...` line with exit code 2, never a traceback.

Python: 3.12 is tested (3.10+ is required for the type syntax). Dependencies: `requirements.txt`.

---

## 2. Configuration (`configs/default.json`)

| Key | Default | Meaning |
|-----|---------|---------|
| `bind`, `port` | `127.0.0.1`, `8765` | Web demo bind (P0, unchanged) |
| `sample_topology` | `data/samples/sample_topology.json` | Default graph |
| `k_candidate_paths` | 5 | Max candidates per pair |
| `max_hops` | 8 | Max links per candidate |
| `candidate_strategy` | `mixed` | `hops`, `delay`, or `mixed` (§3.1) |
| `ospf_cost` | `delay` | `delay` or `inverse_bandwidth` |
| `ospf_reference_bandwidth_bps` | 1e8 | Reference for `inverse_bandwidth` |
| `scoring.weights` / `reference` / `hard_constraints` | see file | Label rule (§4) |
| `training.labels` | `future_outcome` | `future_outcome` (realized cost over the next `horizon_steps`) or `rule_snapshot` (rule cost of the same snapshot) (§5) |
| `training.trace_steps`, `decision_stride` | 300, 2 | Sample-topology traffic trace length and decision spacing |
| `training.synthetic_trace_steps`, `synthetic_decision_stride` | 24, 4 | Same, per synthetic graph |
| `training.history_steps`, `horizon_steps` | 5, 5 | History window (inputs) and label horizon |
| `training.test_time_fraction` | 0.3 | Held-out last part of every trace |
| `training.blackbox_hidden_layers`, `blackbox_max_iter` | [64, 32], 500 | Black-box MLP baseline |
| `training.*` (other) | seed 42, 150 snapshots (rule_snapshot only), 80 synthetic graphs, 150 trees | Dataset and model (§5) |
| `traffic.*` | see file | Traffic model: per-metric mean reversion and noise, burst/incident probability and size (§5.1) |
| `xai.top_k`, `lime_num_samples`, `seed` | 5, 2000, 42 | Explanation output |
| `paths.*` | `models`, `outputs`, `data/processed`, `data/raw` | Artifact folders |
| `compare.pairs`, `random_pairs` | 7 sample pairs, 12 | Comparison pairs (§7) |
| `simulation.scenario` | `configs/scenarios/sample_incident.json` | Default P6 scenario |
| `simulation.hysteresis_margin` | 0.03 | P6 anti-flapping: hold the previous path unless the new pick is this much cheaper (relative); 0 disables it (§8) |
| `evaluation.explanation`, `label_sensitivity`, `attacks` | see file | Evaluation defaults: SHAP repeats/top-k, LIME and RF seed counts; Dirichlet draws/seed; blackhole/compromised metric values (§11) |
| `qrouting.train_steps`, `learning_rate`, `discount`, `seed` | 60, 0.7, 1.0, 11 | Q-routing baseline training (§7) |
| `topology_zoo.*` | see file | Import defaults (§9) |

`src/config.py` validates every key on load (types, ranges, allowed values) and names the bad key in the error. Changing `scoring` after training makes the saved model stale. `infer.py` and `compare.py` detect this from a fingerprint in `models/feature_schema.json` and print a warning.

---

## 3. Phase 1: candidates and path features

### 3.1 Candidate paths

`candidate_paths(graph, src, dst, k, max_hops, strategy)` returns up to `k` distinct simple paths with at most `max_hops` links:

| Strategy | Rule |
|----------|------|
| `hops` | Yen's k-shortest simple paths by hop count (`networkx.shortest_simple_paths`, unweighted). Stops at the first path longer than `max_hops`. |
| `delay` | Yen by summed `delay`. Paths over `max_hops` are skipped; at most `20·k` paths are inspected. |
| `mixed` (default) | Alternates the hop-ordered and delay-ordered lists, dropping duplicates, until `k` paths. |

`mixed` is the default because pure hop-ordered Yen with k=5 can exclude the lowest-delay path. On the sample graph, R2→R7's OSPF path R2-R4-R6-R8-R7 was not a candidate, so the AI could not choose it. With `mixed`, the fewest-hop path and the lowest-delay path are always both candidates.

Errors: an unknown node or `src == dst` raises `RoutingError`. Disconnected nodes, or no path within `max_hops`, raise `NoPathError` with the reason.

### 3.2 Features (canonical order, `FEATURE_COLUMNS`)

| # | Column | Unit | Aggregation over the path's links |
|---|--------|------|-----------------------------------|
| 1 | `hops` | links | count |
| 2 | `sum_delay` | ms | sum (end-to-end latency, additive) |
| 3 | `max_delay` | ms | max (slowest link) |
| 4 | `min_bandwidth` | Mbps | min (bottleneck capacity) |
| 5 | `max_security_risk` | score 0–1 | max (weakest link dominates) |
| 6 | `mean_congestion` | fraction 0–1 | arithmetic mean |
| 7 | `sum_loss` | fraction | sum: first-order (additive) approximation of end-to-end loss |
| 8 | `max_loss` | fraction 0–1 | max |
| 9 | `mean_energy` | relative units | arithmetic mean |
| 10 | `max_utilization` | fraction 0–1 | max |
| 11 | `max_queue` | packets | max |
| 12 | `min_reliability` | probability 0–1 | min (least reliable link) |

**Loss.** `sum_loss` is additive (Σ lᵢ) and is an upper bound on the probabilistic end-to-end loss `1 − Π(1 − lᵢ)`. The two agree to first order for small loss. The model uses `sum_loss`. Reports also show the probabilistic `path_loss`.

**Reliability.** `min_reliability` is the bottleneck link. Reports also show `path_reliability = Π rᵢ`, the probability that all links stay up, assuming independence.

**Missing values.** No defaults are invented at feature time. Every edge must carry all nine metrics within their ranges (§3.3), or loading or feature extraction fails, naming the edge. Defaults exist only in the explicit import step for external datasets (§9), where each one is labelled.

### 3.3 Edge metric ranges (`METRIC_SPEC`)

| Metric | Valid range | Unit |
|--------|-------------|------|
| delay | [0, ∞) | ms |
| bandwidth | (0, ∞) | Mbps |
| congestion, utilization, security_risk | [0, 1] | fraction / score |
| loss | [0, 1) | probability |
| energy | [0, ∞) | relative |
| queue | [0, ∞) | packets |
| reliability | (0, 1] | probability |

Booleans, strings, NaN, and ±inf are rejected. Zero bandwidth is rejected, so `10^8/bandwidth` is always defined. Unknown extra keys on nodes and edges are kept unchanged.

---

## 4. Phase 3: scoring rule (objective)

Each candidate snapshot gets a scalar **rule cost**. Lower is better. The rule defines what a
good path is; with the default `future_outcome` labels the model is trained to predict the rule
cost a path will *experience* next, not to reproduce the rule on its own inputs (§5).

```
cost = Σ wᵢ·termᵢ + penalty · [max_security_risk > risk_limit]
```

| Term | Formula | Weight |
|------|---------|--------|
| delay | `sum_delay / 50 ms` | 0.25 |
| security_risk | `max_security_risk` | 0.20 |
| loss | `sum_loss / 0.10` | 0.15 |
| congestion | `mean_congestion` | 0.15 |
| bandwidth | `max(0, 1 − min_bandwidth / 100 Mbps)` | 0.08 |
| reliability | `(1 − min_reliability) / 0.20` | 0.05 |
| utilization | `max_utilization` | 0.05 |
| queue | `max_queue / 15` | 0.03 |
| energy | `mean_energy / 1.5` | 0.02 |
| hops | `hops / 8` | 0.02 |

Hard constraint: if `max_security_risk > 0.65`, add `penalty = 1.0`. This is larger than any realistic sum of the other terms, so paths over the limit always rank below compliant ones but stay comparable to each other.

**Trade-offs.** The weights encode a policy: latency and link risk first, then loss and congestion, with capacity, reliability, and load as tie-breakers. They are not an objective optimum. A different operator policy (for example energy-first) is a different weight vector in config. The reference scales map each term to roughly 0–1 on the sample data, so weights are comparable. Because of the risk penalty step, `max_security_risk` explains most of the label variance. This is visible in the model's impurity importances (§5).

---

## 5. Phase 3: dataset, model, evaluation

### 5.1 Traffic model (`src/simulate/traffic.py`)

Three edge metrics change over time: congestion, loss, security_risk (all others are static).
Each step, for every edge and dynamic metric x with baseline mu (its value in the input graph):

```
x <- x + reversion * (mu - x) + noise * N(0, 1)   [+ burst]      then clamped to METRIC_SPEC
```

With probability `burst_prob` an edge gets a congestion burst (congestion and loss jump together
by `burst_size` × U(0.5, 1.5)); with probability `incident_prob` a security incident
(security_risk jumps by `incident_size` × U(0.5, 1.5)). Mean reversion makes both transient
(incidents decay more slowly), which is why recent history is informative. The parameters are a
documented assumption, not fitted to measured traffic.

### 5.2 Labels (`training.labels`)

- **`future_outcome` (default, F-020).** One trace of `trace_steps` is simulated on the sample
  topology (seed `training.seed`) and one of `synthetic_trace_steps` on each synthetic graph. At
  each decision time t, a candidate's inputs are its current features plus a summary of its last
  `history_steps` snapshots (`MODEL_COLUMNS`, §5.3), and its label (`target`) is the mean rule
  cost it actually experiences over t+1..t+H (H = `horizon_steps`). The label is not a function of
  the inputs, so the model must forecast. Candidate sets are enumerated once per pair on the t=0
  graph (they are ranked by hops and delay, which the traffic model does not change).
- **`rule_snapshot`.** The earlier scheme: 150 perturbed sample snapshots (every metric scaled by
  `exp(N(0, 0.35))`) plus synthetic graphs, label = rule cost of the same snapshot. The model can
  only imitate the rule; kept for comparison.

Synthetic graphs (both modes): 80 connected Watts–Strogatz graphs with 8–24 nodes, metrics
sampled with loose correlations (loss and utilization rise with congestion), 15 random pairs each.
They broaden feature ranges for imported topologies.

Each row also keeps `rule_cost` (the snapshot rule at t) and realized outcomes over the horizon
(`future_cost`, `future_sum_loss`, `future_max_security_risk`, `future_mean_congestion`).
Default size: 44,160 rows, 8,832 queries. Path features over a trace are computed in one
vectorized pass (`TraceTensor`), checked against `extract_features` in the tests.

### 5.3 History features (`src/features/history.py`, F-010)

`hist_mean_*` / `hist_max_*` of `mean_congestion`, `sum_loss`, and `max_security_risk` over the
last `history_steps` snapshots. With no history (a one-off query on a static topology) the window
is the current snapshot alone, i.e. current conditions are treated as the steady state.

### 5.4 Leakage control

Rows carry a `group` (unordered sample pair `R1|R8`, shared by both directions and all times; or
one whole synthetic graph). Groups are split train/test within each family (25 % test). In
`future_outcome` mode rows also carry a `period`: decision times are drawn separately for the
training period (t + H < t_split, so every training label window ends before the held-out period)
and the held-out period (t ≥ t_split, the last 30 % of each trace). Training rows = training
groups × training period; test rows = test groups × held-out period. Cross-validation on the
training part uses `GroupKFold`.

### 5.5 Models

- **Explained recommender:** `RandomForestRegressor` (150 trees, `min_samples_leaf=5`,
  `random_state=42`) regresses `target` from the 18 `MODEL_COLUMNS`. Training runs in parallel;
  prediction runs single-threaded so results are bit-identical across runs (F-016).
- **Black-box baseline (F-009):** `StandardScaler` + `MLPRegressor` (64-32 hidden units, early
  stopping) on exactly the same rows, inputs, and target. It is never explained; it measures what
  explainability costs in accuracy, if anything. Saved as `models/route_cost_mlp.joblib`.

**Selection.** Score every candidate, pick the lowest predicted cost, then break ties by fewer
hops, then lower candidate index. A model can only ever return one of the enumerated candidates.

### 5.6 Evaluation (held-out queries; `models/training_report.json`)

Every method's pick is scored by the true label (realized future cost):

- **hop count** (RIP-like pick), **min delay** (OSPF-like pick), **snapshot rule** (lowest rule
  cost on the current snapshot — the natural non-learning competitor; under `rule_snapshot` labels
  it is the oracle), **black-box MLP**, **explained RF**, and **oracle** (best in hindsight).
- Per method: top-1 (picked the best path in hindsight), mean regret (true cost minus the
  oracle's), mean true cost. Head-to-head counts vs hop count (with a one-sided sign test), vs
  min delay, vs the snapshot rule, and vs the black-box model.

Measured numbers are in the status board. They are results on a simulated traffic model, not
field measurements of a real network.

## 6. Phase 4: explanations

**Explained output.** The Random Forest's predicted path cost for the recommended candidate (lower is better) — with `future_outcome` labels, the cost it expects the path to incur next. This is a single regression output, not a class probability. Inputs are the 18 `MODEL_COLUMNS`, so explanations can cite history (e.g. R1→R8 beats its runner-up mostly on `hist_mean_loss`, 0.06 vs 0.085). Only the Random Forest is explained; asking to explain the black-box MLP raises an error by design.

- **SHAP** (`shap.TreeExplainer`, tree_path_dependent). `base_value + Σ contributions = predicted cost`; additivity error is checked and saved (~1e-15). A negative contribution lowers cost and argues **for** the path; a positive one argues **against** it.
- **Contrast.** `SHAP(chosen) − SHAP(other)` per feature sums exactly to the predicted-cost gap. "Other" is the runner-up for a single recommendation, or the previous path after a reroute (P6). It answers "why this path and not that one".
- **LIME** (`LimeTabularExplainer`, regression, quartile discretisation, seeded). It explains the same instance, using training-feature background rows saved in `models/xai_background.csv`. The prediction function receives exactly `FEATURE_COLUMNS` in order. Its weights are a local linear surrogate's coefficients on discretised conditions (e.g. `max_security_risk <= 0.31`), with the same sign meaning. Its surrogate R² is reported. LIME is optional: without the `lime` package the run records `available: false` with the install command and continues with SHAP.

**Scope.** Explanations describe the model, which is a learned surrogate of the configured scoring rule. They do not show causation in the network or prove a route globally optimal. Section 11 measures how faithful, stable and method-independent these explanations are.

Outputs: `outputs/explanations/explain_<topology>_<src>_<dst>.json`, `outputs/figures/shap_<...>.png` (local SHAP plus contrast panel), and `outputs/figures/lime_<...>.png` when LIME is installed.

---

## 7. Phase 5: comparison

For each pair, on one graph object (same snapshot):

- **RIP**: Dijkstra with unit link cost. Cost = hops.
- **OSPF**: Dijkstra on `ospf_cost`. `--ospf-cost inverse_bandwidth` overrides the config for real topologies, where delays are defaults.
- **Q-ROUTE** (`src/routing/qrouting.py`): a classical, traffic-reactive baseline from the
  literature (Boyan & Littman, 1994), included so the comparison has "an existing AI routing
  method" alongside the project's own model, per the course brief. Every node keeps a table
  estimating delivery cost to each destination via each neighbour and greedily forwards to the
  cheapest; cost = `delay_ms * (1 + congestion)`, since this project's traffic model only varies
  congestion/loss/security_risk (delay is static — §5.1), so a pure-delay Q-routing would be
  identical to static OSPF. The table is trained once per topology, offline, by replaying
  `generate_trace` with TD(0) backups (`qrouting.train_steps/learning_rate/discount/seed`) —
  matching RIP/OSPF's per-graph, non-persisted pattern rather than the AI models' saved artifacts.
  Included whenever `scripts/compare.py` / the web demo's `/api/compare` run (always); omitted from
  a `compare_pair`/`run_comparison` call that passes no `qmodel`.
- **AI**: the recommender's pick. Cost = predicted cost. Includes a SHAP snippet.
- **AI-BB**: the black-box MLP's pick (when `models/route_cost_mlp.joblib` exists). No explanation.

Both AI methods see the snapshot without traffic history (steady state). The history-aware
comparison on simulated futures is the held-out evaluation (§5.6).

Each method's path is re-measured with the P1 aggregation: `hops`, `sum_delay`, `sum_loss`, `path_loss`, `max_security_risk`, `mean_congestion`, `min_bandwidth`, `min_reliability`, and `rule_cost`. `rule_cost` is the AI's own objective, so it favours the AI by construction and is shown for reference only. The four method-neutral metrics are delay, loss, max risk, and hops.

A pair where a method fails is kept as a row with `status` = `no_path` (disconnected, or over hop limit) or `error` (e.g. unknown node). The summary averages only pairs where every method present in the run succeeded, and states that count.

Pair selection: the config list for the sample graph, `--pairs`, `--all-pairs`, seeded `--random-pairs`, or the largest SNDlib demands.

Outputs: `outputs/reports/compare_<topology>[_ospf-<cost>].csv` and `.md`, and `outputs/figures/compare_<...>.png`.

---

## 8. Phase 6: dynamic simulation

Scenario JSON (`configs/scenarios/*.json`): `name`, `src`, `dst`, `steps`, `seed`, `drift {metrics, sigma}`, `events[{step, edge, set{}, add{}, label}]`, and optional `"traffic": true` (run the §5.1 traffic model each step — the dynamics the default model is trained on) **or** `"real_traffic_dir"` (step through real measured traffic instead — below; mutually exclusive with `"traffic": true`).

At each step t (0..steps−1):

1. If the scenario sets `real_traffic_dir`: replace utilization/congestion/loss/queue outright with that step's real traffic snapshot (below) — every step, including t=0.
2. Else, for t > 0, add seeded `N(0, sigma)` drift to the drift metrics on every edge.
3. Else, for t > 0 with `"traffic": true`, advance the traffic model one step.
4. Apply that step's scripted events (on top of whichever of 1-3 ran).
5. Clip values to valid ranges and re-validate the graph.
6. Re-run the recommender with each candidate's recent history (the previous `history_steps` − 1 snapshots of this run).

The input graph is deep-copied and never modified. The same scenario and seed always give the same run (tested).

On step 0 and on every reroute, the runner:

- prints old → new path, and the net metric changes on both paths' edges with their cause (drift or event label);
- prints how the previous path's features changed;
- writes a fresh SHAP (and LIME) explanation contrasting the new path with the previous one.

The shipped `sample_incident` scenario (R1→R8, 10 steps):

- sigma 0.01 drift on congestion, loss, and risk;
- link R4-R6, on the initial best path, takes congestion 0.85 and loss 0.07 at t=3;
- R4-R6 risk rises to 0.8 at t=5;
- R4-R6 recovers at t=8.

The scenario changes only metrics. The model decides whether and where to reroute; no path is scripted. With the history-aware model it reroutes at t=5 (when R4-R6 is flagged high-risk) and back at t=8; it does not react to the single-step congestion spike at t=3, because the 5-step history smooths it.

The `traffic_dynamics` scenario runs R2→R5 for 30 steps under the traffic model with no scripted events. R2→R5's two best candidates are close, so ordinary dynamics flip the recommendation: 11 reroutes in 30 steps at `hysteresis_margin=0`, several back-and-forth (route flapping). The default `hysteresis_margin=0.03` holds the previous path unless the model's new pick is at least 3% (relative) cheaper, which cuts this to 7 reroutes without delaying the genuine, large degradation in `sample_incident` (still rerouted immediately there). The margin is applied only in the P6 runner (`run_simulation`), not in `RouteRecommender.recommend` itself, so a one-off query (`infer.py`, `/api/infer`) is unaffected.

Outputs: `outputs/simulations/<name>/history.{csv,json}`, `timeline.png`, and `explain_<name>_stepNN.json` / `shap_<name>_stepNN.png` per explained step.

### Real traffic (`real_traffic_dir`, `src/simulate/real_traffic.py`; see SNDlib below for the data)

`configs/scenarios/abilene_real_traffic.json` demos a scenario driven by real measured traffic instead of the §5.1 synthetic model: SNVAng→NYCMng on Internet2's real Abilene network, 48 steps, each one a real 5-minute demand matrix (Zhang et al., via SNDlib).

Per step: every directed demand with non-zero traffic is routed via OSPF(delay) over the static topology (`ospf_route_from_config`); both directions of a pair add their Mbit/s load onto the same undirected edge (the topology is undirected, demands are not). Per edge: `utilization = clip(load_mbps / bandwidth_mbps)`, `congestion = clip(utilization**1.5)`, `loss`/`queue` reuse the Topology Zoo `synthetic` formulas exactly (§9's table below: `0.0005 + 0.05*congestion**2`, `round(25*congestion)`) — reused rather than reinvented, with one deliberate difference: **no noise term on congestion**, because the real matrix already supplies real variation step to step. delay/bandwidth/reliability/energy/security_risk stay at the base topology's values; the demand data carries no signal for any of them. An edge with zero routed load for that step gets congestion/utilization/queue 0 (not a leftover value from the previous step or the base topology), so every step's derived metrics come from that step's real load alone.

This is wired into P6 (`GraphSimulator`/`run_simulation`/`scripts/simulate.py`/the web demo's `/api/simulate`) only, not P3 training — see the SNDlib section below for why.

---

## 9. Phase 7: real topologies and external data

### Topology Zoo (`.gml` from topology-zoo.org or its authors' mirror, `.graphml` from github.com/sk2/topologyzoo)

`scripts/fetch_topology_zoo.py` tries topology-zoo.org, then the Zoo authors' long-term data store
(github.com/mroughan/InternetTopologyZoo, same GML export with coordinates), then the GraphML
sources. The data is CC BY 4.0; cite Knight et al., "The Internet Topology Zoo", IEEE JSAC 29(9),
2011. With the mirror's GML, GÉANT 2012 gets distance-based delay on 58 of 61 links (F-017).


The files describe structure: nodes, links, and sometimes coordinates and link speeds. **They contain no measurements of delay, loss, congestion, risk, energy, utilization, queue, or reliability.** Every imported edge records `metric_source[metric]` as one of:

| Kind | Used for | Rule |
|------|----------|------|
| `documented` | bandwidth | `LinkSpeedRaw`/1e6, or `LinkSpeed`×units, or parsed from the link label (`10 Gbps`, `1 GB/s` read as Gbit, `OC-192c` = 192×51.84, ranges → lower bound) |
| `estimated` | delay | Great-circle distance / 200 km/ms + 0.5 ms per hop. Only when both ends have latitude/longitude. |
| `synthetic` | the 7 QoS/risk metrics | Seeded draws: utilization U(0.1, 0.85); congestion ≈ utilization^1.5 + noise; loss = 0.0005 + 0.05·congestion²; queue = 25·congestion; risk ~ Beta(1.5, 5); energy = 0.8 + 0.4·utilization; reliability ∈ [0.949, 0.999] |
| `default` | any | Configured constant when nothing usable exists (`topology_zoo.default_*`, or `missing_metric_policy = "default"`) |

Parallel links are collapsed to the highest-capacity link (count kept in `parallel_links`). Duplicate labels get the Zoo id appended. Isolated nodes are kept, and comparison reports them as `no_path`. `compare.py` prints and saves the provenance counts.

The GitHub GraphML sources have no coordinates, so delay is `default` (5 ms on every link) for those files. Delay-based OSPF then ranks paths by hop count, so use `--ospf-cost inverse_bandwidth` to route on documented capacity. Results on these graphs come from structure plus labelled synthetic metrics. They are not observations of the real networks.

### SNDlib (native `.txt`)

Parses `NODES` (coordinates), `LINKS` (pre-installed capacity, else largest module capacity, treated as Mbps), and `DEMANDS` (sorted largest first; used as comparison pairs). Other metrics follow the Zoo policy. Keep instances in `data/raw/sndlib/networks/`.

SNDlib dynamic traffic matrices (Abilene: 5-minute intervals over 6 months; GÉANT: 15-minute intervals over 4 months; from sndlib.put.poznan.pl) are a separate download per network: one native-format file per time interval, sharing the base network's `NODES` but with an empty-but-present `LINKS ( )` and a `DEMANDS` section listing only that interval's non-negligible demands (SNDlib rounds and *drops* near-zero demands from the file entirely rather than writing `0.0` — `load_demand_matrix` treats an absent pair as real-measured zero, not missing data). `src/topology/sndlib.py::load_demand_matrix` parses one such file; `scripts/fetch_sndlib_traffic.py` downloads a network's full archive and extracts the demand-matrix files (chronologically-first `--limit` by default, since e.g. Abilene's archive has 48,096 of them). The "Real traffic" subsection of §8 above is what consumes them.

This real traffic data drives **P6 simulation only, not P3 training**. P3's `sample_topology` + 80 synthetic graphs under the §5.1 traffic model is a deliberate design choice for generalization — training on one real network's traffic risks narrowing the model to that network's load pattern and destabilizing the already-measured P3 held-out results (§ Measured results in the status board) for no benefit to P6's actual goal, which is showing the *recommender* react to real measured load, not retraining it on that one network.

### CAIDA

Not supported. CAIDA traces are packet- and flow-level traffic data, not link-metric topologies. Using them would need a separate aggregation step (per-link utilization or loss estimates) and their access agreement. That is outside this version.

Raw files stay in `data/raw/` (gitignored). Check each dataset's terms before redistributing.

### Mininet

`scripts/export_mininet.py` writes `outputs/mininet/<topology>_mininet.py`:

- one OVS bridge per router (STP on, no controller) plus one host each;
- `TCLink` with bw = bandwidth (capped at TCLink's 1000 Mbps), delay = delay ms, loss = loss×100 %.

The script is generated and syntax-checked only. Running it needs Linux, Mininet, and root, and it has not been run in this environment.

### Packet Tracer (`src/packet_tracer/`, `scripts/packet_tracer.py`)

`export` writes `outputs/packet_tracer/`:

- `build_ospf.js` / `build_rip.js` — JavaScript for the PTBuilder extension's Builder Code Editor
  (github.com/kimmknight/PTBuilder) that creates every device and cable and configures the
  network. Each node becomes a **Cisco 3560-24PS** multilayer switch running as a router
  (`ip routing`, `no switchport` routed ports) with one PC on `FastEthernet0/24`: the 3560 has 24
  built-in ports, while stock PT routers have 2–3 and would need scripted module installs.
  Addressing: link i → `10.0.<i/64>.<(i%64)*4>/30`; node n → LAN `192.168.n.0/24` (router `.1`,
  PC `.10`). OSPF interface cost = link delay rounded to an integer, so PT's OSPF optimizes the
  same metric as the OSPF-like baseline. Every step is try/caught and the script ends with one
  summary dialog.
- `ai_routes.js` / `ai_routes_undo.js` — static routes (AD 1, beating OSPF 110 / RIP 120) that pin
  chosen pairs to the AI's path in both directions; conflicting per-destination routes are
  rejected. By default it picks up to 3 pairs where the AI's path differs from every OSPF path.
  `export --no-ai` skips the model entirely and writes only the OSPF/RIP build scripts, configs,
  manifest and guide (no `ai_routes*.js`), so the PT build works before `scripts/train.py` has run
  and on machines without the ML stack; the recommender import is lazy for that reason.
- `configs/<protocol>/<router>.txt` (manual fallback), `manifest.json`, and `GUIDE.md` with the
  steps and the router path `tracert` should show in each configuration.

`verify --protocol ospf|rip [--ai] --trace FILE` parses `tracert` output copied from a PT PC, maps
each hop address to its router, and checks it against the prediction. The prediction comes from
`src/packet_tracer/routesim.py`, which parses the generated IOS lines themselves (interfaces,
OSPF network/cost, RIPv2, static routes, AD preference, ECMP) and computes forwarding paths.

Verified offline only: the generated JavaScript runs under Node against `tests/js/pt_mock.js`, a
mock of PT's Script Engine IPC API (calls documented by PTBuilder and MCP-Packet-Tracer for PT
9.0.1) that enforces device models, port existence and reuse, and copper cable type; the IOS
lines reaching each mock device are fed to the route simulator. Every IOS command used appears in
PT 9.0.1's bundled command reference except `ip routing` (the standard 3560 command, omitted
there). Not yet executed inside Packet Tracer itself (needs the GUI and a NetAcad login).

---

## 10. Outputs

```
models/                         route_cost_rf.joblib (~18 MB), route_cost_mlp.joblib,
                                feature_schema.json, training_report.json,
                                xai_background.csv                            (gitignored)
data/processed/training_table.csv                                            (gitignored)
outputs/routes/route_<topo>_<src>_<dst>.json
outputs/explanations/explain_<topo>_<src>_<dst>.json
outputs/figures/shap_*.png, lime_*.png, compare_*.png,
                explanation_quality.png, label_sensitivity.png, attack_drift.png
outputs/reports/compare_<topo>[_ospf-<cost>].csv|md
outputs/reports/explanation_quality.json|md
outputs/reports/label_sensitivity.json|md
outputs/reports/attack_drift.json|md
outputs/simulations/<scenario>/history.csv|json, timeline.png, explain_*/shap_* per reroute
outputs/mininet/<topo>_mininet.py
outputs/packet_tracer/build_*.js, ai_routes*.js, configs/, manifest.json, GUIDE.md
```

All generated outputs are gitignored. Regenerate them with `python scripts/demo.py`.

---

## 11. Evaluation beyond accuracy

These analyses answer questions the demo does not: can the explanation be trusted, does the model merely encode the scoring formula, and do explanations move when the network is attacked? All three need a trained model and write to `outputs/reports/` and `outputs/figures/`.

### 11.1 Explanation quality (`src/xai/quality.py`, `scripts/explain_quality.py`)

For one recommendation, with `MODEL_COLUMNS` as the feature set:

- **Occlusion fidelity.** Replace each feature of the chosen row by the median of the saved training background and compute `occ_i = f(x) − f(x with feature i replaced)`. Positive `occ_i` means the feature's actual value raised the predicted cost, the same sign as SHAP. Report the Spearman correlation of the signed vectors and top-5 overlap by magnitude. This is a model perturbation, not a causal intervention; replacing `sum_delay` while leaving `hops` fixed can create an impossible path.
- **Comprehensiveness / sufficiency.** Replacing the top-k attributed features should change the prediction more than replacing a random k-subset (`comprehensiveness_advantage`); keeping only the top-k and replacing the rest should preserve it better than a random subset (`sufficiency_advantage`). Both are averaged over 64 seeded random subsets (or all subsets when k equals the feature count).
- **SHAP vs LIME agreement.** Spearman, top-k Jaccard/overlap, sign agreement and cosine distance between the two signed vectors for the same instance.
- **LIME seed stability.** The same LIME run with seeds 42/43/44; pairwise rank/top-k agreement. SHAP is deterministic for one forest, so its seed stability is not meaningful.
- **Random Forest seed stability.** Retrain the forest with seeds 42/43/44 on the **same** labeled table and compare SHAP for the same queries. This isolates model variance from data-sampling variance and reports whether the chosen path and the explanation ranking stay the same.
- **Latency.** Median/mean/p95 wall-clock milliseconds, including explainer construction. This is a local measurement, not a deployment benchmark.

Full run on the sample topology, 7 pairs, default model (`outputs/reports/explanation_quality.json`):

| Metric | Value |
|--------|------:|
| SHAP occlusion fidelity (Spearman) | 0.558 |
| SHAP top-5 overlap with occlusion | 0.629 |
| SHAP comprehensiveness advantage | 0.399 |
| SHAP sufficiency advantage | 0.156 |
| LIME occlusion fidelity (Spearman) | 0.496 |
| LIME top-5 overlap with occlusion | 0.743 |
| SHAP vs LIME Spearman | 0.843 |
| SHAP vs LIME top-5 overlap | 0.810 |
| SHAP vs LIME sign agreement | 0.796 |
| LIME seed stability (Spearman) | 0.815 |
| LIME seed top-5 overlap | 0.914 |
| RF seed stability (Spearman) | 0.995 |
| RF seed top-5 overlap | 0.957 |
| RF seed chosen-path agreement | 1.000 |
| RF seed agreement with production model | 1.000 |
| SHAP median latency | 1,035 ms |
| LIME median latency | 146 ms |
| LIME mean surrogate R² | 0.205 |

Reading: the two methods agree well on this model, and different RF seeds produce almost the same explanation and the same path. Occlusion fidelity is moderate (0.56), so the SHAP ranking is not a complete description of which features the forest reacts to; correlated features and the median baseline both contribute. LIME's linear surrogate explains only about 20 % of the local variance, so its individual weights should be read as an approximate cross-check, not a second ground truth. SHAP latency is dominated by constructing `TreeExplainer`, not by the 18-feature prediction.

### 11.2 Label sensitivity (`src/evaluate/label_sensitivity.py`, `scripts/label_sensitivity.py`)

Default labels are the scoring rule's realized cost over the next horizon. The objection is "the model just learns your formula." The study changes the formula and retrains:

- `delay_heavy` (delay ×4), `risk_heavy` (security risk ×4), `loss_congestion_heavy` (loss and congestion ×3), `hop_heavy` (hops ×10), `uniform` (equal weights), plus seeded Dirichlet draws. Each vector is rescaled to the baseline weight total so the hard-risk penalty keeps the same relative strength. References and the risk limit are unchanged.
- For every scenario, the table is regenerated (traffic seeding is fixed), the forest is retrained, and the same held-out queries are scored. Two change rates are compared: the **rule's** argmin path vs the baseline weights, and the **retrained model's** pick vs the baseline model. `transfer_*` scores the baseline model against the new labels without retraining.
- A model that merely re-implements the formula should have `model_change_rate ≈ rule_change_rate`. Substantial divergence in either direction means the learned forecast does not reproduce every weight-induced pick; it is not evidence of a hidden objective.

This is deliberately policy-conditional: the study tests adaptation to a declared policy, not discovery of a weight-free "true" cost. Runtime is roughly one training run per scenario; `--quick` is for exploration, and `--scenarios baseline,risk_heavy --random-weight-draws 0` is the smallest useful run.

Full run, six scenarios, 601 held-out queries (`outputs/reports/label_sensitivity.json`):

| Scenario | Rule pick changed | Model pick changed | Retrained top-1 | Baseline model transferred |
|----------|------------------:|-------------------:|----------------:|---------------------------:|
| baseline | 0.000 | 0.000 | 0.820 | 0.820 |
| delay_heavy | 0.131 | 0.161 | 0.852 | 0.790 |
| risk_heavy | 0.135 | 0.131 | 0.855 | 0.807 |
| loss_congestion_heavy | 0.097 | 0.101 | 0.804 | 0.774 |
| hop_heavy | 0.050 | 0.068 | 0.840 | 0.819 |
| uniform | 0.136 | 0.121 | 0.817 | 0.779 |

Mean rule change 0.110, mean model change 0.117, cross-scenario correlation **0.882**. Retrained top-1 averages 0.834 vs 0.794 for the baseline model transferred to the new labels (gap 0.040).

Reading: the model does track the policy — when the weights move the rule's pick, the retrained model usually moves too, and the correlation is high. It is not a literal copy: per-scenario rates differ (delay-heavy moves the model more than the rule; uniform moves it less), and the old model loses about four top-1 points when the labels change, so retraining on the new definition is what adapts it. The honest claim is "learned, policy-conditional outcome model", not "weight-free ground truth".

### 11.3 Attack scenarios and attribution drift (`src/simulate/attacks.py`, `src/evaluate/attack_drift.py`)

Two metric-level node attacks:

- **blackhole**: every incident link gets `loss=0.99`, `reliability=0.10` (values configurable under `evaluation.attacks`).
- **compromised**: every incident link gets `security_risk=0.95`, above the 0.65 limit, plus a small loss bump (`0.05`).

A scenario declares `"attacks": [{"kind": "blackhole", "node": "R5", "step": 2}]`. `GraphSimulator` expands an attack into a `set` event per incident edge, reasserted at every step from `step` onward, so a later traffic update cannot partially undo the attack and the existing timeline, reroute explanations and hysteresis work unchanged. Shipped examples: `configs/scenarios/blackhole_r5.json` and `configs/scenarios/compromised_r7.json` (both R3→R8, whose initial path uses R5/R7).

`scripts/attack_drift.py` applies the attack once, finds the **same candidate path** in the before/after candidate sets, and compares its signed SHAP vectors:

- `attribution_drift` = cosine distance (0 = same direction, 2 = opposite); also Spearman, top-k overlap and `top_feature_changed`.
- **Signal detection**: for blackhole the signal feature is `sum_loss`; for compromised it is `max_security_risk`. `detected` means the signal's contribution increased and it entered the top-k after the attack.
- **Reroute / avoidance**: whether the chosen path changed, whether the attacked node is still on it, and whether the node is an endpoint (an attack on the destination cannot be avoided).

Full run, 7 default pairs × 2 attacks (`outputs/reports/attack_drift.json`): 5 of 14 pair-attacks had the attacked node on the baseline path. On those affected pairs, detection was **5/5** and mean cosine drift **1.58**; only 2/5 rerouted, because R7 is the destination on three pairs and cannot be avoided. Across both attacks (14 pair-attacks, including the 9 unaffected) the reroute rate was 0.143 and detection 0.357; among avoidable pairs the model avoided the attacked node in **100 %**. The per-attack split is in the JSON: blackhole R5 affected 1 pair (detected, rerouted), compromised R7 affected 4 (all detected; the one avoidable pair rerouted). This is consistent with attribution-drift monitoring: explanations on an affected path move sharply and the attack's signal feature rises, while unaffected paths stay flat. It is a candidate alarm, not proof of an attack; a temporal threshold is not calibrated here.

### 11.4 Tests and limitations

The new analyses have focused unit tests (`tests/test_explanation_quality.py`, `test_label_sensitivity.py`, `test_attacks.py`) plus end-to-end CLI checks in `tests/test_scripts_e2e.py`. The full suite count is on the status board. The metrics are evaluation instruments, not new routing claims; see the limitations in §13.

---

## 12. Tests

`python scripts/run_tests.py` (stdlib `unittest`; `pytest tests` also works if installed). Integration tests train a small model once into a temp folder, so the real `models/` is never touched. `tests/test_scripts_e2e.py` runs every CLI script with a temp config and checks the files it writes. The LIME test is skipped, with the reason printed, when `lime` is not installed. `tests/test_packet_tracer.py` runs the generated PTBuilder scripts under Node against `tests/js/pt_mock.js` (skipped if Node.js is missing). `tests/test_real_traffic.py` runs against 4 real Abilene traffic-matrix files checked in as fixtures (no network access needed). The suite includes the three evaluation modules and their CLI paths; the full run is 255 tests OK, 1 skipped.

---

## 13. Known limitations

- The objective is a hand-set scoring rule. With `future_outcome` labels the model predicts the rule cost a path will experience, so it no longer just imitates the rule; but "good" is still defined by those weights, and the futures come from a simulated traffic model (§5.1), not measured traffic.
- Under the default traffic model the explained RF roughly ties the snapshot rule on held-out data (status board): bursts rarely change which candidate is best, so history adds little. RIP-like and OSPF-like picks are far worse.
- The default hysteresis margin (3%) only holds near-tied switches; under continuous traffic dynamics with genuinely close candidates it still flaps occasionally (`traffic_dynamics`: 7 reroutes in 30 steps, down from 11 with the margin off).
- Q-routing is a single-objective (delay + congestion only) baseline, trained offline on a synthetic trace rather than online per-packet as in the original algorithm; it is a point of comparison for "an existing dynamic routing method", not a reimplementation of a production Q-routing deployment.
- Candidates are limited to `k` paths (default 5) from `mixed` Yen. A better path outside that set cannot be chosen.
- The sample graph is synthetic. Imported Zoo/SNDlib graphs use synthetic QoS/risk values and, for GraphML sources, default delays (all labelled).
- Real SNDlib traffic (§8/§9) only replays through P6; it does not affect P3's training data or held-out results, by design (§9's SNDlib section explains why). Only congestion/utilization/loss/queue are real-derived — delay, bandwidth, reliability, energy, and security_risk are not measured by a traffic matrix and stay at the base topology's (synthetic or documented) values.
- Simulation is a discrete metric-update model with no packets, queues, or protocol convergence timing. The Mininet export and the Packet Tracer scripts are untested on those platforms here.
- SHAP/LIME explain the model output, not causal network behaviour. LIME depends on discretisation and sampling (seeded).
- Explanation fidelity uses median occlusion, which can create feature combinations no real path has; it tests faithfulness to the model, not correctness of the route. On the sample topology SHAP–occlusion rank correlation is 0.56, so the explanation is informative but incomplete.
- LIME's local surrogate R² is about 0.21 on the sample pairs; its weights are a rough cross-check. Seed stability (0.81) is good, but stability does not make the surrogate exact.
- Label sensitivity retrains on labels generated by each weight vector; a low model change rate means the learned forecast does not reproduce every rule flip, not that the model has discovered an objective independent of the weights. The study does not search the full weight simplex.
- Attack scenarios are metric overrides on incident links, not packet-level attacks. Attribution drift is descriptive: detection is defined by top-k SHAP ranking and has no calibrated false-alarm rate over time.
- The RF seed-stability result uses one training table and three seeds; it isolates forest variance, not variance from re-sampling the traffic traces.
