# Execution plan

**Who runs this:** you (local PowerShell or any shell). Every phase has a script; do not rely on `python -c` one-liners.

**Live status:** [phase-execution-status.md](phase-execution-status.md)  
**Phase design:** [xai-dynamic-routing-phase-plan.md](xai-dynamic-routing-phase-plan.md)  
**Methods reference:** [xai-dynamic-routing-methods.md](xai-dynamic-routing-methods.md)  
**Code:** `projects/xai-dynamic-routing/`  
**Concepts:** [concepts/cn-concepts-xai-routing.md](concepts/cn-concepts-xai-routing.md)

Commands below assume `projects/xai-dynamic-routing` as the working directory, but every script also works from any other directory. On Windows, `scripts\*.cmd` avoids PowerShell's execution policy.

---

## 1. One-time setup

```
cd projects/xai-dynamic-routing
python -m venv .venv
.\.venv\Scripts\activate.bat
pip install -r requirements.txt
```

`lime` is optional at runtime: without it, explanations are SHAP-only and say so.

---

## 2. What you run (by phase)

| Phase | Ready? | You execute | Expected |
|-------|--------|-------------|----------|
| **All** | **yes** | `python scripts/demo.py` or `scripts\demo.cmd` | Runs P0→P6 + Mininet and Packet Tracer exports in order; trains if no (current) model exists |
| **P0** Scaffold | **yes** | `python scripts/load_sample.py` or `scripts\p0.cmd` | `nodes: 8`, `edges: 11`, `connected components: 1` |
| **Web P0–P7** | **yes** | `scripts\web-local.cmd` (no Docker) or `scripts\web-up.cmd` (Docker), then `http://127.0.0.1:8765/` | All tabs: topology, path features, RIP/OSPF, AI recommend, explanation, compare, timeline, larger topology; `scripts\web-test.cmd` prints 9 `ok` lines |
| **P1** Features | **yes** | `python scripts/features.py --src R1 --dst R8` | 5 candidate paths (all 4 hops) and a 12-column feature table; path 0 `R1-R2-R4-R6-R8`, `sum_delay` 25 |
| **P2** Baselines | **yes** | `python scripts/baselines.py --src R1 --dst R8`, then `--all-pairs` | Both pick `R1-R2-R4-R6-R8` (hops 4, delay 25); `--all-pairs` lists 15/56 pairs where RIP ≠ OSPF (e.g. R2→R5) |
| **P3** Train | **yes** | `python scripts/train.py` | ~80–100 s; 44,160 rows (simulated traffic, outcome labels); held-out table of hop count / min delay / snapshot rule / black-box / RF / oracle (RF top-1 ≈ 0.82, regret ≈ 0.027); writes `models/` incl. `route_cost_mlp.joblib` |
| **P3/P4** Infer + XAI | **yes** | `python scripts/infer.py --src R1 --dst R8 --explain` | `RECOMMENDED: R1 -> R2 -> R4 -> R6 -> R8`, signed SHAP list, contrast with runner-up, LIME (or skip note); JSON + PNG saved |
| **P5** Compare | **yes** | `python scripts/compare.py` | 7 pairs × RIP/OSPF/AI/AI-BB; CSV + Markdown in `outputs/reports/`, figure in `outputs/figures/` |
| **P6** Dynamics | **yes** | `python scripts/simulate.py` | 10 steps; reroutes at t=5 and t=8 with reasons and new explanations |
| **P6** Traffic | **yes** | `python scripts/simulate.py --scenario configs/scenarios/traffic_dynamics.json` | R2→R5, 30 steps under the traffic model; 7 reroutes with the default 3% hysteresis margin (11 with it off) |
| **P7** Zoo | **yes** (network) | `python scripts/fetch_topology_zoo.py --name Geant2012` then `python scripts/compare.py --topology data/raw/Geant2012.gml` | 40 nodes / 61 links (from the Zoo authors' mirror when topology-zoo.org is down); delay from distance on 58/61 links; 12-pair comparison |
| **P7** Mininet | export only | `python scripts/export_mininet.py` | `outputs/mininet/sample_topology_mininet.py` (run on Linux with `sudo`) |
| **P7** Packet Tracer | export + verify | `python scripts/packet_tracer.py export` (or `export --no-ai` before a model exists), then follow `outputs/packet_tracer/GUIDE.md`; `python scripts/packet_tracer.py verify --protocol ospf [--ai] --trace trace.txt` | `build_ospf.js` / `build_rip.js` / `ai_routes.js` for PTBuilder; 3 demo pairs where AI ≠ OSPF with expected tracert paths |
| **Eval** Explanation quality | **yes** (model) | `python scripts/explain_quality.py` | 7 pairs; SHAP occlusion fidelity ρ 0.56, SHAP–LIME ρ 0.84, LIME seed ρ 0.81, RF seed ρ 0.995, path agreement 1.0; median 1.03 s SHAP / 0.15 s LIME; JSON/MD/figure |
| **Eval** Label sensitivity | **yes** (model) | `python scripts/label_sensitivity.py --quick` (or full `--scenarios baseline,delay_heavy,risk_heavy,loss_congestion_heavy,hop_heavy,uniform --random-weight-draws 0`) | One retrain per weight scenario. Full 6-scenario run: mean rule change 0.110 vs model change 0.117 (correlation 0.882), retrained top-1 0.834 vs transferred 0.794; JSON/MD/figure. Runtime ~6 training runs |
| **Eval** Attack drift | **yes** (model) | `python scripts/attack_drift.py`; `python scripts/simulate.py --scenario configs/scenarios/blackhole_r5.json --no-lime` | R5 blackhole and R7 compromised; affected-path SHAP drift + signal detection; R3→R8 reroutes in the timeline; JSON/MD/figure |
| **Tests** | **yes** | `python scripts/run_tests.py` or `scripts\tests.cmd` | 228 tests OK, 1 skipped; LIME skip appears only when `lime` is missing; Packet Tracer script tests skipped if Node.js is missing |

Webpage plan: [web/web-phase-plan.md](web/web-phase-plan.md). Docker install/start/debug/test: [web/backend-docker.md](web/backend-docker.md).

---

## 3. Order

1. Setup (venv + pip)
2. P0 `load_sample.py`
3. P1 `features.py`
4. P2 `baselines.py` (independent of the model)
5. P3 `train.py`, then `infer.py`
6. P4 `infer.py --explain`
7. P5 `compare.py`
8. P6 `simulate.py`, then the two attack scenarios (`blackhole_r5.json`, `compromised_r7.json`)
9. P7 `fetch_topology_zoo.py` + `compare.py --topology ...`; `export_mininet.py`; `packet_tracer.py export`
10. Evaluation: `explain_quality.py`; `label_sensitivity.py --quick`; `attack_drift.py`
11. `run_tests.py`

---

## 4. Agent rule (when implementing)

For each new runnable step:

1. Add a script under `projects/xai-dynamic-routing/scripts/` that runs with `python scripts/<name>.py`.
2. Wire it into `scripts/run.ps1` and, if it is a main step, `scripts/demo.py`.
3. Update the table above with **Ready?** and **Expected** taken from a real run.
4. Update [phase-execution-status.md](phase-execution-status.md) before commit.
