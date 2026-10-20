# Explainable AI-Based Dynamic Routing Recommendation

Layer 3 path recommendation from QoS and security link metrics, using a Random Forest that scores k candidate paths from their current features and recent traffic history. It is trained to predict the cost each path will experience over the next few steps of a simulated traffic trace. Each recommendation comes with SHAP and LIME explanations and a comparison against RIP-like (hop count), OSPF-like (Dijkstra), and Q-routing (a classical traffic-reactive) baselines, plus a black-box MLP. A time-stepped simulation reroutes when metrics change, optionally driven by real measured traffic (SNDlib) instead of the synthetic model. The network can also be built in Cisco Packet Tracer from generated scripts.

`security_risk` is a numeric link attribute (0–1) in a simulation. The attack scenarios are metric-level node/link degradation simulations; there is no exploit or offensive content. Explanation-quality evaluation, a label-sensitivity study, and attribution-drift analysis are included beyond the demo path.

Full method reference (features, units, scoring, training, XAI semantics, data provenance, limits): [`docs/xai-dynamic-routing-methods.md`](../../docs/xai-dynamic-routing-methods.md).

## Setup

Python 3.10+ (tested with 3.12).

```
cd projects/xai-dynamic-routing
python -m venv .venv
.\.venv\Scripts\activate.bat        (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

`lime` is needed only for the LIME half of the explanations. Without it, runs continue with SHAP only and say that LIME was skipped. `fastapi`/`uvicorn` are needed only for the web demo.

## Run the demo

Every script works from any directory.

```
python scripts/demo.py                 # P0 -> P6 + Mininet export; trains if no model exists
python scripts/demo.py --with-zoo      # + downloads GEANT 2012 (Topology Zoo) and compares on it
```

Or step by step:

| Phase | Command | What it shows |
|-------|---------|---------------|
| P0 | `python scripts/load_sample.py` | `nodes: 8`, `edges: 11` |
| P1 | `python scripts/features.py --src R1 --dst R8` | k candidate paths + 12-feature table |
| P2 | `python scripts/baselines.py --src R1 --dst R8` (or `--all-pairs`) | RIP-like and OSPF-like path and cost |
| P3 | `python scripts/train.py` | simulated-traffic dataset, held-out table: hop count / min delay / snapshot rule / black-box MLP / RF / oracle |
| P3/P4 | `python scripts/infer.py --src R1 --dst R8 --explain` | ranked candidates, chosen path, signed SHAP/LIME contributions |
| P5 | `python scripts/compare.py` | RIP vs OSPF vs Q-ROUTE vs AI vs AI-BB (black-box) table on several pairs |
| P6 | `python scripts/simulate.py` (`--scenario configs/scenarios/traffic_dynamics.json`) | 10-step incident scenario (or 30 steps of traffic dynamics), reroutes with reasons and new explanations |
| P6/P7 | Save Abilene's network file to `data/raw/sndlib/networks/abilene.txt`, then `python scripts/fetch_sndlib_traffic.py --network abilene --limit 48`, then `python scripts/simulate.py --scenario configs/scenarios/abilene_real_traffic.json` | 48-step scenario driven by real Abilene traffic matrices instead of synthetic dynamics |
| P7 | `python scripts/fetch_topology_zoo.py --name Geant2012` then `python scripts/compare.py --topology data/raw/Geant2012.graphml --ospf-cost inverse_bandwidth` | comparison on a real topology, metric provenance |
| P7 | `python scripts/export_mininet.py` | Mininet script (Linux + root needed to run it) |
| P7 | `python scripts/packet_tracer.py export` | Packet Tracer build / AI-route scripts for PTBuilder + `GUIDE.md`; `export --no-ai` builds the baselines without a trained model; `verify --protocol ospf [--ai] --trace FILE` checks a PT tracert |
| eval | `python scripts/explain_quality.py` | SHAP occlusion fidelity, SHAP/LIME agreement, LIME and Random Forest seed stability, latency |
| eval | `python scripts/label_sensitivity.py --quick` | retrain under delay/risk/loss/hop-heavy, uniform, and seeded random cost weights; rule vs model path changes and transfer |
| eval | `python scripts/attack_drift.py` | blackhole/compromised-node metric attacks, rerouting, SHAP attribution drift, signal-feature detection |
| web | `scripts\web-local.cmd` | demo page with every phase on `http://127.0.0.1:8765/` |
| tests | `python scripts/run_tests.py` | full suite (`--quick` skips the end-to-end script test) |

