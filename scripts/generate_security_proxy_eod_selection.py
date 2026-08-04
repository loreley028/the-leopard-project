#!/usr/bin/env python3
"""Generate an explicit, read-only security-proxy EOD selection snapshot.

Without ``--input`` this runs a deterministic synthetic demonstration only.  It
never calls a Provider, opens a database, starts a Scheduler, or changes Viewer
behaviour.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from leopard_project.security_proxy_eod_selection import (
    SecurityProxyDailySelection, SecurityProxyEodBar, SecurityProxyEtfAum,
    SecurityProxyEodSelectionService, selection_to_dict,
)


def _dates(end: date, count: int = 20) -> list[date]:
    values: list[date] = []
    current = end
    while len(values) < count:
        if current.weekday() < 5: values.append(current)
        current -= timedelta(days=1)
    return list(reversed(values))


def demo_input() -> tuple[date, date, tuple[str, ...], dict[str, list[SecurityProxyEodBar]], dict[str, SecurityProxyEtfAum]]:
    data_as_of = date(2026, 8, 3)
    symbols = {
        "sz300308": (100, 20, 400, 300), "sz300502": (90, 22, 350, 420), "sz300394": (80, 24, 300, 360),
        "sh603259": (70, 20, 500, 250), "sz300760": (75, 18, 600, 220), "sh600276": (65, 30, 450, 800), "sh688180": (50, 15, 200, 180),
        "sh688981": (60, 25, 900, 500), "sz002371": (55, 35, 650, 650), "sh603501": (50, 40, 550, 900), "sz300474": (500, 10, 9999, 9999),
    }
    bars: dict[str, list[SecurityProxyEodBar]] = {}
    for symbol, (close, low, cap, amount) in symbols.items():
        rows: list[SecurityProxyEodBar] = []
        for index, day in enumerate(_dates(data_as_of)):
            rows.append(SecurityProxyEodBar(symbol=symbol, trade_date=day, close=Decimal(str(close - 3 + index / 10)), low=Decimal(str(low if index == 0 else close - 2)), amount=Decimal(str(amount + index)), total_market_cap=Decimal(str(cap)), eod_status="complete_eod"))
        bars[symbol] = rows
    aums = {
        "sh515880": SecurityProxyEtfAum("sh515880", Decimal("1200000000"), date(2026, 7, 31), "synthetic_fixture", "partial"),
        "sz159992": SecurityProxyEtfAum("sz159992", Decimal("900000000"), date(2026, 7, 31), "synthetic_fixture", "direct_or_close"),
        "sz159995": SecurityProxyEtfAum("sz159995", Decimal("800000000"), date(2026, 7, 31), "synthetic_fixture", "partial"),
    }
    return data_as_of, data_as_of, ("cpo", "innovative_drug_medicine", "semiconductor"), bars, aums


def parse_input(path: Path) -> tuple[date, date, tuple[str, ...], dict[str, list[SecurityProxyEodBar]], dict[str, SecurityProxyEtfAum]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    selection_date, data_as_of = date.fromisoformat(document["selection_date"]), date.fromisoformat(document["data_as_of"])
    bars: dict[str, list[SecurityProxyEodBar]] = {}
    for item in document["eod_bars"]:
        bars.setdefault(item["symbol"], []).append(SecurityProxyEodBar(item["symbol"], date.fromisoformat(item["trade_date"]), *(Decimal(str(item[field])) if item.get(field) not in (None, "") else None for field in ("close", "low", "amount", "total_market_cap")), item.get("eod_status", "complete_eod")))
    aums = {item["symbol"]: SecurityProxyEtfAum(item["symbol"], Decimal(str(item["aum"])) if item.get("aum") not in (None, "") else None, date.fromisoformat(item["aum_as_of"]) if item.get("aum_as_of") else None, item["aum_source"], item["coverage_type"]) for item in document.get("etf_aums", [])}
    return selection_date, data_as_of, tuple(document["market_path_keys"]), bars, aums


def _csv_rows(selection: SecurityProxyDailySelection) -> list[dict[str, Any]]:
    instruments = ([selection.selected_etf] if selection.selected_etf else []) + list(selection.selected_leaders)
    return [{"market_path_key": selection.market_path_key, "display_name": selection.display_name, "selection_date": selection.selection_date.isoformat(), "data_as_of": selection.data_as_of.isoformat(), "symbol": item.symbol, "security_name": item.security_name, "proxy_role": item.proxy_role, "selection_source": item.selection_source, "selection_reasons": ";".join(item.selection_reasons), "display_reason": item.display_reason, "metrics_as_of": item.metrics_as_of.isoformat() if item.metrics_as_of else None, "close": str(item.metrics.close) if item.metrics.close is not None else None, "rolling_low": str(item.metrics.rolling_low) if item.metrics.rolling_low is not None else None, "rebound_pct": str(item.metrics.rebound_pct) if item.metrics.rebound_pct is not None else None, "amount": str(item.metrics.amount) if item.metrics.amount is not None else None, "total_market_cap": str(item.metrics.total_market_cap) if item.metrics.total_market_cap is not None else None, "aum": str(item.metrics.aum) if item.metrics.aum is not None else None, "aum_as_of": item.metrics.aum_as_of.isoformat() if item.metrics.aum_as_of else None} for item in instruments]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="research-only security EOD input JSON; no Provider fetch occurs")
    parser.add_argument("--output-dir", type=Path, default=Path("var/provider-research/security-proxy-eod-selection"))
    args = parser.parse_args()
    selection_date, data_as_of, paths, bars, aums = parse_input(args.input) if args.input else demo_input()
    service = SecurityProxyEodSelectionService(now=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc))
    selected, comparisons = zip(*(service.select(path, selection_date=selection_date, data_as_of=data_as_of, eod_bars=bars, etf_aums=aums) for path in paths))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = {"input_mode": "research_only_input" if args.input else "synthetic_demo", "selections": [selection_to_dict(item) for item in selected]}
    comparison = {"comparisons": [selection_to_dict(item) for item in comparisons]}
    summary = {"selection_count": len(selected), "selected_etfs": sum(item.selected_etf is not None for item in selected), "selected_leaders": sum(len(item.selected_leaders) for item in selected), "scheduler_started": False, "viewer_changed": False, "database_written": False, "provider_called": False}
    (args.output_dir / "selection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "comparison-with-previous.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = [row for item in selected for row in _csv_rows(item)]
    with (args.output_dir / "selection.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["market_path_key"]); writer.writeheader(); writer.writerows(rows)
    lines = ["# Security proxy EOD selection", "", "This is a read-only, research-only selection snapshot. It neither calls a Provider nor changes the Scheduler, Viewer, or formal database.", ""]
    for item in selected:
        lines.append(f"## {item.display_name} ({item.market_path_key})")
        lines.append("")
        for row in _csv_rows(item): lines.append(f"- {row['symbol']} {row['security_name']}: {row['selection_source']} / {row['selection_reasons']}")
        lines.append("")
    (args.output_dir / "selection.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({**summary, "output_dir": str(args.output_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
