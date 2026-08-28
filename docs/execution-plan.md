# Execution plan

**Who runs this:** you (local PowerShell). The agent must add a script and a row here whenever a phase becomes runnable. Do not rely on `python -c` one-liners as the only way to verify.

**Live status:** [phase-execution-status.md](phase-execution-status.md)  
**Phase design:** [xai-dynamic-routing-phase-plan.md](xai-dynamic-routing-phase-plan.md)  
**Code:** `projects/xai-dynamic-routing/`  
**Concepts:** [concepts/cn-concepts-xai-routing.md](concepts/cn-concepts-xai-routing.md)

Working directory for all commands below: `projects/xai-dynamic-routing`. On Windows, use `scripts\*.cmd` (PowerShell often blocks `.ps1`).

---

## 1. One-time setup

```
cd projects/xai-dynamic-routing
python -m venv .venv
.\.venv\Scripts\activate.bat
pip install -r requirements.txt
```

Stay in the venv for later steps.

---

## 2. What you run (by phase)

| Phase | Ready? | You execute | Expected |
|-------|--------|-------------|----------|
| **P0** Scaffold | **yes** | `python scripts/load_sample.py` or `scripts\p0.cmd` | `nodes: 8` and `edges: 11` |
| **P0 web** | **yes** | `cd` into `projects\xai-dynamic-routing` then `.\scripts\web-up.cmd` | Graph at `http://127.0.0.1:8765/`; `.\scripts\web-test.cmd` prints `ok` |
| **P1** Features | no | *(script to be added with P1)* | Path/feature table `R1`→`R8` |
| **P2** Baselines | no | *(script to be added with P2)* | RIP vs OSPF traces |
| **P3** Train / infer | no | `python scripts/train.py` then `python scripts/infer.py` | Currently exits: not implemented |
| **P4** XAI | no | *(extend infer or new script)* | Path + SHAP/LIME text |
| **P5** Compare | no | `python scripts/compare.py` | Currently exits: not implemented |
| **P6** Dynamics | no | *(script to be added with P6)* | 10-step reroute log |
| **P7** Zoo / testbed | no | *(script to be added with P7)* | Compare on a non-toy graph |

Webpage plan: [web/web-phase-plan.md](web/web-phase-plan.md). Docker install/start/debug/test: [web/backend-docker.md](web/backend-docker.md). API usage and sample JSON: [web/api.md](web/api.md).

---

## 3. P0 — run now

From repo root:

```
cd projects/xai-dynamic-routing
.\.venv\Scripts\activate.bat
python scripts/load_sample.py
```

Or: `scripts\p0.cmd`

If `networkx` is missing, run setup again. Bind address for any later UI: `127.0.0.1` (see `configs/default.json`).

---

## 4. Order (your plan)

1. Setup (venv + pip)  
2. **P0** `load_sample.py` — confirm 8 / 11  
2b. **P0 web:** `cd projects\xai-dynamic-routing` then `.\scripts\web-up.cmd` → `http://127.0.0.1:8765/` → `.\scripts\web-test.cmd`  
3. Wait for P1 script, then run it (`R1` → `R8` table)  
4. P2 baseline script (can overlap P3 after P1)  
5. P3 `train.py` then `infer.py`  
6. P4 explanations  
7. P5 `compare.py`  
8. Optional P6 then P7  

Do not skip to Mininet (P7) before M3 (P4 demo).

---

## 5. Agent rule (when implementing)

For each new phase:

1. Add a script under `projects/xai-dynamic-routing/scripts/` that you can run with `python scripts/<name>.py`.
2. Wire it in `scripts/run.ps1` if it is a named step.
3. Mark **Ready?** yes in the table above and write **Expected** output.
4. Update [phase-execution-status.md](phase-execution-status.md) before commit.
