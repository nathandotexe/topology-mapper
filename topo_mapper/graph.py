"""Build a NetworkX graph and JSON snapshots from a DiscoveryResult."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx

from .discovery import DiscoveryResult

SNAPSHOT_VERSION = 1


def _link_status(result: DiscoveryResult, device: str, interface: str) -> str:
    dev = result.devices.get(device)
    if not dev:
        return "unknown"
    return dev.interfaces.get(interface, {}).get("status", "unknown")


def combined_link_status(result: DiscoveryResult, link) -> str:
    a = _link_status(result, link.a_device, link.a_interface)
    b = _link_status(result, link.b_device, link.b_interface)
    if "down" in (a, b):
        return "down"
    if a == "up" or b == "up":
        return "up"
    return "unknown"


def build_graph(result: DiscoveryResult) -> nx.Graph:
    graph = nx.Graph()
    for key, dev in result.devices.items():
        graph.add_node(
            key,
            label=dev.label,
            mgmt_ip=dev.mgmt_ip,
            platform=dev.platform,
            role=dev.role,
            reachable=dev.reachable,
            discovered_via=dev.discovered_via,
            errors=list(dev.errors),
        )
    for link in result.links.values():
        graph.add_edge(
            link.a_device,
            link.b_device,
            a_interface=link.a_interface,
            b_interface=link.b_interface,
            protocols=sorted(link.protocols),
            status=combined_link_status(result, link),
        )
    return graph


def build_snapshot(result: DiscoveryResult, seeds: list[str]) -> dict:
    devices = []
    for dev in result.devices.values():
        devices.append(
            {
                "name": dev.name,
                "label": dev.label,
                "mgmt_ip": dev.mgmt_ip,
                "platform": dev.platform,
                "role": dev.role,
                "reachable": dev.reachable,
                "discovered_via": dev.discovered_via,
                "interfaces": dev.interfaces,
                "errors": dev.errors,
            }
        )
    links = []
    for link in result.links.values():
        links.append(
            {
                "a_device": link.a_device,
                "a_interface": link.a_interface,
                "b_device": link.b_device,
                "b_interface": link.b_interface,
                "protocols": sorted(link.protocols),
                "status": combined_link_status(result, link),
            }
        )

    reachable = sum(1 for d in result.devices.values() if d.reachable)
    failed = sum(1 for d in result.devices.values() if d.errors and not d.reachable)
    return {
        "version": SNAPSHOT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seeds": list(seeds),
        "stats": {
            "devices": len(devices),
            "reachable": reachable,
            "failed": failed,
            "not_scanned": len(devices) - reachable - failed,
            "links": len(links),
            "endpoints": sum(1 for d in result.devices.values() if d.role == "endpoint"),
        },
        "devices": sorted(devices, key=lambda d: d["name"]),
        "links": sorted(links, key=lambda l: (l["a_device"], l["a_interface"])),
    }


def save_snapshot(path: str | Path, snapshot: dict) -> None:
    Path(path).write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")


def load_snapshot(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
