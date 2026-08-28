# Fault ledger

**Project:** Explainable AI-Based Dynamic Routing  
**Rule:** Detected faults are logged here. **Do not apply a fix** unless the user names the ID(s) and explicitly approves correction (e.g. “approve F-003 and F-007”).

| Status | Meaning |
|--------|---------|
| `open` | Logged; no fix until approved |
| `approved` | User allowed a fix; work may proceed |
| `corrected` | Fix landed; leave a note in Resolution |
| `rejected` | User declined; do not retry unless they reopen |
| `wontfix` | User accepted the behavior |

Approve by ID. Do not treat “fix everything” as approval unless they list IDs or say “approve all open faults”.

---

## Summary

| ID | Sev | Status | Area | One-line |
|----|-----|--------|------|----------|
| F-001 | Med | open | docs | Title PDF path in overview does not match disk |
| F-002 | Low | open | docs | Overview layout omits `docs/Spec/` and this ledger |
| F-003 | Med | open | process | P0 marked Done while several P0-adjacent gaps remain |
| F-004 | Low | open | process | Standing checklist ticks bind/gitignore inconsistently |
| F-005 | Med | open | code | `load_graph` has no input validation or clear errors |
| F-006 | Med | open | code | Package import assumes cwd = project dir (`src.*`) |
| F-007 | Low | open | code | Silent drop of extra/missing edge attributes |
| F-008 | Info | open | scope | P1–P7 modules are stubs (expected until those phases) |
| F-009 | Low | open | docs | Overview eval asks for a non-explained AI baseline; P5 table does not |
| F-010 | Low | open | docs | “Historical traffic” input is not in sample topology or `EDGE_ATTRS` |
| F-011 | Low | open | skill | Course skill says stdlib sockets; capstone needs ML libs |
| F-012 | Low | open | test | `tests/` has no test for `load_graph` |
| F-013 | Info | open | docs | Title claims *dynamic* routing; dynamics is optional P6 |
| F-014 | Low | open | repo | No `pyproject.toml` / installable package |

---

## Ledger

### F-001 — Wrong PDF path in overview

| | |
|--|--|
| **Severity** | Medium |
| **Status** | open |
| **Where** | `docs/xai-dynamic-routing-overview.md` section 12; source line “Network Project Titles.pdf” |
| **Observed** | File on disk is `docs/Spec/Network Project Titles.pdf`. Overview tree shows `docs/Network Project Titles.pdf`. |
| **Impact** | Broken pointer for anyone following the overview. |
| **Proposed fix** (not applied) | Point the tree and Source line at `docs/Spec/Network Project Titles.pdf`. |

### F-002 — Folder tree out of date

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | Overview section 12 |
| **Observed** | Tree does not list `docs/Spec/`, `docs/fault-ledger.md`, or empty `labs/` / `reports/` gitkeeps. |
| **Impact** | Layout doc drifts from the repo. |
| **Proposed fix** | Update section 12 to match current paths. |

### F-003 — Phase 0 “Done” overstated

| | |
|--|--|
| **Severity** | Medium |
| **Status** | open |
| **Where** | `docs/xai-dynamic-routing-phase-plan.md` status + P0 checklist |
| **Observed** | P0 is all `[x]` and Status **Done**, but: no venv committed (OK), `requirements.txt` not proven installed in a project venv, no `tests` for load, README run fails if `networkx` missing. |
| **Impact** | Next phase may start on a weaker M0 than the checklist implies. |
| **Proposed fix** | Keep M0 `[x]` only for “graph loads with networkx installed”; add an open item for “venv + `pip install -r requirements.txt` verified”, or leave P0 Done and treat install as operator setup. **Needs your call.** |

### F-004 — Standing-rules ticks inconsistent

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | Phase plan §2 standing rules |
| **Observed** | Bind `127.0.0.1` is `[x]` though no server exists (config only). “Do not commit raw dumps” is `[ ]` even though `.gitignore` already excludes `data/raw`, `models`, and generated outputs. |
| **Impact** | Checklist does not reflect repo state. |
| **Proposed fix** | Tick gitignore item `[x]`; either untick bind until a server exists, or note “config only”. |

### F-005 — `load_graph` validation

| | |
|--|--|
| **Severity** | Medium |
| **Status** | open |
| **Where** | `projects/xai-dynamic-routing/src/topology/load.py` |
| **Observed** | Missing file → raw `FileNotFoundError`. Missing `nodes`/`edges`/`u`/`v` → `KeyError`. Invalid JSON → `JSONDecodeError`. Course skill asks for a clear message on bad input. |
| **Impact** | Lab-style traces will be stack traces. |
| **Proposed fix** | Catch and re-raise with a one-line message (path, missing key). |

