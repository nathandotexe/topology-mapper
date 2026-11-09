"""Cytoscape.js element export + standalone HTML viewer bundling."""
from __future__ import annotations

import json
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
_VIEWER = _STATIC / "index.html"
_BOOTSTRAP_MARKER = "const BOOTSTRAP = null;"
_LIBRARY_TAG = '<script src="static/cytoscape.min.js"></script>'


def to_cytoscape(snapshot: dict) -> dict:
    """Return ``{elements: [...], meta: {...}}`` ready for ``cytoscape({ elements })``."""
    elements: list[dict] = []

    for dev in snapshot.get("devices", []):
        elements.append(
            {
                "data": {
                    "id": dev["name"],
                    "label": dev["label"],
                    "role": dev.get("role", "unknown"),
                    "reachable": bool(dev.get("reachable")),
                    "failed": bool(dev.get("errors")) and not dev.get("reachable"),
                    "platform": dev.get("platform"),
                    "mgmt_ip": dev.get("mgmt_ip"),
                    "discovered_via": dev.get("discovered_via"),
                    "errors": dev.get("errors", []),
                    "metrics": dev.get("metrics"),
                }
            }
        )

    for idx, link in enumerate(snapshot.get("links", [])):
        elements.append(
            {
                "data": {
                    "id": f"e{idx}",
                    "source": link["a_device"],
                    "target": link["b_device"],
                    "label": f'{link["a_interface"]} — {link["b_interface"]}',
                    "a_interface": link["a_interface"],
                    "b_interface": link["b_interface"],
                    "protocols": link.get("protocols", []),
                    "status": link.get("status", "unknown"),
                }
            }
        )

    return {
        "elements": elements,
        "meta": {
            "generated_at": snapshot.get("generated_at"),
            "seeds": snapshot.get("seeds", []),
            "stats": snapshot.get("stats", {}),
        },
    }


def to_standalone_html(snapshot: dict) -> str:
    """Inline the snapshot into the viewer template -> one shareable .html file."""
    template = _VIEWER.read_text(encoding="utf-8")
    payload = json.dumps(to_cytoscape(snapshot)).replace("</", "<\\/")
    if _BOOTSTRAP_MARKER not in template or _LIBRARY_TAG not in template:  # pragma: no cover
        raise RuntimeError("viewer template is missing the BOOTSTRAP marker or library tag")
    library = (_STATIC / "cytoscape.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    template = template.replace(_LIBRARY_TAG, f"<script>{library}</script>")
    return template.replace(_BOOTSTRAP_MARKER, f"const BOOTSTRAP = {payload};")
