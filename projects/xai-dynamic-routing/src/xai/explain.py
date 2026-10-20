"""SHAP and LIME explanations for a recommendation (Phase 4).

Explained output: the Random Forest's PREDICTED PATH COST for one candidate (lower is better) -
with the default future_outcome labels, the cost it expects the path to incur over the next
horizon_steps. Inputs are MODEL_COLUMNS: the 12 path features plus their recent-history summary
(hist_* columns), so an explanation can say e.g. "current congestion is high, but its 5-step mean
is low". The black-box MLP baseline is deliberately never explained.
  * SHAP (TreeExplainer, tree_path_dependent): value_i is feature i's additive contribution so that
    base_value + sum(value_i) == predicted cost. Negative = lowers cost = favors the path.
  * Contrast: SHAP(chosen) - SHAP(other) per feature (runner-up, or the previous path after a
    reroute); sums to the predicted-cost gap.
  * LIME (regression mode, quartile-discretized): weights of a local linear surrogate fitted on
    perturbations of the same instance; sign has the same meaning (positive = raises cost).
These describe the model (a learned predictor of the configured scoring rule's cost). They do not
establish causation or prove that a route is globally optimal.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shap  # noqa: E402

from ..errors import ModelError  # noqa: E402
from ..features.history import MODEL_COLUMNS, MODEL_UNITS  # noqa: E402

SIGN_CONVENTION = ("output = predicted path cost (lower is better); positive contribution raises cost "
                   "(argues against the path), negative lowers cost (argues for it)")


def _ranked(names, values, contributions) -> list[dict]:
    rows = [{"feature": n, "value": float(v), "unit": MODEL_UNITS[n], "contribution": float(c)}
            for n, v, c in zip(names, values, contributions)]
    return sorted(rows, key=lambda r: -abs(r["contribution"]))


def shap_explanation(model, X: pd.DataFrame, chosen: int, contrast: int | None) -> dict:
    explainer = shap.TreeExplainer(model)
    values = np.asarray(explainer.shap_values(X[list(MODEL_COLUMNS)]))
    base = float(np.ravel(explainer.expected_value)[0])
    prediction = model.predict(X[list(MODEL_COLUMNS)])
    result = {
        "method": "shap.TreeExplainer (tree_path_dependent)",
        "base_value": base,
        "prediction": float(prediction[chosen]),
        "additivity_error": float(abs(base + values[chosen].sum() - prediction[chosen])),
        "contributions": _ranked(MODEL_COLUMNS, X.iloc[chosen], values[chosen]),
        "all_candidates": values.tolist(),
    }
    if contrast is not None and contrast != chosen:
        diff = values[chosen] - values[contrast]
        result["contrast"] = {
            "contrast_index": int(contrast),
            "predicted_cost_gap": float(prediction[chosen] - prediction[contrast]),
            "contributions": [
                {**row, "contrast_value": float(X.iloc[contrast][row["feature"]])}
                for row in _ranked(MODEL_COLUMNS, X.iloc[chosen], diff)
            ],
        }
    return result


def lime_explanation(model, X: pd.DataFrame, chosen: int, background: pd.DataFrame,
                     xai_cfg: dict) -> tuple[dict, object | None]:
    try:
        from lime.lime_tabular import LimeTabularExplainer
    except ImportError:
        return {"available": False, "reason": "package 'lime' is not installed (pip install lime)"}, None

    def predict(arr: np.ndarray) -> np.ndarray:
        return model.predict(pd.DataFrame(arr, columns=list(MODEL_COLUMNS)))

    explainer = LimeTabularExplainer(
        background[list(MODEL_COLUMNS)].to_numpy(), feature_names=list(MODEL_COLUMNS),
        mode="regression", discretize_continuous=True, random_state=xai_cfg["seed"])
    exp = explainer.explain_instance(
        X.iloc[chosen][list(MODEL_COLUMNS)].to_numpy(), predict,
        num_features=len(MODEL_COLUMNS), num_samples=xai_cfg["lime_num_samples"])
    weights = sorted(exp.as_list(), key=lambda kv: -abs(kv[1]))
    # lime keeps the intercept per label in a dict; regression results live under label 1, the
    # label as_list() reads by default.
    intercept = exp.intercept
    if isinstance(intercept, dict):
        intercept = intercept.get(1, next(iter(intercept.values())))
    return {
        "available": True,
        "method": "lime.LimeTabularExplainer (regression, quartile discretization)",
        "intercept": float(np.ravel(intercept)[0]),
        "local_prediction": float(np.ravel(exp.local_pred)[0]),
        "model_prediction": float(predict(X.iloc[[chosen]].to_numpy())[0]),
        "surrogate_r2": float(exp.score),
        "weights": [{"condition": cond, "weight": float(w)} for cond, w in weights],
    }, exp


def shap_figure(expl: dict, title: str, path: Path, top_k: int) -> None:
    panels = [("local SHAP: chosen path", expl["shap"]["contributions"])]
    if "contrast" in expl["shap"]:
        panels.append((f"chosen minus {expl['contrast_reason']}", expl["shap"]["contrast"]["contributions"]))
    fig, axes = plt.subplots(1, len(panels), figsize=(6.2 * len(panels), 0.5 * top_k + 2.2), squeeze=False)
    for ax, (name, rows) in zip(axes[0], panels):
        rows = rows[:top_k][::-1]
        vals = [r["contribution"] for r in rows]
        ax.barh([f"{r['feature']} = {r['value']:.3g}" for r in rows], vals,
                color=["#c0392b" if v > 0 else "#2471a3" for v in vals])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_title(name, fontsize=10)
        ax.set_xlabel("contribution to predicted cost (+ raises, - lowers)")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def explain_recommendation(rec, recommender, cfg: dict, stem: str, explanations_dir: Path,
                           figures_dir: Path, *, figures: bool = True, lime: bool = True,
                           contrast_index: int | None = None, contrast_reason: str = "runner-up") -> dict:
    """Explain rec.chosen with SHAP (+ contrast to runner-up or a given candidate) and LIME."""
    if getattr(recommender, "kind", "random_forest") != "random_forest":
        raise ModelError("only the Random Forest recommender is explained; the black-box MLP is not, by design")
    X = rec.X
    xai_cfg = cfg["xai"]
    contrast = rec.runner_up if contrast_index is None else contrast_index
    expl = {
        "src": rec.src,
        "dst": rec.dst,
        "recommended_path": list(rec.path),
        "contrast_path": list(rec.candidates[contrast].nodes) if contrast is not None else None,
        "contrast_reason": contrast_reason,
        "explained_output": "RandomForestRegressor predicted path cost (lower is better)",
        "sign_convention": SIGN_CONVENTION,
        "feature_columns": list(MODEL_COLUMNS),
        "shap": shap_explanation(recommender.model, X, rec.chosen, contrast),
        "candidates": [c.label for c in rec.candidates],
        "files": {},
    }
    lime_exp = None
    if lime:
        expl["lime"], lime_exp = lime_explanation(recommender.model, X, rec.chosen,
                                                  recommender.background(), xai_cfg)
    else:
        expl["lime"] = {"available": False, "reason": "disabled (--no-lime)"}

    explanations_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    if figures:
        shap_png = figures_dir / f"shap_{stem}.png"
        shap_figure(expl, f"{rec.src}->{rec.dst}: {'-'.join(rec.path)}  "
                          f"(pred cost {expl['shap']['prediction']:.3f}, base {expl['shap']['base_value']:.3f})",
                    shap_png, xai_cfg["top_k"])
        expl["files"]["shap_figure"] = str(shap_png)
        if lime_exp is not None:
            lime_png = figures_dir / f"lime_{stem}.png"
            fig = lime_exp.as_pyplot_figure()
            fig.set_size_inches(8, 0.45 * len(MODEL_COLUMNS) + 1.5)
            fig.axes[0].set_title(f"LIME local surrogate: {'-'.join(rec.path)} (+ raises predicted cost)",
                                  fontsize=10)
            fig.tight_layout()
            fig.savefig(lime_png, dpi=120)
            plt.close(fig)
            expl["files"]["lime_figure"] = str(lime_png)
    json_path = explanations_dir / f"explain_{stem}.json"
    expl["files"]["json"] = str(json_path)
    json_path.write_text(json.dumps(expl, indent=2), encoding="utf-8")
    return expl


def format_explanation(expl: dict, top_k: int) -> list[str]:
    s = expl["shap"]
    lines = [f"explained output: {expl['explained_output']}",
             f"SHAP base value {s['base_value']:.4f} + contributions = prediction {s['prediction']:.4f} "
             f"(additivity error {s['additivity_error']:.1e})",
             "top SHAP contributions (+ raises cost / against, - lowers cost / for):"]
    for r in s["contributions"][:top_k]:
        verdict = "favors path" if r["contribution"] < 0 else "penalizes path"
        lines.append(f"  {r['feature']:<18} = {r['value']:<9.4g} {r['unit']:<20} {r['contribution']:+.4f}  {verdict}")
    positives = [r for r in s["contributions"] if r["contribution"] > 0][:3]
    negatives = [r for r in s["contributions"] if r["contribution"] < 0][:3]
    lines.append("strongest for (negative): " + (", ".join(
        f"{r['feature']} {r['contribution']:+.4f}" for r in negatives) or "none"))
    lines.append("strongest against (positive): " + (", ".join(
        f"{r['feature']} {r['contribution']:+.4f}" for r in positives) or "none (no feature raised the cost)"))
    if "contrast" in s:
        c = s["contrast"]
        lines.append(f"why not {expl['contrast_reason']} {'-'.join(expl['contrast_path'])} "
                     f"(predicted cost gap {c['predicted_cost_gap']:+.4f}):")
        for r in c["contributions"][:min(3, top_k)]:
            lines.append(f"  {r['feature']:<18} chosen {r['value']:<8.4g} vs {r['contrast_value']:<8.4g} "
                         f"{r['contribution']:+.4f}")
    lime = expl["lime"]
    if lime.get("available"):
        lines.append(f"LIME (surrogate R^2 {lime['surrogate_r2']:.3f}, local pred {lime['local_prediction']:.4f}):")
        for w in lime["weights"][:top_k]:
            lines.append(f"  {w['condition']:<40} {w['weight']:+.4f}")
    else:
        lines.append(f"LIME: skipped - {lime['reason']}")
    return lines


def explanation_snippet(expl: dict, n: int = 3) -> str:
    return "; ".join(f"{r['feature']}={r['value']:.3g} ({r['contribution']:+.3f})"
                     for r in expl["shap"]["contributions"][:n])
