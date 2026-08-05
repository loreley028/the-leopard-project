#!/usr/bin/env python3
"""Read-only metrics preview from accumulated local security EOD files."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from leopard_project.security_proxy_eod import SecurityProxyEodFileStore, candidate_symbols, metrics_for
parser = argparse.ArgumentParser(); parser.add_argument("--input-root", type=Path, default=Path("var/security-proxy-eod")); args = parser.parse_args()
records = SecurityProxyEodFileStore(args.input_root).records()
metrics = [metrics_for(records, symbol) for symbol in candidate_symbols()]
print(json.dumps([item.__dict__ | {key: str(value) if value is not None else None for key, value in item.__dict__.items() if key in {"latest_close", "latest_amount_yuan", "rolling_20d_low", "rebound_pct"}} for item in metrics], ensure_ascii=False, default=str))
