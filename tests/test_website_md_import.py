from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import (
    PathHistoryImport,
    Report,
    ReportDay,
    ReportFile,
    SectorAssessment,
    SectorPathEntry,
    SectorPathHistoryEntry,
)
from leopard_project.web.services import WebDomainError
from leopard_project.web.website_md import parse_website_md


FIXTURES = Path(__file__).parent / "fixtures" / "website_md"
PDF = FIXTURES / "2026-09-01.pdf"
MD = FIXTURES / "2026-09-01.md"


def login(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "admin-test-password",
    })
    assert response.status_code == 200


def test_website_md_0901_fixture_validates_actual_registry_counts() -> None:
    document = parse_website_md(MD.read_bytes(), MD.name)
    assert document.validation_payload() == {
        "schema": "leopard-website-md",
        "schema_version": "1.0",
        "report_date": "2026-09-01",
        "display_row_count": 74,
        "active_object_count": 71,
        "updated_sector_count": 16,
        "unmentioned_sector_count": 55,
        "updated_plus_unmentioned": 71,
        "unknown_sector_count": 0,
        "duplicate_sector_count": 0,
        "validation_status": "valid",
    }
    assert (document.primary_line, document.previous_line) == (3920.0, 3924.47)
    assert "只认收盘" in document.defense["validation_condition"]
    semiconductor = next(item for item in document.sector_updates if item["sector"] == "半导体")
    assert semiconductor["qualification"] == "观察区"


def test_website_md_does_not_trust_declared_checks() -> None:
    payload = MD.read_text(encoding="utf-8").replace("updated_sector_count: 16\n  unmentioned_sector_count: 55", "updated_sector_count: 1\n  unmentioned_sector_count: 1")
    document = parse_website_md(payload.encode(), "report.md")
    assert document.validation_payload()["updated_plus_unmentioned"] == 71
    assert document.checks["updated_sector_count"] == 1


def test_website_md_rejects_duplicate_unknown_and_count_mismatch() -> None:
    original = MD.read_text(encoding="utf-8")
    with pytest.raises(WebDomainError, match="重复板块"):
        parse_website_md(original.replace('- "PCB"', '- "白酒"').encode(), "duplicate.md")
    with pytest.raises(WebDomainError, match="未知板块"):
        parse_website_md(original.replace('- "PCB"', '- "不存在板块"').encode(), "unknown.md")
    with pytest.raises(WebDomainError, match="active 对象数"):
        parse_website_md(original.replace("active_object_count: 71", "active_object_count: 70", 1).encode(), "count.md")


