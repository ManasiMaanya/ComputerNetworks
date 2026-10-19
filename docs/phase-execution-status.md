# Phase execution status

**Canonical live board** for Title 4. Checklists and dependencies stay in [xai-dynamic-routing-phase-plan.md](xai-dynamic-routing-phase-plan.md). Methods: [xai-dynamic-routing-methods.md](xai-dynamic-routing-methods.md).

**Last updated:** 2026-10-19 (anti-flapping hysteresis in P6; fault-ledger cleanup)

**Rule:** Before every git commit that touches this capstone or its docs, refresh this file: Last updated, phase table, current work, next action, execution log. Keep `docs/execution-plan.md` in sync with scripts the user can run.

---

## Current work

| Field | Value |
|-------|--------|
| **Active phase** | None. P0–P7 implemented and verified, including LIME, outcome-based labels, the black-box baseline, and the Packet Tracer export (mock-tested). |
| **Next action** | Run `outputs/packet_tracer/build_ospf.js` inside Packet Tracer and `verify` a tracert (only mock-tested so far); wire SNDlib traffic matrices into the traffic model; add an existing AI routing baseline (e.g. Q-routing). |
| **Blocked by** | — |
| **Faults** | Corrected: F-001–F-012, F-014–F-020. Open: F-013, F-021 ([fault-ledger.md](fault-ledger.md)) |

---

## Phases

| Phase | Name | Status | Checklist | Evidence (2026-10-04 run) |
|-------|------|--------|-----------|---------------------------|
| P0 | Scaffold | **done** | complete | `load_sample.py`: 8 nodes, 11 edges, 1 component. Loader validation and import fixes (F-005/006/007). |
| P1 | Topology + features | **done** | complete | `features.py --src R1 --dst R8`: 5 candidates, all 4 hops; path 0 R1-R2-R4-R6-R8 sum_delay 25, min_bandwidth 70 (hand-checked in tests) |
| P2 | RIP / OSPF baselines | **done** | complete | R1→R8 both R1-R2-R4-R6-R8; `--all-pairs`: 15/56 pairs differ (e.g. R2→R5 RIP R2-R5 1 hop/20 ms vs OSPF R2-R4-R3-R5 18 ms) |
| P3 | Labels + recommender | **done** | complete | Outcome labels (realized cost over the next 5 steps of a simulated trace) + 6 history features; 44,160 rows / 8,832 queries / 108 groups; split by group and time. Held-out (601 queries): RF top-1 0.820, regret 0.0274 vs snapshot rule 0.830 / 0.0278, black-box MLP 0.800 / 0.0311, min delay 0.661 / 0.1234, hop count 0.597 / 0.2115; 207 better / 348 tie / 46 worse vs hop count, p = 7.2e-26 |
| P4 | SHAP / LIME | **done** | complete | SHAP TreeExplainer: R1→R8 signed contributions, additivity error 6.8e-15, runner-up contrast, JSON + figure. LIME (2026-10-12): same instance, top condition `max_security_risk <= 0.35` (-0.355) agrees with SHAP's top feature; surrogate R² 0.13; LIME figure saved. |
| P5 | Compare | **done** | complete | 7 sample pairs × RIP / OSPF / AI / AI-BB, 0 failures. Mean max risk: AI 0.279, OSPF 0.343, RIP 0.500. Mean delay: AI 23.0, OSPF 21.6, RIP 26.4 ms. CSV/MD/figure saved. |
| P6 | Dynamics | **done** | complete | History-aware recommender. `sample_incident` 10 steps: reroute at t=5 (R4-R6 flagged high-risk) to R1-R3-R5-R7-R8, back at t=8 (R4-R6 recovers); the one-step congestion spike at t=3 is smoothed by history. `traffic_dynamics` (R2→R5, 30 steps, traffic model): 11 reroutes at `hysteresis_margin=0` (incl. flapping between two near-tied paths), **7 with the default 3% margin** (anti-flapping, 2026-10-19) — `sample_incident`'s 2 genuine reroutes are unaffected. SHAP vs previous path each time. |
| P7 | Datasets / testbed | **done** (Packet Tracer and Mininet not run on their platforms) | complete | GÉANT 2012 from the Zoo authors' mirror (GML with coordinates): 40 nodes / 61 links, delay from distance on 58/61 links, 12 pairs, 0 failures. Abilene also run. SNDlib loader (fixture-tested). Mininet script exported (not run). Packet Tracer: PTBuilder build/AI-route scripts + IOS configs + tracert verifier, tested against a PT-API mock (sample and real Abilene). |

Statuses: `not_started` · `in_progress` · `blocked` · `done` · `skipped`

---

## Milestones

| ID | After | Meaning | Done |
|----|--------|---------|------|
| M0 | P0 | Sample graph loads | **yes** |
| M1 | P1 | Candidate paths + feature table | **yes** |
| M2 | P2 | RIP path ≠ OSPF path on sample topo | **yes** (15/56 pairs) |
| M3 | P4 | AI path + SHAP/LIME text and figure | **yes** (SHAP and LIME) |
| M4 | P5 | RIP vs OSPF vs AI table | **yes** |
| M5 | P6–P7 | Time-varying routes and/or Topology Zoo | **yes** (both; plus Packet Tracer export) |

