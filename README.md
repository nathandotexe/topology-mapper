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
| `topo-mapper serve` | FastAPI backend + Cytoscape.js viewer for a snapshot, or `--db probe.db` for live hop data. Needs `TOPO_WEB_PASSWORD` to listen beyond loopback. |
| `topo-mapper probe` | Trace paths to the targets in `targets.yaml` on a schedule and record hop health. `--once` runs a single round. |
| `topo-mapper probe-snapshot` | Write the latest probe paths as a snapshot file (public IPs masked unless `--no-redact`). |

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

## Hop monitor (no CDP/LLDP needed)

A network made of a modem, a router and a few servers has no CDP/LLDP neighbors
to ask. `topo-mapper probe` instead traces the path to each target on a schedule
(using [`mtr`](https://github.com/traviscross/mtr)), stores per-hop latency and
loss in SQLite, and the viewer draws the paths as a topology that updates live.

```bash
cp targets.example.yaml targets.yaml        # edit: modem address, targets
topo-mapper probe --targets targets.yaml --db probe.db --once   # try it
topo-mapper probe --targets targets.yaml --db probe.db          # run forever
TOPO_WEB_PASSWORD='a-long-random-password' topo-mapper serve --db probe.db
```

Needs `mtr` on the machine (`apt install mtr-tiny`) and permission to open raw
ICMP sockets; the Docker image takes care of both.

**What you get**

- A graph of the hops, merged across targets and coloured by real loss: green
  up, amber loss of 5% or more, red down, grey for hops that never answer.
- Route-change detection per target, kept in history (`/api/changes`).
- Per-hop tables at `/api/paths` and Prometheus metrics at `/metrics`.

| Metric | Meaning |
|---|---|
| `topo_probe_up{target}` | latest trace reached the target |
| `topo_probe_run_ok{target}` | the trace itself ran (0 means `mtr` failed, not the network) |
| `topo_probe_last_run_timestamp_seconds{target}` | for stale-probe alerts |
| `topo_target_rtt_seconds`, `topo_target_loss_ratio` | final hop |
| `topo_path_changes_total{target}` | counter of route changes |
| `topo_hop_rtt_seconds`, `topo_hop_loss_ratio`, `topo_hop_responding` | by `target` and `hop` position |
| `topo_hop_info{target,hop,host,scope}` | which address sits at each position |

Example Prometheus alert rules:

```yaml
- alert: TargetUnreachable
  expr: topo_probe_up == 0
  for: 5m
- alert: ProbeStale
  expr: time() - topo_probe_last_run_timestamp_seconds > 900
- alert: RouteChanged
  expr: increase(topo_path_changes_total[1h]) > 0
- alert: HopLoss
  expr: topo_hop_loss_ratio > 0.05
  for: 10m
```

**Reading loss correctly.** Routers in the middle of a path often rate-limit the
ICMP replies a trace relies on, so a hop showing 60% loss followed by hops with
0% is not a problem. The tool reports *effective* loss: the lowest loss at that
hop or any hop after it. Hops that never answer are shown as unknown, not down.
Route changes ignore a hop that merely stayed silent; swapping one address for
another counts. A hop newly inserted into an otherwise identical path is not
flagged.

**Privacy and security**

- Nothing leaves the machine: hop names are not resolved (`mtr -n`), no
  AS-number or geolocation lookups, no telemetry, and the viewer loads no
  third-party scripts (Cytoscape.js is bundled in `web/static/`, MIT licence).
- Public IP addresses are masked as `pub-xxxxxxxx` (salted HMAC, stable per
  installation) in the viewer, API, `/metrics` and exports. Private, CGNAT and
  mesh-VPN addresses stay visible. Set `TOPO_REDACT_PUBLIC=0` to show real
  addresses. Logs never contain hop addresses.
- The viewer binds to loopback by default and refuses to listen anywhere else
  without `TOPO_WEB_PASSWORD` (12+ characters). It uses HTTP Basic auth with
  constant-time comparison, locks a client out for 5 minutes after 5 failed
  attempts, sends a strict Content-Security-Policy and other security headers,
  and has the API docs disabled. Only `/healthz` is open. Basic auth is not
  encrypted, so reach the viewer over WireGuard/NetBird, an SSH tunnel, or a
  TLS reverse proxy, and never expose it to the internet.
- Targets are validated (an IP or hostname that cannot start with `-`), the probe
  is started with an argument list rather than a shell, and its output is parsed
  defensively.
- `probe.db` is created with mode 0600 and pruned after 14 days
  (`--retention-days`). `targets.yaml`, `.env` and `*.db` are git-ignored: this
  repository is public, so keep real addresses out of it.
- In Docker the containers run as a non-root user with a read-only filesystem and
  all capabilities dropped. Only the probe gets `NET_RAW`. No Docker socket is
  mounted and the viewer is published on `127.0.0.1` only.

## Running on a homelab server (Docker Compose)

```bash
cp targets.example.yaml targets.yaml
cp .env.example .env            # set TOPO_WEB_PASSWORD (12+ characters)
docker compose up -d --build
```

This starts two services sharing a `topo-data` volume:

- `probe` traces every target in `targets.yaml` on its own interval and records
  the result.
- `viewer` serves the dashboard, API and `/metrics` at `http://127.0.0.1:8000`.
  From another machine use an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 server`) or
  your VPN. To let a Prometheus container scrape `http://viewer:8000/metrics`,
  join it to Prometheus's network (see the comments in `docker-compose.yml`) and
  give Prometheus the same username and password.

Because the probe runs in a container, hop 1 is normally the Docker bridge on
the server, followed by your modem or router.

For managed Cisco gear, `docker compose --profile cdp up -d --build` also starts
the original CDP/LLDP flow: `discover` loops `discover --enrich` every
`DISCOVER_INTERVAL_SECONDS` (default 15 min) and `viewer-cdp` serves the result
at `http://127.0.0.1:8001`. If the lab devices are on a subnet the Docker bridge
can't reach, switch `discover` to `network_mode: host`.

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
  cli.py            argparse entry point (discover / demo / export / serve / probe)
  discovery.py      BFS walk, per-device failure handling
  parsers.py        regex parsers for CDP / LLDP / interface state
  normalize.py      hostname + interface canonicalization
  roles.py          capability -> role inference
  models.py         Device / Link / NeighborRecord
  graph.py          NetworkX graph + JSON snapshot
  connections.py    Netmiko backend + file-backed mock lab
  exporters/        cytoscape / grafana / mermaid / standalone html
  probes/           hop monitor: targets, mtr runner, SQLite history, metrics, masking
  web/              FastAPI app (auth, headers) + bundled Cytoscape.js viewer
  demo_lab/         bundled captured output for `topo-mapper demo`
```

## Roadmap

- SNMP enrichment (utilization, VLAN membership) via pysnmp
- Persist snapshots to Postgres for topology history / diffing
- NAPALM backend option for multi-vendor normalization
- Concurrent discovery workers
- Hop monitor: latency/loss history charts in the viewer, merging CDP/LLDP and probed paths in one graph

## License

MIT
