"""Demo web app, phases P0-P7. Bind inside the container is 0.0.0.0; host publish is 127.0.0.1.

Every route reuses the project modules the CLI scripts use, so the page shows exactly what the
scripts compute:

    GET  /health
    GET  /api/topologies                         sample + data/raw files (Topology Zoo, SNDlib)  [P7]
    GET  /api/topology?topology=                 nodes with layout, edges with metrics           [P0]
    GET  /api/paths?topology=&src=&dst=          k candidates + 12 features + rule cost           [P1]
    GET  /api/baselines?topology=&src=&dst=      RIP-like, OSPF-like (delay and 10^8/bw)         [P2]
    POST /api/infer {topology, src, dst}         AI ranking (+ black-box pick if trained)        [P3]
    GET  /api/explain?topology=&src=&dst=&lime=  SHAP, contrast vs runner-up, LIME, summary      [P4]
    GET  /api/compare?topology=&pairs=           RIP vs OSPF vs AI vs AI-BB on several pairs     [P5]
    GET  /api/evaluation                         held-out results from models/training_report    [P3/P5]
    GET  /api/scenarios, /api/simulate?scenario= time-stepped scenario with reroutes             [P6]

Topologies are chosen from a fixed catalog (no uploads, no arbitrary paths). Set XAI_ROUTING_CONFIG
to use a config other than configs/default.json (the tests do).
"""

from __future__ import annotations

import json
import math
import os
import sys
import threading
from pathlib import Path

import networkx as nx
import pandas as pd
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config, output_dir, project_dir, resolve_path  # noqa: E402
from src.errors import ModelError, NoPathError, RoutingProjectError  # noqa: E402
from src.evaluate.compare import choose_pairs, head_to_head, run_comparison, summarize  # noqa: E402
from src.features.history import MODEL_UNITS  # noqa: E402
from src.features.path_features import (  # noqa: E402
    FEATURE_COLUMNS,
    FEATURE_UNITS,
    enumerate_candidates,
    path_quality_metrics,
)
from src.routing.baselines import ospf_route, rip_route  # noqa: E402
from src.routing.recommender import BLACKBOX_FILE, MODEL_FILE, REPORT_FILE, RouteRecommender  # noqa: E402
from src.routing.scoring import path_cost  # noqa: E402
from src.simulate.graph_sim import load_scenario  # noqa: E402
from src.simulate.runner import run_simulation  # noqa: E402
from src.topology.load import EDGE_ATTRS, load_topology  # noqa: E402
from src.topology.provenance import provenance_summary  # noqa: E402
from src.xai.explain import lime_explanation, shap_explanation  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
SAMPLE_ID = "sample"
VIEW_W, VIEW_H, MARGIN = 1000, 600, 45


# ------------------------------------------------------------------ state

