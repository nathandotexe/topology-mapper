# Topo Mapper

Auto-discover a live network topology from CDP/LLDP neighbor data, build a graph
model, and visualize it — either in a self-contained Cytoscape.js viewer or as a
Grafana Node Graph panel.

Built as a network-engineering portfolio project: it demonstrates automated
discovery (Netmiko), a proper graph model (NetworkX), enrichment with live
interface state, and an observability-friendly output path.

```
seed device ──SSH──▶ show cdp/lldp neighbors detail ──▶ parse ──▶ BFS walk
                                                                     │
                       NetworkX graph  ◀── canonicalize nodes/edges ─┘
                             │
          ┌──────────────────┼─────────────────────┐
     topology.json     Cytoscape viewer       Grafana Node Graph
```

## Features

- **Recursive discovery** — start from one or more seeds, treat every discovered
  neighbor as a new seed (breadth-first) until the topology stops growing.
- **CDP and LLDP**, parsed independently and merged. Links seen by both protocols
  are recorded once, tagged `["cdp", "lldp"]`.
- **Canonicalization** — `Gi0/1` ⇄ `GigabitEthernet0/1`, `SW1.lab.local` ⇄
  `SW1(FDO123)` ⇄ `SW1`, so the graph never sprouts duplicate nodes or edges.
