"""Labeled training table: one row per candidate path (Phase 3).

Two label modes (config `training.labels`):

  * future_outcome (default, fault F-020): a traffic trace is simulated (src/simulate/traffic.py)
    on the sample topology and on every synthetic graph. At each decision time t a candidate's
    inputs are its current features plus a summary of its last `history_steps` snapshots
    (MODEL_COLUMNS), and its label is the rule cost it actually experiences over the next
    `horizon_steps` (mean of per-step rule costs over t+1..t+H). The model therefore forecasts;
    the label is not a function of its inputs.
  * rule_snapshot: the label is the rule cost of the same snapshot the model sees. Sources are
    perturbed sample snapshots (every metric scaled by exp(N(0, perturbation))) and synthetic
    graphs. The model can at best imitate the rule; kept for comparison with earlier results.

Synthetic graphs are connected Watts-Strogatz graphs with sampled, loosely correlated metrics,
so the model also sees longer paths and other value ranges (e.g. real topologies in P7).

Leakage control: each row carries a `group`. Undirected pairs use an unordered key (A|B), so a
pair and its reverse share a group; sample-graph groups span all time steps / snapshots; each
synthetic graph is one group. Train/test splits are by group, never by row. In future_outcome
mode rows also carry a `period`: training rows only use times whose label window ends before the
held-out period (t + H < t_split), test rows only times t >= t_split; rows in between are unused.
"""

from __future__ import annotations

import copy
from itertools import combinations

import networkx as nx
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import pandas as pd

from ..errors import ModelError, NoPathError
from ..features.history import HISTORY_COLUMNS, HISTORY_SOURCES, history_features
from ..features.path_features import FEATURE_COLUMNS, candidates_frame, enumerate_candidates, extract_features
from ..simulate.traffic import TrafficParams, generate_trace
from ..topology.load import EDGE_ATTRS, clamp_metric, validate_graph_metrics
from .scoring import path_cost

#: Realized-outcome columns (means over the label horizon) kept for evaluation reports.
OUTCOME_COLUMNS = ("future_cost", "future_sum_loss", "future_max_security_risk", "future_mean_congestion")

BANDWIDTH_CHOICES = (10, 20, 40, 50, 80, 100, 200, 1000)


def perturb_graph(graph: nx.Graph, rng: np.random.Generator, scale: float) -> nx.Graph:
    snap = copy.deepcopy(graph)
    for _, _, data in snap.edges(data=True):
        for key in EDGE_ATTRS:
            data[key] = clamp_metric(key, data[key] * float(np.exp(rng.normal(0.0, scale))))
    validate_graph_metrics(snap, "perturbed snapshot")
    return snap


def synthetic_graph(rng: np.random.Generator, n_nodes: int, graph_id: int) -> nx.Graph:
    seed = int(rng.integers(0, 2**31 - 1))
    base = nx.connected_watts_strogatz_graph(n_nodes, 4, 0.3, tries=200, seed=seed)
    graph = nx.relabel_nodes(base, {i: f"G{graph_id}N{i}" for i in base.nodes()})
    for _, _, data in graph.edges(data=True):
        congestion = float(rng.beta(2, 4))
        utilization = clamp_metric("utilization", congestion + rng.normal(0, 0.1))
        data.update({
            "delay": float(rng.uniform(1, 25)),
            "bandwidth": float(rng.choice(BANDWIDTH_CHOICES)),
            "congestion": congestion,
            "utilization": utilization,
            "loss": clamp_metric("loss", 0.001 + 0.08 * congestion**2 + rng.uniform(0, 0.02)),
            "security_risk": float(rng.beta(1.5, 4)),
            "energy": float(rng.uniform(0.8, 1.6)),
            "queue": float(round(20 * utilization * rng.uniform(0.5, 1.2))),
            "reliability": clamp_metric("reliability", 1.0 - rng.uniform(0, 0.2)),
        })
    graph.graph["name"] = f"synthetic-{graph_id}"
    validate_graph_metrics(graph, graph.graph["name"])
    return graph


