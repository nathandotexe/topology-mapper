"""Run ``mtr`` and parse its JSON report into hop records."""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import time
from dataclasses import dataclass

from .targets import HOSTNAME_RE, Target

MAX_HOPS = 30
_NO_REPLY = {"", "???", "*"}


class ProbeError(RuntimeError):
    """The probe tool ran but produced something unusable."""


@dataclass(frozen=True)
class Hop:
    ttl: int
    host: str | None
    loss: float = 0.0
    sent: int = 0
    last: float = 0.0
    avg: float = 0.0
    best: float = 0.0
    worst: float = 0.0
    stdev: float = 0.0


@dataclass(frozen=True)
class PathResult:
    target: str
    ts: float
    ok: bool  # the probe tool ran and its output parsed
    reached: bool = False  # the last probed hop answered, i.e. the target was reached
    hops: tuple[Hop, ...] = ()
    error: str | None = None

    @property
    def signature(self) -> str:
        """Responding hosts in order. Silent hops are left out on purpose."""
        return ">".join(h.host for h in self.hops if h.host)


def _num(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _clean_host(value: object) -> str | None:
    """Only ever keep something that is a real IP or hostname."""
    text = str(value or "").strip()
    if text in _NO_REPLY:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        pass
    return text.lower() if HOSTNAME_RE.match(text) else None


def parse_mtr_json(text: str) -> tuple[tuple[Hop, ...], bool]:
    """Return ``(hops, reached)``. Trailing silent hops are dropped from ``hops``."""
    try:
        hubs = json.loads(text)["report"]["hubs"]
    except (ValueError, KeyError, TypeError):
        raise ProbeError("unrecognised mtr output") from None
    if not isinstance(hubs, list) or not hubs:
        raise ProbeError("mtr returned no hops")

    seen: set[int] = set()
    hops: list[Hop] = []
    for hub in hubs[: MAX_HOPS * 2]:
        if not isinstance(hub, dict):
            continue
        try:
            ttl = int(hub.get("count"))
        except (TypeError, ValueError):
            continue
        if not 1 <= ttl <= 255 or ttl in seen:
            continue
        seen.add(ttl)
        hops.append(
            Hop(
                ttl=ttl,
                host=_clean_host(hub.get("host")),
                loss=min(max(_num(hub.get("Loss%")), 0.0), 100.0),
                sent=int(_num(hub.get("Snt"))),
                last=_num(hub.get("Last")),
                avg=_num(hub.get("Avg")),
                best=_num(hub.get("Best")),
                worst=_num(hub.get("Wrst")),
                stdev=_num(hub.get("StDev")),
            )
        )
    if not hops:
        raise ProbeError("mtr returned no usable hops")

    hops.sort(key=lambda h: h.ttl)
    reached = hops[-1].host is not None
    while hops and hops[-1].host is None:
        hops.pop()
    return tuple(hops), reached


def run_mtr(
    target: Target,
    *,
    mtr_bin: str = "mtr",
    max_hops: int = MAX_HOPS,
    runner=subprocess.run,
    now=time.time,
) -> PathResult:
    """Probe one target.

    Safety notes: the command is an argument list (no shell), the host was
    validated when the targets file was loaded and is placed after ``--``, DNS
    and AS-number lookups are off (``-n``, no ``-z``) so hop addresses are never
    sent to a resolver or a third-party service, and the environment is
    reduced to PATH and a fixed locale.
    """
    cmd = [mtr_bin, "-j", "-n", "-c", str(target.count), "-m", str(max_hops), "--", target.host]
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin"), "LC_ALL": "C"}
    ts = now()

    def failed(message: str) -> PathResult:
        return PathResult(target=target.name, ts=ts, ok=False, error=message)

    try:
        proc = runner(
            cmd,
            capture_output=True,
            text=True,
            timeout=target.count + 45,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return failed("mtr is not installed")
    except subprocess.TimeoutExpired:
        return failed("mtr timed out")
    except OSError as exc:
        return failed(f"could not run mtr: {exc.strerror or exc.__class__.__name__}")

    if proc.returncode != 0:
        detail = " ".join((proc.stderr or "").split())[:160]
        return failed(f"mtr exited with status {proc.returncode}" + (f": {detail}" if detail else ""))

    try:
        hops, reached = parse_mtr_json(proc.stdout)
    except ProbeError as exc:
        return failed(str(exc))
    return PathResult(target=target.name, ts=ts, ok=True, reached=reached, hops=hops)