def test_full_0901_pdf_md_import_is_incremental_and_reader_ready(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'website-md.sqlite3'}"
    sessions = create_session_factory(database_url)
    settings = WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-website-md-session-32-characters",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
        auto_publish_uploads=True,
    )
    previous_pdf = settings.upload_dir / "published" / "2026-08-31" / "prior.pdf"
    previous_pdf.parent.mkdir(parents=True)
    previous_pdf.write_bytes(b"%PDF-1.4\n% prior\n%%EOF")
    with sessions() as session:
        previous = Report(
            id="previous0831",
            title="8月31日报告",
            report_date=date(2026, 8, 31),
            report_date_confirmed=True,
            report_date_confidence="high",
            interpretation_status="ready",
            enhanced_status="ready",
            status="published",
            is_current=True,
            core_view="此前观点",
            created_by="fixture",
            published_by="fixture",
            published_at=datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc),
        )
        previous.file = ReportFile(
            sha256="a" * 64,
            original_filename="prior.pdf",
            storage_filename="published/2026-08-31/prior.pdf",
            content_type="application/pdf",
            size_bytes=25,
        )
        session.add(previous)
        session.add(SectorPathHistoryEntry(
            sector_key="pcb",
            sector_name="PCB",
            path_report_date=date(2026, 8, 27),
            path_status="watch",
            source_report_id=previous.id,
            detail_report_id=None,
            source_pdf_sha256=previous.file.sha256,
            template_version="V3.0",
            source_kind="historical_consistency_reference",
        ))
        session.add(SectorPathHistoryEntry(
            sector_key="pcb",
            sector_name="PCB",
            path_report_date=date(2026, 8, 31),
            path_status="strong_watch",
            source_report_id=previous.id,
            detail_report_id=previous.id,
            source_pdf_sha256=previous.file.sha256,
            template_version="V3.0",
            source_kind="report_local_pdf",
        ))
        session.add(SectorPathEntry(
            report_id=previous.id,
            sector_key="pcb",
            sector_name="PCB",
            path_status="strong_watch",
            explicitly_mentioned=True,
            judgement_summary="上一期明确强观",
            source_text_reference="fixture",
            confidence="high",
            quality_status="verified_structure",
            review_status="confirmed",
        ))
        session.add(SectorAssessment(
            report_id=previous.id,
            sector_key="pcb",
            sector_name="PCB",
            current_path_status="strong_watch",
            explicitly_mentioned=True,
            current_judgement="上一期明确强观",
            main_basis="fixture",
            extraction_method="fixture",
            confidence="high",
            quality_status="verified_structure",
            review_status="confirmed",
        ))
        session.commit()

    with TestClient(create_app(settings, sessions)) as client:
        login(client)
        response = client.post("/api/v1/admin/reports/interpret", files={
            "file": (PDF.name, PDF.read_bytes(), "application/pdf"),
            "md_file": (MD.name, MD.read_bytes(), "text/markdown"),
        })
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["publication"] == "published"
        assert body["interpretation_error"] is None
        assert body["md_validation"]["updated_sector_count"] == 16
        assert body["md_validation"]["unmentioned_sector_count"] == 55
        report_id = body["report"]["id"]
        assert body["report"]["report_date"] == "2026-09-01"
        assert body["report"]["interpretation"]["source_kind"] == "website_md"
        assert body["report"]["interpretation"]["website_md"]["pdf_history_matrix_parsed"] is False

        enhanced = client.get(f"/api/v1/reports/{report_id}/enhanced").json()
        defense = enhanced["report_defense"]
        assert defense["defense_line_value"] == 3920
        assert defense["defense_line_source"] == "website_md"
        assert defense["stand_above_condition"]
        assert defense["break_below_condition"]
        assert "只认收盘" in defense["validation_conditions"]
        assessments = {item["sector_name"]: item for item in enhanced["sector_assessments"]}
        expected = {
            "白酒": "turn_hold",
            "电力": "turn_hold",
            "贵金属": "turn_weak",
            "半导体": "strong_watch",
            "CPO": "strong_watch",
            "算力租赁": "strong_watch",
            "商业航天": "strong_watch",
            "创新药": "watch",
        }
        assert {name: assessments[name]["current_path_status"] for name in expected} == expected

        sectors = client.get("/api/v1/sectors?include_low_attention=true").json()
        pcb = next(item for item in sectors if item["sector_key"] == "pcb")
        assert pcb["current_path_status"] == "not_mentioned"
        assert pcb["effective_status"] == "strong_watch"
        assert pcb["effective_source_report_date"] == "2026-08-31"

    with sessions() as session:
        rows = list(session.scalars(select(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.path_report_date == date(2026, 9, 1),
        )))
        assert len(rows) == 71
        assert {item.source_kind for item in rows} == {"website_md_incremental"}
        assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.path_report_date == date(2026, 8, 30),
        )) == 0
        marker = session.scalar(select(ReportDay).where(ReportDay.report_date == date(2026, 8, 30)))
        assert marker is not None and marker.state == "no_live"
        history_import = session.scalar(select(PathHistoryImport).where(PathHistoryImport.source_report_id == report_id))
        assert history_import is not None
        assert (history_import.date_count, history_import.sector_count, history_import.status) == (1, 71, "verified_incremental_md")
        report = session.get(Report, report_id)
        metadata = json.loads(report.interpretation_meta_json)
        assert "pdf_history_matrix" not in metadata
        assert metadata["website_md"]["structured_content"]["dynamic_topics"]