def pair_group(graph: nx.Graph, src: str, dst: str) -> str:
    if graph.is_directed():
        return f"{src}>{dst}"
    a, b = sorted((src, dst))
    return f"{a}|{b}"


def rows_for_pairs(graph: nx.Graph, pairs, k: int, max_hops: int, *, family: str,
                   snapshot: int, group_fn, strategy: str = "mixed") -> list[pd.DataFrame]:
    frames = []
    for src, dst in pairs:
        try:
            cands = enumerate_candidates(graph, src, dst, k, max_hops, strategy)
        except NoPathError:
            continue
        frame = candidates_frame(cands, src, dst)
        frame.insert(0, "family", family)
        frame.insert(1, "snapshot", snapshot)
        frame.insert(2, "group", group_fn(src, dst))
        frame.insert(3, "query", f"{family}:{snapshot}:{src}>{dst}")
        frames.append(frame)
    return frames


def trace_rows(graph: nx.Graph, pairs, cfg: dict, *, family: str, trace_id: int, steps: int,
               stride: int, seed: int, group_fn) -> list[pd.DataFrame]:
    """future_outcome rows for one simulated trace of `graph` (see module docstring).

    Candidate sets are enumerated once on the t=0 graph: they are ranked by hops and delay,
    neither of which the traffic model changes.
    """
    tcfg = cfg["training"]
    n_hist, horizon = tcfg["history_steps"], tcfg["horizon_steps"]
    snapshots = generate_trace(graph, steps, seed, TrafficParams.from_config(cfg.get("traffic")))
    n_snap = len(snapshots)
    t_split = int(round(n_snap * (1.0 - tcfg["test_time_fraction"])))
    # Decision times per period: training label windows end before t_split; test times start at it.
    times = np.array(list(range(n_hist - 1, t_split - horizon, stride)) + list(range(t_split, n_snap - horizon, stride)))
    if times.size == 0:
        return []
    periods = np.where(times >= t_split, "test", "train")
    tensor = TraceTensor(snapshots)

    frames: list[pd.DataFrame] = []
    cache: dict[tuple, dict] = {}
    for src, dst in pairs:
        try:
            cands = enumerate_candidates(graph, src, dst, cfg["k_candidate_paths"], cfg["max_hops"],
                                         cfg["candidate_strategy"])
        except NoPathError:
            continue
        parts = []
        for cand in cands:
            if cand.nodes not in cache:
                cache[cand.nodes] = _path_columns(tensor, cand.nodes, cfg["scoring"], n_hist, horizon)
            cols = cache[cand.nodes]
            part = {name: values[times] for name, values in cols.items()}
            part.update(t=times, period=periods, path_id=cand.path_id, path=cand.label)
            parts.append(pd.DataFrame(part))
        frame = pd.concat(parts, ignore_index=True)
        frame["family"], frame["snapshot"] = family, trace_id
        frame["group"] = group_fn(src, dst)
        frame["src"], frame["dst"] = src, dst
        frame["query"] = [f"{family}:{trace_id}:{t}:{src}>{dst}" for t in frame["t"]]
        frames.append(frame.sort_values(["t", "path_id"], kind="stable").reset_index(drop=True))
    return frames


class TraceTensor:
    """Edge metrics of a trace as one array [time, edge, metric], for fast path aggregation."""

    def __init__(self, snapshots: list[nx.Graph]):
        first = snapshots[0]
        self.directed = first.is_directed()
        edges = list(first.edges())
        self.index = {self._key(u, v): i for i, (u, v) in enumerate(edges)}
        self.values = np.array([[[float(s.edges[u, v][m]) for m in EDGE_ATTRS] for u, v in edges]
                                for s in snapshots])
        self.metric = {m: i for i, m in enumerate(EDGE_ATTRS)}

    def _key(self, u, v):
        return (str(u), str(v)) if self.directed else frozenset((str(u), str(v)))

    def path(self, nodes) -> np.ndarray:
        """[time, link, metric] for the links of `nodes`."""
        return self.values[:, [self.index[self._key(u, v)] for u, v in zip(nodes, nodes[1:])], :]


