"""Check the demo API on 127.0.0.1:8765 (run after web-up)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def get(path: str) -> str:
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.URLError as exc:
        print(f"error: cannot reach {url}: {exc}", file=sys.stderr)
        print("Start the demo: .\\scripts\\run.ps1 web-up  (or ./scripts/wsl-web-up.sh in WSL)", file=sys.stderr)
        raise SystemExit(1) from exc


def main() -> int:
    health = json.loads(get("/health"))
    if health.get("status") != "ok":
        print("error: health not ok", health, file=sys.stderr)
        return 1
    print("health:", health)
    topo = json.loads(get("/api/topology"))
    nodes, edges = topo.get("node_count"), topo.get("edge_count")
    print(f"topology: nodes {nodes} edges {edges}")
    if nodes != 8 or edges != 11:
        print("error: expected 8 nodes and 11 edges", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
