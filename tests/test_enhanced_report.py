from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from sqlalchemy import select

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web import enhanced as enhanced_module
from leopard_project.web.enhanced import EnhancedReportService, calculate_market_metrics, validate_path_status
from leopard_project.web.models import Report, ReportFile, ReportStatus, SectorAssessment, SectorDailyBar, SectorPathEntry, SectorPathHistoryEntry, SecurityProxyDaily
from leopard_project.web.services import WebDomainError


FIXTURE = Path(__file__).parent / "fixtures/sample_report_fixture.pdf"


@pytest.fixture()
def enhanced_web(tmp_path: Path):
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'enhanced.sqlite3'}")
    settings = WebSettings(
        database_url=f"sqlite:///{tmp_path / 'enhanced.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-enhanced-session-value-32-characters",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
    )
    with TestClient(create_app(settings, sessions)) as client:
        yield client, sessions


def login(client: TestClient, role: str = "admin") -> None:
    assert client.post("/api/v1/auth/login", json={"username": role, "password": f"{role}-test-password"}).status_code == 200


def create_report(client: TestClient, report_date: str = "2026-07-19") -> str:
    payload = FIXTURE.read_bytes() + f"\n% enhanced:{report_date}\n".encode()
    report_id = client.post("/api/v1/admin/reports", files={"file": (f"{report_date}.pdf", payload, "application/pdf")}).json()["report"]["id"]
    assert client.post(f"/api/v1/admin/reports/{report_id}/parse").status_code == 200
    assert client.patch(f"/api/v1/admin/reports/{report_id}", json={"report_date": report_date, "report_date_confirmed": True}).status_code == 200
    return report_id


def test_path_status_contract_and_unknown_rejected() -> None:
    assert validate_path_status("hold") == "hold"
    assert validate_path_status("not_mentioned") == "not_mentioned"
    with pytest.raises(WebDomainError) as exc:
        validate_path_status("invented")
    assert exc.value.code == "unknown_path_status"


def test_metrics_use_complete_eod_and_prior_volume_window() -> None:
    bars = []
    for index in range(21):
        close = Decimal("100") + index
        bars.append(SectorDailyBar(
            sector_key="semiconductor",
            trade_date=date(2026, 6, 1 + index),
            close=close,
            pre_close=close - 1,
            daily_pct_change=Decimal("1"),
            volume=Decimal("100") if index < 20 else Decimal("200"),
            amount=None,
            eod_status="complete_eod",
            data_source="fixture",
            provider_role="best_effort_research_source",
            fetched_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            source_response_hash=f"{index:064d}",
        ))
    metrics = calculate_market_metrics(bars)
    assert metrics["ma5"] == Decimal("118")
    assert metrics["ma10"] == Decimal("115.5")
    assert metrics["ma20"] == Decimal("110.5")
    assert metrics["return_5d"] == Decimal("4.347826086956521739130434800")
    assert metrics["return_10d"] == Decimal("9.090909090909090909090909100")
    assert metrics["return_10d"] != sum(bar.daily_pct_change for bar in bars[-10:])
    assert metrics["volume_ratio_5d"] == Decimal("2")
    bars[-1].eod_status = "intraday_snapshot"
    assert calculate_market_metrics(bars)["ma20"] == Decimal("109.5")