def path_feature_series(tensor: TraceTensor, nodes) -> pd.DataFrame:
    """FEATURE_COLUMNS for `nodes` at every time step; same aggregation as extract_features."""
    sub = tensor.path(nodes)
    m = lambda name: sub[:, :, tensor.metric[name]]  # noqa: E731
    return pd.DataFrame({
        "hops": np.full(sub.shape[0], float(sub.shape[1])),
        "sum_delay": m("delay").sum(1), "max_delay": m("delay").max(1),
        "min_bandwidth": m("bandwidth").min(1), "max_security_risk": m("security_risk").max(1),
        "mean_congestion": m("congestion").mean(1), "sum_loss": m("loss").sum(1), "max_loss": m("loss").max(1),
        "mean_energy": m("energy").mean(1), "max_utilization": m("utilization").max(1),
        "max_queue": m("queue").max(1), "min_reliability": m("reliability").min(1),
    }, columns=list(FEATURE_COLUMNS))


def _path_columns(tensor: TraceTensor, nodes, scoring: dict, n_hist: int, horizon: int) -> dict[str, np.ndarray]:
    """Every per-time column for one path, indexed by time (valid for history/horizon-feasible t)."""
    feats = path_feature_series(tensor, nodes)
    cost = path_cost(feats, scoring).to_numpy()
    n = len(feats)
    out = {c: feats[c].to_numpy() for c in FEATURE_COLUMNS}

    def trailing(values: np.ndarray, fn) -> np.ndarray:  # window ending at t (needs t >= n_hist - 1)
        full = np.full(n, np.nan)
        full[n_hist - 1:] = fn(sliding_window_view(values, n_hist), axis=1)
        return full

    def ahead(values: np.ndarray) -> np.ndarray:  # mean over t+1..t+horizon (needs t < n - horizon)
        full = np.full(n, np.nan)
        full[: n - horizon] = sliding_window_view(values[1:], horizon).mean(axis=1)
        return full

    for name, source in HISTORY_SOURCES.items():
        out[f"hist_mean_{name}"] = trailing(out[source], np.mean)
        out[f"hist_max_{name}"] = trailing(out[source], np.max)
    out["rule_cost"] = cost
    out["future_cost"] = ahead(cost)
    out["future_sum_loss"] = ahead(out["sum_loss"])
    out["future_max_security_risk"] = ahead(out["max_security_risk"])
    out["future_mean_congestion"] = ahead(out["mean_congestion"])
    return out


def _sample_pairs(graph: nx.Graph) -> list[tuple[str, str]]:
    nodes = sorted(map(str, graph.nodes()))
    return (list(combinations(nodes, 2)) if not graph.is_directed()
            else [(a, b) for a in nodes for b in nodes if a != b])


def _future_outcome_table(sample_graph: nx.Graph, cfg: dict) -> pd.DataFrame:
    tcfg = cfg["training"]
    rng = np.random.default_rng(tcfg["seed"])
    frames = trace_rows(sample_graph, _sample_pairs(sample_graph), cfg, family="sample", trace_id=0,
                        steps=tcfg["trace_steps"], stride=tcfg["decision_stride"], seed=tcfg["seed"],
                        group_fn=lambda s, d, g=sample_graph: "sample:" + pair_group(g, s, d))
    lo, hi = tcfg["synthetic_nodes"]
    for gid in range(tcfg["synthetic_graphs"]):
        graph = synthetic_graph(rng, int(rng.integers(lo, hi + 1)), gid)
        pairs = list(combinations(sorted(graph.nodes()), 2))
        picks = rng.choice(len(pairs), size=min(15, len(pairs)), replace=False)
        frames += trace_rows(graph, [pairs[i] for i in sorted(picks)], cfg, family="synthetic", trace_id=gid,
                             steps=tcfg["synthetic_trace_steps"], stride=tcfg["synthetic_decision_stride"],
                             seed=int(rng.integers(0, 2**31 - 1)), group_fn=lambda s, d, g=gid: f"synthetic:{g}")
    if not frames:
        raise ModelError("training table is empty: no source/destination pair produced candidates")
    table = pd.concat(frames, ignore_index=True)
    table["target"] = table["future_cost"]
    return table


