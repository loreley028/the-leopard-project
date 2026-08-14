from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from starlette.testclient import TestClient
from sqlalchemy import func, select

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService
from leopard_project.web.models import LiveMarketAnchorDaily, Report, SectorDailyBar, SectorPathHistoryEntry, SecurityProxyDaily
from leopard_project.web.path_history import _exact_market_payload
from leopard_project.config import load_seed_bundle
from leopard_project.security_proxy_observation import load_security_proxy_registry


def _settings(tmp_path) -> WebSettings:
    return WebSettings(
        database_url=f"sqlite:///{tmp_path / 'market.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        session_secret="fixture-value-for-objective-market-tests",
        admin_username="admin", admin_password="admin-password",
        viewer_username="viewer", viewer_password="viewer-password",
    )


def _bar(day: date) -> SectorDailyBar:
    return SectorDailyBar(
        sector_key="semiconductor", trade_date=day,
        close=Decimal("100"), pre_close=Decimal("99"), daily_pct_change=Decimal("1.01"),
        volume=Decimal("1"), amount=None, eod_status="complete_eod",
        data_source="legacy_test", provider_role="research_provider",
        fetched_at=datetime(2026, 8, 12, tzinfo=timezone.utc), source_response_hash="a" * 64,
    )


def test_exact_date_only_rejects_prior_market_fact() -> None:
    requested = date(2026, 8, 10)
    prior = _bar(date(2026, 7, 28))
    assert _exact_market_payload(requested_market_date=requested, snapshot=None, bar=prior) == (None, None, "unavailable")


def test_exact_date_only_attaches_matching_market_fact() -> None:
    requested = date(2026, 8, 10)
    exact = _bar(requested)
    assert _exact_market_payload(requested_market_date=requested, snapshot=None, bar=exact) == (requested, 1.01, "eod_complete")


def test_path_matrix_get_is_read_only_and_uses_uploaded_report_fallback(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    with sessions() as session:
        report = Report(
            title="published", report_date=date(2026, 8, 10), report_date_confirmed=True,
            status="published", is_current=True, created_by="admin", data_origin="real_upload",
        )
        session.add(report)
        session.commit()
        EnhancedReportService(session).ensure_structure(report)
    with TestClient(create_app(settings, sessions)) as client:
        assert client.get(f"/api/v1/reports/{report.id}/path-matrix").status_code == 200
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry)) == 0


