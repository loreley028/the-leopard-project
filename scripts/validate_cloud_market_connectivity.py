#!/usr/bin/env python3
"""One-shot cloud-only market connectivity probe. Never starts app services or writes project data."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leopard_project.cloud_connectivity import Candidate, active_market_paths, run_probe, write_reports
from leopard_project.models import Market
from leopard_project.providers import ProviderError, ProviderErrorCategory, ThsExactSpotProvider
from leopard_project.providers.eastmoney_spot import EastmoneyBoardSpotProvider


def error_class(error: ProviderError) -> str:
    return {ProviderErrorCategory.AUTHENTICATION: "http_401", ProviderErrorCategory.AUTHORIZATION: "http_403", ProviderErrorCategory.RATE_LIMIT: "http_429", ProviderErrorCategory.INVALID_SYMBOL: "http_404", ProviderErrorCategory.TIMEOUT: "timeout", ProviderErrorCategory.MALFORMED_RESPONSE: "parse_error", ProviderErrorCategory.NO_DATA: "missing_current"}.get(error.category, "remote_disconnected" if error.category == ProviderErrorCategory.NETWORK else "parse_error")


class CloudProbe:
    def __init__(self, timeout: float) -> None:
        self.ths = ThsExactSpotProvider(timeout=timeout)
        self.eastmoney = EastmoneyBoardSpotProvider(timeout=timeout)

    def __call__(self, candidate: Candidate, include_history: bool) -> dict:
        started = datetime.now(timezone.utc)
        before = self.ths.request_count + self.eastmoney.request_count
        try:
            if candidate.provider == "ths_exact_spot":
                payload = self.ths._detail(candidate.symbol)
                quote = self.ths._parse_detail(payload, name=candidate.provider_name, symbol=candidate.symbol)
                closes = self.ths._history.historical_daily_bars(candidate.symbol, (started - timedelta(days=30)).date(), (started - timedelta(days=1)).date(), Market.CN_A) if include_history else ()
                count = len(closes[-4:])
                return {"spot_status": "success", "parser_status": "success", "current_available": bool(quote["current"]), "pre_close_available": bool(quote["pre_close"]), "as_of_available": True, "spot_latency_ms": 0, "history_status": "success" if not include_history or count == 4 else "insufficient_history", "previous_close_count": count, "request_count": self.ths.request_count + self.eastmoney.request_count - before}
            if candidate.provider == "eastmoney_board_spot":
                # The production adapter's exact-symbol resolver is deliberately reused.
                self.eastmoney._load()
                row = next((row for group in self.eastmoney._records_by_kind.values() for row in group.values() if str(row.get("f12")) == candidate.symbol), None)
                if row is None: raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "exact Eastmoney board unavailable", retryable=False)
                current, previous = self.eastmoney._decimal(row, "f2"), self.eastmoney._decimal(row, "f18")
                if current in (None, 0) or previous in (None, 0): raise ProviderError(ProviderErrorCategory.NO_DATA, "Eastmoney required quote fields unavailable", retryable=True)
                closes = self.eastmoney._native_history(candidate.symbol, (started - timedelta(days=1)).date()) if include_history else ()
                return {"spot_status": "success", "parser_status": "success", "current_available": True, "pre_close_available": True, "as_of_available": True, "spot_latency_ms": 0, "history_status": "success" if not include_history or len(closes) == 4 else "insufficient_history", "previous_close_count": len(closes), "request_count": self.ths.request_count + self.eastmoney.request_count - before}
            return {"spot_status": "semantic_unverified", "history_status": "not_attempted", "error_class": "semantic_unverified", "error_summary": "no diagnostic adapter", "request_count": 0}
        except ProviderError as exc:
            return {"spot_status": "failed", "history_status": "not_attempted", "error_class": error_class(exc), "error_summary": str(exc)[:160], "request_count": self.ths.request_count + self.eastmoney.request_count - before}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("var/provider-validation"))
    parser.add_argument("--max-concurrency", type=int, default=1, choices=(1, 2))
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--environment-label", default="cloud")
    parser.add_argument("--spot-only", action="store_true")
    parser.add_argument("--include-history", action="store_true")
    args = parser.parse_args()
    result = run_probe(active_market_paths(), CloudProbe(args.timeout), include_history=args.include_history and not args.spot_only)
    stem = f"market-connectivity-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{args.environment_label}"
    paths = write_reports(result, args.output_dir, stem)
    print(result["summary"]); print("\n".join(str(path) for path in paths))
    raise SystemExit(0 if result["summary"]["spot_operational_count"] >= 55 else 2)


if __name__ == "__main__": main()
