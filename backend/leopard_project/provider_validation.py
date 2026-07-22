from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from .config import CONFIG_DIR, load_seed_bundle
from .models import DailyBar, DataStatus, Market, SectorMapping
from .providers import (
    ProviderError, ProviderErrorCategory, SnapshotAnomaly, ThsPublicValidationProvider,
    detect_snapshot_anomaly, provider_role,
)


REPRESENTATIVE_SYMBOLS = {
    "881121", "881157", "881155", "881175", "881145", "881126",
    "886033", "886050", "886044", "886078", "885530", "885517",
    "HS2083", "884093", "886015", "881267", "885700",
    "881134", "881133", "881279", "885921", "881180", "881107", "881161", "881160",
    "CUSTOM_FOOD_BEVERAGE", "CUSTOM_PV_STORAGE", "CUSTOM_OIL_PETROCHEM", "CUSTOM_HOTEL_CATERING",
}
EXCLUSIVE_CLASSIFICATIONS = (
    "direct_full", "direct_short_history", "cross_market_special",
    "custom_composite_ready", "proxy_only", "unavailable",
)


@dataclass(frozen=True)
class BarAudit:
    row_count: int
    latest_trade_date: str | None
    at_least_120: bool
    dates_sorted: bool
    duplicate_dates: int
    null_fields: int
    ohlc_valid: bool
    price_change_consistent: bool
    deterministic_hash: str | None
    has_amount: bool
    liquidity_statuses: tuple[str, ...]