def test_pdf_md_date_mismatch_rejected_before_report_creation(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'mismatch.sqlite3'}"
    sessions = create_session_factory(database_url)
    settings = WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-website-md-session-32-characters",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
    )
    changed = MD.read_text(encoding="utf-8").replace('report_date: "2026-09-01"', 'report_date: "2026-09-02"', 1).encode()
    with TestClient(create_app(settings, sessions)) as client:
        login(client)
        response = client.post("/api/v1/admin/reports/interpret", files={
            "file": (PDF.name, PDF.read_bytes(), "application/pdf"),
            "md_file": ("mismatch.md", changed, "text/markdown"),
        })
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "pdf_md_report_date_mismatch"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Report)) == 0


def test_manual_publish_stages_the_same_incremental_md_history(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'manual-publish.sqlite3'}"
    sessions = create_session_factory(database_url)
    settings = WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-website-md-session-32-characters",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
        auto_publish_uploads=False,
    )
    with TestClient(create_app(settings, sessions)) as client:
        login(client)
        imported = client.post("/api/v1/admin/reports/interpret", files={
            "file": (PDF.name, PDF.read_bytes(), "application/pdf"),
            "md_file": (MD.name, MD.read_bytes(), "text/markdown"),
        })
        assert imported.status_code == 201
        assert imported.json()["publication"] == "needs_review"
        report_id = imported.json()["report"]["id"]
        published = client.post(f"/api/v1/admin/reports/{report_id}/publish")
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.source_report_id == report_id,
            SectorPathHistoryEntry.source_kind == "website_md_incremental",
        )) == 71

@pytest.mark.parametrize("value", ["bad", "-1", ".inf", ".nan", "true", "0"])
def test_invalid_defense_numbers(value):
    text = MD.read_text().replace("previous_line: 3924.47", f"previous_line: {value}")
    with pytest.raises(WebDomainError):
        parse_website_md(text.encode(), "test.md")


@pytest.mark.parametrize("primary,previous,rest,expected,status", [
    (3660, 3660, False, 3660, "continued"),
    (3650, 3660, False, 3650, "changed"),
    (None, None, True, 3660, "continued"),
    (None, None, False, 3660, "continued"),
])
def test_defense_inherits_published_history(tmp_path, primary, previous, rest, expected, status):
    from dataclasses import replace
    from leopard_project.web.website_md import WebsiteMdImportService
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'lines.sqlite3'}")
    with sessions() as session:
        old = Report(id="old", report_date=date(2026, 8, 31), status="published", is_current=True,
                     title="prior", created_by="test",
                     interpretation_meta_json=json.dumps({"defense_lines": {"primary_defense_line": 3660}}))
        session.add(old)
        session.commit()
        original = old.interpretation_meta_json
        document = parse_website_md(MD.read_bytes(), MD.name)
        document = replace(document, defense={**document.defense, "primary_line": primary, "previous_line": previous, "source_summary": "正式攻防线由3660下调至3650"},
                           calendar_markers=[{"date": "2026-09-01", "mark": "休"}] if rest else [])
        resolved = WebsiteMdImportService(session, None).resolve_defense(Report(id="new"), document)
        assert resolved.primary_line == expected
        assert resolved.previous_line == 3660
        assert resolved.defense["line_status"] == status
        assert old.interpretation_meta_json == original


def test_no_history_nullable_defense(tmp_path):
    from dataclasses import replace
    from leopard_project.web.website_md import WebsiteMdImportService
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    text = MD.read_text().replace("primary_line: 3920", "primary_line: null").replace("previous_line: 3924.47", "previous_line: null")
    document = parse_website_md(text.encode(), "empty.md")
    with sessions() as session:
        resolved = WebsiteMdImportService(session, None).resolve_defense(Report(id="new"), document)
        assert resolved.primary_line is None and resolved.previous_line is None
        assert resolved.defense["line_status"] == "unavailable"

