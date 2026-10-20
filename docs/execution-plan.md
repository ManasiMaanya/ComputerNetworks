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
| **P6** Traffic | **yes** | `python scripts/simulate.py --scenario configs/scenarios/traffic_dynamics.json` | R2→R5, 30 steps under the traffic model; 11 reroutes (flapping between two near-tied paths) |
| **P7** Zoo | **yes** (network) | `python scripts/fetch_topology_zoo.py --name Geant2012` then `python scripts/compare.py --topology data/raw/Geant2012.gml` | 40 nodes / 61 links (from the Zoo authors' mirror when topology-zoo.org is down); delay from distance on 58/61 links; 12-pair comparison |
| **P6/P7** Real traffic | **yes** (network) | Save Abilene's network file from sndlib.put.poznan.pl to `data/raw/sndlib/networks/abilene.txt`, then `python scripts/fetch_sndlib_traffic.py --network abilene --limit 48`, then `python scripts/simulate.py --scenario configs/scenarios/abilene_real_traffic.json` | SNVAng→NYCMng, 48 steps, each a real 5-minute Abilene traffic matrix (Zhang et al.) instead of synthetic dynamics |
| **P7** Mininet | export only | `python scripts/export_mininet.py` | `outputs/mininet/sample_topology_mininet.py` (run on Linux with `sudo`) |
| **P7** Packet Tracer | export + verify | `python scripts/packet_tracer.py export`, then follow `outputs/packet_tracer/GUIDE.md`; `python scripts/packet_tracer.py verify --protocol ospf [--ai] --trace trace.txt` | `build_ospf.js` / `build_rip.js` / `ai_routes.js` for PTBuilder; 3 demo pairs where AI ≠ OSPF with expected tracert paths |
| **Tests** | **yes** | `python scripts/run_tests.py` or `scripts\tests.cmd` | 216 tests OK; LIME test skipped if `lime` is missing; Packet Tracer script tests skipped if Node.js is missing |

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
8. P6 `simulate.py`
9. P7 `fetch_topology_zoo.py` + `compare.py --topology ...`; `export_mininet.py`; `packet_tracer.py export`
10. P6/P7 real traffic: `fetch_sndlib_traffic.py` + `simulate.py --scenario configs/scenarios/abilene_real_traffic.json`
11. `run_tests.py`

---

## 4. Agent rule (when implementing)

For each new runnable step:

1. Add a script under `projects/xai-dynamic-routing/scripts/` that runs with `python scripts/<name>.py`.
2. Wire it into `scripts/run.ps1` and, if it is a main step, `scripts/demo.py`.
3. Update the table above with **Ready?** and **Expected** taken from a real run.
4. Update [phase-execution-status.md](phase-execution-status.md) before commit.