---

## Web demo

All tabs P0–P7 implemented (`web/app.py`, `web/static/`): topology with link details and metric colouring, candidate path features, RIP/OSPF overlay, AI recommendation vs black-box MLP, SHAP/LIME explanation with why-not-runner-up and a plain-English summary, RIP/OSPF/AI/AI-BB comparison with the held-out evaluation table, scenario timeline (play/slider, reroute reasons), and 300+ real topologies (Topology Zoo / SNDlib) with geographic layout. Start: `scripts\web-local.cmd`, open `http://127.0.0.1:8765/`. Verified 2026-10-12: `tests/test_web.py` (10 API tests), `scripts/web_health.py` (9/9 ok), and a headless-Chrome walk through every tab with no console errors. Docker path not re-run (Docker Desktop unavailable on that machine).

## Measured results (seed 42, default config)

### P3 held-out evaluation (`models/training_report.json`)

Labels: `future_outcome` — each candidate's realized rule cost over the next 5 steps of a simulated traffic trace (mean-reverting congestion/loss/risk with transient bursts and incidents). Split by group and by time: 7 of 28 sample pairs (`R1|R3, R1|R4, R2|R6, R2|R7, R3|R6, R3|R8, R5|R7`) plus 20 of 80 synthetic graphs are held out, and only their last 30 % of each trace is scored; training rows come from the other groups' first 70 % (label windows end before the held-out period). 601 held-out queries.

| Method | Top-1 (best in hindsight) | Mean regret | Mean true cost |
|--------|--------------------------:|------------:|---------------:|
| Hop count (RIP-like) | 0.597 | 0.2115 | 0.6578 |
| Min delay (OSPF-like) | 0.661 | 0.1234 | 0.5698 |
| Snapshot rule (rule on current state) | 0.830 | 0.0278 | 0.4741 |
| AI black-box (MLP) | 0.800 | 0.0311 | 0.4774 |
| **AI explained (RF)** | **0.820** | **0.0274** | **0.4737** |
| Oracle (hindsight) | 1.000 | 0 | 0.4463 |

RF vs hop count: 207 better / 348 tie / 46 worse (sign test p = 7.2e-26). RF vs snapshot rule: 35 / 525 / 41. RF vs black-box: 60 / 500 / 41. Regression: held-out MAE 0.0946, R² 0.913 (MLP 0.112 / 0.895); group 5-fold CV MAE 0.0868 ± 0.0046. Top impurity importances: `max_security_risk` 0.78 (the risk-limit penalty), `hist_mean_loss` 0.05, `sum_delay` 0.03.

Reading: both AI models are far better than RIP-like/OSPF-like picks, and the explained RF is not worse than the black-box MLP, but under the default traffic model the RF only ties the snapshot rule — bursts rarely change which candidate is best, so history adds little. These are results on a simulated traffic model, not measured network performance. With `"labels": "rule_snapshot"` the earlier rule-imitation setup is still available (top-1 0.958 against its own rule, 2026-10-04).

### P5 sample comparison (7 pairs, `outputs/reports/compare_sample_topology.md`)

| Method | sum_delay (ms) | sum_loss | max_security_risk | hops | rule_cost* |
|--------|---------------:|---------:|------------------:|-----:|-----------:|
| RIP | 26.43 | 0.0800 | 0.500 | 3.00 | 0.990 |
| OSPF (delay) | 21.57 | 0.0586 | 0.343 | 3.29 | 0.413 |
| AI | 23.00 | 0.0571 | 0.279 | 3.57 | 0.396 |
| AI-BB (black-box) | 23.00 | 0.0571 | 0.279 | 3.57 | 0.396 |

\* `rule_cost` is the objective (reference only). On a static snapshot both AI models pick the same routes here; the AI trades about +1.4 ms mean delay against OSPF for lower link risk and loss.

### P7 GÉANT 2012 (12 seeded pairs, GML with coordinates)

| Method | sum_delay (ms) | max_security_risk | hops | rule_cost* |
|--------|---------------:|------------------:|-----:|-----------:|
| RIP | 15.29 | 0.428 | 3.75 | 0.352 |
| OSPF (delay) | 14.66 | 0.416 | 3.92 | 0.345 |
| AI | 15.94 | 0.350 | 4.50 | 0.340 |
| AI-BB | 18.82 | 0.355 | 5.00 | 0.374 |

Provenance: delay estimated from distance on 58/61 links (default 3), bandwidth documented 39 / default 22, other metrics synthetic 61/61.

### Tests

`python scripts/run_tests.py`: **181 tests, OK, 1 skipped** (`LimeMissingTests`, which only runs when `lime` is absent), ~65 s, in a fresh project venv. Includes `tests/test_packet_tracer.py`, which runs the generated PTBuilder scripts under Node against a PT-API mock, and `tests/test_simulation.py::HysteresisTests` (anti-flapping).

