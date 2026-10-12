"""Shared helpers for scripts: config/topology loading, readable tables, uniform error exits."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pandas as pd

from .config import PROJECT_ROOT, load_config, resolve_input_path, resolve_path
from .errors import RoutingProjectError
from .topology.load import load_topology


def add_common_args(parser) -> None:
    parser.add_argument("--config", default=None, help="config JSON (default: configs/default.json)")
    parser.add_argument("--topology", default=None,
                        help="topology: .json, Topology Zoo .gml/.graphml, or SNDlib .txt (default: sample)")


def load_context(args):
    cfg = load_config(args.config)
    topo_path = resolve_input_path(args.topology) if args.topology else resolve_path(cfg["sample_topology"])
    graph = load_topology(topo_path, cfg)
    return cfg, graph, topo_path


def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def banner(title: str) -> None:
    print(f"\n=== {title} ===")


def table(frame: pd.DataFrame, floatfmt: str = "{:.4g}") -> str:
    with pd.option_context("display.max_columns", None, "display.width", 250,
                           "display.max_colwidth", 60, "display.float_format", floatfmt.format):
        return frame.to_string(index=False)


def run(main: Callable[[], int]) -> None:
    try:
        code = main()
    except RoutingProjectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 2
    raise SystemExit(code)
