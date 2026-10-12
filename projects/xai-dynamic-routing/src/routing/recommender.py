"""Random Forest path-cost recommender, plus a black-box MLP baseline (Phase 3).

The model regresses the training `target` (src/routing/dataset.py) from MODEL_COLUMNS: the 12
path features plus their recent-history summary. With the default future_outcome labels the
target is the rule cost the path experiences over the next horizon_steps; with rule_snapshot
labels it is the rule cost of the current snapshot. At inference the recommender scores the k
candidates for a pair and recommends the lowest predicted cost; ties go to fewer hops, then lower
candidate index. It never returns a path outside the enumerated candidates.

The black-box baseline (fault F-009) is a StandardScaler + MLPRegressor trained on exactly the same
rows, inputs, and target. It is never explained; it exists so evaluations can show what, if
anything, explainability costs in accuracy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..errors import ModelError
from ..features.history import MODEL_COLUMNS, MODEL_UNITS, model_matrix
from ..features.path_features import (
    FEATURE_COLUMNS,
    PathCandidate,
    candidates_frame,
    enumerate_candidates,
)
from .scoring import path_cost

MODEL_FILE = "route_cost_rf.joblib"
BLACKBOX_FILE = "route_cost_mlp.joblib"
SCHEMA_FILE = "feature_schema.json"
REPORT_FILE = "training_report.json"
BACKGROUND_FILE = "xai_background.csv"
TARGETS = {
    "future_outcome": "rule_cost experienced over the next horizon_steps (lower is better)",
    "rule_snapshot": "rule_cost of the current snapshot (lower is better)",
}


def scoring_fingerprint(scoring: dict) -> str:
    return hashlib.sha256(json.dumps(scoring, sort_keys=True).encode()).hexdigest()[:16]


def fit_model(tcfg: dict, X, y) -> RandomForestRegressor:
    """Fit in parallel, then predict single-threaded: parallel prediction sums tree outputs in
    thread order, which makes predictions (and tie-breaks) differ in the last bits between runs."""
    model = RandomForestRegressor(
        n_estimators=tcfg["n_estimators"],
        min_samples_leaf=tcfg["min_samples_leaf"],
        max_features=1.0,
        random_state=tcfg["seed"],
        n_jobs=-1,
    ).fit(X, y)
    return model.set_params(n_jobs=1)


def fit_blackbox(tcfg: dict, X, y):
    """Black-box baseline: standardized inputs into a small multilayer perceptron."""
    return make_pipeline(
        StandardScaler(),
        MLPRegressor(hidden_layer_sizes=tuple(tcfg["blackbox_hidden_layers"]), max_iter=tcfg["blackbox_max_iter"],
                     early_stopping=True, random_state=tcfg["seed"]),
    ).fit(X, y)


def selection_order(predicted: np.ndarray, hops: np.ndarray) -> np.ndarray:
    """Candidate indices best-first: lowest predicted cost, then fewer hops, then lower index."""
    index = np.arange(len(predicted))
    return np.lexsort((index, hops, np.round(predicted, 12)))


def _first_min(values: np.ndarray) -> int:
    return int(np.lexsort((np.arange(len(values)), values))[0])


def evaluate_selection(table: pd.DataFrame, predicted: np.ndarray, blackbox: np.ndarray | None = None) -> dict:
    """Per query: score each method's pick by the TRUE label (`target`, else `rule_cost`).

    Methods: the model, hop count (RIP-like pick), min delay (OSPF-like pick), the snapshot rule
    (lowest rule cost on the current snapshot), the black-box model if given, and the oracle
    (best true label; regret 0 by definition). Under rule_snapshot labels the snapshot rule IS the
    oracle; under future_outcome labels it is the natural non-learning competitor.
    """
    true_col = "target" if "target" in table else "rule_cost"
    df = table.assign(pred=predicted)
    if blackbox is not None:
        df = df.assign(pred_blackbox=blackbox)
    tol = 1e-9
    picks = {name: [] for name in ("model", "hop_count", "min_delay", "snapshot_rule", "blackbox", "oracle")}
    random_top1 = []
    for _, q in df.groupby("query", sort=False):
        q = q.sort_values("path_id")
        true = q[true_col].to_numpy()
        best = true.min()
        chosen = {
            "model": int(selection_order(q["pred"].to_numpy(), q["hops"].to_numpy())[0]),
            "hop_count": _first_min(q["hops"].to_numpy()),
            "min_delay": _first_min(q["sum_delay"].to_numpy()),
            "snapshot_rule": _first_min(q["rule_cost"].to_numpy()),
            "oracle": _first_min(true),
        }
        if blackbox is not None:
            chosen["blackbox"] = int(selection_order(q["pred_blackbox"].to_numpy(), q["hops"].to_numpy())[0])
        for name, idx in chosen.items():
            picks[name].append((true[idx], best))
        random_top1.append(float(np.mean(true <= best + tol)))

    def head_to_head(other: str) -> tuple[int, int, int]:
        diff = np.array([m[0] for m in picks["model"]]) - np.array([o[0] for o in picks[other]])
        return int((diff < -tol).sum()), int((np.abs(diff) <= tol).sum()), int((diff > tol).sum())

    methods = {}
    for name, rows in picks.items():
        if rows:
            cost = np.array(rows)
            methods[name] = {"top1": float(np.mean(cost[:, 0] <= cost[:, 1] + tol)),
                             "mean_regret": float(np.mean(cost[:, 0] - cost[:, 1])),
                             "mean_true_cost": float(np.mean(cost[:, 0]))}
    n = len(picks["model"])
    wins, ties, losses = head_to_head("hop_count")
    decided = wins + losses
    p_value = binomtest(wins, decided, 0.5, alternative="greater").pvalue if decided else None
    d_wins, _, d_losses = head_to_head("min_delay")
    s_wins, s_ties, s_losses = head_to_head("snapshot_rule")
    result = {
        "queries": n,
        "true_cost": true_col,
        "methods": methods,
        "model_top1_accuracy": methods["model"]["top1"],
        "random_pick_expected_top1": float(np.mean(random_top1)),
        "model_mean_regret": methods["model"]["mean_regret"],
        "hop_count_mean_regret": methods["hop_count"]["mean_regret"],
        "min_delay_mean_regret": methods["min_delay"]["mean_regret"],
        "vs_hop_count": {
            "model_better": wins, "tie": ties, "hop_count_better": losses,
            "model_better_rate_when_different": (wins / decided) if decided else None,
            "sign_test_p_value": p_value,
        },
        "vs_min_delay": {"model_better": d_wins, "min_delay_better": d_losses, "tie": n - d_wins - d_losses},
        "vs_snapshot_rule": {"model_better": s_wins, "tie": s_ties, "snapshot_rule_better": s_losses},
    }
    if blackbox is not None:
        b_wins, b_ties, b_losses = head_to_head("blackbox")
        result["vs_blackbox"] = {"model_better": b_wins, "tie": b_ties, "blackbox_better": b_losses}
    return result


def train_and_evaluate(table: pd.DataFrame, train_mask: np.ndarray, test_mask: np.ndarray,
                       cfg: dict, *, blackbox: bool = True) -> tuple[RandomForestRegressor, dict, object | None]:
    """Fit the Random Forest (and the black-box MLP), evaluate both on the held-out rows."""
    tcfg = cfg["training"]
    train, test = table[train_mask], table[test_mask]
    if len(train) < 20 or train["query"].nunique() < 5:
        raise ModelError(f"insufficient training data: {len(train)} rows / {train['query'].nunique()} queries")
    if test.empty:
        raise ModelError("test split is empty; lower training.test_size or add data")
    X_train, y_train = train[list(MODEL_COLUMNS)], train["target"]
    X_test = test[list(MODEL_COLUMNS)]

    n_splits = min(5, train["group"].nunique())
    cv_mae = []
    for fit_idx, val_idx in GroupKFold(n_splits=n_splits).split(X_train, y_train, train["group"]):
        fold = fit_model(tcfg, X_train.iloc[fit_idx], y_train.iloc[fit_idx])
        cv_mae.append(mean_absolute_error(y_train.iloc[val_idx], fold.predict(X_train.iloc[val_idx])))

    model = fit_model(tcfg, X_train, y_train)
    pred_test = model.predict(X_test)
    bb_model = fit_blackbox(tcfg, X_train, y_train) if blackbox else None
    bb_test = bb_model.predict(X_test) if bb_model is not None else None
    sample = (test["family"] == "sample").to_numpy()
    report = {
        "labels": tcfg["labels"],
        "target": TARGETS[tcfg["labels"]],
        "rows": {"train": int(len(train)), "test": int(len(test))},
        "queries": {"train": int(train["query"].nunique()), "test": int(test["query"].nunique())},
        "groups": {"train": int(train["group"].nunique()), "test": int(test["group"].nunique())},
        "group_cv_mae_train": {"folds": n_splits, "mean": float(np.mean(cv_mae)), "std": float(np.std(cv_mae))},
        "test_regression": {"mae": float(mean_absolute_error(test["target"], pred_test)),
                            "r2": float(r2_score(test["target"], pred_test))},
        "test_selection": evaluate_selection(test, pred_test, bb_test),
        "test_selection_sample_family": (
            evaluate_selection(test[sample], pred_test[sample], None if bb_test is None else bb_test[sample])
            if sample.any() else None),
        "feature_importance_impurity": dict(sorted(
            zip(MODEL_COLUMNS, map(float, model.feature_importances_)), key=lambda kv: -kv[1])),
    }
    if bb_test is not None:
        report["blackbox_test_regression"] = {"mae": float(mean_absolute_error(test["target"], bb_test)),
                                              "r2": float(r2_score(test["target"], bb_test))}
    return model, report, bb_model


def save_artifacts(models_dir: Path, model, cfg: dict, report: dict, background: pd.DataFrame,
                   blackbox=None) -> dict:
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, models_dir / MODEL_FILE, compress=3)
    if blackbox is not None:
        joblib.dump(blackbox, models_dir / BLACKBOX_FILE, compress=3)
    else:
        (models_dir / BLACKBOX_FILE).unlink(missing_ok=True)
    tcfg = cfg["training"]
    schema = {
        "feature_columns": list(MODEL_COLUMNS),
        "feature_units": MODEL_UNITS,
        "labels": tcfg["labels"],
        "target": TARGETS[tcfg["labels"]],
        "history_steps": tcfg["history_steps"],
        "horizon_steps": tcfg["horizon_steps"],
        "model": f"sklearn {type(model).__name__}",
        "blackbox_model": "sklearn StandardScaler + MLPRegressor" if blackbox is not None else None,
        "scoring_fingerprint": scoring_fingerprint(cfg["scoring"]),
        "scoring": cfg["scoring"],
        "k_candidate_paths": cfg["k_candidate_paths"],
        "max_hops": cfg["max_hops"],
        "candidate_strategy": cfg["candidate_strategy"],
    }
    (models_dir / SCHEMA_FILE).write_text(json.dumps(schema, indent=2), encoding="utf-8")
    (models_dir / REPORT_FILE).write_text(json.dumps(report, indent=2), encoding="utf-8")
    background[list(MODEL_COLUMNS)].to_csv(models_dir / BACKGROUND_FILE, index=False)
    return schema


@dataclass
class Recommendation:
    src: str
    dst: str
    candidates: list[PathCandidate]
    frame: pd.DataFrame          # candidates + history + predicted_cost + rule_cost + rank
    chosen: int                  # row index into candidates/frame
    order: list[int]             # all candidates best-first
    X: pd.DataFrame              # model input (MODEL_COLUMNS), one row per candidate

    @property
    def path(self) -> tuple[str, ...]:
        return self.candidates[self.chosen].nodes

    @property
    def runner_up(self) -> int | None:
        return self.order[1] if len(self.order) > 1 else None

    def to_dict(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "recommended_path": list(self.path),
            "predicted_cost": float(self.frame.loc[self.chosen, "predicted_cost"]),
            "rule_cost": float(self.frame.loc[self.chosen, "rule_cost"]),
            "features": {c: float(self.X.loc[self.chosen, c]) for c in MODEL_COLUMNS},
            "candidates": self.frame.to_dict(orient="records"),
        }


class RouteRecommender:
    def __init__(self, model, schema: dict, cfg: dict, models_dir: Path, kind: str = "random_forest"):
        self.model = model
        self.schema = schema
        self.cfg = cfg
        self.models_dir = models_dir
        self.kind = kind
        self.stale_scoring = schema.get("scoring_fingerprint") != scoring_fingerprint(cfg["scoring"])

    @classmethod
    def load(cls, models_dir: Path, cfg: dict, *, blackbox: bool = False) -> "RouteRecommender":
        """Load the explained Random Forest, or the black-box MLP with blackbox=True."""
        model_path, schema_path = models_dir / (BLACKBOX_FILE if blackbox else MODEL_FILE), models_dir / SCHEMA_FILE
        for path in (model_path, schema_path):
            if not path.is_file():
                raise ModelError(f"missing {path}; run `python scripts/train.py` first")
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            model = joblib.load(model_path)
        except Exception as exc:  # corrupt or incompatible artifact
            raise ModelError(f"cannot load model artifacts from {models_dir}: {exc}; retrain") from exc
        if schema.get("feature_columns") != list(MODEL_COLUMNS):
            raise ModelError(f"{schema_path}: feature columns {schema.get('feature_columns')} do not match "
                             f"code {list(MODEL_COLUMNS)}; retrain with scripts/train.py")
        if getattr(model, "n_features_in_", len(MODEL_COLUMNS)) != len(MODEL_COLUMNS):
            raise ModelError(f"{model_path}: model expects {model.n_features_in_} features; retrain")
        return cls(model, schema, cfg, models_dir, kind="mlp" if blackbox else "random_forest")

    @property
    def history_steps(self) -> int:
        return int(self.schema.get("history_steps", 1))

    def background(self) -> pd.DataFrame:
        path = self.models_dir / BACKGROUND_FILE
        if not path.is_file():
            raise ModelError(f"missing {path}; run `python scripts/train.py` first")
        frame = pd.read_csv(path)
        if list(frame.columns) != list(MODEL_COLUMNS):
            raise ModelError(f"{path}: columns do not match MODEL_COLUMNS; retrain")
        return frame

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(X[list(MODEL_COLUMNS)])

    def recommend(self, graph: nx.Graph, src, dst, k: int | None = None, max_hops: int | None = None,
                  history: list[nx.Graph] | None = None) -> Recommendation:
        """Rank candidates for src -> dst. `history`: earlier snapshots of `graph`, oldest first
        (at most history_steps - 1 are used); without it the current snapshot is the steady state."""
        k = k or self.cfg["k_candidate_paths"]
        max_hops = max_hops or self.cfg["max_hops"]
        candidates = enumerate_candidates(graph, src, dst, k, max_hops, self.cfg["candidate_strategy"])
        keep = self.history_steps - 1
        X = model_matrix(candidates, (history or [])[-keep:] if keep > 0 else None)
        predicted = self.predict(X)
        frame = candidates_frame(candidates, src, dst)
        for col in MODEL_COLUMNS[len(FEATURE_COLUMNS):]:
            frame[col] = X[col].to_numpy()
        frame["predicted_cost"] = predicted
        frame["rule_cost"] = path_cost(X[list(FEATURE_COLUMNS)], self.cfg["scoring"]).values
        order = [int(i) for i in selection_order(predicted, X["hops"].to_numpy())]
        frame["rank"] = 0
        frame.loc[order, "rank"] = np.arange(1, len(order) + 1)
        return Recommendation(str(src), str(dst), candidates, frame, order[0], order, X)
