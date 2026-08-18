from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, sessionmaker

from leopard_project.config import load_seed_bundle
from leopard_project.market_paths import load_market_path_registry, market_path_for_key, report_topic_sector
from leopard_project.providers.capabilities import load_provider_capabilities, provider_capability_summary
from leopard_project.security_proxy_observation import APPROVED, load_security_proxy_registry
from leopard_project.trading_calendar import report_market_date

from .auth import Principal
from .catalog import configured_groups
from .enhanced import (
    EnhancedReportService,
    active_holding_interval,
    assessment_payload,
    effective_statuses,
    market_payload,
    path_entry_payload,
    path_status_document,
    path_statuses,
)
from .models import (
    IntradayRefreshSession,
    LiveMarketAnchorDaily,
    MarketRefreshItem,
    MarketRefreshRun,
    Report,
    ReportSectorMarketSnapshot,
    ReportStatus,
    SectorDailyBar,
    SectorIndicatorSnapshot,
    SectorResearchPreference,
    SectorPathHistoryEntry,
    SectorPathEntry,
    SecurityProxyDaily,
)
from .schemas import (
    ApiListItem,
    ApiObjectResponse,
    MarketBindingRequest,
    MarketRefreshRequest,
    PathEntryPatch,
    SectorAssessmentPatch,
)
from .serializers import report_payload
from .services import WebDomainError
from .market_ingestion import import_real_market, refresh_real_market
from .intraday import IntradayRefreshCoordinator, intraday_policy, resolve_intraday_data_status
from .market_automation import EodBackfillCoordinator
from .live_market_anchor import LiveShanghaiMarketAnchorService
from leopard_project.live_market_anchor_daily import recent_defense_line_validations
from .path_history import matrix_dates
from .primary_market_observation import primary_history


