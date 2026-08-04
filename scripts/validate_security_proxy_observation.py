#!/usr/bin/env python3
"""Explicit, one-batch diagnostic for approved Tencent security proxies."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_observation import FIXED_DISCLOSURE, SecurityProxyObservationService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-provider", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("var/provider-research/security-proxy-observation"))
    parser.add_argument("paths", nargs="*", default=["cpo", "rare_earth", "liquid_cooling"])
    args = parser.parse_args()
    if not args.enable_provider: parser.error("--enable-provider is required; the registry is default-disabled")
    observations = SecurityProxyObservationService(provider=TencentStandardSecurityQuoteProvider()).observe(args.paths, enable_provider=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"market_path_key": row.market_path_key, "display_name": row.display_name, "status": row.status, "symbol": item.symbol, "security_name": item.security_name, "proxy_role": item.proxy_role, "coverage_type": item.coverage_type, "current": str(item.current) if item.current is not None else None, "pre_close": str(item.pre_close) if item.pre_close is not None else None, "change": str(item.change) if item.change is not None else None, "pct_change": str(item.pct_change) if item.pct_change is not None else None, "quote_datetime": item.quote_datetime.isoformat() if item.quote_datetime else None, "quote_status": item.quote_status, "error_class": item.error_class, "disclosure": row.disclosure} for row in observations for item in row.instruments]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path, csv_path, markdown_path = (args.output_dir / f"security-proxy-observation-{stamp}.{suffix}" for suffix in ("json", "csv", "md"))
    json_path.write_text(json.dumps({"disclosure": FIXED_DISCLOSURE, "observations": [{**asdict(item), "quote_datetime": item.quote_datetime.isoformat() if item.quote_datetime else None, "fetched_at": item.fetched_at.isoformat(), "instruments": [{**asdict(quote), "current": str(quote.current) if quote.current is not None else None, "pre_close": str(quote.pre_close) if quote.pre_close is not None else None, "change": str(quote.change) if quote.change is not None else None, "pct_change": str(quote.pct_change) if quote.pct_change is not None else None, "quote_datetime": quote.quote_datetime.isoformat() if quote.quote_datetime else None} for quote in item.instruments]} for item in observations]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["market_path_key", "display_name", "status", "symbol", "security_name", "proxy_role", "coverage_type", "current", "pre_close", "change", "pct_change", "quote_datetime", "quote_status", "error_class", "disclosure"]); writer.writeheader(); writer.writerows(rows)
    markdown_path.write_text(f"# Security proxy observation\n\n{FIXED_DISCLOSURE}\n\n- Paths: {len(observations)}\n- Instruments: {len(rows)}\n- Aggregate returns: not calculated\n", encoding="utf-8")
    print(json.dumps({"paths": len(observations), "instruments": len(rows), "outputs": [str(json_path), str(csv_path), str(markdown_path)]}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
