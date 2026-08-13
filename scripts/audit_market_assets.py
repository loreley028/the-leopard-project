"""Read-only inventory for existing Market Core assets.

The audit intentionally treats database files as evidence, not import input.
It classifies only provenance already recorded in each table and never opens a
network connection or writes to any database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Iterable


DATASETS = {
    "live_market_anchor_daily": ("symbol", "trading_date", ("source",)),
    "security_proxy_daily": ("symbol", "trading_date", ("source",)),
    "sector_daily_bars": ("sector_key", "trade_date", ("data_source", "provider_role")),
}


def classify(table: str, provenance: set[str]) -> tuple[str, str]:
    values = {item.lower() for item in provenance if item}
    if any("fixture" in item or "demo" in item for item in values):
        return "UNUSABLE", "fixture or demo provenance cannot be user market history"
    if table in {"live_market_anchor_daily", "security_proxy_daily"} and values and values <= {"tencent_standard_security_quote", "sina_public_daily_http"}:
        return "CURRENT_OBJECTIVE", "symbol/date/provider are explicit completed-market records with source provenance"
    if table == "sector_daily_bars" and values and all(item.startswith("ths_public_validation") for item in values):
        return "LEGACY_HISTORICAL", "diagnostic THS validation bars; not Shanghai or security-level Market Core history"
    return "AUDIT_ONLY", "provenance requires an explicit product decision before use"


def _database_paths(inputs: Iterable[str]) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for raw in inputs:
        item = Path(raw)
        if item.is_file():
            paths.add(item)
        elif item.is_dir():
            paths.update(path for path in item.rglob("*") if path.is_file() and path.suffix in {".sqlite", ".sqlite3", ".db"})
    return tuple(sorted(paths))


def audit_database(path: Path) -> list[dict]:
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return [{"database": str(path), "classification": "UNUSABLE", "reason": f"cannot open read-only: {type(exc).__name__}"}]
    try:
        tables = {item[0] for item in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        results: list[dict] = []
        for table, (symbol, day, provenance_columns) in DATASETS.items():
            if table not in tables:
                continue
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            row_count, first_date, last_date, distinct_days, unique_rows = conn.execute(
                f"SELECT COUNT(*), MIN({day}), MAX({day}), COUNT(DISTINCT {day}), "
                f"COUNT(DISTINCT {symbol} || char(31) || {day}) FROM {table}"
            ).fetchone()
            provenance: set[str] = set()
            provenance_summary: dict[str, list[dict]] = {}
            for column in provenance_columns:
                if column not in columns:
                    continue
                entries = [
                    {"value": value or "", "rows": rows}
                    for value, rows in conn.execute(
                        f"SELECT COALESCE({column}, ''), COUNT(*) FROM {table} GROUP BY {column} ORDER BY COUNT(*) DESC"
                    )
                ]
                provenance_summary[column] = entries
                provenance.update(item["value"] for item in entries)
            classification, reason = classify(table, provenance)
            symbols = [
                {"symbol": value, "rows": rows, "first_date": first, "last_date": last, "distinct_trading_days": days}
                for value, rows, first, last, days in conn.execute(
                    f"SELECT {symbol}, COUNT(*), MIN({day}), MAX({day}), COUNT(DISTINCT {day}) "
                    f"FROM {table} GROUP BY {symbol} ORDER BY {symbol}"
                )
            ]
            results.append({
                "database": str(path), "dataset": table, "provenance": provenance_summary,
                "first_date": first_date, "last_date": last_date, "distinct_trading_days": distinct_days,
                "row_count": row_count, "duplicate_count": row_count - unique_rows, "symbols": symbols,
                "classification": classification, "usable_for_current_product": classification == "CURRENT_OBJECTIVE", "reason": reason,
            })
        return results
    finally:
        conn.close()


def markdown(rows: list[dict]) -> str:
    lines = ["# Market Asset Inventory", "", "Read-only evidence inventory.  No row is imported by this command.", ""]
    for item in rows:
        if "dataset" not in item:
            lines.extend([f"## {item['database']}", "", f"- {item['classification']}: {item['reason']}", ""])
            continue
        lines.extend([
            f"## {item['dataset']}", "", f"- Database: `{item['database']}`", f"- Classification: **{item['classification']}**", f"- Usable for current product: `{item['usable_for_current_product']}`", f"- Date coverage: {item['first_date'] or '—'} to {item['last_date'] or '—'} ({item['distinct_trading_days']} distinct trading days)", f"- Rows / duplicates: {item['row_count']} / {item['duplicate_count']}", f"- Reason: {item['reason']}", "",
            "| Symbol | Rows | First | Last | Trading days |", "|---|---:|---|---|---:|",
            *[f"| {symbol['symbol']} | {symbol['rows']} | {symbol['first_date'] or '—'} | {symbol['last_date'] or '—'} | {symbol['distinct_trading_days']} |" for symbol in item["symbols"]], "",
        ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="SQLite files or directories to inspect read-only")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    rows = [item for path in _database_paths(args.paths) for item in audit_database(path)]
    payload = json.dumps(rows, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.write_text(payload + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.write_text(markdown(rows) + "\n", encoding="utf-8")
    if not args.json_output and not args.markdown_output:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
