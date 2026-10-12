"""Historical traffic features for a candidate path (fault F-010).

A path's history window is its FEATURE_COLUMNS dict at each of the last N time steps, oldest
first, ending with the current step. HISTORY_COLUMNS summarize the three time-varying path
metrics over that window:

    hist_mean_congestion / hist_max_congestion        mean / peak of mean_congestion
    hist_mean_loss / hist_max_loss                    mean / peak of sum_loss
    hist_mean_security_risk / hist_max_security_risk  mean / peak of max_security_risk

The model input (MODEL_COLUMNS) is the current snapshot features followed by these. With no
history (a one-off query on a static topology) the window is just the current snapshot, i.e. the
current conditions are treated as the steady state.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

from .path_features import FEATURE_COLUMNS, FEATURE_UNITS, PathCandidate, extract_features

HISTORY_SOURCES = {"congestion": "mean_congestion", "loss": "sum_loss", "security_risk": "max_security_risk"}

HISTORY_COLUMNS: tuple[str, ...] = tuple(f"hist_{stat}_{name}" for name in HISTORY_SOURCES for stat in ("mean", "max"))
MODEL_COLUMNS: tuple[str, ...] = FEATURE_COLUMNS + HISTORY_COLUMNS
MODEL_UNITS: dict[str, str] = {
    **FEATURE_UNITS,
    **{f"hist_{stat}_{name}": f"{stat} of {src} over history ({FEATURE_UNITS[src]})"
       for name, src in HISTORY_SOURCES.items() for stat in ("mean", "max")},
}


def history_features(window: list[dict[str, float]]) -> dict[str, float]:
    """Summarize a feature-dict window (oldest first, current last) into HISTORY_COLUMNS."""
    if not window:
        raise ValueError("history window must contain at least the current snapshot")
    out: dict[str, float] = {}
    for name, source in HISTORY_SOURCES.items():
        values = [float(w[source]) for w in window]
        out[f"hist_mean_{name}"] = sum(values) / len(values)
        out[f"hist_max_{name}"] = max(values)
    return out


def model_row(window: list[dict[str, float]]) -> dict[str, float]:
    """Model input row: current snapshot features + history summary, in MODEL_COLUMNS order."""
    row = {c: float(window[-1][c]) for c in FEATURE_COLUMNS}
    row.update(history_features(window))
    return row


def model_matrix(candidates: list[PathCandidate], history: list[nx.Graph] | None = None) -> pd.DataFrame:
    """MODEL_COLUMNS for each candidate. `history` holds earlier graph snapshots, oldest first."""
    rows = []
    for cand in candidates:
        window = [extract_features(g, cand.nodes) for g in (history or [])] + [cand.features]
        rows.append(model_row(window))
    return pd.DataFrame(rows, columns=list(MODEL_COLUMNS)).astype(float)
