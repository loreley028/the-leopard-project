from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from starlette.testclient import TestClient
from sqlalchemy import func, select

from leopard_project.config import load_seed_bundle
from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market, ProviderNativeClose
from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService, intraday_matches_complete_eod_scale
from leopard_project.web.intraday import IntradayRefreshCoordinator, calculate_intraday_ma5, calculate_provider_native_intraday_ma5, market_phase, market_session, provider_failure_contract, resolve_intraday_data_status
from leopard_project.web.models import (
    MarketRefreshItem,
    MarketRefreshRun,
    IntradayRefreshSession,
    MarketAutomationControl,
    Report,
    ReportFile,
    ReportSectorMarketSnapshot,
    SectorDailyBar,
    SectorIndicatorSnapshot,
    SectorIntradaySnapshot,
    SectorProviderNativeClose,
    SectorPathHistoryEntry,
)
from leopard_project.web.path_history import sync_path_history


DATES = [
    "6/09", "6/10", "6/11", "6/14", "6/15", "6/16", "6/17", "6/18", "6/21", "6/22", "6/23", "6/24",
    "6/25", "6/28", "6/29", "6/30", "7/01", "7/02", "7/05", "7/06", "7/07", "7/08", "7/09", "7/12",
    "7/13", "7/14", "7/15", "7/16", "7/19", "7/20", "7/21", "7/22", "7/23", "7/26",
]


def settings(tmp_path: Path) -> WebSettings:
    return WebSettings(
        database_url=f"sqlite:///{tmp_path / 'history.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        session_secret="history-intraday-session-secret-32-characters",
        admin_username="admin", admin_password="admin-test-password",
        viewer_username="viewer", viewer_password="viewer-test-password",
    )


def test_existing_sqlite_receives_only_additive_intraday_columns(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE sector_intraday_snapshots (id VARCHAR(32) PRIMARY KEY)")
    connection.execute("CREATE TABLE market_refresh_items (id VARCHAR(32) PRIMARY KEY)")
    connection.execute("INSERT INTO market_refresh_items (id) VALUES ('preserved')")
    connection.commit()
    connection.close()

    create_session_factory(f"sqlite:///{database}")
    create_session_factory(f"sqlite:///{database}")
    connection = sqlite3.connect(database)
    snapshot_columns = {row[1] for row in connection.execute("PRAGMA table_info(sector_intraday_snapshots)")}
    item_columns = {row[1] for row in connection.execute("PRAGMA table_info(market_refresh_items)")}
    assert {"provider_symbol", "lineage", "source_status", "freshness_status", "intraday_ma5", "intraday_vs_ma5", "native_history_status"} <= snapshot_columns
    assert {"provider", "provider_symbol", "lineage", "error_code", "error_message"} <= item_columns
    assert connection.execute("SELECT id FROM market_refresh_items").fetchall() == [("preserved",)]
    connection.close()


def add_report(session, report_date: date, *, full_matrix: bool) -> Report:
    bundle = load_seed_bundle()
    metadata = {"pdf_history_matrix": {"dates": DATES, "rows": [
        {"sector_key": sector.sector_key, "sector_name": sector.sector_name,
         "statuses": ["turn_hold" if index == 3 else "hold" if 3 < index < 12 else "strong_watch" if index == 12 else "not_mentioned" for index in range(len(DATES))]}
        for sector in bundle.sectors
    ]}} if full_matrix else {}
    report = Report(
        title=f"report-{report_date}", report_date=report_date, market_as_of_date=date(2026, 7, 24) if report_date == date(2026, 7, 26) else report_date,
        report_date_confirmed=True, market_as_of_date_confirmed=True, status="published", is_current=True,
        template_version="V2.3.1", interpretation_meta_json=json.dumps(metadata), created_by="admin", data_origin="real_upload",
    )
    report.file = ReportFile(
        sha256=f"{report_date:%Y%m%d}".ljust(64, "0"), original_filename=f"{report_date}.pdf",
        storage_filename=f"{report_date}.pdf", content_type="application/pdf", size_bytes=100,
    )
    session.add(report); session.flush()
    EnhancedReportService(session).ensure_structure(report)
    return report


def test_full_pdf_restores_34_periods_independent_of_two_detailed_reports(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'history.sqlite3'}")
    with sessions() as session:
        first = add_report(session, date(2026, 7, 23), full_matrix=False)
        latest = add_report(session, date(2026, 7, 26), full_matrix=True)
        result = sync_path_history(session, latest)
        assert result.date_count == 34
        assert result.sector_count == 66
        assert result.inserted_count == 34 * 66
        assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry)) == 34 * 66
        assert session.scalar(select(func.count(func.distinct(SectorPathHistoryEntry.path_report_date)))) == 34
        assert session.scalar(select(func.count()).select_from(Report)) == 2
        assert sync_path_history(session, latest).inserted_count == 0
        assert first.id != latest.id
    app = create_app(settings(tmp_path), sessions)
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewer-test-password"}).status_code == 200
        latest_id = client.get("/api/v1/reports/latest").json()["id"]
        assert len(client.get(f"/api/v1/reports/{latest_id}/path-matrix?periods=10").json()["dates"]) == 10
        assert len(client.get(f"/api/v1/reports/{latest_id}/path-matrix?periods=20").json()["dates"]) == 20
        assert len(client.get(f"/api/v1/reports/{latest_id}/path-matrix?periods=40").json()["dates"]) == 34
        matrix = client.get(f"/api/v1/reports/{latest_id}/path-matrix?periods=all").json()
        assert len(matrix["dates"]) == 34
        assert len(matrix["groups"]) == 8
        assert [item["group_order"] for item in matrix["groups"]] == list(range(1, 9))
        assert [item["group_order"] for item in matrix["rows"]] == sorted(item["group_order"] for item in matrix["rows"])
        assert all("overall_order" in item for item in matrix["rows"])
        sunday = matrix["dates"][-1]
        assert sunday["report_date"] == "2026-07-26"
        assert sunday["weekday"] == "周日"
        assert sunday["market_as_of_date"] == "2026-07-24"
        assert sunday["market_weekday"] == "周五"
        assert sum(item["has_detailed_report"] for item in matrix["dates"]) == 2
        history_only = matrix["rows"][0]["cells"][0]
        assert history_only["has_detailed_report"] is False
        broad = client.get("/api/v1/sectors/pcb/research?path_periods=60&market_days=20").json()
        assert broad["strict_holding_interval"] is None
        assert broad["broad_holding_interval"]["status"] == "market_insufficient"
        assert len(broad["recent_path_entries"]) == 34


