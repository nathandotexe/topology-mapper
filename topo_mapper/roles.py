"""Device role inference from CDP/LLDP capability advertisements."""
from __future__ import annotations

from collections.abc import Iterable

ROLE_COLORS = {
    "router": "#f2a154",
    "switch": "#4c9be8",
    "l3-switch": "#8e5bd9",
    "endpoint": "#57b894",
    "unknown": "#8a8a8a",
}
UNREACHABLE_COLOR = "#d64545"


def infer_role(capabilities: Iterable[str]) -> str:
    """Map CDP words (``Router Switch Host``) or LLDP letters (``R``, ``B``) to a role."""
    tokens = {c.strip().lower() for c in capabilities if c and c.strip()}

    has_router = "router" in tokens or "r" in tokens
    has_switch = bool(tokens & {"switch", "bridge", "b"})
    has_phone = bool(tokens & {"phone", "telephone", "t"})
    has_host = bool(tokens & {"host", "station", "s", "w"})

    if has_phone:
        return "endpoint"
    if has_switch and has_router:
        return "l3-switch"
    if has_switch:
        return "switch"
    if has_router:
        return "router"
    if has_host:
        return "endpoint"
    return "unknown"
