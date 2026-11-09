"""Turn the latest probe results into a topology snapshot the viewer understands."""
from __future__ import annotations

import ipaddress
from collections import defaultdict
from datetime import datetime, timezone

from .analysis import effective_losses, hop_status
from .redact import Redactor
from .store import ProbeStore

SNAPSHOT_VERSION = 1
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_SEVERITY = ["up", "unknown", "degraded", "down"]


def describe_scope(host: str | None) -> str | None:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return None
    if ip in _CGNAT:
        return "CGNAT / mesh VPN range"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        return "private network"
    if ip.is_global:
        return "public internet"
    return "reserved range"


def _worse(a: str, b: str) -> str:
    return a if _SEVERITY.index(a) >= _SEVERITY.index(b) else b


def _device(name: str, label: str, *, role: str, platform: str | None, ip: str | None,
            reachable: bool, via: str, errors: list[str] | None = None) -> dict:
    return {
        "name": name, "label": label, "mgmt_ip": ip, "platform": platform, "role": role,
        "reachable": reachable, "discovered_via": via, "interfaces": {}, "errors": errors or [],
    }


def build_path_snapshot(store: ProbeStore, redactor: Redactor) -> dict:
    devices: dict[str, dict] = {
        "probe": _device("probe", "this server", role="endpoint", platform="probe origin",
                         ip=None, reachable=True, via="probe"),
    }
    links: dict[tuple[str, str], dict] = {}
    seen_metrics: dict[str, list[tuple[float, float]]] = defaultdict(list)
    targets: set[str] = set()  # hops that are the end of some path
    forwarding: set[str] = set()  # hops that sit in the middle of some path
    runs = store.latest_runs()

    def add_link(a: str, a_if: str, b: str, b_if: str, status: str) -> None:
        if a == b:
            return
        key = tuple(sorted((a, b)))
        if key in links:
            links[key]["status"] = _worse(links[key]["status"], status)
            return
        (ad, ai), (bd, bi) = sorted([(a, a_if), (b, b_if)])
        links[key] = {
            "a_device": ad, "a_interface": ai, "b_device": bd, "b_interface": bi,
            "protocols": ["probe"], "status": status,
        }

    for run in runs:
        via = f"probe:{run.target}"
        losses = effective_losses(run.hops)
        prev_id, prev_ttl = "probe", 0
        last_ttl = run.hops[-1].ttl if run.hops else 0

        for hop in run.hops:
            status = hop_status(losses[hop.ttl])
            if hop.host is None:
                node_id = f"silent-{run.target}-{hop.ttl}"
                devices.setdefault(node_id, _device(
                    node_id, f"no reply (hop {hop.ttl})", role="unknown", platform=None,
                    ip=None, reachable=False, via=via))
            else:
                node_id = redactor.ip(hop.host)
                is_target = run.reached and hop.ttl == last_ttl
                device = devices.setdefault(node_id, _device(
                    node_id, node_id, role="router", platform=describe_scope(hop.host),
                    ip=node_id, reachable=True, via=via))
                if is_target:
                    device["label"] = run.target
                    targets.add(node_id)
                else:
                    forwarding.add(node_id)
                seen_metrics[node_id].append((hop.avg, losses[hop.ttl] or 0.0))
            add_link(prev_id, "probe" if prev_ttl == 0 else f"hop {prev_ttl}",
                     node_id, f"hop {hop.ttl}", status)
            prev_id, prev_ttl = node_id, hop.ttl

        if not run.reached:
            dest_id = f"unreached-{run.target}"
            reason = redactor.scrub(run.error) if not run.ok else "no reply from target"
            devices[dest_id] = _device(
                dest_id, run.target, role="endpoint", platform=None, ip=None,
                reachable=False, via=via, errors=[reason or "no reply from target"])
            add_link(prev_id, "probe" if prev_ttl == 0 else f"hop {prev_ttl}",
                     dest_id, "target", "down" if run.ok else "unknown")

    for node_id in targets - forwarding:  # a modem that also carries other paths stays a router
        devices[node_id]["role"] = "endpoint"

    for node_id, samples in seen_metrics.items():
        devices[node_id]["metrics"] = {
            "avg_ms": round(sum(a for a, _ in samples) / len(samples), 2),
            "loss_pct": round(max(loss for _, loss in samples), 1),
            "paths": len(samples),
        }

    device_list = sorted(devices.values(), key=lambda d: d["name"])
    link_list = sorted(links.values(), key=lambda l: (l["a_device"], l["a_interface"]))
    reachable = sum(1 for d in device_list if d["reachable"])
    failed = sum(1 for d in device_list if d["errors"] and not d["reachable"])
    return {
        "version": SNAPSHOT_VERSION,
        "mode": "probe",
        "redacted": redactor.enabled,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seeds": [r.target for r in runs],
        "stats": {
            "devices": len(device_list), "reachable": reachable, "failed": failed,
            "not_scanned": len(device_list) - reachable - failed, "links": len(link_list),
            "endpoints": sum(1 for d in device_list if d["role"] == "endpoint"),
        },
        "devices": device_list,
        "links": link_list,
    }


def build_paths_api(store: ProbeStore, redactor: Redactor, now: float) -> dict:
    """Per-target hop tables for ``/api/paths``."""
    counts = store.change_counts()
    paths = []
    for run in store.latest_runs():
        losses = effective_losses(run.hops)
        paths.append({
            "target": run.target,
            "ts": run.ts,
            "age_seconds": max(0, round(now - run.ts)),
            "ok": run.ok,
            "reached": run.reached,
            "error": redactor.scrub(run.error),
            "path_changes": counts.get(run.target, 0),
            "hops": [
                {
                    "ttl": h.ttl,
                    "host": redactor.ip(h.host),
                    "scope": describe_scope(h.host),
                    "status": hop_status(losses[h.ttl]),
                    "loss_pct": round(h.loss, 1),
                    "effective_loss_pct": None if losses[h.ttl] is None else round(losses[h.ttl], 1),
                    "sent": h.sent,
                    "avg_ms": round(h.avg, 2),
                    "best_ms": round(h.best, 2),
                    "worst_ms": round(h.worst, 2),
                    "stdev_ms": round(h.stdev, 2),
                }
                for h in run.hops
            ],
        })
    return {"generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
            "redacted": redactor.enabled, "paths": paths}


def build_changes_api(store: ProbeStore, redactor: Redactor, limit: int = 50) -> dict:
    def mask(signature: str) -> list[str]:
        return [redactor.ip(h) or h for h in signature.split(">") if h]

    return {
        "redacted": redactor.enabled,
        "changes": [
            {"target": c.target, "ts": c.ts, "old_path": mask(c.old_signature),
             "new_path": mask(c.new_signature)}
            for c in store.recent_changes(limit)
        ],
    }
