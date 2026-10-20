"""Run a scenario: mutate metrics each step, re-recommend, explain every reroute (Phase 6).

The recommender sees each candidate's recent history: the previous history_steps - 1 graph
snapshots of this run (before t=0 there is none, so early steps use what exists).
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import pandas as pd  # noqa: E402

from ..features.path_features import FEATURE_COLUMNS, extract_features  # noqa: E402
from ..routing.baselines import ospf_route_from_config, rip_route  # noqa: E402
from ..xai.explain import explain_recommendation, format_explanation  # noqa: E402
from .graph_sim import GraphSimulator, Scenario  # noqa: E402
from .traffic import TrafficParams  # noqa: E402

TRACKED = ("congestion", "loss", "security_risk")
#: Change causes treated as background noise; anything else (scripted events, bursts, incidents) is an event.
BACKGROUND = ("drift", "traffic")


def _path_edges(path) -> set[frozenset]:
    return {frozenset(e) for e in zip(path, path[1:])}


def net_changes(changes: list[dict]) -> list[dict]:
    """Collapse drift + event updates of the same edge metric into one old -> new entry."""
    merged: dict[tuple, dict] = {}
    for c in changes:
        key = (c["edge"], c["metric"])
        if key in merged:
            merged[key]["new"] = c["new"]
            if c["cause"] not in merged[key]["cause"]:
                merged[key]["cause"] += f" + {c['cause']}"
        else:
            merged[key] = dict(c)
    return [c for c in merged.values() if c["new"] != c["old"]]


def apply_hysteresis(rec, prev_path: tuple[str, ...] | None, margin: float) -> int:
    """Anti-flapping (F-021 follow-up): don't reroute away from `prev_path` for a negligible gain.

    If `prev_path` is still among this step's candidates and the model's top pick is not at least
    `margin` (relative) cheaper than it, keep `prev_path` instead of switching. Returns the
    candidate index to use as `rec.chosen`. A reroute still happens immediately whenever the
    previous path drops out of the candidate set (e.g. an edge becomes unusable) or the new pick
    is clearly better, so genuine degradations (sample_incident's risk/congestion events) are not
    delayed -- only near-tied noise-level flips are suppressed.
    """
    if prev_path is None or margin <= 0:
        return rec.chosen
    labels = [c.nodes for c in rec.candidates]
    if prev_path not in labels or labels[rec.chosen] == prev_path:
        return rec.chosen
    prev_idx = labels.index(prev_path)
    new_cost = float(rec.frame.loc[rec.chosen, "predicted_cost"])
    old_cost = float(rec.frame.loc[prev_idx, "predicted_cost"])
    if old_cost <= 0 or new_cost < old_cost * (1 - margin):
        return rec.chosen  # clearly better (or old_cost non-positive, margin undefined): switch
    return prev_idx  # not clearly better: hold the previous path


def reroute_reason(changes: list[dict], old_path, new_path, old_before: dict, old_now: dict) -> dict:
    on_old, on_new = _path_edges(old_path), _path_edges(new_path)
    relevant = []
    for c in net_changes(changes):
        edge = frozenset(c["edge"].split("-", 1))
        where = [name for name, edges in (("previous", on_old), ("new", on_new)) if edge in edges]
        if where:
            relevant.append({**c, "on_path": "+".join(where)})
    relevant.sort(key=lambda c: (c["cause"] in BACKGROUND, -abs(c["new"] - c["old"])))
    feature_deltas = {f: {"before": old_before[f], "now": old_now[f]} for f in FEATURE_COLUMNS
                      if abs(old_now[f] - old_before[f]) > 1e-9}
    return {"metric_changes_on_paths": relevant[:8], "previous_path_feature_changes": feature_deltas}


def run_simulation(graph: nx.Graph, scenario: Scenario, recommender, cfg: dict, out_dir: Path, *,
                   lime: bool = True, figures: bool = True, log=print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    sim = GraphSimulator(graph, scenario, TrafficParams.from_config(cfg.get("traffic")),
                         attack_defaults=cfg.get("evaluation", {}).get("attacks"))
    scenario = sim.scenario  # attacks are expanded into ordinary events here
    past = deque(maxlen=max(recommender.history_steps - 1, 1))
    event_edges = sorted({ev.edge for ev in scenario.events})
    history: list[dict] = []
    prev_rec = prev_features = None
    top_k = cfg["xai"]["top_k"]
    hysteresis_margin = cfg.get("simulation", {}).get("hysteresis_margin", 0.0)

    for t in range(scenario.steps):
        changes = sim.step(t)
        g = sim.graph
        rec = recommender.recommend(g, scenario.src, scenario.dst, history=list(past))
        raw_chosen = rec.chosen
        held_prev = False
        if prev_rec is not None:
            new_chosen = apply_hysteresis(rec, prev_rec.path, hysteresis_margin)
            if new_chosen != rec.chosen:
                rec.chosen = new_chosen
                held_prev = True
        chosen = rec.frame.loc[rec.chosen]
        events = sorted({c["cause"] for c in changes if c["cause"] not in BACKGROUND})
        drift_n = sum(c["cause"] in BACKGROUND for c in changes)
        rerouted = prev_rec is not None and rec.path != prev_rec.path
        record = {
            "step": t,
            "events": events,
            "drift_changes": drift_n,
            "path": "-".join(rec.path),
            "predicted_cost": float(chosen["predicted_cost"]),
            "rule_cost": float(chosen["rule_cost"]),
            "rerouted": rerouted,
            "previous_path": "-".join(prev_rec.path) if prev_rec is not None else None,
            "rip_path": rip_route(g, scenario.src, scenario.dst).label,
            "ospf_path": ospf_route_from_config(g, scenario.src, scenario.dst, cfg).label,
            "candidates": [c.label for c in rec.candidates],
            "held_by_hysteresis": held_prev,
            "model_top_pick": rec.candidates[raw_chosen].label if held_prev else None,
            **{f"{u}-{v}.{m}": float(g.edges[u, v][m]) for u, v in event_edges for m in TRACKED},
        }
        log(f"\nt={t:02d} events: {', '.join(events) or 'none'}  (background drift/traffic updates: {drift_n})")
        if held_prev:
            log(f"      (model's top pick was {record['model_top_pick']}; held previous path, "
                f"hysteresis margin {hysteresis_margin:.0%})")
        for u, v in event_edges:
            log(f"      {u}-{v}: " + ", ".join(f"{m}={g.edges[u, v][m]:.3f}" for m in TRACKED))
        log(f"      AI path: {record['path']}  predicted cost {record['predicted_cost']:.4f}  "
            f"rule cost {record['rule_cost']:.4f}   (OSPF {record['ospf_path']}, RIP {record['rip_path']})")

        explain_now = t == 0 or rerouted
        if rerouted:
            old_now = extract_features(g, prev_rec.path)
            record["reason"] = reroute_reason(changes, prev_rec.path, rec.path, prev_features, old_now)
            log(f"      REROUTE: {record['previous_path']}  ->  {record['path']}")
            for c in record["reason"]["metric_changes_on_paths"][:4]:
                log(f"        {c['edge']} {c['metric']}: {c['old']:.3f} -> {c['new']:.3f}  "
                    f"({c['cause']}; on {c['on_path']} path)")
            for f, d in list(record["reason"]["previous_path_feature_changes"].items())[:4]:
                log(f"        previous path {f}: {d['before']:.4g} -> {d['now']:.4g}")
        if explain_now:
            labels = [c.nodes for c in rec.candidates]
            contrast = labels.index(prev_rec.path) if rerouted and prev_rec.path in labels else None
            expl = explain_recommendation(
                rec, recommender, cfg, f"{scenario.name}_step{t:02d}", out_dir, out_dir,
                figures=figures, lime=lime, contrast_index=contrast,
                contrast_reason="previous path" if contrast is not None else "runner-up")
            record["explanation_file"] = expl["files"]["json"]
            for line in format_explanation(expl, top_k):
                log("      " + line)
        history.append(record)
        prev_rec, prev_features = rec, extract_features(g, rec.path)
        past.append(g.copy())

    frame = pd.DataFrame([{k: v for k, v in r.items() if k not in ("reason", "candidates")} for r in history])
    frame.to_csv(out_dir / "history.csv", index=False)
    result = {"scenario": scenario.name, "description": scenario.description, "src": scenario.src,
              "dst": scenario.dst, "steps": scenario.steps, "seed": scenario.seed,
              "reroutes": int(frame["rerouted"].sum()), "history": history}
    (out_dir / "history.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    if figures:
        timeline_figure(frame, event_edges, out_dir / "timeline.png", scenario)
    return result


def timeline_figure(frame: pd.DataFrame, event_edges, path: Path, scenario: Scenario) -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
    ax1.plot(frame["step"], frame["predicted_cost"], marker="o", label="AI predicted cost (chosen path)")
    ax1.plot(frame["step"], frame["rule_cost"], marker="x", linestyle="--", label="rule cost (chosen path)")
    for _, row in frame[frame["rerouted"]].iterrows():
        ax1.axvline(row["step"], color="#c0392b", alpha=0.4)
        ax1.annotate(row["path"], (row["step"], row["predicted_cost"]), fontsize=7, rotation=20,
                     xytext=(4, 6), textcoords="offset points")
    ax1.annotate(frame.iloc[0]["path"], (0, frame.iloc[0]["predicted_cost"]), fontsize=7,
                 xytext=(4, 6), textcoords="offset points")
    ax1.set_ylabel("path cost (lower is better)")
    ax1.legend(fontsize=8)
    for u, v in event_edges:
        for m in TRACKED:
            ax2.plot(frame["step"], frame[f"{u}-{v}.{m}"], marker=".", label=f"{u}-{v} {m}")
    ax2.set_xlabel("simulation step")
    ax2.set_ylabel("link metric")
    ax2.legend(fontsize=8)
    fig.suptitle(f"Scenario {scenario.name}: {scenario.src}->{scenario.dst} (red lines = reroute)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
