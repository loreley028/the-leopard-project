from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from leopard_project.config import CONFIG_DIR, load_seed_bundle, normalize_alias

from .models import (
    EnhancedReportRevision,
    MarketRefreshItem,
    MarketRefreshRun,
    Report,
    ReportComparison,
    ReportSectorMarketSnapshot,
    SectorAssessment,
    SectorDailyBar,
    SectorIndicatorSnapshot,
    SectorIntradaySnapshot,
    SectorPathHistoryEntry,
    SectorPathEntry,
)
from .services import WebDomainError


PATH_STATUS_PATH = CONFIG_DIR / "sector_path_status_v1.json"
ENHANCED_POLICY_PATH = CONFIG_DIR / "enhanced_report_policy_v1.json"
CALENDAR_PATH = CONFIG_DIR / "enhanced_demo_calendar_v1.json"


def path_status_document() -> dict[str, Any]:
    return json.loads(PATH_STATUS_PATH.read_text(encoding="utf-8"))


def path_statuses() -> dict[str, dict[str, Any]]:
    return {item["code"]: item for item in path_status_document()["statuses"]}


def validate_path_status(value: str) -> str:
    if value not in path_statuses():
        raise WebDomainError("unknown_path_status", "未知路径状态必须进入人工复核，不得自动猜测", 422)
    return value


HOLDING_STATUSES = {"turn_hold", "hold"}
HOLDING_END_STATUSES = {"strong_watch", "watch", "weak_watch", "turn_weak", "exit", "avoid"}


def effective_statuses(reported_statuses: Sequence[str]) -> list[str | None]:
    """Carry the last explicit view across `not_mentioned` without inventing a view."""
    effective: str | None = None
    output: list[str | None] = []
    for status in reported_statuses:
        if status != "not_mentioned":
            effective = status
        output.append(effective)
    return output