def build_training_table(sample_graph: nx.Graph, cfg: dict) -> pd.DataFrame:
    """Labeled candidate rows. `target` is the training label (lower is better) for either mode."""
    if cfg["training"]["labels"] == "future_outcome":
        table = _future_outcome_table(sample_graph, cfg)
    else:
        table = _rule_snapshot_table(sample_graph, cfg)
    table["is_best"] = table["target"].eq(table.groupby("query")["target"].transform("min"))
    return table


def _rule_snapshot_table(sample_graph: nx.Graph, cfg: dict) -> pd.DataFrame:
    tcfg = cfg["training"]
    rng = np.random.default_rng(tcfg["seed"])
    k, max_hops = cfg["k_candidate_paths"], cfg["max_hops"]
    frames: list[pd.DataFrame] = []

    sample_pairs = _sample_pairs(sample_graph)
    for snap in range(tcfg["sample_snapshots"]):
        graph = sample_graph if snap == 0 else perturb_graph(sample_graph, rng, tcfg["perturbation"])
        frames += rows_for_pairs(graph, sample_pairs, k, max_hops, family="sample", snapshot=snap,
                                 strategy=cfg["candidate_strategy"],
                                 group_fn=lambda s, d, g=graph: "sample:" + pair_group(g, s, d))

    lo, hi = tcfg["synthetic_nodes"]
    for gid in range(tcfg["synthetic_graphs"]):
        graph = synthetic_graph(rng, int(rng.integers(lo, hi + 1)), gid)
        gnodes = sorted(graph.nodes())
        all_pairs = list(combinations(gnodes, 2))
        picks = rng.choice(len(all_pairs), size=min(15, len(all_pairs)), replace=False)
        frames += rows_for_pairs(graph, [all_pairs[i] for i in sorted(picks)], k, max_hops,
                                 family="synthetic", snapshot=gid,
                                 strategy=cfg["candidate_strategy"],
                                 group_fn=lambda s, d, g=gid: f"synthetic:{g}")

    if not frames:
        raise ModelError("training table is empty: no source/destination pair produced candidates")
    table = pd.concat(frames, ignore_index=True)
    table["rule_cost"] = path_cost(table[list(FEATURE_COLUMNS)], cfg["scoring"]).values
    # Snapshot rows have no history: the window is the snapshot itself (steady state).
    steady = pd.DataFrame([history_features([row]) for row in table[list(FEATURE_COLUMNS)].to_dict("records")])
    table[list(HISTORY_COLUMNS)] = steady[list(HISTORY_COLUMNS)].to_numpy()
    table["target"] = table["rule_cost"]
    table["period"] = "all"
    return table


def split_groups(table: pd.DataFrame, test_size: float, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Boolean train/test masks, splitting each family's groups separately (no group in both).

    When rows carry a time `period` (future_outcome mode), training rows must also be in the
    'train' period and test rows in the 'test' period; 'gap' rows are in neither.
    """
    rng = np.random.default_rng(seed)
    test_groups: set[str] = set()
    for _, fam in table.groupby("family"):
        groups = np.array(sorted(fam["group"].unique()))
        if len(groups) < 2:
            raise ModelError(f"family '{fam['family'].iloc[0]}' has {len(groups)} group(s); need >= 2 to split")
        n_test = max(1, int(round(len(groups) * test_size)))
        test_groups.update(rng.choice(groups, size=n_test, replace=False).tolist())
    test_group = table["group"].isin(test_groups).to_numpy()
    period = table["period"].to_numpy() if "period" in table else np.full(len(table), "all")
    train = ~test_group & np.isin(period, ("train", "all"))
    test = test_group & np.isin(period, ("test", "all"))
    return train, test
