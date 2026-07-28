from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market
from leopard_project.web.database import create_session_factory
from leopard_project.web.market_ingestion import import_real_market, refresh_real_market
from leopard_project.web.models import SectorDailyBar, SectorIndicatorSnapshot


def bar(day: date, index: int = 0) -> DailyBar:
    close = Decimal("100") + index
    return DailyBar(
        symbol="881121", symbol_name="半导体", market=Market.CN_A, trade_date=day,
        open=close - 1, high=close + 1, low=close - 2, close=close,
        pre_close=close - 1, change=Decimal("1"), pct_change=Decimal("1"),
        volume=Decimal("1000"), amount=Decimal("2000"), turnover_rate=None,
        liquidity_status=LiquidityStatus.COMPLETE, provider="fake_diagnostic",
        fetched_at=datetime(2026, 7, 27, tzinfo=UTC), source_payload_hash=f"{index:064d}",
        data_status=DataStatus.NORMAL,
    )


class FakeProvider:
    def historical_daily_bars(self, symbol, start, end, market):
        assert symbol == "881121"
        return [bar(date(2026, 6, 1) + timedelta(days=index), index) for index in range(24)]


def test_manual_real_refresh_is_injected_offline_and_recalculates_indicators(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'market.sqlite3'}")
    with sessions() as session:
        run = refresh_real_market(session, "admin", sector_keys=["semiconductor"], as_of=date(2026, 7, 24), provider=FakeProvider())
        assert (run.requested_count, run.success_count, run.failure_count) == (1, 1, 0)
        assert run.provider_role == "diagnostic_provider"
        assert session.scalar(select(func.count()).select_from(SectorDailyBar)) == 24
        assert session.scalar(select(func.count()).select_from(SectorIndicatorSnapshot)) == 24
        stored = session.scalar(select(SectorDailyBar).order_by(SectorDailyBar.trade_date.desc()))
        assert stored is not None and stored.eod_status == "complete_eod"
        assert stored.data_source == "ths_public_validation"


def test_csv_import_previews_then_writes_without_fabricating_amount(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'import.sqlite3'}")
    payload = (
        "trade_date,sector_key,open,high,low,close,pre_close,volume,amount,turnover_rate,source_name\n"
        "2026-07-24,semiconductor,100,103,99,102,100,12345,,,licensed_manual_export\n"
    ).encode()
    with sessions() as session:
        preview = import_real_market(session, "admin", "market.csv", payload, confirmed=False)
        assert preview["ready_count"] == 1 and preview["written"] is False
        assert session.scalar(select(func.count()).select_from(SectorDailyBar)) == 0
        result = import_real_market(session, "admin", "market.csv", payload, confirmed=True)
        assert result["success_count"] == 1
        stored = session.scalar(select(SectorDailyBar))
        assert stored is not None
        assert stored.amount is None
        assert stored.liquidity_status == "partial"
        assert stored.data_source == "manual_file_import:licensed_manual_export"
