from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from leopard_project.config import load_seed_bundle
from leopard_project.market_paths import load_market_path_registry
from leopard_project.providers.capabilities import provider_capability_summary
from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market
from leopard_project.web.database import create_session_factory
from leopard_project.web.market_automation import EodBackfillCoordinator, expected_latest_complete_trade_date
from leopard_project.web.models import SectorDailyBar, SectorIndicatorSnapshot


def _stored_bar(sector_key: str, trade_date: date) -> SectorDailyBar:
    return SectorDailyBar(
        sector_key=sector_key,
        trade_date=trade_date,
        open=100,
        high=101,
        low=99,
        close=100,
        pre_close=99,
        daily_pct_change=Decimal("1.010101"),
        volume=1000,
        amount=None,
        turnover_rate=None,
        liquidity_status="partial",
        eod_status="complete_eod",
        data_source="real_test_source",
        provider_role="diagnostic_provider",
        fetched_at=datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc),
        source_response_hash=(sector_key * 64)[:64],
    )


class OneDayProvider:
    def historical_daily_bars(self, symbol: str, _start: date, end: date, _market: Market):
        close = Decimal("102")
        return [DailyBar(
            symbol=symbol,
            symbol_name=symbol,
            market=Market.CN_A,
            trade_date=end,
            open=Decimal("100"),
            high=Decimal("103"),
            low=Decimal("99"),
            close=close,
            pre_close=Decimal("100"),
            change=Decimal("2"),
            pct_change=Decimal("2"),
            volume=Decimal("1200"),
            amount=None,
            turnover_rate=None,
            liquidity_status=LiquidityStatus.PARTIAL,
            provider="real_test_source",
            fetched_at=datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc),
            source_payload_hash=(symbol * 64)[:64],
            data_status=DataStatus.NORMAL,
        )]


def test_expected_latest_complete_trade_date_uses_shanghai_close_and_calendar() -> None:
    trading = {date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28)}
    assert expected_latest_complete_trade_date(datetime(2026, 7, 28, 7, 29, tzinfo=timezone.utc), trading) == date(2026, 7, 27)
    assert expected_latest_complete_trade_date(datetime(2026, 7, 28, 7, 30, tzinfo=timezone.utc), trading) == date(2026, 7, 28)
    assert expected_latest_complete_trade_date(datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc), trading) == date(2026, 7, 28)


def test_gap_only_backfill_recalculates_indicators_and_never_requests_hstech(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'eod.sqlite3'}")
    supported = list(load_market_path_registry().supported_market_paths)
    with sessions() as session:
        session.add_all(_stored_bar(sector.market_path_key, date(2026, 7, 24)) for sector in supported)
        session.add(_stored_bar("catering", date(2026, 7, 27)))
        session.commit()

    coordinator = EodBackfillCoordinator(
        sessions,
        now=lambda: datetime(2026, 7, 28, 4, 0, tzinfo=timezone.utc),
        provider_factory=OneDayProvider,
    )
    before = coordinator.status()
    assert before["expected_latest_complete_trade_date"] == "2026-07-27"
    assert before["latest_complete_trade_date"] == "2026-07-27"
    assert before["missing_dates"] == ["2026-07-27"]
    operational = provider_capability_summary()["operational_coverage"]
    assert before["missing_sector_count"] == operational

    result = coordinator.run_if_needed()
    assert result["status"] == "complete"
    assert result["success_count"] == result["requested_count"] == operational
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SectorDailyBar).where(SectorDailyBar.trade_date == date(2026, 7, 27))) == len(supported)
        assert session.scalar(select(func.count()).select_from(SectorIndicatorSnapshot)) == 130
        assert session.scalar(select(func.count()).select_from(SectorDailyBar).where(SectorDailyBar.sector_key == "hang_seng_tech")) == 0
    assert coordinator.status()["missing_dates"] == []
