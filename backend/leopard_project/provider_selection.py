from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Sequence

from .config import PROJECT_ROOT
from .models import DailyBar, Market
from .provider_validation import audit_bars, canonical_bar_hash
from .providers import ProviderError, ThsPublicValidationProvider
from .support import CollectionTask, build_collection_plan


SELECTION_DIR = PROJECT_ROOT / "data" / "provider-selection"


def _field_available(bars: Sequence[DailyBar], field: str) -> bool:
    return bool(bars) and all(getattr(bar, field) is not None for bar in bars)


def _validate_task(
    task: CollectionTask,
    provider: ThsPublicValidationProvider,
    start: date,
    end: date,
) -> dict[str, object]:
    components: list[dict[str, object]] = []
    component_bars: list[Sequence[DailyBar]] = []
    for symbol in task.provider_symbols:
        try:
            first = provider.historical_daily_bars(symbol, start, end, Market.CN_A)
            second = provider.historical_daily_bars(symbol, start, end, Market.CN_A)
            audit = audit_bars(first)
            components.append({
                "symbol": symbol, "audit": audit.__dict__,
                "repeated_request_consistent": canonical_bar_hash(first) == canonical_bar_hash(second),
                "source_payload_hash": first[-1].source_payload_hash if first else None,
            })
            component_bars.append(first)
        except ProviderError as exc:
            components.append({
                "symbol": symbol, "error_category": exc.category, "error": str(exc),
                "retryable": exc.retryable,
            })
    successful = len(component_bars) == len(task.provider_symbols) and all(component_bars)
    all_bars = [bar for bars in component_bars for bar in bars]
    latest_dates = [bars[-1].trade_date for bars in component_bars if bars]
    return {
        "sector_key": task.sector_key, "sector_name": task.sector_name,
        "market": task.market, "mapping_type": task.mapping_type,
        "data_status": task.data_status, "provider_symbols": task.provider_symbols,
        "has_any_real_data": successful,
        "has_120_days": successful and all(len(bars) >= 120 for bars in component_bars),
        "latest_trade_date": min(latest_dates).isoformat() if successful else None,
        "has_open": _field_available(all_bars, "open"),
        "has_high": _field_available(all_bars, "high"),
        "has_low": _field_available(all_bars, "low"),
        "has_close": _field_available(all_bars, "close"),
        "has_pre_close": _field_available(all_bars, "pre_close"),
        "has_pct_change": _field_available(all_bars, "pct_change"),
        "has_volume": _field_available(all_bars, "volume"),
        "has_turnover_rate": _field_available(all_bars, "turnover_rate"),
        "has_amount": _field_available(all_bars, "amount"),
        "dates_sorted": successful and all(audit_bars(bars).dates_sorted for bars in component_bars),
        "duplicate_dates": sum(audit_bars(bars).duplicate_dates for bars in component_bars),
        "null_required_fields": sum(audit_bars(bars).null_fields for bars in component_bars),
        "repeated_request_consistent": successful and all(bool(row.get("repeated_request_consistent")) for row in components),
        "name_match_status": "not_independently_exposed_by_chart_endpoint",
        "components": components,
    }


