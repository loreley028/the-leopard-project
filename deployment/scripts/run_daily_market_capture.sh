#!/usr/bin/env bash
# Version-controlled host wrapper for the intentionally explicit daily captures.
# Installed by the deployment runbook; never called by the web process.
set -euo pipefail
umask 077

readonly API_CONTAINER="${LEOPARD_API_CONTAINER:-leopard-api}"

docker exec "$API_CONTAINER" \
  python /app/scripts/capture_live_market_anchor_daily.py --enable-provider
docker exec "$API_CONTAINER" \
  python /app/scripts/capture_security_proxy_daily.py --enable-provider
