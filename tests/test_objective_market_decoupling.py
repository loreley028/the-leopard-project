from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from starlette.testclient import TestClient
from sqlalchemy import func, select

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService
from leopard_project.web.models import (
    LiveMarketAnchorDaily,
    Report,
    SectorAssessment,
    SectorDailyBar,
    SectorPathEntry,
    SectorPathHistoryEntry,
    SecurityProxyDaily,
)
from leopard_project.web.path_history import _exact_market_payload
from leopard_project.config import load_seed_bundle
from leopard_project.security_proxy_observation import load_security_proxy_registry
from leopard_project.web.primary_market_observation import primary_for_exact_date, primary_history
from leopard_project.trading_calendar import report_market_date


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


def test_weekend_report_maps_previous_controlled_trade_day() -> None:
    assert report_market_date(date(2026, 8, 2)) == date(2026, 7, 31)


def test_holiday_report_maps_previous_controlled_trade_day() -> None:
    assert report_market_date(date(2026, 10, 7)) == date(2026, 9, 30)


def test_weekday_report_maps_same_day() -> None:
    assert report_market_date(date(2026, 8, 11)) == date(2026, 8, 11)


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


def test_matrix_uses_same_primary_across_dates_and_never_displays_proxy_ratio(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    day, prior = date(2026, 8, 7), date(2026, 8, 6)
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
    cpo_cell = next(
        item for item in next(row for row in matrix["rows"] if row["sector_key"] == "cpo")["cells"]
        if item["trading_date"] == day.isoformat()
    )
    assert cpo_cell["daily_return"] is None
    assert cpo_cell["market_overlay"]["kind"] == "primary"
    assert cpo_cell["market_overlay"]["label"] == "通信ETF +10.00%"
    assert cpo_cell["market_overlay"]["market_date"] == day.isoformat()
    assert cpo_cell["market_overlay"]["primary"] | {"pct_change": None} == {
        "name": "通信ETF", "security_code": "515880.SH", "role": "etf", "close": 11.0,
        "pct_change": None, "trading_date": day.isoformat(),
    }
    assert cpo_cell["market_overlay"]["primary"]["pct_change"] == pytest.approx(10.0)
    assert len(cpo_cell["market_overlay"]["instruments"]) == 3
    assert all(item["pct_change"] is not None for item in cpo_cell["market_overlay"]["instruments"])
    assert "代理" not in cpo_cell["market_overlay"]["label"]
    assert "官方" not in cpo_cell["market_overlay"]["label"]


def test_matrix_keeps_verified_report_local_ledger_over_stale_detail_overlay(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    day = date(2026, 8, 10)
    with sessions() as session:
        report = Report(
            id="report-local", title="published", report_date=day, report_date_confirmed=True,
            status="published", is_current=True, created_by="admin", data_origin="real_upload",
        )
        session.add(report)
        EnhancedReportService(session).ensure_structure(report)
        session.add(SectorPathHistoryEntry(
            sector_key="semiconductor", sector_name="半导体", path_report_date=day,
            path_status="hold", source_report_id=report.id, detail_report_id=report.id,
            market_as_of_date=None, frozen_daily_pct_change=None,
            market_data_status="unavailable", source_pdf_sha256="f" * 64,
            source_kind="report_local_pdf",
        ))
        primary = next(item for item in load_security_proxy_registry() if item.market_path_key == "cpo").primary_observation
        assert primary is not None
        session.add(SecurityProxyDaily(
            symbol=primary.symbol, trading_date=day, close=Decimal("10"), open=None,
            high=None, low=None, amount_yuan=None, quote_datetime=None,
            fetched_at=datetime.now(timezone.utc), source="test",
        ))
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        matrix = client.get(f"/api/v1/reports/{report.id}/path-matrix?periods=10").json()
    cell = next(item for item in next(row for row in matrix["rows"] if row["sector_key"] == "semiconductor")["cells"] if item["trading_date"] == day.isoformat())
    assert cell["path_status"] == "hold"
    assert cell["revision_id"] == report.id


@pytest.mark.parametrize(("frozen_status", "current_status"), [
    ("hold", "hold"),
    ("weak_watch", "avoid"),
])
def test_matrix_explicit_report_fact_refreshes_report_overlay(
    tmp_path, frozen_status: str, current_status: str,
) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    prior_day, day = date(2026, 8, 25), date(2026, 8, 26)
    primary = next(
        item for item in load_security_proxy_registry()
        if item.market_path_key == "semiconductor"
    ).primary_observation
    assert primary is not None
    with sessions() as session:
        prior_report = Report(
            id="prior-source", title="prior", report_date=prior_day,
            report_date_confirmed=True, status="published", is_current=True,
            created_by="admin", data_origin="real_upload",
        )
        current_report = Report(
            id="current-detail", title="current", report_date=day,
            report_date_confirmed=True, status="published", is_current=True,
            created_by="admin", data_origin="real_upload",
        )
        session.add_all([prior_report, current_report])
        EnhancedReportService(session).ensure_structure(current_report)
        entry = session.scalar(select(SectorPathEntry).where(
            SectorPathEntry.report_id == current_report.id,
            SectorPathEntry.sector_key == "semiconductor",
        ))
        assessment = session.scalar(select(SectorAssessment).where(
            SectorAssessment.report_id == current_report.id,
            SectorAssessment.sector_key == "semiconductor",
        ))
        assert entry is not None and assessment is not None
        entry.path_status = assessment.current_path_status = current_status
        entry.explicitly_mentioned = assessment.explicitly_mentioned = True
        session.add(SectorPathHistoryEntry(
            sector_key="semiconductor", sector_name="半导体", path_report_date=day,
            path_status=frozen_status, source_report_id=prior_report.id,
            detail_report_id=prior_report.id, market_as_of_date=None,
            frozen_daily_pct_change=None, market_data_status="unavailable",
            source_pdf_sha256="d" * 64, source_kind="full_pdf_matrix",
        ))
        session.add_all([
            SecurityProxyDaily(
                symbol=primary.symbol, trading_date=prior_day, close=Decimal("10"),
                open=None, high=None, low=None, amount_yuan=None, quote_datetime=None,
                fetched_at=datetime.now(timezone.utc), source="test",
            ),
            SecurityProxyDaily(
                symbol=primary.symbol, trading_date=day, close=Decimal("11"),
                open=None, high=None, low=None, amount_yuan=None, quote_datetime=None,
                fetched_at=datetime.now(timezone.utc), source="test",
            ),
        ])
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        matrix = client.get(
            f"/api/v1/reports/{current_report.id}/path-matrix?periods=10"
        ).json()
    cell = next(
        item
        for item in next(
            row for row in matrix["rows"] if row["sector_key"] == "semiconductor"
        )["cells"]
        if item["trading_date"] == day.isoformat()
    )
    assert cell["path_status"] == current_status
    assert cell["report_id"] == current_report.id
    assert cell["detail_report_id"] == current_report.id
    assert cell["revision_id"] == current_report.id


def test_matrix_uses_controlled_trading_days_and_maps_weekend_report_overlay(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    report_day, mapped_day, prior_day = date(2026, 8, 2), date(2026, 7, 31), date(2026, 7, 30)
    cpo = next(item for item in load_security_proxy_registry() if item.market_path_key == "cpo")
    with sessions() as session:
        report = Report(
            id="weekend", title="weekend", report_date=report_day, report_date_confirmed=True,
            status="published", is_current=True, created_by="admin", data_origin="real_upload",
        )
        session.add(report)
        session.add(SectorPathHistoryEntry(
            sector_key="cpo", sector_name="CPO", path_report_date=report_day, path_status="hold",
            source_report_id=report.id, detail_report_id=report.id, market_as_of_date=None,
            frozen_daily_pct_change=None, market_data_status="unavailable", source_pdf_sha256="b" * 64,
        ))
        primary = cpo.primary_observation
        assert primary is not None
        session.add_all([
            SecurityProxyDaily(symbol=primary.symbol, trading_date=prior_day, close=Decimal("10"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
            SecurityProxyDaily(symbol=primary.symbol, trading_date=mapped_day, close=Decimal("11"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
        ])
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        matrix = client.get(f"/api/v1/reports/{report.id}/path-matrix?periods=10").json()
    assert [item["trading_date"] for item in matrix["dates"]] == [prior_day.isoformat(), mapped_day.isoformat()]
    assert report_day.isoformat() not in [item["trading_date"] for item in matrix["dates"]]
    cpo_cells = next(row for row in matrix["rows"] if row["sector_key"] == "cpo")["cells"]
    no_report, weekend_overlay = cpo_cells
    assert no_report["report_present"] is False
    assert no_report["path_status"] is None
    assert no_report["path_status_color"] is None
    assert no_report["market_overlay"]["market_date"] == prior_day.isoformat()
    assert weekend_overlay["report_present"] is True
    assert weekend_overlay["report_date"] == report_day.isoformat()
    assert weekend_overlay["trading_date"] == mapped_day.isoformat()
    assert weekend_overlay["market_overlay"]["market_date"] == mapped_day.isoformat()


def test_sector_timeline_and_matrix_share_primary_observation_source(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    report_day, prior_day = date(2026, 8, 11), date(2026, 8, 10)
    cpo = next(item for item in load_security_proxy_registry() if item.market_path_key == "cpo")
    primary = cpo.primary_observation
    assert primary is not None
    with sessions() as session:
        report = Report(
            id="shared-primary", title="published", report_date=report_day, report_date_confirmed=True,
            status="published", is_current=True, created_by="admin", data_origin="real_upload",
        )
        session.add(report)
        session.add(SectorPathHistoryEntry(
            sector_key="cpo", sector_name="CPO", path_report_date=report_day, path_status="hold",
            source_report_id=report.id, detail_report_id=report.id, market_as_of_date=None,
            frozen_daily_pct_change=None, market_data_status="unavailable", source_pdf_sha256="c" * 64,
        ))
        session.add_all([
            SecurityProxyDaily(symbol=primary.symbol, trading_date=prior_day, close=Decimal("10"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
            SecurityProxyDaily(symbol=primary.symbol, trading_date=report_day, close=Decimal("11"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
        ])
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        timeline = client.get("/api/v1/sectors/cpo/research").json()
        matrix = client.get("/api/v1/reports/shared-primary/path-matrix?periods=10").json()
    assert timeline["timeline_market_basis"] == {"name": primary.security_name, "security_code": primary.reader_code}
    cpo_cell = next(cell for cell in next(row for row in matrix["rows"] if row["sector_key"] == "cpo")["cells"] if cell["trading_date"] == report_day.isoformat())
    assert cpo_cell["market_overlay"]["primary"]["name"] == timeline["timeline_market_basis"]["name"]
    assert cpo_cell["market_overlay"]["primary"]["security_code"] == timeline["timeline_market_basis"]["security_code"]


def test_matrix_market_axis_extends_beyond_latest_report_and_keeps_empty_report_overlay(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    report_day, later_day, prior_day = date(2026, 8, 11), date(2026, 8, 12), date(2026, 8, 10)
    cpo = next(item for item in load_security_proxy_registry() if item.market_path_key == "cpo")
    primary = cpo.primary_observation
    assert primary is not None
    with sessions() as session:
        session.add(Report(id="market-axis", title="published", report_date=report_day, report_date_confirmed=True, status="published", is_current=True, created_by="admin", data_origin="real_upload"))
        session.add_all([
            SecurityProxyDaily(symbol=primary.symbol, trading_date=prior_day, close=Decimal("10"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
            SecurityProxyDaily(symbol=primary.symbol, trading_date=report_day, close=Decimal("11"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
            SecurityProxyDaily(symbol=primary.symbol, trading_date=later_day, close=Decimal("12"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"),
        ])
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        matrix = client.get("/api/v1/reports/market-axis/path-matrix?periods=10").json()
    assert matrix["date_axis_kind"] == "market_trading_day"
    assert [item["trading_date"] for item in matrix["dates"]][-1] == later_day.isoformat()
    cpo_cell = next(item for item in next(row for row in matrix["rows"] if row["sector_key"] == "cpo")["cells"] if item["trading_date"] == later_day.isoformat())
    assert cpo_cell["report_present"] is False
    assert cpo_cell["path_status"] is None


def test_primary_market_exact_date_only_and_no_primary_truthful_empty(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    cpo = next(item for item in load_security_proxy_registry() if item.market_path_key == "cpo")
    with sessions() as session:
        session.add(SecurityProxyDaily(
            symbol="sz300308", trading_date=date(2026, 8, 10), close=Decimal("100"),
            open=None, high=None, low=None, amount_yuan=None, quote_datetime=None,
            fetched_at=datetime.now(timezone.utc), source="test",
        ))
        session.commit()
        assert primary_for_exact_date(session, cpo, date(2026, 8, 10)) is None
        primary = primary_history(session, cpo)
    assert primary is not None
    assert primary["symbol"] == "sh515880"
    assert primary["history"] == []
    assert primary["close"] is None


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
