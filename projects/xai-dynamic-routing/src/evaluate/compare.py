"""RIP vs OSPF-like vs Q-routing vs AI on the same graph snapshot (Phase 5).

Methods: RIP (hop count), OSPF (Dijkstra on the configured cost), Q-ROUTE (the Q-routing baseline,
src/routing/qrouting.py -- a classical method that, unlike RIP/OSPF, reacts to live congestion) when
a trained model is passed in, AI (the explained Random Forest), and AI-BB (the black-box MLP
baseline, fault F-009) when its model file exists. Both AI methods see the snapshot without traffic
history (steady state); the history-aware comparison on simulated futures is the held-out
evaluation in models/training_report.json.

Every method's path is measured with the same P1 aggregation (extract_features) plus
end-to-end path_loss = 1 - prod(1 - loss_i). Failures are kept as rows with status
'no_path' or 'error', never dropped. `rule_cost` is the AI's own training objective, so it is
reported for reference only; delay, loss, risk, and hops are the method-neutral metrics.
"""

from __future__ import annotations

import random
from itertools import permutations
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ..errors import NoPathError, RoutingProjectError  # noqa: E402
from ..features.path_features import extract_features, path_quality_metrics  # noqa: E402
from ..routing.baselines import ospf_route_from_config, rip_route  # noqa: E402
from ..routing.qrouting import qroute_route  # noqa: E402
from ..routing.scoring import path_cost  # noqa: E402
from ..xai.explain import explanation_snippet, shap_explanation  # noqa: E402

METHODS = ("RIP", "OSPF", "Q-ROUTE", "AI", "AI-BB")
REQUIRED_METRICS = ("sum_delay", "sum_loss", "max_security_risk", "hops")
COLUMNS = ["topology", "src", "dst", "method", "status", "path", "hops", "route_cost", "route_cost_metric",
           "sum_delay", "sum_loss", "path_loss", "max_security_risk", "mean_congestion", "min_bandwidth",
           "min_reliability", "rule_cost", "ai_candidate", "note"]


def _measure(graph: nx.Graph, path, scoring: dict) -> dict:
    feats = extract_features(graph, path)
    quality = path_quality_metrics(graph, path)
    rule = float(path_cost(pd.DataFrame([feats]), scoring).iloc[0])
    return {"hops": int(feats["hops"]), "sum_delay": feats["sum_delay"], "sum_loss": feats["sum_loss"],
            "path_loss": quality["path_loss"], "max_security_risk": feats["max_security_risk"],
            "mean_congestion": feats["mean_congestion"], "min_bandwidth": feats["min_bandwidth"],
            "min_reliability": feats["min_reliability"], "rule_cost": rule}


