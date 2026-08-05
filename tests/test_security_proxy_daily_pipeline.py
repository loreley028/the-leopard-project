from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from leopard_project.providers.tencent_standard_quote import StandardSecurityQuote, TencentQuoteBatch, TencentQuoteErrorCode
from leopard_project.security_proxy_daily_pipeline import SecurityProxyDailyPipeline
from leopard_project.security_proxy_eod import SHANGHAI


class FakeProvider:
    max_batch_size = 20
    def fetch_batch(self, symbols, *, allow_network=False):
        now = datetime(2026, 8, 5, 15, 21, tzinfo=SHANGHAI)
        quotes = tuple(StandardSecurityQuote(symbol, symbol, symbol[2:], Decimal("10"), Decimal("9"), now, Decimal("1"), Decimal("11.11"), 88, "hash", Decimal("9.5"), Decimal("10.5"), Decimal("9.4"), Decimal("100")) for symbol in symbols)
        return TencentQuoteBatch(quotes, {}, 1)


def test_daily_pipeline_is_default_disabled_idempotent_and_file_only(tmp_path: Path) -> None:
    pipeline = SecurityProxyDailyPipeline(eod_root=tmp_path / "eod", selection_root=tmp_path / "selection", provider=FakeProvider(), now=lambda: datetime(2026, 8, 5, 15, 21, tzinfo=SHANGHAI))
    assert pipeline.run_once()["status"] == "scheduler_disabled"
    result = pipeline.run_once(enable_provider=True)
    assert result["status"] == "completed" and result["database_written"] is False
    assert pipeline.run_once(enable_provider=True)["status"] == "already_completed"


def test_daily_pipeline_reuses_an_existing_verified_day_without_overwrite(tmp_path: Path) -> None:
    pipeline = SecurityProxyDailyPipeline(eod_root=tmp_path / "eod", selection_root=tmp_path / "selection", provider=FakeProvider(), now=lambda: datetime(2026, 8, 5, 15, 21, tzinfo=SHANGHAI))
    first = pipeline.run_once(enable_provider=True)
    (tmp_path / "selection" / "2026" / "2026-08-05.json").unlink()
    second = pipeline.run_once(enable_provider=True)
    assert first["status"] == second["status"] == "completed" and second["provider_called"] is False


def test_daily_pipeline_rejects_before_safe_window_without_provider(tmp_path: Path) -> None:
    pipeline = SecurityProxyDailyPipeline(eod_root=tmp_path / "eod", selection_root=tmp_path / "selection", provider=FakeProvider(), now=lambda: datetime(2026, 8, 5, 15, 19, tzinfo=SHANGHAI))
    assert pipeline.run_once(enable_provider=True)["status"] == "market_not_closed"
