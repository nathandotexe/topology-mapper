"""Dependency-free HTML report: summary stats plus device and link tables.

Unlike the Cytoscape viewer this needs no JavaScript or CDN, so it renders
anywhere (air-gapped hosts, email attachments, a quick ``open topo.html``).
"""
from __future__ import annotations

from html import escape

from ..roles import ROLE_COLORS, UNREACHABLE_COLOR

_CSS = """
:root { --bg:#ffffff; --text:#1d2433; --muted:#5f6b85; --border:#dde2ec; --head:#f3f5f9;
  --up:#2e8b57; --down:#d64545; --unknown:#8a8a8a; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#0f1420; --text:#e6e9f2; --muted:#9aa4bf; --border:#2a3350; --head:#171e2e; }
}
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px; background: var(--bg); color: var(--text);
  font: 14px/1.5 system-ui, sans-serif; }
main { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; }
.meta { color: var(--muted); font-size: 13px; margin: 0; }
.stats { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.stat { border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; min-width: 110px; }
.stat b { display: block; font-size: 20px; }
.stat span { color: var(--muted); font-size: 12px; }
.scroll { overflow-x: auto; }
table { width: 100%; min-width: 960px; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border);
  vertical-align: top; }
th { background: var(--head); font-weight: 600; white-space: nowrap; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; }
.badge { display: inline-block; padding: 0 7px; border-radius: 10px; font-size: 12px;
  color: #fff; }
.up { background: var(--up); } .down { background: var(--down); }
.unknown { background: var(--unknown); }
.err { color: var(--down); }
.muted { color: var(--muted); }
td:first-child { white-space: nowrap; }
td.platform { min-width: 280px; }
"""


def _cell(value) -> str:
    if value in (None, "", []):
        return '<span class="muted">—</span>'
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return escape(str(value))


def _badge(status: str, text: str | None = None) -> str:
    cls = status if status in ("up", "down") else "unknown"
    return f'<span class="badge {cls}">{escape(text or status)}</span>'


def _device_state(dev: dict) -> str:
    if dev.get("reachable"):
        return _badge("up", "reachable")
    if dev.get("errors"):
        return _badge("down", "failed")
    return _badge("unknown", "not scanned")


def to_simple_html(snapshot: dict) -> str:
    stats = snapshot.get("stats", {})
    labels = {d["name"]: d["label"] for d in snapshot.get("devices", [])}

    stat_items = [
        ("devices", stats.get("devices")),
        ("reachable", stats.get("reachable")),
        ("failed", stats.get("failed")),
        ("not scanned", stats.get("not_scanned")),
        ("links", stats.get("links")),
        ("endpoints", stats.get("endpoints")),
    ]
    stat_html = "".join(
        f'<div class="stat"><b>{_cell(v)}</b><span>{escape(k)}</span></div>'
        for k, v in stat_items
    )

    device_rows = []
    for dev in snapshot.get("devices", []):
        failed = bool(dev.get("errors")) and not dev.get("reachable")
        role = dev.get("role", "unknown")
        color = UNREACHABLE_COLOR if failed else ROLE_COLORS.get(role, ROLE_COLORS["unknown"])
        errors = (
            f'<div class="err">{_cell(dev["errors"])}</div>' if dev.get("errors") else ""
        )
        device_rows.append(
            "<tr>"
            f'<td><i class="dot" style="background:{color}"></i>{_cell(dev["label"])}</td>'
            f"<td>{_cell(role)}</td>"
            f"<td>{_cell(dev.get('mgmt_ip'))}</td>"
            f"<td>{_device_state(dev)}{errors}</td>"
            f"<td>{_cell(dev.get('discovered_via'))}</td>"
            f'<td class="platform">{_cell(dev.get("platform"))}</td>'
            "</tr>"
        )

    link_rows = []
    for link in snapshot.get("links", []):
        a = labels.get(link["a_device"], link["a_device"])
        b = labels.get(link["b_device"], link["b_device"])
        link_rows.append(
            "<tr>"
            f"<td>{_cell(a)}</td><td>{_cell(link['a_interface'])}</td>"
            f"<td>{_cell(b)}</td><td>{_cell(link['b_interface'])}</td>"
            f"<td>{_cell(link.get('protocols'))}</td>"
            f"<td>{_badge(link.get('status', 'unknown'))}</td>"
            "</tr>"
        )

    seeds = ", ".join(snapshot.get("seeds", [])) or "—"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Topology Report</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>Topology report</h1>
<p class="meta">Generated {_cell(snapshot.get("generated_at"))} · seeds: {escape(seeds)}</p>
<div class="stats">{stat_html}</div>

<h2>Devices</h2>
<div class="scroll"><table>
<thead><tr><th>Device</th><th>Role</th><th>Mgmt IP</th><th>State</th><th>Found via</th><th>Platform</th></tr></thead>
<tbody>{"".join(device_rows)}</tbody>
</table></div>

<h2>Links</h2>
<div class="scroll"><table>
<thead><tr><th>Device A</th><th>Interface A</th><th>Device B</th><th>Interface B</th><th>Protocols</th><th>Status</th></tr></thead>
<tbody>{"".join(link_rows)}</tbody>
</table></div>
</main>
</body>
</html>
"""