@pytest.mark.parametrize("initial_failure", [False, True])
def test_retry_revision_and_published_conflict(tmp_path, monkeypatch, initial_failure):
    from leopard_project.web.website_md import WebsiteMdImportService
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'retry.sqlite3'}")
    settings = WebSettings(
        database_url=f"sqlite:///{tmp_path / 'retry.sqlite3'}", upload_dir=tmp_path / "uploads",
        session_secret="retry-test-session-32-characters-long", admin_username="admin",
        admin_password="admin-test-password", viewer_username="viewer",
        viewer_password="viewer-test-password", auto_publish_uploads=False,
    )
    original_apply = WebsiteMdImportService.apply
    def files(md=None):
        return {"file": (PDF.name, PDF.read_bytes(), "application/pdf"),
                "md_file": (MD.name, md or MD.read_bytes(), "text/markdown")}
    with TestClient(create_app(settings, sessions)) as client:
        login(client)
        if initial_failure:
            def fail(*args, **kwargs):
                raise WebDomainError("injected_failure", "injected failure", 422)
            monkeypatch.setattr(WebsiteMdImportService, "apply", fail)
            assert client.post("/api/v1/admin/reports/interpret", files=files()).status_code == 422
            with sessions() as session:
                pending = session.scalar(select(Report))
                assert pending.status == "uploaded"
                assert not json.loads(pending.interpretation_meta_json or "{}").get("website_md")
            monkeypatch.setattr(WebsiteMdImportService, "apply", original_apply)
        first = client.post("/api/v1/admin/reports/interpret", files=files())
        assert first.status_code == 201, first.text
        report_id = first.json()["report"]["id"]
        changed = MD.read_bytes() + b"\n<!-- formatting revision -->\n"
        refused = client.post("/api/v1/admin/reports/interpret", files=files(changed))
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "pending_md_revision_confirmation_required"
        revised = client.post("/api/v1/admin/reports/interpret", files=files(changed),
                              data={"confirm_md_revision": "true"})
        assert revised.status_code == 201, revised.text
        assert revised.json()["report"]["id"] == report_id
        assert client.post(f"/api/v1/admin/reports/{report_id}/publish").status_code == 200
        again = client.post("/api/v1/admin/reports/interpret", files=files(changed))
        assert again.status_code == 201, again.text
        assert again.json()["publication"] == "already_published"
        assert client.post("/api/v1/admin/reports/interpret", files=files(),
                           data={"confirm_md_revision": "true"}).status_code == 409
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Report)) == 1
        assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry)) == 71


def test_concurrent_zero_update_upload_and_publish_retry(tmp_path, monkeypatch):
    import re
    import yaml
    from concurrent.futures import ThreadPoolExecutor
    from leopard_project.web.website_md import WebsiteMdImportService
    text = MD.read_text()
    document = parse_website_md(text.encode(), MD.name)
    names = [item["sector"] for item in document.sector_updates] + document.unmentioned_sectors
    text = re.sub(r"sector_updates:\n.*?(?=\n```)", "sector_updates: []", text, flags=re.S)
    text = re.sub(r"unmentioned_sectors:\n.*?(?=\n```)",
                  yaml.safe_dump({"unmentioned_sectors": names}, allow_unicode=True).strip(), text, flags=re.S)
    assert len(parse_website_md(text.encode(), "zero.md").sector_updates) == 0
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'concurrent.sqlite3'}")
    settings = WebSettings(
        database_url=f"sqlite:///{tmp_path / 'concurrent.sqlite3'}", upload_dir=tmp_path / "uploads",
        session_secret="test-only-concurrent-session-32-characters", admin_username="admin",
        admin_password="admin-test-password", viewer_username="viewer",
        viewer_password="viewer-test-password", auto_publish_uploads=True,
    )
    with TestClient(create_app(settings, sessions)) as client:
        login(client)
        def upload():
            return client.post("/api/v1/admin/reports/interpret", files={
                "file": (PDF.name, PDF.read_bytes(), "application/pdf"),
                "md_file": ("zero.md", text.encode(), "text/markdown")})
        original = WebsiteMdImportService.stage_incremental_history
        def fail_after_history(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise WebDomainError("injected_history_failure", "retry", 409)
        monkeypatch.setattr(WebsiteMdImportService, "stage_incremental_history", fail_after_history)
        failed = upload()
        assert failed.json()["interpretation_error"]["code"] == "injected_history_failure"
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry)) == 0
        monkeypatch.setattr(WebsiteMdImportService, "stage_incremental_history", original)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: upload(), range(2)))
        assert all(result.status_code == 201 for result in results), [r.text for r in results]
        assert {r.json()["publication"] for r in results} == {"published", "already_published"}
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Report)) == 1
        rows = list(session.scalars(select(SectorPathHistoryEntry)))
        assert len(rows) == 71
        assert {row.path_status for row in rows} == {"not_mentioned"}


