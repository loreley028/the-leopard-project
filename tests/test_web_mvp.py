from __future__ import annotations

import json
import warnings
from datetime import date
from pathlib import Path

import pytest
warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")

from starlette.testclient import TestClient
from sqlalchemy import func, select

from leopard_project.config import CONFIG_DIR
from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import ReportRevision, ReportStatus
from leopard_project.web.repository import ReportRepository
from leopard_project.web.schedule import ReportSchedulePolicy
from leopard_project.web.services import ReportService, UploadPolicy, WebDomainError, validate_pdf


FIXTURE = Path(__file__).parent / "fixtures/sample_report_fixture.pdf"


@pytest.fixture()
def web(tmp_path: Path):
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    settings = WebSettings(
        database_url=f"sqlite:///{tmp_path / 'web.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-session-secret-with-32-characters",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
    )
    with TestClient(create_app(settings, sessions)) as client:
        yield client, sessions, settings


def login(client: TestClient, role: str = "admin") -> None:
    response = client.post("/api/v1/auth/login", json={"username": role, "password": f"{role}-test-password"})
    assert response.status_code == 200


def upload(client: TestClient, name: str = "fixture.pdf"):
    payload = FIXTURE.read_bytes() + f"\n% fixture-variant: {name}\n".encode()
    return client.post("/api/v1/admin/reports", files={"file": (name, payload, "application/pdf")})


