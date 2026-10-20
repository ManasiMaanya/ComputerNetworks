"""Discrete-time metric simulation on a copy of the topology (Phase 6).

Each step t = 0..steps-1:
  1. t > 0: seeded Gaussian drift N(0, sigma) is added to the scenario's drift metrics on every edge;
  2. t > 0 and the scenario sets "traffic": true: one step of the traffic model (src/simulate/traffic.py,
     mean-reverting congestion/loss/risk with bursts and incidents; config `traffic`), the same
     dynamics the default model is trained on;
  3. scripted events for step t ("set" absolute values, "add" deltas) are applied to named edges;
  4. values are clipped to METRIC_SPEC ranges and the whole graph is re-validated.
The input graph is deep-copied and never modified. Same scenario + seed => identical run.
Mininet/NS-3 adapters are out of scope here; see src/simulate/mininet_export.py for a topology export.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import networkx as nx
import numpy as np

from ..errors import ConfigError
from ..topology.load import EDGE_ATTRS, METRIC_SPEC, clamp_metric, validate_graph_metrics
from .traffic import TrafficModel, TrafficParams


@dataclass
class Event:
    step: int
    edge: tuple[str, str]
    set: dict[str, float] = field(default_factory=dict)
    add: dict[str, float] = field(default_factory=dict)
    label: str = ""


@dataclass(frozen=True)
class Attack:
    """A node-level attack expanded into per-edge events by src/simulate/attacks.py.

    blackhole: every incident link drops traffic (high loss, low reliability).
    compromised: every incident link is marked above the scoring rule's risk limit.
    """
    kind: str
    node: str
    step: int = 0
    loss: float | None = None
    risk: float | None = None
    label: str = ""


@dataclass
class Scenario:
    name: str
    src: str
    dst: str
    steps: int
    seed: int
    drift_metrics: tuple[str, ...]
    drift_sigma: float
    events: list[Event]
    topology: str | None = None
    description: str = ""
    traffic: bool = False
    attacks: list[Attack] = field(default_factory=list)


def _metrics(obj, where: str) -> dict[str, float]:
    if not isinstance(obj, dict):
        raise ConfigError(f"{where}: must be an object of metric -> number")
    for key, value in obj.items():
        if key not in EDGE_ATTRS:
            raise ConfigError(f"{where}: unknown metric '{key}'; allowed {EDGE_ATTRS}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
            raise ConfigError(f"{where}: '{key}' must be a finite number, got {value!r}")
    return {k: float(v) for k, v in obj.items()}


def parse_scenario(data: dict, where: str = "scenario") -> Scenario:
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: top level must be an object")
    for key in ("name", "src", "dst", "steps", "seed"):
        if key not in data:
            raise ConfigError(f"{where}: missing key '{key}'")
    steps, seed = data["steps"], data["seed"]
    if not isinstance(steps, int) or steps < 1:
        raise ConfigError(f"{where}: 'steps' must be an int >= 1")
    if not isinstance(seed, int):
        raise ConfigError(f"{where}: 'seed' must be an int")
    drift = data.get("drift", {"metrics": [], "sigma": 0.0})
    metrics = tuple(drift.get("metrics", []))
    bad = [m for m in metrics if m not in EDGE_ATTRS]
    if bad:
        raise ConfigError(f"{where}.drift: unknown metrics {bad}")
    sigma = drift.get("sigma", 0.0)
    if not isinstance(sigma, (int, float)) or sigma < 0:
        raise ConfigError(f"{where}.drift: 'sigma' must be >= 0")
    events = []
    for i, ev in enumerate(data.get("events", [])):
        label = f"{where}.events[{i}]"
        if not isinstance(ev, dict) or "step" not in ev or "edge" not in ev:
            raise ConfigError(f"{label}: needs 'step' and 'edge'")
        if not isinstance(ev["step"], int) or not 0 <= ev["step"] < steps:
            raise ConfigError(f"{label}: 'step' must be an int in [0, {steps - 1}]")
        if not (isinstance(ev["edge"], list) and len(ev["edge"]) == 2):
            raise ConfigError(f"{label}: 'edge' must be [u, v]")
        if not ev.get("set") and not ev.get("add"):
            raise ConfigError(f"{label}: needs 'set' and/or 'add'")
        events.append(Event(ev["step"], (str(ev["edge"][0]), str(ev["edge"][1])),
                            _metrics(ev.get("set", {}), f"{label}.set"),
                            _metrics(ev.get("add", {}), f"{label}.add"), ev.get("label", "")))
    traffic = data.get("traffic", False)
    if not isinstance(traffic, bool):
        raise ConfigError(f"{where}: 'traffic' must be true or false")
    raw_attacks = data.get("attacks", [])
    if not isinstance(raw_attacks, list):
        raise ConfigError(f"{where}: 'attacks' must be a list")
    attacks = []
    for i, atk in enumerate(raw_attacks):
        label = f"{where}.attacks[{i}]"
        if not isinstance(atk, dict):
            raise ConfigError(f"{label}: must be an object")
        kind = atk.get("kind")
        if kind not in ("blackhole", "compromised"):
            raise ConfigError(f"{label}: 'kind' must be 'blackhole' or 'compromised', got {kind!r}")
        node = atk.get("node")
        if not isinstance(node, str) or not node:
            raise ConfigError(f"{label}: 'node' must be a non-empty string")
        step = atk.get("step", 0)
        if not isinstance(step, int) or not 0 <= step < steps:
            raise ConfigError(f"{label}: 'step' must be an int in [0, {steps - 1}]")
        for key in ("loss", "risk"):
            value = atk.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not np.isfinite(value) or not 0 <= value <= 1):
                raise ConfigError(f"{label}: '{key}' must be a number in [0, 1]")
        attacks.append(Attack(kind, node, step,
                              None if atk.get("loss") is None else float(atk["loss"]),
                              None if atk.get("risk") is None else float(atk["risk"]),
                              str(atk.get("label", ""))))
    return Scenario(str(data["name"]), str(data["src"]), str(data["dst"]), steps, seed, metrics,
                    float(sigma), events, data.get("topology"), data.get("description", ""), traffic,
                    attacks=attacks)


def load_scenario(path: Path) -> Scenario:
    if not path.is_file():
        raise ConfigError(f"scenario file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc
    return parse_scenario(data, path.name)


class GraphSimulator:
    def __init__(self, graph: nx.Graph, scenario: Scenario, traffic: TrafficParams | None = None,
                 attack_defaults: dict | None = None):
        from .attacks import attack_events  # local import: attacks imports Event/Attack from here

        events = list(scenario.events)
        for attack in scenario.attacks:
            events.extend(attack_events(graph, attack, attack_defaults, steps=scenario.steps))
        if scenario.attacks:
            scenario = replace(scenario, events=events)
        for ev in scenario.events:
            if not graph.has_edge(*ev.edge):
                raise ConfigError(f"scenario '{scenario.name}': event edge {ev.edge[0]}-{ev.edge[1]} not in graph")
        self.graph = copy.deepcopy(graph)
        self.scenario = scenario
        self.rng = np.random.default_rng(scenario.seed)
        self.traffic = TrafficModel(graph, traffic) if scenario.traffic else None

    def _set(self, u, v, metric: str, value: float, cause: str, changes: list) -> None:
        data = self.graph.edges[u, v]
        old = data[metric]
        new = clamp_metric(metric, value)
        if metric == "queue":
            new = float(round(new, 3))
        if new != old:
            data[metric] = new
            changes.append({"edge": f"{u}-{v}", "metric": metric, "old": old, "new": new, "cause": cause})

    def step(self, t: int) -> list[dict]:
        """Advance to step t and return every metric change applied."""
        changes: list[dict] = []
        sc = self.scenario
        if t > 0 and sc.drift_metrics and sc.drift_sigma > 0:
            for u, v, data in sorted(self.graph.edges(data=True), key=lambda e: (str(e[0]), str(e[1]))):
                for metric in sc.drift_metrics:
                    self._set(u, v, metric, data[metric] + self.rng.normal(0, sc.drift_sigma), "drift", changes)
        if t > 0 and self.traffic is not None:
            changes += self.traffic.step(self.graph, self.rng)
        for ev in sc.events:
            if ev.step != t:
                continue
            u, v = ev.edge
            for metric, value in ev.set.items():
                self._set(u, v, metric, value, ev.label or "event", changes)
            for metric, delta in ev.add.items():
                self._set(u, v, metric, self.graph.edges[u, v][metric] + delta, ev.label or "event", changes)
        validate_graph_metrics(self.graph, f"simulation step {t}")
        return changes


def describe_ranges() -> dict[str, str]:
    return {m: METRIC_SPEC[m].describe() for m in EDGE_ATTRS}
