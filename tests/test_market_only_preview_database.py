from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from leopard_project.web.database import create_session_factory
from leopard_project.web.models import LiveMarketAnchorDaily, Report, SecurityProxyDaily
from scripts.create_market_only_preview_database import create_market_only_database


def test_market_only_preview_copies_only_objective_market_tables(tmp_path) -> None:
    source, target = tmp_path / "source.sqlite3", tmp_path / "market-only.sqlite3"
    sessions = create_session_factory(f"sqlite:///{source}")
    with sessions() as session:
        session.add_all([
            Report(title="must not copy", status="published", is_current=True, created_by="admin", data_origin="real_upload"),
            LiveMarketAnchorDaily(symbol="sh000001", trading_date=date(2026, 8, 12), close=Decimal("3946.68"), pre_close=Decimal("3934.09"), pct_change=Decimal("0.32"), high=None, low=None, quote_datetime=datetime.now(timezone.utc), fetched_at=datetime.now(timezone.utc), source="tencent_standard_security_quote"),
            SecurityProxyDaily(symbol="sh515880", trading_date=date(2026, 8, 12), close=Decimal("1"), quote_datetime=datetime.now(timezone.utc), fetched_at=datetime.now(timezone.utc), source="tencent_standard_security_quote"),
        ])
        session.commit()
    summary = create_market_only_database(source, target)
    assert summary["live_market_anchor_daily"] == 1 and summary["security_proxy_daily"] == 1
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM live_market_anchor_daily").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM security_proxy_daily").fetchone()[0] == 1


def test_market_only_preview_refuses_to_overwrite_target(tmp_path) -> None:
    source, target = tmp_path / "source.sqlite3", tmp_path / "market-only.sqlite3"
    create_session_factory(f"sqlite:///{source}")
    target.write_bytes(b"do-not-overwrite")
    with pytest.raises(ValueError, match="already exists"):
        create_market_only_database(source, target)
