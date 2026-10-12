"""Shared test setup: project import path, fixtures, and a small model trained once per run."""

from __future__ import annotations

import atexit
import copy
import shutil
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config, resolve_path  # noqa: E402
from src.topology.load import load_graph  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def sample_graph():
    cfg = load_config()
    return load_graph(resolve_path(cfg["sample_topology"]))


def tmp_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="xai_routing_test_"))
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def small_config(work: Path | None = None) -> dict:
    """Default config with a small training budget and outputs redirected to a temp folder."""
    cfg = copy.deepcopy(load_config())
    work = work or tmp_dir()
    cfg["paths"] = {"models_dir": str(work / "models"), "outputs_dir": str(work / "outputs"),
                    "processed_dir": str(work / "processed"), "raw_dir": str(work / "raw")}
    cfg["training"].update({"sample_snapshots": 25, "synthetic_graphs": 12, "n_estimators": 40,
                            "min_samples_leaf": 3, "lime_background_rows": 200,
                            "trace_steps": 80, "decision_stride": 3, "synthetic_trace_steps": 20,
                            "synthetic_decision_stride": 4, "blackbox_max_iter": 200})
    cfg["xai"]["lime_num_samples"] = 300
    return cfg


@lru_cache(maxsize=1)
def trained():
    """(cfg, recommender, report, table) for a small model trained once and saved to a temp dir."""
    from src.config import project_dir
    from src.routing.dataset import build_training_table, split_groups
    from src.routing.recommender import RouteRecommender, save_artifacts, train_and_evaluate

    cfg = small_config()
    table = build_training_table(sample_graph(), cfg)
    train_mask, test_mask = split_groups(table, cfg["training"]["test_size"], cfg["training"]["seed"])
    model, report, blackbox = train_and_evaluate(table, train_mask, test_mask, cfg)
    models_dir = project_dir(cfg, "models_dir")
    save_artifacts(models_dir, model, cfg, report, table[train_mask].head(cfg["training"]["lime_background_rows"]),
                   blackbox)
    return cfg, RouteRecommender.load(models_dir, cfg), report, table


def has_module(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True
