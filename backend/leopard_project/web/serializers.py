from __future__ import annotations

import json
from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from leopard_project.config import load_seed_bundle
from leopard_project.dormant_sectors import classify_dormant_sector
from leopard_project.market_paths import load_market_path_registry, report_topic_sector
from leopard_project.providers.capabilities import load_provider_capabilities
from leopard_project.report_registry import reader_report_registry
from leopard_project.security_proxy_observation import APPROVED, load_security_proxy_registry
from leopard_project.sector_lifecycle import is_active_report_object_on
from leopard_project.trading_calendar import controlled_trading_day_on_or_before, next_controlled_trading_day, report_market_date
from sqlalchemy import desc, select

from .effective_strategy import ReportStrategyFact, effective_strategy_for_trading_day
from .models import (
    MarketRefreshItem,
    MarketRefreshRun,
    Report,
    SectorAssessment,
    SectorDailyBar,
    SectorPathEntry,
    SectorPathHistoryEntry,
    SectorResearchPreference,
)
from .repository import ReportRepository
from .primary_market_observation import primary_history
from .market_date_axis import market_core_completed_dates


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
    explicit_assessment_count = sum(1 for entry in report.assessments if entry.explicitly_mentioned)
    interpretation_meta = json.loads(report.interpretation_meta_json or "{}")
    field_provenance = interpretation_meta.get("field_provenance", {})
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
        "reader_fact_provenance": {
            "core_characterization": field_provenance.get("core_view", {}),
            "execution_conclusion": field_provenance.get("market_path", {}),
        },
        "focus_sectors": json.loads(report.focus_sectors_json),
        "explicit_assessment_count": explicit_assessment_count,
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
        payload.update({
            "raw_text": report.raw_text,
            "parse_note": report.parse_note,
            "original_filename": report.file.original_filename,
            "sha256": report.file.sha256,
            "interpretation": interpretation_meta,
            "attention_items": interpretation_meta.get("attention_items", []),
            "mapping_summary": interpretation_meta.get("mapping_summary", {}),
            "field_provenance": field_provenance,
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


def sector_view_payloads(repo: ReportRepository) -> list[dict]:
    """Build the report-derived Board view with a bounded set of queries.

    This read model deliberately excludes EOD prices, indicators, holding
    returns and persisted intraday observations.  Those fields remain on the
    existing ``/sectors`` market-enrichment response and cannot delay the
    first rendering of report facts.
    """
    from .enhanced import assessment_path_payload, assessment_payload, effective_statuses, path_entry_payload, path_statuses

    session = repo.session
    bundle = load_seed_bundle()
    registry = load_market_path_registry(bundle)
    capabilities = load_provider_capabilities()
    published = list(session.execute(select(
        Report.id,
        Report.report_date,
        Report.created_at,
    ).where(
        Report.status == "published",
        Report.is_current.is_(True),
    ).order_by(desc(Report.report_date), desc(Report.created_at))))
    report_ids = [report.id for report in published]
    path_entries = list(session.execute(select(
        SectorPathEntry.id,
        SectorPathEntry.report_id,
        SectorPathEntry.sector_key,
        SectorPathEntry.path_status,
        SectorPathEntry.explicitly_mentioned,
    ).where(
        SectorPathEntry.report_id.in_(report_ids)
    ))) if report_ids else []
    assessments = list(session.execute(select(
        SectorAssessment.id,
        SectorAssessment.report_id,
        SectorAssessment.sector_key,
        SectorAssessment.current_path_status,
        SectorAssessment.explicitly_mentioned,
    ).where(
        SectorAssessment.report_id.in_(report_ids)
    ))) if report_ids else []
    history_query = select(SectorPathHistoryEntry)
    if published and published[0].report_date:
        history_query = history_query.where(SectorPathHistoryEntry.path_report_date <= published[0].report_date)
    history_rows = list(session.scalars(history_query.order_by(
        SectorPathHistoryEntry.sector_key,
        desc(SectorPathHistoryEntry.path_report_date),
    )))
    pinned = {item.sector_key for item in session.scalars(select(SectorResearchPreference).where(
        SectorResearchPreference.is_pinned_for_research.is_(True)
    ))}
    controlled_dates = market_core_completed_dates(session)

    report_objects = reader_report_registry()
    current_sector_keys = {item.sector_key for item in report_objects}
    entries_by_pair = {(item.report_id, item.sector_key): item for item in path_entries}
    assessments_by_pair = {(item.report_id, item.sector_key): item for item in assessments}
    assessments_by_report: dict[str, list[SectorAssessment]] = {}
    for assessment in assessments:
        assessments_by_report.setdefault(assessment.report_id, []).append(assessment)
    histories_by_sector: dict[str, list[SectorPathHistoryEntry]] = {}
    for item in history_rows:
        if is_active_report_object_on(item.sector_key, item.path_report_date):
            histories_by_sector.setdefault(item.sector_key, []).append(item)

    latest_explicit = {}
    for report in published:
        for assessment in assessments_by_report.get(report.id, []):
            sector_key = assessment.sector_key
            if (
                sector_key in latest_explicit
                or sector_key not in current_sector_keys
                or not is_active_report_object_on(sector_key, report.report_date)
            ):
                continue
            entry = entries_by_pair.get((report.id, sector_key))
            if (
                not assessment.explicitly_mentioned
                or assessment.current_path_status == "not_mentioned"
                or entry is not None and (not entry.explicitly_mentioned or entry.path_status == "not_mentioned")
            ):
                continue
            latest_explicit[sector_key] = (report, entry, assessment)

    explicit_assessment_ids = [fact[2].id for fact in latest_explicit.values()]
    explicit_entry_ids = [fact[1].id for fact in latest_explicit.values() if fact[1] is not None]
    explicit_assessments = {
        item.id: item for item in session.scalars(select(SectorAssessment).where(
            SectorAssessment.id.in_(explicit_assessment_ids)
        ))
    } if explicit_assessment_ids else {}
    explicit_entries = {
        item.id: item for item in session.scalars(select(SectorPathEntry).where(
            SectorPathEntry.id.in_(explicit_entry_ids)
        ))
    } if explicit_entry_ids else {}

    latest_report = published[0] if published else None
    latest_report_assessments = {
        item.sector_key: item for item in assessments_by_report.get(latest_report.id, [])
    } if latest_report else {}
    latest_report_path_keys = {
        item.sector_key for item in path_entries if latest_report and item.report_id == latest_report.id
    }
    latest_report_keys = {
        sector_key for sector_key, (report, _, _) in latest_explicit.items()
        if latest_report and report.id == latest_report.id
    }
    market_paths_by_parent: dict[str, list] = {}
    for market_path in registry.market_paths:
        market_paths_by_parent.setdefault(market_path.parent_report_topic, []).append(market_path)
    primary_definitions = {
        item.market_path_key: item for item in load_security_proxy_registry() if item.status == APPROVED
    }
    status_contract = path_statuses()
    current_trading_day = controlled_trading_day_on_or_before(datetime.now(SHANGHAI).date())
    cached_next_trading_day = lru_cache(maxsize=None)(next_controlled_trading_day)
    cached_report_market_date = lru_cache(maxsize=None)(report_market_date)

    output: list[dict] = []
    for report_object in report_objects:
        report_key = report_object.sector_key
        candidates = market_paths_by_parent.get(report_key, [])
        market_path = next(
            (item for item in candidates if item.market_path_key == report_key),
            candidates[0] if candidates else None,
        )
        market_key = market_path.market_path_key if market_path is not None else report_key
        explicit_fact = latest_explicit.get(report_key)
        explicit_report, explicit_entry_fact, explicit_assessment_fact = explicit_fact if explicit_fact else (None, None, None)
        explicit_entry = explicit_entries.get(explicit_entry_fact.id) if explicit_entry_fact is not None else None
        explicit_assessment = explicit_assessments.get(explicit_assessment_fact.id) if explicit_assessment_fact is not None else None
        explicit_assessment_data = assessment_payload(explicit_assessment) if explicit_assessment else None
        latest_view = " · ".join(filter(None, (
            explicit_assessment_data["current_judgement"] if explicit_assessment_data else "",
            explicit_assessment_data["main_basis"] if explicit_assessment_data else "",
            explicit_assessment_data["observation_condition"] if explicit_assessment_data else "",
        ))) or None

        path_history = histories_by_sector.get(report_key, [])
        recent_path = [{
            "id": item.id,
            "report_id": item.detail_report_id or f"path:{item.path_report_date.isoformat()}",
            "detail_report_id": item.detail_report_id,
            "has_detailed_report": item.detail_report_id is not None,
            "report_date": item.path_report_date.isoformat(),
            "market_as_of_date": item.market_as_of_date.isoformat() if item.market_as_of_date else None,
            "path_status": item.path_status,
            "path_status_label": status_contract[item.path_status]["label"],
            "path_status_color": status_contract[item.path_status]["color"],
            "explicitly_mentioned": bool(item.detail_report_id and item.path_status != "not_mentioned"),
        } for item in reversed(path_history[:10])]
        latest_report_assessment = latest_report_assessments.get(report_key)
        latest_report_date = latest_report.report_date if latest_report else None
        if (
            latest_report_assessment is not None
            and report_key not in latest_report_path_keys
            and latest_report_date is not None
            and not any(item["report_date"] == latest_report_date.isoformat() for item in recent_path)
        ):
            recent_path.append({
                "id": f"assessment-path:{latest_report_assessment.id}",
                "report_id": latest_report.id,
                "detail_report_id": latest_report.id,
                "has_detailed_report": True,
                "report_date": latest_report_date.isoformat(),
                "market_as_of_date": None,
                "path_status": latest_report_assessment.current_path_status,
                "path_status_label": status_contract[latest_report_assessment.current_path_status]["label"],
                "path_status_color": status_contract[latest_report_assessment.current_path_status]["color"],
                "explicitly_mentioned": latest_report_assessment.explicitly_mentioned,
            })
            recent_path = recent_path[-10:]

        statuses = [item.path_status for item in reversed(path_history)]
        if latest_report_assessment is not None and report_key not in latest_report_path_keys and latest_report_date is not None and (
            not path_history or path_history[0].path_report_date < latest_report_date
        ):
            statuses.append(latest_report_assessment.current_path_status)
        effective = effective_statuses(statuses)
        facts: list[ReportStrategyFact] = []
        for report in published:
            if report.report_date is None or not is_active_report_object_on(report_key, report.report_date):
                continue
            entry = entries_by_pair.get((report.id, report_key))
            assessment = assessments_by_pair.get((report.id, report_key))
            if entry is not None:
                facts.append(ReportStrategyFact(report.id, report.report_date, entry.path_status, entry.explicitly_mentioned))
            elif assessment is not None:
                facts.append(ReportStrategyFact(report.id, report.report_date, assessment.current_path_status, assessment.explicitly_mentioned))
        strategy = effective_strategy_for_trading_day(
            facts,
            current_trading_day,
            next_trading_day=cached_next_trading_day,
        ) if current_trading_day else None
        current_effective = (
            strategy.effective_status if strategy else None
        ) or (effective[-1] if effective else None)
        explicit_statuses = [status for status in statuses if status != "not_mentioned"]
        unsupported = report_key == "hang_seng_tech" or bool(
            market_path and market_path.support_status.value == "unsupported"
        )
        capability = capabilities.get(market_key)
        primary_definition = primary_definitions.get(report_key)
        data_status = (
            "unsupported" if unsupported else "short_history" if report_key == "glass_substrate"
            else "proxy" if primary_definition is not None
            else "unverified" if capability and not capability.selectable_candidates else "supported"
        )
        dormant = classify_dormant_sector(
            path_history,
            controlled_dates,
            market_date_for_report=cached_report_market_date,
        )
        is_low_attention = (
            report_object.lifecycle == "active" and dormant.is_dormant and report_key not in latest_report_keys
        )
        output.append({
            "sector_key": report_key,
            "sector_name": report_object.sector_name,
            "market_path_key": market_key,
            "parent_report_topic": report_key,
            "report_topic_name": report_object.sector_name,
            "group_name": report_object.group_name,
            "group_order": report_object.group_order,
            "overall_order": report_object.display_order,
            "latest_view": latest_view,
            "latest_view_date": explicit_report.report_date.isoformat() if explicit_report and explicit_report.report_date else None,
            "latest_view_report_id": explicit_report.id if explicit_report else None,
            "latest_explicit_view": {
                "report_id": explicit_report.id,
                "report_date": explicit_report.report_date.isoformat(),
                "path": path_entry_payload(explicit_entry) if explicit_entry else assessment_path_payload(explicit_assessment),
                "assessment": explicit_assessment_data,
            } if explicit_report and explicit_report.report_date and explicit_assessment and explicit_assessment_data else None,
            "mentioned_in_latest_published": report_key in latest_report_keys,
            "market_support_status": "unsupported" if unsupported else "supported",
            "data_status": data_status,
            "market_status_detail": "港股跨市场行情暂未接入" if unsupported else "当前无可靠固定主观察标的" if report_key == "glass_substrate" else "研究辅助数据，非生产级行情服务。",
            "current_path_status": statuses[-1] if statuses else "not_mentioned",
            "current_path_status_label": status_contract[statuses[-1]]["label"] if statuses else "未提",
            "reported_status": statuses[-1] if statuses else "not_mentioned",
            "effective_status": current_effective,
            "effective_status_label": status_contract[current_effective]["label"] if current_effective else "暂无",
            "effective_source_report_id": strategy.source_report_id if strategy else None,
            "effective_source_report_date": strategy.source_report_date.isoformat() if strategy and strategy.source_report_date else None,
            "effective_from_trading_date": strategy.effective_from.isoformat() if strategy and strategy.effective_from else None,
            "effective_display_signal": strategy.display_signal if strategy else None,
            "effective_derived_from_transition": strategy.derived_from_transition if strategy else False,
            "recent_path": recent_path,
            "recent_mention_count": sum(item["explicitly_mentioned"] for item in recent_path),
            "is_low_attention": is_low_attention,
            "is_dormant_20d": is_low_attention,
            "dormant_report_overlay_count": dormant.overlay_count,
            "is_pinned_for_research": report_key in pinned,
            "status_changed": len(explicit_statuses) >= 2 and explicit_statuses[-1] != explicit_statuses[-2],
            "latest_market": None,
            "latest_complete_market": None,
            "primary_market": None,
            "recent_10_trading_days": [],
            "date_axis_kinds": {
                "sector_market_history": "market_trading_day",
                "board_recent10_status": "report_date",
                "holding_range": "report_date",
            },
        })
    return output


def sector_payloads(repo: ReportRepository) -> list[dict]:
    from .enhanced import EnhancedReportService, assessment_path_payload, assessment_payload, effective_statuses, path_entry_payload, path_statuses

    bundle = load_seed_bundle()
    registry = load_market_path_registry(bundle)
    capabilities = load_provider_capabilities()
    published = repo.list_reports(published_only=True)
    enhanced = EnhancedReportService(repo.session)
    primary_definitions = {item.market_path_key: item for item in load_security_proxy_registry() if item.status == APPROVED}
    from .intraday import intraday_policy, market_phase, resolve_intraday_data_status
    latest_run = repo.session.scalar(select(MarketRefreshRun).where(MarketRefreshRun.mode == "intraday_refresh").order_by(desc(MarketRefreshRun.started_at)))
    latest_items = {
        item.sector_key: item.status for item in repo.session.scalars(select(MarketRefreshItem).where(MarketRefreshItem.run_id == latest_run.id))
    } if latest_run else {}
    pinned = {item.sector_key for item in repo.session.scalars(select(SectorResearchPreference).where(SectorResearchPreference.is_pinned_for_research.is_(True)))}
    now = datetime.now(timezone.utc)
    phase = market_phase(now)
    latest_explicit = enhanced.latest_explicit_sector_facts(published)
    latest_report_assessments = {
        item.sector_key: item
        for item in enhanced.assessments(published[0].id)
    } if published else {}
    latest_report_path_keys = {
        item.sector_key
        for item in enhanced.path_entries(published[0].id)
    } if published else set()
    latest_report_keys = {
        sector_key
        for sector_key, (report, _, _) in latest_explicit.items()
        if published and report.id == published[0].id
    }
    market_paths_by_parent: dict[str, list] = {}
    for market_path in registry.market_paths:
        market_paths_by_parent.setdefault(market_path.parent_report_topic, []).append(market_path)
    controlled_dates = market_core_completed_dates(repo.session)
    output: list[dict] = []
    for report_object in reader_report_registry():
        report_key = report_object.sector_key
        candidates = market_paths_by_parent.get(report_key, [])
        # The hotel/restaurant report topic keeps the pre-existing hotel path
        # only for legacy snapshots. Its Reader market observation below is
        # always the explicitly configured report-topic primary.
        market_path = next((item for item in candidates if item.market_path_key == report_key), candidates[0] if candidates else None)
        market_key = market_path.market_path_key if market_path is not None else report_key
        explicit_fact = latest_explicit.get(report_key)
        explicit_report, explicit_entry, explicit_assessment = explicit_fact if explicit_fact else (None, None, None)
        latest_report_assessment = latest_report_assessments.get(report_key)
        explicit_assessment_data = assessment_payload(explicit_assessment) if explicit_assessment else None
        latest_view = " · ".join(filter(None, (
            explicit_assessment_data["current_judgement"] if explicit_assessment_data else "",
            explicit_assessment_data["main_basis"] if explicit_assessment_data else "",
            explicit_assessment_data["observation_condition"] if explicit_assessment_data else "",
        ))) or None
        path_history = enhanced.path_history(report_key, through=published[0].report_date if published else None)
        path = path_history[0] if path_history else None
        legacy_market = None if market_path is None or market_key == "hang_seng_tech" else enhanced.latest_market(market_key)
        unsupported = report_key == "hang_seng_tech" or bool(market_path and market_path.support_status.value == "unsupported")
        capability = capabilities.get(market_key)
        primary_definition = primary_definitions.get(report_key)
        data_status = (
            "unsupported" if unsupported else "short_history" if report_key == "glass_substrate"
            else "proxy" if primary_definition is not None
            else "unverified" if capability and not capability.selectable_candidates else "supported"
        )
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
        latest_report_date = published[0].report_date if published else None
        if (
            latest_report_assessment is not None
            and report_key not in latest_report_path_keys
            and latest_report_date is not None
            and not any(item["report_date"] == latest_report_date.isoformat() for item in recent_path)
        ):
            recent_path.append({
                "id": f"assessment-path:{latest_report_assessment.id}",
                "report_id": published[0].id,
                "detail_report_id": published[0].id,
                "has_detailed_report": True,
                "report_date": latest_report_date.isoformat(),
                "market_as_of_date": None,
                "path_status": latest_report_assessment.current_path_status,
                "path_status_label": path_statuses()[latest_report_assessment.current_path_status]["label"],
                "path_status_color": path_statuses()[latest_report_assessment.current_path_status]["color"],
                "explicitly_mentioned": latest_report_assessment.explicitly_mentioned,
            })
            recent_path = recent_path[-10:]
        recent_mention_count = sum(item["explicitly_mentioned"] for item in recent_path)
        statuses = [item.path_status for item in reversed(path_history)]
        if latest_report_assessment is not None and report_key not in latest_report_path_keys and latest_report_date is not None and (
            not path_history or path_history[0].path_report_date < latest_report_date
        ):
            statuses.append(latest_report_assessment.current_path_status)
        effective = effective_statuses(statuses)
        # Board/Reader strategy is a controlled-trading-day projection, not a
        # restatement of the latest report-local marker.  In particular, a
        # report uploaded after a session cannot rewrite that session.
        strategy = enhanced.effective_strategy_for_sector(
            report_key,
            controlled_trading_day_on_or_before(datetime.now(SHANGHAI).date()),
            published,
        )
        current_effective = strategy.effective_status or (effective[-1] if effective else None)
        explicit_statuses = [status for status in statuses if status != "not_mentioned"]
        intervals = enhanced.holding_intervals_for_sector(report_key, published[0].report_date if published else None)
        holding = intervals["active_holding_interval"]
        snapshot = None if unsupported else enhanced.latest_intraday(market_key)
        intraday_status = resolve_intraday_data_status(
            phase=phase, snapshot=snapshot, latest_result=latest_items.get(market_key), now=now,
            stale_after_minutes=intraday_policy()["stale_after_minutes"], unsupported=unsupported,
        )
        if capability and not capability.selectable_candidates:
            intraday_status = "provider_failed"
        dormant = classify_dormant_sector(path_history, controlled_dates)
        is_pinned = report_key in pinned
        is_low_attention = report_object.lifecycle == "active" and dormant.is_dormant and report_key not in latest_report_keys
        attention_level = (
            "high" if is_pinned or report_key in latest_report_keys or holding
            or current_effective in {"turn_hold", "hold", "strong_watch"}
            else "low" if is_low_attention else "normal"
        )
        primary_market = primary_history(repo.session, primary_definition) if primary_definition is not None else None
        recent_days = primary_market["history"] if primary_market is not None else []
        output.append({
            "sector_key": report_key,
            "sector_name": report_object.sector_name,
            "market_path_key": market_key,
            "parent_report_topic": report_key,
            "report_topic_name": report_object.sector_name,
            "group_name": report_object.group_name,
            "group_order": report_object.group_order,
            "overall_order": report_object.display_order,
            "latest_view": latest_view,
            "latest_view_date": explicit_report.report_date.isoformat() if explicit_report and explicit_report.report_date else None,
            "latest_view_report_id": explicit_report.id if explicit_report else None,
            "latest_explicit_view": {
                "report_id": explicit_report.id,
                "report_date": explicit_report.report_date.isoformat(),
                "path": path_entry_payload(explicit_entry) if explicit_entry else assessment_path_payload(explicit_assessment),
                "assessment": explicit_assessment_data,
            } if explicit_report and explicit_report.report_date and explicit_assessment and explicit_assessment_data else None,
            "mentioned_in_latest_published": report_key in latest_report_keys,
            "market_support_status": "unsupported" if unsupported else "supported",
            "data_status": data_status,
            "market_status_detail": "港股跨市场行情暂未接入" if unsupported else "当前无可靠固定主观察标的" if report_key == "glass_substrate" else "研究辅助数据，非生产级行情服务。",
            "current_path_status": statuses[-1] if statuses else "not_mentioned",
            "current_path_status_label": path_statuses()[statuses[-1]]["label"] if statuses else "未提",
            "reported_status": statuses[-1] if statuses else "not_mentioned",
            "effective_status": current_effective,
            "effective_status_label": path_statuses()[current_effective]["label"] if current_effective else "暂无",
            "effective_source_report_id": strategy.source_report_id,
            "effective_source_report_date": strategy.source_report_date.isoformat() if strategy.source_report_date else None,
            "effective_from_trading_date": strategy.effective_from.isoformat() if strategy.effective_from else None,
            "effective_display_signal": strategy.display_signal,
            "effective_derived_from_transition": strategy.derived_from_transition,
            "latest_market": None,
            "latest_complete_market": None,
            "primary_market": primary_market,
            "intraday_snapshot": snapshot,
            "intraday_status": intraday_status,
            "intraday_last_attempt_at": _display_short_time(latest_run.started_at) if latest_run else None,
            "recent_10_trading_days": recent_days,
            "date_axis_kinds": {
                "sector_market_history": "market_trading_day",
                "board_recent10_status": "report_date",
                "holding_range": "report_date",
            },
            "legacy_market_audit": legacy_market,
            "recent_path": recent_path,
            "recent_mention_count": recent_mention_count,
            "attention_level": attention_level,
            "active_holding_interval": holding,
            "historical_holding_intervals": intervals["historical_holding_intervals"],
            "strict_holding_interval": intervals["strict_holding_interval"],
            "broad_holding_interval": intervals["broad_holding_interval"],
            "historical_strict_intervals": intervals["historical_strict_intervals"],
            "historical_broad_intervals": intervals["historical_broad_intervals"],
            "is_low_attention": is_low_attention,
            "is_dormant_20d": is_low_attention,
            "dormant_report_overlay_count": dormant.overlay_count,
            "is_pinned_for_research": is_pinned,
            "status_changed": len(explicit_statuses) >= 2 and explicit_statuses[-1] != explicit_statuses[-2],
        })
    return output
