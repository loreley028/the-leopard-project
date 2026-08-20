#!/usr/bin/env bash
# Host-only reconciliation: reads coverage first, then repairs exact-date gaps.
set -euo pipefail
umask 077

readonly API_CONTAINER="${LEOPARD_API_CONTAINER:-leopard-api}"

docker exec "$API_CONTAINER" \
  python /app/scripts/advance_market_core.py \
  --mode reconcile --enable-sina-provider
