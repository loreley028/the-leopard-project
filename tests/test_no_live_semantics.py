from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from starlette.testclient import TestClient

from leopard_project.trading_calendar import next_controlled_trading_day
from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.effective_strategy import ReportStrategyFact, effective_strategy_for_trading_day
from leopard_project.web.enhanced import EnhancedReportService
from leopard_project.web.models import (
    LiveMarketAnchorDaily,
    Report,
    ReportDay,
    ReportFile,
    ReportStatus,
    SectorAssessment,
    SectorPathEntry,
    SecurityProxyDaily,
)


DAY_1 = date(2026, 8, 27)
NO_LIVE_DAY = date(2026, 8, 30)
DAY_2 = date(2026, 8, 31)
SECTOR = "semiconductor"


def _web(tmp_path: Path) -> tuple[TestClient, object]:
    database_url = f"sqlite:///{tmp_path / 'no-live.sqlite3'}"
    sessions = create_session_factory(database_url)
    app = create_app(WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-no-live-session-secret-32chars",
        admin_username="admin",
        admin_password="admin-password",
        viewer_username="viewer",
        viewer_password="viewer-password",
    ), sessions)
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password"}).status_code == 200
    return client, sessions


def _report(session, report_id: str, report_date: date, *, status: str, explicit: bool, sector_key: str = SECTOR, sector_name: str = "半导体") -> Report:
    report = Report(
        id=report_id,
        title=f"authoritative {report_date.isoformat()}",
        report_date=report_date,
        report_date_confirmed=True,
        report_date_confidence="high",
        status=ReportStatus.PUBLISHED.value,
        is_current=True,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        created_by="admin",
        published_by="admin",
    )
    session.add(report)
    session.add(ReportFile(
        report_id=report_id,
        sha256=f"{sum(map(ord, report_id)):064x}",
        original_filename=f"{report_id}.pdf",
        storage_filename=f"{report_id}.pdf",
        content_type="application/pdf",
        size_bytes=1,
    ))
    session.add(SectorPathEntry(
        report_id=report_id,
        sector_key=sector_key,
        sector_name=sector_name,
        path_status=status,
        explicitly_mentioned=explicit,
        quality_status="verified_structure",
        review_status="confirmed",
    ))
    session.add(SectorAssessment(
        report_id=report_id,
        sector_key=sector_key,
        sector_name=sector_name,
        current_path_status=status,
        explicitly_mentioned=explicit,
        quality_status="verified_structure",
        review_status="confirmed",
    ))
    return report


