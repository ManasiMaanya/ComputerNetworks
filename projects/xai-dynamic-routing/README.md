# Explainable AI-Based Dynamic Routing Recommendation

Layer 3 path recommendation using QoS + security features, with SHAP/LIME explanations. Compared later with RIP-like hop count and OSPF-like SPF.

Any local service must bind `127.0.0.1`. Default demo port (if a UI is added later): `8765`.

## Setup

```
cd projects/xai-dynamic-routing
python -m venv .venv
.\.venv\Scripts\activate.bat
pip install -r requirements.txt
```

## Run (Phase 0)

```
python scripts/load_sample.py
```

Or: `.\scripts\run.ps1 p0`

Expected: `nodes: 8` and `edges: 11`. Full operator plan: `docs/execution-plan.md`.

## Webpage (Docker / WSL)

Install, start, debug, test: `docs/web/backend-docker.md`  
What the page shows each phase: `docs/web/web-phase-plan.md`

```
scripts\web-up.cmd
```

Open `http://127.0.0.1:8765/` then `scripts\web-test.cmd`. Stop: `scripts\web-down.cmd`.



## Layout

Layout: `docs/xai-dynamic-routing-overview.md` section 12.  
Phases and dependencies: `docs/xai-dynamic-routing-phase-plan.md`.  
Execution status: `docs/phase-execution-status.md` (refresh before commit).  
Fault ledger: `docs/fault-ledger.md` (no fix without explicit ID approval).
