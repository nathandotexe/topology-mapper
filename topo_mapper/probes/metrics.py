"""Prometheus text exposition for probe results.

Hop addresses appear only as the ``host`` label of ``topo_hop_info`` so that
the other series keep stable labels when a route changes. With redaction on
(the default) public addresses are masked there as well.
"""
from __future__ import annotations

from .analysis import effective_losses
from .graphview import describe_scope
from .redact import Redactor
from .store import ProbeStore

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_HELP = {
    "topo_probe_up": ("gauge", "1 if the latest probe reached the target, else 0."),
    "topo_probe_run_ok": ("gauge", "1 if the latest probe ran and produced a usable report."),
    "topo_probe_last_run_timestamp_seconds": ("gauge", "Unix time of the latest probe run."),
    "topo_probe_hops": ("gauge", "Number of hops that answered in the latest probe."),
    "topo_target_rtt_seconds": ("gauge", "Average round-trip time to the target."),
    "topo_target_loss_ratio": ("gauge", "Packet loss to the target, 0 to 1."),
    "topo_path_changes_total": ("counter", "Route changes detected for the target."),
    "topo_hop_rtt_seconds": ("gauge", "Average round-trip time to a hop."),
    "topo_hop_loss_ratio": ("gauge", "Effective loss at a hop, 0 to 1 (rate-limited middle hops ignored)."),
    "topo_hop_responding": ("gauge", "1 if the hop answered at all."),
    "topo_hop_info": ("gauge", "Address of the hop at this position in the latest path."),
}


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels: object) -> str:
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items()) + "}"


def _number(value: float) -> str:
    return format(float(value), ".6g")


def render_metrics(store: ProbeStore, redactor: Redactor) -> str:
    series: dict[str, list[str]] = {name: [] for name in _HELP}
    counts = store.change_counts()

    for run in store.latest_runs():
        target = _labels(target=run.target)
        series["topo_probe_up"].append(f"topo_probe_up{target} {int(run.reached)}")
        series["topo_probe_run_ok"].append(f"topo_probe_run_ok{target} {int(run.ok)}")
        series["topo_probe_last_run_timestamp_seconds"].append(
            f"topo_probe_last_run_timestamp_seconds{target} {_number(run.ts)}")
        series["topo_probe_hops"].append(
            f"topo_probe_hops{target} {sum(1 for h in run.hops if h.host)}")
        series["topo_path_changes_total"].append(
            f"topo_path_changes_total{target} {counts.get(run.target, 0)}")

        if run.ok and run.reached and run.hops:
            final = run.hops[-1]
            series["topo_target_rtt_seconds"].append(
                f"topo_target_rtt_seconds{target} {_number(final.avg / 1000)}")
            series["topo_target_loss_ratio"].append(
                f"topo_target_loss_ratio{target} {_number(final.loss / 100)}")

        losses = effective_losses(run.hops)
        for hop in run.hops:
            hop_labels = _labels(target=run.target, hop=hop.ttl)
            responding = hop.host is not None
            series["topo_hop_responding"].append(
                f"topo_hop_responding{hop_labels} {int(responding)}")
            if responding:
                series["topo_hop_rtt_seconds"].append(
                    f"topo_hop_rtt_seconds{hop_labels} {_number(hop.avg / 1000)}")
                series["topo_hop_loss_ratio"].append(
                    f"topo_hop_loss_ratio{hop_labels} {_number((losses[hop.ttl] or 0.0) / 100)}")
                info = _labels(target=run.target, hop=hop.ttl, host=redactor.ip(hop.host),
                               scope=describe_scope(hop.host) or "unknown")
                series["topo_hop_info"].append(f"topo_hop_info{info} 1")

    lines: list[str] = []
    for name, samples in series.items():
        if not samples:
            continue
        kind, text = _HELP[name]
        lines += [f"# HELP {name} {text}", f"# TYPE {name} {kind}", *samples]
    return "\n".join(lines) + "\n"