def test_recent_complete_days_returns_latest_ten_controlled_dates_in_ascending_order(enhanced_web) -> None:
    _, sessions = enhanced_web
    controlled_dates = [
        date(2026, 7, 20), date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23),
        date(2026, 7, 24), date(2026, 7, 27), date(2026, 7, 28), date(2026, 7, 29),
        date(2026, 7, 30), date(2026, 7, 31), date(2026, 8, 3), date(2026, 8, 4),
    ]
    with sessions() as session:
        for index, trade_date in enumerate(controlled_dates):
            session.add(SectorDailyBar(
                sector_key="semiconductor", trade_date=trade_date,
                close=Decimal("100") + index, pre_close=Decimal("99") + index,
                daily_pct_change=Decimal("1") if index % 3 == 0 else Decimal("-1") if index % 3 == 1 else Decimal("0"),
                volume=Decimal("100"), amount=None, eod_status="complete_eod",
                data_source="fixture", provider_role="research_provider",
                fetched_at=datetime(2026, 8, 4, tzinfo=timezone.utc), source_response_hash=f"{index:064d}",
            ))
        session.add(SectorDailyBar(
            sector_key="semiconductor", trade_date=date(2026, 8, 5), close=Decimal("999"),
            pre_close=Decimal("998"), daily_pct_change=Decimal("1"), volume=Decimal("100"), amount=None,
            eod_status="intraday_snapshot", data_source="fixture", provider_role="research_provider",
            fetched_at=datetime(2026, 8, 5, tzinfo=timezone.utc), source_response_hash="f" * 64,
        ))
        session.commit()
        recent = EnhancedReportService(session).recent_complete_days("semiconductor")
    assert [item["trade_date"] for item in recent] == [item.isoformat() for item in controlled_dates[-10:]]
    assert len(recent) == 10
    assert "2026-07-25" not in {item["trade_date"] for item in recent}
    assert "2026-08-01" not in {item["trade_date"] for item in recent}


def test_viewer_assessment_hides_legacy_pending_review_placeholder(enhanced_web) -> None:
    client, sessions = enhanced_web
    login(client)
    report_id = create_report(client)
    assert client.post(f"/api/v1/admin/reports/{report_id}/enhance/parse").status_code == 200
    assert client.post(f"/api/v1/admin/reports/{report_id}/enhanced-ready").status_code == 200
    assert client.post(f"/api/v1/admin/reports/{report_id}/publish").status_code == 200
    with sessions() as session:
        assessment = session.scalar(select(SectorAssessment).where(
            SectorAssessment.report_id == report_id, SectorAssessment.sector_key == "chemicals",
        ))
        assert assessment is not None
        assessment.explicitly_mentioned = True
        assessment.main_basis = "等待管理员复核"
        assessment.observation_condition = "等待管理员复核"
        session.commit()
    payload = client.get(f"/api/v1/reports/{report_id}/enhanced").json()
    assessment = next(item for item in payload["sector_assessments"] if item["sector_key"] == "chemicals")
    assert assessment["main_basis"] == "本期报告未提供可结构化展示的独立依据"
    assert assessment["observation_condition"] == ""


def test_verified_native_reparse_repairs_report_local_status_without_touching_history(enhanced_web, monkeypatch) -> None:
    _, sessions = enhanced_web
    record = {
        "sector_key": "semiconductor", "sector_name": "半导体", "path_status": "weak_watch",
        "recent_path_summary": "8/19弱观 → 8/20弱观", "current_judgement": "弱观",
        "main_basis": "主力资金仍在离场。", "observation_condition": "需明显反弹才重新评估。",
        "source_section": "板块观点详细汇总", "source_text_reference": "PDF 原生五列表格行",
        "source_text_excerpt": "PDF 原生五列表格行", "source_page": 7, "source_text_start": 100,
        "source_text_end": 200, "extraction_method": "pdf_v29_positioned_table_cells",
        "quality_status": "verified_structure", "confidence": "high", "validation_flags": [],
    }
    monkeypatch.setattr(enhanced_module, "extract_text_layer", lambda payload: "PDF text")
    monkeypatch.setattr(enhanced_module, "extract_layout_text", lambda payload: "PDF layout")
    monkeypatch.setattr(enhanced_module, "extract_positioned_pages", lambda payload: [])
    monkeypatch.setattr(
        enhanced_module, "parse_report_text",
        lambda *args, **kwargs: ({"interpretation_meta": {"assessment_records": [record]}}, [], [], []),
    )
    with sessions() as session:
        report = Report(title="published", status="published", created_by="admin", interpretation_meta_json="{}")
        session.add(report)
        session.flush()
        session.add_all([
            SectorPathEntry(
                report_id=report.id, sector_key="semiconductor", sector_name="半导体", path_status="watch",
                explicitly_mentioned=False, judgement_summary="", source_text_reference="fallback",
            ),
            SectorAssessment(
                report_id=report.id, sector_key="semiconductor", sector_name="半导体", current_path_status="watch",
                explicitly_mentioned=False, recent_path_summary="本期首次记录", current_judgement="",
                main_basis="", observation_condition="", source_text_reference="fallback",
            ),
            SectorPathHistoryEntry(
                sector_key="semiconductor", sector_name="半导体", path_report_date=date(2026, 8, 20),
                path_status="hold", source_report_id=report.id, detail_report_id=report.id,
                market_as_of_date=None, frozen_daily_pct_change=None, market_data_status="unavailable",
                source_pdf_sha256="a" * 64,
            ),
        ])
        session.commit()
        result = EnhancedReportService(session).reparse_missing_assessment_facts(report, b"pdf", "test")
        assessment = session.scalar(select(SectorAssessment).where(SectorAssessment.report_id == report.id))
        entry = session.scalar(select(SectorPathEntry).where(SectorPathEntry.report_id == report.id))
        frozen = session.scalar(select(SectorPathHistoryEntry).where(SectorPathHistoryEntry.source_report_id == report.id))
    assert result == {"parsed_records": 1, "updated_assessments": 1, "updated_path_entries": 1}
    assert assessment is not None and assessment.current_path_status == "weak_watch"
    assert assessment.explicitly_mentioned is True and assessment.current_judgement == "弱观"
    assert assessment.main_basis == "主力资金仍在离场。"
    assert entry is not None and (entry.path_status, entry.explicitly_mentioned, entry.judgement_summary) == ("weak_watch", True, "弱观")
    assert frozen is not None and frozen.path_status == "hold"


