# Computer Networks — reference

Read from `SKILL.md` when the task needs layout, formulas, or topic mapping. Keep this file updated when the user adds course-specific rules.

## Repo layout

Course labs:

```
labs/
  lab<NN>-<short-name>/
    README.md
    *.py
reports/               # only if the user asks for a write-up
```

Example: `labs/lab01-crc/crc.py`

Socket pairs live in the same lab folder: `server.py` and `client.py`.

Capstone (Title 4 — XAI dynamic routing): `projects/xai-dynamic-routing/`. Layout: `docs/xai-dynamic-routing-overview.md` section 12. Phases, dependencies, and checklists: `docs/xai-dynamic-routing-phase-plan.md`. Live execution status: `docs/phase-execution-status.md` (refresh before every commit). Operator commands: `docs/execution-plan.md` (always ship a runnable script; no `python -c`-only verification). After finishing a phase, tick that checklist in the phase-plan file. Put new routing/XAI code under the project folder, not under `labs/`.

Faults are logged in `docs/fault-ledger.md`. Do **not** apply those fixes unless the user names the fault ID(s) and explicitly approves correction.

## Topic map (typical VIT CSE CN)

Use this to pick the right algorithm and OSI layer. Adjust if the user names a different syllabus item.

| Area | Typical tasks | Layer |
|------|----------------|-------|
| Intro | OSI vs TCP/IP, encapsulation | all |
| Physical / link | CRC, Hamming, parity, framing | 1–2 |
| Flow / error control | Stop-and-wait, GBN, SR, sliding window | 2 / 4 |
| Network | IP classes, subnetting, CIDR, VLSM | 3 |
| Routing | Dijkstra, Bellman-Ford, distance vector vs link state | 3 |
| Transport | TCP vs UDP, ports, 3-way handshake (explain only) | 4 |
| Sockets | TCP/UDP client–server, concurrent server | 4–7 |
| Application | HTTP, DNS, SMTP, FTP (message formats, not attacks) | 7 |

## Subnetting (show every step)

Given IP + prefix or mask:

1. Address class (if classful) and default mask.
2. Network bits / host bits from the prefix.
3. Block size = `2^(host bits)` for the interesting octet (classful/VLSM as asked).
4. Network address = IP AND mask.
5. Broadcast = network OR host-bits-all-ones.
6. First host = network + 1; last host = broadcast − 1.
7. Number of usable hosts = `2^h − 2` (unless the question uses /31 or /32).

Write binary for the mask octet that changes. State CIDR (`/n`) and dotted mask.

## CRC

1. Align message and generator (divisor).
2. Append `deg(generator)` zeros to the message.
3. XOR divide; remainder is the FCS (same width as degree).
4. Transmitted frame = message + remainder.
5. Receiver: divide frame by generator; remainder 0 ⇒ no detected error.

Name the polynomial if given (`CRC-12`, `x^3+x+1`, etc.).

## Hamming (single-error correcting)

1. Find number of parity bits `r` with `2^r >= m + r + 1`.
2. Place parity at positions `2^0, 2^1, ...`.
3. Compute each parity over bits whose position has that bit set.
4. Syndrome bits identify the error position (0 = no error).

## Routing

- **Dijkstra**: link-state; non-negative weights; show iteration table (visited, distance, previous).
- **Bellman-Ford**: distance-vector; relax `|V|-1` times; mention negative-cycle check if asked.
- Count-to-infinity and poisoned reverse only when the question is about DV issues.

## Sockets (this course)

- TCP: `SOCK_STREAM` — echo, chat, file transfer labs.
- UDP: `SOCK_DGRAM` — DNS-like query/reply, unreliable send labs.
- Encode strings as UTF-8; for binary headers use `struct`.
- Default: IPv4, `127.0.0.1`. Document the port in the lab README.
- Concurrent TCP server: `threading` or `select`; mention which in the README.

## Lab README template

```markdown
# Lab NN: Title

## Aim
One or two sentences.

## Algorithm / protocol
Numbered steps.

## Run
python server.py
python client.py

## Sample I/O
Paste from a real run.
```

## Faculty / course notes

(Add constraints here as the user provides them: language, port range, submission format, avoid libraries, etc.)