def daily_bar(sector_key: str, day: date, close: Decimal = Decimal("101")) -> DailyBar:
    provider = "synthetic_intraday_provider"
    provider_symbol = f"native-{sector_key}"
    history_days = (date(2026, 7, 21), date(2026, 7, 22), date(2026, 7, 23), date(2026, 7, 24))
    history = tuple(ProviderNativeClose(
        provider=provider, provider_symbol=provider_symbol,
        trade_date=history_day, close=Decimal("100"),
        source_payload_hash=(f"native-{offset}" * 64)[:64], lineage="synthetic native history",
    ) for offset, history_day in enumerate(history_days))
    return DailyBar(
        symbol=sector_key, symbol_name=sector_key, market=Market.CN_A, trade_date=day,
        open=close, high=close, low=close, close=close, pre_close=Decimal("100"), change=close - 100,
        pct_change=(close / 100 - 1) * 100, volume=Decimal("1000"), amount=None, turnover_rate=None,
        liquidity_status=LiquidityStatus.PARTIAL, provider=provider,
        fetched_at=datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc), source_payload_hash=(sector_key * 64)[:64],
        data_status=DataStatus.NORMAL, provider_symbol=provider_symbol,
        provider_native_history=history, provider_native_history_status="complete",
    )


def test_intraday_is_one_server_cache_and_never_enters_eod_models(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'intraday.sqlite3'}")
    calls: list[str] = []
    now = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)
    coordinator = IntradayRefreshCoordinator(sessions, now=lambda: now, fetcher=lambda key, _mapping, _now: calls.append(key) or daily_bar(key, date(2026, 7, 27)), sleep=lambda _: None)
    coordinator.policy["request_spacing_seconds"] = 0
    assert coordinator.status()["session_status"] == "paused"
    result = coordinator.refresh_once()
    assert result["success_count"] == 65
    assert len(calls) == 65
    runtime_status = coordinator.status()
    assert runtime_status["intraday_trade_date"] == "2026-07-27"
    assert runtime_status["production_primary"] is None
    assert runtime_status["production_primary_approved"] is False
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SectorIntradaySnapshot)) == 65
        assert session.scalar(select(func.count()).select_from(SectorDailyBar)) == 0
        assert session.scalar(select(func.count()).select_from(SectorIndicatorSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(ReportSectorMarketSnapshot)) == 0
        cached = EnhancedReportService(session).latest_intraday("semiconductor")
        assert cached and cached["observed_at_iso"].endswith("+00:00")
        assert resolve_intraday_data_status(
            phase="intraday_open", snapshot=cached, latest_result="intraday_fresh",
            now=now, stale_after_minutes=10,
        ) == "intraday_fresh"
    app = create_app(settings(tmp_path), sessions)
    app.state.intraday_coordinator = coordinator
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewer-test-password"}).status_code == 200
        before = len(calls)
        for _ in range(10):
            assert client.get("/api/v1/market/intraday/sectors").status_code == 200
        assert len(calls) == before
        assert client.post("/api/v1/admin/market/intraday/start").status_code == 403
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-test-password"}).status_code == 200
        latest_run = next(item for item in client.get("/api/v1/admin/market/refresh-runs").json() if item["mode"] == "intraday_refresh")
        run_detail = client.get(f"/api/v1/admin/market/refresh-runs/{latest_run['run_id']}").json()
        assert run_detail["provider"] == "research_intraday_chain"
        assert run_detail["duration_ms"] is not None
        assert len(run_detail["items"]) == 65
        assert all(item["provider"] == "synthetic_intraday_provider" for item in run_detail["items"])
    restarted = IntradayRefreshCoordinator(sessions, now=lambda: now, fetcher=lambda key, mapping, observed: daily_bar(key, observed.date()))
    assert restarted.status()["session_status"] == "paused"


def test_intraday_ma5_uses_provider_native_history_and_never_formal_eod(tmp_path: Path) -> None:
    assert calculate_intraday_ma5(Decimal("110"), [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103")]) == (
        Decimal("103.2"), (Decimal("110") / Decimal("103.2") - 1) * 100,
    )
    assert calculate_intraday_ma5(Decimal("110"), [Decimal("100")] * 3) is None
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'intraday-ma5.sqlite3'}")
    with sessions() as session:
        for offset, close in enumerate((Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"))):
            day = date(2026, 7, 21 + offset)
            session.add(SectorDailyBar(
                sector_key="semiconductor", trade_date=day, open=close, high=close, low=close,
                close=close, pre_close=close - 1, daily_pct_change=Decimal("1"), volume=1000,
                amount=None, turnover_rate=None, liquidity_status="partial", eod_status="complete_eod",
                data_source="real_test", provider_role="research_provider", fetched_at=datetime.now(timezone.utc),
                source_response_hash=f"{offset}" * 64,
            ))
        session.commit()
    now = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)
    def native_bar(key: str, _mapping: object, _observed: datetime) -> DailyBar:
        if key != "semiconductor":
            return daily_bar(key, date(2026, 7, 27))
        provider = "synthetic_intraday_provider"
        symbol = "native-semiconductor"
        history = tuple(ProviderNativeClose(
            provider=provider, provider_symbol=symbol, trade_date=date(2026, 7, 21 + offset), close=close,
            source_payload_hash=f"{offset}" * 64, lineage="same provider and symbol",
        ) for offset, close in enumerate((Decimal("100"), Decimal("101"), Decimal("102"), Decimal("103"))))
        return DailyBar(
            symbol=symbol, symbol_name="半导体", market=Market.CN_A, trade_date=date(2026, 7, 27),
            open=Decimal("104"), high=Decimal("111"), low=Decimal("103"), close=Decimal("110"),
            pre_close=Decimal("103"), change=Decimal("7"), pct_change=Decimal("7") / Decimal("103") * 100,
            volume=Decimal("1000"), amount=None, turnover_rate=None, liquidity_status=LiquidityStatus.PARTIAL,
            provider=provider, provider_symbol=symbol, fetched_at=now, source_payload_hash="a" * 64,
            data_status=DataStatus.NORMAL, provider_native_history=history,
            provider_native_history_status="complete", lineage="synthetic current",
        )

    coordinator = IntradayRefreshCoordinator(
        sessions, now=lambda: now,
        fetcher=native_bar,
        sleep=lambda _: None,
    )
    assert coordinator.refresh_once()["success_count"] == 65
    with sessions() as session:
        snapshot = session.scalar(select(SectorIntradaySnapshot).where(SectorIntradaySnapshot.sector_key == "semiconductor"))
        assert snapshot and Decimal(str(snapshot.intraday_ma5)) == Decimal("103.2")
        assert Decimal(str(snapshot.intraday_vs_ma5)) == ((Decimal("110") / Decimal("103.2") - 1) * 100).quantize(Decimal("0.000001"))
        assert session.scalar(select(func.count()).select_from(SectorIndicatorSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(SectorProviderNativeClose)) == 65 * 4


def test_intraday_ma5_rejects_mixed_provider_symbol_and_scale() -> None:
    bar = daily_bar("semiconductor", date(2026, 7, 27), Decimal("101"))
    assert calculate_provider_native_intraday_ma5(bar) is not None
    mixed = bar.model_copy(update={"provider_native_history": tuple(
        item.model_copy(update={"provider": "other"}) for item in bar.provider_native_history
    )})
    assert calculate_provider_native_intraday_ma5(mixed) is None
    wrong_symbol = bar.model_copy(update={"provider_native_history": tuple(
        item.model_copy(update={"provider_symbol": "other"}) for item in bar.provider_native_history
    )})
    assert calculate_provider_native_intraday_ma5(wrong_symbol) is None
    wrong_scale = bar.model_copy(update={"pre_close": Decimal("1000")})
    assert calculate_provider_native_intraday_ma5(wrong_scale) is None
    missing = bar.model_copy(update={"provider_native_history": (), "provider_native_history_status": "provider_failed"})
    assert calculate_provider_native_intraday_ma5(missing) is None


def test_intraday_holding_reference_rejects_cross_provider_or_scale() -> None:
    formal = SectorDailyBar(
        sector_key="hotel_catering", trade_date=date(2026, 7, 28),
        open=Decimal("2580"), high=Decimal("2600"), low=Decimal("2570"), close=Decimal("2593"),
        pre_close=Decimal("2557"), daily_pct_change=Decimal("1.4"), volume=1000,
        amount=None, turnover_rate=None, liquidity_status="partial", eod_status="complete_eod",
        data_source="formal_ths", provider_role="research_provider",
        fetched_at=datetime.now(timezone.utc), source_response_hash="f" * 64,
    )
    mixed = {"provider": "eastmoney_board_spot", "index_value": 1025, "pre_close": 1000}
    wrong_scale = {"provider": "formal_ths", "index_value": 1025, "pre_close": 1000}
    compatible = {"provider": "formal_ths", "index_value": 2600, "pre_close": 2593}
    assert intraday_matches_complete_eod_scale(mixed, formal) is False
    assert intraday_matches_complete_eod_scale(wrong_scale, formal) is False
    assert intraday_matches_complete_eod_scale(compatible, formal) is True


def test_intraday_provider_io_does_not_hold_sqlite_write_transaction(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'intraday-nonblocking.sqlite3'}")
    now = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)
    wrote_during_fetch = False

    def fetch(key: str, _mapping: object, _observed: datetime) -> DailyBar:
        nonlocal wrote_during_fetch
        if not wrote_during_fetch:
            with sessions() as session:
                session.add(IntradayRefreshSession(
                    status="paused", refresh_interval_minutes=5,
                    provider_role="research_provider", started_by="concurrent_admin",
                ))
                session.commit()
            wrote_during_fetch = True
        return daily_bar(key, date(2026, 7, 27))

    result = IntradayRefreshCoordinator(sessions, now=lambda: now, fetcher=fetch, sleep=lambda _: None).refresh_once()
    assert result["success_count"] == 65
    assert wrote_during_fetch is True


def test_intraday_market_phases_and_cycle_overlap_fail_closed() -> None:
    trading = {date(2026, 7, 27)}
    zone = timezone.utc
    # Asia/Shanghai: 10:00, 12:00, 16:00.
    assert market_phase(datetime(2026, 7, 27, 2, 0, tzinfo=zone), trading_dates=trading) == "intraday_open"
    assert market_phase(datetime(2026, 7, 27, 4, 0, tzinfo=zone), trading_dates=trading) == "market_break"
    assert market_phase(datetime(2026, 7, 27, 8, 0, tzinfo=zone), trading_dates=trading) == "market_closed"
    assert market_phase(datetime(2026, 7, 26, 2, 0, tzinfo=zone), trading_dates=trading) == "market_closed"
    assert market_session(datetime(2026, 7, 27, 0, 0, tzinfo=zone), trading_dates=trading) == "pre_open"
    assert market_session(datetime(2026, 7, 27, 2, 0, tzinfo=zone), trading_dates=trading) == "open"
    assert market_session(datetime(2026, 7, 27, 4, 0, tzinfo=zone), trading_dates=trading) == "market_break"
    assert market_session(datetime(2026, 7, 27, 8, 0, tzinfo=zone), trading_dates=trading) == "closed"
    assert market_session(datetime(2026, 7, 26, 2, 0, tzinfo=zone), trading_dates=trading) == "non_trading_day"
    now = datetime(2026, 7, 27, 2, 0, tzinfo=zone)
    assert resolve_intraday_data_status(phase="intraday_open", snapshot=None, latest_result="provider_failed", now=now, stale_after_minutes=10) == "provider_failed"
    assert resolve_intraday_data_status(phase="market_break", snapshot=None, latest_result="provider_failed", now=now, stale_after_minutes=10) == "market_break"
    assert resolve_intraday_data_status(phase="market_closed", snapshot=None, latest_result="provider_failed", now=now, stale_after_minutes=10) == "market_closed"
    assert resolve_intraday_data_status(phase="intraday_open", snapshot=None, latest_result=None, now=now, stale_after_minutes=10, unsupported=True) == "unsupported"
    fresh = {"observed_at": (now - timedelta(minutes=4)).isoformat()}
    stale = {"observed_at": (now - timedelta(minutes=11)).isoformat()}
    assert resolve_intraday_data_status(phase="intraday_open", snapshot=fresh, latest_result="intraday_fresh", now=now, stale_after_minutes=10) == "intraday_fresh"
    assert resolve_intraday_data_status(phase="intraday_open", snapshot=stale, latest_result="intraday_fresh", now=now, stale_after_minutes=10) == "intraday_stale"


def test_admin_pause_persists_but_process_pause_and_market_break_do_not(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'pause.sqlite3'}")
    lunch = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)
    coordinator = IntradayRefreshCoordinator(sessions, now=lambda: lunch, fetcher=lambda key, mapping, observed: daily_bar(key, observed.date()))
    coordinator.start("admin")
    assert coordinator.status()["scheduler_registered"] is True
    assert coordinator.refresh_once()["status"] == "market_break"
    assert coordinator.enabled is True
    coordinator.pause("admin", persistent=True)
    assert coordinator.status()["admin_paused"] is True

    restarted = IntradayRefreshCoordinator(sessions, now=lambda: lunch, fetcher=lambda key, mapping, observed: daily_bar(key, observed.date()))
    restarted.start("system_auto_resume")
    assert restarted.enabled is False
    restarted.start("admin")
    assert restarted.status()["admin_paused"] is False
    restarted.shutdown()
    with sessions() as session:
        assert session.get(MarketAutomationControl, "intraday").admin_paused is False

    again = IntradayRefreshCoordinator(sessions, now=lambda: lunch, fetcher=lambda key, mapping, observed: daily_bar(key, observed.date()))
    again.start("system_auto_resume")
    assert again.enabled is True
    again.shutdown()


def test_strict_and_broad_holding_end_status_contracts_use_full_path_ledger(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'holding-contract.sqlite3'}")
    with sessions() as session:
        latest = add_report(session, date(2026, 7, 26), full_matrix=True)
        sync_path_history(session, latest)
        entries = list(session.scalars(select(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.sector_key == "pcb"
        ).order_by(SectorPathHistoryEntry.path_report_date)))
        assert len(entries) == 34

        for ending in ("strong_watch", "watch", "weak_watch", "turn_weak", "exit", "avoid"):
            for row in entries:
                row.path_status = "not_mentioned"
            entries[2].path_status = "turn_hold"
            entries[3].path_status = "hold"
            entries[4].path_status = "not_mentioned"
            entries[5].path_status = ending
            session.flush()
            result = EnhancedReportService(session).holding_intervals_for_sector("pcb")
            assert result["strict_holding_interval"] is None
            assert result["historical_strict_intervals"][0]["end_status"] == ending
            if ending == "strong_watch":
                assert result["broad_holding_interval"]["status"] == "market_insufficient"
                assert result["historical_broad_intervals"] == []
            else:
                assert result["broad_holding_interval"] is None
                assert result["historical_broad_intervals"][0]["end_status"] == ending

        for row in entries:
            row.path_status = "not_mentioned"
        entries[2].path_status = "turn_hold"
        entries[3].path_status = "hold"
        session.flush()
        active = EnhancedReportService(session).holding_intervals_for_sector("pcb")
        assert active["strict_holding_interval"]["latest_report_not_mentioned"] is True
        assert active["broad_holding_interval"]["latest_report_not_mentioned"] is True


def test_low_attention_filter_search_and_admin_pin(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'visibility.sqlite3'}")
    with sessions() as session:
        latest = add_report(session, date(2026, 7, 26), full_matrix=True)
        sync_path_history(session, latest)
        rows = list(session.scalars(select(SectorPathHistoryEntry).where(SectorPathHistoryEntry.sector_key == "pcb")))
        for row in rows:
            row.path_status = "not_mentioned"
        session.commit()
    app = create_app(settings(tmp_path), sessions)
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewer-test-password"}).status_code == 200
        default_rows = client.get("/api/v1/sectors").json()
        all_rows = client.get("/api/v1/sectors?include_low_attention=true").json()
        search_rows = client.get("/api/v1/sectors?search=PCB").json()
        assert len(all_rows) == 66
        assert [item["group_order"] for item in all_rows] == sorted(item["group_order"] for item in all_rows)
        assert all(item["attention_level"] in {"high", "normal", "low"} for item in all_rows)
        assert not any(item["sector_key"] == "pcb" for item in default_rows)
        assert next(item for item in all_rows if item["sector_key"] == "pcb")["is_low_attention"] is True
        assert [item["sector_key"] for item in search_rows] == ["pcb"]
        assert client.get("/api/v1/sectors/pcb").status_code == 200
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-test-password"}).status_code == 200
        assert client.post("/api/v1/admin/sectors/pcb/pin").json()["is_pinned_for_research"] is True
        assert any(item["sector_key"] == "pcb" for item in client.get("/api/v1/sectors").json())
        assert client.delete("/api/v1/admin/sectors/pcb/pin").status_code == 204


def test_intraday_break_close_and_overlap_never_request_provider(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'intraday-gates.sqlite3'}")
    calls: list[str] = []

    for now, expected in (
        (datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc), "pre_open"),
        (datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc), "market_break"),
        (datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc), "market_closed"),
        (datetime(2026, 7, 26, 2, 0, tzinfo=timezone.utc), "non_trading_day"),
    ):
        coordinator = IntradayRefreshCoordinator(
            sessions,
            now=lambda now=now: now,
            fetcher=lambda key, _mapping, _observed: calls.append(key) or daily_bar(key, now.date()),
            sleep=lambda _: None,
        )
        result = coordinator.refresh_once()
        assert result == {
            "status": expected,
            "provider_requests": 0,
            "trade_date": now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        }

    coordinator = IntradayRefreshCoordinator(sessions, now=lambda: datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc))
    coordinator._running_cycle = True
    assert coordinator.refresh_once() == {"status": "cycle_already_running", "provider_requests": 0}
    assert calls == []


