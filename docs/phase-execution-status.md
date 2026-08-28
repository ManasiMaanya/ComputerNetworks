# Phase execution status

**Canonical live board** for Title 4. Checklists and dependencies stay in [xai-dynamic-routing-phase-plan.md](xai-dynamic-routing-phase-plan.md).

**Last updated:** 2026-08-28 (web demo, concepts, Docker commit)

**Rule:** Before every git commit that touches this capstone or its docs, refresh this file: Last updated, phase table, current work, next action, execution log. Keep `docs/execution-plan.md` in sync with scripts the user can run.

---

## Current work

| Field | Value |
|-------|--------|
| **Active phase** | None (P0 complete; P1 not started) |
| **Next action** | P0 CLI: `python scripts/load_sample.py` or `scripts\p0.cmd`. P0 web: `scripts\web-up.cmd` then `http://127.0.0.1:8765/` then `scripts\web-test.cmd`. Then Phase 1. |
| **Blocked by** | — |
| **Faults** | All ledger items `open`; no IDs approved for correction ([fault-ledger.md](fault-ledger.md)) |

---

## Phases

| Phase | Name | Status | Checklist | Evidence (this snapshot) |
|-------|------|--------|-----------|--------------------------|
| P0 | Scaffold | **done** | complete | Tree, sample JSON, `load.py`; CLI `8 11`; P0 webpage + Docker docs |
| P1 | Topology + features | **not_started** | open | `path_features.py` is a docstring only |
| P2 | RIP / OSPF baselines | **not_started** | open | `baselines.py` stub |
| P3 | Labels + recommender | **not_started** | open | `recommender.py` stub; `train.py`/`infer.py` exit unimplemented |
| P4 | SHAP / LIME | **not_started** | open | `explain.py` stub |
| P5 | Compare | **not_started** | open | `compare.py` stubs |
| P6 | Dynamics | **not_started** (optional) | open | `graph_sim.py` stub |
| P7 | Datasets / testbed | **not_started** (later) | open | No Topology Zoo loader |

Statuses: `not_started` · `in_progress` · `blocked` · `done` · `skipped`

---

## Milestones

| ID | After | Meaning | Done |
|----|--------|---------|------|
| M0 | P0 | Sample graph loads | **yes** |
| M1 | P1 | Candidate paths + feature table | no |
| M2 | P2 | RIP path ≠ OSPF path on sample topo | no |
| M3 | P4 | AI path + SHAP/LIME text and figure | no |
| M4 | P5 | RIP vs OSPF vs AI table | no |
| M5 | P6–P7 | Time-varying routes and/or Topology Zoo | no |

---

## This commit (what landed)

Use when staging. Update the list if the commit set changes.

- Concepts guide + figures (`docs/concepts/`)
- Webpage phase plan + backend/Docker docs (`docs/web/`)
- P0 FastAPI/Docker demo, Windows `.cmd` launchers, WSL compose scripts
- WSL GitHub SSH notes (`docs/wsl-github-ssh.md`) and setup script
- Skill / README / execution-plan updates

**Not in this commit as completed work:** P1–P7 implementation.

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

---

## How to update (agent / before commit)

1. Set **Last updated** to today.
2. Set **Active phase** / **Next action** from the repo, not from memory.
3. Change a phase to `done` only if that phase’s checklist in the phase-plan file is fully ticked **and** the exit criterion holds.
4. Append one row to the execution log.
5. Copy the phase/milestone summary into phase-plan §2 if it drifted.
