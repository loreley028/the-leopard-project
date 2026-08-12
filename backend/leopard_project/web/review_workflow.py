from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enhanced import path_statuses
from .models import AuditEvent, Report, ReportReviewIssue, ReportStatus, SectorAssessment
from .services import WebDomainError


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _value(raw: str | None) -> Any:
    return None if raw is None else json.loads(raw)


def _issue_key(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "review")
    subject = str(item.get("sector_key") or item.get("field") or item.get("term") or "report")
    return f"{kind}:{subject}"


def _severity(item: dict[str, Any]) -> str:
    return "required" if item.get("severity") == "blocking" else "suggestion"


class ReviewWorkflowService:
    """Persist the small set of human decisions separately from parser diagnostics."""

    def __init__(self, session: Session):
        self.session = session

    def sync(self, report: Report) -> list[ReportReviewIssue]:
        existing = {
            item.issue_key: item
            for item in self.session.scalars(
                select(ReportReviewIssue).where(ReportReviewIssue.report_id == report.id)
            )
        }
        metadata = json.loads(report.interpretation_meta_json or "{}")
        assessments = {
            item.sector_key: item
            for item in self.session.scalars(
                select(SectorAssessment).where(SectorAssessment.report_id == report.id)
            )
        }

        for attention in metadata.get("attention_items", []):
            key = _issue_key(attention)
            assessment = assessments.get(attention.get("sector_key"))
            suggested = assessment.current_path_status if assessment else attention.get("suggested_value")
            if suggested is None and str(attention.get("kind", "")).startswith("report_date"):
                suggested = (report.report_date or report.candidate_report_date)
                suggested = suggested.isoformat() if suggested else None
            if key in existing:
                issue = existing[key]
                if issue.resolved_at is None:
                    issue.explanation = attention.get("message") or issue.explanation
                    issue.evidence_json = _json(self._evidence(attention, assessment))
                continue
            options = list(path_statuses()) if assessment else self._options(attention, suggested)
            issue = ReportReviewIssue(
                report_id=report.id,
                issue_key=key,
                issue_type=str(attention.get("kind") or "review"),
                severity=_severity(attention),
                subject_key=assessment.sector_key if assessment else attention.get("field"),
                subject_label=assessment.sector_name if assessment else self._subject_label(attention),
                explanation=attention.get("message") or "系统已给出建议，请确认最终采用值。",
                original_value_json=_json(suggested),
                suggested_value_json=_json(suggested),
                options_json=_json(options),
                evidence_json=_json(self._evidence(attention, assessment)),
            )
            self.session.add(issue)
            existing[key] = issue

        if report.report_date_confirmed_by_user or report.report_date_confirmed:
            for issue in existing.values():
                if issue.resolved_at is None and issue.issue_type in {"report_date", "report_date_conflict"}:
                    now = datetime.now(timezone.utc)
                    issue.final_value_json = _json(report.report_date.isoformat() if report.report_date else None)
                    issue.resolution_source = "manual_override"
                    issue.resolved_at = now
                    issue.resolved_by = report.created_by
                    issue.updated_at = now
                    self.session.add(AuditEvent(
                        actor=report.created_by,
                        action="review_issue_resolved",
                        entity_type="report_review_issue",
                        entity_id=issue.issue_key,
                        details_json=_json({"report_id": report.id, "resolution_source": "manual_override", "confirmed_report_date": True}),
                    ))

        # Preserve decisions made by the old advanced workbench. This additive
        # backfill is intentionally one row per stable sector key and never
        # rewrites a later persisted human decision.
        for assessment in assessments.values():
            if not assessment.manually_modified or report.status != ReportStatus.PUBLISHED.value:
                continue
            key = f"assessment:{assessment.sector_key}:current_path_status"
            if key in existing:
                continue
            value = assessment.current_path_status
            issue = ReportReviewIssue(
                report_id=report.id,
                issue_key=key,
                issue_type="assessment_confirmation",
                severity="suggestion",
                subject_key=assessment.sector_key,
                subject_label=assessment.sector_name,
                explanation="该板块曾需要人工确认，已保留此前采用的最终判断。",
                original_value_json=_json(value),
                suggested_value_json=_json(value),
                options_json=_json(list(path_statuses())),
                evidence_json=_json(self._evidence({}, assessment)),
                final_value_json=_json(value),
                resolution_source="manual_override",
                resolved_at=assessment.updated_at,
                resolved_by=report.published_by or report.created_by,
            )
            self.session.add(issue)
            existing[key] = issue
            self.session.add(AuditEvent(
                actor=issue.resolved_by or "legacy_admin",
                action="review_issue_migrated",
                entity_type="report_review_issue",
                entity_id=key,
                details_json=_json({"report_id": report.id, "preserved_manual_decision": True}),
            ))

        self.session.flush()
        issues = list(self.session.scalars(
            select(ReportReviewIssue)
            .where(ReportReviewIssue.report_id == report.id)
            .order_by(ReportReviewIssue.created_at, ReportReviewIssue.issue_key)
        ))
        self._apply_report_state(report, issues)
        self.session.commit()
        return issues

    def resolve(
        self, report: Report, issue_key: str, final_value: Any, actor: str,
        *, source: str, note: str = "",
    ) -> ReportReviewIssue:
        if report.status == ReportStatus.PUBLISHED.value:
            raise WebDomainError("published_review_read_only", "已发布报告的确认记录为只读留痕", 409)
        issues = self.sync(report)
        issue = next((item for item in issues if item.issue_key == issue_key), None)
        if issue is None:
            raise WebDomainError("review_issue_not_found", "待确认问题不存在", 404)
        if source not in {"accepted_suggestion", "manual_override", "bulk_accept"}:
            raise WebDomainError("invalid_resolution_source", "确认来源无效", 422)
        encoded = _json(final_value)
        if issue.final_value_json == encoded and issue.resolution_source == source:
            return issue

        if issue.subject_key:
            assessment = self.session.scalar(select(SectorAssessment).where(
                SectorAssessment.report_id == report.id,
                SectorAssessment.sector_key == issue.subject_key,
            ))
            if assessment is not None and final_value in path_statuses():
                assessment.current_path_status = str(final_value)
                assessment.current_judgement = path_statuses()[str(final_value)]["label"]
                assessment.review_status = "confirmed"
                assessment.manually_modified = source == "manual_override"
                assessment.quality_status = "verified_structure"
                assessment.confidence = "high"
                assessment.updated_at = datetime.now(timezone.utc)
        if issue.issue_type in {"report_date", "report_date_conflict"} and isinstance(final_value, str):
            try:
                report.report_date = date.fromisoformat(final_value)
                report.report_date_confirmed = True
                report.report_date_confirmed_by_user = True
                report.report_date_confidence = "high"
            except ValueError as exc:
                raise WebDomainError("invalid_report_date", "报告日期格式无效", 422) from exc

        metadata = json.loads(report.interpretation_meta_json or "{}")
        if issue.issue_type == "defense_line_conflict":
            try:
                selected_line = float(final_value)
            except (TypeError, ValueError) as exc:
                raise WebDomainError("invalid_defense_line", "核心攻防线必须是有效数值", 422) from exc
            allowed_lines: set[float] = set()
            for item in _value(issue.options_json) or []:
                try:
                    allowed_lines.add(float(item))
                except (TypeError, ValueError):
                    continue
            if selected_line not in allowed_lines:
                raise WebDomainError("invalid_defense_line", "只能选择PDF证据中列出的核心攻防线", 422)
            defense = metadata.setdefault("defense_lines", {})
            defense["primary_defense_line"] = selected_line
            defense["conflict"] = False
            defense["manual_resolution"] = {
                "selected_primary_defense_line": selected_line,
                "resolution_source": source,
            }

        now = datetime.now(timezone.utc)
        issue.final_value_json = encoded
        issue.resolution_source = source
        issue.resolved_at = now
        issue.resolved_by = actor
        issue.optional_note = note
        issue.updated_at = now
        metadata["attention_items"] = [
            item for item in metadata.get("attention_items", [])
            if _issue_key(item) != issue.issue_key
            and item.get("sector_key") != issue.subject_key
        ]
        metadata["quality_status"] = (
            "blocking_parse_error" if any(item.get("severity") == "blocking" for item in metadata["attention_items"])
            else "verified_structure"
        )
        report.interpretation_meta_json = _json(metadata)
        report.interpretation_status = "needs_attention" if metadata["attention_items"] else "ready"
        self.session.flush()
        current = list(self.session.scalars(select(ReportReviewIssue).where(ReportReviewIssue.report_id == report.id)))
        self._apply_report_state(report, current)
        self.session.add(AuditEvent(
            actor=actor,
            action="review_issue_resolved",
            entity_type="report_review_issue",
            entity_id=issue.issue_key,
            details_json=_json({"report_id": report.id, "resolution_source": source, "final_value": final_value}),
        ))
        self.session.commit()
        return issue

    def bulk_accept(self, report: Report, actor: str) -> list[ReportReviewIssue]:
        issues = self.sync(report)
        for issue in issues:
            if issue.resolved_at is None and issue.severity == "suggestion":
                self.resolve(report, issue.issue_key, _value(issue.suggested_value_json), actor, source="bulk_accept")
        return self.sync(report)

    def payload(self, report: Report, path_entry_count: int) -> dict[str, Any]:
        issues = self.sync(report)
        unresolved_suggestions = [item for item in issues if item.resolved_at is None and item.severity == "suggestion"]
        unresolved_required = [item for item in issues if item.resolved_at is None and item.severity == "required"]
        handled = [item for item in issues if item.resolved_at is not None]
        return {
            "workflow_status": self._workflow_status(report, issues),
            "summary": {
                "auto_confirmed": max(0, path_entry_count - len(issues)),
                "suggested_review": len(unresolved_suggestions),
                "must_handle": len(unresolved_required),
                "handled": len(handled),
            },
            "steps": [
                {"key": "upload", "label": "上传报告", "state": "complete"},
                {"key": "review", "label": "检查疑问", "state": "complete" if not unresolved_suggestions and not unresolved_required else "current"},
                {"key": "publish", "label": "发布报告", "state": "complete" if report.status == ReportStatus.PUBLISHED.value else "current" if not unresolved_suggestions and not unresolved_required else "pending"},
            ],
            "issues": [self.issue_payload(item) for item in issues],
        }

    @staticmethod
    def issue_payload(issue: ReportReviewIssue) -> dict[str, Any]:
        resolved_at = issue.resolved_at
        if resolved_at is not None and resolved_at.tzinfo is None:
            resolved_at = resolved_at.replace(tzinfo=timezone.utc)
        return {
            "issue_key": issue.issue_key,
            "issue_type": issue.issue_type,
            "severity": issue.severity,
            "subject_key": issue.subject_key,
            "subject_label": issue.subject_label,
            "explanation": issue.explanation,
            "original_value": _value(issue.original_value_json),
            "suggested_value": _value(issue.suggested_value_json),
            "options": _value(issue.options_json),
            "evidence": _value(issue.evidence_json),
            "resolved": issue.resolved_at is not None,
            "final_value": _value(issue.final_value_json),
            "resolution_source": issue.resolution_source,
            "resolved_at": resolved_at.isoformat() if resolved_at else None,
            "resolved_by": issue.resolved_by,
            "optional_note": issue.optional_note,
        }

    @staticmethod
    def _subject_label(item: dict[str, Any]) -> str:
        labels = {
            "report_date": "报告日期", "history_rewrite": "历史路径", "unmapped_alias": "板块名称",
            "defense_line_conflict": "核心攻防线", "defense_line_missing": "核心攻防线",
        }
        return labels.get(str(item.get("kind")), "报告内容")

    @staticmethod
    def _options(item: dict[str, Any], suggested: Any) -> list[Any]:
        values: list[Any] = []
        if suggested is not None:
            values.append(suggested)
        for candidate in item.get("candidates", []):
            value = candidate.get("value")
            if value is not None and value not in values:
                values.append(value)
        return values

    @staticmethod
    def _evidence(item: dict[str, Any], assessment: SectorAssessment | None) -> dict[str, Any]:
        if assessment is None:
            candidates = item.get("candidates") or []
            return {
                "page": item.get("source_page") or (candidates[0].get("page") if candidates else None),
                "excerpt": item.get("source_text_excerpt") or item.get("message"),
                "candidates": candidates,
                "current_database_value": item.get("current_database_value"),
                "impact": item.get("impact") or "未确认前不会发布，也不会覆盖既有历史。",
                "technical_codes": item.get("validation_flags") or [],
            }
        return {
            "page": assessment.source_page,
            "excerpt": assessment.source_text_excerpt or assessment.source_text_reference,
            "source_reference": assessment.source_text_reference,
            "extraction_method": assessment.extraction_method,
            "confidence": assessment.confidence,
            "technical_codes": json.loads(assessment.validation_flags_json or "[]"),
        }

    @staticmethod
    def _workflow_status(report: Report, issues: list[ReportReviewIssue]) -> str:
        if report.status == ReportStatus.PUBLISHED.value:
            return "published"
        if report.status == ReportStatus.PARSE_FAILED.value or report.interpretation_status == "failed":
            return "failed"
        if report.status == ReportStatus.PARSING.value or report.interpretation_status in {"uploading", "interpreting"}:
            return "parsing"
        if any(item.resolved_at is None and item.severity == "required" for item in issues):
            return "blocked"
        if any(item.resolved_at is None for item in issues):
            return "needs_review"
        return "ready_to_publish"

    def _apply_report_state(self, report: Report, issues: list[ReportReviewIssue]) -> None:
        workflow = self._workflow_status(report, issues)
        if report.status in {ReportStatus.PUBLISHED.value, ReportStatus.WITHDRAWN.value, ReportStatus.PARSING.value, ReportStatus.PARSE_FAILED.value}:
            return
        if report.status != workflow:
            report.status = workflow
            report.updated_at = datetime.now(timezone.utc)
