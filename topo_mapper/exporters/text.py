"""Plain-text exports (Mermaid) for embedding a topology in Markdown/README."""
from __future__ import annotations

import re

_SAFE = re.compile(r"[^A-Za-z0-9_]")


def _node_id(name: str) -> str:
    slug = _SAFE.sub("_", name)
    return slug if slug and not slug[0].isdigit() else f"n_{slug}"


def to_mermaid(snapshot: dict) -> str:
    lines = ["graph LR"]

    for dev in snapshot.get("devices", []):
        marker = " (unreachable)" if dev.get("errors") and not dev.get("reachable") else ""
        role = dev.get("role", "unknown")
        lines.append(
            f'  {_node_id(dev["name"])}["{dev["label"]}<br/><small>{role}{marker}</small>"]'
        )

    for link in snapshot.get("links", []):
        label = f'{link["a_interface"]} &lt;-&gt; {link["b_interface"]}'
        left = _node_id(link["a_device"])
        right = _node_id(link["b_device"])
        if link.get("status") == "down":
            lines.append(f'  {left} -. "{label} (down)" .- {right}')
        else:
            lines.append(f'  {left} --- |"{label}"| {right}')

    return "\n".join(lines) + "\n"
