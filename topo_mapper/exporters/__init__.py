"""Snapshot exporters for downstream visualization tools."""
from __future__ import annotations

from .cytoscape import to_cytoscape, to_standalone_html
from .grafana import to_grafana_nodegraph
from .text import to_mermaid

FORMATS = {
    "json": None,  # handled specially in the CLI (pretty passthrough)
    "cytoscape": to_cytoscape,
    "grafana": to_grafana_nodegraph,
    "mermaid": to_mermaid,
    "html": to_standalone_html,
}

__all__ = [
    "FORMATS",
    "to_cytoscape",
    "to_grafana_nodegraph",
    "to_mermaid",
    "to_standalone_html",
]