def _market_core_row(session, trading_day: date) -> None:
    session.add(LiveMarketAnchorDaily(
        symbol="sh000001",
        trading_date=trading_day,
        close=3900,
        pre_close=3890,
        pct_change=0.26,
        high=None,
        low=None,
        quote_datetime=datetime.combine(trading_day, datetime.min.time(), tzinfo=timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        source="acceptance",
    ))
    session.add(SecurityProxyDaily(
        symbol="sz159995",
        trading_date=trading_day,
        close=1,
        open=None,
        high=None,
        low=None,
        amount_yuan=None,
        quote_datetime=None,
        fetched_at=datetime.now(timezone.utc),
        source="acceptance",
    ))


def test_generic_no_live_three_date_acceptance(tmp_path: Path) -> None:
    """Cases 1, 3, 4 and 5 using the real acceptance calendar dates."""
    client, sessions = _web(tmp_path)
    with sessions() as session:
        _report(session, "r0827", DAY_1, status="hold", explicit=True)
        for item in (DAY_1, date(2026, 8, 28), DAY_2):
            _market_core_row(session, item)
        session.commit()

    # CASE 1/4: calendar-only no_live makes no report facts and does not block market rows.
    response = client.post(f"/api/v1/admin/report-days/{NO_LIVE_DAY.isoformat()}/no-live", json={"reason": "confirmed no live"})
    assert response.status_code == 200
    assert response.json()["state"] == "no_live"
    days = client.get("/api/v1/admin/report-days?start=2026-08-27&end=2026-08-31").json()
    no_live = next(item for item in days if item["report_date"] == NO_LIVE_DAY.isoformat())
    assert no_live["state"] == "no_live" and no_live["reports"] == []
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Report).where(Report.report_date == NO_LIVE_DAY)) == 0
        assert session.scalar(select(func.count()).select_from(SectorAssessment).join(Report).where(Report.report_date == NO_LIVE_DAY)) == 0
        assert session.scalar(select(func.count()).select_from(SectorPathEntry).join(Report).where(Report.report_date == NO_LIVE_DAY)) == 0
        assert session.scalar(select(func.count()).select_from(LiveMarketAnchorDaily).where(LiveMarketAnchorDaily.trading_date == DAY_2)) == 1
        service = EnhancedReportService(session)
        daytime = service.effective_strategy_for_sector(SECTOR, DAY_2)
        assert (daytime.effective_status, daytime.source_report_id, daytime.source_report_date) == ("hold", "r0827", DAY_1)

        # CASE 5: a later explicit report refreshes provenance only from its
        # next controlled trading day, while a report-local not-mentioned row
        # remains distinguishable from the no-live calendar record.
        _report(session, "r0831", DAY_2, status="strong_watch", explicit=True)
        session.add(SectorPathEntry(
            report_id="r0831", sector_key="bank", sector_name="银行", path_status="not_mentioned",
            explicitly_mentioned=False, quality_status="verified_structure", review_status="confirmed",
        ))
        session.add(SectorAssessment(
            report_id="r0831", sector_key="bank", sector_name="银行", current_path_status="not_mentioned",
            explicitly_mentioned=False, quality_status="verified_structure", review_status="confirmed",
        ))
        session.commit()

    with sessions() as session:
        service = EnhancedReportService(session)
        daytime = service.effective_strategy_for_sector(SECTOR, DAY_2)
        next_day = next_controlled_trading_day(DAY_2)
        assert next_day is not None
        overnight = service.effective_strategy_for_sector(SECTOR, next_day)
        assert daytime.source_report_id == "r0827" and daytime.effective_status == "hold"
        assert (overnight.effective_status, overnight.source_report_id, overnight.source_report_date) == ("strong_watch", "r0831", DAY_2)
        # CASE 3: a real report-local not_mentioned exists only on a
        # published report and is different from the no-live calendar record.
        assert session.scalar(select(func.count()).select_from(SectorAssessment).where(
            SectorAssessment.report_id == "r0831", SectorAssessment.sector_key == "bank", SectorAssessment.current_path_status == "not_mentioned",
        )) == 1
        _report(session, "r0901", next_day, status="not_mentioned", explicit=False)
        session.commit()
        after_not_mentioned = service.effective_strategy_for_sector(SECTOR, next_controlled_trading_day(next_day))
        assert after_not_mentioned.source_report_id == "r0831"
        assert session.scalar(select(func.count()).select_from(ReportDay).where(ReportDay.report_date == NO_LIVE_DAY)) == 1

    matrix = client.get("/api/v1/reports/r0831/path-matrix?periods=10").json()
    timeline = {(item["report_date"], item["state"]): item for item in matrix["report_calendar"]}
    assert timeline[(DAY_1.isoformat(), "published")]["report_id"] == "r0827"
    assert timeline[(NO_LIVE_DAY.isoformat(), "no_live")]["display_label"] == "休"
    assert timeline[(DAY_2.isoformat(), "published")]["report_id"] == "r0831"


def test_turn_hold_matures_once_and_no_live_cannot_repeat_it() -> None:
    """CASE 2: transition signal is one-day display metadata, not a new fact."""
    first_effective_day = next_controlled_trading_day(DAY_1)
    assert first_effective_day is not None
    facts = [ReportStrategyFact("r0827", DAY_1, "turn_hold", True)]
    on_first_day = effective_strategy_for_trading_day(facts, first_effective_day)
    after_no_live_gap = effective_strategy_for_trading_day(facts, DAY_2)
    assert (on_first_day.effective_status, on_first_day.display_signal, on_first_day.source_report_id) == ("hold", "turn_hold", "r0827")
    assert (after_no_live_gap.effective_status, after_no_live_gap.display_signal, after_no_live_gap.source_report_id) == ("hold", None, "r0827")
