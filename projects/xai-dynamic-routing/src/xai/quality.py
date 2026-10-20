"""Explanation-quality metrics: fidelity, stability, SHAP/LIME agreement, latency.

The metrics here answer "how much should I trust this explanation?" rather than "which path
wins?". They are computed on one recommendation at a time:

  * Fidelity: do the attributions identify the features the model actually reacts to? We
    occlude each input feature (replace it with the median of the training background) and
    compare |SHAP| or |LIME| rankings with the resulting change in predicted cost. Reported
    as Spearman rank correlation, top-k overlap, and how much more the top-k features change
    the prediction than a random k-subset (removal and sufficiency variants).
  * SHAP vs LIME agreement: rank correlation, top-k Jaccard/overlap, and sign agreement
    between the two explanation methods for the same instance.
  * LIME seed stability: pairwise agreement between LIME runs with different sampling seeds.
  * Latency: wall-clock milliseconds per explanation (median/mean/p95).

Occlusion is a model perturbation, not a causal intervention: replacing a path feature such as
`sum_delay` with a background median can produce a combination that no real path has. The
metrics therefore test faithfulness to the model, not correctness of the route.
"""

from __future__ import annotations

import re
import time

import numpy as np
import pandas as pd

from ..features.history import MODEL_COLUMNS

#: Below this magnitude a contribution is treated as absent for sign agreement.
_SIGN_EPS = 1e-12


def _vector(values) -> dict[str, float]:
    """Normalize a contribution vector to feature -> float.

    Accepts a dict, a list of {'feature', 'contribution'} rows, or a plain sequence aligned
    with MODEL_COLUMNS.
    """
    if isinstance(values, dict):
        return {str(k): float(v) for k, v in values.items()}
    if isinstance(values, (list, tuple)) and values and isinstance(values[0], dict):
        return {str(row["feature"]): float(row.get("contribution", row.get("weight", 0.0)))
                for row in values}
    return {name: float(value) for name, value in zip(MODEL_COLUMNS, values)}


def _aligned(a, b, names=None) -> tuple[list[str], np.ndarray, np.ndarray]:
    a, b = _vector(a), _vector(b)
    names = list(names) if names is not None else sorted(set(a) | set(b))
    return names, np.array([a.get(n, 0.0) for n in names], dtype=float), \
        np.array([b.get(n, 0.0) for n in names], dtype=float)


def top_features(values, k: int) -> list[str]:
    """The k largest-magnitude features, ties broken by feature name (deterministic)."""
    vector = _vector(values)
    ordered = sorted(vector.items(), key=lambda kv: (-abs(kv[1]), kv[0]))
    return [name for name, _ in ordered[:max(int(k), 0)]]


def rank_stats(a, b, top_k: int = 5) -> dict:
    """Agreement between two signed attribution vectors.

    spearman: Pearson correlation of average ranks (equivalent to Spearman; None when either
    vector is constant). top_k_jaccard / top_k_overlap compare the top-k sets by |value|.
    sign_agreement compares the signs of features that are non-zero in both vectors.
    cosine_distance is 1 - cosine similarity (0 = identical direction, 2 = opposite).
    """
    names, x, y = _aligned(a, b)
    k = max(1, min(int(top_k), len(names))) if names else 0
    stats = {"n_features": len(names), "top_k": k, "spearman": None,
             "top_k_jaccard": None, "top_k_overlap": None, "sign_agreement": None,
             "cosine_distance": None, "l1_distance": None, "max_abs_delta": None}
    if not names:
        return stats
    if len(names) >= 2 and np.ptp(x) > 0 and np.ptp(y) > 0:
        stats["spearman"] = float(np.corrcoef(pd.Series(x).rank(), pd.Series(y).rank())[0, 1])
    top_a, top_b = set(top_features(dict(zip(names, x)), k)), set(top_features(dict(zip(names, y)), k))
    if top_a or top_b:
        stats["top_k_jaccard"] = float(len(top_a & top_b) / len(top_a | top_b))
        stats["top_k_overlap"] = float(len(top_a & top_b) / k)
    both = (np.abs(x) > _SIGN_EPS) & (np.abs(y) > _SIGN_EPS)
    if both.any():
        stats["sign_agreement"] = float(np.mean(np.sign(x[both]) == np.sign(y[both])))
    nx, ny = float(np.linalg.norm(x)), float(np.linalg.norm(y))
    if nx > 0 or ny > 0:
        stats["cosine_distance"] = float(1.0 - (float(np.dot(x, y)) / (nx * ny) if nx and ny else 0.0))
        stats["l1_distance"] = float(np.abs(x - y).sum())
        stats["max_abs_delta"] = float(np.abs(x - y).max())
    return stats