def minimal_renderable_pdf() -> bytes:
    """Build one blank, standards-compliant PDF page without a fixture dependency."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, item in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode())
        payload.extend(item + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(payload)


def complete_report(client: TestClient) -> str:
    response = upload(client)
    report_id = response.json()["report"]["id"]
    parsed = client.post(f"/api/v1/admin/reports/{report_id}/parse")
    assert parsed.status_code == 200
    confirmed = client.patch(f"/api/v1/admin/reports/{report_id}", json={"report_date": "2026-07-19", "report_date_confirmed": True})
    assert confirmed.status_code == 200
    assert client.post(f"/api/v1/admin/reports/{report_id}/ready").status_code == 200
    assert client.post(f"/api/v1/admin/reports/{report_id}/publish").status_code == 200
    return report_id


def test_pdf_type_header_size_and_path_validation() -> None:
    policy = UploadPolicy(max_file_size_bytes=20, allowed_mime_types=frozenset({"application/pdf"}), required_header=b"%PDF-")
    with pytest.raises(WebDomainError, match="Only application/pdf"):
        validate_pdf("bad.txt", "text/plain", b"hello", policy)
    with pytest.raises(WebDomainError, match="PDF header"):
        validate_pdf("bad.pdf", "application/pdf", b"hello", policy)
    with pytest.raises(WebDomainError, match="size limit"):
        validate_pdf("large.pdf", "application/pdf", b"%PDF-" + b"x" * 30, policy)
    with pytest.raises(WebDomainError, match="not safe"):
        validate_pdf("../escape.pdf", "application/pdf", b"%PDF-ok", policy)
    with pytest.raises(WebDomainError, match="not safe"):
        validate_pdf("..\\escape.pdf", "application/pdf", b"%PDF-ok", policy)


def test_auth_cookie_roles_and_no_registration(web) -> None:
    client, _, _ = web
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "viewer")
    assert client.get("/api/v1/auth/me").json()["role"] == "viewer"
    assert client.get("/api/v1/admin/reports").status_code == 403
    assert client.post("/api/v1/auth/register", json={}).status_code == 404
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_admin_upload_duplicate_and_safe_storage(web) -> None:
    client, _, settings = web
    login(client)
    first = upload(client)
    assert first.status_code == 201 and first.json()["duplicate"] is False
    second = upload(client)
    assert second.status_code == 201 and second.json()["duplicate"] is True
    files = list(settings.upload_dir.glob("*.pdf"))
    assert len(files) == 1
    assert files[0].name != "fixture.pdf"


def test_admin_upload_rejects_invalid_pdf_without_server_path(web) -> None:
    client, _, settings = web
    login(client)
    response = client.post("/api/v1/admin/reports", files={"file": ("bad.pdf", b"not pdf", "application/pdf")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_pdf_header"
    assert str(settings.upload_dir) not in response.text


def test_parse_auto_recognizes_high_confidence_report_date(web) -> None:
    client, _, _ = web
    login(client)
    report_id = upload(client).json()["report"]["id"]
    parsed = client.post(f"/api/v1/admin/reports/{report_id}/parse").json()
    assert parsed["status"] == "needs_review"
    assert parsed["candidate_report_date"] == "2026-07-19"
    assert parsed["report_date"] == "2026-07-19"
    assert parsed["report_date_confidence"] == "high"
    response = client.post(f"/api/v1/admin/reports/{report_id}/ready")
    assert response.status_code == 200
    assert client.get(f"/api/v1/reports/{report_id}/pdf").status_code == 404


def test_pdf_preview_is_page_images_and_only_download_is_attachment(web) -> None:
    client, _, _ = web
    login(client)
    uploaded = client.post(
        "/api/v1/admin/reports",
        files={"file": ("renderable.pdf", minimal_renderable_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    report_id = uploaded.json()["report"]["id"]
    preview = client.get(f"/api/v1/reports/{report_id}/pdf/preview")
    first_page = client.get(f"/api/v1/reports/{report_id}/pdf/preview/pages/1")
    download = client.get(f"/api/v1/reports/{report_id}/pdf/download")
    assert preview.status_code == 200
    assert preview.json()["render_mode"] == "server_memory_png"
    assert preview.json()["source_pdf_requested"] is False
    assert first_page.status_code == 200 and first_page.headers["content-type"] == "image/png"
    assert first_page.headers["content-disposition"] == "inline"
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")


def test_specification_backups_are_admin_versioned_and_parser_independent(web) -> None:
    client, _, settings = web
    login(client)
    first = client.post("/api/v1/admin/specifications", data={"specification_name": "直播总结制作规范", "version": "2.3"}, files={"file": ("spec.md", b"# local specification", "text/markdown")})
    assert first.status_code == 201
    first_id = first.json()["id"]
    duplicate = client.post("/api/v1/admin/specifications", data={"specification_name": "直播总结制作规范", "version": "2.3-copy"}, files={"file": ("spec.md", b"# local specification", "text/markdown")})
    assert duplicate.status_code == 201 and duplicate.json()["id"] == first_id
    second = client.post("/api/v1/admin/specifications", data={"specification_name": "直播总结制作规范", "version": "2.3.1"}, files={"file": ("spec.md", b"# next local specification", "text/markdown")})
    assert second.status_code == 201
    assert client.post(f"/api/v1/admin/specifications/{first_id}/set-current").status_code == 200
    items = client.get("/api/v1/admin/specifications").json()
    assert len(items) == 2 and next(item for item in items if item["id"] == first_id)["is_current"] is True
    download = client.get(f"/api/v1/admin/specifications/{first_id}/file")
    assert download.headers["content-disposition"].startswith("attachment;")
    assert (settings.upload_dir.parent / "specifications").exists()
    assert complete_report(client)
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    assert client.get("/api/v1/admin/specifications").status_code == 403


def test_state_machine_rejects_illegal_transition(web) -> None:
    client, sessions, settings = web
    login(client)
    report_id = upload(client).json()["report"]["id"]
    with sessions() as session:
        report = ReportRepository(session).by_id(report_id)
        assert report is not None
        with pytest.raises(WebDomainError, match="Cannot transition"):
            ReportService(ReportRepository(session), settings.upload_dir).transition(report, ReportStatus.PUBLISHED)


def test_end_to_end_publish_is_idempotent_and_viewer_only_sees_published(web) -> None:
    client, _, _ = web
    login(client)
    draft_id = upload(client, "draft.pdf").json()["report"]["id"]
    published_id = complete_report(client)
    assert client.post(f"/api/v1/admin/reports/{published_id}/publish").status_code == 200
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    reports = client.get("/api/v1/reports").json()
    assert [item["id"] for item in reports] == [published_id]
    assert reports[0]["published_at"] is not None
    assert reports[0]["published_at_display"].count(":") == 1
    assert reports[0]["status"] == "published"
    assert client.get("/api/v1/reports/latest").json()["change_summary"]["kind"] == "first_published_report"
    assert client.get(f"/api/v1/reports/{draft_id}").status_code == 404


def test_withdraw_removes_report_from_viewer(web) -> None:
    client, _, _ = web
    login(client)
    report_id = complete_report(client)
    response = client.post(f"/api/v1/admin/reports/{report_id}/withdraw", json={"reason": "测试撤回原因"})
    assert response.json()["status"] == "withdrawn"
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    assert client.get("/api/v1/reports").json() == []


def test_published_update_creates_revision(web) -> None:
    client, sessions, _ = web
    login(client)
    report_id = complete_report(client)
    assert client.patch(f"/api/v1/admin/reports/{report_id}", json={"title": "修订后的虚构标题"}).status_code == 200
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ReportRevision).where(ReportRevision.report_id == report_id)) == 1


def test_sector_catalog_and_hstech_dual_status(web) -> None:
    client, _, _ = web
    login(client)
    complete_report(client)
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    sectors = client.get("/api/v1/sectors").json()
    assert len(sectors) == 66
    assert sum(item["market_support_status"] == "supported" for item in sectors) == 65
    hstech = next(item for item in sectors if item["sector_key"] == "hang_seng_tech")
    assert hstech["latest_view"] is not None
    assert hstech["market_support_status"] == "unsupported"
    assert "港股跨市场" in hstech["market_status_detail"]


def test_sector_research_query_supports_filter_sort_and_pagination(web) -> None:
    client, _, _ = web
    login(client)
    complete_report(client)
    rows = client.get("/api/v1/sectors", params={"mentioned": "true", "sort": "status", "page": 1, "page_size": 5}).json()
    assert 1 <= len(rows) <= 5
    assert all(item["mentioned_in_latest_published"] for item in rows)
    searched = client.get("/api/v1/sectors", params={"search": "恒生科技"}).json()
    assert [item["sector_key"] for item in searched] == ["hang_seng_tech"]


def test_sector_timeline_uses_published_reports(web) -> None:
    client, _, _ = web
    login(client)
    complete_report(client)
    client.post("/api/v1/auth/logout")
    login(client, "viewer")
    detail = client.get("/api/v1/sectors/semiconductor").json()
    assert len(detail["timeline"]) == 1
    assert detail["timeline"][0]["report_date"] == "2026-07-19"


def test_unmapped_term_can_only_resolve_to_existing_sector(web) -> None:
    client, _, _ = web
    login(client)
    payload = FIXTURE.read_bytes().replace(b"%LEOPARD_TEXT_END", "未映射：量子小岛\n%LEOPARD_TEXT_END".encode())
    uploaded = client.post("/api/v1/admin/reports", files={"file": ("unmapped.pdf", payload, "application/pdf")}).json()
    report_id = uploaded["report"]["id"]
    parsed = client.post(f"/api/v1/admin/reports/{report_id}/parse").json()
    term_id = parsed["unmapped_terms"][0]["id"]
    assert client.post(f"/api/v1/admin/unmapped-terms/{term_id}/resolve", json={"sector_key": "not-a-sector"}).status_code == 404
    resolved = client.post(f"/api/v1/admin/unmapped-terms/{term_id}/resolve", json={"sector_key": "semiconductor"})
    assert resolved.json()["resolved_sector_key"] == "semiconductor"


def test_weekend_schedule_has_no_missing_alert() -> None:
    policy = ReportSchedulePolicy.load()
    assert policy.timezone == "Asia/Shanghai"
    assert policy.report_expected(date(2026, 7, 19)) is True  # Sunday
    assert policy.report_expected(date(2026, 7, 24)) is False  # Friday
    assert policy.report_expected(date(2026, 7, 25)) is False  # Saturday
    assert policy.missing_report_alert(date(2026, 7, 24)) is False
    assert policy.upload_time_is_report_date is False
    assert policy.report_date_requires_confirmation is False
    assert policy.report_date_confirmation_required_for == frozenset({"low", "conflict"})


def test_policy_forbids_external_ai_and_keeps_upload_local() -> None:
    policy = json.loads((CONFIG_DIR / "pdf_upload_policy_v1.json").read_text(encoding="utf-8"))
    assert policy["external_ai_enabled"] is False
    assert policy["external_links_followed"] is False
    assert policy["storage_directory"] == "var/uploads"


def test_parse_failed_retains_original_file(web) -> None:
    client, _, settings = web
    login(client)
    payload = b"%PDF-1.4\n%%EOF"
    response = client.post("/api/v1/admin/reports", files={"file": ("empty.pdf", payload, "application/pdf")})
    report_id = response.json()["report"]["id"]
    parsed = client.post(f"/api/v1/admin/reports/{report_id}/parse")
    assert parsed.status_code == 422
    report = client.get(f"/api/v1/admin/reports/{report_id}").json()
    assert report["status"] == "parse_failed"
    assert list(settings.upload_dir.glob("*.pdf"))


def test_cookie_is_http_only_and_strict(web) -> None:
    client, _, _ = web
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-test-password"})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
