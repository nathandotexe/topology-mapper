"""Interpreting per-hop loss the way ``mtr`` documents it.

Routers on the path often rate-limit or deprioritise the ICMP replies that
traceroute depends on, so loss shown at a middle hop is only real when it
continues to the hops after it. The effective loss of a hop is therefore the
lowest loss seen at that hop or anywhere beyond it.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

LOSS_DEGRADED_PCT = 5.0
LOSS_DOWN_PCT = 100.0


class _HopLike(Protocol):
    ttl: int
    host: str | None
    loss: float


def effective_losses(hops: Iterable[_HopLike]) -> dict[int, float | None]:
    """Map ttl -> effective loss percent, or None for hops that never answered."""
    result: dict[int, float | None] = {}
    floor: float | None = None
    for hop in sorted(hops, key=lambda h: h.ttl, reverse=True):
        if hop.host is None:
            result[hop.ttl] = None
            continue
        floor = hop.loss if floor is None else min(floor, hop.loss)
        result[hop.ttl] = floor
    return result


def hop_status(effective_loss: float | None) -> str:
    """up | degraded | down | unknown"""
    if effective_loss is None:
        return "unknown"
    if effective_loss >= LOSS_DOWN_PCT:
        return "down"
    if effective_loss >= LOSS_DEGRADED_PCT:
        return "degraded"
    return "up"
