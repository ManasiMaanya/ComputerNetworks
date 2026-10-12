"""Check the demo API on 127.0.0.1:8765 (run after web-up or web-local).

P0-P2 must answer. P3-P6 need a trained model; without one they report 503 and are listed as
skipped (run `python scripts/train.py`), which is not a failure of the web service itself.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8765"


def call(path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, dict]:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")
    except urllib.error.URLError as exc:
        print(f"error: cannot reach {url}: {exc}", file=sys.stderr)
        print("Start the demo: scripts\\web-local.cmd (no Docker) or scripts\\web-up.cmd (Docker)", file=sys.stderr)
        raise SystemExit(1) from exc


def main() -> int:
    failures, skipped = [], []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
        if not ok:
            failures.append(label)

    code, health = call("/health")
    check("P0 /health", code == 200 and health.get("status") == "ok")
    code, topo = call("/api/topology")
    check("P0 /api/topology", code == 200 and topo.get("node_count") == 8 and topo.get("edge_count") == 11,
          f"nodes {topo.get('node_count')} edges {topo.get('edge_count')}")
    code, cat = call("/api/topologies")
    check("P7 /api/topologies", code == 200 and any(t["id"] == "sample" for t in cat.get("topologies", [])),
          f"{len(cat.get('topologies', []))} topologies")
    q = urllib.parse.urlencode({"src": "R1", "dst": "R7"})
    code, paths = call(f"/api/paths?{q}")
    check("P1 /api/paths", code == 200 and len(paths.get("candidates", [])) >= 1)
    code, base = call(f"/api/baselines?{q}")
    check("P2 /api/baselines", code == 200 and base["rip"]["nodes"] != base["ospf_delay"]["nodes"],
          f"RIP {'-'.join(base.get('rip', {}).get('nodes', []))} vs OSPF {'-'.join(base.get('ospf_delay', {}).get('nodes', []))}")

    model_checks = [
        ("P3 /api/infer", lambda: call("/api/infer", {"src": "R1", "dst": "R7"}), lambda d: bool(d.get("path"))),
        ("P4 /api/explain", lambda: call(f"/api/explain?{q}"), lambda d: "contributions" in d.get("shap", {})),
        ("P5 /api/compare", lambda: call("/api/compare?pairs=R1:R8,R2:R5"), lambda d: len(d.get("rows", [])) >= 6),
        ("P6 /api/simulate", lambda: call("/api/simulate?scenario=sample_incident"), lambda d: len(d.get("steps", [])) == 10),
    ]
    for label, run, valid in model_checks:
        code, data = run()
        if code == 503:
            print(f"skip {label}  (no trained model: run python scripts/train.py)")
            skipped.append(label)
        else:
            check(label, code == 200 and valid(data))

    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("ok" + (f" ({len(skipped)} model check(s) skipped)" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
