"""Masking of public IP addresses in anything that leaves the probe database.

Private, loopback, link-local and CGNAT/mesh-VPN addresses (100.64.0.0/10) are
left alone because they say nothing about where the network sits on the
internet. Public addresses become ``pub-<hash>``: stable for one installation
(keyed by a random salt kept in the database) so graphs and metrics stay
usable, but not reversible or comparable across installations.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re

_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6 = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")


def is_public(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


class Redactor:
    def __init__(self, salt: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self._key = (salt or "").encode("utf-8")

    def ip(self, value: str | None) -> str | None:
        if value is None or not self.enabled or not is_public(value):
            return value
        digest = hmac.new(self._key, value.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"pub-{digest[:8]}"

    def scrub(self, text: str | None) -> str | None:
        """Replace public IPs embedded in free text such as tool error messages."""
        if text is None or not self.enabled:
            return text

        def swap(match: re.Match) -> str:
            return self.ip(match.group(0)) or match.group(0)

        return _IPV6.sub(swap, _IPV4.sub(swap, text))
