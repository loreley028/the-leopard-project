"""Reconcile already-published PDF-derived report facts in a staged SQLite copy.

The command is deliberately for an operator-controlled cutover rehearsal.  It
never obtains facts from a preview database: every candidate result comes from
the report's own stored PDF and the current deterministic parser.  A dry run
always works on a SQLite backup copy.  ``--apply`` atomically replaces only the
specified *isolated* database after the staged result is valid, so callers can
keep production outside the command's scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from leopard_project.web.database import create_session_factory
from leopard_project.web.models import (
    Report,
    ReportReviewIssue,
    ReportSection,
    SectorAssessment,
    SectorPathEntry,
    SectorMention,
    UnmappedTerm,
)
from leopard_project.web.repository import ReportRepository
from leopard_project.web.services import ReportService


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _rows(session: Any, model: Any, report_id: str, fields: tuple[str, ...], order_field: Any) -> list[dict[str, Any]]:
    return [
        {field: getattr(item, field) for field in fields}
        for item in session.scalars(
            select(model).where(model.report_id == report_id).order_by(order_field)
        )
    ]


def _facts(session: Any, report_date: date) -> dict[str, Any]:
    report = session.scalar(select(Report).where(Report.report_date == report_date, Report.is_current.is_(True)))
    if report is None:
        raise ValueError(f"published_report_not_found:{report_date.isoformat()}")
    return {
        "report": {
            key: getattr(report, key)
            for key in (
                "title", "candidate_report_date", "detected_report_date", "report_date_source",
                "report_date_confidence", "interpretation_status", "interpretation_meta_json",
                "enhanced_status", "template_version", "core_view", "market_path", "risk_warning",
                "focus_sectors_json", "raw_text", "parse_note",
            )
        },
        "file_identity": {
            "sha256": report.file.sha256 if report.file else None,
            "storage_filename": report.file.storage_filename if report.file else None,
        },
        "sections": _rows(session, ReportSection, report.id, ("section_type", "heading", "raw_text", "extraction_status"), ReportSection.section_type),
        "mentions": _rows(session, SectorMention, report.id, ("sector_key", "sector_name", "summary", "source_text", "extraction_status"), SectorMention.sector_key),
        "unmapped_terms": _rows(session, UnmappedTerm, report.id, ("term", "source_text", "status", "resolved_sector_key"), UnmappedTerm.term),
        "assessments": _rows(
            session, SectorAssessment, report.id,
            (
                "sector_key", "sector_name", "current_path_status", "explicitly_mentioned",
                "recent_path_summary", "current_judgement", "main_basis", "observation_condition",
                "source_text_reference", "extraction_method", "source_page", "source_text_start",
                "source_text_end", "source_text_excerpt", "confidence", "validation_flags_json",
                "quality_status", "review_status",
            ),
            SectorAssessment.sector_key,
        ),
        "path_entries": _rows(
            session, SectorPathEntry, report.id,
            (
                "sector_key", "sector_name", "path_status", "explicitly_mentioned", "judgement_summary",
                "source_text_reference", "source_page", "source_text_start", "source_text_end",
                "confidence", "validation_flags_json", "quality_status", "review_status",
            ),
            SectorPathEntry.sector_key,
        ),
        "review_issues": _rows(
            session, ReportReviewIssue, report.id,
            ("issue_key", "issue_type", "severity", "subject_key", "subject_label", "explanation", "evidence_json", "final_value_json"),
            ReportReviewIssue.issue_key,
        ),
    }


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _difference_count(left: Any, right: Any) -> int:
    if isinstance(left, dict) and isinstance(right, dict):
        return sum(_difference_count(left.get(key), right.get(key)) for key in sorted(set(left) | set(right)))
    if isinstance(left, list) and isinstance(right, list):
        return abs(len(left) - len(right)) + sum(_difference_count(a, b) for a, b in zip(left, right))
    return 0 if left == right else 1


def _backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as reader, sqlite3.connect(destination) as writer:
        reader.backup(writer)


def _reconcile(database: Path, upload_dir: Path, report_dates: list[date], actor: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    factory = create_session_factory(f"sqlite:///{database}")
    before: dict[str, dict[str, Any]] = {}
    results: dict[str, Any] = {}
    with factory() as session:
        repo = ReportRepository(session)
        service = ReportService(repo, upload_dir)
        for report_date in report_dates:
            key = report_date.isoformat()
            before[key] = _facts(session, report_date)
            report = session.scalar(select(Report).where(Report.report_date == report_date, Report.is_current.is_(True)))
            if report is None:
                raise ValueError(f"published_report_not_found:{key}")
            results[key] = service.reconcile_existing_report_facts(report, actor)
    after: dict[str, dict[str, Any]] = {}
    with factory() as session:
        for report_date in report_dates:
            key = report_date.isoformat()
            after[key] = _facts(session, report_date)
    return before, {key: {**results[key], "after": after[key]} for key in results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path, help="isolated SQLite database only")
    parser.add_argument("--upload-dir", required=True, type=Path)
    parser.add_argument("--report-date", action="append", required=True, type=date.fromisoformat)
    parser.add_argument("--actor", default="legacy-reconciliation")
    parser.add_argument("--apply", action="store_true", help="atomically replace the specified isolated database")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.exists():
        parser.error(f"database does not exist: {database}")
    if not args.upload_dir.exists():
        parser.error(f"upload directory does not exist: {args.upload_dir}")
    if len(set(args.report_date)) != len(args.report_date):
        parser.error("report dates must be unique")

    with tempfile.TemporaryDirectory(prefix="leopard-reconcile-") as directory:
        staged = Path(directory) / database.name
        _backup(database, staged)
        with create_session_factory(f"sqlite:///{database}")() as session:
            target_before = {value.isoformat(): _facts(session, value) for value in args.report_date}
        _, staged_result = _reconcile(staged, args.upload_dir.resolve(), args.report_date, args.actor)
        records: list[dict[str, Any]] = []
        changed = False
        for report_date in args.report_date:
            key = report_date.isoformat()
            before = target_before[key]
            after = staged_result[key].pop("after")
            field_count = _difference_count(before, after)
            changed = changed or field_count > 0
            records.append({
                "report_date": key,
                "before_digest": _digest(before),
                "after_digest": _digest(after),
                "changed_field_count": field_count,
                "result": staged_result[key],
            })
        if args.apply and changed:
            replacement = database.with_name(f".{database.name}.reconciled")
            # Copy through SQLite's online-backup API, rather than copying the
            # main file alone: the staged parser uses WAL mode and its newest
            # committed pages may still be in the WAL sidecar.
            _backup(staged, replacement)
            # The target is explicitly an offline, isolated database.  Its
            # old WAL/SHM pair belongs to the pre-reconciliation main file;
            # retaining it across ``os.replace`` would make SQLite combine
            # incompatible page histories.  The authoritative backup above
            # already captured every target page before this cleanup.
            for suffix in ("-wal", "-shm"):
                Path(f"{database}{suffix}").unlink(missing_ok=True)
            os.replace(replacement, database)
        output = {
            "mode": "apply" if args.apply else "dry_run",
            "database": str(database),
            "source": "authoritative_pdf_plus_current_parser",
            "applied": bool(args.apply and changed),
            "records": records,
        }
    rendered = json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
