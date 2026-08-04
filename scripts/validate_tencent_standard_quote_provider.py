#!/usr/bin/env python3
"""One-shot, default-disabled diagnostic probe for Tencent standard securities."""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider, load_tencent_quote_config


def write_reports(batch: object, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = batch  # keeps the CLI output intentionally limited to parsed fields.
    rows = [{
        "requested_symbol": quote.requested_symbol, "name": quote.name, "symbol": quote.symbol,
        "current": str(quote.current), "pre_close": str(quote.pre_close), "change": str(quote.change),
        "pct_change": str(quote.pct_change), "quote_datetime": quote.quote_datetime.isoformat(),
        "field_count": quote.response_field_count, "payload_sha256": quote.payload_sha256,
    } for quote in result.quotes]
    document = {"request_count": result.request_count, "quote_count": len(rows), "failures": {key: value.value for key, value in result.failures.items()}, "quotes": rows}
    stem = f"tencent-standard-security-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    json_path, csv_path, markdown_path = (output_dir / f"{stem}.{suffix}" for suffix in ("json", "csv", "md"))
    json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["requested_symbol", "name", "symbol", "current", "pre_close", "change", "pct_change", "quote_datetime", "field_count", "payload_sha256"])
        writer.writeheader(); writer.writerows(rows)
    markdown_path.write_text("# Tencent standard-security diagnostic\n\n" + f"- Request count: {result.request_count}\n- Parsed quotes: {len(rows)}\n- Failures: {len(result.failures)}\n- Endpoint: configured template (symbols omitted)\n", encoding="utf-8")
    return json_path, csv_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enable-network", action="store_true", help="required: the checked-in Provider remains disabled")
    parser.add_argument("--output-dir", type=Path, default=Path("var/provider-research/tencent-standard-security"))
    parser.add_argument("symbols", nargs="*")
    args = parser.parse_args()
    if not args.enable_network:
        parser.error("--enable-network is required because this diagnostic Provider is disabled by default")
    config = load_tencent_quote_config()
    provider = TencentStandardSecurityQuoteProvider(config=config)
    symbols = args.symbols or config["diagnostic_default_symbols"]
    batch = provider.fetch_batch(symbols, allow_network=True)
    paths = write_reports(batch, args.output_dir)
    print(json.dumps({"request_count": batch.request_count, "parsed_quotes": len(batch.quotes), "failures": {key: value.value for key, value in batch.failures.items()}, "reports": [str(path) for path in paths]}, ensure_ascii=False))
    return 0 if len(batch.quotes) >= 4 else 2


if __name__ == "__main__":
    raise SystemExit(main())