Windows launchers: `scripts\demo.cmd`, `scripts\p0.cmd`, `scripts\tests.cmd`.

The three `eval` scripts need a trained model (`python scripts/train.py`). `explain_quality.py`
writes `outputs/reports/explanation_quality.{json,md}` and a figure; `label_sensitivity.py`
retrains once per scenario, so `--quick --scenarios baseline,risk_heavy --random-weight-draws 0`
is the fast exploratory run; `attack_drift.py` defaults to R5 blackhole and R7 compromised on the
sample topology. Full report semantics are in
[`docs/xai-dynamic-routing-methods.md`](../../docs/xai-dynamic-routing-methods.md), section 11.

## Layout

```
configs/default.json              all tunables (validated by src/config.py)
configs/scenarios/*.json          P6 scenarios
data/samples/                     sample topology (8 routers, 11 links)
data/raw/                         downloaded Topology Zoo / SNDlib files (gitignored)
src/topology/                     load.py (JSON), zoo.py (GML/GraphML), sndlib.py (+ real traffic matrices), provenance.py
src/features/path_features.py     candidates + FEATURE_COLUMNS
src/features/history.py           traffic-history features, MODEL_COLUMNS
src/routing/                      baselines.py, qrouting.py, scoring.py, dataset.py, recommender.py
src/xai/explain.py                SHAP, LIME, figures
src/xai/quality.py                occlusion fidelity, rank/top-k agreement, drift, latency
src/evaluate/compare.py           comparison table, report, figure
src/evaluate/explanation_quality.py  per-pair quality report + forest seed stability
src/evaluate/label_sensitivity.py    alternate cost weights, retraining, transfer
src/evaluate/attack_drift.py         SHAP drift before/after node attacks
src/simulate/                     traffic.py, real_traffic.py, graph_sim.py, runner.py, attacks.py, mininet_export.py
src/packet_tracer/                plan, IOS configs, PTBuilder scripts, route simulator, tracert check
scripts/                          CLIs (see table above)
tests/                            unittest suite + fixtures (tests/js/pt_mock.js: Packet Tracer API mock, needs Node.js)
models/, outputs/                 generated (gitignored); regenerate with scripts/demo.py
```

## Outputs

`outputs/routes/`, `outputs/explanations/`, `outputs/figures/`, `outputs/reports/`, `outputs/simulations/<scenario>/`, `outputs/mininet/`, `outputs/packet_tracer/`. The evaluation reports are `outputs/reports/explanation_quality.*`, `label_sensitivity.*`, and `attack_drift.*`, with matching figures. See the methods doc, section 10.

## Web demo (P0–P7)

```
scripts\web-local.cmd          (or: python -m uvicorn web.app:app --host 127.0.0.1 --port 8765)
```

Open `http://127.0.0.1:8765/`. Tabs: topology, path features, RIP/OSPF, AI recommendation, explanation (SHAP/LIME), comparison (with the held-out evaluation), scenario timeline, and larger real topologies. Tabs P3–P6 need a trained model (`python scripts/train.py`). Binds `127.0.0.1`, port `8765`. Docker and health checks: `docs/web/backend-docker.md`; check a running server with `python scripts/web_health.py`.

## Project docs

Phases and checklists: `docs/xai-dynamic-routing-phase-plan.md`. Status and measured results: `docs/phase-execution-status.md`. Operator commands: `docs/execution-plan.md`. Fault ledger: `docs/fault-ledger.md`.
