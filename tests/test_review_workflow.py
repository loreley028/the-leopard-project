from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from leopard_project.web.database import create_session_factory
from leopard_project.web.models import AuditEvent, Report, ReportReviewIssue, SectorAssessment
from leopard_project.web.review_workflow import ReviewWorkflowService
from leopard_project.web.services import WebDomainError


def report_with_issues(session) -> Report:
    report = Report(
        title="review", created_by="admin", status="needs_review", interpretation_status="needs_attention",
        interpretation_meta_json=json.dumps({"quality_status": "needs_attention", "attention_items": [
            {"kind": "assessment_conflict", "severity": "warning", "sector_key": "computing_power_rental", "message": "PDF表达存在两个合理口径"},
            {"kind": "assessment_conflict", "severity": "warning", "sector_key": "tourism", "message": "请确认最终判断"},
        ]}),
    )
    session.add(report); session.flush()
    session.add_all([
        SectorAssessment(report_id=report.id, sector_key="computing_power_rental", sector_name="算力租赁", current_path_status="avoid", current_judgement="不碰", explicitly_mentioned=True),
        SectorAssessment(report_id=report.id, sector_key="tourism", sector_name="旅游", current_path_status="watch", current_judgement="观察", explicitly_mentioned=True),
    ])
    session.commit()
    return report


def test_review_summary_resolution_idempotency_and_manual_priority(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'review.sqlite3'}")
    with sessions() as session:
        report = report_with_issues(session)
        service = ReviewWorkflowService(session)
        first = service.payload(report, 66)
        assert first["workflow_status"] == "needs_review"
        assert first["summary"] == {"auto_confirmed": 64, "suggested_review": 2, "must_handle": 0, "handled": 0}
        keys = [item["issue_key"] for item in first["issues"]]
        assert keys == ["assessment_conflict:computing_power_rental", "assessment_conflict:tourism"]

        service.resolve(report, keys[0], "hold", "admin", source="manual_override")
        service.resolve(report, keys[0], "hold", "admin", source="manual_override")
        assert session.scalar(select(func.count()).select_from(ReportReviewIssue)) == 2
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "review_issue_resolved")) == 1
        assessment = session.scalar(select(SectorAssessment).where(SectorAssessment.sector_key == "computing_power_rental"))
        assert assessment and assessment.current_path_status == "hold"

        # A parser retry may restore diagnostics, but never overwrites the
        # already-persisted human final value or creates another issue row.
        metadata = json.loads(report.interpretation_meta_json)
        metadata["attention_items"].append({"kind": "assessment_conflict", "severity": "warning", "sector_key": "computing_power_rental", "message": "retry"})
        report.interpretation_meta_json = json.dumps(metadata)
        session.commit()
        retried = service.payload(report, 66)
        resolved = next(item for item in retried["issues"] if item["issue_key"] == keys[0])
        assert resolved["resolved"] is True and resolved["final_value"] == "hold"
        assert session.scalar(select(func.count()).select_from(ReportReviewIssue)) == 2

        service.bulk_accept(report, "admin")
        ready = service.payload(report, 66)
        assert ready["workflow_status"] == "ready_to_publish"
        assert ready["summary"]["suggested_review"] == 0
        assert next(item for item in ready["issues"] if item["issue_key"] == keys[0])["resolution_source"] == "manual_override"
        assert report.status == "ready_to_publish"


def test_blocking_issue_and_published_review_are_explicit(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'blocked.sqlite3'}")
    with sessions() as session:
        report = Report(
            title="blocked", created_by="admin", status="needs_review", interpretation_status="needs_attention",
            interpretation_meta_json=json.dumps({"quality_status": "blocking_parse_error", "attention_items": [
                {"kind": "report_date_conflict", "severity": "blocking", "field": "report_date", "message": "日期冲突"},
            ]}),
        )
        session.add(report); session.commit()
        service = ReviewWorkflowService(session)
        payload = service.payload(report, 66)
        assert payload["workflow_status"] == "blocked"
        assert payload["summary"]["must_handle"] == 1
        assert report.status == "blocked"
        issue = payload["issues"][0]
        service.resolve(report, issue["issue_key"], "2026-07-28", "admin", source="manual_override")
        assert report.status == "ready_to_publish"
        report.status = "published"; session.commit()
        with pytest.raises(WebDomainError, match="只读"):
            service.resolve(report, issue["issue_key"], "2026-07-27", "admin", source="manual_override")


def test_defense_conflict_review_exposes_semantic_options_and_pdf_evidence(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'defense.sqlite3'}")
    with sessions() as session:
        report = Report(
            title="defense", created_by="admin", status="needs_review", interpretation_status="needs_attention",
            interpretation_meta_json=json.dumps({"quality_status": "blocking_parse_error", "attention_items": [{
                "kind": "defense_line_conflict", "severity": "blocking", "field": "primary_defense_line",
                "message": "核心攻防线存在相互冲突的高置信PDF证据，请选择采用的核心线。",
                "suggested_value": 3878.83,
                "candidates": [
                    {"value": 3878.83, "role": "primary", "page": 1, "source_text": "核心成本线由3864.27继续上移至3878.83", "confidence": "high"},
                    {"value": 3864.27, "role": "primary", "page": 2, "source_text": "核心攻防线为3864.27", "confidence": "high"},
                ],
            }]}),
        )
        session.add(report); session.commit()
        issue = ReviewWorkflowService(session).payload(report, 66)["issues"][0]
        assert issue["severity"] == "required"
        assert issue["options"] == [3878.83, 3864.27]
        assert issue["evidence"]["candidates"][0]["page"] == 1
        assert "不会发布" in issue["evidence"]["impact"]
        service = ReviewWorkflowService(session)
        service.resolve(report, issue["issue_key"], 3864.27, "admin", source="manual_override")
        metadata = json.loads(report.interpretation_meta_json)
        assert metadata["defense_lines"]["primary_defense_line"] == 3864.27
        assert metadata["defense_lines"]["conflict"] is False
        assert metadata["defense_lines"]["manual_resolution"]["selected_primary_defense_line"] == 3864.27


def test_legacy_manual_confirmation_is_backfilled_once(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    with sessions() as session:
        report = Report(title="published", created_by="admin", published_by="admin", status="published", interpretation_status="ready", interpretation_meta_json="{}")
        session.add(report); session.flush()
        session.add(SectorAssessment(
            report_id=report.id, sector_key="computing_power_rental", sector_name="算力租赁",
            current_path_status="avoid", current_judgement="不碰", manually_modified=True,
            review_status="confirmed", quality_status="verified_structure", confidence="high",
            updated_at=datetime(2026, 7, 29, 3, 6, tzinfo=timezone.utc),
        ))
        session.commit()
        service = ReviewWorkflowService(session)
        first = service.payload(report, 66)
        second = service.payload(report, 66)
        assert first == second
        assert first["workflow_status"] == "published"
        assert first["summary"] == {"auto_confirmed": 65, "suggested_review": 0, "must_handle": 0, "handled": 1}
        issue = first["issues"][0]
        assert issue["issue_key"] == "assessment:computing_power_rental:current_path_status"
        assert issue["final_value"] == "avoid" and issue["resolved"] is True
        assert session.scalar(select(func.count()).select_from(ReportReviewIssue)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "review_issue_migrated")) == 1