@pytest.mark.parametrize("summary,accepted", [
    ("11月9日主播在直播中明确新报3659点，替代11月8日继续沿用的3660点", True),
    ("正式攻防线由3660点调整为3659点", True),
    ("核心攻防线从3660下调至3659", True),
    ("主播明确公布新线3659点替代旧线3660点", True),
    ("主播明确新报3659点，取代原线3660点", True),
    ("明确宣布攻防线为3659.00点，替代原攻防线3660.0点", True),
    ("正式攻防线由3661点调整为3659点", False),
    ("正式攻防线由3660点调整为3658点", False),
    ("明确新报3659点，替代原3661点", False),
    ("明确新报3658点，替代原3660点", False),
    ("正式攻防线由13660点调整为3659点", False),
    ("正式攻防线由3660点调整为36590点", False),
    ("3659点是普通支撑位，原攻防线3660点", False),
    ("目标位由3660调整为3659", False),
    ("盘中最低3659点，最高3660点", False),
    ("明确新报目标位3659点，替代原3660点", False),
    ("明确新报3659点，替代原3660点作为盘中支撑", False),
    ("未明确新报3659点，替代原3660点", False),
    ("若正式攻防线由3660调整为3659，则等待确认", False),
    ("计划明确公布新线3659点替代旧线3660点", False),
    ("明确新报3659点", False),
    ("正式攻防线调整为3659点", False),
])
def test_formal_defense_change_evidence(tmp_path, summary, accepted):
    from dataclasses import replace
    from leopard_project.web.website_md import WebsiteMdImportService
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'evidence.sqlite3'}")
    with sessions() as session:
        prior = Report(id="prior", title="prior", created_by="test", status="published",
                       is_current=True, report_date=date(2026, 11, 8),
                       interpretation_meta_json=json.dumps({"defense_lines": {"primary_defense_line": 3660}}))
        session.add(prior)
        session.commit()
        original = prior.interpretation_meta_json
        document = parse_website_md(MD.read_bytes(), MD.name)
        document = replace(document, metadata={**document.metadata, "report_date": "2026-11-09"},
                           defense={**document.defense, "primary_line": 3659, "previous_line": 3660,
                                    "source_summary": summary})
        service = WebsiteMdImportService(session, None)
        if accepted:
            resolved = service.resolve_defense(Report(id="new"), document)
            assert (resolved.previous_line, resolved.primary_line) == (3660, 3659)
            assert resolved.defense["line_status"] == "changed"
            assert resolved.defense["source_summary"] == summary
            # Text cannot override the last published line.
            wrong = replace(document, defense={**document.defense, "previous_line": 3661})
            with pytest.raises(WebDomainError) as exc:
                service.resolve_defense(Report(id="new"), wrong)
            assert exc.value.code == "defense_previous_conflict"
        else:
            with pytest.raises(WebDomainError) as exc:
                service.resolve_defense(Report(id="new"), document)
            assert exc.value.code == "defense_change_evidence_required"
        assert prior.interpretation_meta_json == original
