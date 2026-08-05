from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from leopard_project.providers.tencent_standard_quote import StandardSecurityQuote, TencentQuoteBatch, TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_eod import (
    SHANGHAI, SecurityProxyEodCaptureService, SecurityProxyEodError, SecurityProxyEodFileStore, _shanghai,
    SecurityProxyEodRecord, atomic_write_text, candidate_symbols, metrics_for, record_from_quote,
    validate_capture_date,
)


NOW = datetime.fromisoformat("2026-08-04T16:20:00+08:00")
CAPTURE_NOW = datetime.fromisoformat("2026-08-05T15:15:00+08:00")


def raw(symbol: str, *, timestamp: str = "20260804161440", fields: int = 88, amount: str = "10000") -> bytes:
    values = [""] * fields
    values[1], values[2], values[3], values[4], values[5] = ("示例", symbol[2:], "10.02", "10", "10")
    values[30], values[31], values[32], values[33], values[34], values[35] = timestamp, "0.02", "0.2", "11", "9", f"10.02/100/{amount}"
    values[78] = "999"
    return f'v_{symbol}="{"~".join(values)}";'.encode("gbk")


def quote(symbol: str = "sh510300", **kwargs: object) -> StandardSecurityQuote:
    return TencentStandardSecurityQuoteProvider(transport=lambda _u, _t: raw(symbol, **kwargs), now=lambda: NOW).fetch_batch([symbol], allow_network=True).quotes[0]


def record(symbol: str, day: date, low: str = "8", close: str = "10", amount: str = "100") -> SecurityProxyEodRecord:
    return SecurityProxyEodRecord(symbol, "示例", day, Decimal("9"), Decimal("11"), Decimal(low), Decimal(close), Decimal(amount), datetime(day.year, day.month, day.day, 16, tzinfo=SHANGHAI), NOW)


def complete_quote(symbol: str) -> StandardSecurityQuote:
    return StandardSecurityQuote(symbol, symbol, symbol[2:], Decimal("10"), Decimal("9"), datetime(2026, 8, 5, 15, 15, tzinfo=SHANGHAI), Decimal("1"), Decimal("11.11"), 88, "hash", Decimal("9.5"), Decimal("10.5"), Decimal("9.4"), Decimal("100"))


