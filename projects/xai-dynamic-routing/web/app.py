"""P0 demo API: health + topology. Bind inside the container is 0.0.0.0; host publish is 127.0.0.1."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.topology.load import EDGE_ATTRS, load_graph

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
CONFIG_PATH = ROOT / "configs" / "default.json"


def _config() -> dict:
    if not CONFIG_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"missing config {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _topology_path() -> Path:
    relative = _config().get("sample_topology", "data/samples/sample_topology.json")
    path = ROOT / relative
    if not path.is_file():
        raise HTTPException(status_code=500, detail=f"missing topology {path}")
    return path


app = FastAPI(title="XAI dynamic routing demo", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/topology")
def api_topology() -> dict:
    path = _topology_path()
    graph = load_graph(path)
    nodes = [{"id": str(n)} for n in graph.nodes()]
    edges = []
    for u, v, data in graph.edges(data=True):
        item = {"source": str(u), "target": str(v)}
        for key in EDGE_ATTRS:
            if key in data:
                item[key] = data[key]
        edges.append(item)
    return {
        "file": str(path.relative_to(ROOT)).replace("\\", "/"),
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "nodes": nodes,
        "edges": edges,
    }


@app.get("/")
def index() -> FileResponse:
    index_file = STATIC / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=500, detail="missing web/static/index.html")
    return FileResponse(index_file)
