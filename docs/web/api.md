# Demo API reference

**Base URL:** `http://127.0.0.1:8765`  
**Code:** `projects/xai-dynamic-routing/web/app.py`  
**Start the server first:** `cd projects\xai-dynamic-routing` then `.\scripts\web-up.cmd`  
**Ops:** [backend-docker.md](backend-docker.md)  
**UI by phase:** [web-phase-plan.md](web-phase-plan.md)

Interactive try-out (when the server is up): [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs) (Swagger). Alternate: `/redoc`. Machine-readable: `/openapi.json`.

All JSON is UTF-8. Host bind is **127.0.0.1**. There is no API key.

---

## Status of routes

| Method | Path | Phase | Status |
|--------|------|--------|--------|
| `GET` | `/health` | P0 | **implemented** |
| `GET` | `/api/topology` | P0 | **implemented** |
| `GET` | `/` | P0 | **implemented** (HTML) |
| `GET` | `/static/...` | P0 | **implemented** (CSS/JS) |
| `GET` | `/docs` `/redoc` `/openapi.json` | P0 | **implemented** (FastAPI built-in) |
| `GET` | `/api/paths` | P1 | not built |
| `GET` | `/api/baselines` | P2 | not built |
| `POST` | `/api/infer` | P3 | not built |
| `GET` | `/api/explain` | P4 | not built |
| `GET` | `/api/compare` | P5 | not built |
| `GET` | `/api/simulate` | P6 | not built |
| — | larger topology | P7 | not built |

When a later route is added, append a full section here (usage + example output) in the same change.

---

## How to call (Windows)

PowerShell (`Invoke-WebRequest`):

```
cd C:\Users\manas\VIT\ComputerNetworks\projects\xai-dynamic-routing
.\scripts\web-up.cmd
```

Keep that window running. In a **second** PowerShell:

```
Invoke-RestMethod http://127.0.0.1:8765/health
Invoke-RestMethod http://127.0.0.1:8765/api/topology
```

Or browser: paste the URL.  
Or `.\scripts\web-test.cmd` (checks health + topology counts only).

WSL / curl:

```
curl -sS http://127.0.0.1:8765/health
curl -sS http://127.0.0.1:8765/api/topology
```

---

## `GET /health`

**Use.** Liveness check. Does not load the graph.

**Request.** No query, no body.

**Success:** `200`  
**Body:**

```json
{"status": "ok"}
```

**`web-test` prints:** `health: {'status': 'ok'}`

**Errors.** If uvicorn is not running: connection refused (no JSON). `web-test` then prints `error: cannot reach http://127.0.0.1:8765/health`.

---

## `GET /api/topology`

**Use.** Returns the sample lab graph for the webpage (nodes R1–R8, link QoS + `security_risk`).

**Request.** No query. File comes from `configs/default.json` → `sample_topology` (default `data/samples/sample_topology.json`).

**Success:** `200`

**Shape:**

| Field | Type | Meaning |
|--------|------|---------|
| `file` | string | Path relative to the project, `/` separators |
| `node_count` | number | Should be **8** |
| `edge_count` | number | Should be **11** |
| `nodes` | array | `{ "id": "R1" }` … `R8` |
| `edges` | array | One object per undirected link |

**Each edge:**

| Field | Example | Meaning |
|--------|---------|---------|
| `source` | `"R1"` | Endpoint |
| `target` | `"R2"` | Endpoint |
| `delay` | `5` | Link delay (ms in this lab) |
| `bandwidth` | `100` | Capacity |
| `congestion` | `0.2` | 0–1 |
| `loss` | `0.01` | 0–1 |
| `energy` | `1.0` | Lab energy cost |
| `security_risk` | `0.1` | Lab score 0–1, not an attack |
| `utilization` | `0.3` | 0–1 |
| `queue` | `2` | Queue length |
| `reliability` | `0.99` | 0–1 |

**Example output (truncated; real response has 8 nodes and 11 edges):**

```json
{
  "file": "data/samples/sample_topology.json",
  "node_count": 8,
  "edge_count": 11,
  "nodes": [
    {"id": "R1"},
    {"id": "R2"},
    {"id": "R3"},
    {"id": "R4"},
    {"id": "R5"},
    {"id": "R6"},
    {"id": "R7"},
    {"id": "R8"}
  ],
  "edges": [
    {
      "source": "R1",
      "target": "R2",
      "delay": 5,
      "bandwidth": 100,
      "congestion": 0.2,
      "loss": 0.01,
      "energy": 1.0,
      "security_risk": 0.1,
      "utilization": 0.3,
      "queue": 2,
      "reliability": 0.99
    },
    {
      "source": "R1",
      "target": "R3",
      "delay": 12,
      "bandwidth": 40,
      "congestion": 0.5,
      "loss": 0.04,
      "energy": 1.2,
      "security_risk": 0.4,
      "utilization": 0.6,
      "queue": 8,
      "reliability": 0.9
    }
  ]
}
```

**`web-test` prints:**

```
topology: nodes 8 edges 11
ok
```

**Errors:**

| Code | When |
|------|------|
| 500 | Missing `configs/default.json` or topology file (`detail` explains which) |
| connection error | Server not started |

---

## `GET /`

**Use.** Demo webpage (graph + click an edge). Not JSON.

**Success:** `200`, `Content-Type: text/html`. Body is `web/static/index.html`.

**Browser:** open [http://127.0.0.1:8765/](http://127.0.0.1:8765/)

**Error:** `500` if `index.html` is missing.

---

## `GET /static/style.css` and `GET /static/app.js`

**Use.** Page assets. The HTML loads these automatically.

**Success:** `200`, CSS or JavaScript text.

**Example:** [http://127.0.0.1:8765/static/app.js](http://127.0.0.1:8765/static/app.js)

---

## FastAPI extras

| Path | Output |
|------|--------|
| `GET /docs` | Swagger UI to click **Try it out** |
| `GET /redoc` | Alternate docs page |
| `GET /openapi.json` | OpenAPI schema JSON |

---

## Planned APIs (not implemented — do not call yet)

These will return **404** until the matching phase is coded. Intended contracts (from the webpage plan):

| Route | Intended use | Intended success sketch |
|--------|----------------|-------------------------|
| `GET /api/paths?src=R1&dst=R8` | k candidate paths + features | JSON list of paths and numeric columns |
| `GET /api/baselines?src=R1&dst=R8` | RIP-like and OSPF-like traces | Two paths + costs |
| `POST /api/infer` body `{ "src", "dst" }` | AI path | Path + score; 503 if no model |
| `GET /api/explain?src=&dst=` | SHAP/LIME | Feature names + values |
| `GET /api/compare` | RIP vs OSPF vs AI table | Rows of metrics |
| `GET /api/simulate?steps=10` | Dynamic reroute | Per-step path + reason |

---

## Automated check vs full API

| Tool | What it covers |
|------|----------------|
| `.\scripts\web-test.cmd` | `/health` + `node_count`/`edge_count` only |
| This document | Full `/api/topology` field meanings |
| Browser `/` | Human graph; not a JSON test |
