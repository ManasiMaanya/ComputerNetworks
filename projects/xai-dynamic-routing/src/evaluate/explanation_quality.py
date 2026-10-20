"""Explanation-quality evaluation across pairs, plus Random Forest seed stability.

`quality_report` runs the per-pair metrics in `src/xai/quality.py`. `model_seed_stability`
retrains the forest with several random seeds on the SAME labeled table (no new data, no CV)
and compares the SHAP vectors and chosen paths for the same queries. That separates model
variance from attribution-method variance: SHAP is deterministic for one forest, but not across
forests.

This is an evaluation of the explained model, not a new recommender. Reports are written by
`scripts/explain_quality.py`.
"""

from __future__ import annotations

import copy
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ..config import project_dir  # noqa: E402
from ..errors import NoPathError  # noqa: E402
from ..features.history import MODEL_COLUMNS  # noqa: E402
from ..routing.dataset import split_groups  # noqa: E402
from ..routing.recommender import (  # noqa: E402
    RouteRecommender,
    fit_model,
    scoring_fingerprint,
)
from ..xai.explain import shap_explanation  # noqa: E402
from ..xai.quality import explanation_quality, rank_stats  # noqa: E402

LIMITATIONS = [
    "Fidelity uses occlusion with the training-background median, a model perturbation rather than a causal intervention.",
    "LIME is a local linear surrogate; its weights are approximate and seed-dependent by construction.",
    "Seed stability compares forests trained on the same table, so it isolates model variance, not data-sampling variance.",
    "Latency is wall-clock on this machine and includes explanation-object construction; it is not a deployment benchmark.",
]


def _mean(values) -> float | None:
    clean = [float(v) for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(clean)) if clean else None


def _path_mean(rows, *keys) -> float | None:
    values = []
    for row in rows:
        value = row
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        values.append(value)
    return _mean(values)


def aggregate_summary(rows: list[dict]) -> dict:
    """Aggregate per-pair quality rows into one summary block."""
    lime_rows = [row for row in rows if row.get("lime", {}).get("available")]
    return {
        "pairs": len(rows),
        "pairs_with_lime": len(lime_rows),
        "shap_fidelity_spearman": _path_mean(rows, "shap", "fidelity", "spearman"),
        "shap_fidelity_top_k_overlap": _path_mean(rows, "shap", "fidelity", "top_k_overlap"),
        "shap_fidelity_comprehensiveness_advantage": _path_mean(
            rows, "shap", "fidelity", "comprehensiveness_advantage"),
        "shap_fidelity_sufficiency_advantage": _path_mean(
            rows, "shap", "fidelity", "sufficiency_advantage"),
        "lime_fidelity_spearman": _path_mean(lime_rows, "lime", "fidelity", "spearman"),
        "lime_fidelity_top_k_overlap": _path_mean(lime_rows, "lime", "fidelity", "top_k_overlap"),
        "shap_lime_spearman": _path_mean(lime_rows, "lime", "agreement_with_shap", "spearman"),
        "shap_lime_top_k_overlap": _path_mean(
            lime_rows, "lime", "agreement_with_shap", "top_k_overlap"),
        "shap_lime_sign_agreement": _path_mean(
            lime_rows, "lime", "agreement_with_shap", "sign_agreement"),
        "lime_seed_spearman": _path_mean(lime_rows, "lime", "seed_stability", "spearman"),
        "lime_seed_top_k_overlap": _path_mean(
            lime_rows, "lime", "seed_stability", "top_k_overlap"),
        "shap_latency_ms_median": _path_mean(rows, "shap", "latency_ms", "median_ms"),
        "shap_latency_ms_p95": _path_mean(rows, "shap", "latency_ms", "p95_ms"),
        "lime_latency_ms_median": _path_mean(lime_rows, "lime", "latency_ms", "median_ms"),
        "lime_latency_ms_p95": _path_mean(lime_rows, "lime", "latency_ms", "p95_ms"),
        "lime_mean_surrogate_r2": _path_mean(lime_rows, "lime", "mean_surrogate_r2"),
    }


