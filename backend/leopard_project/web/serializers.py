from __future__ import annotations

import json

from leopard_project.config import load_seed_bundle

from .models import Report, SectorMention
from .repository import ReportRepository


def report_payload(report: Report, *, admin: bool = False) -> dict:
    payload = {
        "id": report.id,
        "title": report.title,
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "candidate_report_date": report.candidate_report_date.isoformat() if report.candidate_report_date else None,
        "report_date_confirmed": report.report_date_confirmed,
        "status": report.status,
        "core_view": report.core_view,
        "market_path": report.market_path,
        "risk_warning": report.risk_warning,
        "focus_sectors": json.loads(report.focus_sectors_json),
        "created_at": report.created_at.isoformat(),
        "published_at": report.published_at.isoformat() if report.published_at else None,
        "mentions": [
            {"sector_key": item.sector_key, "sector_name": item.sector_name, "summary": item.summary, "extraction_status": item.extraction_status}
            for item in report.mentions
        ],
        "pdf_url": f"/api/v1/reports/{report.id}/pdf",
        "data_notice": "研究辅助数据，非生产级行情服务。",
    }
    if admin:
        payload.update({
            "raw_text": report.raw_text,
            "parse_note": report.parse_note,
            "original_filename": report.file.original_filename,
            "sha256": report.file.sha256,
            "unmapped_terms": [
                {"id": item.id, "term": item.term, "status": item.status, "resolved_sector_key": item.resolved_sector_key}
                for item in report.unmapped_terms
            ],
        })
    return payload


def objective_change_summary(current: Report, previous: Report | None) -> dict:
    if previous is None:
        return {"kind": "first_published_report", "text": "这是当前系统中的首期已发布报告，暂无上一期可比较。"}
    current_focus = set(json.loads(current.focus_sectors_json))
    previous_focus = set(json.loads(previous.focus_sectors_json))
    added = sorted(current_focus - previous_focus)
    removed = sorted(previous_focus - current_focus)
    return {
        "kind": "focus_sector_diff",
        "added_focus_sectors": added,
        "removed_focus_sectors": removed,
        "text": f"重点板块新增 {len(added)} 个、移出 {len(removed)} 个；仅描述结构化字段差异，不推断观点失效。",
    }


def sector_payloads(repo: ReportRepository) -> list[dict]:
    bundle = load_seed_bundle()
    published = repo.list_reports(published_only=True)
    latest: dict[str, SectorMention] = {}
    latest_dates: dict[str, str] = {}
    for report in published:
        for mention in report.mentions:
            if mention.sector_key not in latest:
                latest[mention.sector_key] = mention
                latest_dates[mention.sector_key] = report.report_date.isoformat()
    latest_report_keys = {item.sector_key for item in published[0].mentions} if published else set()
    output: list[dict] = []
    for sector in sorted(bundle.sectors, key=lambda item: item.overall_order):
        mention = latest.get(sector.sector_key)
        unsupported = sector.sector_key == "hang_seng_tech"
        data_status = "unsupported" if unsupported else "short_history" if sector.sector_key == "glass_substrate" else "proxy" if sector.sector_key == "hotel_catering" else "supported"
        output.append({
            "sector_key": sector.sector_key,
            "sector_name": sector.sector_name,
            "group_name": sector.category_level_1,
            "group_order": sector.group_order,
            "overall_order": sector.overall_order,
            "latest_view": mention.summary if mention else None,
            "latest_view_date": latest_dates.get(sector.sector_key),
            "mentioned_in_latest_published": sector.sector_key in latest_report_keys,
            "market_support_status": "unsupported" if unsupported else "supported",
            "data_status": data_status,
            "market_status_detail": "港股跨市场行情暂未接入" if unsupported else "研究辅助数据，非生产级行情服务。",
        })
    return output