def test_market_date_contract_sunday_and_fail_closed(enhanced_web) -> None:
    client, sessions = enhanced_web
    login(client)
    report_id = create_report(client)
    accepted = client.post(f"/api/v1/admin/reports/{report_id}/market-binding", json={"market_as_of_date": "2026-07-17", "confirmed": True})
    assert accepted.status_code == 200
    assert accepted.json()["market_as_of_date"] == "2026-07-17"
    assert client.post(f"/api/v1/admin/reports/{report_id}/market-binding", json={"market_as_of_date": "2026-07-19", "confirmed": True}).json()["error"]["code"] == "market_date_not_trading_day"
    assert client.post(f"/api/v1/admin/reports/{report_id}/market-binding", json={"market_as_of_date": "2026-08-03", "confirmed": True}).json()["error"]["code"] == "calendar_coverage_unavailable"


def test_real_complete_eod_coverage_can_prove_trading_day_outside_fixture_calendar(enhanced_web) -> None:
    client, sessions = enhanced_web
    login(client)
    report_id = create_report(client)
    with sessions() as session:
        report = session.get(Report, report_id)
        assert report is not None
        report.report_date = date(2026, 8, 4)
        for index in range(60):
            session.add(SectorDailyBar(
                sector_key=f"observed-{index}", trade_date=date(2026, 8, 3),
                close=Decimal("100"), pre_close=Decimal("99"), daily_pct_change=Decimal("1.010101"),
                volume=Decimal("100"), amount=None, eod_status="complete_eod",
                data_source="manual_file_import:licensed_source", provider_role="research_provider",
                fetched_at=datetime(2026, 8, 3, 17, tzinfo=timezone.utc), source_response_hash=f"{index:064d}",
            ))
        session.commit()
        bound = EnhancedReportService(session).bind_market_date(report, date(2026, 8, 3), True, "admin")
        assert bound.market_as_of_date == date(2026, 8, 3)


def test_enhanced_parse_keeps_66_persisted_paths_and_exposes_71_current_report_rows(enhanced_web) -> None:
    client, _ = enhanced_web
    login(client)
    report_id = create_report(client)
    result = client.post(f"/api/v1/admin/reports/{report_id}/enhance/parse").json()
    assert result["report_id"] == report_id
    assert result["enhanced_status"] == "ready"
    assert result["path_entry_count"] == 66
    assert result["external_llm_calls"] == 0
    matrix = client.get(f"/api/v1/reports/{report_id}/path-matrix").json()
    assert len(matrix["rows"]) == 71
    assert sum(row["market_available"] is False for row in matrix["rows"]) == 2
    hstech = next(row for row in matrix["rows"] if row["sector_key"] == "hang_seng_tech")
    assert hstech["cells"] == []  # draft is excluded from the published cross-period matrix


