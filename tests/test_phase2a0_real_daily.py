from __future__ import annotations

from datetime import date
from pathlib import Path

from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.catalog import add_catalog_entry, configured_catalog
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import active_holding_interval, effective_statuses
from leopard_project.web.services import compare_frozen_history


def client(tmp_path: Path, mode: str = "real_local") -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'real.sqlite3'}"
    app = create_app(
        WebSettings(
            database_url=database_url,
            upload_dir=tmp_path / "uploads",
            session_secret="test-only-real-local-session-secret",
            admin_username="admin",
            admin_password="admin-password",
            viewer_username="viewer",
            viewer_password="viewer-password",
            data_mode=mode,
        ),
        create_session_factory(database_url),
    )
    result = TestClient(app)
    assert result.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password"}).status_code == 200
    return result


def test_real_local_runtime_and_schedule_states(tmp_path: Path) -> None:
    web = client(tmp_path)
    runtime = web.get("/api/v1/runtime").json()
    assert runtime["data_mode"] == "real_local"
    assert runtime["environment"] == "real_local"
    assert runtime["build_commit"] == "unknown"
    days = web.get("/api/v1/admin/report-days?start=2026-07-24&end=2026-07-26").json()
    assert [item["state"] for item in days] == ["normally_no_report", "normally_no_report", "pending_upload"]
    assert web.post("/api/v1/admin/report-days/2026-07-24/skip", json={"reason": "确认无直播"}).json()["state"] == "skipped"
    assert web.delete("/api/v1/admin/report-days/2026-07-24/skip").status_code == 204


def test_real_local_rejects_fixture_refresh(tmp_path: Path) -> None:
    web = client(tmp_path)
    result = web.post("/api/v1/admin/market/refresh", json={"mode": "controlled_fixture", "confirmed_research_only": True})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "fixture_forbidden_in_real_local"


def test_effective_status_and_holding_interval_are_pure() -> None:
    assert effective_statuses(["turn_hold", "hold", "not_mentioned"]) == ["turn_hold", "hold", "hold"]
    history = [
        {"report_date": "2026-06-18", "reported_status": "turn_hold", "market": {"close": 100, "trade_date": "2026-06-18"}},
        {"report_date": "2026-07-23", "reported_status": "hold", "market": {"close": 112, "trade_date": "2026-07-23"}},
        {"report_date": "2026-07-26", "reported_status": "not_mentioned", "market": {"close": 112, "trade_date": "2026-07-23"}},
    ]
    result = active_holding_interval(history)
    assert result and result["return_pct"] == 12.0
    assert result["latest_report_not_mentioned"] is True
    assert active_holding_interval([*history, {"report_date": "2026-07-27", "reported_status": "watch", "market": {"close": 110}}]) is None


def test_catalog_version_can_add_67th_without_rewriting_old_version() -> None:
    current = configured_catalog()
    assert len(current["entries"]) == 66
    expanded = add_catalog_entry(current, {
        "sector_key": "future_sector",
        "display_name": "未来板块",
        "group_key": "待确认分组",
        "display_order": 67,
        "aliases": [],
        "support_status": "unsupported",
    }, new_version="v2.4", valid_from=date(2026, 8, 1))
    assert len(expanded["entries"]) == 67
    assert len(current["entries"]) == 66
    assert expanded["entries"][-1]["valid_from"] == "2026-08-01"


def test_frozen_history_accepts_append_and_reports_rewrite() -> None:
    frozen = {
        "dates": ["7/22", "7/23"],
        "rows": [{"sector_key": "insurance", "statuses": ["turn_weak", "hold"]}],
    }
    appended = {
        "dates": ["7/22", "7/23", "7/26"],
        "rows": [{"sector_key": "insurance", "statuses": ["turn_weak", "hold", "hold"]}],
    }
    matched = compare_frozen_history(frozen, appended, through="2026-07-23")
    assert matched["status"] == "matched_append_only"
    assert matched["appended_dates"] == ["7/26"]
    rewritten = {
        "dates": ["7/22", "7/23", "7/26"],
        "rows": [{"sector_key": "insurance", "statuses": ["avoid", "hold", "hold"]}],
    }
    changed = compare_frozen_history(frozen, rewritten, through="2026-07-23")
    assert changed["status"] == "frozen_history_changed"
    assert changed["differences"][0] == {
        "sector_key": "insurance",
        "date": "7/22",
        "before": "turn_weak",
        "after": "avoid",
        "reason": "status_changed",
    }
