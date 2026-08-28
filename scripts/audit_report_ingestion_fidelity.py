"""Audit authoritative PDF facts against the normal Admin ingestion path.

The source PDF is the authority.  This tool deliberately creates a clean,
temporary SQLite database and uploads each supplied PDF through the same Admin
endpoint used by the product.  It never reads or writes a production database
and it does not copy rows from a reference preview.

An optional ``--reference-database`` is comparison-only.  It can make older
accepted preview representations visible in the audit, but it can never alter
the PDF-derived or newly ingested facts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from leopard_project.web.app import WebSettings, create_app
from leopard_project.config import load_seed_bundle
from leopard_project.report_registry import load_report_registry
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import Report, ReportReviewIssue, SectorAssessment, SectorPathEntry
from leopard_project.web.services import extract_layout_text, extract_positioned_pages, extract_text_layer, parse_report_text


REPORT_FIELDS = ("report_date", "report_version", "core_view", "execution_conclusion", "review_status", "review_issues")
SECTOR_FIELDS = (
    "daily_path_marker", "reported_status", "explicitly_mentioned", "primary_evidence",
    "observation_condition", "path_source", "report_local_path_entry",
)


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    report_date: str
    snapshot: dict[str, Any]


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalization_only(left: Any, right: Any) -> bool:
    return str(left or "") != str(right or "") and _compact(left) == _compact(right)


def _record_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "daily_path_marker": record.get("current_judgement", ""),
        "reported_status": record.get("path_status", "not_mentioned"),
        "explicitly_mentioned": True,
        "primary_evidence": record.get("main_basis", ""),
        "observation_condition": record.get("observation_condition", ""),
        # Persisted path entries retain the PDF row excerpt, rather than the
        # human-readable page/row locator.  Compare that immutable excerpt;
        # the locator remains available in the full PDF-derived snapshot.
        "path_source": record.get("source_text_reference", ""),
        "report_local_path_entry": record.get("path_status", "not_mentioned"),
    }


def pdf_snapshot(path: Path) -> SourceDocument:
    payload = path.read_bytes()
    fields, _, _, _ = parse_report_text(
        extract_text_layer(payload),
        "fidelity-audit-source",
        path.name,
        extract_layout_text(payload),
        extract_positioned_pages(payload),
    )
    metadata = fields["interpretation_meta"]
    report_date = fields["candidate_report_date"]
    if report_date is None:
        raise ValueError(f"report_date_unavailable:{path.name}")
    parsed_records = {
        item["sector_key"]: _record_snapshot(item)
        for item in metadata.get("assessment_records", [])
    }
    # The upload route deliberately creates a complete 66-topic report-local
    # ledger.  A sector that has no native detailed-table row is therefore an
    # explicit *not mentioned* local fact, not a missing comparison row and
    # not an effective-status carry-forward.
    canonical_path_keys = {sector.sector_key for sector in load_seed_bundle().sectors}
    records = {
        sector.sector_key: parsed_records.get(sector.sector_key, {
            "daily_path_marker": "",
            "reported_status": "not_mentioned",
            "explicitly_mentioned": False,
            "primary_evidence": "",
            "observation_condition": "",
            "path_source": "",
            "report_local_path_entry": "not_mentioned",
        })
        for sector in load_report_registry()
    }
    for sector_key, record in records.items():
        if sector_key not in canonical_path_keys:
            record["report_local_path_entry"] = "not_mentioned"
    snapshot = {
        "report_date": report_date.isoformat(),
        "report_version": metadata.get("template_version", "unknown"),
        "core_view": fields.get("core_view", ""),
        "execution_conclusion": fields.get("market_path", ""),
        # ``needs_attention`` is the persisted canonical status for a PDF
        # that carries review items.  The parser's internal term
        # ``needs_review`` is an implementation label, not a different
        # Reader-visible state.
        "review_status": "needs_attention" if metadata.get("attention_items") else "ready",
        "review_issues": metadata.get("attention_items", []),
        "sectors": records,
        "direct_assessment_keys": sorted(parsed_records),
    }
    return SourceDocument(path=path, report_date=report_date.isoformat(), snapshot=snapshot)


def _persisted_snapshot(session: Any, report_date: str) -> dict[str, Any]:
    report = session.scalar(select(Report).where(Report.report_date == report_date, Report.is_current.is_(True)))
    if report is None:
        raise ValueError(f"persisted_report_missing:{report_date}")
    metadata = json.loads(report.interpretation_meta_json or "{}")
    assessments = {
        item.sector_key: item
        for item in session.scalars(select(SectorAssessment).where(SectorAssessment.report_id == report.id))
    }
    entries = {
        item.sector_key: item
        for item in session.scalars(select(SectorPathEntry).where(SectorPathEntry.report_id == report.id))
    }
    sectors: dict[str, dict[str, Any]] = {}
    for sector_key in sorted(set(assessments) | set(entries)):
        assessment, entry = assessments.get(sector_key), entries.get(sector_key)
        sectors[sector_key] = {
            "daily_path_marker": assessment.current_judgement if assessment else "",
            "reported_status": entry.path_status if entry else (assessment.current_path_status if assessment else "not_mentioned"),
            "explicitly_mentioned": bool(entry.explicitly_mentioned if entry else assessment and assessment.explicitly_mentioned),
            "primary_evidence": assessment.main_basis if assessment else "",
            "observation_condition": assessment.observation_condition if assessment else "",
            "path_source": entry.source_text_reference if entry else (assessment.source_text_reference if assessment else ""),
            "report_local_path_entry": entry.path_status if entry else "not_mentioned",
        }
    return {
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "report_version": report.template_version,
        "core_view": report.core_view,
        "execution_conclusion": report.market_path,
        "review_status": report.interpretation_status,
        "review_issues": metadata.get("attention_items", []),
        "sectors": sectors,
        # This is the final persisted publication state, deliberately kept
        # separate from the API response's immediate publication label.
        "publication": report.status,
        "final_publication_state": report.status,
        "blocking_issue_count": sum(
            item.severity == "required" and item.resolved_at is None
            for item in session.scalars(select(ReportReviewIssue).where(ReportReviewIssue.report_id == report.id))
        ),
        "sha256": report.file.sha256 if report.file else None,
    }


def _reference_snapshot(database: Path, report_date: str) -> dict[str, Any] | None:
    """Read a comparison-only preview snapshot without using ORM writes."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        report = connection.execute(
            "SELECT id, report_date, template_version, core_view, market_path, interpretation_status, "
            "interpretation_meta_json, status FROM reports WHERE report_date = ? AND is_current = 1",
            (report_date,),
        ).fetchone()
        if report is None:
            return None
        metadata = json.loads(report["interpretation_meta_json"] or "{}")
        assessments = {
            row["sector_key"]: row
            for row in connection.execute(
                "SELECT sector_key, current_judgement, current_path_status, explicitly_mentioned, main_basis, "
                "observation_condition FROM sector_assessments WHERE report_id = ?", (report["id"],)
            )
        }
        entries = {
            row["sector_key"]: row
            for row in connection.execute(
                "SELECT sector_key, path_status, explicitly_mentioned, source_text_reference "
                "FROM sector_path_entries WHERE report_id = ?", (report["id"],)
            )
        }
        sectors: dict[str, dict[str, Any]] = {}
        for sector_key in sorted(set(assessments) | set(entries)):
            assessment, entry = assessments.get(sector_key), entries.get(sector_key)
            sectors[sector_key] = {
                "daily_path_marker": assessment["current_judgement"] if assessment else "",
                "reported_status": entry["path_status"] if entry else (assessment["current_path_status"] if assessment else "not_mentioned"),
                "explicitly_mentioned": bool(entry["explicitly_mentioned"] if entry else assessment and assessment["explicitly_mentioned"]),
                "primary_evidence": assessment["main_basis"] if assessment else "",
                "observation_condition": assessment["observation_condition"] if assessment else "",
                "path_source": entry["source_text_reference"] if entry else (assessment["source_text_reference"] if assessment else ""),
                "report_local_path_entry": entry["path_status"] if entry else "not_mentioned",
            }
        return {
            "report_date": report["report_date"],
            "report_version": report["template_version"],
            "core_view": report["core_view"],
            "execution_conclusion": report["market_path"],
            "review_status": report["interpretation_status"],
            "review_issues": metadata.get("attention_items", []),
            "sectors": sectors,
            "publication": report["status"],
        }
    finally:
        connection.close()


