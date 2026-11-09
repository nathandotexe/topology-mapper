"""Authentication, brute-force limiting and response headers for the web viewer.

The viewer shows the shape of a home network, so it refuses to listen on a
non-loopback address without a password, and it never loads anything from a
third-party host.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import time
from dataclasses import dataclass

MIN_PASSWORD_LENGTH = 12
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300
MAX_TRACKED_CLIENTS = 1024
OPEN_PATHS = {"/healthz"}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


@dataclass(frozen=True)
class AuthConfig:
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "AuthConfig | None":
        password = os.getenv("TOPO_WEB_PASSWORD", "")
        if not password:
            return None
        if len(password) < MIN_PASSWORD_LENGTH:
            raise SystemExit(
                f"TOPO_WEB_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters."
            )
        return cls(user=os.getenv("TOPO_WEB_USER", "admin"), password=password)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def ensure_safe_bind(host: str, auth: AuthConfig | None) -> None:
    if auth is None and not is_loopback(host):
        raise SystemExit(
            f"Refusing to listen on {host} without a password. "
            "Set TOPO_WEB_PASSWORD (12+ characters), or bind to 127.0.0.1."
        )


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def credentials_match(header: str | None, auth: AuthConfig) -> bool:
    """Constant-time check of an ``Authorization: Basic`` header."""
    user, password = "", ""
    if header and header[:6].lower() == "basic ":
        try:
            decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
            user, _, password = decoded.partition(":")
        except (ValueError, UnicodeDecodeError):
            pass
    user_ok = hmac.compare_digest(_digest(user), _digest(auth.user))
    pass_ok = hmac.compare_digest(_digest(password), _digest(auth.password))
    return user_ok and pass_ok


class FailureLimiter:
    """Locks a client out after repeated bad logins. In memory, bounded."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._state: dict[str, tuple[int, float]] = {}  # client -> (failures, locked_until)

    def blocked(self, client: str) -> bool:
        failures, locked_until = self._state.get(client, (0, 0.0))
        if locked_until and self._clock() >= locked_until:
            del self._state[client]
            return False
        return locked_until > 0 and self._clock() < locked_until

    def failure(self, client: str) -> None:
        if len(self._state) >= MAX_TRACKED_CLIENTS and client not in self._state:
            self._state.pop(next(iter(self._state)))
        failures, _ = self._state.get(client, (0, 0.0))
        failures += 1
        locked_until = self._clock() + LOCKOUT_SECONDS if failures >= MAX_FAILURES else 0.0
        self._state[client] = (failures, locked_until)

    def success(self, client: str) -> None:
        self._state.pop(client, None)