def provider_comparison(coverage: dict[str, object]) -> dict[str, object]:
    summary = coverage["summary"]  # type: ignore[assignment]
    fields = summary["field_counts"]  # type: ignore[index]
    public = {
        "provider_name": "ths_public_validation", "provider_role": "diagnostic_provider",
        "supported_sector_count": summary["real_data_count"],
        "coverage_rate": summary["coverage_rate"], "full_history_count": summary["full_history_count"],
        "latest_trade_date_count": summary["latest_trade_date_count"],
        **{key: fields[key] for key in (
            "has_open", "has_high", "has_low", "has_close", "has_pre_close", "has_pct_change",
            "has_volume", "has_turnover_rate", "has_amount",
        )},
        "freshness_risk": "medium; latest-date gate required",
        "stale_snapshot_risk": "high; public cache/version drift observed in Phase 1A HSTECH test",
        "rate_limit": "undocumented; Phase 1B-0 uses sequential requests with >=0.35s interval",
        "authentication_required": False, "paid_permission_required": False,
        "licensing_risk": "high; no project-specific production authorization established",
        "endpoint_stability": "low; undocumented web chart callback",
        "integration_complexity": "low", "maintenance_cost": "high",
        "production_recommendation": "B_current_source_remains_diagnostic_provider",
        "blocking_reasons": ["undocumented_endpoint", "no_sla", "licensing_not_confirmed", "name_not_exposed", "turnover_rate_absent"],
        "evidence": ["phase1b0_live_scan", "phase1a_snapshot_observation"],
    }
    unknown_fields = {key: None for key in (
        "has_open", "has_high", "has_low", "has_close", "has_pre_close", "has_pct_change",
        "has_volume", "has_turnover_rate", "has_amount",
    )}
    akshare = {
        "provider_name": "akshare_ths", "provider_role": "research_provider",
        "supported_sector_count": None, "coverage_rate": None, "full_history_count": None,
        "latest_trade_date_count": None, **unknown_fields,
        "freshness_risk": "not_live_validated", "stale_snapshot_risk": "shares THS upstream risk",
        "rate_limit": "upstream-dependent and undocumented", "authentication_required": False,
        "paid_permission_required": False, "licensing_risk": "upstream data terms require confirmation",
        "endpoint_stability": "not independently established", "integration_complexity": "medium",
        "maintenance_cost": "medium_to_high",
        "production_recommendation": "research_only_not_an_independent_fallback",
        "blocking_reasons": ["not_live_validated_in_repository", "same_or_similar_public_upstream", "no_project_sla"],
        "evidence": ["akshare_official_repository_and_documented_interfaces"],
    }
    tushare = {
        "provider_name": "tushare_ths_daily", "provider_role": "candidate_primary",
        "supported_sector_count": None, "coverage_rate": None, "full_history_count": None,
        "latest_trade_date_count": None, **unknown_fields,
        "freshness_risk": "not_live_validated", "stale_snapshot_risk": "not_evaluated",
        "rate_limit": "official endpoint documents permission/points requirements",
        "authentication_required": True, "paid_permission_required": "permission_or_points_required",
        "licensing_risk": "account use terms and project authorization require confirmation",
        "endpoint_stability": "documented API but not tested with this account",
        "integration_complexity": "medium", "maintenance_cost": "medium",
        "production_recommendation": "candidate_only_no_provider_implementation_in_phase1b0",
        "blocking_reasons": ["no_account_permission_test", "65_symbol_conversion_not_verified", "amount_not_documented"],
        "evidence": ["tushare_official_ths_daily_documentation"],
    }
    return {
        "schema_version": 1, "generated_at": datetime.now(UTC).isoformat(),
        "selection_conclusion": "D_free_or_public_sources_are_not_yet_sufficient_for_stable_production",
        "production_primary_approved": False,
        "providers": [public, akshare, tushare],
    }


def run_provider_selection(
    *, output_dir: Path = SELECTION_DIR,
    provider: ThsPublicValidationProvider | None = None,
    start: date = date(2026, 1, 1), end: date | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    provider = provider or ThsPublicValidationProvider()
    end = end or date.today()
    plan = build_collection_plan(end)
    results = [_validate_task(task, provider, start, end) for task in plan.tasks]
    latest = max((str(row["latest_trade_date"]) for row in results if row["latest_trade_date"]), default=None)
    field_names = (
        "has_open", "has_high", "has_low", "has_close", "has_pre_close", "has_pct_change",
        "has_volume", "has_turnover_rate", "has_amount",
    )
    summary = {
        "business_catalog_count": plan.total_business_sectors,
        "supported_sector_count": len(results), "unsupported_sector_count": len(plan.unsupported_sectors),
        "collection_denominator": plan.collection_denominator,
        "real_data_count": sum(bool(row["has_any_real_data"]) for row in results),
        "coverage_rate": sum(bool(row["has_any_real_data"]) for row in results) / len(results),
        "full_history_count": sum(bool(row["has_120_days"]) for row in results),
        "latest_trade_date": latest,
        "latest_trade_date_count": sum(row["latest_trade_date"] == latest for row in results),
        "field_counts": {name: sum(bool(row[name]) for row in results) for name in field_names},
        "name_independently_verified_count": 0,
    }
    coverage = {
        "schema_version": 1, "phase": "1B-0", "provider": provider.provider_key,
        "provider_role": "diagnostic_provider", "generated_at": datetime.now(UTC).isoformat(),
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "rate_control": {"concurrent_requests": 1, "automatic_retries": 0, "minimum_interval_seconds": 0.35},
        "summary": summary, "unsupported_sectors": [row.model_dump(mode="json") for row in plan.unsupported_sectors],
        "results": results,
    }
    comparison = provider_comparison(coverage)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "coverage_65.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    (output_dir / "provider_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    samples = output_dir / "sample_responses"
    samples.mkdir(exist_ok=True)
    for row in results:
        if set(row["provider_symbols"]) & {"881121", "886111", "881160"}:
            sample = {key: row[key] for key in (
                "sector_key", "sector_name", "mapping_type", "data_status", "provider_symbols",
                "has_any_real_data", "has_120_days", "latest_trade_date", "has_volume",
                "has_turnover_rate", "has_amount", "repeated_request_consistent", "components",
            )}
            (samples / f'{row["sector_key"]}.json').write_text(json.dumps(sample, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return coverage, comparison
