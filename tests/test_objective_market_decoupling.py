from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from starlette.testclient import TestClient
from sqlalchemy import func, select

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService
from leopard_project.web.models import LiveMarketAnchorDaily, Report, SectorDailyBar, SectorPathHistoryEntry
from leopard_project.web.path_history import _exact_market_payload


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