def compare_pair(graph: nx.Graph, src, dst, cfg: dict, recommender, topology: str, blackbox=None,
                 qmodel=None) -> list[dict]:
    src, dst = str(src), str(dst)
    base = {"topology": topology, "src": src, "dst": dst}
    rows: list[dict] = []
    ai_candidates: set[tuple] = set()

    try:
        rec = recommender.recommend(graph, src, dst)
        ai_candidates = {c.nodes for c in rec.candidates}
        expl = {"shap": shap_explanation(recommender.model, rec.X, rec.chosen, None)}
        rows.append({**base, "method": "AI", "status": "ok", "path": "-".join(rec.path),
                     "route_cost": float(rec.frame.loc[rec.chosen, "predicted_cost"]),
                     "route_cost_metric": "predicted_cost", **_measure(graph, rec.path, cfg["scoring"]),
                     "ai_candidate": True, "note": "SHAP: " + explanation_snippet(expl)})
    except NoPathError as exc:
        rows.append({**base, "method": "AI", "status": "no_path", "note": str(exc)})
    except RoutingProjectError as exc:
        rows.append({**base, "method": "AI", "status": "error", "note": str(exc)})

    if blackbox is not None:
        try:
            bb = blackbox.recommend(graph, src, dst)
            rows.append({**base, "method": "AI-BB", "status": "ok", "path": "-".join(bb.path),
                         "route_cost": float(bb.frame.loc[bb.chosen, "predicted_cost"]),
                         "route_cost_metric": "predicted_cost", **_measure(graph, bb.path, cfg["scoring"]),
                         "ai_candidate": True, "note": "black-box MLP (not explained)"})
        except NoPathError as exc:
            rows.append({**base, "method": "AI-BB", "status": "no_path", "note": str(exc)})
        except RoutingProjectError as exc:
            rows.append({**base, "method": "AI-BB", "status": "error", "note": str(exc)})

    classical = [("RIP", lambda: rip_route(graph, src, dst)),
                ("OSPF", lambda: ospf_route_from_config(graph, src, dst, cfg))]
    if qmodel is not None:
        classical.append(("Q-ROUTE", lambda: qroute_route(graph, src, dst, qmodel)))
    for method, fn in classical:
        try:
            result = fn()
            rows.append({**base, "method": method, "status": "ok", "path": result.label,
                         "route_cost": result.cost, "route_cost_metric": result.cost_metric,
                         **_measure(graph, result.path, cfg["scoring"]),
                         "ai_candidate": result.path in ai_candidates, "note": ""})
        except NoPathError as exc:
            rows.append({**base, "method": method, "status": "no_path", "note": str(exc)})
        except RoutingProjectError as exc:
            rows.append({**base, "method": method, "status": "error", "note": str(exc)})
    order = {m: i for i, m in enumerate(METHODS)}
    return sorted(rows, key=lambda r: order[r["method"]])


def choose_pairs(graph: nx.Graph, cfg: dict, *, explicit=None, all_pairs=False, random_pairs=None,
                 is_sample=False) -> list[tuple[str, str]]:
    nodes = sorted(map(str, graph.nodes()))
    if explicit:
        return [(str(a), str(b)) for a, b in explicit]
    if all_pairs:
        return list(permutations(nodes, 2))
    if is_sample and random_pairs is None:
        return [(a, b) for a, b in cfg["compare"]["pairs"]]
    n = random_pairs or cfg["compare"]["random_pairs"]
    demands = graph.graph.get("demands")
    if demands and random_pairs is None:  # SNDlib: largest traffic demands first
        return [(d["src"], d["dst"]) for d in demands[:n]]
    rng = random.Random(cfg["training"]["seed"])
    every = list(permutations(nodes, 2))
    return sorted(rng.sample(every, min(n, len(every))))


def run_comparison(graph: nx.Graph, pairs, cfg: dict, recommender, topology: str, blackbox=None,
                   qmodel=None) -> pd.DataFrame:
    rows = [row for src, dst in pairs
            for row in compare_pair(graph, src, dst, cfg, recommender, topology, blackbox, qmodel)]
    return pd.DataFrame(rows).reindex(columns=COLUMNS)


def methods_in(frame: pd.DataFrame) -> list[str]:
    return [m for m in METHODS if m in set(frame["method"])]


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    """Mean metrics per method over pairs where every compared method returned a path."""
    methods = methods_in(frame)
    ok = frame[frame["status"] == "ok"]
    complete = ok.groupby(["src", "dst"])["method"].nunique()
    keys = set(complete[complete == len(methods)].index)
    both = ok[[(s, d) in keys for s, d in zip(ok["src"], ok["dst"])]]
    if both.empty:
        return pd.DataFrame()
    summary = both.groupby("method")[["sum_delay", "sum_loss", "path_loss", "max_security_risk", "hops",
                                      "rule_cost"]].mean().reindex(methods)
    summary.insert(0, "pairs", len(keys))
    return summary.reset_index()