### F-006 — Imports tied to working directory

| | |
|--|--|
| **Severity** | Medium |
| **Status** | open |
| **Where** | `src/topology/__init__.py` (`from src.topology.load import load_graph`); README `python -c "from src.topology..."` |
| **Observed** | Must run from `projects/xai-dynamic-routing/` with that folder on `PYTHONPATH` (cwd usually enough). From repo root the import fails. |
| **Impact** | Easy to break when running scripts from the repo root. |
| **Proposed fix** | Relative imports inside the package, and/or a small `pyproject.toml` with `pip install -e .`. |

### F-007 — Edge attributes dropped without warning

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | `load.py` `EDGE_ATTRS` filter |
| **Observed** | Unknown JSON keys are ignored. Required attrs missing on an edge still create the edge with a partial attribute set. |
| **Impact** | Later Dijkstra/features can hit `KeyError` on missing `delay`. |
| **Proposed fix** | Require all `EDGE_ATTRS` per edge; error listing the edge `u-v`. |

### F-008 — Phase 1–7 not implemented

| | |
|--|--|
| **Severity** | Info (expected) |
| **Status** | open |
| **Where** | `path_features.py`, `baselines.py`, `recommender.py`, `explain.py`, `graph_sim.py`, `src/evaluate/compare.py`, `scripts/*.py` |
| **Observed** | Docstrings/stubs only; scripts `SystemExit("Phase N: not implemented yet")`. |
| **Impact** | None until those phases start. Not a defect of P0 unless treated as incomplete product. |
| **Proposed fix** | Implement per phase plan when you approve that phase (not a ledger “bugfix” unless you want stubs to raise `NotImplementedError` from functions too). |

### F-009 — Evaluation criteria mismatch

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | Overview §10 vs phase plan P5 |
| **Observed** | Overview: compare OSPF/RIP **and a non-explained AI baseline**. P5 checklist: RIP vs OSPF vs AI only. |
| **Impact** | Report and code may disagree. |
| **Proposed fix** | Add a black-box AI column to P5, or strike that line from overview §10. |

### F-010 — Feature listed but not in data model

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | Overview §4 “Historical traffic statistics”; `EDGE_ATTRS` / sample JSON |
| **Observed** | No field for history/time series on links or paths. |
| **Impact** | P1 feature list vs brief will not match unless deferred. |
| **Proposed fix** | Mark as P6/P7 or add a placeholder `traffic_history` / omit from §4 until then. |

### F-011 — Skill vs capstone libraries

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | `.cursor/skills/computer-networks/SKILL.md` coding rules vs `requirements.txt` |
| **Observed** | Skill: stdlib `socket`/`struct` unless asked otherwise. Capstone correctly uses NetworkX/sklearn/SHAP. |
| **Impact** | Agent might refuse pandas/networkx on this project. |
| **Proposed fix** | In `reference.md`: capstone under `projects/xai-dynamic-routing/` may use packages in that `requirements.txt`. |

### F-012 — No test for M0

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | `projects/xai-dynamic-routing/tests/` |
| **Observed** | Only `.gitkeep`. Phase plan P0 does not require tests; M0 is a manual `python -c`. |
| **Impact** | Load regressions go unnoticed. |
| **Proposed fix** | Add `test_load_sample.py` asserting 8 nodes / 11 edges. |

### F-013 — “Dynamic” in the title vs optional P6

| | |
|--|--|
| **Severity** | Info |
| **Status** | open |
| **Where** | Title vs phase plan P6 |
| **Observed** | First demo (M3) is static sample graph. Dynamic reroute is optional. |
| **Impact** | Viva: title overclaims if P6 is skipped. |
| **Proposed fix** | Keep P6 optional and state in overview that v1 is static recommendation; or make P6 required for submission. **Needs your call.** |

### F-014 — Not an installable package

| | |
|--|--|
| **Severity** | Low |
| **Status** | open |
| **Where** | `projects/xai-dynamic-routing/` |
| **Observed** | No `pyproject.toml` / `setup.cfg`. Relies on cwd imports. |
| **Impact** | Same as F-006. |
| **Proposed fix** | Minimal `pyproject.toml` or document `PYTHONPATH` only. May duplicate F-006. |

---

## How to approve

Reply with IDs, for example:

- `approve F-001, F-005` — fix only those  
- `approve all open except F-013` — fix the rest  
- `reject F-008` — leave stubs as-is  

After a fix, this file should set **Status** to `corrected` and add a one-line **Resolution**.
