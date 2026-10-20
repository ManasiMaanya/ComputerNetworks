"""Scalar path cost used to label candidate paths (Phase 3). LOWER IS BETTER.

    cost = sum_i  w_i * term_i  +  penalty * [max_security_risk > risk_limit]

Terms (each a dimensionless "badness", roughly 0..1 at the reference scale):
    delay          sum_delay / reference.delay_ms
    loss           sum_loss / reference.loss
    congestion     mean_congestion
    security_risk  max_security_risk
    bandwidth      max(0, 1 - min_bandwidth / reference.bandwidth_mbps)
    reliability    (1 - min_reliability) / reference.unreliability
    energy         mean_energy / reference.energy
    utilization    max_utilization
    queue          max_queue / reference.queue
    hops           hops / reference.hops

Weights, references, and the risk limit come from config `scoring`. They encode a policy
preference (latency and risk first, then loss/congestion), not an objective optimum.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import SCORE_TERMS


def score_terms(features: pd.DataFrame, scoring: dict) -> pd.DataFrame:
    ref = scoring["reference"]
    f = features
    return pd.DataFrame({
        "delay": f["sum_delay"] / ref["delay_ms"],
        "loss": f["sum_loss"] / ref["loss"],
        "congestion": f["mean_congestion"],
        "security_risk": f["max_security_risk"],
        "bandwidth": np.clip(1.0 - f["min_bandwidth"] / ref["bandwidth_mbps"], 0.0, None),
        "reliability": (1.0 - f["min_reliability"]) / ref["unreliability"],
        "energy": f["mean_energy"] / ref["energy"],
        "utilization": f["max_utilization"],
        "queue": f["max_queue"] / ref["queue"],
        "hops": f["hops"] / ref["hops"],
    }, index=features.index)


def path_cost(features: pd.DataFrame, scoring: dict) -> pd.Series:
    """Rule cost for each row of a FEATURE_COLUMNS frame (lower is better)."""
    terms = score_terms(features, scoring)
    weights = pd.Series({t: float(scoring["weights"].get(t, 0.0)) for t in SCORE_TERMS})
    cost = terms[list(SCORE_TERMS)].mul(weights).sum(axis=1)
    hard = scoring["hard_constraints"]
    violates = features["max_security_risk"] > hard["max_security_risk"]
    return (cost + violates.astype(float) * float(hard["penalty"])).rename("rule_cost")


def violates_risk_limit(features: pd.DataFrame, scoring: dict) -> pd.Series:
    return features["max_security_risk"] > scoring["hard_constraints"]["max_security_risk"]
