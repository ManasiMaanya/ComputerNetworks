"""Project exceptions. Every message names the file, node, edge, or key at fault."""

from __future__ import annotations


class RoutingProjectError(Exception):
    """Base class for all expected, user-facing errors in this project."""


class ConfigError(RoutingProjectError):
    """Configuration file is missing, unreadable, or has invalid values."""


class TopologyError(RoutingProjectError):
    """Topology file is missing, malformed, or has invalid node/edge data."""


class RoutingError(RoutingProjectError):
    """Invalid routing request (unknown node, source equals destination, bad weights)."""


class NoPathError(RoutingError):
    """No path exists between the requested nodes (within the configured hop limit)."""


class ModelError(RoutingProjectError):
    """Trained model or its feature schema is missing, stale, or inconsistent."""
