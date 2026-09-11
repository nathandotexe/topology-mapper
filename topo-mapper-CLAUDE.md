# Topo Mapper — Network Topology Auto-Discovery & Visualization

## Overview
A Python tool that discovers live network topology via CDP/LLDP neighbor data, builds a graph model, and renders it visually — either as a Grafana Node Graph panel (reusing the existing homelab Grafana/Prometheus stack) or a small standalone web view. Built as a network engineering portfolio project to demonstrate automated network discovery and observability skills.

## Goals
- Automatically discover devices and links in a lab topology rather than hand-documenting them
- Represent the topology as a proper graph (nodes = devices, edges = links) instead of a static diagram
- Annotate the graph with live status (interface up/down, VLAN, bandwidth) where possible
- Visualize it in a way that's demoable — ideally reusing infrastructure already in place (Grafana/Prometheus, Postgres)

## Architecture
1. **Seed + inventory** — start from one or more seed devices (IP/host + credentials via env vars).
2. **Discovery engine** — Netmiko (or NAPALM) SSHes in, runs `show cdp neighbors detail` / `show lldp neighbors detail`, and parses neighbor device-id, local/remote interface, and platform.
3. **Recursive walk** — treat newly discovered neighbors as new seeds (BFS) until no new devices are found, building the full topology instead of just one hop.
4. **Graph model** — NetworkX graph: nodes = devices (attributes: platform, role), edges = links (attributes: local/remote interface).
5. **Enrichment (stretch)** — SNMP (pysnmp) or additional `show` commands pull interface operational status, VLAN membership, or utilization, attached as node/edge attributes.
6. **Storage** — export graph snapshots as JSON, optionally persist into Postgres (reusing the schema/instance from the traceroute visualizer or homelab stack) for history over time.
7. **Visualization** — two options:
   - Export nodes/edges into Grafana's Node Graph panel format (consistent with the traceroute visualizer's Grafana approach)
   - A small FastAPI backend + Cytoscape.js or vis.js frontend for an interactive, clickable topology map

## Tech stack
Python 3.11+, Netmiko, NetworkX, PyYAML, python-dotenv. Optional: pysnmp for enrichment, FastAPI + Cytoscape.js for a custom frontend, Postgres for history.

## Important constraint: lab environment
Same issue as any Netmiko-based tool: Packet Tracer devices aren't reachable via real SSH from outside Packet Tracer. Use GNS3/EVE-NG with IOSv/IOSv-L2 images (lets you reuse the DC1-BRANCH or Final Lab Assessment topology), a couple of physical devices, or a DevNet sandbox/CML lab.

## Out of scope (v1)
- Multi-site/multi-vendor discovery (single lab, Cisco CDP/LLDP only for now)
- Real-time streaming updates (a periodic re-scan is enough for a portfolio demo)
- Full NMS feature parity (this is a discovery + visualization tool, not a monitoring platform)

## Suggested build order
1. CDP/LLDP parsing against a single seed device
2. Recursive discovery across the full lab topology
3. Build the NetworkX graph, export to JSON
4. Render via Grafana Node Graph (fastest path, reuses existing infra) or a minimal FastAPI + Cytoscape.js page
5. Add interface up/down enrichment
6. README with a screenshot/GIF of the discovered topology map