def head_to_head(frame: pd.DataFrame) -> dict:
    ok = frame[frame["status"] == "ok"].set_index(["src", "dst", "method"])
    out = {}
    for base in ("RIP", "OSPF", "Q-ROUTE"):
        if base not in set(frame["method"]):
            continue
        stats = {"pairs": 0, "different_path": 0}
        for metric in ("sum_delay", "max_security_risk", "sum_loss", "hops"):
            stats[f"ai_lower_{metric}"] = stats[f"ai_higher_{metric}"] = 0
        for (src, dst), _ in frame.groupby(["src", "dst"]):
            if (src, dst, "AI") not in ok.index or (src, dst, base) not in ok.index:
                continue
            ai, other = ok.loc[(src, dst, "AI")], ok.loc[(src, dst, base)]
            stats["pairs"] += 1
            stats["different_path"] += ai["path"] != other["path"]
            for metric in ("sum_delay", "max_security_risk", "sum_loss", "hops"):
                stats[f"ai_lower_{metric}"] += ai[metric] < other[metric] - 1e-12
                stats[f"ai_higher_{metric}"] += ai[metric] > other[metric] + 1e-12
        out[base] = {k: int(v) for k, v in stats.items()}
    return out


def comparison_figure(frame: pd.DataFrame, path: Path, title: str) -> None:
    ok = frame[frame["status"] == "ok"].copy()
    ok["pair"] = ok["src"] + ">" + ok["dst"]
    pairs = list(dict.fromkeys(ok["pair"]))
    fig, axes = plt.subplots(2, 2, figsize=(max(9, 0.9 * len(pairs) + 4), 7.5))
    methods = methods_in(frame)
    width = 0.8 / len(methods)
    colors = {"RIP": "#7f8c8d", "OSPF": "#2471a3", "Q-ROUTE": "#27ae60", "AI": "#c0392b", "AI-BB": "#d4a017"}
    x = np.arange(len(pairs))
    for ax, metric in zip(axes.ravel(), REQUIRED_METRICS):
        for i, method in enumerate(methods):
            sub = ok[ok["method"] == method].set_index("pair")[metric].reindex(pairs)
            ax.bar(x + (i - (len(methods) - 1) / 2) * width, sub.to_numpy(dtype=float), width, label=method,
                   color=colors[method])
        ax.set_title(metric)
        ax.set_xticks(x)
        ax.set_xticklabels(pairs, rotation=60, ha="right", fontsize=7)
    axes[0, 0].legend()
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def markdown_report(frame: pd.DataFrame, summary: pd.DataFrame, h2h: dict, meta: dict) -> str:
    fmt = lambda v: "" if pd.isna(v) else (f"{v:.4g}" if isinstance(v, (float, np.floating)) else str(v))
    lines = [f"# Routing comparison: {meta['topology']}", ""]
    lines += [f"- {k}: {v}" for k, v in meta.items()]
    lines += ["", "Metrics use the Phase 1 aggregation: `sum_delay` (ms, additive), `sum_loss` (additive "
              "approximation), `path_loss` = 1 - prod(1 - loss_i), `max_security_risk` (bottleneck), `hops`. "
              "`rule_cost` is the AI's training objective and is shown for reference only.", ""]
    if not summary.empty:
        lines += ["## Mean over pairs where every method found a path", "",
                  "| " + " | ".join(summary.columns) + " |", "|" + "---|" * len(summary.columns)]
        lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in summary.itertuples(index=False)]
        lines.append("")
    lines += ["## AI head-to-head (count of pairs)", ""]
    for base, stats in h2h.items():
        lines.append(f"- vs {base}: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    cols = ["src", "dst", "method", "status", "path", "hops", "route_cost", "route_cost_metric", "sum_delay",
            "sum_loss", "path_loss", "max_security_risk", "rule_cost", "note"]
    lines += ["", "## Per pair", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame[cols].itertuples(index=False):
        lines.append("| " + " | ".join(fmt(v).replace("|", "/") for v in row) + " |")
    return "\n".join(lines) + "\n"