def _difference(
    *, report_date: str, sector_key: str, field: str, pdf_value: Any, ingested_value: Any, preview_value: Any,
) -> dict[str, Any] | None:
    if pdf_value == ingested_value:
        return None
    return {
        "comparison_target": "admin_ingestion",
        "report_date": report_date,
        "sector_key": sector_key or None,
        "field": field,
        "pdf_derived_value": pdf_value,
        "admin_ingested_value": ingested_value,
        "approved_preview_value": preview_value,
        "first_divergence_stage": "PERSISTENCE",
        "classification": "NORMALIZATION_ONLY" if _normalization_only(pdf_value, ingested_value) else "SUBSTANTIVE",
    }


def _reference_difference(
    *, report_date: str, sector_key: str, field: str, pdf_value: Any, preview_value: Any,
) -> dict[str, Any] | None:
    if preview_value is None or pdf_value == preview_value:
        return None
    return {
        "comparison_target": "approved_preview_reference",
        "report_date": report_date,
        "sector_key": sector_key or None,
        "field": field,
        "pdf_derived_value": pdf_value,
        "admin_ingested_value": pdf_value,
        "approved_preview_value": preview_value,
        # This is deliberately not attributed to the current ingestion path:
        # the independently re-ingested Admin value already matches the PDF.
        "first_divergence_stage": "PREVIEW_PERSISTENCE",
        "classification": "NORMALIZATION_ONLY" if _normalization_only(pdf_value, preview_value) else "REFERENCE_SUBSTANTIVE",
    }


