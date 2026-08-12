from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.services import detect_report_date, parse_report_text


def pseudo_pdf(text: str) -> bytes:
    return f"%PDF-1.4\n%LEOPARD_TEXT_BEGIN\n{text}\n%LEOPARD_TEXT_END\n%%EOF".encode()


V23_TEXT = """V2.3
大盘猎豹 2026年7月22日直播总结
核心结论速览
核心定性：指数微红不能掩盖个股退潮，3902点以下继续防守。
行情结论：观察缩量阴跌是否延续，以及资源方向能否得到量价验证。
板块主线
半导体、白酒
五、次日验证与两个操作风险
第一个风险是只看指数颜色。第二个风险是追逐轮动高点。
六、板块历史路径图
七、7月22日板块观点详细汇总
B1. 继续持有
板块 历史路径（最近转折） 7/22 判断 主要依据 观察条件
白酒
7/12 观察 → 7/16 持有
持有
防守方向保持承接。
若资金明确离场则调整。
B2. 重点观察区
板块 历史路径（最近转折） 7/22 判断 主要依据 观察条件
半导体
7/13 离场 → 7/19 不碰
弱观
科技利好未形成承接。
下一交易日需放量修复才重新评估。
"""

# The compact pseudo-PDF intentionally omits the 66-row matrix. Tests that
# exercise the happy publication path therefore omit the matrix section label.
PUBLISHABLE_TEXT = V23_TEXT.replace("六、板块历史路径图\n", "")


@pytest.fixture()
def interpretation_web(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'interpretation.sqlite3'}"
    sessions = create_session_factory(database_url)
    settings = WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-interpretation-session-32-characters",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
    )
    with TestClient(create_app(settings, sessions)) as client:
        yield client, settings


def login(client: TestClient, role: str = "admin") -> None:
    response = client.post("/api/v1/auth/login", json={
        "username": role,
        "password": f"{role}-test-password",
    })
    assert response.status_code == 200


def test_upload_triggers_complete_interpretation_without_second_parse_request(interpretation_web) -> None:
    client, settings = interpretation_web
    login(client)
    response = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("大盘猎豹7月22日直播总结.pdf", pseudo_pdf(PUBLISHABLE_TEXT), "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    report = body["report"]
    interpretation = body["interpretation"]
    assert report["status"] == "ready_to_publish"
    assert report["interpretation_status"] == "ready"
    assert report["report_date"] == "2026-07-22"
    assert report["report_date_confidence"] == "high"
    assert report["core_view"]
    assert report["market_path"]
    assert report["risk_warning"]
    assert interpretation["path_entry_count"] == 66
    assert len(interpretation["mentioned_assessments"]) == 2
    assert interpretation["status_counts"]["not_mentioned"] == 64
    assert interpretation["external_llm_calls"] == 0
    assert interpretation["ocr_used"] is False
    assert interpretation["market_data_status"] == "not_bound"
    assert interpretation["quality_status"] == "verified_structure"
    assert interpretation["quality_summary"]["assessment_blocking"] == 0
    assert len(list(settings.upload_dir.rglob("*.pdf"))) == 1


def test_duplicate_upload_is_idempotent_and_keeps_one_report(interpretation_web) -> None:
    client, settings = interpretation_web
    login(client)
    files = {"file": ("大盘猎豹7月22日直播总结.pdf", pseudo_pdf(V23_TEXT), "application/pdf")}
    first = client.post("/api/v1/admin/reports/interpret", files=files).json()
    second = client.post("/api/v1/admin/reports/interpret", files=files).json()
    assert second["duplicate"] is True
    assert second["report"]["id"] == first["report"]["id"]
    assert len(client.get("/api/v1/admin/reports").json()) == 1
    assert len(list(settings.upload_dir.rglob("*.pdf"))) == 1


def test_same_date_different_file_creates_a_revision_without_overwrite(interpretation_web) -> None:
    client, settings = interpretation_web
    login(client)
    first = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("7月22日初版.pdf", pseudo_pdf(PUBLISHABLE_TEXT), "application/pdf")},
    ).json()["report"]
    corrected_text = PUBLISHABLE_TEXT.replace("防守方向保持承接。", "防守方向继续保持承接。")
    second = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("7月22日修正版.pdf", pseudo_pdf(corrected_text), "application/pdf")},
    ).json()["report"]
    assert first["revision_number"] == 1
    assert second["revision_number"] == 2
    assert second["replaces_report_id"] == first["id"]
    assert first["id"] != second["id"]
    assert len(client.get("/api/v1/admin/reports").json()) == 2
    assert len(list(settings.upload_dir.rglob("*.pdf"))) == 2