def quality_report(recommender, cfg: dict, graph, pairs, *, repeats: int = 3,
                   lime_seeds=(None,), top_k: int = 5, include_lime: bool = True,
                   log=print) -> dict:
    """Per-pair explanation-quality metrics for an already-loaded recommender."""
    rows = []
    for src, dst in pairs:
        try:
            rec = recommender.recommend(graph, src, dst)
        except NoPathError as exc:
            rows.append({"src": src, "dst": dst, "status": "no_path", "note": str(exc)})
            log(f"{src}->{dst}: no path ({exc})")
            continue
        try:
            row = explanation_quality(rec, recommender, cfg, repeats=repeats,
                                      lime_seeds=lime_seeds, top_k=top_k,
                                      include_lime=include_lime)
            row["status"] = "ok"
        except Exception as exc:  # keep evaluating other pairs; the report names the failure
            row = {"src": src, "dst": dst, "status": "error", "note": f"{type(exc).__name__}: {exc}"}
            log(f"{src}->{dst}: explanation-quality error: {row['note']}")
        rows.append(row)
        if row["status"] == "ok":
            shap_rho = row["shap"]["fidelity"].get("spearman")
            lime_rho = (row["lime"].get("agreement_with_shap", {}).get("spearman")
                        if row["lime"].get("available") else None)
            log(f"{src}->{dst}: SHAP fidelity rho={shap_rho if shap_rho is not None else 'n/a'} "
                f"LIME-vs-SHAP rho={lime_rho if lime_rho is not None else 'n/a'}")
    valid = [row for row in rows if row.get("status") == "ok"]
    return {
        "method": "explanation quality: occlusion fidelity, SHAP/LIME agreement, LIME seed stability, latency",
        "top_k": int(top_k),
        "repeats": int(repeats),
        "lime_seeds": list(lime_seeds),
        "pairs": [[str(src), str(dst)] for src, dst in pairs],
        "per_pair": rows,
        "summary": aggregate_summary(valid),
        "limitations": LIMITATIONS,
    }


def _recommender_for(model, cfg: dict) -> RouteRecommender:
    schema = {
        "history_steps": int(cfg["training"]["history_steps"]),
        "scoring_fingerprint": scoring_fingerprint(cfg["scoring"]),
    }
    return RouteRecommender(model, schema, cfg, project_dir(cfg, "models_dir"))


def model_seed_stability(graph, table: pd.DataFrame, cfg: dict, pairs, seeds,
                         *, top_k: int = 5, reference_recommender=None) -> dict:
    """Retrain the forest with each seed on the same table and compare SHAP for the same queries.

    `seeds` are RandomForest `random_state` values. Data generation, the train mask, and the
    query set stay fixed, so differences come from the model alone.
    """
    seeds = [int(seed) for seed in seeds]
    if not seeds:
        return {"seeds": [], "pairs": [], "comparisons": [], "summary": {}}
    train_mask, _ = split_groups(table, cfg["training"]["test_size"], cfg["training"]["seed"])
    train = table[train_mask]
    X_train, y_train = train[list(MODEL_COLUMNS)], train["target"]
    recommenders = []
    for seed in seeds:
        scfg = copy.deepcopy(cfg)
        scfg["training"]["seed"] = seed
        model = fit_model(scfg["training"], X_train, y_train)
        recommenders.append(_recommender_for(model, scfg))

    rows = []
    for src, dst in pairs:
        try:
            recs = [rec.recommend(graph, src, dst) for rec in recommenders]
        except NoPathError:
            continue
        vectors = []
        for rec, recommender in zip(recs, recommenders):
            shap = shap_explanation(recommender.model, rec.X, rec.chosen, None)
            vectors.append({row["feature"]: row["contribution"] for row in shap["contributions"]})
        reference_path = None
        if reference_recommender is not None:
            reference_path = list(reference_recommender.recommend(graph, src, dst).path)
        paths = [list(rec.path) for rec in recs]
        for i in range(1, len(seeds)):
            stats = rank_stats(vectors[0], vectors[i], top_k)
            rows.append({
                "src": src,
                "dst": dst,
                "seed_a": seeds[0],
                "seed_b": seeds[i],
                **stats,
                "same_path": paths[0] == paths[i],
                "path_a": paths[0],
                "path_b": paths[i],
                "reference_path": reference_path,
                "matches_reference_a": (paths[0] == reference_path
                                        if reference_path is not None else None),
                "matches_reference_b": (paths[i] == reference_path
                                        if reference_path is not None else None),
            })
    return {
        "seeds": seeds,
        "pairs": len({(row["src"], row["dst"]) for row in rows}),
        "comparisons": rows,
        "summary": {
            "comparisons": len(rows),
            "mean_spearman": _mean(row["spearman"] for row in rows),
            "mean_top_k_jaccard": _mean(row["top_k_jaccard"] for row in rows),
            "mean_top_k_overlap": _mean(row["top_k_overlap"] for row in rows),
            "mean_sign_agreement": _mean(row["sign_agreement"] for row in rows),
            "path_agreement_rate": _mean(row["same_path"] for row in rows),
            "reference_agreement_rate": _mean(
                [row["matches_reference_a"] for row in rows
                 if row["matches_reference_a"] is not None]
                + [row["matches_reference_b"] for row in rows
                   if row["matches_reference_b"] is not None])
            if reference_recommender is not None else None,
        },
    }


