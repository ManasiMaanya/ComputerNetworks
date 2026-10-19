"""Load and validate `configs/default.json`. All tunables live there, not in code."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.json"

OSPF_COST_CHOICES = ("delay", "inverse_bandwidth")
LABEL_MODES = ("future_outcome", "rule_snapshot")
CANDIDATE_STRATEGIES = ("hops", "delay", "mixed")
SCORE_TERMS = (
    "delay",
    "loss",
    "congestion",
    "security_risk",
    "bandwidth",
    "reliability",
    "energy",
    "utilization",
    "queue",
    "hops",
)
SCORE_REFERENCES = ("delay_ms", "loss", "bandwidth_mbps", "unreliability", "energy", "queue", "hops")


def resolve_path(value: str | Path, *, base: Path = PROJECT_ROOT) -> Path:
    """Absolute paths pass through; relative ones resolve against the project root."""
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def resolve_input_path(value: str | Path) -> Path:
    """CLI input: prefer the path as given (relative to cwd), else relative to the project root."""
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path.resolve()
    return resolve_path(path)


def _require(cfg: dict, key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if key not in cfg:
        raise ConfigError(f"{where}: missing key '{key}'")
    value = cfg[key]
    if isinstance(value, bool) or not isinstance(value, kind):
        raise ConfigError(f"{where}: '{key}' must be {kind}, got {value!r}")
    return value


def _positive_int(cfg: dict, key: str, where: str) -> int:
    value = _require(cfg, key, int, where)
    if value < 1:
        raise ConfigError(f"{where}: '{key}' must be >= 1, got {value}")
    return value


def _finite(value: Any, name: str, where: str, *, minimum: float | None = None, strict: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{where}: '{name}' must be a finite number, got {value!r}")
    if minimum is not None and (value <= minimum if strict else value < minimum):
        op = ">" if strict else ">="
        raise ConfigError(f"{where}: '{name}' must be {op} {minimum}, got {value}")
    return float(value)


def validate_config(cfg: dict, where: str = "config") -> dict:
    if not isinstance(cfg, dict):
        raise ConfigError(f"{where}: top level must be a JSON object")
    _positive_int(cfg, "k_candidate_paths", where)
    _positive_int(cfg, "max_hops", where)
    _require(cfg, "sample_topology", str, where)
    strategy = _require(cfg, "candidate_strategy", str, where)
    if strategy not in CANDIDATE_STRATEGIES:
        raise ConfigError(f"{where}: 'candidate_strategy' must be one of {CANDIDATE_STRATEGIES}, got '{strategy}'")
    ospf = _require(cfg, "ospf_cost", str, where)
    if ospf not in OSPF_COST_CHOICES:
        raise ConfigError(f"{where}: 'ospf_cost' must be one of {OSPF_COST_CHOICES}, got '{ospf}'")
    _finite(_require(cfg, "ospf_reference_bandwidth_bps", (int, float), where),
            "ospf_reference_bandwidth_bps", where, minimum=0, strict=True)

    scoring = _require(cfg, "scoring", dict, where)
    weights = _require(scoring, "weights", dict, f"{where}.scoring")
    unknown = set(weights) - set(SCORE_TERMS)
    if unknown:
        raise ConfigError(f"{where}.scoring.weights: unknown terms {sorted(unknown)}; allowed {SCORE_TERMS}")
    for term in SCORE_TERMS:
        _finite(weights.get(term, 0.0), term, f"{where}.scoring.weights", minimum=0)
    if sum(weights.values()) <= 0:
        raise ConfigError(f"{where}.scoring.weights: at least one weight must be > 0")
    refs = _require(scoring, "reference", dict, f"{where}.scoring")
    for name in SCORE_REFERENCES:
        if name not in refs:
            raise ConfigError(f"{where}.scoring.reference: missing '{name}'")
        _finite(refs[name], name, f"{where}.scoring.reference", minimum=0, strict=True)
    hard = _require(scoring, "hard_constraints", dict, f"{where}.scoring")
    _finite(_require(hard, "max_security_risk", (int, float), f"{where}.scoring.hard_constraints"),
            "max_security_risk", f"{where}.scoring.hard_constraints", minimum=0)
    _finite(_require(hard, "penalty", (int, float), f"{where}.scoring.hard_constraints"),
            "penalty", f"{where}.scoring.hard_constraints", minimum=0)

    training = _require(cfg, "training", dict, where)
    for key in ("seed", "sample_snapshots", "synthetic_graphs", "n_estimators", "min_samples_leaf",
                "lime_background_rows"):
        _require(training, key, int, f"{where}.training")
    if not 0 < _finite(_require(training, "test_size", (int, float), f"{where}.training"),
                       "test_size", f"{where}.training") < 1:
        raise ConfigError(f"{where}.training: 'test_size' must be between 0 and 1")
    _finite(_require(training, "perturbation", (int, float), f"{where}.training"),
            "perturbation", f"{where}.training", minimum=0)
    nodes = _require(training, "synthetic_nodes", list, f"{where}.training")
    if len(nodes) != 2 or not all(isinstance(n, int) and n >= 3 for n in nodes) or nodes[0] > nodes[1]:
        raise ConfigError(f"{where}.training: 'synthetic_nodes' must be [min, max] ints >= 3")
    labels = _require(training, "labels", str, f"{where}.training")
    if labels not in LABEL_MODES:
        raise ConfigError(f"{where}.training: 'labels' must be one of {LABEL_MODES}, got '{labels}'")
    for key in ("trace_steps", "decision_stride", "synthetic_trace_steps", "synthetic_decision_stride",
                "history_steps", "horizon_steps", "blackbox_max_iter"):
        _positive_int(training, key, f"{where}.training")
    if not 0 < _finite(_require(training, "test_time_fraction", (int, float), f"{where}.training"),
                       "test_time_fraction", f"{where}.training") < 1:
        raise ConfigError(f"{where}.training: 'test_time_fraction' must be between 0 and 1")
    layers = _require(training, "blackbox_hidden_layers", list, f"{where}.training")
    if not layers or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in layers):
        raise ConfigError(f"{where}.training: 'blackbox_hidden_layers' must be a non-empty list of ints >= 1")

    from .simulate.traffic import TrafficParams  # local import: simulate depends on config's package

    TrafficParams.from_config(_require(cfg, "traffic", dict, where), f"{where}.traffic")

    xai = _require(cfg, "xai", dict, where)
    _positive_int(xai, "top_k", f"{where}.xai")
    _positive_int(xai, "lime_num_samples", f"{where}.xai")
    _require(xai, "seed", int, f"{where}.xai")

    paths = _require(cfg, "paths", dict, where)
    for key in ("models_dir", "outputs_dir", "processed_dir", "raw_dir"):
        _require(paths, key, str, f"{where}.paths")

    compare = _require(cfg, "compare", dict, where)
    pairs = _require(compare, "pairs", list, f"{where}.compare")
    for pair in pairs:
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) for p in pair)):
            raise ConfigError(f"{where}.compare.pairs: each pair must be [src, dst] strings, got {pair!r}")
    _positive_int(compare, "random_pairs", f"{where}.compare")

    _require(cfg, "simulation", dict, where)
    _require(cfg["simulation"], "scenario", str, f"{where}.simulation")
    margin = _finite(_require(cfg["simulation"], "hysteresis_margin", (int, float), f"{where}.simulation"),
                     "hysteresis_margin", f"{where}.simulation", minimum=0)
    if margin >= 1:
        raise ConfigError(f"{where}.simulation: 'hysteresis_margin' must be < 1, got {margin}")
    _require(cfg, "topology_zoo", dict, where)
    return cfg


def load_config(path: str | Path | None = None) -> dict:
    config_path = DEFAULT_CONFIG_PATH if path is None else resolve_input_path(path)
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}") from exc
    return validate_config(cfg, where=str(config_path.name))


def project_dir(cfg: dict, key: str) -> Path:
    """Return a configured project directory (e.g. 'models_dir'), creating it if needed."""
    path = resolve_path(cfg["paths"][key])
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(cfg: dict, *parts: str) -> Path:
    path = project_dir(cfg, "outputs_dir").joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
