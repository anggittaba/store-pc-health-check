#!/usr/bin/env bash
# Build a fresh demo database ending 2026-10-11, serve it, capture the README screenshots, stop the server.
set -euo pipefail
cd "$(dirname "$0")/.."
export PCHEALTH_LLM=off PCHEALTH_VAR=var/shots
python -m pchealth backfill --end 2026-10-11 >/dev/null
python -m pchealth serve --port 8812 & SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT
for _ in $(seq 50); do curl -fs http://127.0.0.1:8812/healthz >/dev/null && break; sleep 0.2; done
python scripts/capture_screenshots.py --base http://127.0.0.1:8812 --store ST-458 "$@"
