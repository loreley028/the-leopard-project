#!/usr/bin/env python3
"""Import a manually verified, unadjusted security-proxy EOD history file."""
from __future__ import annotations
import argparse
from datetime import date
from pathlib import Path
from leopard_project.security_proxy_eod import SecurityProxyEodFileStore
from leopard_project.security_proxy_eod_bootstrap import import_bootstrap_rows, load_bootstrap_rows

parser = argparse.ArgumentParser()
parser.add_argument("--input-file", required=True, type=Path)
parser.add_argument("--output-root", default=Path("var/security-proxy-eod"), type=Path)
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--allow-research-overwrite", action="store_true")
parser.add_argument("--today", type=date.fromisoformat, help="controlled test date only")
args = parser.parse_args()
rows = load_bootstrap_rows(args.input_file, today=args.today)
paths = import_bootstrap_rows(rows, store=SecurityProxyEodFileStore(args.output_root), dry_run=args.dry_run, allow_research_overwrite=args.allow_research_overwrite)
print({"rows": len(rows), "days": len(paths), "dry_run": args.dry_run, "database_written": False, "provider_called": False})
