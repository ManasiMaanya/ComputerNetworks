---
name: computer-networks
description: >-
  Guides Computer Networks coursework in this VIT repo: labs, socket programs,
  subnetting, CRC/Hamming, routing, TCP/UDP, and protocol write-ups. Use when
  working in ComputerNetworks, writing CN labs or assignments, calculating
  subnets, implementing sockets, explaining OSI/TCP-IP, or adding skill docs
  under .cursor/skills/computer-networks/.
---

# Computer Networks (this repo)

Project skill for `ComputerNetworks`. Read this file first. Put extra skill docs next to it, not in `~/.cursor/skills/`.

## Storage (mandatory)

All skill content for this course lives here:

```
.cursor/skills/computer-networks/
├── SKILL.md          # this file — always follow
├── reference.md      # topics, formulas, lab layout
└── examples.md       # input/output and code patterns
```

When the user asks to add skill knowledge (conventions, formulas, lab notes, faculty constraints):

1. Update `SKILL.md` only if it is a standing rule the agent must always apply.
2. Put long notes, tables, and topic detail in `reference.md`.
3. Put sample programs and expected I/O in `examples.md`.
4. Do not create personal skills for this course.
5. Do not dump course theory into random repo markdown unless the user asked for a report or notes file.

## When to apply

Use this skill for any work in this repository: new labs, debugging sockets, addressing/subnetting, error-control codes, routing algorithms, protocol explanations, lab reports, and extending these skill files.

## Phase execution status (mandatory)

Live board: `docs/phase-execution-status.md`.

Update that file **before the user commits** (and whenever a phase starts, finishes, or blocks): Last updated, phase table, current work, next action, execution log. Tick matching checklists in `docs/xai-dynamic-routing-phase-plan.md`. Do not mark a phase `done` unless its exit criterion is met.

Faults: `docs/fault-ledger.md` — no fix without explicit ID approval.


## Runnable scripts (mandatory)

Always add a script the user can run themselves (`python scripts/<name>.py` or a lab `*.py`). Do not leave verification as `python -c` only.

Keep the operator plan in `docs/execution-plan.md`: what to run, in order, expected output, Ready? yes/no. When a phase is implemented, add the script and a row there the same change.

Windows: PowerShell (`.\scripts\run.ps1 p0`) often blocked by execution policy — prefer `scripts\p0.cmd` and `scripts\web-up.cmd`.

## Default workflow

1. Read `SKILL.md`. Open `reference.md` or `examples.md` only if the task needs them.
2. Match existing folder layout. If the repo is still empty, create the lab as in `reference.md`.
3. Prefer Python 3 unless the user names another language.
4. Keep programs academic: stdin/stdout, comments that map to the protocol or algorithm, no extra frameworks.
5. Explain the network idea briefly, then implement. Do not pad with textbook essays unless asked.
6. Never provide exploit payloads, attack steps, malware, or unauthorized-access help. Protocol teaching and defensive/lab implementations are fine.

## Coding rules

- One concern per file; name files after the protocol or algorithm (`crc.py`, `tcp_server.py`).
- Print steps that would appear in a lab record (divisor, remainder, window, RTT, etc.).
- Validate user input; fail with a clear message.
- Servers bind `127.0.0.1` by default; take port as an argument or prompt.
- Use `socket`, `struct`, and stdlib only unless the user asks otherwise. This applies to `labs/`; the capstone under `projects/xai-dynamic-routing/` is exempt (see `reference.md`) and may use any package listed in its `requirements.txt`.
- Windows is the local OS: use PowerShell-friendly commands; no bash-only one-liners.

## Academic output

For theory or viva-style answers: definition, where it sits in OSI/TCP-IP, how it works (short), then a tiny example. For numeric problems (subnetting, CRC, Hamming): show each step, then box the final answer.

## Additional resources

- Lab layout, syllabus map, formulas: [reference.md](reference.md)
- Socket and algorithm examples: [examples.md](examples.md)
- Operator commands: `docs/execution-plan.md`
- Title 4 CN concepts: `docs/concepts/cn-concepts-xai-routing.md`
- Demo webpage by phase: `docs/web/web-phase-plan.md`
- Backend/Docker ops: `docs/web/backend-docker.md`