def active_holding_interval(history: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """Calculate the latest still-open holding interval from chronological inputs."""
    if not history:
        return None
    effective = effective_statuses([str(item["reported_status"]) for item in history])
    if effective[-1] not in HOLDING_STATUSES:
        return None
    start_index: int | None = None
    for index in range(len(history) - 1, -1, -1):
        status = str(history[index]["reported_status"])
        if status == "turn_hold":
            start_index = index
            break
        if status in HOLDING_END_STATUSES:
            break
    if start_index is None:
        return {
            "status": "start_unknown",
            "effective_status": effective[-1],
            "latest_report_not_mentioned": history[-1]["reported_status"] == "not_mentioned",
        }
    start_market = history[start_index].get("market")
    end_market = history[-1].get("market")
    if not start_market or not end_market or not start_market.get("close") or end_market.get("close") is None:
        return {
            "status": "market_insufficient",
            "start_report_date": history[start_index].get("report_date"),
            "effective_status": effective[-1],
            "latest_report_not_mentioned": history[-1]["reported_status"] == "not_mentioned",
        }
    start_close = Decimal(str(start_market["close"]))
    end_close = Decimal(str(end_market["close"]))
    return {
        "status": "active",
        "start_report_date": history[start_index].get("report_date"),
        "start_market_as_of_date": start_market.get("trade_date") or start_market.get("market_as_of_date"),
        "trading_days": history[-1].get("trading_days_from_start"),
        "return_pct": float((end_close / start_close - Decimal("1")) * Decimal("100")),
        "effective_status": effective[-1],
        "latest_report_not_mentioned": history[-1]["reported_status"] == "not_mentioned",
    }


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _ratio(current: Decimal | None, values: Sequence[Decimal | None]) -> Decimal | None:
    if current is None or not values or any(value is None for value in values):
        return None
    complete = [value for value in values if value is not None]
    average = sum(complete, Decimal("0")) / Decimal(len(complete))
    return None if average == 0 else current / average


def _ma(values: Sequence[Decimal], sessions: int) -> Decimal | None:
    return None if len(values) < sessions else sum(values[-sessions:], Decimal("0")) / Decimal(sessions)


def _pct(current: Decimal, previous: Decimal | None) -> Decimal | None:
    return None if previous in (None, Decimal("0")) else (current / previous - 1) * Decimal("100")


def calculate_market_metrics(bars: Sequence[SectorDailyBar]) -> dict[str, Decimal | str | None]:
    eligible = sorted((bar for bar in bars if bar.eod_status == "complete_eod"), key=lambda bar: bar.trade_date)
    if not eligible:
        raise WebDomainError("complete_eod_required", "指标只接受 complete_eod 数据", 422)
    current = eligible[-1]
    closes = [_decimal(bar.close) for bar in eligible]
    volumes = [_decimal(bar.volume) for bar in eligible]
    assert all(value is not None for value in closes)
    close_values = [value for value in closes if value is not None]
    ma5, ma10, ma20 = (_ma(close_values, sessions) for sessions in (5, 10, 20))
    current_close = close_values[-1]
    previous_volumes = volumes[:-1]
    volume_average_5d = _ma([value for value in previous_volumes if value is not None], 5) if len(previous_volumes) >= 5 and all(value is not None for value in previous_volumes[-5:]) else None
    volume_average_20d = _ma([value for value in previous_volumes if value is not None], 20) if len(previous_volumes) >= 20 and all(value is not None for value in previous_volumes[-20:]) else None
    result: dict[str, Decimal | str | None] = {
        "return_5d": _pct(current_close, close_values[-6] if len(close_values) >= 6 else None),
        "return_10d": _pct(current_close, close_values[-11] if len(close_values) >= 11 else None),
        "return_20d": _pct(current_close, close_values[-21] if len(close_values) >= 21 else None),
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "close_vs_ma5_pct": _pct(current_close, ma5),
        "close_vs_ma10_pct": _pct(current_close, ma10),
        "close_vs_ma20_pct": _pct(current_close, ma20),
        "volume_average_5d": volume_average_5d,
        "volume_average_20d": volume_average_20d,
        "volume_ratio_5d": _ratio(_decimal(current.volume), previous_volumes[-5:]) if len(previous_volumes) >= 5 else None,
        "volume_ratio_20d": _ratio(_decimal(current.volume), previous_volumes[-20:]) if len(previous_volumes) >= 20 else None,
        "history_status": "complete" if len(eligible) >= 21 else "history_insufficient",
    }
    return result


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def market_payload(bar: SectorDailyBar | None, indicator: SectorIndicatorSnapshot | None = None) -> dict[str, Any] | None:
    if bar is None:
        return None
    payload = {
        "trade_date": bar.trade_date.isoformat(),
        "open": _number(bar.open),
        "high": _number(bar.high),
        "low": _number(bar.low),
        "close": _number(bar.close),
        "pre_close": _number(bar.pre_close),
        "daily_pct_change": _number(bar.daily_pct_change),
        "volume": _number(bar.volume),
        "amount": _number(bar.amount),
        "turnover_rate": _number(bar.turnover_rate),
        "liquidity_status": bar.liquidity_status,
        "eod_status": bar.eod_status,
        "data_source": bar.data_source,
        "provider_role": bar.provider_role,
        "fetched_at": bar.fetched_at.isoformat(),
        "source_response_hash": bar.source_response_hash,
    }
    if indicator:
        payload.update({
            key: _number(getattr(indicator, key))
            for key in (
                "return_5d", "return_10d", "return_20d", "ma5", "ma10", "ma20",
                "close_vs_ma5_pct", "close_vs_ma10_pct", "close_vs_ma20_pct",
                "volume_average_5d", "volume_average_20d", "volume_ratio_5d", "volume_ratio_20d",
            )
        })
        payload["history_status"] = indicator.history_status
    return payload


def intraday_matches_complete_eod_scale(intraday: dict[str, Any] | None, latest_bar: SectorDailyBar | None) -> bool:
    """Do not calculate a holding return across Provider or point-value scales."""
    if intraday is None or latest_bar is None:
        return False
    if intraday.get("index_value") is None or intraday.get("pre_close") is None:
        return False
    if intraday.get("provider") != latest_bar.data_source:
        return False
    pre_close = Decimal(str(intraday["pre_close"]))
    formal_close = Decimal(str(latest_bar.close))
    return pre_close > 0 and formal_close > 0 and abs(pre_close / formal_close - Decimal("1")) <= Decimal("0.005")


@dataclass
class EnhancedReportService:
    session: Session

    def ensure_structure(self, report: Report, actor: str = "system") -> None:
        bundle = load_seed_bundle()
        mention_map = {item.sector_key: item for item in report.mentions}
        existing = {
            item.sector_key
            for item in self.session.scalars(select(SectorPathEntry).where(SectorPathEntry.report_id == report.id))
        }
        for sector in bundle.sectors:
            if sector.sector_key in existing:
                continue
            mention = mention_map.get(sector.sector_key)
            status = "watch" if mention else "not_mentioned"
            summary = mention.summary if mention else ""
            self.session.add(SectorPathEntry(
                report_id=report.id,
                sector_key=sector.sector_key,
                sector_name=sector.sector_name,
                path_status=status,
                explicitly_mentioned=mention is not None,
                judgement_summary=summary,
                source_text_reference=mention.source_text if mention else "",
                confidence="medium" if mention else "low",
                quality_status="needs_attention" if mention else "not_applicable",
                review_status="confirmed" if mention else "not_applicable",
            ))
            self.session.add(SectorAssessment(
                report_id=report.id,
                sector_key=sector.sector_key,
                sector_name=sector.sector_name,
                current_path_status=status,
                explicitly_mentioned=mention is not None,
                recent_path_summary="本期首次记录" if mention else "本期未明确提及",
                current_judgement=summary,
                main_basis="等待管理员复核" if mention else "",
                observation_condition="等待管理员复核" if mention else "",
                source_text_reference=mention.source_text if mention else "",
                extraction_method="mention_fallback" if mention else "unavailable",
                confidence="medium" if mention else "low",
                validation_flags_json=json.dumps(["structured_row_not_parsed"] if mention else []),
                quality_status="needs_attention" if mention else "not_applicable",
                review_status="needs_review" if mention else "not_applicable",
            ))
        report.enhanced_status = "needs_review"
        self.session.commit()

    def parse_structured_text(self, report: Report, actor: str) -> dict[str, int]:
        """Best-effort deterministic text-layer enhancement; ambiguous input stays in review."""
        self.ensure_structure(report, actor)
        bundle = load_seed_bundle()
        label_to_code = {item["label"]: item["code"] for item in path_status_document()["statuses"]}
        entries = {item.sector_key: item for item in self.path_entries(report.id)}
        assessments = {item.sector_key: item for item in self.assessments(report.id)}
        parsed_paths = parsed_assessments = unknown_statuses = 0
        interpretation_meta = json.loads(report.interpretation_meta_json or "{}")
        for record in interpretation_meta.get("assessment_records", []):
            sector_key = record.get("sector_key")
            status = record.get("path_status")
            if sector_key not in entries or sector_key not in assessments or status not in path_statuses():
                continue
            entry = entries[sector_key]
            entry.path_status = status
            entry.explicitly_mentioned = True
            entry.judgement_summary = record.get("current_judgement", "")
            entry.source_text_reference = record.get("source_text_reference", "")
            entry.source_page = record.get("source_page")
            entry.source_text_start = record.get("source_text_start")
            entry.source_text_end = record.get("source_text_end")
            entry.confidence = record.get("confidence", "low")
            entry.validation_flags_json = json.dumps(record.get("validation_flags", []), ensure_ascii=False)
            entry.quality_status = record.get("quality_status", "needs_attention")
            entry.review_status = "confirmed" if entry.quality_status == "verified_structure" else "needs_review"
            assessment = assessments[sector_key]
            assessment.current_path_status = status
            assessment.explicitly_mentioned = True
            assessment.recent_path_summary = record.get("recent_path_summary", "")
            assessment.current_judgement = record.get("current_judgement", "")
            assessment.main_basis = record.get("main_basis", "")
            assessment.observation_condition = record.get("observation_condition", "")
            assessment.source_text_reference = record.get("source_text_reference", "")
            assessment.extraction_method = record.get("extraction_method", "unavailable")
            assessment.source_page = record.get("source_page")
            assessment.source_text_start = record.get("source_text_start")
            assessment.source_text_end = record.get("source_text_end")
            assessment.source_text_excerpt = record.get("source_text_excerpt", "")
            assessment.confidence = record.get("confidence", "low")
            assessment.validation_flags_json = json.dumps(record.get("validation_flags", []), ensure_ascii=False)
            assessment.quality_status = record.get("quality_status", "needs_attention")
            assessment.review_status = "confirmed" if assessment.quality_status == "verified_structure" else "needs_review"
            parsed_paths += 1
            parsed_assessments += 1
        for match in re.finditer(r"^路径状态[：:]\s*([^|｜]+)[|｜]\s*([^|｜\s]+)(?:[|｜]\s*(.*))?$", report.raw_text, re.M):
            sector_key = normalize_alias(match.group(1).strip(), bundle)
            if not sector_key:
                continue
            raw_status = match.group(2).strip()
            status = raw_status if raw_status in path_statuses() else label_to_code.get(raw_status)
            if status is None:
                entries[sector_key].review_status = "unknown_status"
                unknown_statuses += 1
                continue
            entry = entries[sector_key]
            entry.path_status = status
            entry.explicitly_mentioned = status != "not_mentioned"
            entry.judgement_summary = (match.group(3) or "").strip()
            entry.source_text_reference = match.group(0)
            entry.review_status = "needs_review"
            parsed_paths += 1
        for match in re.finditer(r"^板块解读[：:]\s*([^|｜]+)[|｜]\s*([^|｜]*)[|｜]\s*([^|｜]*)[|｜]\s*([^|｜]*)[|｜]\s*(.*)$", report.raw_text, re.M):
            sector_key = normalize_alias(match.group(1).strip(), bundle)
            if not sector_key:
                continue
            assessment = assessments[sector_key]
            assessment.recent_path_summary = match.group(2).strip()
            assessment.current_judgement = match.group(3).strip()
            assessment.main_basis = match.group(4).strip()
            assessment.observation_condition = match.group(5).strip()
            assessment.source_text_reference = match.group(0)
            assessment.review_status = "needs_review"
            parsed_assessments += 1
        report.enhanced_status = "needs_review" if report.interpretation_status == "needs_attention" else "ready"
        from .path_history import audit_frozen_path_history
        differences = audit_frozen_path_history(self.session, report)
        if differences:
            severity = "warning" if len(differences) <= 10 else "blocking"
            interpretation_meta.setdefault("attention_items", []).append({
                "kind": "history_rewrite", "severity": severity,
                "message": f"新PDF与冻结路径存在{len(differences)}处差异，旧记录未被覆盖",
                "differences": differences,
            })
            if severity == "blocking":
                interpretation_meta["quality_status"] = "blocking_parse_error"
            report.interpretation_meta_json = json.dumps(interpretation_meta, ensure_ascii=False)
        self._revision(report, actor, "deterministic_text_layer_enhancement")
        self.session.commit()
        return {"path_entries_parsed": parsed_paths, "assessments_parsed": parsed_assessments, "unknown_statuses": unknown_statuses}

    def interpretation(self, report: Report) -> dict[str, Any]:
        metadata = json.loads(report.interpretation_meta_json or "{}")
        paths = self.path_entries(report.id)
        assessments = self.assessments(report.id)
        sector_groups = {item.sector_key: item.category_level_1 for item in load_seed_bundle().sectors}
        relevant_keys = {
            item.sector_key for item in paths
            if item.explicitly_mentioned or item.path_status != "not_mentioned" or item.review_status not in {"confirmed", "not_applicable"}
        }
        relevant_assessments = [
            assessment_payload(item)
            for item in assessments
            if item.sector_key in relevant_keys and item.explicitly_mentioned
        ]
        counts = {code: 0 for code in path_statuses()}
        for item in paths:
            counts[item.path_status] += 1
        return {
            "report_id": report.id,
            "status": report.interpretation_status,
            "report_date": report.report_date.isoformat() if report.report_date else None,
            "detected_report_date": report.detected_report_date.isoformat() if report.detected_report_date else None,
            "report_date_source": report.report_date_source,
            "report_date_confidence": report.report_date_confidence,
            "report_date_confirmed_by_user": report.report_date_confirmed_by_user,
            "candidate_market_as_of_date": report.candidate_market_as_of_date.isoformat() if report.candidate_market_as_of_date else None,
            "market_as_of_date": report.market_as_of_date.isoformat() if report.market_as_of_date else None,
            "market_data_status": "attached" if self.report_snapshots(report.id) else "not_bound",
            "field_provenance": metadata.get("field_provenance", {}),
            "quality_status": metadata.get("quality_status", "needs_attention"),
            "quality_summary": metadata.get("quality_summary", {}),
            "attention_items": metadata.get("attention_items", []),
            "mapping_summary": metadata.get("mapping_summary", {}),
            "status_counts": counts,
            "mentioned_assessments": relevant_assessments,
            "relevant_path_entries": [path_entry_payload(item) for item in paths if item.sector_key in relevant_keys],
            "all_path_entries": [
                {**path_entry_payload(item), "group_name": sector_groups[item.sector_key]}
                for item in paths
            ],
            "pdf_history_matrix": metadata.get("pdf_history_matrix", {"dates": [], "rows": []}),
            "path_entry_count": len(paths),
            "external_llm_calls": 0,
            "ocr_used": False,
        }

    def path_entries(self, report_id: str) -> list[SectorPathEntry]:
        return list(self.session.scalars(
            select(SectorPathEntry).where(SectorPathEntry.report_id == report_id).order_by(SectorPathEntry.sector_name)
        ))

    def assessments(self, report_id: str) -> list[SectorAssessment]:
        return list(self.session.scalars(
            select(SectorAssessment).where(SectorAssessment.report_id == report_id).order_by(SectorAssessment.sector_name)
        ))

    def update_path(self, report: Report, entry_id: str, changes: dict[str, Any], actor: str) -> SectorPathEntry:
        entry = self.session.get(SectorPathEntry, entry_id)
        if entry is None or entry.report_id != report.id:
            raise WebDomainError("path_entry_not_found", "路径单元格不存在", 404)
        if "path_status" in changes:
            entry.path_status = validate_path_status(changes["path_status"])
        for field in ("explicitly_mentioned", "judgement_summary", "source_text_reference", "review_status"):
            if field in changes:
                setattr(entry, field, changes[field])
        entry.manually_modified = True
        entry.confidence = "high"
        entry.validation_flags_json = "[]"
        entry.quality_status = "verified_structure"
        entry.revision_id = f"manual-{report.enhanced_revision_number + 1}"
        entry.updated_at = datetime.now(timezone.utc)
        report.enhanced_revision_number += 1
        self._revision(report, actor, "path_entry_updated")
        self.session.commit()
        return entry

    def update_assessment(self, report: Report, assessment_id: str, changes: dict[str, Any], actor: str) -> SectorAssessment:
        assessment = self.session.get(SectorAssessment, assessment_id)
        if assessment is None or assessment.report_id != report.id:
            raise WebDomainError("sector_assessment_not_found", "板块解读不存在", 404)
        if "current_path_status" in changes:
            assessment.current_path_status = validate_path_status(changes["current_path_status"])
        for field in (
            "explicitly_mentioned", "recent_path_summary", "current_judgement", "main_basis",
            "observation_condition", "source_section", "source_text_reference", "review_status",
        ):
            if field in changes:
                setattr(assessment, field, changes[field])
        assessment.manually_modified = True
        assessment.confidence = "high"
        assessment.validation_flags_json = "[]"
        assessment.quality_status = "verified_structure"
        assessment.extraction_method = "manual_admin_correction"
        assessment.revision_id = f"manual-{report.enhanced_revision_number + 1}"
        assessment.updated_at = datetime.now(timezone.utc)
        report.enhanced_revision_number += 1
        metadata = json.loads(report.interpretation_meta_json or "{}")
        metadata["attention_items"] = [
            item for item in metadata.get("attention_items", [])
            if item.get("sector_key") != assessment.sector_key
        ]
        remaining_blocking = any(item.get("severity") == "blocking" for item in metadata["attention_items"])
        metadata["quality_status"] = "blocking_parse_error" if remaining_blocking else "verified_structure"
        report.interpretation_meta_json = json.dumps(metadata, ensure_ascii=False)
        report.interpretation_status = "needs_attention" if metadata["attention_items"] else "ready"
        self._revision(report, actor, "sector_assessment_updated")
        self.session.commit()
        return assessment

    def bind_market_date(self, report: Report, market_as_of_date: date, confirmed: bool, actor: str) -> Report:
        calendar = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
        covered = {date.fromisoformat(value) for value in calendar["trading_dates"] + calendar["non_trading_dates"]}
        trading = {date.fromisoformat(value) for value in calendar["trading_dates"]}
        observed_coverage = self.session.scalar(select(func.count(func.distinct(SectorDailyBar.sector_key))).where(
            SectorDailyBar.trade_date == market_as_of_date,
            SectorDailyBar.eod_status == "complete_eod",
        )) or 0
        observed_real_trading_day = observed_coverage >= 60
        if market_as_of_date not in covered and not observed_real_trading_day:
            raise WebDomainError("calendar_coverage_unavailable", "日期超出受控交易日历范围，系统按失败关闭处理", 422)
        if market_as_of_date not in trading and not observed_real_trading_day:
            raise WebDomainError("market_date_not_trading_day", "market_as_of_date 必须是受控日历中的交易日", 422)
        if report.report_date and market_as_of_date > report.report_date:
            raise WebDomainError("market_date_after_report", "行情日期不得晚于报告日期", 422)
        report.market_as_of_date = market_as_of_date
        report.market_as_of_date_confirmed = confirmed
        self._revision(report, actor, "market_date_bound")
        self.session.commit()
        return report

    def fixture_refresh(self, actor: str, sector_keys: list[str] | None = None) -> MarketRefreshRun:
        bundle = load_seed_bundle()
        supported = [item for item in bundle.sectors if item.sector_key != "hang_seng_tech"]
        if sector_keys:
            supported = [item for item in supported if item.sector_key in set(sector_keys)]
        run = MarketRefreshRun(
            mode="controlled_fixture",
            provider_role="best_effort_research_source",
            requested_count=len(supported),
            requested_by=actor,
            status="running",
        )
        self.session.add(run)
        self.session.flush()
        trading_dates = [date.fromisoformat(value) for value in json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))["trading_dates"]][-25:]
        for sector in supported:
            dates = trading_dates[-14:] if sector.sector_key == "glass_substrate" else trading_dates
            for position, day in enumerate(dates):
                base = Decimal("80") + Decimal(sector.overall_order) / Decimal("3")
                close = base + Decimal(position) * Decimal("0.18") + Decimal((sector.overall_order + position) % 5) / Decimal("10")
                pre_close = close - Decimal("0.12")
                digest = hashlib.sha256(f"fixture:{sector.sector_key}:{day}".encode()).hexdigest()
                existing = self.session.scalar(select(SectorDailyBar).where(
                    SectorDailyBar.sector_key == sector.sector_key,
                    SectorDailyBar.trade_date == day,
                ))
                if existing is None:
                    self.session.add(SectorDailyBar(
                        sector_key=sector.sector_key,
                        trade_date=day,
                        close=close,
                        pre_close=pre_close,
                        daily_pct_change=_pct(close, pre_close) or Decimal("0"),
                        volume=Decimal("1000000") + Decimal(position * 25000 + sector.overall_order * 1000),
                        amount=None if sector.overall_order % 7 == 0 else Decimal("85000000") + Decimal(position * 100000),
                        eod_status="complete_eod",
                        data_source="controlled_fixture",
                        provider_role="best_effort_research_source",
                        fetched_at=datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc),
                        source_response_hash=digest,
                    ))
            self.session.flush()
            bars = list(self.session.scalars(
                select(SectorDailyBar).where(SectorDailyBar.sector_key == sector.sector_key).order_by(SectorDailyBar.trade_date)
            ))
            latest = bars[-1]
            for bar_index, target_bar in enumerate(bars, start=1):
                indicator = self.session.scalar(select(SectorIndicatorSnapshot).where(SectorIndicatorSnapshot.daily_bar_id == target_bar.id))
                if indicator is None:
                    metrics = calculate_market_metrics(bars[:bar_index])
                    self.session.add(SectorIndicatorSnapshot(daily_bar_id=target_bar.id, **metrics))
            self.session.add(MarketRefreshItem(run_id=run.id, sector_key=sector.sector_key, status="complete_eod", trade_date=latest.trade_date, detail="controlled fixture"))
        run.success_count = len(supported)
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        self.session.commit()
        return run

    def freeze_market_snapshot(self, report: Report, actor: str) -> int:
        if not report.market_as_of_date_confirmed or not report.market_as_of_date:
            raise WebDomainError("market_as_of_date_confirmation_required", "必须先确认 market_as_of_date", 409)
        existing_count = len(list(self.session.scalars(
            select(ReportSectorMarketSnapshot).where(
                ReportSectorMarketSnapshot.report_id == report.id,
                ReportSectorMarketSnapshot.revision_number == 1,
            )
        )))
        if existing_count:
            return existing_count
        count = 0
        for sector in load_seed_bundle().sectors:
            if sector.sector_key == "hang_seng_tech":
                continue
            bar = self.session.scalar(select(SectorDailyBar).where(
                SectorDailyBar.sector_key == sector.sector_key,
                SectorDailyBar.trade_date == report.market_as_of_date,
                SectorDailyBar.eod_status == "complete_eod",
            ))
            if bar is None:
                continue
            indicator = self.session.scalar(select(SectorIndicatorSnapshot).where(SectorIndicatorSnapshot.daily_bar_id == bar.id))
            payload = market_payload(bar, indicator)
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self.session.add(ReportSectorMarketSnapshot(
                report_id=report.id,
                sector_key=sector.sector_key,
                market_as_of_date=report.market_as_of_date,
                snapshot_json=serialized,
                snapshot_hash=hashlib.sha256(serialized.encode()).hexdigest(),
            ))
            count += 1
        self._revision(report, actor, "market_snapshot_frozen")
        self.session.commit()
        return count

    def previous_report(self, report: Report) -> Report | None:
        if report.report_date is None:
            return None
        return self.session.scalar(
            select(Report).where(
                Report.status == "published",
                Report.report_date < report.report_date,
            ).order_by(desc(Report.report_date), desc(Report.published_at))
        )

    def comparison(self, report: Report) -> dict[str, Any]:
        previous = self.previous_report(report)
        if previous is None:
            return {"previous_report_id": None, "kind": "first_published_report", "status_changes": [], "counts": {}}
        current = {item.sector_key: item for item in self.path_entries(report.id)}
        prior = {item.sector_key: item for item in self.path_entries(previous.id)}
        changes = []
        counts = {"newly_mentioned": 0, "not_mentioned": 0, "turned_hold": 0, "turned_weak": 0, "exit": 0, "continued_hold": 0}
        for key, item in current.items():
            before = prior.get(key)
            if item.explicitly_mentioned and (before is None or not before.explicitly_mentioned):
                counts["newly_mentioned"] += 1
            if item.path_status == "not_mentioned":
                counts["not_mentioned"] += 1
            if item.path_status == "turn_hold" or (item.path_status == "hold" and before and before.path_status == "watch"):
                counts["turned_hold"] += 1
            if item.path_status == "turn_weak":
                counts["turned_weak"] += 1
            if item.path_status == "exit":
                counts["exit"] += 1
            if item.path_status == "hold" and before and before.path_status == "hold":
                counts["continued_hold"] += 1
            if before and item.path_status != "not_mentioned" and before.path_status != "not_mentioned" and before.path_status != item.path_status:
                changes.append({"sector_key": key, "sector_name": item.sector_name, "from": before.path_status, "to": item.path_status})
        return {"previous_report_id": previous.id, "previous_report_date": previous.report_date.isoformat(), "status_changes": changes, "counts": counts}

    def latest_market(self, sector_key: str) -> dict[str, Any] | None:
        bar = self.session.scalar(select(SectorDailyBar).where(
            SectorDailyBar.sector_key == sector_key,
            SectorDailyBar.eod_status == "complete_eod",
        ).order_by(desc(SectorDailyBar.trade_date)))
        indicator = self.session.scalar(select(SectorIndicatorSnapshot).where(SectorIndicatorSnapshot.daily_bar_id == bar.id)) if bar else None
        return market_payload(bar, indicator)

    def recent_complete_days(self, sector_key: str, count: int = 5) -> list[dict[str, Any]]:
        rows = list(self.session.scalars(select(SectorDailyBar).where(
            SectorDailyBar.sector_key == sector_key,
            SectorDailyBar.eod_status == "complete_eod",
        ).order_by(desc(SectorDailyBar.trade_date)).limit(count)))
        return [{
            "trade_date": item.trade_date.isoformat(),
            "daily_pct_change": _number(item.daily_pct_change),
            "close": _number(item.close),
            "data_status": "eod_complete",
        } for item in reversed(rows)]

    def latest_intraday(self, sector_key: str) -> dict[str, Any] | None:
        item = self.session.scalar(select(SectorIntradaySnapshot).where(
            SectorIntradaySnapshot.sector_key == sector_key,
        ).order_by(desc(SectorIntradaySnapshot.observed_at)))
        if item is None:
            return None
        observed_at = item.observed_at if item.observed_at.tzinfo else item.observed_at.replace(tzinfo=timezone.utc)
        fetched_at = item.fetched_at if item.fetched_at.tzinfo else item.fetched_at.replace(tzinfo=timezone.utc)
        return {
            "sector_key": item.sector_key,
            "trade_date": item.trade_date.isoformat(),
            "observed_at": observed_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%m/%d %H:%M"),
            "observed_at_iso": observed_at.isoformat(),
            "index_value": _number(item.index_value),
            "pre_close": _number(item.pre_close),
            "pct_change": _number(item.pct_change),
            "volume": _number(item.volume),
            "amount": _number(item.amount),
            "provider": item.provider,
            "provider_symbol": item.provider_symbol,
            "provider_role": item.provider_role,
            "lineage": item.lineage,
            "source_status": item.source_status,
            "freshness_status": item.freshness_status,
            "intraday_ma5": _number(item.intraday_ma5),
            "intraday_vs_ma5": _number(item.intraday_vs_ma5),
            "native_history_status": item.native_history_status,
            "data_status": item.data_status,
            "response_hash": item.response_hash,
            "fetched_at": fetched_at.isoformat(),
        }

    def path_history(self, sector_key: str, limit: int | None = None, through: date | None = None) -> list[SectorPathHistoryEntry]:
        query = select(SectorPathHistoryEntry).where(SectorPathHistoryEntry.sector_key == sector_key)
        if through is not None:
            query = query.where(SectorPathHistoryEntry.path_report_date <= through)
        query = query.order_by(desc(SectorPathHistoryEntry.path_report_date))
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def holding_intervals_for_sector(self, sector_key: str, through: date | None = None) -> dict[str, Any]:
        entries = list(reversed(self.path_history(sector_key, through=through)))
        if not entries:
            return {
                "active_holding_interval": None, "historical_holding_intervals": [],
                "strict_holding_interval": None, "broad_holding_interval": None,
                "historical_strict_intervals": [], "historical_broad_intervals": [],
            }
        bars = list(self.session.scalars(select(SectorDailyBar).where(
            SectorDailyBar.sector_key == sector_key,
            SectorDailyBar.eod_status == "complete_eod",
        ).order_by(SectorDailyBar.trade_date)))
        by_date = {item.trade_date: item for item in bars}
        latest_bar = bars[-1] if bars else None
        latest_intraday = self.latest_intraday(sector_key)
        def calculate(kind: str, allowed: set[str], endings: set[str]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
            historical: list[dict[str, Any]] = []
            active_start: SectorPathHistoryEntry | None = None
            effective = "not_mentioned"
            for entry in entries:
                if entry.path_status == "not_mentioned":
                    continue
                effective = entry.path_status
                if entry.path_status == "turn_hold":
                    active_start = entry
                    continue
                if active_start is not None and entry.path_status in endings:
                    start_bar = by_date.get(active_start.market_as_of_date) if active_start.market_as_of_date else None
                    end_bar = by_date.get(entry.market_as_of_date) if entry.market_as_of_date else None
                    interval: dict[str, Any] = {
                        "interval_type": kind,
                        "status": "complete" if start_bar and end_bar else "market_insufficient",
                        "calculation_status": "complete" if start_bar and end_bar else "market_insufficient",
                        "start_report_date": active_start.path_report_date.isoformat(),
                        "start_market_as_of_date": active_start.market_as_of_date.isoformat() if active_start.market_as_of_date else None,
                        "end_report_date": entry.path_report_date.isoformat(),
                        "end_market_as_of_date": entry.market_as_of_date.isoformat() if entry.market_as_of_date else None,
                        "end_status": entry.path_status,
                        "start_source": "sector_path_history", "end_source": "sector_path_history",
                    }
                    if start_bar and end_bar and Decimal(str(start_bar.close)) != 0:
                        interval["trading_days"] = max(0, sum(start_bar.trade_date <= bar.trade_date <= end_bar.trade_date for bar in bars) - 1)
                        interval["eod_return"] = float((Decimal(str(end_bar.close)) / Decimal(str(start_bar.close)) - 1) * 100)
                        interval["return_pct"] = interval["eod_return"]
                    historical.append(interval)
                    active_start = None
            active: dict[str, Any] | None = None
            if effective in allowed and active_start is not None:
                start_bar = by_date.get(active_start.market_as_of_date) if active_start.market_as_of_date else None
                active = {
                    "interval_type": kind,
                    "status": "active" if start_bar and latest_bar else "market_insufficient",
                    "calculation_status": "complete" if start_bar and latest_bar else "market_insufficient",
                    "start_report_date": active_start.path_report_date.isoformat(),
                    "start_market_as_of_date": active_start.market_as_of_date.isoformat() if active_start.market_as_of_date else None,
                    "effective_status": effective,
                    "latest_report_not_mentioned": entries[-1].path_status == "not_mentioned",
                    "start_source": "sector_path_history", "end_source": "latest_complete_eod",
                }
                if start_bar and latest_bar and Decimal(str(start_bar.close)) != 0:
                    active["trading_days"] = max(0, sum(start_bar.trade_date <= bar.trade_date <= latest_bar.trade_date for bar in bars) - 1)
                    active["eod_return"] = float((Decimal(str(latest_bar.close)) / Decimal(str(start_bar.close)) - 1) * 100)
                    active["return_pct"] = active["eod_return"]
                    if intraday_matches_complete_eod_scale(latest_intraday, latest_bar):
                        active["intraday_reference_return"] = float((Decimal(str(latest_intraday["index_value"])) / Decimal(str(start_bar.close)) - 1) * 100)
            return active, list(reversed(historical))

        strict, strict_history = calculate("strict", {"turn_hold", "hold"}, {"strong_watch", "watch", "weak_watch", "turn_weak", "exit", "avoid"})
        broad, broad_history = calculate("broad", {"turn_hold", "hold", "strong_watch"}, {"watch", "weak_watch", "turn_weak", "exit", "avoid"})
        return {
            "active_holding_interval": strict,
            "historical_holding_intervals": strict_history,
            "strict_holding_interval": strict,
            "broad_holding_interval": broad,
            "historical_strict_intervals": strict_history,
            "historical_broad_intervals": broad_history,
        }
    def holding_interval_for_sector(self, report: Report, sector_key: str) -> dict[str, Any] | None:
        return self.holding_intervals_for_sector(sector_key, report.report_date).get("active_holding_interval")

    def market_history(self, sector_key: str, limit: int = 20) -> list[dict[str, Any]]:
        bars = list(self.session.scalars(
            select(SectorDailyBar).where(
                SectorDailyBar.sector_key == sector_key,
                SectorDailyBar.eod_status == "complete_eod",
            ).order_by(desc(SectorDailyBar.trade_date)).limit(limit)
        ))
        output: list[dict[str, Any]] = []
        for bar in reversed(bars):
            indicator = self.session.scalar(
                select(SectorIndicatorSnapshot).where(SectorIndicatorSnapshot.daily_bar_id == bar.id)
            )
            payload = market_payload(bar, indicator)
            if payload:
                output.append(payload)
        return output

    def report_snapshots(self, report_id: str) -> list[dict[str, Any]]:
        rows = list(self.session.scalars(
            select(ReportSectorMarketSnapshot).where(ReportSectorMarketSnapshot.report_id == report_id).order_by(ReportSectorMarketSnapshot.sector_key)
        ))
        return [{"sector_key": item.sector_key, "market_as_of_date": item.market_as_of_date.isoformat(), **json.loads(item.snapshot_json), "snapshot_hash": item.snapshot_hash} for item in rows]

    def _revision(self, report: Report, actor: str, reason: str) -> None:
        payload = f"{report.id}:{report.enhanced_revision_number}:{reason}:{datetime.now(timezone.utc).isoformat()}"
        self.session.add(EnhancedReportRevision(
            report_id=report.id,
            revision_number=max(1, report.enhanced_revision_number),
            changed_by=actor,
            reason=reason,
            snapshot_hash=hashlib.sha256(payload.encode()).hexdigest(),
        ))


def path_entry_payload(item: SectorPathEntry) -> dict[str, Any]:
    status = path_statuses()[item.path_status]
    return {
        "id": item.id,
        "sector_key": item.sector_key,
        "sector_name": item.sector_name,
        "path_status": item.path_status,
        "path_status_label": status["label"],
        "path_status_color": status["color"],
        "explicitly_mentioned": item.explicitly_mentioned,
        "judgement_summary": item.judgement_summary,
        "source_text_reference": item.source_text_reference,
        "source_page": item.source_page,
        "source_text_start": item.source_text_start,
        "source_text_end": item.source_text_end,
        "confidence": item.confidence,
        "validation_flags": json.loads(item.validation_flags_json or "[]"),
        "quality_status": item.quality_status,
        "review_status": item.review_status,
        "manually_modified": item.manually_modified,
        "revision_id": item.revision_id,
    }


def assessment_payload(item: SectorAssessment, market: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "sector_key": item.sector_key,
        "sector_name": item.sector_name,
        "current_path_status": item.current_path_status,
        "path_status_label": path_statuses()[item.current_path_status]["label"],
        "explicitly_mentioned": item.explicitly_mentioned,
        "recent_path_summary": item.recent_path_summary,
        "current_judgement": item.current_judgement,
        "main_basis": item.main_basis,
        "observation_condition": item.observation_condition,
        "source_section": item.source_section,
        "source_text_reference": item.source_text_reference,
        "extraction_method": item.extraction_method,
        "source_page": item.source_page,
        "source_text_start": item.source_text_start,
        "source_text_end": item.source_text_end,
        "source_text_excerpt": item.source_text_excerpt,
        "confidence": item.confidence,
        "validation_flags": json.loads(item.validation_flags_json or "[]"),
        "quality_status": item.quality_status,
        "review_status": item.review_status,
        "manually_modified": item.manually_modified,
        "revision_id": item.revision_id,
        "market": market,
    }
