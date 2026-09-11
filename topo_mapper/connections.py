"""Connection backends: real SSH via Netmiko, and a file-backed mock lab."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import yaml


class Connection(Protocol):
    """The minimal surface the discovery engine needs from a device session."""

    def send_command(self, command: str) -> str: ...

    def find_prompt(self) -> str: ...

    def disconnect(self) -> None: ...


class ConnectionError_(Exception):
    """Raised when a device cannot be reached / authenticated."""


# --------------------------------------------------------------------- Netmiko


class NetmikoConnection:
    def __init__(self, host: str, params: dict):
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:  # pragma: no cover - import guard
            raise ConnectionError_(
                "netmiko is not installed; run `pip install netmiko` or use --mock"
            ) from exc
        try:
            self._conn = ConnectHandler(host=host, **params)
        except Exception as exc:  # netmiko raises many subclasses
            raise ConnectionError_(f"{host}: {exc}") from exc

    def send_command(self, command: str) -> str:
        return self._conn.send_command(command, read_timeout=30)

    def find_prompt(self) -> str:
        return self._conn.find_prompt()

    def disconnect(self) -> None:
        try:
            self._conn.disconnect()
        except Exception:  # pragma: no cover - best effort teardown
            pass


def _connection_params(host: str, inventory: dict) -> dict:
    params: dict = {
        "device_type": os.getenv("TOPO_DEVICE_TYPE", "cisco_ios"),
        "username": os.getenv("TOPO_USERNAME"),
        "password": os.getenv("TOPO_PASSWORD"),
    }
    if os.getenv("TOPO_SECRET"):
        params["secret"] = os.getenv("TOPO_SECRET")

    params.update({k: v for k, v in inventory.get("defaults", {}).items() if v is not None})
    devices = inventory.get("devices", {}) or {}
    if host in devices:
        params.update({k: v for k, v in devices[host].items() if v is not None})

    return {k: v for k, v in params.items() if v is not None}


def netmiko_factory(inventory: dict | None = None):
    inventory = inventory or {}

    def factory(host: str) -> Connection:
        return NetmikoConnection(host, _connection_params(host, inventory))

    return factory


# ------------------------------------------------------------------ Mock lab


class MockConnection:
    """Replays captured ``show`` output from ``<lab_dir>/<hostname>/<cmd>.txt``."""

    def __init__(self, hostname: str, host_dir: Path):
        self._hostname = hostname
        self._dir = host_dir

    def send_command(self, command: str) -> str:
        slug = command.strip().lower().replace(" ", "_").replace("/", "_")
        path = self._dir / f"{slug}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def find_prompt(self) -> str:
        return f"{self._hostname}#"

    def disconnect(self) -> None:  # nothing to tear down
        pass


class MockLab:
    def __init__(self, lab_dir: str | os.PathLike):
        self.dir = Path(lab_dir)
        hosts_file = self.dir / "hosts.yaml"
        if not hosts_file.exists():
            raise FileNotFoundError(f"mock lab has no hosts.yaml: {hosts_file}")
        data = yaml.safe_load(hosts_file.read_text(encoding="utf-8")) or {}
        self.address_map: dict[str, str] = {str(k): str(v) for k, v in (data.get("map") or {}).items()}
        self.seeds: list[str] = [str(s) for s in (data.get("seeds") or [])]

    def factory(self):
        def factory(host: str) -> Connection:
            hostname = self.address_map.get(host, host)
            host_dir = self.dir / hostname
            if not host_dir.is_dir():
                raise ConnectionError_(f"{host}: no route to host (not in mock lab)")
            return MockConnection(hostname, host_dir)

        return factory


def bundled_demo_lab() -> Path:
    return Path(__file__).with_name("demo_lab")
