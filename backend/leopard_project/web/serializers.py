from __future__ import annotations

import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from leopard_project.config import load_seed_bundle
from sqlalchemy import desc, select

from .models import MarketRefreshItem, MarketRefreshRun, Report, SectorDailyBar, SectorMention, SectorResearchPreference
from .repository import ReportRepository


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _display_time(value) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M")


def _display_short_time(value) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(SHANGHAI).strftime("%m/%d %H:%M")


def report_payload(report: Report, *, admin: bool = False) -> dict:
    payload = {
        "id": report.id,
        "title": report.title,
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "candidate_report_date": report.candidate_report_date.isoformat() if report.candidate_report_date else None,
        "report_date_confirmed": report.report_date_confirmed,
        "detected_report_date": report.detected_report_date.isoformat() if report.detected_report_date else None,
        "report_date_source": report.report_date_source,
        "report_date_confidence": report.report_date_confidence,
        "report_date_confirmed_by_user": report.report_date_confirmed_by_user,
        "target_trade_date": report.target_trade_date.isoformat() if report.target_trade_date else None,
        "market_as_of_date": report.market_as_of_date.isoformat() if report.market_as_of_date else None,
        "candidate_market_as_of_date": report.candidate_market_as_of_date.isoformat() if report.candidate_market_as_of_date else None,
        "market_as_of_date_confirmed": report.market_as_of_date_confirmed,
        "interpretation_status": report.interpretation_status,
        "enhanced_status": report.enhanced_status,
        "enhanced_revision_number": report.enhanced_revision_number,
        "template_version": report.template_version,
        "revision_number": report.revision_number,
        "is_current": report.is_current,
        "replaces_report_id": report.replaces_report_id,
        "revision_note": report.revision_note,
        "data_origin": report.data_origin,
        "status": report.status,
        "core_view": report.core_view,
        "market_path": report.market_path,
        "risk_warning": report.risk_warning,
        "focus_sectors": json.loads(report.focus_sectors_json),
        "created_at": report.created_at.isoformat(),
        "created_at_display": _display_time(report.created_at),
        "published_at": report.published_at.isoformat() if report.published_at else None,
        "published_at_display": _display_time(report.published_at),
        "mentions": [
            {"sector_key": item.sector_key, "sector_name": item.sector_name, "summary": item.summary, "extraction_status": item.extraction_status}
            for item in report.mentions
        ],
        "pdf_url": f"/api/v1/reports/{report.id}/pdf/preview",
        "pdf_download_url": f"/api/v1/reports/{report.id}/pdf/download",
        "data_notice": "研究辅助数据，非生产级行情服务。",
    }
    if admin:
        interpretation_meta = json.loads(report.interpretation_meta_json or "{}")
        payload.update({
            "raw_text": report.raw_text,
            "parse_note": report.parse_note,
            "original_filename": report.file.original_filename,
            "sha256": report.file.sha256,
            "interpretation": interpretation_meta,
            "attention_items": interpretation_meta.get("attention_items", []),
            "mapping_summary": interpretation_meta.get("mapping_summary", {}),
            "field_provenance": interpretation_meta.get("field_provenance", {}),
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
    from .enhanced import EnhancedReportService, effective_statuses, path_statuses
    from .path_history import ensure_latest_path_history

    bundle = load_seed_bundle()
    published = repo.list_reports(published_only=True)
    enhanced = EnhancedReportService(repo.session)
    from .intraday import intraday_policy, market_phase, resolve_intraday_data_status
    latest_run = repo.session.scalar(select(MarketRefreshRun).where(MarketRefreshRun.mode == "intraday_refresh").order_by(desc(MarketRefreshRun.started_at)))
    latest_items = {
        item.sector_key: item.status for item in repo.session.scalars(select(MarketRefreshItem).where(MarketRefreshItem.run_id == latest_run.id))
    } if latest_run else {}
    pinned = {item.sector_key for item in repo.session.scalars(select(SectorResearchPreference).where(SectorResearchPreference.is_pinned_for_research.is_(True)))}
    now = datetime.now(timezone.utc)
    phase = market_phase(now)
    for report in published:
        enhanced.ensure_structure(report)
    latest: dict[str, SectorMention] = {}
    latest_dates: dict[str, str] = {}
    for report in published:
        for mention in report.mentions:
            if mention.sector_key not in latest:
                latest[mention.sector_key] = mention
                latest_dates[mention.sector_key] = report.report_date.isoformat()
    latest_report_keys = {item.sector_key for item in published[0].mentions} if published else set()
    if published:
        ensure_latest_path_history(repo.session, published[0].report_date)
    output: list[dict] = []
    for sector in sorted(bundle.sectors, key=lambda item: item.overall_order):
        mention = latest.get(sector.sector_key)
        path_history = enhanced.path_history(sector.sector_key, through=published[0].report_date if published else None)
        path = path_history[0] if path_history else None
        market = None if sector.sector_key == "hang_seng_tech" else enhanced.latest_market(sector.sector_key)
        unsupported = sector.sector_key == "hang_seng_tech"
        data_status = "unsupported" if unsupported else "short_history" if sector.sector_key == "glass_substrate" else "proxy" if sector.sector_key == "hotel_catering" else "supported"
        recent_path = [{
            "id": item.id,
            "report_id": item.detail_report_id or f"path:{item.path_report_date.isoformat()}",
            "detail_report_id": item.detail_report_id,
            "has_detailed_report": item.detail_report_id is not None,
            "report_date": item.path_report_date.isoformat(),
            "market_as_of_date": item.market_as_of_date.isoformat() if item.market_as_of_date else None,
            "path_status": item.path_status,
            "path_status_label": path_statuses()[item.path_status]["label"],
            "path_status_color": path_statuses()[item.path_status]["color"],
            "explicitly_mentioned": bool(item.detail_report_id and item.path_status != "not_mentioned"),
        } for item in reversed(path_history[:10])]
        statuses = [item.path_status for item in reversed(path_history)]
        effective = effective_statuses(statuses)
        current_effective = effective[-1] if effective else None
        explicit_statuses = [status for status in statuses if status != "not_mentioned"]
        intervals = enhanced.holding_intervals_for_sector(sector.sector_key, published[0].report_date if published else None)
        holding = intervals["active_holding_interval"]
        snapshot = None if unsupported else enhanced.latest_intraday(sector.sector_key)
        intraday_status = resolve_intraday_data_status(
            phase=phase, snapshot=snapshot, latest_result=latest_items.get(sector.sector_key), now=now,
            stale_after_minutes=intraday_policy()["stale_after_minutes"], unsupported=unsupported,
        )
        last_ten = path_history[:10]
        ten_not_mentioned = len(last_ten) == 10 and all(item.path_status == "not_mentioned" for item in last_ten)
        # A global Provider outage is surfaced in the market status strip; it must
        # not force all 65 otherwise-low-attention rows into the default table.
        special = data_status in {"proxy", "short_history", "unsupported"}
        is_pinned = sector.sector_key in pinned
        is_low_attention = bool(
            ten_not_mentioned and not intervals["strict_holding_interval"] and not intervals["broad_holding_interval"]
            and current_effective not in {"turn_hold", "hold", "strong_watch"} and not special and not is_pinned
        )
        recent_days = [] if unsupported else enhanced.recent_complete_days(sector.sector_key)
        if market is not None:
            market["recent_5_trading_days"] = recent_days
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
            "market_status_detail": "港股跨市场行情暂未接入" if unsupported else "881160代理口径" if sector.sector_key == "hotel_catering" else "历史较短，指标不足时显示历史不足" if sector.sector_key == "glass_substrate" else "研究辅助数据，非生产级行情服务。",
            "current_path_status": path.path_status if path else "not_mentioned",
            "current_path_status_label": path_statuses()[path.path_status]["label"] if path else "未提",
            "reported_status": path.path_status if path else "not_mentioned",
            "effective_status": current_effective,
            "effective_status_label": path_statuses()[current_effective]["label"] if current_effective else "暂无",
            "latest_market": market,
            "latest_complete_market": market,
            "intraday_snapshot": snapshot,
            "intraday_status": intraday_status,
            "intraday_last_attempt_at": _display_short_time(latest_run.started_at) if latest_run else None,
            "recent_5_trading_days": recent_days,
            "recent_path": recent_path,
            "active_holding_interval": holding,
            "historical_holding_intervals": intervals["historical_holding_intervals"],
            "strict_holding_interval": intervals["strict_holding_interval"],
            "broad_holding_interval": intervals["broad_holding_interval"],
            "historical_strict_intervals": intervals["historical_strict_intervals"],
            "historical_broad_intervals": intervals["historical_broad_intervals"],
            "is_low_attention": is_low_attention,
            "is_pinned_for_research": is_pinned,
            "status_changed": len(explicit_statuses) >= 2 and explicit_statuses[-1] != explicit_statuses[-2],
        })
    return output
