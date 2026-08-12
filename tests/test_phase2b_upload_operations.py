from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.services import parse_report_text


def pseudo_pdf(text: str) -> bytes:
    return f"%PDF-1.4\n%LEOPARD_TEXT_BEGIN\n{text}\n%LEOPARD_TEXT_END\n%%EOF".encode()


def report_text(day: str, version: str, freeze: str, primary: str, secondary: str) -> str:
    year, month, calendar_day = day.split("-")
    chinese_day = f"{year}年{int(month)}月{int(calendar_day)}日"
    return f"""大盘猎豹 {chinese_day}直播总结 {version}
历史冻结至{freeze}，仅新增{day[5:].replace('-', '/')}。
核心结论：严格校验后的最终报告。
行情结论：核心攻防线：{primary}；次攻防线：{secondary}。
板块主线
半导体
"""


@pytest.fixture()
def automatic_web(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'automatic.sqlite3'}"
    settings = WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-phase2b-session-secret-at-least-32",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
        auto_publish_uploads=True,
    )
    with TestClient(create_app(settings, create_session_factory(database_url))) as client:
        assert client.post("/api/v1/auth/admin/login", json={"username": "admin", "password": "admin-test-password"}).status_code == 200
        yield client, settings


def upload(client: TestClient, filename: str, text: str):
    return client.post("/api/v1/admin/reports/interpret", files={"file": (filename, pseudo_pdf(text), "application/pdf")})


def test_v29_0810_contract_is_metadata_not_date_specific() -> None:
    fields, *_ = parse_report_text(
        report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09"),
        "v29-contract",
    )
    metadata = fields["interpretation_meta"]
    assert fields["candidate_report_date"].isoformat() == "2026-08-10"
    assert metadata["template_version"] == "V2.9"
    assert metadata["history_freeze"]["through"] == "2026-08-09"
    assert metadata["defense_lines"] == {"primary_defense_line": 3864.27, "secondary_defense_line": 3847.09}
    assert metadata["matrix_statistics"] == {"display_rows": None, "active_objects": None}


def test_v29_0811_matrix_statistics_contract_is_not_hardcoded() -> None:
    fields, *_ = parse_report_text(
        report_text("2026-08-11", "V2.9", "2026-08-10", "3878.83", "3864.27")
        + "\ndisplay_rows: 74\nactive_objects: 71\n",
        "v29-0811-matrix-contract",
    )
    metadata = fields["interpretation_meta"]
    assert fields["candidate_report_date"].isoformat() == "2026-08-11"
    assert metadata["history_freeze"]["through"] == "2026-08-10"
    assert metadata["defense_lines"] == {"primary_defense_line": 3878.83, "secondary_defense_line": 3864.27}
    assert metadata["matrix_statistics"] == {"display_rows": 74, "active_objects": 71}


def test_v28_and_v29_version_metadata_are_compatible() -> None:
    for version in ("V2.8", "V2.9"):
        fields, *_ = parse_report_text(report_text("2026-08-11", version, "2026-08-10", "3878.83", "3864.27"), version)
        assert fields["interpretation_meta"]["template_version"] == version
        assert fields["interpretation_meta"]["history_freeze"]["through"] == "2026-08-10"


def test_final_upload_publishes_automatically_and_duplicate_is_idempotent(automatic_web) -> None:
    client, settings = automatic_web
    payload = report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09")
    first = upload(client, "final-0810.pdf", payload)
    assert first.status_code == 201
    body = first.json()
    assert body["publication"] == "published"
    assert body["report"]["status"] == "published"
    assert len(list(settings.upload_dir.rglob("*.pdf"))) == 1
    assert len(list((settings.upload_dir / "published").glob("*.pdf"))) == 1
    assert not list((settings.upload_dir / ".staging").glob("*.pdf"))
    duplicate = upload(client, "final-0810.pdf", payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["publication"] == "already_published"
    assert duplicate.json()["report"]["id"] == body["report"]["id"]
    assert len(client.get("/api/v1/admin/reports").json()) == 1


def test_same_date_different_pdf_is_blocked_without_changing_latest(automatic_web) -> None:
    client, settings = automatic_web
    first = upload(client, "final-0810.pdf", report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09"))
    assert first.status_code == 201
    conflict = upload(client, "replacement-0810.pdf", report_text("2026-08-10", "V2.9", "2026-08-09", "3865.27", "3847.09"))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "report_date_conflict"
    latest = client.get("/api/v1/reports/latest").json()
    assert latest["id"] == first.json()["report"]["id"]
    assert len(list((settings.upload_dir / "published").glob("*.pdf"))) == 1
    assert len(list((settings.upload_dir / ".staging").glob("*.pdf"))) == 1


def test_automatic_publish_stops_for_incomplete_or_ambiguous_input(automatic_web) -> None:
    client, _ = automatic_web
    incomplete = "大盘猎豹 2026年8月10日直播总结 V2.9\n板块历史路径图\n"
    response = upload(client, "incomplete.pdf", incomplete)
    assert response.status_code == 201
    assert response.json()["publication"] == "needs_review"
    assert response.json()["report"]["status"] != "published"


def test_operations_status_is_read_only_and_has_empty_state(automatic_web) -> None:
    client, _ = automatic_web
    response = client.get("/api/v1/admin/operations/status")
    assert response.status_code == 200
    assert response.json()["latest_published_report_date"] is None
    assert response.json()["latest_live_market_anchor_eod_date"] is None
    assert response.json()["latest_security_proxy_eod_date"] is None
    assert response.json()["capture_mode"] == "host_systemd_timer"