def test_provider_failure_preserves_last_intraday_snapshot_without_zeroing(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'intraday-fallback.sqlite3'}")
    now = datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc)
    successful = IntradayRefreshCoordinator(
        sessions,
        now=lambda: now,
        fetcher=lambda key, _mapping, _observed: daily_bar(key, date(2026, 7, 27)),
        sleep=lambda _: None,
    )
    successful.policy["request_spacing_seconds"] = 0
    assert successful.refresh_once()["success_count"] == 65

    failed = IntradayRefreshCoordinator(
        sessions,
        now=lambda: now,
        fetcher=lambda _key, _mapping, _observed: (_ for _ in ()).throw(TimeoutError("synthetic timeout")),
        sleep=lambda _: None,
    )
    failed.policy["request_spacing_seconds"] = 0
    result = failed.refresh_once()
    assert result["failure_count"] == 65
    with sessions() as session:
        snapshots = list(session.scalars(select(SectorIntradaySnapshot)))
        assert len(snapshots) == 65
        assert all(item.index_value == Decimal("101") for item in snapshots)
        assert all(item.data_status == "intraday_fresh" for item in snapshots)
        latest_run = session.get(MarketRefreshRun, result["run_id"])
        assert latest_run and latest_run.failure_count == 65
        items = list(session.scalars(select(MarketRefreshItem).where(MarketRefreshItem.run_id == latest_run.id)))
        assert len(items) == 65
        assert all(item.status == "provider_failed" for item in items)
        assert all(item.error_code == "timeout" for item in items)
        assert all(item.error_message == "Provider request timed out" for item in items)
        assert all("synthetic timeout" not in item.error_message for item in items)


def test_provider_failure_contract_does_not_expose_arbitrary_exception_text() -> None:
    assert provider_failure_contract(RuntimeError("token=must-not-leak")) == (
        "provider_error", "Provider request failed",
    )
