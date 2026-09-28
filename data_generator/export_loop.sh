#!/bin/sh
# Simulates source systems dropping incremental export files on a fixed cadence.
set -eu
INTERVAL="${EXPORT_INTERVAL_SECONDS:-900}"
while true; do
  python generate_data.py --landing-dir "${LANDING_DIR:-/data/landing}" || echo "export failed, retrying next cycle" >&2
  sleep "$INTERVAL"
done