---

## Execution log

| Date | Event |
|------|--------|
| 2026-08-28 | P0 scaffold created; sample topology loads (8 nodes, 11 edges) — **M0** |
| 2026-08-28 | Phase plan, dependencies, and per-phase checklists written |
| 2026-08-28 | Fault ledger F-001–F-014 opened; fixes wait on explicit ID approval |
| 2026-08-28 | This status board added; tables synced for commit |
| 2026-08-28 | Operator execution plan + `scripts/load_sample.py` / `run.ps1`; skill: always ship a runnable script |
| 2026-08-28 | First git commit of skill, docs, and P0 scaffold |
| 2026-08-28 | Concepts guide + figures: `docs/concepts/cn-concepts-xai-routing.md` |
| 2026-08-28 | P0 webpage + Docker/WSL docs; `web-up` / `web-test` scripts |
| 2026-08-28 | Windows `.cmd` launchers for execution-policy Restricted |
| 2026-08-28 | Commit: concepts, P0 webpage, Docker/WSL, GitHub SSH helper |
| 2026-10-04 | User approved F-005/F-006/F-007 and full P1–P7 execution. Baseline: P1–P7 stubs, no tests; `lime`, `fastapi`, `pytest` not installed |
| 2026-10-04 | P0 fixes: `src/config.py`, `src/errors.py`, validated loader, relative imports — F-005/006/007 corrected |
| 2026-10-04 | P1 `features.py` (**M1**); P2 `baselines.py`, 15/56 pairs differ (**M2**) |
| 2026-10-04 | P3 scoring, dataset (group split), Random Forest, `train.py`/`infer.py`; model shrunk 77 MB → 15 MB (150 trees, leaf 5) |
| 2026-10-04 | P4 SHAP + contrast + LIME integration; M3 demo with SHAP (**M3**, LIME unverified) |
| 2026-10-04 | P5 `compare.py` (**M4**); found F-015 (candidate set excluded OSPF path), fixed with `mixed` candidates, retrained |
| 2026-10-04 | P6 `simulate.py`: 2 model-decided reroutes in 10 steps with explanations |
| 2026-10-04 | P7 Topology Zoo GML/GraphML + SNDlib loaders, provenance; GÉANT 2012 and Abilene compared (**M5**); Mininet export |
| 2026-10-04 | 123-test suite; F-016 (prediction determinism) fixed; `demo.py --retrain --with-zoo` end-to-end OK; artifacts and schemas validated |
| 2026-10-12 | Fresh `.venv` + `pip install -r requirements.txt` verified (F-003). With `lime` installed, 3 tests failed on one bug (`exp.intercept` is a per-label dict); fixed, LIME verified (F-018). P4 done, M3 met with SHAP and LIME. |
| 2026-10-12 | Merged the separate `xai-dynamic-routing` work: traffic model (`src/simulate/traffic.py`), history features (F-010), outcome labels with group + time split (F-020), black-box MLP baseline (F-009), extended held-out evaluation (snapshot rule, oracle), history-aware simulation + `traffic_dynamics` scenario, Packet Tracer integration (`src/packet_tracer/`, `scripts/packet_tracer.py`, Node PT-API mock). Zoo authors' mirror added to `fetch_topology_zoo.py` (F-017). 162 tests OK; `demo.py --retrain` end to end OK. |
| 2026-10-12 | Web demo P1–P7 (F-019): FastAPI routes for every phase, 8-tab page, `scripts/web-local.cmd`, extended `web_health.py`, compose mounts for models/data/outputs; 172 tests OK. |
| 2026-10-19 | Fault-ledger cleanup (user-approved F-001, F-002, F-004, F-011, F-014): overview §12 tree/PDF path fixed; stdlib-only coding rule scoped to `labs/` with the capstone's package list spelled out in `reference.md`; added `projects/xai-dynamic-routing/pyproject.toml`, verified with `pip install -e .` + import from outside the project dir. 173 tests still OK. |
| 2026-10-19 | Anti-flapping hysteresis in P6 (`src/simulate/runner.py::apply_hysteresis`, config `simulation.hysteresis_margin`, default 0.03): hold the previous path when the model's new top pick isn't at least `margin` cheaper and the previous path is still a candidate; a reroute still happens immediately when the previous path drops out of the candidate set or a clearly better path appears. `traffic_dynamics`: 11 → 7 reroutes. `sample_incident`'s 2 scripted reroutes (t=5, t=8) unaffected. `scripts/simulate.py --hysteresis-margin` overrides it; web demo timeline surfaces `held_by_hysteresis` / `model_top_pick`. 8 new tests (`tests/test_simulation.py::HysteresisTests`); 181 tests OK. |

---

## How to update (agent / before commit)

1. Set **Last updated** to today.
2. Set **Active phase** / **Next action** from the repo, not from memory.
3. Change a phase to `done` only if that phase's checklist in the phase-plan file is fully ticked **and** the exit criterion holds.
4. Append one row to the execution log.
5. Copy the phase/milestone summary into phase-plan §2 if it drifted.