def test_not_mentioned_keeps_latest_explicit_view(enhanced_web) -> None:
    client, sessions = enhanced_web
    login(client)
    first = create_report(client, "2026-07-13")
    client.post(f"/api/v1/admin/reports/{first}/enhance/parse")
    client.post(f"/api/v1/admin/reports/{first}/ready")
    client.post(f"/api/v1/admin/reports/{first}/publish")
    second = create_report(client, "2026-07-19")
    client.post(f"/api/v1/admin/reports/{second}/enhance/parse")
    with sessions() as session:
        report = session.get(Report, second)
        assert report is not None
        metadata = json.loads(report.interpretation_meta_json)
        metadata["pdf_history_matrix"] = {
            "dates": ["7/01", "7/02", "7/03", "7/04", "7/05", "7/06", "7/07", "7/08", "7/13", "7/19"],
            "rows": [{"sector_key": "semiconductor", "statuses": ["watch"] * 9 + ["not_mentioned"]}],
        }
        report.interpretation_meta_json = json.dumps(metadata)
        session.add(SecurityProxyDaily(symbol="sz159995", trading_date=date(2026, 7, 10), close=Decimal("10"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"))
        session.add(SecurityProxyDaily(symbol="sz159995", trading_date=date(2026, 7, 13), close=Decimal("11"), open=None, high=None, low=None, amount_yuan=None, quote_datetime=None, fetched_at=datetime.now(timezone.utc), source="test"))
        session.commit()
    second_entries = client.get(f"/api/v1/reports/{second}/enhanced").json()["path_entries"]
    second_entry_id = next(item["id"] for item in second_entries if item["sector_key"] == "semiconductor")
    client.patch(f"/api/v1/admin/reports/{second}/path-entries/{second_entry_id}", json={"path_status": "not_mentioned", "explicitly_mentioned": False})
    matrix = client.get(f"/api/v1/reports/{second}/path-matrix").json()
    first_row = next(row for row in matrix["rows"] if row["sector_key"] == "semiconductor")
    entry_id = next(cell["id"] for cell in first_row["cells"] if cell["report_id"] == first)
    client.patch(f"/api/v1/admin/reports/{first}/path-entries/{entry_id}", json={"path_status": "hold", "explicitly_mentioned": True})
    client.post(f"/api/v1/admin/reports/{second}/ready")
    client.post(f"/api/v1/admin/reports/{second}/publish")
    research = client.get("/api/v1/sectors/semiconductor/research").json()
    assert research["latest_explicit_view"]["report_id"] == first
    assert research["latest_report_date"] == "2026-07-19"
    assert research["latest_report_explicitly_mentioned"] is False
    assert research["history"][0]["path"]["path_status"] == "not_mentioned"
    assert len(research["recent_path"]) == len(research["recent_path_entries"]) == 10
    assert sum(item["has_detailed_assessment"] for item in research["recent_path_entries"]) == 2


def test_same_status_restatement_refreshes_latest_board_and_detail_provenance(enhanced_web) -> None:
    client, sessions = enhanced_web
    login(client)

    def persist_semiconductor_fact(report_id: str, marker: str) -> None:
        with sessions() as session:
            entry = session.scalar(select(SectorPathEntry).where(
                SectorPathEntry.report_id == report_id,
                SectorPathEntry.sector_key == "semiconductor",
            ))
            assessment = session.scalar(select(SectorAssessment).where(
                SectorAssessment.report_id == report_id,
                SectorAssessment.sector_key == "semiconductor",
            ))
            assert entry is not None and assessment is not None
            entry.path_status = assessment.current_path_status = "strong_watch"
            entry.explicitly_mentioned = assessment.explicitly_mentioned = True
            entry.judgement_summary = assessment.current_judgement = "强观察"
            entry.source_text_reference = assessment.source_text_reference = f"{marker} explicit source"
            assessment.main_basis = f"{marker} main basis"
            assessment.observation_condition = f"{marker} observation condition"
            session.commit()

    first = create_report(client, "2026-08-25")
    client.post(f"/api/v1/admin/reports/{first}/enhance/parse")
    persist_semiconductor_fact(first, "D1")
    client.post(f"/api/v1/admin/reports/{first}/ready")
    client.post(f"/api/v1/admin/reports/{first}/publish")

    second = create_report(client, "2026-08-26")
    client.post(f"/api/v1/admin/reports/{second}/enhance/parse")
    persist_semiconductor_fact(second, "D2")
    client.post(f"/api/v1/admin/reports/{second}/ready")
    client.post(f"/api/v1/admin/reports/{second}/publish")

    latest = client.get(f"/api/v1/reports/{second}/enhanced").json()
    latest_fact = next(item for item in latest["sector_assessments"] if item["sector_key"] == "semiconductor")
    board = next(item for item in client.get("/api/v1/sectors").json() if item["sector_key"] == "semiconductor")
    detail = client.get("/api/v1/sectors/semiconductor/research").json()

    assert latest_fact["current_path_status"] == "strong_watch"
    assert board["latest_view_report_id"] == second
    assert board["latest_view_date"] == "2026-08-26"
    assert board["latest_explicit_view"]["report_id"] == second
    assert board["latest_explicit_view"]["assessment"]["main_basis"] == "D2 main basis"
    assert detail["latest_explicit_view"]["report_id"] == second
    assert detail["latest_explicit_view"]["assessment"]["main_basis"] == "D2 main basis"
    assert board["latest_explicit_view"]["assessment"] == detail["latest_explicit_view"]["assessment"]


def test_manual_refresh_requires_confirmation_and_excludes_hstech(enhanced_web) -> None:
    client, _ = enhanced_web
    login(client)
    denied = client.post("/api/v1/admin/market/refresh", json={"mode": "controlled_fixture"})
    assert denied.status_code == 409
    result = client.post("/api/v1/admin/market/refresh", json={"mode": "controlled_fixture", "confirmed_research_only": True}).json()
    assert result["requested_count"] == result["success_count"] == 65
    summary = client.get("/api/v1/admin/market/summary").json()
    assert summary["production_primary"] is None
    assert summary["automatic_scheduler"] is False
    assert client.get("/api/v1/sectors/hang_seng_tech/market/latest").json()["status"] == "unsupported"


def test_snapshot_is_idempotent_and_current_refresh_does_not_overwrite(enhanced_web) -> None:
    client, _ = enhanced_web
    login(client)
    report_id = create_report(client)
    client.post("/api/v1/admin/market/refresh", json={"mode": "controlled_fixture", "confirmed_research_only": True})
    client.post(f"/api/v1/admin/reports/{report_id}/market-binding", json={"market_as_of_date": "2026-07-17", "confirmed": True})
    first = client.post(f"/api/v1/admin/reports/{report_id}/market-snapshot").json()
    second = client.post(f"/api/v1/admin/reports/{report_id}/market-snapshot").json()
    assert first["snapshot_count"] == second["snapshot_count"] == 65
    before = client.get(f"/api/v1/reports/{report_id}/market-snapshots").json()
    client.post("/api/v1/admin/market/refresh", json={"mode": "controlled_fixture", "confirmed_research_only": True})
    assert client.get(f"/api/v1/reports/{report_id}/market-snapshots").json() == before


def test_one_click_publish_freezes_available_market_snapshot(enhanced_web) -> None:
    client, _ = enhanced_web
    login(client)
    report_id = create_report(client)
    client.post("/api/v1/admin/market/refresh", json={"mode": "controlled_fixture", "confirmed_research_only": True})
    client.post(f"/api/v1/admin/reports/{report_id}/market-binding", json={"market_as_of_date": "2026-07-17", "confirmed": True})
    published = client.post(f"/api/v1/admin/reports/{report_id}/publish")
    assert published.status_code == 200
    assert len(client.get(f"/api/v1/reports/{report_id}/market-snapshots").json()) == 65


def test_viewer_only_reads_published_enhanced_report(enhanced_web) -> None:
    client, _ = enhanced_web
    login(client)
    report_id = create_report(client)
    client.post(f"/api/v1/admin/reports/{report_id}/enhance/parse")
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    assert client.get(f"/api/v1/reports/{report_id}/enhanced").status_code == 404
