from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market


def make_bars(count: int = 61, *, descending: bool = False, amount_step: int = 10) -> tuple[DailyBar, ...]:
    start = date(2026, 1, 1)
    bars = []
    for index in range(count):
        close = Decimal(200 - index if descending else 100 + index)
        pre_close = close - Decimal(-1 if descending else 1)
        bars.append(
            DailyBar(
                symbol="FIXTURE",
                symbol_name="固定夹具",
                market=Market.CN_A,
                trade_date=start + timedelta(days=index),
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                pre_close=pre_close,
                change=close - pre_close,
                pct_change=(close / pre_close - 1) * Decimal("100"),
                volume=Decimal(1000 + index),
                amount=Decimal(1000 + index * amount_step),
                liquidity_status=LiquidityStatus.COMPLETE,
                provider="fixture",
                fetched_at=datetime(2026, 7, 22, tzinfo=timezone.utc),
                source_payload_hash=f"hash-{index}",
                data_status=DataStatus.NORMAL,
            )
        )
    return tuple(bars)