- **Graceful failure** — an unreachable or auth-failing device still appears as a
  partial node (from its neighbors' data) with the error attached.
- **Role inference** from CDP/LLDP capabilities (`router`, `switch`, `l3-switch`,
  `endpoint`).
- **Enrichment** (`--enrich`) — pulls `show interfaces status` /
  `show ip interface brief` and annotates links up/down.
- **No hardware required to try it** — a bundled mock lab replays captured
  `show` output.

## Install

Requires Python 3.10+.

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[web,dev]"
```

Core install (no viewer): `pip install -e .`

## Quickstart — the bundled demo

```bash
topo-mapper demo --serve
```

Runs discovery against `topo_mapper/demo_lab/` (a 5-switch lab with an IP phone
and an unreachable edge firewall), writes `topology.json`, and serves the
interactive viewer at http://127.0.0.1:8000.

Without a browser:

```bash
topo-mapper demo --out topology.json
topo-mapper export --in topology.json --format mermaid
```

## Against a real lab

1. `cp .env.example .env` and set `TOPO_USERNAME` / `TOPO_PASSWORD`.
2. (optional) `cp inventory.example.yaml inventory.yaml` for per-device overrides.
3. Discover:

```bash
topo-mapper discover --seed 10.0.0.1 --enrich --out topology.json
topo-mapper serve --in topology.json
```

Seeds may be given via `--seed` (repeatable), `TOPO_SEEDS`, or `seeds:` in the
inventory. Connection settings resolve lowest-to-highest:
Netmiko defaults → `.env` → inventory `defaults:` → inventory `devices.<host>:`.

> **Lab environment note.** Packet Tracer devices are not reachable over real SSH.
> Use GNS3/EVE-NG with IOSv/IOSv-L2, a CML/DevNet sandbox, or physical gear.

## Commands

| Command | Purpose |
|---|---|
| `topo-mapper discover` | Walk a live topology, write a snapshot. `--mock DIR` replays captured output instead of SSH. |
| `topo-mapper demo` | `discover` against the bundled mock lab. `--serve` to open the viewer. |
| `topo-mapper export --format {cytoscape,grafana,mermaid,html,simple,json}` | Convert a snapshot. `--out -` for stdout. |
| `topo-mapper serve` | FastAPI backend + Cytoscape.js viewer for a snapshot. |

Key `discover` flags: `--protocol cdp,lldp`, `--enrich`, `--max-devices N`,
`--keep-domain`, `--inventory FILE`.

## Snapshot format (`topology.json`)

```jsonc
{
  "version": 1,
  "generated_at": "2026-09-07T12:00:00+00:00",
  "seeds": ["10.0.0.1"],
  "stats": { "devices": 7, "reachable": 5, "failed": 1, "not_scanned": 1, "links": 7, "endpoints": 1 },
  "devices": [
    { "name": "core1", "label": "core1", "mgmt_ip": "10.0.0.1", "role": "l3-switch",
      "reachable": true, "discovered_via": "seed", "platform": "Cisco IOS Software ...",
      "interfaces": { "GigabitEthernet0/0": { "status": "up", "vlan": "routed" } },
      "errors": [] }
  ],
  "links": [
    { "a_device": "core1", "a_interface": "GigabitEthernet0/0",
      "b_device": "dist1", "b_interface": "GigabitEthernet0/1",
      "protocols": ["cdp", "lldp"], "status": "up" }
  ]
}
```

## Visualization

**Cytoscape.js viewer** — `topo-mapper serve` (or a fully standalone file via
`export --format html --out topo.html`). Nodes coloured by role, unreachable
nodes dashed red, click a node/edge for details, switchable layouts.

**Simple HTML report** — summary stats plus device and link tables, with no
JavaScript or CDN needed. Served at `/simple` by `topo-mapper serve`, or written
to a file with `export --format simple --out report.html`.

**Grafana Node Graph** — `export --format grafana --out nodegraph.json` produces
`{ "nodes": [...], "edges": [...] }` matching the Node Graph panel's default
field mapping. Serve it via the Infinity datasource (or the Node Graph API
datasource) and drop a Node Graph panel on a dashboard in the existing
homelab Grafana.

## Running on a homelab server (Docker Compose)

```bash
cp .env.example .env            # fill in TOPO_USERNAME / TOPO_PASSWORD
cp inventory.example.yaml inventory.yaml   # optional, per-device overrides
docker compose up -d --build
```

This starts two services sharing a `topo-data` volume:

- `topo-mapper-discover` — loops `discover --enrich` on an interval
  (`DISCOVER_INTERVAL_SECONDS` in `docker-compose.yml`, default 15 min) and
  writes `topology.json` into the volume.
- `topo-mapper-viewer` — `topo-mapper serve`, reachable at
  `http://<server>:8000`. It reads the snapshot fresh on every request, so it
  picks up each new discovery run without a restart.

If the lab devices are on a subnet the Docker bridge can't reach, switch
`topo-mapper-discover` to `network_mode: host` in `docker-compose.yml`.

Once a Grafana/Prometheus stack is back on the server, add a Node Graph panel
fed by `topo-mapper export --format grafana` (see Visualization above) instead
of, or alongside, the standalone viewer.

## Mock lab layout

```
demo_lab/
  hosts.yaml                       # mgmt-IP -> host directory, plus seeds
  core1/
    show_version.txt
    show_cdp_neighbors_detail.txt
    show_lldp_neighbors_detail.txt
    show_interfaces_status.txt
  dist1/ ...
```

Point `discover --mock path/to/lab` at your own captures to test parsing against
real gear output offline.

## Tests

```bash
pytest
```

Parser tests run against the mock-lab fixtures; discovery tests run the full BFS
walk through the mock connection backend (no network).

## Project layout

```
topo_mapper/
  cli.py            argparse entry point (discover / demo / export / serve)
  discovery.py      BFS walk, per-device failure handling
  parsers.py        regex parsers for CDP / LLDP / interface state
  normalize.py      hostname + interface canonicalization
  roles.py          capability -> role inference
  models.py         Device / Link / NeighborRecord
  graph.py          NetworkX graph + JSON snapshot
  connections.py    Netmiko backend + file-backed mock lab
  exporters/        cytoscape / grafana / mermaid / standalone html
  web/              FastAPI app + Cytoscape.js single-page viewer
  demo_lab/         bundled captured output for `topo-mapper demo`
```

## Roadmap

- SNMP enrichment (utilization, VLAN membership) via pysnmp
- Persist snapshots to Postgres for topology history / diffing
- NAPALM backend option for multi-vendor normalization
- Concurrent discovery workers

## License

MIT