def canonical_bar_hash(bars: Sequence[DailyBar]) -> str:
    rows = [
        {
            "symbol": bar.symbol, "date": bar.trade_date.isoformat(), "open": str(bar.open),
            "high": str(bar.high), "low": str(bar.low), "close": str(bar.close),
            "pre_close": str(bar.pre_close), "pct_change": str(bar.pct_change),
            "volume": str(bar.volume), "amount": str(bar.amount),
        }
        for bar in bars
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def audit_bars(bars: Sequence[DailyBar]) -> BarAudit:
    days = [bar.trade_date for bar in bars]
    required = ("open", "high", "low", "close", "pre_close", "pct_change")
    null_fields = sum(getattr(bar, field) is None for bar in bars for field in required)
    ohlc_valid = all(bar.high >= max(bar.open, bar.close, bar.low) and bar.low <= min(bar.open, bar.close, bar.high) for bar in bars)
    price_change_consistent = all(
        bar.change == bar.close - bar.pre_close
        and (bar.pre_close == 0 or abs(bar.pct_change - (bar.change / bar.pre_close * Decimal("100"))) < Decimal("0.000001"))
        for bar in bars
    )
    return BarAudit(
        row_count=len(bars), latest_trade_date=max(days).isoformat() if days else None,
        at_least_120=len(bars) >= 120, dates_sorted=days == sorted(days),
        duplicate_dates=len(days) - len(set(days)), null_fields=null_fields,
        ohlc_valid=ohlc_valid, price_change_consistent=price_change_consistent,
        deterministic_hash=canonical_bar_hash(bars) if bars else None,
        has_amount=bool(bars) and all(bar.amount is not None for bar in bars),
        liquidity_statuses=tuple(sorted({bar.liquidity_status.value for bar in bars})),
    )


def validate_expected_name(expected: str, actual: str, *, aliases: Iterable[str] = ()) -> None:
    accepted = {expected, *aliases}
    if actual not in accepted:
        raise ProviderError(
            ProviderErrorCategory.NAME_MISMATCH,
            f"provider name does not match configured mapping: expected={expected!r}, actual={actual!r}",
            retryable=False,
        )


def _composition_definitions() -> dict[str, dict[str, object]]:
    document = json.loads((CONFIG_DIR / "custom_compositions_v2_3.json").read_text(encoding="utf-8"))
    return {row["symbol"]: row for row in document["compositions"]}


def _provider_policy() -> dict[str, object]:
    return json.loads((CONFIG_DIR / "provider_policy_phase1a_v1.json").read_text(encoding="utf-8"))


def _mapping_result(
    mapping: SectorMapping,
    provider: ThsPublicValidationProvider,
    start: date,
    end: date,
    compositions: dict[str, dict[str, object]],
) -> dict[str, object]:
    symbol = mapping.primary_symbol
    if symbol.startswith("CUSTOM_"):
        definition = compositions[symbol]
        if symbol == "CUSTOM_HOTEL_CATERING":
            proxy = _provider_policy()["proxy_mappings"]["hotel_catering"]  # type: ignore[index]
            provider_symbol_value = str(proxy["provider_symbol"])
            try:
                bars = tuple(
                    bar.model_copy(update={"symbol_name": "酒店餐饮", "data_status": DataStatus.PROXY})
                    for bar in provider.historical_daily_bars(provider_symbol_value, start, end, Market.CN_A)
                )
                audit = audit_bars(bars)
                return {
                    "sector_key": mapping.sector_key, "sector_name": mapping.sector_name,
                    "canonical_sector": "酒店餐饮", "original_mapping": symbol,
                    "provider_symbol": provider_symbol_value, "mapping_type": "proxy",
                    "data_status": DataStatus.PROXY, "primary_classification": "proxy_only",
                    "has_any_real_data": bool(bars), "has_120_days": audit.at_least_120,
                    "has_amount": audit.has_amount, "requires_custom_calculation": False,
                    "audit": audit.__dict__, "provider_role": provider_role(provider.provider_key),
                    "replacement_rule": proxy["replacement_rule"], "user_confirmation_required": False,
                }
            except ProviderError as exc:
                return {
                    "sector_key": mapping.sector_key, "sector_name": mapping.sector_name,
                    "canonical_sector": "酒店餐饮", "original_mapping": symbol,
                    "provider_symbol": provider_symbol_value, "mapping_type": "proxy",
                    "data_status": DataStatus.MISSING, "primary_classification": "unavailable",
                    "has_any_real_data": False, "has_120_days": False, "has_amount": False,
                    "requires_custom_calculation": False, "error_category": exc.category,
                    "error": str(exc), "retryable": exc.retryable, "user_confirmation_required": False,
                }
        if "components" in definition:
            component_symbols = [item["symbol"] for item in definition["components"]]  # type: ignore[index]
        else:
            component_symbols = [definition["constituent_source_symbol"], definition["proxy_symbol"]]
        components: list[dict[str, object]] = []
        for component_symbol in component_symbols:
            try:
                bars = provider.historical_daily_bars(str(component_symbol), start, end, Market.CN_A)
                components.append({"symbol": component_symbol, "audit": audit_bars(bars).__dict__})
            except ProviderError as exc:
                components.append({"symbol": component_symbol, "error_category": exc.category, "error": str(exc), "retryable": exc.retryable})
        all_ready = all(item.get("audit", {}).get("at_least_120", False) for item in components)  # type: ignore[union-attr]
        has_any = all(bool(item.get("audit", {}).get("row_count")) for item in components)  # type: ignore[union-attr]
        has_amount = all(bool(item.get("audit", {}).get("has_amount")) for item in components)  # type: ignore[union-attr]
        return {
            "sector_key": mapping.sector_key, "sector_name": mapping.sector_name,
            "original_mapping": symbol,
            "primary_classification": "custom_composite_ready" if all_ready else "unavailable",
            "has_any_real_data": has_any, "has_120_days": all_ready, "has_amount": has_amount,
            "requires_custom_calculation": True, "components": components,
            "name_check": "configuration_only", "provider_role": provider_role(provider.provider_key),
            "user_confirmation_required": False,
        }
    market = Market.HK if symbol in {"HS2083", "HSTECH"} else Market.CN_A
    try:
        first = provider.historical_daily_bars(symbol, start, end, market)
        second = provider.historical_daily_bars(symbol, start, end, market)
        audit = audit_bars(first)
        deterministic = canonical_bar_hash(first) == canonical_bar_hash(second)
        if market == Market.HK:
            classification = "cross_market_special"
            field_note = "HSTECH canonical symbol; HS2083 provider symbol; amount optional and absent"
        elif audit.at_least_120:
            classification = "direct_full"
            field_note = "OHLC, volume and amount direct; pre_close and pct_change derived from adjacent close"
        else:
            classification = "direct_short_history"
            field_note = "mapping valid; real history shorter than 120 sessions"
        return {
            "sector_key": mapping.sector_key, "sector_name": mapping.sector_name,
            "original_mapping": symbol,
            "canonical_symbol": "HSTECH" if market == Market.HK else symbol,
            "provider_symbol": "HS2083" if market == Market.HK else symbol,
            "market": market, "primary_classification": classification,
            "has_any_real_data": bool(first), "has_120_days": audit.at_least_120,
            "has_amount": audit.has_amount, "requires_custom_calculation": False,
            "data_status": DataStatus.NORMAL if audit.at_least_120 else DataStatus.HISTORY_INSUFFICIENT,
            "audit": audit.__dict__,
            "repeated_request_consistent": deterministic, "field_note": field_note,
            "name_check": "verified_from_payload" if market == Market.HK else "not_exposed_by_chart_endpoint",
            "provider_name": provider.provider_key, "provider_role": provider_role(provider.provider_key),
            "fetched_at": first[-1].fetched_at.isoformat() if first else None,
            "source_payload_hash": first[-1].source_payload_hash if first else None,
            "snapshot_anomaly": None,
            "user_confirmation_required": False,
        }
    except ProviderError as exc:
        return {
            "sector_key": mapping.sector_key, "sector_name": mapping.sector_name,
            "original_mapping": symbol, "primary_classification": "unavailable",
            "has_any_real_data": False, "has_120_days": False, "has_amount": False,
            "requires_custom_calculation": False, "error_category": exc.category, "error": str(exc),
            "retryable": exc.retryable, "candidate_replacement": None,
            "basis_difference": None, "user_confirmation_required": True,
        }


def run_validation(
    *,
    scope: str,
    output_dir: Path | None = None,
    provider: ThsPublicValidationProvider | None = None,
    start: date = date(2026, 1, 1),
    end: date | None = None,
) -> dict[str, object]:
    if scope not in {"representative", "all"}:
        raise ValueError("scope must be representative or all")
    previous_hstech: dict[str, object] | None = None
    if output_dir and (output_dir / "coverage.json").exists():
        previous_document = json.loads((output_dir / "coverage.json").read_text(encoding="utf-8"))
        previous_hstech = next(
            (row for row in previous_document.get("results", []) if row.get("sector_key") == "hang_seng_tech"),
            None,
        )
    provider = provider or ThsPublicValidationProvider()
    end = end or date.today()
    mappings = load_seed_bundle().mappings
    if scope == "representative":
        mappings = tuple(mapping for mapping in mappings if mapping.primary_symbol in REPRESENTATIVE_SYMBOLS)
    compositions = _composition_definitions()
    results = [_mapping_result(mapping, provider, start, end, compositions) for mapping in mappings]
    hstech = next((row for row in results if row["sector_key"] == "hang_seng_tech"), None)
    if hstech and hstech.get("audit"):
        anomaly = None
        if previous_hstech and previous_hstech.get("audit"):
            previous_audit = previous_hstech["audit"]
            current_audit = hstech["audit"]
            anomaly = detect_snapshot_anomaly(
                date.fromisoformat(str(previous_audit["latest_trade_date"])), int(previous_audit["row_count"]),
                date.fromisoformat(str(current_audit["latest_trade_date"])), int(current_audit["row_count"]),
            )
        hstech["snapshot_anomaly"] = anomaly
        hstech["eligible_for_normal_write"] = anomaly is None
        if anomaly == SnapshotAnomaly.STALE_SNAPSHOT:
            hstech["data_status"] = DataStatus.STALE_SNAPSHOT
        elif anomaly == SnapshotAnomaly.HISTORY_LENGTH_CHANGED:
            hstech["data_status"] = DataStatus.PROVIDER_ANOMALY
    observed = Counter(str(result["primary_classification"]) for result in results)
    counts = {classification: observed[classification] for classification in EXCLUSIVE_CLASSIFICATIONS}
    if sum(counts.values()) != len(results):
        raise RuntimeError("exclusive coverage classifications do not sum to mapping count")
    coverage = {
        "schema_version": 1, "phase": "1A", "scope": scope,
        "generated_at": datetime.now(UTC).isoformat(), "requested_start": start.isoformat(),
        "requested_end": end.isoformat(), "provider": provider.provider_key,
        "rate_control": {"concurrent_requests": 1, "automatic_retries": 0},
        "summary": {
            "mapping_count": len(results),
            "exclusive_classifications": counts,
            "exclusive_classification_total": sum(counts.values()),
            "overlapping_statistics": {
                key: sum(bool(row[key]) for row in results)
                for key in ("has_any_real_data", "has_120_days", "has_amount", "requires_custom_calculation")
            },
        },
        "results": results,
    }
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        samples = output_dir / "sample_responses"
        samples.mkdir(exist_ok=True)
        for result in results:
            if result.get("audit") and result["original_mapping"] in {"881121", "886033", "HS2083"}:
                sample = {key: result[key] for key in (
                    "sector_name", "original_mapping", "provider_symbol", "market", "provider_name",
                    "fetched_at", "source_payload_hash", "audit", "field_note", "primary_classification",
                    "snapshot_anomaly", "eligible_for_normal_write",
                ) if key in result}
                (samples / f'{result["original_mapping"]}.json').write_text(
                    json.dumps(sample, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
                )
    return coverage
