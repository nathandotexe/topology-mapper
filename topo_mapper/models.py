"""Core data structures for discovery results."""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class NeighborRecord:
    """One neighbor entry parsed from CDP/LLDP output on a single device."""

    local_interface: str
    remote_interface: str
    remote_device: str
    mgmt_ip: str | None = None
    platform: str | None = None
    capabilities: tuple[str, ...] = ()
    protocol: str = "cdp"  # "cdp" | "lldp"


@dataclass
class Device:
    """A node in the topology graph."""

    name: str  # canonical key: lowercase, domain stripped
    label: str  # display name (device's own hostname / advertised device-id)
    mgmt_ip: str | None = None
    platform: str | None = None
    role: str = "unknown"  # router | switch | l3-switch | endpoint | unknown
    reachable: bool = False  # did we successfully SSH in and read neighbors?
    discovered_via: str = "seed"  # "seed" | "cdp:<device>" | "lldp:<device>"
    interfaces: dict[str, dict] = field(default_factory=dict)  # ifname -> {status, vlan, ...}
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Link:
    """An undirected link between two devices, canonicalized on construction."""

    a_device: str
    a_interface: str
    b_device: str
    b_interface: str
    protocols: frozenset[str] = frozenset()

    @staticmethod
    def between(d1: str, i1: str, d2: str, i2: str, protocol: str) -> "Link":
        (ad, ai), (bd, bi) = sorted([(d1, i1), (d2, i2)])
        return Link(ad, ai, bd, bi, frozenset({protocol}))

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.a_device, self.a_interface, self.b_device, self.b_interface)

    def merged_with(self, other: "Link") -> "Link":
        return replace(self, protocols=self.protocols | other.protocols)