class State:
    """Config, topology catalog, and caches. One per app instance."""

    def __init__(self, config_path: str | None):
        self.cfg = load_config(config_path)
        self._lock = threading.Lock()
        self._graphs: dict[str, tuple] = {}
        self._models: dict[bool, tuple] = {}

    # topologies ---------------------------------------------------------
    def catalog(self) -> list[dict]:
        sample = resolve_path(self.cfg["sample_topology"])
        items = [{"id": SAMPLE_ID, "label": f"Sample lab topology ({sample.name})", "group": "Sample",
                  "path": sample}]
        raw = resolve_path(self.cfg["paths"]["raw_dir"])
        if raw.is_dir():
            for f in sorted(raw.iterdir()):
                if f.suffix.lower() in (".gml", ".graphml") and f.is_file():
                    items.append({"id": f"raw/{f.name}", "label": f.name, "group": "data/raw", "path": f})
            for f in sorted((raw / "topology-zoo").rglob("*.gml")):
                items.append({"id": f"zoo/{f.stem}", "label": f.stem, "group": "Topology Zoo", "path": f})
            for f in sorted((raw / "sndlib").rglob("*.txt")):
                if "networks" in f.parts:
                    items.append({"id": f"sndlib/{f.stem}", "label": f.stem, "group": "SNDlib", "path": f})
        return items

    def graph(self, topology_id: str):
        """(graph, name, path, layout) for a catalog id; cached."""
        with self._lock:
            if topology_id in self._graphs:
                return self._graphs[topology_id]
        entry = next((t for t in self.catalog() if t["id"] == topology_id), None)
        if entry is None:
            raise HTTPException(404, f"unknown topology '{topology_id}'; see /api/topologies")
        try:
            graph = load_topology(entry["path"], self.cfg)
        except RoutingProjectError as exc:
            raise HTTPException(422, str(exc)) from exc
        result = (graph, graph.graph.get("name", entry["path"].stem), entry["path"], layout(graph))
        with self._lock:
            self._graphs[topology_id] = result
        return result

    # models -------------------------------------------------------------
    def recommender(self, blackbox: bool = False) -> RouteRecommender:
        models_dir = project_dir(self.cfg, "models_dir")
        path = models_dir / (BLACKBOX_FILE if blackbox else MODEL_FILE)
        mtime = path.stat().st_mtime if path.is_file() else None
        with self._lock:
            cached = self._models.get(blackbox)
            if cached and cached[0] == mtime:
                return cached[1]
        try:
            rec = RouteRecommender.load(models_dir, self.cfg, blackbox=blackbox)
        except ModelError as exc:
            raise HTTPException(503, f"{exc}") from exc
        with self._lock:
            self._models[blackbox] = (mtime, rec)
        return rec

    def blackbox_or_none(self):
        try:
            return self.recommender(blackbox=True)
        except HTTPException:
            return None