class FakeProvider:
    max_batch_size = 20

    def __init__(self, *, failures: dict[str, str] | None = None, empty: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.failures, self.empty = failures or {}, empty

    def fetch_batch(self, symbols, *, allow_network: bool = False) -> TencentQuoteBatch:
        selected = tuple(symbols)
        self.calls.append(selected)
        quotes = () if self.empty else tuple(complete_quote(symbol) for symbol in selected if symbol not in self.failures)
        from leopard_project.providers.tencent_standard_quote import TencentQuoteErrorCode
        return TencentQuoteBatch(quotes, {symbol: TencentQuoteErrorCode.MALFORMED_RECORD for symbol in selected if symbol in self.failures}, 1)


def error_code(callable_) -> str:
    with pytest.raises(SecurityProxyEodError) as exc:
        callable_()
    return exc.value.code


def test_extended_quote_fields_parse_and_p78_is_ignored() -> None:
    item = quote()
    assert item.open == Decimal("10") and item.high == Decimal("11") and item.low == Decimal("9")
    assert item.amount_yuan == Decimal("10000") and not item.eod_extension_errors


def test_invalid_eod_extension_does_not_remove_base_quote() -> None:
    item = quote(amount="bad")
    assert item.current == Decimal("10.02") and item.amount_yuan is None and "amount_yuan" in item.eod_extension_errors


def test_record_normalizes_shanghai_cross_day_and_rejects_naive_or_mismatch() -> None:
    assert _shanghai(datetime(2026, 8, 3, 16, tzinfo=timezone.utc), field="test").date() == date(2026, 8, 4)
    utc_quote = replace(quote(), quote_datetime=datetime(2026, 8, 4, 8, tzinfo=timezone.utc))
    item = record_from_quote(utc_quote, trading_date=date(2026, 8, 4), fetched_at=NOW)
    assert item.trading_date == date(2026, 8, 4) and item.quote_datetime.tzinfo == SHANGHAI
    assert error_code(lambda: record_from_quote(replace(quote(), quote_datetime=datetime(2026, 8, 4, 16)), trading_date=date(2026, 8, 4), fetched_at=NOW)) == "naive_quote_datetime"
    assert error_code(lambda: record_from_quote(quote(), trading_date=date(2026, 8, 5), fetched_at=NOW)) == "quote_date_mismatch"


def test_record_rejects_pre_close_and_invalid_ohlc() -> None:
    assert error_code(lambda: record_from_quote(replace(quote(), quote_datetime=datetime(2026, 8, 4, 14, 59, 59, tzinfo=SHANGHAI)), trading_date=date(2026, 8, 4), fetched_at=NOW)) == "market_not_closed"
    invalid = replace(quote(), high=Decimal("9"), low=Decimal("9.5"), open=Decimal("10"))
    assert error_code(lambda: record_from_quote(invalid, trading_date=date(2026, 8, 4), fetched_at=NOW)) == "invalid_ohlc"


def test_controlled_calendar_rejects_non_trading_and_out_of_range() -> None:
    assert error_code(lambda: validate_capture_date(date(2026, 8, 1))) == "non_trading_day"
    assert error_code(lambda: validate_capture_date(date(2027, 1, 4))) == "calendar_date_not_covered"


def test_capture_rejects_non_trading_before_provider_or_files(tmp_path: Path) -> None:
    provider = FakeProvider()
    service = SecurityProxyEodCaptureService(provider, SecurityProxyEodFileStore(tmp_path), now=lambda: CAPTURE_NOW)
    assert error_code(lambda: service.capture(date(2026, 8, 1), enable_provider=True)) == "non_trading_day"
    assert not provider.calls and not list(tmp_path.rglob("*.json"))


def test_capture_requires_explicit_enablement_and_closed_target_time(tmp_path: Path) -> None:
    service = SecurityProxyEodCaptureService(FakeProvider(), SecurityProxyEodFileStore(tmp_path), now=lambda: datetime(2026, 8, 5, 15, 9, tzinfo=SHANGHAI))
    with pytest.raises(PermissionError):
        service.capture(date(2026, 8, 5))
    assert error_code(lambda: service.capture(date(2026, 8, 5), enable_provider=True)) == "market_not_closed"


def test_store_is_stably_sorted_refuses_duplicate_day_and_updates_latest_atomically(tmp_path: Path) -> None:
    store = SecurityProxyEodFileStore(tmp_path)
    first = store.write_day(date(2026, 8, 4), (record("sz300308", date(2026, 8, 4)), record("sh510300", date(2026, 8, 4))))
    assert [row.symbol for row in store.records()] == ["sh510300", "sz300308"] and first.exists()
    old_latest = (tmp_path / "latest.json").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        store.write_day(date(2026, 8, 4), (record("sh510300", date(2026, 8, 4)),))
    with pytest.raises(SecurityProxyEodError, match="duplicate"):
        SecurityProxyEodFileStore(tmp_path / "two").write_day(date(2026, 8, 4), (record("sh510300", date(2026, 8, 4)), record("sh510300", date(2026, 8, 4))))
    assert old_latest == (tmp_path / "latest.json").read_text(encoding="utf-8")


def test_atomic_failure_preserves_old_file_and_cleans_temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "latest.json"
    target.write_text("old", encoding="utf-8")
    import leopard_project.security_proxy_eod as eod
    monkeypatch.setattr(eod.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old" and not list(tmp_path.glob(".*.tmp"))


def test_latest_failure_keeps_old_latest_and_complete_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SecurityProxyEodFileStore(tmp_path)
    store.write_day(date(2026, 8, 4), (record("sh510300", date(2026, 8, 4)),))
    old_latest = (tmp_path / "latest.json").read_text(encoding="utf-8")
    import leopard_project.security_proxy_eod as eod
    original = eod.atomic_write_text
    monkeypatch.setattr(eod, "atomic_write_text", lambda path, content, **kwargs: (_ for _ in ()).throw(OSError("latest failed")) if path.name == "latest.json" else original(path, content, **kwargs))
    with pytest.raises(OSError, match="latest failed"):
        store.write_day(date(2026, 8, 5), (record("sh510300", date(2026, 8, 5)),))
    assert store.day_path(date(2026, 8, 5)).exists() and (tmp_path / "latest.json").read_text(encoding="utf-8") == old_latest


def test_metrics_need_twenty_distinct_days_and_then_calculate() -> None:
    days = [date(2026, 7, 1 + index) for index in range(20)]
    rows = [record("sh510300", day, low="8" if index == 0 else "9", close="10", amount="100") for index, day in enumerate(days)]
    assert metrics_for(rows[:19], "sh510300").fastest_rebound_status == "insufficient_history"
    metric = metrics_for(rows, "sh510300")
    assert metric.accumulated_trading_days == 20 and metric.rolling_20d_low == Decimal("8") and metric.rebound_pct == Decimal("0.25")
    assert metric.turnover_slot_status == "available" and metric.market_cap_slot_status == "missing_verified_shares" and metric.etf_scale_slot_status == "missing_verified_aum"
    assert error_code(lambda: metrics_for(rows + [rows[-1]], "sh510300")) == "duplicate_security_date"


def test_capture_batches_and_preserves_manual_required_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    service = SecurityProxyEodCaptureService(provider, SecurityProxyEodFileStore(tmp_path), now=lambda: CAPTURE_NOW)
    result = service.capture(date(2026, 8, 5), enable_provider=True, market_path_keys=("cpo", "innovative_drug_medicine", "rare_earth"))
    assert len(result.records) == 13 and result.request_count == 1 and result.batch_count == 1 and [len(batch) for batch in provider.calls] == [13]
    symbols = {item.symbol for item in result.records}
    assert {"sz300308", "sz300502", "sz300394", "sh603259", "sz300760"} <= symbols
    monkeypatch.setattr("leopard_project.security_proxy_eod.candidate_symbols", lambda **_kwargs: tuple(f"sh{index:06d}" for index in range(21)))
    oversized = FakeProvider()
    result = SecurityProxyEodCaptureService(oversized, SecurityProxyEodFileStore(tmp_path / "oversized"), now=lambda: CAPTURE_NOW).capture(date(2026, 8, 5), enable_provider=True)
    assert len(result.records) == 21 and [len(batch) for batch in oversized.calls] == [20, 1]


def test_partial_and_empty_capture_fail_closed_without_fake_complete_file(tmp_path: Path) -> None:
    partial = SecurityProxyEodCaptureService(FakeProvider(failures={"sh515880": "bad"}), SecurityProxyEodFileStore(tmp_path / "partial"), now=lambda: CAPTURE_NOW).capture(date(2026, 8, 5), enable_provider=True, market_path_keys=("cpo",))
    assert len(partial.records) == 3 and partial.failures == {"sh515880": "malformed_record"}
    empty_root = tmp_path / "empty"
    assert error_code(lambda: SecurityProxyEodCaptureService(FakeProvider(empty=True), SecurityProxyEodFileStore(empty_root), now=lambda: CAPTURE_NOW).capture(date(2026, 8, 5), enable_provider=True, market_path_keys=("cpo",))) == "empty_capture"
    assert not list(empty_root.rglob("*.json"))


def test_candidates_are_deduplicated_and_have_no_history_scheduler_database_or_viewer_dependency() -> None:
    assert len(candidate_symbols()) == len(set(candidate_symbols()))
    assert candidate_symbols(market_path_keys=("cpo", "innovative_drug_medicine", "rare_earth")) == (
        "sh515880", "sz300308", "sz300502", "sz300394", "sh516780", "sh600111",
        "sz000831", "sz000970", "sz159992", "sh603259", "sz300760", "sh600276", "sh688180",
    )
    assert error_code(lambda: candidate_symbols(market_path_keys=("not-a-path",))) == "invalid_market_path"
    source = Path("backend/leopard_project/security_proxy_eod.py").read_text(encoding="utf-8").lower()
    assert all(value not in source for value in ("scheduler", "sqlite", "minute", "fqkline", "from .web"))