def parse_lime_weights(lime: dict) -> dict[str, float]:
    """Map LIME's discretized conditions to MODEL_COLUMNS.

    LIME prints conditions such as ``22.99 < sum_delay <= 31.19`` or
    ``hist_max_security_risk <= 0.42``. Feature names are matched with word boundaries, and
    the longest match wins, so ``max_loss`` does not also match inside ``hist_max_loss``.
    Unrecognized conditions are ignored (they are reported by ``unmatched_conditions``).
    """
    if not lime or not lime.get("available"):
        return {}
    weights: dict[str, float] = {}
    for row in lime.get("weights", []):
        condition = str(row.get("condition", ""))
        matches = [name for name in MODEL_COLUMNS
                   if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", condition)]
        if not matches:
            continue
        name = max(matches, key=len)
        weights[name] = weights.get(name, 0.0) + float(row.get("weight", 0.0))
    return weights


def unmatched_lime_conditions(lime: dict) -> list[str]:
    """Conditions LIME emitted that could not be mapped to a MODEL_COLUMNS feature."""
    if not lime or not lime.get("available"):
        return []
    unmatched = []
    for row in lime.get("weights", []):
        condition = str(row.get("condition", ""))
        if not any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", condition)
                   for name in MODEL_COLUMNS):
            unmatched.append(condition)
    return unmatched


def _reference_row(X: pd.DataFrame, chosen: int) -> pd.DataFrame:
    return X.iloc[[chosen]][list(MODEL_COLUMNS)].copy().reset_index(drop=True)


def occlusion_deltas(model, X: pd.DataFrame, chosen: int, reference: pd.Series | dict) -> dict[str, float]:
    """How much each feature's actual value contributes to the prediction, by occlusion.

    For each feature we replace the chosen row's value with `reference` (the training-background
    median) and report ``prediction(original) - prediction(replaced)``. A positive value means
    the feature's actual value raised the predicted path cost, the same sign convention as SHAP
    (positive = argues against the path). This is the approximate negation of the raw
    replacement delta, so it lines up with SHAP rather than anti-correlating with it.
    """
    row = _reference_row(X, chosen)
    base = float(model.predict(row)[0])
    replaced = pd.concat([row] * len(MODEL_COLUMNS), ignore_index=True)
    for i, name in enumerate(MODEL_COLUMNS):
        replaced.loc[i, name] = float(reference[name])
    delta = base - model.predict(replaced)
    return {name: float(delta[i]) for i, name in enumerate(MODEL_COLUMNS)}


def _subset_delta(model, X: pd.DataFrame, chosen: int, reference, features, base: float) -> float:
    row = _reference_row(X, chosen)
    for name in features:
        row.at[0, name] = float(reference[name])
    return float(model.predict(row)[0] - base)


