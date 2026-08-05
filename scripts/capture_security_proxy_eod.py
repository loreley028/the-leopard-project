#!/usr/bin/env python3
"""Explicit, default-disabled file capture of Tencent standard-quote EOD records."""
from __future__ import annotations
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_eod import SecurityProxyEodCaptureService, SecurityProxyEodError, SecurityProxyEodFileStore, atomic_write_text

parser = argparse.ArgumentParser()
parser.add_argument("--trading-date", type=date.fromisoformat, required=True)
parser.add_argument("--output-root", type=Path, default=Path("var/security-proxy-eod"))
parser.add_argument("--enable-provider", action="store_true")
parser.add_argument("--allow-research-overwrite", action="store_true")
parser.add_argument("--market-path", action="append", default=[], help="approved path key; repeat to limit a research capture")
args = parser.parse_args()
if not args.enable_provider: parser.error("--enable-provider is required")
try:
    result = SecurityProxyEodCaptureService(
        TencentStandardSecurityQuoteProvider(), SecurityProxyEodFileStore(args.output_root), now=lambda: datetime.now().astimezone(),
    ).capture(
        args.trading_date,
        enable_provider=True,
        allow_research_overwrite=args.allow_research_overwrite,
        market_path_keys=args.market_path or None,
    )
except SecurityProxyEodError as exc:
    parser.exit(2, f"{exc.code}: {exc}\n")
summary = {"trading_date": args.trading_date.isoformat(), "records": len(result.records), "failures": result.failures, "request_count": result.request_count, "batch_count": result.batch_count, "capture_status": "complete" if not result.failures else "partial", "market_paths": args.market_path, "database_written": False, "scheduler_started": False, "provider": "tencent_standard_quote"}
atomic_write_text(args.output_root / "capture-summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
atomic_write_text(args.output_root / "capture-summary.md", f"# Security proxy EOD capture\n\n- Trading date: {args.trading_date}\n- Records: {len(result.records)}\n- Status: {summary['capture_status']}\n- Scheduler/database: not used\n")
print(json.dumps(summary, ensure_ascii=False))
