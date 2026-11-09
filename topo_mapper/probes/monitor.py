"""Scheduler that probes each target on its own interval.

Log lines carry target names and outcomes only, never hop addresses, because
container logs are often shipped to other systems.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence

from .mtr import PathResult, run_mtr
from .store import ProbeStore
from .targets import Target

log = logging.getLogger(__name__)

PRUNE_EVERY_SECONDS = 6 * 3600
STAGGER_SECONDS = 2.0


class Monitor:
    def __init__(
        self,
        targets: Sequence[Target],
        store: ProbeStore,
        *,
        probe: Callable[[Target], PathResult] = run_mtr,
        retention_days: float = 14,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.targets = list(targets)
        self.store = store
        self._probe = probe
        self._retention_days = retention_days
        self._clock = clock
        start = clock()
        self._next_due = {t.name: start + i * STAGGER_SECONDS for i, t in enumerate(self.targets)}
        self._next_prune = start + PRUNE_EVERY_SECONDS

    def probe_target(self, target: Target) -> PathResult:
        try:
            result = self._probe(target)
        except Exception:  # keep the loop alive whatever the probe does
            log.exception("probe of %s crashed", target.name)
            result = PathResult(target=target.name, ts=time.time(), ok=False, error="probe crashed")
        changed = self.store.record(result)
        if not result.ok:
            log.warning("probe %s failed: %s", target.name, result.error)
        elif not result.reached:
            log.warning("probe %s: target not reached (%d hops answered)", target.name,
                        sum(1 for h in result.hops if h.host))
        else:
            log.info("probe %s: reached in %d hops%s", target.name, len(result.hops),
                     " (route changed)" if changed else "")
        return result

    def run_once(self) -> list[PathResult]:
        """Probe every target now, ignoring schedules. Used by ``--once``."""
        return [self.probe_target(t) for t in self.targets]

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            now = self._clock()
            due = [t for t in self.targets if self._next_due[t.name] <= now]
            for target in due:
                if stop.is_set():
                    return
                self.probe_target(target)
                self._next_due[target.name] = self._clock() + target.interval
            if self._clock() >= self._next_prune:
                removed = self.store.prune(self._retention_days)
                log.info("pruned %d old probe runs", removed)
                self._next_prune = self._clock() + PRUNE_EVERY_SECONDS
            wait = max(1.0, min(self._next_due.values()) - self._clock())
            stop.wait(wait)