def register_enhanced_routes(
    app: FastAPI,
    sessions: sessionmaker[Session],
    optional_principal: Callable,
    admin: Callable,
    required_report: Callable,
    data_mode: str = "test",
    intraday: IntradayRefreshCoordinator | None = None,
    eod_backfill: EodBackfillCoordinator | None = None,
    live_market_anchor: LiveShanghaiMarketAnchorService | None = None,
) -> None:
    intraday = intraday or IntradayRefreshCoordinator(sessions)
    eod_backfill = eod_backfill or EodBackfillCoordinator(sessions)
    live_market_anchor = live_market_anchor or app.state.live_market_anchor
    def db_session():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    def readable(report: Report, current: Principal | None) -> Report:
        if report.status != ReportStatus.PUBLISHED.value and (current is None or current.role != "admin"):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        return report

    def snapshot_map(service: EnhancedReportService, report_id: str) -> dict[str, dict]:
        return {item["sector_key"]: item for item in service.report_snapshots(report_id)}

    def latest_intraday_item_status(session: Session, sector_key: str) -> str | None:
        run = session.scalar(select(MarketRefreshRun).where(MarketRefreshRun.mode == "intraday_refresh").order_by(desc(MarketRefreshRun.started_at)))
        if run is None:
            return None
        item = session.scalar(select(MarketRefreshItem).where(
            MarketRefreshItem.run_id == run.id, MarketRefreshItem.sector_key == sector_key,
        ))
        return item.status if item else None

    def objective_market_anchor(session: Session) -> dict:
        """Expose Shanghai market facts without a report or defense dependency."""
        live = live_market_anchor.observe(market_path="", core_view="")
        quote_datetime = datetime.fromisoformat(live["quote_datetime"]) if live["quote_datetime"] else None
        now = datetime.now(timezone.utc)
        fresh_live = quote_datetime is not None and quote_datetime.astimezone(timezone.utc) >= now - timedelta(minutes=15)
        if live["quote_status"] == "available" and fresh_live:
            return {
                "data_mode": "live",
                "market_context": "objective_market_anchor",
                "quote_status": "available",
                "trading_date": live["quote_datetime"][:10] if live["quote_datetime"] else None,
                "value": live["current"],
                "current": live["current"],
                "pre_close": live["pre_close"],
                "change": live["change"],
                "pct_change": live["pct_change"],
                "quote_datetime": live["quote_datetime"],
                "captured_at": None,
                "source": live["provider"],
                "provider": live["provider"],
                "provider_role": live["provider_role"],
                "error_code": None,
                "index_name": live["index_name"],
                "symbol": live["symbol"],
            }
        completed = session.scalar(select(LiveMarketAnchorDaily).where(
            LiveMarketAnchorDaily.symbol == "sh000001",
        ).order_by(desc(LiveMarketAnchorDaily.trading_date)))
        if completed is not None:
            return {
                "data_mode": "completed_eod",
                "market_context": "objective_market_anchor",
                "quote_status": "available",
                "trading_date": completed.trading_date.isoformat(),
                "value": float(completed.close),
                "current": float(completed.close),
                "pre_close": float(completed.pre_close),
                "change": float(completed.close - completed.pre_close),
                "pct_change": float(completed.pct_change),
                "quote_datetime": completed.quote_datetime.isoformat(),
                "captured_at": completed.fetched_at.isoformat(),
                "source": completed.source,
                "provider": completed.source,
                "provider_role": "diagnostic_provider",
                "error_code": None,
                "index_name": "上证指数",
                "symbol": completed.symbol,
            }
        return {
            "data_mode": "unavailable", "market_context": "objective_market_anchor",
            "quote_status": "unavailable", "trading_date": None, "value": None,
            "current": None, "pre_close": None, "change": None, "pct_change": None,
            "quote_datetime": None, "captured_at": None, "source": None,
            "provider": live["provider"], "provider_role": live["provider_role"],
            "error_code": live["error_code"], "index_name": "上证指数", "symbol": "sh000001",
        }

    def completed_market_anchor_history(session: Session, *, limit: int = 10) -> dict:
        """Read the independently captured Shanghai closes, never report data.

        The current quote remains a separate live fact.  This history contains
        only completed EOD records actually present in the database and is
        deliberately not padded to a requested display length.
        """
        rows = list(reversed(session.scalars(select(LiveMarketAnchorDaily).where(
            LiveMarketAnchorDaily.symbol == "sh000001",
        ).order_by(desc(LiveMarketAnchorDaily.trading_date)).limit(limit)).all()))
        return {
            "market_context": "objective_market_anchor_history",
            "index_name": "上证指数",
            "symbol": "sh000001",
            "max_days": limit,
            "completed_days": len(rows),
            "items": [{
                "trading_date": item.trading_date.isoformat(),
                "close": float(item.close),
                "pre_close": float(item.pre_close),
                "change": float(item.close - item.pre_close),
                "pct_change": float(item.pct_change),
                "data_mode": "completed_eod",
                "quote_datetime": item.quote_datetime.isoformat(),
                "source": item.source,
            } for item in rows],
        }

    def report_defense_payload(report: Report) -> dict:
        metadata = json.loads(report.interpretation_meta_json or "{}")
        defense = live_market_anchor.defense_payload(
            market_path=report.market_path,
            core_view=report.core_view,
            parsed_primary=(metadata.get("defense_lines") or {}).get("primary_defense_line"),
        )
        return {
            **{
                key: defense[key]
                for key in (
                    "defense_line_value", "defense_line_source", "stand_above_condition",
                    "break_below_condition", "validation_conditions", "distance_points",
                    "distance_pct", "defense_position",
                )
            },
            "market_context_note": "报告攻防线仅来自本报告；当前或最近完整上证数据由独立市场锚点读取。",
        }

    @app.get("/api/v1/path-statuses", response_model=ApiObjectResponse)
    def status_contract(current: Principal | None = Depends(optional_principal)) -> dict:
        return path_status_document()

    @app.get("/api/v1/reports/{report_id}/enhanced", response_model=ApiObjectResponse)
    def enhanced_report(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        report = readable(required_report(report_id, session), current)
        service = EnhancedReportService(session)
        snapshots = snapshot_map(service, report.id)
        assessments = []
        for item in service.assessments(report.id):
            payload = assessment_payload(item, snapshots.get(item.sector_key))
            payload["active_holding_interval"] = service.holding_interval_for_sector(report, item.sector_key)
            assessments.append(payload)
        paths = [path_entry_payload(item) for item in service.path_entries(report.id)]
        report_defense = report_defense_payload(report)
        groups: dict[str, list[dict]] = {}
        for item in assessments:
            groups.setdefault(item["current_path_status"], []).append(item)
        return {
            "report": report_payload(report),
            "path_entries": paths,
            "sector_assessments": assessments,
            "status_groups": [{"status": key, "count": len(value), "items": value} for key, value in groups.items()],
            "market_snapshots": list(snapshots.values()),
            "report_defense": report_defense,
            "recent_defense_line_validations": recent_defense_line_validations(session),
            "comparison": service.comparison(report),
            # Compatibility only.  The Viewer must never treat this legacy
            # report-snapshot count as a market-data quality gate.
            "market_data_attached": bool(snapshots),
            "data_notice": "研究辅助数据，非生产级行情服务。",
        }

    @app.get("/api/v1/reports/{report_id}/path-matrix", response_model=ApiObjectResponse)
    def path_matrix(
        report_id: str,
        periods: str = Query(default="20", pattern="^(10|20|40|all)$", alias="periods"),
        period: str | None = Query(default=None, pattern="^(10|20|40|all)$", alias="period"),
        current: Principal | None = Depends(optional_principal),
        session: Session = Depends(db_session),
    ) -> dict:
        report = readable(required_report(report_id, session), current)
        service = EnhancedReportService(session)
        selected_period = period or periods
        available_dates = list(session.scalars(select(SectorPathHistoryEntry.path_report_date).where(
            SectorPathHistoryEntry.path_report_date <= report.report_date,
        ).distinct().order_by(SectorPathHistoryEntry.path_report_date)))
        if not available_dates:
            fallback_reports = list(session.scalars(select(Report).where(
                Report.status == ReportStatus.PUBLISHED.value,
                Report.report_date <= report.report_date,
            ).order_by(Report.report_date)))
            selected_period = period or periods
            if selected_period != "all":
                fallback_reports = fallback_reports[-int(selected_period):]
            fallback_paths = {
                item.id: {entry.sector_key: entry for entry in service.path_entries(item.id)}
                for item in fallback_reports
            }
            return {
                "caption": "板块历史路径矩阵",
                "period": selected_period,
                "default_period": "20",
                "available_period_count": len(fallback_reports),
                "dates": [{
                    "report_id": item.id,
                    "detail_report_id": item.id,
                    "has_detailed_report": True,
                    "report_date": item.report_date.isoformat(),
                    "market_as_of_date": report_market_date(item.report_date).isoformat() if report_market_date(item.report_date) else None,
                    "market_weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][report_market_date(item.report_date).weekday()] if report_market_date(item.report_date) else None,
                    "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][item.report_date.weekday()],
                    "is_weekend_report": item.report_date.weekday() >= 5,
                } for item in fallback_reports],
                "groups": configured_groups(),
                "rows": [{
                    "sector_key": sector.sector_key,
                    "sector_name": sector.sector_name,
                    "group_name": sector.category_level_1,
                    "group_order": sector.group_order,
                    "overall_order": sector.overall_order,
                    "cells": [{
                        "report_id": item.id,
                        "detail_report_id": item.id,
                        "has_detailed_report": True,
                        "report_date": item.report_date.isoformat(),
                        **path_entry_payload(fallback_paths[item.id][sector.sector_key]),
                        "daily_return": None,
                        "market_as_of_date": report_market_date(item.report_date).isoformat() if report_market_date(item.report_date) else None,
                        "market_data_status": "unavailable",
                        "market_overlay": {
                            "kind": "unavailable", "label": "—",
                            "market_date": report_market_date(item.report_date).isoformat() if report_market_date(item.report_date) else None,
                            "pct_change": None, "instruments": [],
                        },
                    } for item in fallback_reports],
                } for sector in sorted(load_seed_bundle().sectors, key=lambda item: item.overall_order)],
                "status_contract": path_status_document(),
                "history_origin": "uploaded_reports_fallback",
            }
        if selected_period != "all":
            available_dates = available_dates[-int(selected_period):]
        reports = {
            item.report_date: item
            for item in session.scalars(select(Report).where(
                Report.status == ReportStatus.PUBLISHED.value,
                Report.report_date.in_(available_dates),
                Report.is_current.is_(True),
            ))
            if item.report_date
        }
        entries = list(session.scalars(select(SectorPathHistoryEntry).where(
            SectorPathHistoryEntry.path_report_date.in_(available_dates)
        ))) if available_dates else []
        by_sector_date = {(item.sector_key, item.path_report_date): item for item in entries}
        mapped_market_dates = {path_date: report_market_date(path_date) for path_date in available_dates}
        weekday_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        columns = [{
            "report_id": reports[path_date].id if path_date in reports else f"path:{path_date.isoformat()}",
            "detail_report_id": reports[path_date].id if path_date in reports else None,
            "has_detailed_report": path_date in reports,
            "report_date": path_date.isoformat(),
            "market_as_of_date": mapped_market_dates[path_date].isoformat() if mapped_market_dates[path_date] else None,
            "market_weekday": weekday_labels[mapped_market_dates[path_date].weekday()] if mapped_market_dates[path_date] else None,
            "weekday": weekday_labels[path_date.weekday()],
            "is_weekend_report": path_date.weekday() >= 5,
        } for path_date in available_dates]
        bundle = load_seed_bundle()
        proxy_definitions = {
            item.market_path_key: item
            for item in load_security_proxy_registry()
            if item.status == APPROVED
        }
        proxy_symbols = tuple(sorted({
            instrument.symbol
            for definition in proxy_definitions.values()
            for instrument in definition.instruments
            if instrument.enabled
        }))
        # The controlled calendar resolves each report date exactly once.  A
        # later absent daily record stays absent; no data-date fallback is
        # permitted after this mapping.
        maximum_market_date = max((item for item in mapped_market_dates.values() if item is not None), default=None)
        proxy_rows = list(session.scalars(select(SecurityProxyDaily).where(
            SecurityProxyDaily.symbol.in_(proxy_symbols),
            SecurityProxyDaily.trading_date <= maximum_market_date,
        ).order_by(SecurityProxyDaily.symbol, SecurityProxyDaily.trading_date))) if proxy_symbols and maximum_market_date else []
        proxy_by_symbol_date = {(item.symbol, item.trading_date): item for item in proxy_rows}
        proxy_previous_close: dict[tuple[str, date], float | None] = {}
        previous_by_symbol: dict[str, float] = {}
        for item in proxy_rows:
            proxy_previous_close[(item.symbol, item.trading_date)] = previous_by_symbol.get(item.symbol)
            previous_by_symbol[item.symbol] = float(item.close)

        def market_overlay(sector_key: str, entry: SectorPathHistoryEntry, market_date: date | None) -> dict:
            """Describe one fixed, exact-date Reader market observation.

            Reader cells use the registry's stable primary security only.  The
            remaining fixed securities survive in the detail payload and are
            never combined into a sector return.
            """
            definition = proxy_definitions.get(sector_key)
            if definition is None or market_date is None:
                return {
                    "kind": "unavailable", "label": "—",
                    "market_date": market_date.isoformat() if market_date else None,
                    "pct_change": None, "primary": None, "instruments": [],
                }
            primary = definition.primary_observation
            primary_record = proxy_by_symbol_date.get((primary.symbol, market_date)) if primary else None
            if primary is None or primary_record is None:
                return {
                    "kind": "unavailable", "label": "—",
                    "market_date": market_date.isoformat(), "pct_change": None,
                    "primary": None, "instruments": [],
                }
            primary_previous = proxy_previous_close.get((primary.symbol, market_date))
            primary_close = float(primary_record.close)
            primary_pct = ((primary_close / primary_previous - 1) * 100) if primary_previous and primary_previous > 0 else None
            primary_payload = {
                "name": primary.security_name, "role": primary.proxy_role,
                "security_code": primary.reader_code,
                "close": primary_close, "pct_change": primary_pct,
                "trading_date": market_date.isoformat(),
            }
            instruments = []
            for instrument in definition.instruments:
                if not instrument.enabled or instrument.symbol == primary.symbol:
                    continue
                record = proxy_by_symbol_date.get((instrument.symbol, market_date))
                if record is None:
                    continue
                previous_close = proxy_previous_close.get((instrument.symbol, market_date))
                close = float(record.close)
                pct_change = ((close / previous_close - 1) * 100) if previous_close and previous_close > 0 else None
                instruments.append({
                    "name": instrument.security_name,
                    "role": instrument.proxy_role,
                    "security_code": instrument.reader_code,
                    "close": close,
                    "pct_change": pct_change,
                    "trading_date": market_date.isoformat(),
                })
            return {
                "kind": "primary",
                "label": f"{primary.security_name} {primary_pct:+.2f}%" if primary_pct is not None else f"{primary.security_name} —",
                "market_date": market_date.isoformat(), "pct_change": primary_pct,
                "primary": primary_payload, "instruments": instruments,
            }
        rows = []
        for sector in sorted(bundle.sectors, key=lambda item: item.overall_order):
            rows.append({
                "sector_key": sector.sector_key,
                "sector_name": sector.sector_name,
                "group_name": sector.category_level_1,
                "group_order": sector.group_order,
                "overall_order": sector.overall_order,
                "cells": [{
                    "id": (entry := by_sector_date[(sector.sector_key, path_date)]).id,
                    "sector_key": sector.sector_key,
                    "sector_name": sector.sector_name,
                    "report_id": reports[path_date].id if path_date in reports else f"path:{path_date.isoformat()}",
                    "detail_report_id": reports[path_date].id if path_date in reports else None,
                    "has_detailed_report": path_date in reports,
                    "report_date": path_date.isoformat(),
                    "path_status": entry.path_status,
                    "path_status_label": path_statuses()[entry.path_status]["label"],
                    "path_status_color": path_statuses()[entry.path_status]["color"],
                    "explicitly_mentioned": path_date in reports and entry.path_status != "not_mentioned",
                    "judgement_summary": "",
                    "source_text_reference": "",
                    "review_status": "frozen_history",
                    "manually_modified": False,
                    "revision_id": entry.source_report_id,
                    "daily_return": float(entry.frozen_daily_pct_change) if entry.frozen_daily_pct_change is not None else None,
                    "market_as_of_date": mapped_market_dates[path_date].isoformat() if mapped_market_dates[path_date] else None,
                    "market_data_status": entry.market_data_status,
                    "market_overlay": market_overlay(sector.sector_key, entry, mapped_market_dates[path_date]),
                } for path_date in available_dates],
            })
        return {
            "caption": "板块历史路径矩阵",
            "period": selected_period,
            "default_period": "20",
            "available_period_count": len(available_dates),
            "dates": columns,
            "groups": configured_groups(),
            "rows": rows,
            "status_contract": path_status_document(),
            "history_origin": "sector_path_history_ledger",
        }

    @app.get("/api/v1/reports/{report_id}/sector-assessments", response_model=list[ApiListItem])
    def report_assessments(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> list[dict]:
        report = readable(required_report(report_id, session), current)
        service = EnhancedReportService(session)
        snapshots = snapshot_map(service, report.id)
        return [assessment_payload(item, snapshots.get(item.sector_key)) for item in service.assessments(report.id)]

    @app.get("/api/v1/reports/{report_id}/market-snapshots", response_model=list[ApiListItem])
    def report_market_snapshots(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> list[dict]:
        report = readable(required_report(report_id, session), current)
        return EnhancedReportService(session).report_snapshots(report.id)

    @app.get("/api/v1/reports/{report_id}/comparison", response_model=ApiObjectResponse)
    def report_comparison(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        report = readable(required_report(report_id, session), current)
        return EnhancedReportService(session).comparison(report)

    @app.get("/api/v1/sectors/{sector_key}/research", response_model=ApiObjectResponse)
    def sector_research(
        sector_key: str,
        path_periods: int = Query(default=20, ge=10, le=60),
        market_days: int = Query(default=20, ge=20, le=60),
        path_period: int | None = Query(default=None, ge=5, le=60),
        current: Principal | None = Depends(optional_principal),
        session: Session = Depends(db_session),
    ) -> dict:
        market_path = market_path_for_key(sector_key)
        if market_path is None:
            raise WebDomainError("sector_not_found", "Sector not found", 404)
        sector = report_topic_sector(market_path)
        market_key = market_path.market_path_key
        report_key = market_path.parent_report_topic
        service = EnhancedReportService(session)
        reports = list(session.scalars(select(Report).where(Report.status == "published").order_by(desc(Report.report_date))))
        selected_path_period = path_period if path_period is not None else path_periods
        if selected_path_period not in {10, 20, 40, 60}:
            raise WebDomainError("invalid_path_period", "路径期数仅支持10、20、40或60期", 422)
        if market_days not in {20, 40, 60}:
            raise WebDomainError("invalid_market_days", "行情范围仅支持20、40或60个交易日", 422)
        path_rows = service.path_history(report_key, selected_path_period, reports[0].report_date if reports else None)
        all_path_rows = service.path_history(report_key, through=reports[0].report_date if reports else None)
        report_by_id = {item.id: item for item in reports}
        latest_report_entry = session.scalar(
            select(SectorPathEntry).where(
                SectorPathEntry.report_id == reports[0].id,
                SectorPathEntry.sector_key == report_key,
            )
        ) if reports else None
        assessment_by_report = {
            item.id: next((assessment for assessment in service.assessments(item.id) if assessment.sector_key == report_key), None)
            for item in reports
        }
        detailed_history = []
        latest_explicit = None
        for report in reports:
            entry = session.scalar(select(SectorPathEntry).where(SectorPathEntry.report_id == report.id, SectorPathEntry.sector_key == report_key))
            assessment = assessment_by_report[report.id]
            if entry:
                item = {
                    "report_id": report.id,
                    "report_date": report.report_date.isoformat(),
                    "path": path_entry_payload(entry),
                    "assessment": assessment_payload(assessment) if assessment else None,
                    "report_snapshot": None if report_key == "hotel_catering" else next((row for row in service.report_snapshots(report.id) if row["sector_key"] == market_key), None),
                }
                detailed_history.append(item)
                if latest_explicit is None and entry.explicitly_mentioned and entry.path_status != "not_mentioned":
                    latest_explicit = item
        chronological = list(reversed(path_rows))
        effective = effective_statuses([item.path_status for item in chronological])
        effective_by_date = {item.path_report_date: value for item, value in zip(chronological, effective)}
        recent_path_entries = [{
            "id": item.id,
            "report_id": item.detail_report_id or f"path:{item.path_report_date.isoformat()}",
            "detail_report_id": item.detail_report_id,
            "has_detailed_assessment": bool(item.detail_report_id and assessment_by_report.get(item.detail_report_id)),
            "report_date": item.path_report_date.isoformat(),
            "market_as_of_date": item.market_as_of_date.isoformat() if item.market_as_of_date else None,
            "reported_status": item.path_status,
            "effective_status": effective_by_date.get(item.path_report_date),
            "path": {
                "id": item.id,
                "sector_key": item.sector_key,
                "sector_name": item.sector_name,
                "path_status": item.path_status,
                "path_status_label": path_statuses()[item.path_status]["label"],
                "path_status_color": path_statuses()[item.path_status]["color"],
                "explicitly_mentioned": bool(item.detail_report_id and item.path_status != "not_mentioned"),
                "judgement_summary": "",
                "source_text_reference": "",
                "review_status": "frozen_history",
                "manually_modified": False,
                "revision_id": item.source_report_id,
            },
        } for item in path_rows]
        if not recent_path_entries and reports:
            matrix = (json.loads(reports[0].interpretation_meta_json or "{}").get("pdf_history_matrix") or {})
            source_row = next((item for item in matrix.get("rows", []) if item.get("sector_key") == report_key), None)
            raw_dates = matrix.get("dates") or []
            if source_row and len(source_row.get("statuses") or []) == len(raw_dates):
                resolved = matrix_dates(reports[0].report_date, raw_dates)
                selected = list(zip(resolved, source_row["statuses"]))[-selected_path_period:]
                selected_effective = effective_statuses([status for _, status in selected])
                detailed_by_date = {item.report_date: item for item in reports if item.report_date}
                recent_path_entries = list(reversed([{
                    "id": f"path:{report_key}:{path_date.isoformat()}",
                    "report_id": detailed_by_date[path_date].id if path_date in detailed_by_date else f"path:{path_date.isoformat()}",
                    "detail_report_id": detailed_by_date[path_date].id if path_date in detailed_by_date else None,
                    "has_detailed_assessment": path_date in detailed_by_date,
                    "report_date": path_date.isoformat(),
                    "market_as_of_date": None,
                    "reported_status": status,
                    "effective_status": effective_value,
                    "path": {
                        "id": f"path:{report_key}:{path_date.isoformat()}", "sector_key": report_key,
                        "sector_name": sector.sector_name, "path_status": status,
                        "path_status_label": path_statuses()[status]["label"],
                        "path_status_color": path_statuses()[status]["color"],
                        "explicitly_mentioned": path_date in detailed_by_date and status != "not_mentioned",
                        "judgement_summary": "", "source_text_reference": "", "review_status": "pdf_history_only",
                        "manually_modified": False, "revision_id": reports[0].id,
                    },
                } for (path_date, status), effective_value in zip(selected, selected_effective)]))
        unsupported = market_path.support_status.value == "unsupported"
        intervals = service.holding_intervals_for_sector(report_key, reports[0].report_date if reports else None)
        latest_market = None if unsupported else service.latest_market(market_key)
        recent_days = [] if unsupported else service.recent_complete_days(market_key)
        if latest_market is not None:
            latest_market["recent_10_trading_days"] = recent_days
        intraday_snapshot = None if unsupported else service.latest_intraday(market_key)
        runtime_status = intraday.status()
        latest_intraday_result = latest_intraday_item_status(session, market_key)
        runtime_phase = runtime_status["market_phase"]
        resolved_intraday_status = resolve_intraday_data_status(
            phase=runtime_phase, snapshot=intraday_snapshot, latest_result=latest_intraday_result,
            now=datetime.now(timezone.utc), stale_after_minutes=intraday_policy()["stale_after_minutes"], unsupported=unsupported,
        )
        capability = load_provider_capabilities().get(market_key)
        if capability and not capability.selectable_candidates:
            resolved_intraday_status = "provider_failed"
        primary_definition = next((item for item in load_security_proxy_registry() if item.market_path_key == market_key and item.status == APPROVED), None)
        primary_market = primary_history(session, primary_definition) if primary_definition is not None else None
        pref = session.get(SectorResearchPreference, market_key)
        is_pinned = bool(pref and pref.is_pinned_for_research)
        last_ten = all_path_rows[:10]
        data_status = "unsupported" if unsupported else "proxy" if market_path.mapping_type == "proxy" else "short_history" if market_key == "glass_substrate" else "unverified" if capability and not capability.selectable_candidates else "supported"
        is_low_attention = bool(
            len(last_ten) == 10 and all(item.path_status == "not_mentioned" for item in last_ten)
            and not intervals["strict_holding_interval"] and not intervals["broad_holding_interval"]
            and (effective_statuses([item.path_status for item in reversed(all_path_rows)])[-1] if all_path_rows else None) not in {"turn_hold", "hold", "strong_watch"}
            and data_status == "supported" and not is_pinned
        )
        return {
            "sector_key": market_key,
            "sector_name": market_path.display_name,
            "market_path_key": market_key,
            "parent_report_topic": report_key,
            "report_topic_name": sector.sector_name,
            "group_name": sector.category_level_1,
            "latest_explicit_view": latest_explicit,
            "latest_report_date": reports[0].report_date.isoformat() if reports and reports[0].report_date else None,
            "latest_report_explicitly_mentioned": bool(
                latest_report_entry
                and latest_report_entry.explicitly_mentioned
                and latest_report_entry.path_status != "not_mentioned"
            ) if reports else None,
            "current_latest_market": latest_market,
            "latest_complete_market": latest_market,
            "primary_market": primary_market,
            "recent_10_trading_days": recent_days,
            "intraday_snapshot": intraday_snapshot,
            "intraday_status": resolved_intraday_status,
            "intraday_session": runtime_status,
            "market_support_status": "unsupported" if unsupported else "supported",
            "data_status": data_status,
            "market_status_detail": "港股跨市场行情暂未接入" if unsupported else market_path.display_detail if market_key in {"hotel", "catering"} else "历史较短，指标不足时显示历史不足" if market_key == "glass_substrate" else "研究辅助数据，非生产级行情服务。",
            "recent_path": recent_path_entries,
            "recent_path_entries": recent_path_entries,
            "path_periods": selected_path_period,
            "available_path_periods": len(all_path_rows) or len(recent_path_entries),
            "reported_status": path_rows[0].path_status if path_rows else recent_path_entries[0]["reported_status"] if recent_path_entries else "not_mentioned",
            "effective_status": effective_statuses([item.path_status for item in reversed(all_path_rows)])[-1] if all_path_rows else recent_path_entries[0]["effective_status"] if recent_path_entries else None,
            "active_holding_interval": None if report_key == "hotel_catering" else intervals["active_holding_interval"],
            "historical_holding_intervals": [] if report_key == "hotel_catering" else intervals["historical_holding_intervals"],
            "strict_holding_interval": None if report_key == "hotel_catering" else intervals["strict_holding_interval"],
            "broad_holding_interval": None if report_key == "hotel_catering" else intervals["broad_holding_interval"],
            "historical_strict_intervals": [] if report_key == "hotel_catering" else intervals["historical_strict_intervals"],
            "historical_broad_intervals": [] if report_key == "hotel_catering" else intervals["historical_broad_intervals"],
            "is_low_attention": is_low_attention,
            "is_pinned_for_research": is_pinned,
            "market_history": [] if unsupported else service.market_history(market_key, market_days),
            "market_days": market_days,
            "history": detailed_history,
            "detailed_history": detailed_history,
        }

    @app.get("/api/v1/sectors/{sector_key}/market/latest", response_model=ApiObjectResponse)
    def sector_latest_market(sector_key: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        market_path = market_path_for_key(sector_key)
        if market_path is None:
            raise WebDomainError("sector_not_found", "Sector not found", 404)
        if market_path.support_status.value == "unsupported":
            return {"sector_key": sector_key, "status": "unsupported", "detail": "港股跨市场行情暂未接入"}
        payload = EnhancedReportService(session).latest_market(sector_key)
        return {"sector_key": sector_key, "status": "available" if payload else "unavailable", "market": payload}

    @app.get("/api/v1/market/anchor", response_model=ApiObjectResponse)
    def market_anchor(current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        return objective_market_anchor(session)

    @app.get("/api/v1/market/anchor/history", response_model=ApiObjectResponse)
    def market_anchor_history(current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        return completed_market_anchor_history(session)

    @app.post("/api/v1/admin/reports/{report_id}/enhance/parse", response_model=ApiObjectResponse)
    def enhance_parse(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        service = EnhancedReportService(session)
        parse_result = service.parse_structured_text(report, current.username)
        return {"report_id": report.id, "enhanced_status": report.enhanced_status, "path_entry_count": len(service.path_entries(report.id)), "external_llm_calls": 0, **parse_result}

    @app.patch("/api/v1/admin/reports/{report_id}/path-entries/{entry_id}", response_model=ApiObjectResponse)
    def patch_path(report_id: str, entry_id: str, payload: PathEntryPatch, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        item = EnhancedReportService(session).update_path(report, entry_id, payload.model_dump(exclude_unset=True), current.username)
        return path_entry_payload(item)

    @app.patch("/api/v1/admin/reports/{report_id}/sector-assessments/{assessment_id}", response_model=ApiObjectResponse)
    def patch_assessment(report_id: str, assessment_id: str, payload: SectorAssessmentPatch, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        item = EnhancedReportService(session).update_assessment(report, assessment_id, payload.model_dump(exclude_unset=True), current.username)
        return assessment_payload(item)

    @app.post("/api/v1/admin/reports/{report_id}/market-binding", response_model=ApiObjectResponse)
    def market_binding(report_id: str, payload: MarketBindingRequest, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = EnhancedReportService(session).bind_market_date(required_report(report_id, session), payload.market_as_of_date, payload.confirmed, current.username)
        return report_payload(report, admin=True)

    @app.post("/api/v1/admin/market/refresh", response_model=ApiObjectResponse)
    def market_refresh(payload: MarketRefreshRequest, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        if not payload.confirmed_research_only:
            raise WebDomainError("manual_confirmation_required", "必须确认研究辅助数据口径后才能刷新", 409)
        if payload.mode == "manual_real_refresh":
            if data_mode != "real_local":
                raise WebDomainError("real_refresh_real_local_only", "真实刷新只允许在real_local显式执行", 409)
            if payload.as_of_date is None:
                raise WebDomainError("as_of_date_required", "真实刷新必须明确截至日期", 422)
            run = refresh_real_market(session, current.username, sector_keys=payload.sector_keys, as_of=payload.as_of_date)
        elif payload.mode == "controlled_fixture" and data_mode != "real_local":
            run = EnhancedReportService(session).fixture_refresh(current.username, payload.sector_keys)
        else:
            raise WebDomainError("fixture_forbidden_in_real_local", "真实本地模式禁止载入fixture行情", 409)
        return {
            "run_id": run.id,
            "status": run.status,
            "requested_count": run.requested_count,
            "success_count": run.success_count,
            "failure_count": run.failure_count,
            "intraday_count": run.intraday_count,
            "stale_count": run.stale_count,
            "short_history_count": run.short_history_count,
            "unsupported_count": run.unsupported_count,
            "provider_role": run.provider_role,
        }

    @app.post("/api/v1/admin/market/import", response_model=ApiObjectResponse)
    async def market_import(
        file: UploadFile = File(...),
        confirmed: bool = Form(False),
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
    ) -> dict:
        if data_mode != "real_local":
            raise WebDomainError("real_import_real_local_only", "真实行情导入只允许在real_local执行", 409)
        payload = await file.read()
        if len(payload) > 10 * 1024 * 1024:
            raise WebDomainError("market_import_too_large", "行情导入文件不得超过10MB", 413)
        return import_real_market(session, current.username, file.filename or "market.csv", payload, confirmed=confirmed)

    @app.get("/api/v1/market/status", response_model=ApiObjectResponse)
    def market_status(current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        latest_run = session.scalar(select(MarketRefreshRun).order_by(desc(MarketRefreshRun.started_at)))
        latest_bar = session.scalar(select(SectorDailyBar).where(SectorDailyBar.eod_status == "complete_eod").order_by(desc(SectorDailyBar.trade_date)))
        bar_count = len(list(session.scalars(select(SectorDailyBar).where(SectorDailyBar.eod_status == "complete_eod"))))
        indicator_count = len(list(session.scalars(select(SectorIndicatorSnapshot))))
        return {
            "data_mode": data_mode,
            "provider": "ths_public_validation" if latest_run and latest_run.mode == "manual_real_refresh" else None,
            "provider_role": latest_run.provider_role if latest_run else None,
            "production_primary": None,
            "automatic_scheduler": data_mode == "real_local",
            "bar_count": bar_count,
            "indicator_count": indicator_count,
            "latest_complete_eod": latest_bar.trade_date.isoformat() if latest_bar else None,
            "latest_run_id": latest_run.id if latest_run else None,
            **eod_backfill.status(),
        }

    @app.get("/api/v1/market/intraday/status", response_model=ApiObjectResponse)
    def intraday_status(current: Principal | None = Depends(optional_principal)) -> dict:
        return intraday.status()

    @app.get("/api/v1/admin/market/intraday/sessions", response_model=list[ApiListItem])
    def intraday_sessions(
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
    ) -> list[dict]:
        rows = session.scalars(
            select(IntradayRefreshSession)
            .order_by(desc(IntradayRefreshSession.started_at))
            .limit(20)
        )
        return [{
            "session_id": row.id,
            "status": row.status,
            "started_at": row.started_at.isoformat(),
            "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
            "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "terminal_reason": row.terminal_reason,
            "started_by": row.started_by,
        } for row in rows]

    @app.get("/api/v1/admin/market/providers/health", response_model=list[ApiListItem])
    def provider_health(current: Principal = Depends(admin)) -> list[dict]:
        return intraday.provider_health()

    @app.post("/api/v1/admin/market/providers/{provider_key}/probe", response_model=ApiObjectResponse)
    def provider_probe(provider_key: str, current: Principal = Depends(admin)) -> dict:
        return intraday.probe_provider(provider_key)

    @app.get("/api/v1/market/intraday/sectors", response_model=list[ApiListItem])
    def intraday_sectors(current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> list[dict]:
        service = EnhancedReportService(session)
        status = intraday.status()
        policy = intraday_policy()
        now = datetime.now(timezone.utc)
        output = []
        capabilities = load_provider_capabilities()
        for market_path in load_market_path_registry().market_paths:
            if market_path.support_status.value == "unsupported":
                output.append({
                    "sector_key": market_path.market_path_key, "sector_name": market_path.display_name,
                    "data_status": "unsupported", "snapshot": None,
                })
                continue
            snapshot = service.latest_intraday(market_path.market_path_key)
            data_status = resolve_intraday_data_status(
                phase=status["market_phase"], snapshot=snapshot,
                latest_result=latest_intraday_item_status(session, market_path.market_path_key), now=now,
                stale_after_minutes=policy["stale_after_minutes"],
            )
            capability = capabilities[market_path.market_path_key]
            if not capability.selectable_candidates:
                data_status = "provider_failed"
            output.append({
                "sector_key": market_path.market_path_key, "sector_name": market_path.display_name,
                "data_status": data_status, "snapshot": snapshot,
            })
        return output

    @app.post("/api/v1/admin/market/intraday/start", response_model=ApiObjectResponse)
    def start_intraday(current: Principal = Depends(admin)) -> dict:
        return intraday.start(current.username)

    @app.post("/api/v1/admin/market/intraday/pause", response_model=ApiObjectResponse)
    def pause_intraday(current: Principal = Depends(admin)) -> dict:
        return intraday.pause(current.username, persistent=True)

    @app.post("/api/v1/admin/market/intraday/refresh-now", response_model=ApiObjectResponse)
    def refresh_intraday_now(current: Principal = Depends(admin)) -> dict:
        return intraday.refresh_now()

    @app.get("/api/v1/admin/market/summary", response_model=ApiObjectResponse)
    def market_summary(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        latest = session.scalar(select(MarketRefreshRun).order_by(desc(MarketRefreshRun.started_at)))
        registry = load_market_path_registry()
        capability_summary = provider_capability_summary()
        return {
            "provider": "ths_public_validation",
            "provider_role": "diagnostic_provider",
            "production_primary": None,
            "report_topic_count": registry.report_topic_count,
            "market_path_count": registry.market_path_count,
            "supported_count": len(registry.supported_market_paths),
            "unsupported_count": len(registry.unsupported_market_paths),
            "estimated_request_count": len(registry.supported_market_paths),
            "capability_summary": capability_summary,
            "automatic_scheduler": data_mode == "real_local",
            "latest_run": None if latest is None else {
                "run_id": latest.id,
                "status": latest.status,
                "success_count": latest.success_count,
                "failure_count": latest.failure_count,
                "intraday_count": latest.intraday_count,
                "stale_count": latest.stale_count,
                "short_history_count": latest.short_history_count,
                "unsupported_count": latest.unsupported_count,
                "started_at": latest.started_at.isoformat(),
                "finished_at": latest.finished_at.isoformat() if latest.finished_at else None,
            },
            "notice": "研究辅助数据，无生产SLA。real_local可执行受控盘中刷新和EOD缺口补齐；Viewer不会访问Provider。",
        }

    @app.get("/api/v1/admin/market/provider-capabilities", response_model=list[ApiListItem])
    def provider_capabilities(current: Principal = Depends(admin)) -> list[dict]:
        rows = load_provider_capabilities()
        return [{
            "market_path_key": item.sector_key,
            "display_name": item.display_name,
            "parent_report_topic": item.parent_report_topic,
            "mapping_type": item.mapping_type,
            "validation_status": "validated" if item.selectable_candidates else "unverified",
            "selected_provider": item.selectable_candidates[0].provider if item.selectable_candidates else None,
            "selected_symbol": item.selectable_candidates[0].symbol if item.selectable_candidates else None,
            "provider_name": item.selectable_candidates[0].provider_name if item.selectable_candidates else None,
            "spot_supported": bool(item.selectable_candidates),
            "history_supported": bool(item.selectable_candidates),
            "ma5_capable": bool(item.selectable_candidates),
        } for item in rows.values()]

    @app.get("/api/v1/admin/market/refresh-runs", response_model=list[ApiListItem])
    def refresh_runs(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> list[dict]:
        runs = list(session.scalars(select(MarketRefreshRun).order_by(desc(MarketRefreshRun.started_at)).limit(20)))
        return [{
            "run_id": run.id, "mode": run.mode, "provider_role": run.provider_role, "status": run.status,
            "requested_count": run.requested_count, "success_count": run.success_count,
            "failure_count": run.failure_count, "intraday_count": run.intraday_count,
            "stale_count": run.stale_count, "short_history_count": run.short_history_count,
            "unsupported_count": run.unsupported_count, "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        } for run in runs]

    @app.get("/api/v1/admin/market/refresh-runs/{run_id}", response_model=ApiObjectResponse)
    def refresh_run(run_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        run = session.get(MarketRefreshRun, run_id)
        if run is None:
            raise WebDomainError("refresh_run_not_found", "刷新记录不存在", 404)
        items = list(session.scalars(select(MarketRefreshItem).where(MarketRefreshItem.run_id == run.id).order_by(MarketRefreshItem.sector_key)))
        return {
            "run_id": run.id,
            "status": run.status,
            "provider": intraday.policy["provider"] if run.mode == "intraday_refresh" else None,
            "provider_role": run.provider_role,
            "requested_count": run.requested_count,
            "success_count": run.success_count,
            "failure_count": run.failure_count,
            "intraday_count": run.intraday_count,
            "stale_count": run.stale_count,
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "duration_ms": round((run.finished_at - run.started_at).total_seconds() * 1000) if run.finished_at else None,
            "items": [{
                "sector_key": item.sector_key,
                "status": item.status,
                "trade_date": item.trade_date.isoformat() if item.trade_date else None,
                "provider": item.provider,
                "provider_symbol": item.provider_symbol,
                "lineage": item.lineage,
                "error_code": item.error_code,
                "error_message": item.error_message,
                "expected_trade_date": item.expected_trade_date.isoformat() if item.expected_trade_date else None,
                "attempt_number": item.attempt_number,
                "attempted_at": item.attempted_at.isoformat() if item.attempted_at else None,
                "next_retry_at": item.next_retry_at.isoformat() if item.next_retry_at else None,
                "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                "detail": item.detail,
            } for item in items],
        }

    @app.post("/api/v1/admin/reports/{report_id}/market-snapshot", response_model=ApiObjectResponse)
    def freeze_snapshot(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        count = EnhancedReportService(session).freeze_market_snapshot(report, current.username)
        return {"report_id": report.id, "snapshot_count": count, "immutable": report.status == "published"}

    @app.post("/api/v1/admin/reports/{report_id}/enhanced-ready", response_model=ApiObjectResponse)
    def enhanced_ready(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        service = EnhancedReportService(session)
        service.ensure_structure(report, current.username)
        if len(service.path_entries(report.id)) != 66:
            raise WebDomainError("path_matrix_incomplete", "历史路径必须覆盖66个板块", 409)
        if not report.report_date_confirmed:
            raise WebDomainError("report_date_confirmation_required", "必须确认 report_date", 409)
        report.enhanced_status = "ready"
        session.commit()
        return {
            "report_id": report.id,
            "enhanced_status": report.enhanced_status,
            "market_data_attached": bool(service.report_snapshots(report.id)),
            "market_notice": "行情辅助数据未附加" if not service.report_snapshots(report.id) else "报告发布行情快照已固化",
        }