def audit(documents: list[SourceDocument], *, reference_database: Path | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="leopard-fidelity-") as directory:
        root = Path(directory)
        database_url = f"sqlite:///{root / 'audit.sqlite3'}"
        audit_session_secret = str("fidelity-audit-session-secret-at-least-32-bytes")
        audit_admin_password = str("fidelity-audit-password-at-least-16")
        audit_viewer_password = str("fidelity-audit-viewer-password-at-least-16")
        settings = WebSettings(
            database_url=database_url,
            upload_dir=root / "uploads",
            session_secret=audit_session_secret,
            admin_username="fidelity-audit-admin",
            admin_password=audit_admin_password,
            viewer_username="fidelity-audit-viewer",
            viewer_password=audit_viewer_password,
            auto_publish_uploads=True,
        )
        factory = create_session_factory(database_url)
        reports: list[dict[str, Any]] = []
        with TestClient(create_app(settings, factory)) as client:
            login = client.post("/api/v1/auth/admin/login", json={
                "username": settings.admin_username, "password": settings.admin_password,
            })
            if login.status_code != 200:
                raise RuntimeError(f"audit_admin_login_failed:{login.status_code}")
            for document in documents:
                response = client.post(
                    "/api/v1/admin/reports/interpret",
                    files={"file": (document.path.name, document.path.read_bytes(), "application/pdf")},
                )
                if response.status_code != 201:
                    raise RuntimeError(f"admin_ingestion_failed:{document.path.name}:{response.status_code}:{response.text[:300]}")
                api_response = response.json()
                with factory() as session:
                    ingested = _persisted_snapshot(session, document.report_date)
                preview = _reference_snapshot(reference_database, document.report_date) if reference_database else None
                differences: list[dict[str, Any]] = []
                reference_differences: list[dict[str, Any]] = []
                for field in REPORT_FIELDS:
                    difference = _difference(
                        report_date=document.report_date,
                        sector_key="",
                        field=field,
                        pdf_value=document.snapshot.get(field),
                        ingested_value=ingested.get(field),
                        preview_value=preview.get(field) if preview else None,
                    )
                    if difference:
                        differences.append(difference)
                    if preview:
                        reference_difference = _reference_difference(
                            report_date=document.report_date,
                            sector_key="",
                            field=field,
                            pdf_value=document.snapshot.get(field),
                            preview_value=preview.get(field),
                        )
                        if reference_difference:
                            reference_differences.append(reference_difference)
                for sector_key in sorted(document.snapshot["direct_assessment_keys"]):
                    source_sector = document.snapshot["sectors"].get(sector_key, {})
                    stored_sector = ingested["sectors"].get(sector_key, {})
                    preview_sector = (preview or {}).get("sectors", {}).get(sector_key, {})
                    for field in SECTOR_FIELDS:
                        difference = _difference(
                            report_date=document.report_date,
                            sector_key=sector_key,
                            field=field,
                            pdf_value=source_sector.get(field),
                            ingested_value=stored_sector.get(field),
                            preview_value=preview_sector.get(field),
                        )
                        if difference:
                            differences.append(difference)
                        if preview:
                            reference_difference = _reference_difference(
                                report_date=document.report_date,
                                sector_key=sector_key,
                                field=field,
                                pdf_value=source_sector.get(field),
                                preview_value=preview_sector.get(field),
                            )
                            if reference_difference:
                                reference_differences.append(reference_difference)
                reports.append({
                    "report_date": document.report_date,
                    "filename": document.path.name,
                    "admin_upload": {
                        "http_status": response.status_code,
                        "duplicate": bool(api_response.get("duplicate")),
                        "api_publication": api_response.get("publication"),
                        "interpretation_error": api_response.get("interpretation_error"),
                    },
                    "pdf_derived": document.snapshot,
                    "admin_ingested": ingested,
                    "approved_preview": preview,
                    "differences": differences,
                    "reference_differences": reference_differences,
                })
    all_differences = [item for report in reports for item in report["differences"]]
    all_reference_differences = [item for report in reports for item in report["reference_differences"]]
    final_publications = Counter(str(item["admin_ingested"]["final_publication_state"]) for item in reports)
    review_statuses = Counter(str(item["admin_ingested"]["review_status"]) for item in reports)
    api_publications = Counter(str(item["admin_upload"]["api_publication"]) for item in reports)
    return {
        "authority": "original_pdf",
        "reference_database_is_comparison_only": reference_database is not None,
        "report_count": len(reports),
        "reports": reports,
        "summary": {
            "admin_ingestion_substantive_mismatches": sum(item["classification"] == "SUBSTANTIVE" for item in all_differences),
            "normalization_only_mismatches": sum(item["classification"] == "NORMALIZATION_ONLY" for item in all_differences),
            "first_divergence_stages": sorted({item["first_divergence_stage"] for item in all_differences}),
            "approved_preview_reference_differences": len(all_reference_differences),
            "approved_preview_substantive_reference_differences": sum(
                item["classification"] == "REFERENCE_SUBSTANTIVE" for item in all_reference_differences
            ),
            "api_publication_counts": dict(sorted(api_publications.items())),
            "final_publication_counts": dict(sorted(final_publications.items())),
            "review_status_counts": dict(sorted(review_statuses.items())),
            "blocking_issue_count": sum(int(item["admin_ingested"]["blocking_issue_count"]) for item in reports),
        },
    }


def _input_paths(directory: Path | None, explicit: list[Path]) -> list[Path]:
    paths = list(explicit)
    if directory:
        paths.extend(sorted(directory.rglob("*.pdf")))
    unique = {path.resolve(): path.resolve() for path in paths}
    return sorted(unique.values(), key=lambda path: path.name)


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report_ingestion_fidelity_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8",
    )
    rows = [
        item
        for report in result["reports"]
        for collection in (report["differences"], report.get("reference_differences", []))
        for item in collection
    ]
    with (output_dir / "report_ingestion_fidelity_audit.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "comparison_target", "report_date", "sector_key", "field", "classification", "first_divergence_stage",
            "pdf_derived_value", "admin_ingested_value", "approved_preview_value",
        ))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path)
    parser.add_argument("--pdf", type=Path, action="append", default=[])
    parser.add_argument("--reference-database", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("var/audit"))
    args = parser.parse_args()
    paths = _input_paths(args.pdf_dir, args.pdf)
    if not paths:
        parser.error("at least one --pdf or --pdf-dir PDF is required")
    result = audit([pdf_snapshot(path) for path in paths], reference_database=args.reference_database)
    write_outputs(result, args.output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if result["summary"]["admin_ingestion_substantive_mismatches"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
