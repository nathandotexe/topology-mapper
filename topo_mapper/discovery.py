"""Recursive CDP/LLDP discovery engine (breadth-first walk from seed devices)."""
from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .connections import Connection, ConnectionError_
from .models import Device, Link, NeighborRecord
from .normalize import device_key, looks_like_ip, normalize_hostname
from .parsers import (
    parse_cdp_detail,
    parse_hostname,
    parse_interface_status,
    parse_ip_interface_brief,
    parse_lldp_detail,
    parse_platform,
)
from .roles import infer_role

log = logging.getLogger(__name__)

CMD_VERSION = "show version"
CMD_CDP = "show cdp neighbors detail"
CMD_LLDP = "show lldp neighbors detail"
CMD_IF_STATUS = "show interfaces status"
CMD_IP_BRIEF = "show ip interface brief"

ConnectFactory = Callable[[str], Connection]


@dataclass
class DiscoveryResult:
    devices: dict[str, Device] = field(default_factory=dict)
    links: dict[tuple, Link] = field(default_factory=dict)
    scanned: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def add_link(self, link: Link) -> None:
        existing = self.links.get(link.key)
        self.links[link.key] = existing.merged_with(link) if existing else link


class Discoverer:
    def __init__(
        self,
        connect_factory: ConnectFactory,
        *,
        protocols: Sequence[str] = ("cdp", "lldp"),
        enrich: bool = False,
        max_devices: int = 100,
        keep_domain: bool = False,
    ):
        self._connect = connect_factory
        self._protocols = tuple(protocols)
        self._enrich = enrich
        self._max_devices = max_devices
        self._keep_domain = keep_domain
        self._visited: set[str] = set()
        self._queued: set[str] = set()

    # ------------------------------------------------------------------ public

    def run(self, seeds: Sequence[str]) -> DiscoveryResult:
        result = DiscoveryResult()
        queue: deque[tuple[str, str | None, str]] = deque(
            (seed, None, "seed") for seed in seeds
        )

        while queue:
            host, expected_key, via = queue.popleft()
            if len(self._visited) >= self._max_devices:
                log.warning("reached max_devices=%d, stopping walk", self._max_devices)
                break
            self._scan(host, expected_key, via, result, queue)

        return result

    # ----------------------------------------------------------------- internal

    def _scan(self, host, expected_key, via, result, queue) -> None:
        try:
            conn = self._connect(host)
        except (ConnectionError_, Exception) as exc:  # noqa: BLE001 - report, don't crash
            self._record_failure(host, expected_key, via, result, exc)
            return

        try:
            version = self._safe(conn, CMD_VERSION)
            hostname = parse_hostname(version) or self._prompt_hostname(conn) or host
            key = device_key(hostname, self._keep_domain)
            if key in self._visited:
                return
            self._visited.add(key)
            result.scanned.append(key)

            device = self._ensure_device(result, hostname, via)
            device.reachable = True
            device.label = normalize_hostname(hostname, self._keep_domain)
            if looks_like_ip(host):
                device.mgmt_ip = device.mgmt_ip or host
            device.platform = device.platform or parse_platform(version)

            for record in self._collect_neighbors(conn):
                self._process_neighbor(result, device, record, queue)

            if self._enrich:
                self._enrich_interfaces(conn, device)
        finally:
            conn.disconnect()

    def _collect_neighbors(self, conn: Connection) -> list[NeighborRecord]:
        records: list[NeighborRecord] = []
        if "cdp" in self._protocols:
            records += parse_cdp_detail(self._safe(conn, CMD_CDP))
        if "lldp" in self._protocols:
            records += parse_lldp_detail(self._safe(conn, CMD_LLDP))
        return records

    def _process_neighbor(self, result, local_dev, record, queue) -> None:
        neighbor = self._ensure_device(
            result, record.remote_device, f"{record.protocol}:{local_dev.label}"
        )
        if record.mgmt_ip and not neighbor.mgmt_ip:
            neighbor.mgmt_ip = record.mgmt_ip
        if record.platform and not neighbor.platform:
            neighbor.platform = record.platform
        role = infer_role(record.capabilities)
        if role != "unknown" and neighbor.role == "unknown":
            neighbor.role = role

        result.add_link(
            Link.between(
                local_dev.name,
                record.local_interface,
                neighbor.name,
                record.remote_interface,
                record.protocol,
            )
        )

        if (
            record.mgmt_ip
            and neighbor.name not in self._visited
            and neighbor.name not in self._queued
        ):
            self._queued.add(neighbor.name)
            queue.append(
                (record.mgmt_ip, neighbor.name, f"{record.protocol}:{local_dev.label}")
            )

    def _enrich_interfaces(self, conn: Connection, device: Device) -> None:
        states = parse_interface_status(self._safe(conn, CMD_IF_STATUS))
        if not states:
            states = parse_ip_interface_brief(self._safe(conn, CMD_IP_BRIEF))
        for name, info in states.items():
            device.interfaces.setdefault(name, {}).update(info)

    # ------------------------------------------------------------------ helpers

    def _ensure_device(self, result: DiscoveryResult, name_raw: str, via: str) -> Device:
        key = device_key(name_raw, self._keep_domain)
        device = result.devices.get(key)
        if device is None:
            device = Device(
                name=key,
                label=normalize_hostname(name_raw, self._keep_domain),
                discovered_via=via,
            )
            result.devices[key] = device
        return device

    def _record_failure(self, host, expected_key, via, result, exc) -> None:
        message = str(exc)
        log.warning("failed to scan %s: %s", host, message)
        result.failed.append(host)
        target = expected_key or device_key(host, self._keep_domain)
        self._visited.add(target)
        device = result.devices.get(target)
        if device is None:
            device = Device(name=target, label=host, discovered_via=via, reachable=False)
            result.devices[target] = device
        device.errors.append(message)

    @staticmethod
    def _safe(conn: Connection, command: str) -> str:
        try:
            return conn.send_command(command) or ""
        except Exception as exc:  # noqa: BLE001 - a missing command must not abort a scan
            log.debug("command %r failed: %s", command, exc)
            return ""

    @staticmethod
    def _prompt_hostname(conn: Connection) -> str | None:
        try:
            return conn.find_prompt().strip().rstrip("#>").strip() or None
        except Exception:  # pragma: no cover
            return None
