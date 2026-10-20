"""Node-level attack scenarios and their per-edge effects.

Two attacks are supported:

  * blackhole: a node silently drops traffic. Every incident link gets the configured blackhole
    loss (default 0.99) and reliability (default 0.10). The scoring rule's loss/reliability
    terms should make paths through the node unattractive.
  * compromised: a node is assumed hostile. Every incident link is marked above the rule's
    hard risk limit (default security_risk 0.95, limit 0.65) and gets a small loss bump. The
    hard-constraint penalty should remove those paths from consideration.

Attacks are declared in a scenario JSON as
``"attacks": [{"kind": "blackhole", "node": "R5", "step": 2}]`` and expanded into ordinary
per-edge Events by `attack_events`; `GraphSimulator` does this at construction. That keeps the
existing timeline/explanation machinery unchanged and makes attack scenarios reusable with any
topology that contains the named node. `apply_attack` is the one-shot version used by
`scripts/attack_drift.py` for before/after attribution analysis.

These are metric-level simulations for routing-policy evaluation. They do not implement packet
capture, exploitation, or any real network attack.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import networkx as nx

from ..errors import ConfigError, RoutingError
from ..topology.load import clamp_metric, validate_graph_metrics
from .graph_sim import Attack, Event

ATTACK_KINDS = ("blackhole", "compromised")
DEFAULT_CONFIG = {
    "blackhole_loss": 0.99,
    "blackhole_reliability": 0.10,
    "compromised_risk": 0.95,
    "compromised_loss": 0.05,
}
#: The feature that should become more important after each attack (for drift detection).
SIGNAL_FEATURES = {
    "blackhole": ("sum_loss", "max_loss", "min_reliability"),
    "compromised": ("max_security_risk", "sum_loss"),
}


def parse_attack(kind: str, node: str, step: int = 0, *, loss: float | None = None,
                 risk: float | None = None, label: str = "") -> Attack:
    if kind not in ATTACK_KINDS:
        raise ConfigError(f"attack kind must be one of {ATTACK_KINDS}, got {kind!r}")
    if not isinstance(node, str) or not node:
        raise ConfigError("attack node must be a non-empty string")
    if not isinstance(step, int) or step < 0:
        raise ConfigError(f"attack step must be an int >= 0, got {step!r}")
    for name, value in (("loss", loss), ("risk", risk)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not 0 <= float(value) <= 1):
            raise ConfigError(f"attack {name} must be a number in [0, 1], got {value!r}")
    return Attack(kind, node, step, None if loss is None else float(loss),
                  None if risk is None else float(risk), label)


def parse_attack_spec(text: str, step: int = 0) -> Attack:
    """Parse ``blackhole:R5`` or ``compromised:R7@3`` (the suffix overrides the step)."""
    if not isinstance(text, str) or ":" not in text:
        raise ConfigError(f"attack spec must look like KIND:NODE, got {text!r}")
    kind, rest = text.split(":", 1)
    node, _, step_text = rest.partition("@")
    if step_text:
        try:
            step = int(step_text)
        except ValueError:
            raise ConfigError(f"attack spec step must be an integer, got {step_text!r}") from None
    return parse_attack(kind.strip(), node.strip(), step)


def incident_edges(graph: nx.Graph, node: str) -> list[tuple[str, str]]:
    node = str(node)
    if node not in graph:
        raise RoutingError(f"attack node '{node}' is not in the topology")
    edges = list(graph.edges(node))
    if graph.is_directed():
        edges += list(graph.in_edges(node))
    return sorted({(str(u), str(v)) for u, v in edges})


def attack_effects(attack: Attack, config: dict | None = None) -> dict[str, float]:
    """Metric values the attack sets on every incident edge, after overrides and clamping."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if attack.kind == "blackhole":
        effects = {"loss": cfg["blackhole_loss"], "reliability": cfg["blackhole_reliability"]}
    else:
        effects = {"security_risk": cfg["compromised_risk"], "loss": cfg["compromised_loss"]}
    if attack.loss is not None:
        effects["loss"] = attack.loss
    if attack.risk is not None:
        effects["security_risk"] = attack.risk
    return {name: clamp_metric(name, float(value)) for name, value in effects.items()}


def attack_events(graph: nx.Graph, attack: Attack, config: dict | None = None,
                  steps: int | None = None) -> list[Event]:
    """Expand a node attack into one set-event per incident edge and step.

    With `steps` omitted this is a one-shot expansion at `attack.step` (useful for a static
    before/after view). `GraphSimulator` passes the scenario length so the attack is reasserted
    every step: otherwise a later traffic update could partially undo the loss/risk values.
    """
    effects = attack_effects(attack, config)
    label = attack.label or f"{attack.kind} {attack.node}"
    at_steps = ([attack.step] if steps is None
                else list(range(attack.step, max(attack.step + 1, steps))))
    return [Event(step, edge, set=dict(effects), label=label)
            for step in at_steps for edge in incident_edges(graph, attack.node)]


def apply_attack(graph: nx.Graph, attack: Attack, config: dict | None = None) -> tuple[nx.Graph, dict]:
    """Deep-copy `graph` and apply the attack once; return (attacked graph, metadata)."""
    attacked = copy.deepcopy(graph)
    edges = incident_edges(attacked, attack.node)
    effects = attack_effects(attack, config)
    records = []
    for u, v in edges:
        before = {name: float(attacked.edges[u, v][name]) for name in effects}
        for name, value in effects.items():
            attacked.edges[u, v][name] = value
        after = {name: float(attacked.edges[u, v][name]) for name in effects}
        records.append({"edge": f"{u}-{v}", "before": before, "after": after})
    validate_graph_metrics(attacked, f"{attack.kind} attack on {attack.node}")
    try:
        articulation = attack.node in set(nx.articulation_points(graph)) if not graph.is_directed() else False
    except nx.NetworkXError:
        articulation = False
    return attacked, {
        "kind": attack.kind,
        "node": attack.node,
        "step": attack.step,
        "effects": effects,
        "signal_features": list(SIGNAL_FEATURES[attack.kind]),
        "edges": records,
        "changed_edges": len(records),
        "degree": int(graph.degree(attack.node)),
        "articulation_point": bool(articulation),
    }


def attack_scenario_events(scenario, graph: nx.Graph, config: dict | None = None):
    """Return a copy of `scenario` with its attacks expanded to events (used by tests/reports)."""
    events = list(scenario.events)
    for attack in scenario.attacks:
        events.extend(attack_events(graph, attack, config, steps=scenario.steps))
    return replace(scenario, events=events)
