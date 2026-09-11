#!/bin/sh
# Re-runs discovery on an interval, writing into the shared /data volume
# that topo-mapper-viewer serves from.
set -eu

INTERVAL="${DISCOVER_INTERVAL_SECONDS:-900}"
ARGS="discover --enrich --out /data/topology.json"

if [ -f /app/inventory.yaml ]; then
  ARGS="$ARGS --inventory /app/inventory.yaml"
fi

while true; do
  echo "[discover-loop] $(date -Iseconds) running: topo-mapper $ARGS"
  topo-mapper $ARGS || echo "[discover-loop] discover failed, will retry next interval"
  sleep "$INTERVAL"
done