def test_date_detection_confidence_and_conflict_rules() -> None:
    high = detect_report_date("大盘猎豹 2026年7月22日直播总结", "summary.pdf")
    assert (high["value"].isoformat(), high["confidence"], high["source"]) == ("2026-07-22", "high", "pdf_title")
    medium = detect_report_date("本报告仅出现2026年7月内容", "summary-2026-07-22.pdf")
    assert medium["value"].isoformat() == "2026-07-22"
    assert medium["confidence"] == "medium"
    conflict = detect_report_date("大盘猎豹 2026年7月22日直播总结", "summary-2026-07-21.pdf")
    assert conflict["confidence"] == "low"
    assert conflict["conflict"] is True


def test_section_variants_confirmed_mapping_and_probable_attention() -> None:
    text = """大盘猎豹 2026年7月22日直播总结
一、核心观点：保持防守纪律。
二、指数路径：放量站稳后才确认进攻。
三、风险点：不要追逐轮动高点。
板块主线
半导体
可能板块：半导
"""
    fields, _, mentions, terms = parse_report_text(text, "report-id", "report.pdf")
    assert fields["core_view"] == "保持防守纪律。"
    assert fields["market_path"] == "放量站稳后才确认进攻。"
    assert fields["risk_warning"] == "不要追逐轮动高点。"
    assert [item.sector_name for item in mentions] == ["半导体"]
    assert mentions[0].extraction_status == "confirmed"
    assert terms[0].status == "probable"
    assert fields["interpretation_meta"]["mapping_summary"]["probable"] == 1
    assert any(item["kind"] == "probable" for item in fields["interpretation_meta"]["attention_items"])


def test_high_confidence_report_can_publish_without_market_snapshot(interpretation_web) -> None:
    client, _ = interpretation_web
    login(client)
    report = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("大盘猎豹7月22日直播总结.pdf", pseudo_pdf(PUBLISHABLE_TEXT), "application/pdf")},
    ).json()["report"]
    published = client.post(f"/api/v1/admin/reports/{report['id']}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    assert client.get(f"/api/v1/reports/{report['id']}").status_code == 200


def test_low_confidence_date_blocks_publish_until_user_confirmation(interpretation_web) -> None:
    client, _ = interpretation_web
    login(client)
    text = PUBLISHABLE_TEXT.replace("2026年7月22日", "直播日期待确认")
    report = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("summary.pdf", pseudo_pdf(text), "application/pdf")},
    ).json()["report"]
    assert report["report_date_confidence"] == "low"
    denied = client.post(f"/api/v1/admin/reports/{report['id']}/publish")
    assert denied.status_code == 409
    patched = client.patch(
        f"/api/v1/admin/reports/{report['id']}/interpretation",
        json={"report_date": "2026-07-22", "report_date_confirmed": True},
    ).json()
    assert patched["interpretation"]["attention_items"] == []
    assert client.post(f"/api/v1/admin/reports/{report['id']}/publish").status_code == 200


def test_admin_interpretation_is_not_available_to_viewer_drafts(interpretation_web) -> None:
    client, _ = interpretation_web
    login(client)
    report_id = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("summary.pdf", pseudo_pdf(V23_TEXT), "application/pdf")},
    ).json()["report"]["id"]
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    assert client.get(f"/api/v1/admin/reports/{report_id}/interpretation").status_code == 403
    assert client.get(f"/api/v1/reports/{report_id}").status_code == 404


def test_incomplete_declared_history_matrix_blocks_publish(interpretation_web) -> None:
    client, _ = interpretation_web
    login(client)
    result = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": ("incomplete-matrix.pdf", pseudo_pdf(V23_TEXT), "application/pdf")},
    ).json()
    assert result["interpretation"]["quality_summary"]["history_matrix"] == "needs_attention"
    assert any(item["kind"] == "history_matrix_quality" for item in result["interpretation"]["attention_items"])
    denied = client.post(f"/api/v1/admin/reports/{result['report']['id']}/publish")
    assert denied.status_code == 409