def test_path_matrix_uses_exact_path_date_proxy_rows_without_synthesizing_a_sector_return(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    day, prior = date(2026, 8, 10), date(2026, 8, 9)
    with sessions() as session:
        report = Report(
            id="source", title="published", report_date=day, report_date_confirmed=True,
            status="published", is_current=True, created_by="admin", data_origin="real_upload",
        )
        session.add(report)
        for sector in load_seed_bundle().sectors:
            session.add(SectorPathHistoryEntry(
                sector_key=sector.sector_key, sector_name=sector.sector_name,
                path_report_date=day, path_status="hold", source_report_id=report.id,
                detail_report_id=report.id, market_as_of_date=None,
                frozen_daily_pct_change=None, market_data_status="unavailable",
                source_pdf_sha256="a" * 64,
            ))
        cpo = next(item for item in load_security_proxy_registry() if item.market_path_key == "cpo")
        for offset, instrument in enumerate(cpo.instruments):
            session.add_all([
                SecurityProxyDaily(symbol=instrument.symbol, trading_date=prior, close=Decimal("10") + offset,
                    open=None, high=None, low=None, amount_yuan=None, quote_datetime=None,
                    fetched_at=datetime.now(timezone.utc), source="test"),
                SecurityProxyDaily(symbol=instrument.symbol, trading_date=day, close=Decimal("11") + offset,
                    open=None, high=None, low=None, amount_yuan=None, quote_datetime=None,
                    fetched_at=datetime.now(timezone.utc), source="test"),
            ])
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        matrix = client.get(f"/api/v1/reports/{report.id}/path-matrix?periods=10").json()
    cpo_cell = next(row for row in matrix["rows"] if row["sector_key"] == "cpo")["cells"][0]
    assert cpo_cell["daily_return"] is None
    assert cpo_cell["market_overlay"]["kind"] == "proxy_multi"
    assert cpo_cell["market_overlay"]["label"] == "代理 4/4"
    assert cpo_cell["market_overlay"]["market_date"] == day.isoformat()
    assert len(cpo_cell["market_overlay"]["instruments"]) == 4
    assert all(item["pct_change"] is not None for item in cpo_cell["market_overlay"]["instruments"])


def test_market_anchor_works_without_report_and_falls_back_to_completed_eod(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    with sessions() as session:
        session.add(LiveMarketAnchorDaily(
            symbol="sh000001", trading_date=date(2026, 8, 12), close=Decimal("3946.68"),
            pre_close=Decimal("3934.09"), pct_change=Decimal("0.32"), high=None, low=None,
            quote_datetime=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc),
            source="tencent_standard_security_quote",
        ))
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        payload = client.get("/api/v1/market/anchor").json()
    assert payload["data_mode"] == "completed_eod"
    assert payload["trading_date"] == "2026-08-12"
    assert payload["value"] == 3946.68


def test_stale_anchor_quote_uses_completed_eod_instead_of_live_label(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    with sessions() as session:
        session.add(LiveMarketAnchorDaily(
            symbol="sh000001", trading_date=date(2026, 8, 12), close=Decimal("3946.68"),
            pre_close=Decimal("3934.09"), pct_change=Decimal("0.32"), high=None, low=None,
            quote_datetime=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc), source="tencent_standard_security_quote",
        ))
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        payload = client.get("/api/v1/market/anchor").json()
    assert payload["data_mode"] == "completed_eod"
    assert payload["current"] == 3946.68


def test_market_anchor_history_returns_only_actual_completed_days_in_ascending_order(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    with sessions() as session:
        trading_days = [
            date(2026, 7, 27), date(2026, 7, 28), date(2026, 7, 29), date(2026, 7, 30),
            date(2026, 7, 31), date(2026, 8, 3), date(2026, 8, 4), date(2026, 8, 5),
            date(2026, 8, 6), date(2026, 8, 7), date(2026, 8, 10), date(2026, 8, 11),
        ]
        for offset, day in enumerate(trading_days):
            session.add(LiveMarketAnchorDaily(
                symbol="sh000001", trading_date=day, close=Decimal(3900 + offset),
                pre_close=Decimal(3899 + offset), pct_change=Decimal("0.03"), high=None, low=None,
                quote_datetime=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc),
                fetched_at=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc),
                source="tencent_standard_security_quote",
            ))
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        payload = client.get("/api/v1/market/anchor/history").json()
    assert payload["completed_days"] == 10
    assert [item["trading_date"] for item in payload["items"]] == [item.isoformat() for item in trading_days[-10:]]
    assert all(item["data_mode"] == "completed_eod" for item in payload["items"])


def test_market_anchor_history_does_not_pad_missing_real_days(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    with sessions() as session:
        session.add(LiveMarketAnchorDaily(
            symbol="sh000001", trading_date=date(2026, 8, 12), close=Decimal("3946.68"),
            pre_close=Decimal("3934.09"), pct_change=Decimal("0.32"), high=None, low=None,
            quote_datetime=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 8, 12, 15, 20, tzinfo=timezone.utc), source="tencent_standard_security_quote",
        ))
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        payload = client.get("/api/v1/market/anchor/history").json()
    assert payload["completed_days"] == 1
    assert payload["items"] == [{
        "trading_date": "2026-08-12", "close": 3946.68, "pre_close": 3934.09,
        "change": 12.59, "pct_change": 0.32, "data_mode": "completed_eod",
        "quote_datetime": payload["items"][0]["quote_datetime"], "source": "tencent_standard_security_quote",
    }]
