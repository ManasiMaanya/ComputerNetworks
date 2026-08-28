# Context summary

**Updated:** 2026-08-28 (auto, long thread ≈ high context)

Use this file plus `docs/phase-execution-status.md` instead of replaying the whole chat.

---

## Goal

VIT Title 4: **Explainable AI-Based Dynamic Routing Recommendation** (QoS + `security_risk` as a number, SHAP/LIME). Code: `projects/xai-dynamic-routing/`. Bind **`127.0.0.1:8765`**.

---

## Done

- Project Cursor skill: `.cursor/skills/computer-networks/`
- Docs: overview, phase plan + checklists, execution plan, fault ledger F-001–F-014 (all **open**, no IDs approved), concepts guide + figures, web phase plan, backend/Docker, **API reference** `docs/web/api.md`
- P0: sample graph 8 nodes / 11 edges; `load.py`; `scripts/p0.cmd` / `load_sample.py`
- P0 web: FastAPI `GET /health`, `GET /api/topology`, `GET /`; uvicorn fallback if Docker missing
- Windows: do not run `scripts\web-up.cmd` without `.\` — use `.\scripts\web-up.cmd` from `projects\xai-dynamic-routing`
- Docker: **not** installed in WSL / not at default Program Files path
- GitHub: `https://github.com/ManasiMaanya/ComputerNetworks` — latest pushed commit **`8f59833`**. Local may have **uncommitted** web-up uvicorn fallback + API doc
- `origin` is **SSH** (`git@github.com:...`). Windows `git push` failed host-key; push used **HTTPS**. WSL has ed25519 key; user must add **public** key on GitHub for WSL SSH push
- Git user.name/email not in config; commits used `Manasi_Maanya` / `manasi.maanya@outlook.com` via env for one-off commits

---

## Next

1. Run demo: `cd projects\xai-dynamic-routing` → `.\.venv\Scripts\activate.bat` → `pip install -r requirements.txt` → `.\scripts\web-up.cmd` → http://127.0.0.1:8765/ → `.\scripts\web-test.cmd` expects `health ok`, `nodes 8 edges 11`, `ok`
2. Commit/push leftover docs and web-up.cmd fallback when the user asks
3. **Phase 1** when asked: path features + script + `/api/paths` + UI tab

---

## Do not

- Fix fault-ledger items without explicit `approve F-xxx`
- Implement exploits; `security_risk` is a link score
- Mark P1–P7 done
- Skip to Mininet/train before P1–P4

---

## Key commands

```
.\scripts\p0.cmd
.\scripts\web-up.cmd
.\scripts\web-test.cmd
```

API: `docs/web/api.md` · Ops: `docs/web/backend-docker.md` · SSH: `docs/wsl-github-ssh.md`
