"""Parsers for Cisco IOS ``show`` output used during discovery.

These are deliberately regex-based and dependency-free so they can be unit
tested against captured fixtures. If ``ntc-templates`` is available you could
swap in Netmiko's ``use_textfsm=True`` and adapt the rows to ``NeighborRecord``.
"""
from __future__ import annotations

import re

from .models import NeighborRecord
from .normalize import normalize_interface

_DASH_LINE = re.compile(r"^[ \t]*-{4,}[ \t]*$", re.M)


def _split_blocks(text: str) -> list[str]:
    return [b.strip() for b in _DASH_LINE.split(text or "") if b.strip()]


def _first(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


# --------------------------------------------------------------------------- CDP


def parse_cdp_detail(text: str) -> list[NeighborRecord]:
    """Parse ``show cdp neighbors detail``."""
    records: list[NeighborRecord] = []
    for block in _split_blocks(text):
        device_id = _first(r"Device ID:\s*(.+)", block)
        if not device_id:
            continue

        local_if = _first(r"Interface:\s*([^,]+?)\s*,", block)
        remote_if = _first(r"Port ID \(outgoing port\):\s*(.+)", block)
        if not (local_if and remote_if):
            continue

        caps_raw = _first(r"Capabilities:\s*(.+)", block)
        platform = _first(r"Platform:\s*(.+?)\s*,\s*Capabilities:", block) or _first(
            r"Platform:\s*(.+)", block, re.M
        )

        records.append(
            NeighborRecord(
                local_interface=normalize_interface(local_if),
                remote_interface=normalize_interface(remote_if),
                remote_device=device_id.strip(),
                mgmt_ip=_first(r"IP(?:v4)? address:\s*([0-9.]+)", block, re.I),
                platform=platform,
                capabilities=tuple(caps_raw.split()) if caps_raw else (),
                protocol="cdp",
            )
        )
    return records


# -------------------------------------------------------------------------- LLDP


def parse_lldp_detail(text: str) -> list[NeighborRecord]:
    """Parse ``show lldp neighbors detail``."""
    records: list[NeighborRecord] = []
    for block in _split_blocks(text):
        local_if = _first(r"Local Intf:\s*(\S+)", block)
        if not local_if:
            continue

        port_desc = _first(r"Port Description:\s*(.+)", block)
        port_id = _first(r"Port id:\s*(\S+)", block, re.I)
        remote_if = port_desc or port_id
        remote_device = _first(r"System Name:\s*(.+)", block) or _first(
            r"Chassis id:\s*(\S+)", block, re.I
        )
        if not (remote_if and remote_device):
            continue

        caps_raw = _first(r"Enabled Capabilities:\s*(.+)", block) or _first(
            r"System Capabilities:\s*(.+)", block
        )
        sys_descr = _first(r"System Description:\s*\n\s*(.+)", block)

        records.append(
            NeighborRecord(
                local_interface=normalize_interface(local_if),
                remote_interface=normalize_interface(remote_if),
                remote_device=remote_device.strip(),
                mgmt_ip=_first(r"\bIP:\s*([0-9.]+)", block, re.I),
                platform=sys_descr.strip() if sys_descr else None,
                capabilities=tuple(c.strip() for c in caps_raw.split(",")) if caps_raw else (),
                protocol="lldp",
            )
        )
    return records


# --------------------------------------------------------------- interface state

_STATUS_UP = {"connected", "up"}
_STATUS_DOWN = {
    "notconnect",
    "notconnected",
    "disabled",
    "err-disabled",
    "down",
    "administratively",  # "administratively down"
}


def _classify_status(raw: str) -> str:
    token = (raw or "").strip().lower().split()[0] if raw and raw.strip() else ""
    if token in _STATUS_UP:
        return "up"
    if token in _STATUS_DOWN:
        return "down"
    return "unknown"


def parse_interface_status(text: str) -> dict[str, dict]:
    """Parse ``show interfaces status`` (switch style)."""
    result: dict[str, dict] = {}
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("Port "):
            continue
        cols = line.split()
        if len(cols) < 2:
            continue
        name = normalize_interface(cols[0])
        # status is the first column after an optional free-text "Name" field;
        # scan for a recognizable status token.
        status = "unknown"
        vlan = None
        for idx, col in enumerate(cols[1:], start=1):
            classified = _classify_status(col)
            if classified != "unknown" or col.lower() in {"monitoring", "faulty"}:
                status = classified
                vlan = cols[idx + 1] if idx + 1 < len(cols) else None
                break
        result[name] = {"status": status, "vlan": vlan}
    return result


def parse_ip_interface_brief(text: str) -> dict[str, dict]:
    """Parse ``show ip interface brief`` (router style)."""
    result: dict[str, dict] = {}
    for line in (text or "").splitlines():
        cols = line.split()
        if len(cols) < 6 or cols[0].lower() == "interface":
            continue
        name = normalize_interface(cols[0])
        protocol = cols[-1].lower()
        result[name] = {
            "status": "up" if protocol == "up" else "down",
            "ip": cols[1] if cols[1].lower() != "unassigned" else None,
        }
    return result


def parse_hostname(show_version: str) -> str | None:
    match = re.search(r"(?m)^(\S+)\s+uptime is\s", show_version or "")
    return match.group(1) if match else None


def parse_platform(show_version: str) -> str | None:
    return _first(r"(?m)^(Cisco .*Software.*?)(?:,\s*RELEASE|$)", show_version or "")
