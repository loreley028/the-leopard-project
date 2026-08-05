#!/usr/bin/env python3
"""Generate an empty, controlled template for a verified EOD bootstrap file."""
from __future__ import annotations
import argparse
from datetime import date
from pathlib import Path
from leopard_project.security_proxy_eod_bootstrap import write_import_template
from leopard_project.trading_calendar import load_calendar

parser = argparse.ArgumentParser()
parser.add_argument("--as-of", type=date.fromisoformat, required=True)
parser.add_argument("--output", type=Path, default=Path("var/security-proxy-eod-import-template/security_proxy_eod_history_template.csv"))
args = parser.parse_args()
calendar = load_calendar()
if calendar is None: parser.error("controlled calendar unavailable")
days = [day for day in sorted(calendar.trading_dates()) if day <= args.as_of][-20:]
if len(days) != 20: parser.error("calendar does not contain 20 controlled dates")
print(write_import_template(args.output, trading_dates=days))
