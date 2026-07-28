from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from leopard_project.config import PROJECT_ROOT, load_seed_bundle
from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService
from leopard_project.web.models import Report, ReportFile, ReportStatus, SectorMention, SectorPathEntry, SectorAssessment


FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/enhanced_reports_v1.json"
SOURCE_PDF = PROJECT_ROOT / "tests/fixtures/sample_report_fixture.pdf"
REPORT_DATES = [
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-28",
    "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-05",
    "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-12",
    "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-19",
]
MARKET_DATES = [
    "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
    "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03",
    "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10",
    "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17",
]


def build_demo_documents(fixture: dict, sectors: list) -> list[dict]:
    ordered = sorted(sectors, key=lambda item: item.overall_order)
    statuses = ["avoid", "strong_watch", "watch", "weak_watch", "turn_hold", "hold", "turn_weak", "exit"]
    documents = []
    for index, (report_date, market_date) in enumerate(zip(REPORT_DATES, MARKET_DATES, strict=True)):
        template = fixture["reports"][index % len(fixture["reports"])]
        mentioned = [ordered[(index * 7 + offset) % 66] for offset in range(16)]
        documents.append({**template, "fixture_key": f"fidelity-{report_date}", "title": f"虚构直播总结·第{index + 1:02d}期", "report_date": report_date, "market_as_of_date": market_date, "focus_sectors": [sector.sector_name for sector in mentioned[:4]], "statuses": {sector.sector_key: statuses[(index + offset + sector.overall_order) % len(statuses)] for offset, sector in enumerate(mentioned)}})
    return documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an isolated Phase 2A-0 enhanced demo database.")
    parser.add_argument("--runtime-dir", type=Path, default=PROJECT_ROOT / "var/demo-enhanced")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime = args.runtime_dir.resolve()
    expected_parent = (PROJECT_ROOT / "var").resolve()
    allowed_runtime_names = {"demo-enhanced", "demo-interpretation", "demo-fidelity"}
    if runtime.parent != expected_parent or runtime.name not in allowed_runtime_names:
        raise SystemExit(
            "runtime-dir must be an isolated var/demo-enhanced, "
            "var/demo-interpretation, or var/demo-fidelity directory"
        )
    database = runtime / "leopard_demo.sqlite3"
    if database.exists():
        raise SystemExit(f"Refusing to overwrite existing demo database: {database}")
    runtime.mkdir(parents=True, exist_ok=True)
    uploads = runtime / "uploads"
    uploads.mkdir()
    sessions = create_session_factory(f"sqlite:///{database}")
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    bundle = load_seed_bundle()
    sector_map = {item.sector_key: item for item in bundle.sectors}
    documents = build_demo_documents(fixture, bundle.sectors)
    report_ids: list[str] = []
    with sessions() as session:
        service = EnhancedReportService(session)
        service.fixture_refresh("fixture-admin")
        for index, document in enumerate(documents, start=1):
            payload = SOURCE_PDF.read_bytes() + f"\n% enhanced-fixture:{document['fixture_key']}\n".encode()
            digest = hashlib.sha256(payload).hexdigest()
            storage_name = f"fixture-{document['fixture_key']}.pdf"
            (uploads / storage_name).write_bytes(payload)
            report = Report(
                title=document["title"],
                report_date=date.fromisoformat(document["report_date"]),
                candidate_report_date=date.fromisoformat(document["report_date"]),
                report_date_confirmed=True,
                detected_report_date=date.fromisoformat(document["report_date"]),
                report_date_source="controlled_fixture",
                report_date_confidence="high",
                report_date_confirmed_by_user=False,
                market_as_of_date=date.fromisoformat(document["market_as_of_date"]),
                candidate_market_as_of_date=date.fromisoformat(document["market_as_of_date"]),
                market_as_of_date_confirmed=True,
                interpretation_status="ready",
                interpretation_meta_json=json.dumps(
                    {
                        "fixture_only": True,
                        "external_llm_calls": 0,
                        "ocr_calls": 0,
                        "attention_items": [],
                        "mapping_summary": {
                            "confirmed": len(document["statuses"]),
                            "probable": 0,
                            "unmapped": 0,
                            "conflict": 0,
                        },
                        "quality_status": "verified_structure",
                        "quality_summary": {
                            "report_structure": "verified_structure",
                            "history_matrix": "verified_structure",
                            "history_rows": 66,
                            "assessment_rows": len(document["statuses"]),
                            "assessment_verified": len(document["statuses"]),
                            "assessment_blocking": 0,
                        },
                    },
                    ensure_ascii=False,
                ),
                status=ReportStatus.PUBLISHED.value,
                enhanced_status="ready",
                core_view=document["core_view"],
                market_path=document["market_path"],
                risk_warning=document["risk_warning"],
                focus_sectors_json=json.dumps(document["focus_sectors"], ensure_ascii=False),
                raw_text=f"FIXTURE {document['fixture_key']}：所有内容均为虚构脱敏演示。",
                parse_note="Controlled offline fixture; no external AI and no network.",
                created_by="fixture-admin",
                published_by="fixture-admin",
                created_at=datetime.combine(date.fromisoformat(document["report_date"]), datetime.min.time(), tzinfo=timezone.utc).replace(hour=12, minute=30),
                published_at=datetime.combine(date.fromisoformat(document["report_date"]), datetime.min.time(), tzinfo=timezone.utc).replace(hour=14),
            )
            report.file = ReportFile(
                sha256=digest,
                original_filename=f"fixture-{document['fixture_key']}.pdf",
                storage_filename=storage_name,
                content_type="application/pdf",
                size_bytes=len(payload),
            )
            for sector_key, status in document["statuses"].items():
                sector = sector_map[sector_key]
                report.mentions.append(SectorMention(
                    sector_key=sector_key,
                    sector_name=sector.sector_name,
                    summary=f"{sector.sector_name}：{status} 的虚构直播判断，等待既定观察条件确认。",
                    source_text=f"FIXTURE:{document['fixture_key']}:{sector_key}",
                    extraction_status="fixture_confirmed",
                ))
            session.add(report)
            session.commit()
            service.ensure_structure(report, "fixture-admin")
            for sector_key, status in document["statuses"].items():
                entry = session.scalar(select(SectorPathEntry).where(SectorPathEntry.report_id == report.id, SectorPathEntry.sector_key == sector_key))
                assessment = session.scalar(select(SectorAssessment).where(SectorAssessment.report_id == report.id, SectorAssessment.sector_key == sector_key))
                entry.path_status = status
                entry.explicitly_mentioned = status != "not_mentioned"
                entry.review_status = "confirmed"
                entry.extraction_method = "controlled_fixture"
                entry.confidence = "high"
                entry.validation_flags_json = "[]"
                entry.quality_status = "verified_structure"
                entry.judgement_summary = f"虚构判断：{sector_map[sector_key].sector_name}当前为{status}。"
                assessment.current_path_status = status
                assessment.explicitly_mentioned = status != "not_mentioned"
                assessment.recent_path_summary = f"由上一期状态确定性转为{status}。"
                assessment.current_judgement = entry.judgement_summary
                assessment.main_basis = "受控fixture中的量价结构与直播原文占位依据。"
                assessment.observation_condition = "仅当完整EOD和既定结构条件同时满足时继续观察。"
                assessment.review_status = "confirmed"
                assessment.extraction_method = "controlled_fixture"
                assessment.source_text_excerpt = f"虚构脱敏fixture：{sector_map[sector_key].sector_name}第{index:02d}期详细观点。"
                assessment.confidence = "high"
                assessment.validation_flags_json = "[]"
                assessment.quality_status = "verified_structure"
            session.commit()
            service.freeze_market_snapshot(report, "fixture-admin")
            report_ids.append(report.id)
        summary = {
            "fixture_only": True,
            "external_llm_calls": 0,
            "network_calls": 0,
            "report_count": len(report_ids),
            "path_entry_count": session.scalar(select(SectorPathEntry).count()) if False else len(report_ids) * 66,
            "supported_market_count": 65,
            "unsupported": ["hang_seng_tech"],
            "database": str(database),
            "upload_dir": str(uploads),
            "latest_report_id": report_ids[-1],
            "sunday_report_id": report_ids[-1],
            "report_dates": REPORT_DATES,
            "friday_saturday_report_count": 0,
        }
    (runtime / "fixture-manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