def fidelity_metrics(model, X: pd.DataFrame, chosen: int, reference: pd.Series | dict,
                     attributions, top_k: int = 5, *, seed: int = 0,
                     random_trials: int = 64) -> dict:
    """Fidelity of one attribution vector against model occlusion.

    The top-k features by |attribution| are compared with the top-k by |occlusion delta|.
    ``comprehensiveness_advantage`` is (mean |delta| from removing the top-k) minus the same
    for random k-subsets: positive means the attributed features matter more to the model.
    ``sufficiency_advantage`` is the reverse comparison when all OTHER features are replaced:
    positive means keeping the top-k alone preserves the prediction better than random.
    """
    names = list(MODEL_COLUMNS)
    vector = {name: float(_vector(attributions).get(name, 0.0)) for name in names}
    k = max(1, min(int(top_k), len(names)))
    occ = occlusion_deltas(model, X, chosen, reference)
    stats = rank_stats(vector, occ, k)
    top = top_features(vector, k)
    complement = [name for name in names if name not in set(top)]

    rng = np.random.default_rng(seed)
    if k >= len(names):
        random_subsets = [names]
    else:
        seen: set[tuple] = set()
        random_subsets = []
        for _ in range(max(1, int(random_trials))):
            subset = tuple(sorted(rng.choice(names, size=k, replace=False).tolist()))
            if subset not in seen:
                seen.add(subset)
                random_subsets.append(list(subset))

    row = _reference_row(X, chosen)
    base = float(model.predict(row)[0])
    top_remove = _subset_delta(model, X, chosen, reference, top, base)
    random_remove = [_subset_delta(model, X, chosen, reference, s, base) for s in random_subsets]
    top_keep = _subset_delta(model, X, chosen, reference, complement, base)
    random_keep = [_subset_delta(model, X, chosen, reference,
                                 [n for n in names if n not in set(s)], base) for s in random_subsets]

    top_abs = float(np.mean([abs(occ[n]) for n in top]))
    random_abs = float(np.mean([np.mean([abs(occ[n]) for n in s]) for s in random_subsets]))
    result = {
        **stats,
        "attribution_top_features": top,
        "occlusion_top_features": top_features(occ, k),
        "top_k_mean_abs_occlusion": top_abs,
        "random_k_mean_abs_occlusion": random_abs,
        "importance_concentration": (top_abs / random_abs) if random_abs > 0 else None,
        "comprehensiveness_top_k": float(abs(top_remove)),
        "comprehensiveness_random_k": float(np.mean(np.abs(random_remove))),
        "comprehensiveness_advantage": float(abs(top_remove) - np.mean(np.abs(random_remove))),
        "sufficiency_top_k": float(abs(top_keep)),
        "sufficiency_random_k": float(np.mean(np.abs(random_keep))),
        "sufficiency_advantage": float(np.mean(np.abs(random_keep)) - abs(top_keep)),
        "occlusion": {name: float(occ[name]) for name in names},
        "random_trials": len(random_subsets),
    }
    return result


