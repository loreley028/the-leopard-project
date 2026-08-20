#!/usr/bin/env bash
# Version-controlled host wrapper for the independent Market Core advance.
# Installed by the deployment runbook; never called by the web process.
set -euo pipefail
umask 077

readonly API_CONTAINER="${LEOPARD_API_CONTAINER:-leopard-api}"

docker exec "$API_CONTAINER" \
  python /app/scripts/advance_market_core.py \
  --mode advance --enable-tencent-provider --enable-sina-provider
