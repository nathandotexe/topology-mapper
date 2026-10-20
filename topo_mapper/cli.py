"""Command-line interface for Topo Mapper."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from . import __version__
from .connections import MockLab, bundled_demo_lab, netmiko_factory
from .discovery import Discoverer
from .exporters import FORMATS
from .graph import build_snapshot, load_snapshot, save_snapshot

DEFAULT_OUT = "topology.json"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover - optional convenience
        pass


def _load_inventory(path: str | None) -> dict:
    if not path:
        return {}
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _resolve_seeds(args, inventory: dict, mock_lab: MockLab | None) -> list[str]:
    if args.seed:
        return list(args.seed)
    if mock_lab and mock_lab.seeds:
        return list(mock_lab.seeds)
    if os.getenv("TOPO_SEEDS"):
        return [s.strip() for s in os.getenv("TOPO_SEEDS").split(",") if s.strip()]
    if inventory.get("seeds"):
        return [str(s) for s in inventory["seeds"]]
    return []


def _print_summary(snapshot: dict, out_path: str) -> None:
    stats = snapshot["stats"]
    failed = [d["label"] for d in snapshot["devices"] if d["errors"] and not d["reachable"]]
    print(
        f"Discovered {stats['devices']} devices "
        f"({stats['reachable']} reachable, {stats['failed']} failed, "
        f"{stats['not_scanned']} not scanned), {stats['links']} links"
    )
    if failed:
        print(f"  failed to reach: {', '.join(failed)}")
    print(f"Snapshot written to {out_path}")


def _run_discovery(args, *, mock_lab: MockLab | None) -> dict:
    inventory = _load_inventory(getattr(args, "inventory", None))
    seeds = _resolve_seeds(args, inventory, mock_lab)
    if not seeds:
        sys.exit(
            "No seed devices. Pass --seed, set TOPO_SEEDS, or add 'seeds:' to the inventory."
        )

    factory = mock_lab.factory() if mock_lab else netmiko_factory(inventory)
    discoverer = Discoverer(
        factory,
        protocols=[p.strip() for p in args.protocol.split(",") if p.strip()],
        enrich=args.enrich,
        max_devices=args.max_devices,
        keep_domain=args.keep_domain,
    )
    result = discoverer.run(seeds)
    return build_snapshot(result, seeds)


# --------------------------------------------------------------------- commands


def cmd_discover(args) -> None:
    mock_lab = None
    if args.mock:
        mock_lab = MockLab(args.mock)
    snapshot = _run_discovery(args, mock_lab=mock_lab)
    save_snapshot(args.out, snapshot)
    _print_summary(snapshot, args.out)


def cmd_demo(args) -> None:
    mock_lab = MockLab(bundled_demo_lab())
    snapshot = _run_discovery(args, mock_lab=mock_lab)
    save_snapshot(args.out, snapshot)
    _print_summary(snapshot, args.out)
    if args.serve:
        from .web.app import serve

        print(f"Serving viewer on http://{args.host}:{args.port}")
        serve(args.out, host=args.host, port=args.port)


def cmd_export(args) -> None:
    snapshot = load_snapshot(args.in_path)
    if args.format == "json":
        rendered = json.dumps(snapshot, indent=2) + "\n"
    else:
        exporter = FORMATS[args.format]
        rendered = exporter(snapshot)
        if not isinstance(rendered, str):
            rendered = json.dumps(rendered, indent=2) + "\n"
    if args.out and args.out != "-":
        Path(args.out).write_text(rendered, encoding="utf-8")
        print(f"Wrote {args.format} export to {args.out}")
    else:
        sys.stdout.write(rendered)


def cmd_serve(args) -> None:
    from .web.app import serve

    if not Path(args.in_path).exists():
        sys.exit(f"Snapshot not found: {args.in_path} (run `topo-mapper discover` first)")
    print(f"Serving {args.in_path} on http://{args.host}:{args.port}")
    serve(args.in_path, host=args.host, port=args.port)


# ------------------------------------------------------------------- arg parsing


def _add_discovery_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", action="append", metavar="HOST", help="seed device (repeatable)")
    parser.add_argument("--protocol", default="cdp,lldp", help="cdp,lldp (default: both)")
    parser.add_argument("--enrich", action="store_true", help="pull interface up/down state")
    parser.add_argument("--max-devices", type=int, default=100, help="walk cap (default: 100)")
    parser.add_argument("--keep-domain", action="store_true", help="keep FQDN in node ids")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="topo-mapper", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_disc = sub.add_parser("discover", help="walk a live topology and write a snapshot")
    _add_discovery_flags(p_disc)
    p_disc.add_argument("--inventory", help="YAML inventory with per-device overrides")
    p_disc.add_argument("--mock", metavar="DIR", help="use a file-backed mock lab instead of SSH")
    p_disc.add_argument("--out", default=DEFAULT_OUT, help=f"snapshot path (default: {DEFAULT_OUT})")
    p_disc.set_defaults(func=cmd_discover)

    p_demo = sub.add_parser("demo", help="run discovery against the bundled mock lab")
    _add_discovery_flags(p_demo)
    p_demo.add_argument("--out", default=DEFAULT_OUT, help=f"snapshot path (default: {DEFAULT_OUT})")
    p_demo.add_argument("--serve", action="store_true", help="serve the viewer afterwards")
    p_demo.add_argument("--host", default="127.0.0.1")
    p_demo.add_argument("--port", type=int, default=8000)
    p_demo.set_defaults(func=cmd_demo)

    p_exp = sub.add_parser("export", help="convert a snapshot to another format")
    p_exp.add_argument("--in", dest="in_path", default=DEFAULT_OUT, help="snapshot to read")
    p_exp.add_argument(
        "--format",
        required=True,
        choices=sorted(FORMATS),
        help="cytoscape | grafana | mermaid | html | simple | json",
    )
    p_exp.add_argument("--out", default="-", help="output file, or - for stdout")
    p_exp.set_defaults(func=cmd_export)

    p_srv = sub.add_parser("serve", help="serve the interactive viewer for a snapshot")
    p_srv.add_argument("--in", dest="in_path", default=DEFAULT_OUT, help="snapshot to serve")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> None:
    _load_env()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