def layout(graph: nx.Graph) -> dict[str, tuple[float, float]]:
    """Node positions in a VIEW_W x VIEW_H box: geographic when every node has coordinates."""
    nodes = list(graph.nodes(data=True))
    if not nodes:
        return {}
    coords = [(d.get("latitude"), d.get("longitude")) for _, d in nodes]
    if all(isinstance(la, (int, float)) and isinstance(lo, (int, float)) for la, lo in coords):
        mean_lat = math.radians(sum(la for la, _ in coords) / len(coords))
        raw = {str(n): (lo * math.cos(mean_lat), -la) for (n, _), (la, lo) in zip(nodes, coords)}
    elif nx.is_connected(graph.to_undirected()) and len(nodes) <= 120:
        raw = {str(n): tuple(p) for n, p in nx.kamada_kawai_layout(graph).items()}
    else:
        raw = {str(n): tuple(p) for n, p in nx.spring_layout(graph, seed=7).items()}
    xs, ys = [p[0] for p in raw.values()], [p[1] for p in raw.values()]
    span_x, span_y = (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0
    scale = min((VIEW_W - 2 * MARGIN) / span_x, (VIEW_H - 2 * MARGIN) / span_y)
    off_x = (VIEW_W - span_x * scale) / 2
    off_y = (VIEW_H - span_y * scale) / 2
    return {n: (round(off_x + (x - min(xs)) * scale, 1), round(off_y + (y - min(ys)) * scale, 1))
            for n, (x, y) in raw.items()}


def _num(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{k: _num(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def _measure(graph, path, cfg) -> dict:
    from src.features.path_features import extract_features

    feats = extract_features(graph, path)
    return {**feats, **path_quality_metrics(graph, path),
            "rule_cost": float(path_cost(pd.DataFrame([feats]), cfg["scoring"]).iloc[0])}


def _endpoints(graph, src: str, dst: str) -> None:
    missing = [n for n in (src, dst) if n not in graph]
    if missing:
        raise HTTPException(404, f"unknown node(s) {missing}")
    if src == dst:
        raise HTTPException(422, "source and destination must differ")


def plain_summary(path: list[str], shap: dict, contrast_path: list[str] | None) -> str:
    """One readable sentence from SHAP output (negative contributions favor the path)."""
    favor = [c for c in shap["contributions"] if c["contribution"] < 0][:3]
    against = [c for c in shap["contributions"] if c["contribution"] > 0.02][:1]  # ignore negligible ones
    text = f"{'-'.join(path)} is recommended mainly because of " + ", ".join(
        f"{c['feature']} = {c['value']:.3g}" for c in favor) + "." if favor else \
        f"{'-'.join(path)} is recommended."
    if against:
        text += f" Its main drawback is {against[0]['feature']} = {against[0]['value']:.3g}."
    if contrast_path and "contrast" in shap:
        edge = [c for c in shap["contrast"]["contributions"] if c["contribution"] < 0][:2]
        if edge:
            text += f" Compared with the runner-up {'-'.join(contrast_path)}, it wins on " + ", ".join(
                f"{c['feature']} ({c['value']:.3g} vs {c['contrast_value']:.3g})" for c in edge) + "."
    return text


# ------------------------------------------------------------------ app

def create_app(config_path: str | None = None) -> FastAPI:
    state = State(config_path or os.environ.get("XAI_ROUTING_CONFIG"))
    app = FastAPI(title="XAI dynamic routing demo", version="0.2.0")
    app.state.demo = state
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def revalidate_page_assets(request, call_next):
        """Make browsers re-check the page and its JS/CSS on every load, so a cached older
        version (e.g. the P0-only page) is never mixed with the current HTML."""
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    def guarded(fn):
        try:
            return fn()
        except NoPathError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ModelError as exc:
            raise HTTPException(503, str(exc)) from exc
        except RoutingProjectError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        # Version the asset URLs by file modification time: a changed app.js/style.css gets a
        # new URL, so no browser can pair new HTML with an old cached script or stylesheet.
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for asset in ("style.css", "app.js"):
            version = int((STATIC / asset).stat().st_mtime)
            html = html.replace(f"/static/{asset}\"", f"/static/{asset}?v={version}\"")
        return HTMLResponse(html)

    @app.get("/api/topologies")
    def topologies() -> dict:
        items = state.catalog()
        return {"default": SAMPLE_ID, "topologies": [{k: v for k, v in t.items() if k != "path"} for t in items]}

    @app.get("/api/topology")
    def topology(topology: str = SAMPLE_ID) -> dict:
        graph, name, path, pos = state.graph(topology)
        nodes = [{"id": str(n), "label": str(d.get("label") or n), "x": pos[str(n)][0], "y": pos[str(n)][1]}
                 for n, d in graph.nodes(data=True)]
        edges = []
        for u, v, data in graph.edges(data=True):
            item = {"source": str(u), "target": str(v)}
            item.update({k: data[k] for k in EDGE_ATTRS if k in data})
            if "metric_source" in data:
                item["metric_source"] = data["metric_source"]
            edges.append(item)
        try:
            file = str(path.resolve().relative_to(ROOT)).replace("\\", "/")
        except ValueError:
            file = path.name
        return {"id": topology, "name": name, "file": file, "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(), "components": nx.number_connected_components(
                    graph.to_undirected()), "directed": graph.is_directed(),
                "provenance": provenance_summary(graph), "nodes": nodes, "edges": edges,
                "viewbox": [VIEW_W, VIEW_H]}

    @app.get("/api/paths")
    def paths(src: str, dst: str, topology: str = SAMPLE_ID) -> dict:
        graph = state.graph(topology)[0]
        _endpoints(graph, src, dst)
        cfg = state.cfg

        def run():
            cands = enumerate_candidates(graph, src, dst, cfg["k_candidate_paths"], cfg["max_hops"],
                                         cfg["candidate_strategy"])
            frame = pd.DataFrame([c.features for c in cands], columns=list(FEATURE_COLUMNS))
            costs = path_cost(frame, cfg["scoring"])
            return {"src": src, "dst": dst, "units": FEATURE_UNITS, "columns": list(FEATURE_COLUMNS),
                    "strategy": cfg["candidate_strategy"], "k": cfg["k_candidate_paths"],
                    "candidates": [{"path_id": c.path_id, "nodes": list(c.nodes), "features": c.features,
                                    "rule_cost": float(cost), **path_quality_metrics(graph, c.nodes)}
                                   for c, cost in zip(cands, costs)]}
        return guarded(run)

    @app.get("/api/baselines")
    def baselines(src: str, dst: str, topology: str = SAMPLE_ID) -> dict:
        graph = state.graph(topology)[0]
        _endpoints(graph, src, dst)
        ref = float(state.cfg["ospf_reference_bandwidth_bps"])

        def one(result):
            return {"method": result.method, "nodes": list(result.path), "cost": result.cost,
                    "cost_metric": result.cost_metric, "hops": result.hops,
                    "metrics": _measure(graph, result.path, state.cfg)}

        def run():
            return {"src": src, "dst": dst, "rip": one(rip_route(graph, src, dst)),
                    "ospf_delay": one(ospf_route(graph, src, dst, "delay", ref)),
                    "ospf_inverse_bandwidth": one(ospf_route(graph, src, dst, "inverse_bandwidth", ref)),
                    "configured_ospf_cost": state.cfg["ospf_cost"]}
        return guarded(run)

    @app.post("/api/infer")
    def infer(body: dict = Body(...)) -> dict:
        topology_id = str(body.get("topology", SAMPLE_ID))
        src, dst = str(body.get("src", "")), str(body.get("dst", ""))
        graph = state.graph(topology_id)[0]
        _endpoints(graph, src, dst)
        rec = state.recommender()
        bb = state.blackbox_or_none()

        def run():
            result = rec.recommend(graph, src, dst)
            frame = result.frame.sort_values("rank")
            out = {"src": src, "dst": dst, "path": list(result.path),
                   "labels": rec.schema.get("labels"), "target": rec.schema.get("target"),
                   "stale_scoring": rec.stale_scoring,
                   "note": "one-off query without traffic history: the current snapshot is treated as steady state",
                   "candidates": [{"rank": int(r["rank"]), "path_id": int(r["path_id"]), "nodes": r["path"].split("-"),
                                   "predicted_cost": float(r["predicted_cost"]), "rule_cost": float(r["rule_cost"]),
                                   "hops": float(r["hops"]), "sum_delay": float(r["sum_delay"]),
                                   "max_security_risk": float(r["max_security_risk"]),
                                   "sum_loss": float(r["sum_loss"])} for _, r in frame.iterrows()],
                   "blackbox": None}
            if bb is not None:
                b = bb.recommend(graph, src, dst)
                out["blackbox"] = {"path": list(b.path),
                                   "predicted_cost": float(b.frame.loc[b.chosen, "predicted_cost"])}
            return out
        return guarded(run)

    @app.get("/api/explain")
    def explain(src: str, dst: str, topology: str = SAMPLE_ID, lime: bool = False) -> dict:
        graph = state.graph(topology)[0]
        _endpoints(graph, src, dst)
        rec = state.recommender()

        def run():
            result = rec.recommend(graph, src, dst)
            runner = result.runner_up
            shap = shap_explanation(rec.model, result.X, result.chosen, runner)
            shap.pop("all_candidates", None)
            contrast_path = list(result.candidates[runner].nodes) if runner is not None else None
            out = {"src": src, "dst": dst, "path": list(result.path), "contrast_path": contrast_path,
                   "units": MODEL_UNITS, "shap": shap,
                   "summary": plain_summary(list(result.path), shap, contrast_path),
                   "lime": {"available": False, "reason": "not requested (tick 'include LIME')"}}
            if lime:
                out["lime"] = lime_explanation(rec.model, result.X, result.chosen, rec.background(),
                                               state.cfg["xai"])[0]
            return out
        return guarded(run)

    @app.get("/api/compare")
    def compare(topology: str = SAMPLE_ID, pairs: str | None = Query(None, description="SRC:DST,SRC:DST"),
                random_pairs: int | None = None) -> dict:
        graph, name, path, _ = state.graph(topology)
        rec = state.recommender()
        bb = state.blackbox_or_none()

        def run():
            explicit = None
            if pairs:
                explicit = []
                for item in pairs.split(","):
                    if ":" not in item:
                        raise HTTPException(422, f"bad pair '{item}', expected SRC:DST")
                    a, b = item.split(":", 1)
                    explicit.append((a.strip(), b.strip()))
            chosen = choose_pairs(graph, state.cfg, explicit=explicit, random_pairs=random_pairs,
                                  is_sample=topology == SAMPLE_ID)
            frame = run_comparison(graph, chosen, state.cfg, rec, name, bb)
            summary = summarize(frame)
            return {"topology": name, "pairs": [list(p) for p in chosen], "rows": _records(frame),
                    "summary": _records(summary) if not summary.empty else [],
                    "head_to_head": head_to_head(frame)}
        return guarded(run)

    @app.get("/api/evaluation")
    def evaluation() -> dict:
        report = project_dir(state.cfg, "models_dir") / REPORT_FILE
        if not report.is_file():
            raise HTTPException(503, "no training report; run `python scripts/train.py` first")
        data = json.loads(report.read_text(encoding="utf-8"))
        sel = data.get("test_selection", {})
        return {"labels": data.get("labels"), "target": data.get("target"), "queries": sel.get("queries"),
                "methods": sel.get("methods"), "vs_hop_count": sel.get("vs_hop_count"),
                "vs_snapshot_rule": sel.get("vs_snapshot_rule"), "vs_blackbox": sel.get("vs_blackbox"),
                "test_regression": data.get("test_regression"),
                "blackbox_test_regression": data.get("blackbox_test_regression"),
                "feature_importance": dict(list(data.get("feature_importance_impurity", {}).items())[:8])}

    def scenario_files() -> dict[str, Path]:
        folder = resolve_path("configs/scenarios")
        return {f.stem: f for f in sorted(folder.glob("*.json"))}

    @app.get("/api/scenarios")
    def scenarios() -> dict:
        out = []
        for sid, f in scenario_files().items():
            sc = load_scenario(f)
            out.append({"id": sid, "name": sc.name, "description": sc.description, "src": sc.src,
                        "dst": sc.dst, "steps": sc.steps, "traffic": sc.traffic, "events": len(sc.events),
                        "topology": sc.topology})
        return {"default": Path(state.cfg["simulation"]["scenario"]).stem, "scenarios": out}

    @app.get("/api/simulate")
    def simulate(scenario: str) -> dict:
        files = scenario_files()
        if scenario not in files:
            raise HTTPException(404, f"unknown scenario '{scenario}'; see /api/scenarios")
        rec = state.recommender()

        def run():
            sc = load_scenario(files[scenario])
            if sc.topology:
                graph = load_topology(resolve_path(sc.topology), state.cfg)
                topo_id = None
            else:
                graph, topo_id = state.graph(SAMPLE_ID)[0], SAMPLE_ID
            out_dir = output_dir(state.cfg, "simulations", sc.name)
            result = run_simulation(graph, sc, rec, state.cfg, out_dir, lime=False, figures=False,
                                    log=lambda *_: None)
            steps = []
            for r in result["history"]:
                step = {"step": r["step"], "path": r["path"].split("-"), "rerouted": r["rerouted"],
                        "previous_path": r["previous_path"].split("-") if r["previous_path"] else None,
                        "events": r["events"], "background_updates": r["drift_changes"],
                        "predicted_cost": r["predicted_cost"], "rule_cost": r["rule_cost"],
                        "rip_path": r["rip_path"].split("-"), "ospf_path": r["ospf_path"].split("-"),
                        "watched": {k: v for k, v in r.items() if "." in k and "-" in k.split(".")[0]}}
                if "reason" in r:
                    step["changes"] = r["reason"]["metric_changes_on_paths"][:5]
                if r.get("explanation_file"):
                    expl = json.loads(Path(r["explanation_file"]).read_text(encoding="utf-8"))
                    s = expl["shap"]
                    step["explanation"] = {
                        "contrast_reason": expl.get("contrast_reason"), "contrast_path": expl.get("contrast_path"),
                        "top": s["contributions"][:4],
                        "contrast": s.get("contrast", {}).get("contributions", [])[:4]}
                steps.append(step)
            return {"scenario": sc.name, "description": sc.description, "src": sc.src, "dst": sc.dst,
                    "topology": topo_id, "traffic": sc.traffic, "reroutes": result["reroutes"], "steps": steps}
        return guarded(run)

    return app


app = create_app()
