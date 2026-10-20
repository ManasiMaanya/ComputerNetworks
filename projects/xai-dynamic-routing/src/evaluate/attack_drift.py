"""Attribution drift under blackhole / compromised-node attacks.

For each attack and source-destination pair this module compares the SHAP explanation of the
SAME candidate path before and after the attack (and, separately, the chosen path before vs the
chosen path after). The primary drift score is cosine distance between the signed SHAP vectors;
rank correlation and top-k overlap say whether the explanation's ranking moved. A detection
flag asks whether the attack's signal feature (loss for blackhole, risk for compromised) became
more important and entered the top-k.

This is the evaluation behind the "attribution-drift monitoring" idea: an explanation that
suddenly changes shape while traffic metrics move is a candidate alarm, not proof of an attack.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..errors import NoPathError  # noqa: E402
from ..simulate.attacks import SIGNAL_FEATURES, apply_attack  # noqa: E402
from ..xai.explain import shap_explanation  # noqa: E402
from ..xai.quality import drift_metrics  # noqa: E402

LIMITATIONS = [
    "The attack is a metric override on incident links, not a packet-level or exploit simulation.",
    "Drift is measured for one candidate path before/after; a changed candidate set can leave no directly comparable path.",
    "Detection checks the top-k SHAP ranking, not statistical significance across time; a threshold would need calibration.",
    "SHAP values depend on the trained forest and the training background, so absolute magnitudes are model-specific.",
]


def _mean(values) -> float | None:
    clean = [float(v) for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(clean)) if clean else None


def _vector(shap: dict) -> dict[str, float]:
    return {row["feature"]: float(row["contribution"]) for row in shap["contributions"]}


def _rank_of(vector: dict[str, float], feature: str) -> int | None:
    if feature not in vector:
        return None
    magnitude = abs(vector[feature])
    return 1 + sum(abs(value) > magnitude for value in vector.values())


def _signal(kind: str, before: dict, after: dict, before_values, after_values,
            top_k: int) -> dict:
    feature = SIGNAL_FEATURES[kind][0]
    delta = after.get(feature, 0.0) - before.get(feature, 0.0)
    rank_before, rank_after = _rank_of(before, feature), _rank_of(after, feature)
    details = []
    for name in SIGNAL_FEATURES[kind]:
        details.append({
            "feature": name,
            "before_contribution": float(before.get(name, 0.0)),
            "after_contribution": float(after.get(name, 0.0)),
            "delta": float(after.get(name, 0.0) - before.get(name, 0.0)),
            "before_value": float(before_values.get(name, np.nan)),
            "after_value": float(after_values.get(name, np.nan)),
            "rank_before": _rank_of(before, name),
            "rank_after": _rank_of(after, name),
        })
    return {
        "feature": feature,
        "before_contribution": float(before.get(feature, 0.0)),
        "after_contribution": float(after.get(feature, 0.0)),
        "delta": float(delta),
        "rank_before": rank_before,
        "rank_after": rank_after,
        "detected": bool(rank_after is not None and rank_after <= top_k and delta > 0),
        "details": details,
    }


def _candidate_index(rec, nodes) -> int | None:
    labels = [candidate.nodes for candidate in rec.candidates]
    return labels.index(nodes) if nodes in labels else None


def _aggregate_attack(rows: list[dict]) -> dict:
    valid = [row for row in rows if row.get("status") == "ok"]
    avoidable = [row for row in valid if not row["unavoidable"]]
    affected = [row for row in valid if row["attacked_node_on_before_path"]]
    return {
        "pairs": len(rows),
        "evaluated": len(valid),
        "rerouted": sum(bool(row["path_changed"]) for row in valid),
        "reroute_rate": _mean(row["path_changed"] for row in valid),
        "detection_rate": _mean(row["signal"]["detected"] for row in valid),
        "mean_attribution_drift": _mean(row["same_path_drift"]["attribution_drift"]
                                        if row.get("same_path_drift") else None for row in valid),
        "mean_top_k_overlap": _mean(row["same_path_drift"]["top_k_overlap"]
                                    if row.get("same_path_drift") else None for row in valid),
        "mean_spearman": _mean(row["same_path_drift"]["spearman"]
                               if row.get("same_path_drift") else None for row in valid),
        "mean_signal_delta": _mean(row["signal"]["delta"] for row in valid),
        "mean_predicted_cost_delta": _mean(row["predicted_cost_delta"] for row in valid),
        "avoidance_rate": _mean(not row["attacked_node_on_after_path"] for row in avoidable),
        "unavoidable_pairs": sum(row["unavoidable"] for row in valid),
        # The interesting subset: attacks actually on the baseline path (where SHAP should move).
        "affected_pairs": len(affected),
        "affected_reroute_rate": _mean(row["path_changed"] for row in affected),
        "affected_detection_rate": _mean(row["signal"]["detected"] for row in affected),
        "affected_mean_attribution_drift": _mean(
            row["same_path_drift"]["attribution_drift"] if row.get("same_path_drift") else None
            for row in affected),
        "affected_mean_top_k_overlap": _mean(
            row["same_path_drift"]["top_k_overlap"] if row.get("same_path_drift") else None
            for row in affected),
    }


def attack_report(graph, recommender, cfg: dict, attacks, pairs, *, top_k: int = 5,
                  log=print) -> dict:
    """Compare SHAP before/after each attack for every pair."""
    attack_defaults = cfg.get("evaluation", {}).get("attacks")
    reports = []
    for attack in attacks:
        attacked, meta = apply_attack(graph, attack, attack_defaults)
        rows = []
        for src, dst in pairs:
            try:
                before_rec = recommender.recommend(graph, src, dst)
                after_rec = recommender.recommend(attacked, src, dst)
            except NoPathError as exc:
                rows.append({"src": src, "dst": dst, "status": "no_path", "note": str(exc)})
                log(f"{attack.kind} {attack.node} {src}->{dst}: no path ({exc})")
                continue
            before_shap = shap_explanation(recommender.model, before_rec.X, before_rec.chosen, None)
            after_shap = shap_explanation(recommender.model, after_rec.X, after_rec.chosen, None)
            before_vec, after_chosen_vec = _vector(before_shap), _vector(after_shap)
            same_index = _candidate_index(after_rec, before_rec.path)
            if same_index is not None:
                same_shap = shap_explanation(recommender.model, after_rec.X, same_index, None)
                same_vec = _vector(same_shap)
                same_drift = drift_metrics(before_vec, same_vec, top_k)
                signal_after_vec = same_vec
                signal_after_values = after_rec.X.iloc[same_index]
            else:
                same_drift = None
                signal_after_vec = after_chosen_vec
                signal_after_values = after_rec.X.iloc[after_rec.chosen]
            signal = _signal(attack.kind, before_vec, signal_after_vec,
                             before_rec.X.iloc[before_rec.chosen], signal_after_values, top_k)
            row = {
                "src": src,
                "dst": dst,
                "status": "ok",
                "before_path": list(before_rec.path),
                "after_path": list(after_rec.path),
                "path_changed": before_rec.path != after_rec.path,
                "predicted_cost_before": float(before_rec.frame.loc[before_rec.chosen, "predicted_cost"]),
                "predicted_cost_after": float(after_rec.frame.loc[after_rec.chosen, "predicted_cost"]),
                "predicted_cost_delta": float(after_rec.frame.loc[after_rec.chosen, "predicted_cost"]
                                             - before_rec.frame.loc[before_rec.chosen, "predicted_cost"]),
                "rule_cost_before": float(before_rec.frame.loc[before_rec.chosen, "rule_cost"]),
                "rule_cost_after": float(after_rec.frame.loc[after_rec.chosen, "rule_cost"]),
                "attacked_node_on_before_path": attack.node in before_rec.path,
                "attacked_node_on_after_path": attack.node in after_rec.path,
                "unavoidable": attack.node in (src, dst),
                "same_path_available": same_index is not None,
                "same_path_drift": same_drift,
                "chosen_path_drift": drift_metrics(before_vec, after_chosen_vec, top_k),
                "signal": signal,
            }
            rows.append(row)
            drift_value = same_drift["attribution_drift"] if same_drift else None
            log(f"{attack.kind} {attack.node} {src}->{dst}: "
                f"{'-'.join(before_rec.path)} -> {'-'.join(after_rec.path)}  "
                f"drift={drift_value if drift_value is not None else 'n/a'}  "
                f"signal={signal['feature']} {'detected' if signal['detected'] else 'not in top-k'}")
        reports.append({
            "kind": attack.kind,
            "node": attack.node,
            "step": attack.step,
            "effects": meta["effects"],
            "changed_edges": meta["changed_edges"],
            "articulation_point": meta["articulation_point"],
            "degree": meta["degree"],
            "pairs": rows,
            "summary": _aggregate_attack(rows),
        })
    valid_rows = [row for report in reports for row in report["pairs"] if row.get("status") == "ok"]
    affected_rows = [row for row in valid_rows if row["attacked_node_on_before_path"]]
    overall = {
        "attacks": len(reports),
        "pairs": sum(len(report["pairs"]) for report in reports),
        "evaluated": sum(report["summary"]["evaluated"] for report in reports),
        "reroute_rate": _mean(row["path_changed"] for row in valid_rows),
        "detection_rate": _mean(row["signal"]["detected"] for row in valid_rows),
        "mean_attribution_drift": _mean(report["summary"]["mean_attribution_drift"] for report in reports),
        "mean_top_k_overlap": _mean(report["summary"]["mean_top_k_overlap"] for report in reports),
        "mean_signal_delta": _mean(report["summary"]["mean_signal_delta"] for report in reports),
        "affected_pairs": len(affected_rows),
        "affected_reroute_rate": _mean(row["path_changed"] for row in affected_rows),
        "affected_detection_rate": _mean(row["signal"]["detected"] for row in affected_rows),
        "affected_mean_attribution_drift": _mean(
            row["same_path_drift"]["attribution_drift"] if row.get("same_path_drift") else None
            for row in affected_rows),
    }
    return {
        "method": "SHAP attribution drift before/after node attacks (same candidate path)",
        "top_k": int(top_k),
        "attacks": reports,
        "summary": overall,
        "limitations": LIMITATIONS,
    }


def attack_drift_figure(report: dict, path: Path) -> None:
    attacks = report.get("attacks", [])
    if not attacks:
        return
    names = [f"{item['kind']} {item['node']}" for item in attacks]

    def affected(item, key, fallback):
        s = item["summary"]
        return (s.get(key) if s.get("affected_pairs") else s.get(fallback)) or 0.0

    drift = [affected(item, "affected_mean_attribution_drift", "mean_attribution_drift")
             for item in attacks]
    overlap = [affected(item, "affected_mean_top_k_overlap", "mean_top_k_overlap")
               for item in attacks]
    detection = [affected(item, "affected_detection_rate", "detection_rate")
                 for item in attacks]
    avoidance = [item["summary"]["avoidance_rate"] or 0.0 for item in attacks]
    x = np.arange(len(names))
    width = 0.38
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))
    ax1.bar(x - width / 2, drift, width, label="mean cosine drift", color="#c0392b")
    ax1.bar(x + width / 2, overlap, width, label="mean top-k overlap", color="#2471a3")
    ax1.set_xticks(x, names, rotation=20, ha="right")
    ax1.set_ylim(0, max(1.0, max(drift + overlap) * 1.1))
    ax1.set_title("Attribution drift on affected paths")
    ax1.legend(fontsize=8)
    ax2.bar(x - width / 2, detection, width, label="signal in top-k", color="#27ae60")
    ax2.bar(x + width / 2, avoidance, width, label="attack node avoided", color="#7f8c8d")
    ax2.set_xticks(x, names, rotation=20, ha="right")
    ax2.set_ylim(0, 1)
    ax2.set_title("Affected-path detection and avoidance")
    ax2.legend(fontsize=8)
    fig.suptitle("Attribution drift under node attacks")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def attack_drift_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    lines = ["# Attribution drift under attacks", "",
             f"Top-k = {report['top_k']}", "", "## Summary", "", "| Metric | Value |", "|---|---|"]
    for key, value in summary.items():
        lines.append(f"| {key} | {value:.4f} |" if isinstance(value, float) else f"| {key} | {value} |")
    lines += ["", "## Attacks", "",
              "| Attack | Edges | Pairs | Affected | Reroute rate | Drift (all) | Drift (affected) | Detection (affected) | Avoidance |",
              "|---|---|---|---|---|---|---|---|---|"]
    for item in report.get("attacks", []):
        s = item["summary"]
        fmt = lambda value: "n/a" if value is None else f"{value:.4f}"  # noqa: E731
        lines.append(f"| {item['kind']} {item['node']} | {item['changed_edges']} | {s['evaluated']} | "
                     f"{s['affected_pairs']} | {fmt(s['reroute_rate'])} | "
                     f"{fmt(s['mean_attribution_drift'])} | {fmt(s['affected_mean_attribution_drift'])} | "
                     f"{fmt(s['affected_detection_rate'])} | {fmt(s['avoidance_rate'])} |")
    lines += ["", "`Affected` counts pairs whose baseline path used the attacked node. Drift and "
                  "detection on that subset answer the audit question; rates over all pairs are diluted "
                  "by paths the attack never touched.", ""]
    lines += ["", "## Per pair", "",
              "| Attack | Pair | Path hit | Before | After | Drift | Signal | Delta | Rank after | Detected |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for item in report.get("attacks", []):
        for row in item["pairs"]:
            if row.get("status") != "ok":
                continue
            drift = row["same_path_drift"]["attribution_drift"] if row["same_path_drift"] else None
            fmt = lambda value: "n/a" if value is None else f"{value:.4f}"  # noqa: E731
            lines.append(f"| {item['kind']} {item['node']} | {row['src']}->{row['dst']} | "
                         f"{'yes' if row['attacked_node_on_before_path'] else 'no'} | "
                         f"{'-'.join(row['before_path'])} | {'-'.join(row['after_path'])} | "
                         f"{fmt(drift)} | {row['signal']['feature']} | {fmt(row['signal']['delta'])} | "
                         f"{row['signal']['rank_after']} | {row['signal']['detected']} |")
    lines += ["", "## Limitations", ""] + [f"- {item}" for item in report.get("limitations", [])]
    return "\n".join(lines) + "\n"
