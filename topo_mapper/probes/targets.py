"""Probe targets loaded from a YAML file and validated before they reach a subprocess."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)

MAX_TARGETS = 25
MIN_INTERVAL = 30
MAX_INTERVAL = 86_400
MIN_COUNT = 3
MAX_COUNT = 30
DEFAULT_INTERVAL = 300
DEFAULT_COUNT = 10


class TargetError(ValueError):
    """Raised when the targets file is missing, malformed or unsafe."""


@dataclass(frozen=True)
class Target:
    name: str
    host: str
    interval: int = DEFAULT_INTERVAL
    count: int = DEFAULT_COUNT


def validate_host(value: object) -> str:
    """Return a normalised IP or hostname, or raise.

    A host must start with a letter or digit, so it can never be read as a
    command-line option by the probe binary.
    """
    host = str(value or "").strip()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if HOSTNAME_RE.match(host):
        return host.lower()
    raise TargetError(f"invalid host {host[:60]!r}: expected an IP address or hostname")


def _bounded(value: object, field: str, low: int, high: int, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise TargetError(f"target {name!r}: {field} must be a whole number") from None
    if not low <= number <= high:
        raise TargetError(f"target {name!r}: {field} must be between {low} and {high}")
    return number


def parse_targets(data: object) -> list[Target]:
    if not isinstance(data, dict) or not isinstance(data.get("targets"), list):
        raise TargetError("targets file must contain a 'targets:' list")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise TargetError("'defaults' must be a mapping")
    if len(data["targets"]) > MAX_TARGETS:
        raise TargetError(f"too many targets (max {MAX_TARGETS})")

    targets: list[Target] = []
    seen: set[str] = set()
    for entry in data["targets"]:
        if not isinstance(entry, dict):
            raise TargetError("each target must be a mapping with 'name' and 'host'")
        name = str(entry.get("name") or "").strip()
        if not NAME_RE.match(name):
            raise TargetError(
                f"invalid target name {name[:40]!r}: use letters, digits, '.', '_' or '-' (max 40)"
            )
        if name in seen:
            raise TargetError(f"duplicate target name {name!r}")
        seen.add(name)
        host = validate_host(entry.get("host"))
        interval = _bounded(
            entry.get("interval", defaults.get("interval", DEFAULT_INTERVAL)),
            "interval", MIN_INTERVAL, MAX_INTERVAL, name,
        )
        count = _bounded(
            entry.get("count", defaults.get("count", DEFAULT_COUNT)),
            "count", MIN_COUNT, MAX_COUNT, name,
        )
        targets.append(Target(name=name, host=host, interval=interval, count=count))

    if not targets:
        raise TargetError("no targets defined")
    return targets


def load_targets(path: str | Path) -> list[Target]:
    path = Path(path)
    if path.is_dir():
        raise TargetError(
            f"{path} is a directory. Create the file first (cp targets.example.yaml targets.yaml)."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TargetError(f"cannot read {path}: {exc.strerror or exc}") from None
    except yaml.YAMLError as exc:
        raise TargetError(f"{path} is not valid YAML: {exc}") from None
    return parse_targets(data)
