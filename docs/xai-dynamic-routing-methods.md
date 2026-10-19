# Methods and reference: XAI dynamic routing

Technical reference for `projects/xai-dynamic-routing/`. It covers what each phase computes, the units and aggregation rules, how labels and the model are built, what SHAP and LIME explain, and the limits of each result. Commands are in [execution-plan.md](execution-plan.md). Status and measured results are in [phase-execution-status.md](phase-execution-status.md).

---

## 1. Architecture

```
configs/default.json ──► src/config.py (validated config, project-root path resolution)
data/samples/*.json  ──► src/topology/load.py      JSON loader + metric validation      [P0]
data/raw/*.gml|graphml ► src/topology/zoo.py       Topology Zoo import + provenance     [P7]
data/raw/*.txt       ──► src/topology/sndlib.py    SNDlib native import + demands       [P7]
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

**Scope.** Explanations describe the model, which is a learned surrogate of the configured scoring rule. They do not show causation in the network or prove a route globally optimal.

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

Scenario JSON (`configs/scenarios/*.json`): `name`, `src`, `dst`, `steps`, `seed`, `drift {metrics, sigma}`, `events[{step, edge, set{}, add{}, label}]`, and optional `"traffic": true` (run the §5.1 traffic model each step — the dynamics the default model is trained on).

At each step t (0..steps−1):

1. For t > 0, add seeded `N(0, sigma)` drift to the drift metrics on every edge.
2. For t > 0 with `"traffic": true`, advance the traffic model one step.
3. Apply that step's scripted events.
4. Clip values to valid ranges and re-validate the graph.
5. Re-run the recommender with each candidate's recent history (the previous `history_steps` − 1 snapshots of this run).

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

Parses `NODES` (coordinates), `LINKS` (pre-installed capacity, else largest module capacity, treated as Mbps), and `DEMANDS` (sorted largest first; used as comparison pairs). Other metrics follow the Zoo policy. Keep instances in `data/raw/`.

SNDlib dynamic traffic matrices (Abilene: 5-minute intervals over 6 months; GÉANT: 15-minute
intervals over 4 months; from sndlib.put.poznan.pl) can be downloaded into `data/raw/sndlib/`;
the loader currently uses the static `DEMANDS` section only.

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
outputs/figures/shap_*.png, lime_*.png, compare_*.png
outputs/reports/compare_<topo>[_ospf-<cost>].csv|md
outputs/simulations/<scenario>/history.csv|json, timeline.png, explain_*/shap_* per reroute
outputs/mininet/<topo>_mininet.py
outputs/packet_tracer/build_*.js, ai_routes*.js, configs/, manifest.json, GUIDE.md
```

All generated outputs are gitignored. Regenerate them with `python scripts/demo.py`.

---

## 11. Tests

`python scripts/run_tests.py` (stdlib `unittest`; `pytest tests` also works if installed). Integration tests train a small model once into a temp folder, so the real `models/` is never touched. `tests/test_scripts_e2e.py` runs every CLI script with a temp config and checks the files it writes. The LIME test is skipped, with the reason printed, when `lime` is not installed. `tests/test_packet_tracer.py` runs the generated PTBuilder scripts under Node against `tests/js/pt_mock.js` (skipped if Node.js is missing). 190 tests.

---

## 12. Known limitations

- The objective is a hand-set scoring rule. With `future_outcome` labels the model predicts the rule cost a path will experience, so it no longer just imitates the rule; but "good" is still defined by those weights, and the futures come from a simulated traffic model (§5.1), not measured traffic.
- Under the default traffic model the explained RF roughly ties the snapshot rule on held-out data (status board): bursts rarely change which candidate is best, so history adds little. RIP-like and OSPF-like picks are far worse.
- The default hysteresis margin (3%) only holds near-tied switches; under continuous traffic dynamics with genuinely close candidates it still flaps occasionally (`traffic_dynamics`: 7 reroutes in 30 steps, down from 11 with the margin off).
- Q-routing is a single-objective (delay + congestion only) baseline, trained offline on a synthetic trace rather than online per-packet as in the original algorithm; it is a point of comparison for "an existing dynamic routing method", not a reimplementation of a production Q-routing deployment.
- Candidates are limited to `k` paths (default 5) from `mixed` Yen. A better path outside that set cannot be chosen.
- The sample graph is synthetic. Imported Zoo/SNDlib graphs use synthetic QoS/risk values and, for GraphML sources, default delays (all labelled).
- Simulation is a discrete metric-update model with no packets, queues, or protocol convergence timing. The Mininet export and the Packet Tracer scripts are untested on those platforms here.
- SHAP/LIME explain the model output, not causal network behaviour. LIME depends on discretisation and sampling (seeded).