def quality_figure(report: dict, path: Path) -> None:
    """Two panels: agreement/fidelity correlations (with model seeds if present) and latency."""
    summary = report.get("summary", {})
    stability = report.get("model_seed_stability", {}).get("summary", {})
    labels, values = [], []
    for label, key in (
        ("SHAP fidelity", "shap_fidelity_spearman"),
        ("LIME fidelity", "lime_fidelity_spearman"),
        ("SHAP vs LIME", "shap_lime_spearman"),
        ("LIME seed", "lime_seed_spearman"),
    ):
        if summary.get(key) is not None:
            labels.append(label)
            values.append(summary[key])
    if stability.get("mean_spearman") is not None:
        labels.append("RF seed")
        values.append(stability["mean_spearman"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2))
    if labels:
        ax1.bar(labels, values, color="#2471a3")
        ax1.axhline(0, color="black", linewidth=0.8)
        ax1.set_ylim(-1, 1)
        ax1.set_ylabel("rank correlation (1 = identical ranking)")
        ax1.set_title("Attribution agreement / fidelity")
        ax1.tick_params(axis="x", rotation=20)
    else:
        ax1.text(0.5, 0.5, "no correlation metrics", ha="center", va="center")
        ax1.set_axis_off()

    lat_labels, lat_values = [], []
    if summary.get("shap_latency_ms_median") is not None:
        lat_labels.append("SHAP")
        lat_values.append(summary["shap_latency_ms_median"])
    if summary.get("lime_latency_ms_median") is not None:
        lat_labels.append("LIME")
        lat_values.append(summary["lime_latency_ms_median"])
    if lat_labels:
        ax2.bar(lat_labels, lat_values, color="#c0392b")
        ax2.set_ylabel("median ms per explanation")
        ax2.set_title("Explanation latency")
    else:
        ax2.text(0.5, 0.5, "no latency metrics", ha="center", va="center")
        ax2.set_axis_off()
    fig.suptitle("Explanation quality (per-pair medians)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def quality_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    lines = ["# Explanation quality", "",
             f"Top-k = {report['top_k']}, SHAP repeats = {report['repeats']}, "
             f"LIME seeds = {report['lime_seeds']}", "",
             "| Metric | Value |", "|---|---|"]
    for key, value in summary.items():
        if isinstance(value, float):
            lines.append(f"| {key} | {value:.4f} |")
        else:
            lines.append(f"| {key} | {value} |")
    stability = report.get("model_seed_stability", {}).get("summary", {})
    if stability:
        lines += ["", "## Random Forest seed stability", "", "| Metric | Value |", "|---|---|"]
        for key, value in stability.items():
            lines.append(f"| {key} | {value:.4f} |" if isinstance(value, float)
                         else f"| {key} | {value} |")
    lines += ["", "## Per pair", "",
              "| Pair | Path | SHAP fidelity rho | SHAP vs LIME rho | LIME seed rho | SHAP ms | LIME ms |",
              "|---|---|---|---|---|---|---|"]
    for row in report.get("per_pair", []):
        if row.get("status") != "ok":
            lines.append(f"| {row['src']}->{row['dst']} | {row['status']} | | | | | |")
            continue
        shap = row["shap"]
        lime = row["lime"]
        agreements = lime.get("agreement_with_shap", {}) if lime.get("available") else {}
        stability_row = lime.get("seed_stability", {}) if lime.get("available") else {}
        vals = [shap["fidelity"].get("spearman"), agreements.get("spearman"),
                stability_row.get("spearman"), shap["latency_ms"].get("median_ms"),
                lime.get("latency_ms", {}).get("median_ms") if lime.get("available") else None]
        text = ["n/a" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v)) for v in vals]
        lines.append(f"| {row['src']}->{row['dst']} | {'-'.join(row['recommended_path'])} | "
                     + " | ".join(text) + " |")
    lines += ["", "## Limitations", ""] + [f"- {item}" for item in report.get("limitations", [])]
    return "\n".join(lines) + "\n"