def latency_stats(seconds: list[float]) -> dict:
    """Millisecond summary of repeated timed calls."""
    if not seconds:
        return {"n": 0, "mean_ms": None, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
    ms = np.asarray(seconds, dtype=float) * 1000.0
    return {
        "n": int(len(ms)),
        "mean_ms": float(ms.mean()),
        "median_ms": float(np.median(ms)),
        "p95_ms": float(np.percentile(ms, 95)),
        "min_ms": float(ms.min()),
        "max_ms": float(ms.max()),
    }


def _mean(values) -> float | None:
    clean = [float(v) for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(clean)) if clean else None


def _aggregate_stats(rows: list[dict], keys) -> dict:
    return {key: _mean(row.get(key) for row in rows) for key in keys}


def drift_metrics(before, after, top_k: int = 5) -> dict:
    """Attribution drift between two signed SHAP vectors for the same candidate path.

    The primary score is cosine distance (scale-free across path-cost units). Spearman and
    top-k overlap say whether the *ranking* of reasons changed; top_feature_changed says
    whether the headline explanation moved to a different feature.
    """
    stats = rank_stats(before, after, top_k)
    top_a, top_b = top_features(before, 1), top_features(after, 1)
    stats["top_feature_before"] = top_a[0] if top_a else None
    stats["top_feature_after"] = top_b[0] if top_b else None
    stats["top_feature_changed"] = bool(top_a and top_b and top_a[0] != top_b[0])
    stats["attribution_drift"] = stats["cosine_distance"]
    return stats


def explanation_quality(rec, recommender, cfg: dict, *, repeats: int = 3,
                        lime_seeds=(None,), top_k: int = 5, include_lime: bool = True) -> dict:
    """Fidelity, agreement, seed stability, and latency for one recommendation.

    SHAP is deterministic for a fixed forest, so its stability is measured by retraining in
    ``src/evaluate/explanation_quality.py``; here the repeated SHAP calls only measure latency.
    LIME is sampled, so different seeds are compared directly.
    """
    from .explain import lime_explanation, shap_explanation

    X, chosen = rec.X, rec.chosen
    background = recommender.background()
    reference = background[list(MODEL_COLUMNS)].median()

    shap_times, shap = [], None
    for _ in range(max(1, int(repeats))):
        start = time.perf_counter()
        shap = shap_explanation(recommender.model, X, chosen, None)
        shap_times.append(time.perf_counter() - start)
    shap_vector = {row["feature"]: row["contribution"] for row in shap["contributions"]}
    shap_fidelity = fidelity_metrics(recommender.model, X, chosen, reference, shap_vector, top_k)

    result = {
        "src": rec.src,
        "dst": rec.dst,
        "recommended_path": list(rec.path),
        "chosen_index": int(chosen),
        "top_k": int(top_k),
        "background_reference": "median of models/xai_background.csv",
        "shap": {
            "prediction": float(shap["prediction"]),
            "additivity_error": float(shap["additivity_error"]),
            "latency_ms": latency_stats(shap_times),
            "fidelity": shap_fidelity,
            "top_features": top_features(shap_vector, top_k),
        },
        "lime": {"available": False, "reason": "disabled"},
    }
    if not include_lime:
        return result

    seeds = list(lime_seeds) if lime_seeds else [None]
    lime_rows, weights_by_seed, timings, surrogates = [], {}, [], []
    for seed in seeds:
        lime_cfg = dict(cfg["xai"])
        if seed is not None:
            lime_cfg["seed"] = int(seed)
        start = time.perf_counter()
        lime, _ = lime_explanation(recommender.model, X, chosen, background, lime_cfg)
        timings.append(time.perf_counter() - start)
        if not lime.get("available"):
            result["lime"] = lime
            return result
        vector = parse_lime_weights(lime)
        weights_by_seed[seed] = vector
        surrogates.append(float(lime.get("surrogate_r2", np.nan)))
        lime_rows.append({
            "seed": seed,
            "agreement_with_shap": rank_stats(shap_vector, vector, top_k),
            "fidelity": fidelity_metrics(recommender.model, X, chosen, reference, vector, top_k),
            "top_features": top_features(vector, top_k),
            "surrogate_r2": float(lime.get("surrogate_r2", np.nan)),
            "unmatched_conditions": unmatched_lime_conditions(lime),
            "model_prediction": float(lime.get("model_prediction", np.nan)),
        })

    pairwise = []
    labels = list(weights_by_seed)
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            pairwise.append(rank_stats(weights_by_seed[a], weights_by_seed[b], top_k))

    result["lime"] = {
        "available": True,
        "seeds": seeds,
        "latency_ms": latency_stats(timings),
        "mean_surrogate_r2": _mean(surrogates),
        "agreement_with_shap": _aggregate_stats(
            [row["agreement_with_shap"] for row in lime_rows],
            ("spearman", "top_k_jaccard", "top_k_overlap", "sign_agreement", "cosine_distance")),
        "fidelity": _aggregate_stats(
            [row["fidelity"] for row in lime_rows],
            ("spearman", "top_k_jaccard", "top_k_overlap", "importance_concentration",
             "comprehensiveness_advantage", "sufficiency_advantage")),
        "seed_stability": _aggregate_stats(
            pairwise, ("spearman", "top_k_jaccard", "top_k_overlap", "sign_agreement")),
        "runs": lime_rows,
    }
    return result
