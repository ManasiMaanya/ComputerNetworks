# Backend and Docker

Canonical ops for the Title 4 **demo webpage**. UI evolution: [web-phase-plan.md](web-phase-plan.md).  
Host bind: **`127.0.0.1`**. Host port: **`8765`** (`configs/default.json`).

The process inside Docker listens on `0.0.0.0:8765` so the container port can be published. Compose **must** publish as `127.0.0.1:8765:8765` so the service is not advertised on all LAN interfaces.

---

## 1. What runs

| Piece | Role |
|--------|------|
| `web/app.py` | FastAPI: health, every phase's API (P0–P7), static demo page |
| `web/static/` | Demo page, all tabs P0–P7 (vanilla HTML/JS/CSS, no external libraries) |
| `Dockerfile` | Image: Python 3.12 + app |
| `docker-compose.yml` | One service `web`; mounts `models/` (read-only), `data/raw/` (read-only), `outputs/` |
| NetworkX `src/topology/load.py` | Loads `data/samples/sample_topology.json` |

Later phases add routes on the **same** service (see web-phase-plan.md). Do not add a second public port without documenting it here.

```
Browser (Windows)  -->  127.0.0.1:8765  -->  Docker publish  -->  uvicorn in container
```

---

## 2. Install

### 2.1 Windows + WSL + Docker Desktop (recommended)

