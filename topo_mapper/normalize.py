
from __future__ import annotations

import re

_IF_PREFIX_MAP = {
    "fa": "FastEthernet",
    "fas": "FastEthernet",
    "fast": "FastEthernet",
    "fastethernet": "FastEthernet",
    "gi": "GigabitEthernet",
    "gig": "GigabitEthernet",
    "ge": "GigabitEthernet",
    "gigabitethernet": "GigabitEthernet",
    "te": "TenGigabitEthernet",
    "ten": "TenGigabitEthernet",
    "tengige": "TenGigabitEthernet",
    "tengigabitethernet": "TenGigabitEthernet",
    "twe": "TwentyFiveGigE",
    "twentyfivegige": "TwentyFiveGigE",
    "fo": "FortyGigabitEthernet",
    "fortygige": "FortyGigabitEthernet",
    "fortygigabitethernet": "FortyGigabitEthernet",
    "hu": "HundredGigE",
    "hundredgige": "HundredGigE",
    "eth": "Ethernet",
    "et": "Ethernet",
    "ethernet": "Ethernet",
    "po": "Port-channel",
    "portchannel": "Port-channel",
    "port-channel": "Port-channel",
    "lo": "Loopback",
    "loopback": "Loopback",
    "vl": "Vlan",
    "vlan": "Vlan",
    "tu": "Tunnel",
    "tunnel": "Tunnel",
    "ma": "Management",
    "mgmt": "Management",
    "management": "Management",
    "se": "Serial",
    "serial": "Serial",
}

_IF_RE = re.compile(r"^\s*([A-Za-z][A-Za-z-]*?)\s*(\d[\d/.:]*)\s*$")
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


def looks_like_ip(value: str) -> bool:
    return bool(_IP_RE.match(value or ""))


def normalize_interface(name: str) -> str:
    """``Gi0/1`` -> ``GigabitEthernet0/1``. Unknown prefixes pass through joined."""
    if not name:
        return name
    match = _IF_RE.match(name.strip())
    if not match:
        return name.strip()
    prefix, number = match.group(1), match.group(2)
    full = _IF_PREFIX_MAP.get(prefix.lower())
    return f"{full}{number}" if full else f"{prefix}{number}"


def normalize_hostname(device_id: str, keep_domain: bool = False) -> str:
    """Strip trailing ``(serial)``, drop any description, optionally drop domain."""
    if not device_id:
        return device_id
    host = device_id.strip()
    host = re.sub(r"\s*\([^)]*\)\s*$", "", host)  # SW1(FDO1234ABCD) -> SW1
    host = host.split()[0] if host.split() else host
    if not keep_domain and "." in host and not looks_like_ip(host):
        host = host.split(".", 1)[0]
    return host


def device_key(device_id: str, keep_domain: bool = False) -> str:
    """Canonical, case-insensitive identity used as the graph node id."""
    return normalize_hostname(device_id, keep_domain).lower()
