"""Export to Grafana Node Graph panel format.

Shape matches the "Node Graph API" datasource / Infinity JSON: a ``nodes`` array
and an ``edges`` array with the field names the panel maps by default.
See https://grafana.com/docs/grafana/latest/panels-visualizations/visualizations/node-graph/
"""
from __future__ import annotations

from ..roles import ROLE_COLORS, UNREACHABLE_COLOR


def to_grafana_nodegraph(snapshot: dict) -> dict:
    nodes = []
    for dev in snapshot.get("devices", []):
        failed = bool(dev.get("errors")) and not dev.get("reachable")
        nodes.append(
            {
                "id": dev["name"],
                "title": dev["label"],
                "subTitle": dev.get("mgmt_ip") or "",
                "mainStat": dev.get("role", "unknown"),
                "secondaryStat": (dev.get("platform") or "")[:60],
                "color": UNREACHABLE_COLOR
                if failed
                else ROLE_COLORS.get(dev.get("role", "unknown"), ROLE_COLORS["unknown"]),
                "icon": "exclamation-triangle" if failed else "",
            }
        )

    edges = []
    for idx, link in enumerate(snapshot.get("links", [])):
        edges.append(
            {
                "id": f"e{idx}",
                "source": link["a_device"],
                "target": link["b_device"],
                "mainStat": f'{link["a_interface"]} ↔ {link["b_interface"]}',
                "secondaryStat": "/".join(link.get("protocols", [])) or "",
                "color": UNREACHABLE_COLOR if link.get("status") == "down" else "#b0b7c3",
            }
        )

    return {"nodes": nodes, "edges": edges}