1. WSL 2 installed (you have this).  
2. [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with **Use the WSL 2 based engine** and your distro enabled under **Settings → Resources → WSL integration**.  
3. Open a **WSL** terminal. Confirm:

```
docker version
docker compose version
```

Both should print a client and a server. If the server fails, start Docker Desktop and wait until it is running.

### 2.2 Repo path inside WSL

From PowerShell, the repo is often:

```
wsl -e bash -lc "ls /mnt/c/Users/manas/VIT/ComputerNetworks/projects/xai-dynamic-routing"
```

Work in that directory (or your actual username path).

### 2.3 Python venv (optional, without Docker)

Same as [../execution-plan.md](../execution-plan.md) §1, then:

```
pip install -r requirements.txt
```

`fastapi` and `uvicorn` are in `requirements.txt`. Use this for local debug without containers.

---

## 3. Start

### 3.1 Docker (preferred demo)

**From WSL**, in `projects/xai-dynamic-routing`:

```
chmod +x scripts/wsl-web-up.sh scripts/wsl-web-down.sh scripts/wsl-web-test.sh
./scripts/wsl-web-up.sh
```

**From Windows (PowerShell execution policy often blocks `.ps1`):** prefer `.cmd` files:

```
scripts\web-up.cmd
```

Same folder: `scripts\web-down.cmd`, `scripts\web-test.cmd`.

If you still want `run.ps1` for this session only:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 web-up
```

Do **not** need to change the machine-wide execution policy. `web-up.cmd` calls WSL to run `wsl-web-up.sh`.

Wait until health checks succeed. Open a browser:

**http://127.0.0.1:8765/**

### 3.2 Local uvicorn (no Docker)

Windows, no venv activation needed: `scripts\web-local.cmd` (or `.\scripts\run.ps1 web`).

From `projects/xai-dynamic-routing` with venv on:

```
python -m uvicorn web.app:app --host 127.0.0.1 --port 8765
```

Then the same URL. Stop with Ctrl+C.

---

## 4. Stop

WSL:

```
./scripts/wsl-web-down.sh
```

PowerShell:

```
scripts\web-down.cmd
```

Compose equivalent:

```
docker compose down
```

---

## 5. Test

| Test | Command | Expected |
|------|---------|----------|
| Image/API health | `./scripts/wsl-web-test.sh` or `scripts\web-test.cmd` | `ok` and 8 nodes / 11 edges |
| CLI topology (no web) | `python scripts/load_sample.py` | `nodes: 8` `edges: 11` |
| HTTP from WSL | `curl -sS http://127.0.0.1:8765/health` | `{"status":"ok"}` |
| Topology API | `curl -sS http://127.0.0.1:8765/api/topology` | JSON with 8 nodes, 11 edges |

`scripts/web_health.py` checks every phase from Python (Windows or WSL) against `127.0.0.1:8765`:
P0–P2 and P7 must pass; P3–P6 are reported as skipped (not failed) when no trained model exists.

| Phase route | Quick check | Expected |
|-------------|-------------|----------|
| P1 | `curl "http://127.0.0.1:8765/api/paths?src=R1&dst=R8"` | 5 candidates with features |
| P2 | `curl "http://127.0.0.1:8765/api/baselines?src=R1&dst=R7"` | RIP R1-R2-R5-R7, OSPF R1-R3-R5-R7 |
| P3 | `curl -X POST -H "Content-Type: application/json" -d "{\"src\":\"R1\",\"dst\":\"R7\"}" http://127.0.0.1:8765/api/infer` | ranked candidates + black-box pick |
| P4 | `curl "http://127.0.0.1:8765/api/explain?src=R1&dst=R8"` | SHAP, contrast, summary sentence |
| P5 | `curl "http://127.0.0.1:8765/api/compare?pairs=R1:R8,R2:R5"` | 8 rows (4 methods × 2 pairs) |
| P6 | `curl "http://127.0.0.1:8765/api/simulate?scenario=sample_incident"` | 10 steps, reroutes at t=5 and t=8 |
| P7 | `curl http://127.0.0.1:8765/api/topologies` | sample + data/raw networks |

Automated: `python -m unittest tests.test_web` (FastAPI `TestClient`, needs `httpx`; skipped if missing).

The Docker path (§3.1) was not re-run on 2026-10-12 (Docker Desktop did not start on that machine);
the compose file now mounts `models/`, `data/raw/` and `outputs/` so the AI tabs work in the
container once a model is trained on the host.

---

## 6. Debug

### 6.1 Container not starting

```
docker compose ps
docker compose logs web
```

Typical causes: Docker Desktop not running; compose run from the wrong folder; port 8765 already in use.

Port busy:

```
# WSL
ss -ltn | grep 8765
```

Stop the other process or change **only** the **host** port in `docker-compose.yml` and this document together.

### 6.2 Health fails, container is up

- Confirm publish: `docker compose port web 8765`  
- Curl **inside** the container:

```
docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8765/health').read())"
```

If inside works but Windows browser fails: Docker Desktop networking; try `http://127.0.0.1:8765/` not `localhost` if a proxy hijacks localhost; allow WSL/Docker through the firewall for localhost.

### 6.3 Reload code

Compose does not live-reload unless you add a bind mount. **Rebuild** after Python/HTML changes:

```
docker compose up --build -d
```

`wsl-web-up.sh` already uses `--build`.

For fast UI tweaks without rebuild, use local uvicorn (§3.2) with the repo as the working directory.

### 6.4 Python traceback

Logs: `docker compose logs -f web`. Fix the file on the host, rebuild. Do not exec-edit in the container (changes are lost).

### 6.5 WSL vs PowerShell Docker

Use **one** Docker engine. If `docker` works in WSL but not in PowerShell (or the reverse), always start/stop from the side that sees the same engine, or enable Docker Desktop WSL integration for that distro.

### 6.6 PowerShell: running scripts is disabled

Windows **Restricted** policy blocks `.\scripts\run.ps1`. Use `scripts\web-up.cmd` or:

`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run.ps1 web-up`

Do not require a permanent `Set-ExecutionPolicy` change for this course.

For venv, use `.\.venv\Scripts\activate.bat` instead of `Activate.ps1` if `.ps1` is blocked.

---

## 7. File map

| Path | Purpose |
|------|---------|
| `projects/xai-dynamic-routing/Dockerfile` | Image build |
| `projects/xai-dynamic-routing/docker-compose.yml` | Publish `127.0.0.1:8765` |
| `projects/xai-dynamic-routing/.dockerignore` | Keep image small |
| `projects/xai-dynamic-routing/web/app.py` | FastAPI app |
| `projects/xai-dynamic-routing/web/static/` | Demo page |
| `projects/xai-dynamic-routing/scripts/web-local.cmd` | Windows start without Docker (venv uvicorn) |
| `projects/xai-dynamic-routing/scripts/web-up.cmd` | Windows start (no execution-policy issue) |
| `projects/xai-dynamic-routing/scripts/web-down.cmd` | Windows stop |
| `projects/xai-dynamic-routing/scripts/web-test.cmd` | Windows health check |
| `projects/xai-dynamic-routing/scripts/wsl-web-up.sh` | Start |
| `projects/xai-dynamic-routing/scripts/wsl-web-down.sh` | Stop |
| `projects/xai-dynamic-routing/scripts/wsl-web-test.sh` | curl tests |
| `projects/xai-dynamic-routing/scripts/web_health.py` | Python health |

---

## 8. Security / course rules

- Host bind **127.0.0.1** only.  
- No attack simulators, exploit UIs, or scanning tools.  
- `security_risk` is displayed as a number on a link.  
- Do not commit `data/raw/` dumps or large models.

---

## 9. Phase API checklist (docs only until implemented)

| Phase | Route | Status |
|-------|--------|--------|
| 0 | `GET /health` `GET /api/topology` `GET /` | **implemented** |
| 1 | `GET /api/paths` | **implemented** |
| 2 | `GET /api/baselines` | **implemented** |
| 3 | `POST /api/infer` | **implemented** |
| 4 | `GET /api/explain` | **implemented** |
| 5 | `GET /api/compare`, `GET /api/evaluation` | **implemented** |
| 6 | `GET /api/scenarios`, `GET /api/simulate` | **implemented** |
| 7 | `GET /api/topologies` + `?topology=` switch (no upload) | **implemented** |
