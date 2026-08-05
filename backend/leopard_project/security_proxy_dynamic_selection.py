"""File-backed, next-trading-day security-proxy selection snapshots.

Selection is deliberately deterministic and entirely local.  It consumes only
the approved candidate pool, audited preferences, and file-backed EOD rows;
it never fetches a quote or selects a user supplied security.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

from .security_proxy_eod import SecurityProxyEodFileStore, SecurityProxyEodRecord, atomic_write_text
from .security_proxy_eod_selection import SecurityProxyCandidate, load_security_proxy_candidate_pool
from .trading_calendar import CalendarStatus, load_calendar


PREFERENCES_PATH = Path(__file__).parent.parent.parent / "config" / "security_proxy_selection_preferences_v1.json"
DISCLOSURE = "代理证券用于观察主题相关标的表现，不代表官方板块指数或完整行业表现。"


class SecurityProxyDynamicSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class SecurityProxySelectionPreference:
    market_path_key: str
    enabled: bool
    required_symbols: tuple[str, ...]
    eligible_etf_symbols: tuple[str, ...]
    eligible_large_cap_symbols: tuple[str, ...]
    auto_rebound_slots: int
    auto_turnover_slots: int
    excluded_symbols: tuple[str, ...]
    approval_note: str
    approved_at: date
    policy_version: str
    curated_etf_symbol: str | None = None
    curated_etf_note: str | None = None
    curated_etf_reviewed_at: date | None = None
    curated_etf_coverage: str | None = None
    curated_etf_replaceable: bool = True
    migration_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecurityProxySelectedInstrumentSnapshot:
    symbol: str
    security_name: str
    instrument_type: str
    proxy_coverage: str
    selection_reasons: tuple[str, ...]
    selection_source: str
    required_manual: bool
    metric_values: dict[str, str | None]
    metric_statuses: dict[str, str]


@dataclass(frozen=True)
class SecurityProxySelectionSnapshot:
    market_path_key: str
    calculation_trading_date: date
    effective_from_trading_date: date
    selected_instruments: tuple[SecurityProxySelectedInstrumentSnapshot, ...]
    policy_version: str
    generated_at: datetime
    warnings: tuple[str, ...]


def _as_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SecurityProxyDynamicSelectionError("preference list must be a list")
    return tuple(str(item).lower() for item in value)


def load_selection_preferences(path: Path = PREFERENCES_PATH) -> tuple[SecurityProxySelectionPreference, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not document.get("policy_version") or not document.get("disclosure"):
        raise SecurityProxyDynamicSelectionError("preferences need a policy version and disclosure")
    _, pools = load_security_proxy_candidate_pool()
    pool_map = {pool.market_path_key: pool for pool in pools}
    values: list[SecurityProxySelectionPreference] = []
    for raw in document.get("paths", []):
        if not isinstance(raw, dict):
            raise SecurityProxyDynamicSelectionError("preference path must be an object")
        key = str(raw["market_path_key"])
        pool = pool_map.get(key)
        if pool is None:
            raise SecurityProxyDynamicSelectionError(f"unapproved preference path: {key}")
        old_etfs, old_large = "preferred_etf_symbols" in raw, "preferred_large_cap_symbols" in raw
        if "eligible_etf_symbols" not in raw and not old_etfs or "eligible_large_cap_symbols" not in raw and not old_large:
            raise SecurityProxyDynamicSelectionError(f"preferences need eligible candidate sets for {key}")
        migration = tuple(name for name, present in (("deprecated_preferred_etf_symbols", old_etfs), ("deprecated_preferred_large_cap_symbols", old_large)) if present)
        curated_raw = raw.get("curated_etf_symbol")
        curated_symbol = str(curated_raw).lower() if curated_raw else None
        preference = SecurityProxySelectionPreference(
            market_path_key=key,
            enabled=bool(raw["enabled"]),
            required_symbols=_as_tuple(raw["required_symbols"]),
            eligible_etf_symbols=_as_tuple(raw.get("eligible_etf_symbols", raw.get("preferred_etf_symbols", []))),
            eligible_large_cap_symbols=_as_tuple(raw.get("eligible_large_cap_symbols", raw.get("preferred_large_cap_symbols", []))),
            auto_rebound_slots=int(raw["auto_rebound_slots"]),
            auto_turnover_slots=int(raw["auto_turnover_slots"]),
            excluded_symbols=_as_tuple(raw["excluded_symbols"]),
            approval_note=str(raw["approval_note"]),
            approved_at=date.fromisoformat(str(raw["approved_at"])),
            policy_version=str(raw["policy_version"]),
            curated_etf_symbol=curated_symbol,
            curated_etf_note=str(raw["curated_etf_note"]) if raw.get("curated_etf_note") else None,
            curated_etf_reviewed_at=date.fromisoformat(str(raw["curated_etf_reviewed_at"])) if raw.get("curated_etf_reviewed_at") else None,
            curated_etf_coverage=str(raw["curated_etf_coverage"]) if raw.get("curated_etf_coverage") else None,
            curated_etf_replaceable=bool(raw.get("curated_etf_replaceable", True)),
            migration_warnings=migration,
        )
        symbols = {candidate.symbol for candidate in (*pool.etf_candidates, *pool.stock_candidates) if candidate.enabled}
        etfs = {candidate.symbol for candidate in pool.etf_candidates if candidate.enabled}
        stocks = {candidate.symbol for candidate in pool.stock_candidates if candidate.enabled}
        if not preference.enabled or preference.policy_version != document["policy_version"]:
            raise SecurityProxyDynamicSelectionError(f"invalid policy state for {key}")
        if not set(preference.required_symbols) <= stocks or not set(preference.eligible_etf_symbols) <= etfs:
            raise SecurityProxyDynamicSelectionError(f"preferences contain unapproved symbols for {key}")
        if preference.curated_etf_symbol and preference.curated_etf_symbol not in etfs:
            raise SecurityProxyDynamicSelectionError(f"curated ETF is not approved for {key}")
        if preference.curated_etf_symbol and preference.curated_etf_symbol in preference.excluded_symbols:
            raise SecurityProxyDynamicSelectionError(f"curated ETF is excluded for {key}")
        if preference.curated_etf_symbol and not preference.curated_etf_note:
            raise SecurityProxyDynamicSelectionError(f"curated ETF needs a review note for {key}")
        if not set(preference.eligible_large_cap_symbols) <= stocks or len(preference.eligible_large_cap_symbols) > 2:
            raise SecurityProxyDynamicSelectionError(f"large-cap preferences invalid for {key}")
        if not set(preference.excluded_symbols) <= symbols or set(preference.excluded_symbols) & set(preference.required_symbols):
            raise SecurityProxyDynamicSelectionError(f"exclusion rules invalid for {key}")
        if preference.auto_rebound_slots < 0 or preference.auto_turnover_slots < 0:
            raise SecurityProxyDynamicSelectionError(f"automatic slot count invalid for {key}")
        values.append(preference)
    if set(item.market_path_key for item in values) != set(pool_map) or len(values) != len(pool_map):
        raise SecurityProxyDynamicSelectionError("preferences must exactly cover the 11 approved proxy paths")
    return tuple(sorted(values, key=lambda item: item.market_path_key))


def next_controlled_trading_day(day: date) -> date:
    calendar = load_calendar()
    if calendar is None:
        raise SecurityProxyDynamicSelectionError("controlled trading calendar unavailable")
    for candidate in sorted(calendar.trading_dates()):
        if candidate > day:
            return candidate
    raise SecurityProxyDynamicSelectionError("next controlled trading day unavailable")


def _metric(rows: Iterable[SecurityProxyEodRecord], symbol: str, calculation_date: date) -> dict[str, Decimal | None | str]:
    values = sorted((row for row in rows if row.symbol == symbol and row.trading_date <= calculation_date and row.completeness_status in {"complete", "partial_amount_missing"}), key=lambda row: row.trading_date)
    if len({row.trading_date for row in values}) != len(values):
        raise SecurityProxyDynamicSelectionError(f"duplicate history for {symbol}")
    latest = values[-1] if values and values[-1].trading_date == calculation_date else None
    if latest is None:
        return {"history_days": str(len(values)), "latest_close": None, "latest_amount_yuan": None, "median_amount_yuan": None, "rolling_20d_low": None, "rebound_pct": None, "rebound_status": "missing_latest_eod", "turnover_status": "missing_latest_eod"}
    recent = values[-20:]
    low = min((row.low for row in recent), default=None) if len(recent) == 20 else None
    rebound = latest.close / low - Decimal("1") if low is not None else None
    amounts = sorted(row.amount_yuan for row in recent if row.amount_yuan is not None and row.amount_yuan > 0)
    median = amounts[len(amounts) // 2] if len(amounts) % 2 else (amounts[len(amounts) // 2 - 1] + amounts[len(amounts) // 2]) / Decimal("2") if amounts else None
    liquidity_status = "available" if len(recent) == 20 and len(amounts) == 20 else "liquidity_history_partial" if len(values) >= 5 and len(amounts) >= 5 else "insufficient_liquidity_history"
    return {"history_days": str(len(values)), "latest_close": latest.close, "latest_amount_yuan": latest.amount_yuan, "median_amount_yuan": median, "rolling_20d_low": low, "rebound_pct": rebound, "rebound_status": "available" if rebound is not None else "insufficient_history", "turnover_status": "available" if latest.amount_yuan is not None else "missing_amount", "liquidity_status": liquidity_status}


def _snapshot_item(candidate: SecurityProxyCandidate, *, reasons: list[str], source: str, required: bool, metrics: Mapping[str, Decimal | None | str]) -> SecurityProxySelectedInstrumentSnapshot:
    values = {key: str(value) if isinstance(value, Decimal) else value for key, value in metrics.items() if key in {"latest_close", "latest_amount_yuan", "median_amount_yuan", "rolling_20d_low", "rebound_pct", "history_days"}}
    statuses = {key: str(value) for key, value in metrics.items() if key in {"rebound_status", "turnover_status", "liquidity_status"}}
    return SecurityProxySelectedInstrumentSnapshot(candidate.symbol, candidate.security_name, candidate.security_type, candidate.coverage_type, tuple(reasons), source, required, values, statuses)


class SecurityProxySelectionSnapshotStore:
    def __init__(self, root: Path = Path("var/security-proxy-selections")) -> None:
        self.root = root

    def day_path(self, day: date) -> Path:
        return self.root / str(day.year) / f"{day.isoformat()}.json"

    def write(self, *, calculation_date: date, snapshots: Iterable[SecurityProxySelectionSnapshot], allow_research_overwrite: bool = False) -> Path:
        entries = tuple(sorted(snapshots, key=lambda value: value.market_path_key))
        if not entries:
            raise SecurityProxyDynamicSelectionError("refusing empty selection snapshot")
        if any(value.calculation_trading_date != calculation_date for value in entries):
            raise SecurityProxyDynamicSelectionError("selection snapshot date mismatch")
        document = {"calculation_trading_date": calculation_date.isoformat(), "effective_from_trading_date": entries[0].effective_from_trading_date.isoformat(), "selections": [_to_dict(value) for value in entries]}
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        path = self.day_path(calculation_date)
        atomic_write_text(path, content, allow_overwrite=allow_research_overwrite)
        atomic_write_text(self.root / "latest.json", content)
        return path

    def latest_effective_for(self, day: date) -> dict[str, SecurityProxySelectionSnapshot]:
        candidates: list[SecurityProxySelectionSnapshot] = []
        for path in sorted(self.root.glob("*/*.json")):
            candidates.extend(_from_dict(row) for row in json.loads(path.read_text(encoding="utf-8")).get("selections", []))
        effective = [row for row in candidates if row.effective_from_trading_date <= day]
        chosen: dict[str, SecurityProxySelectionSnapshot] = {}
        for row in sorted(effective, key=lambda item: (item.effective_from_trading_date, item.calculation_trading_date)):
            chosen[row.market_path_key] = row
        return chosen


class SecurityProxyDynamicSelectionService:
    def __init__(self, *, preferences: Iterable[SecurityProxySelectionPreference] | None = None, pools: Iterable[object] | None = None, verified_aums: Mapping[str, Decimal] | None = None, verified_market_caps: Mapping[str, Decimal] | None = None, now=lambda: datetime.now(timezone.utc)) -> None:
        self.preferences = {value.market_path_key: value for value in (preferences or load_selection_preferences())}
        _, loaded_pools = load_security_proxy_candidate_pool()
        self.pools = {pool.market_path_key: pool for pool in (tuple(pools) if pools is not None else loaded_pools)}
        # Kept as a read-compatible constructor argument. Curated ETF selection
        # deliberately never reads AUM, shares, or ETF turnover history.
        del verified_aums
        self.verified_market_caps = dict(verified_market_caps or {})
        self.now = now

    def build(self, calculation_date: date, records: Iterable[SecurityProxyEodRecord]) -> tuple[SecurityProxySelectionSnapshot, ...]:
        next_day = next_controlled_trading_day(calculation_date)
        all_records = tuple(records)
        result: list[SecurityProxySelectionSnapshot] = []
        for key, preference in sorted(self.preferences.items()):
            pool = self.pools[key]
            candidates = {item.symbol: item for item in (*pool.etf_candidates, *pool.stock_candidates) if item.enabled}
            metrics = {symbol: _metric(all_records, symbol, calculation_date) for symbol in candidates}
            selected: list[SecurityProxySelectedInstrumentSnapshot] = []
            used: dict[str, SecurityProxySelectedInstrumentSnapshot] = {}
            warnings: list[str] = []
            def choose(symbol: str, reason: str, source: str, required: bool = False) -> None:
                if symbol in preference.excluded_symbols:
                    return
                candidate = candidates[symbol]
                if symbol in used:
                    old = used[symbol]
                    updated = SecurityProxySelectedInstrumentSnapshot(old.symbol, old.security_name, old.instrument_type, old.proxy_coverage, (*old.selection_reasons, reason), old.selection_source, old.required_manual or required, old.metric_values, old.metric_statuses)
                    selected[selected.index(old)] = updated; used[symbol] = updated; return
                item = _snapshot_item(candidate, reasons=[reason], source=source, required=required, metrics=metrics[symbol])
                selected.append(item); used[symbol] = item
            for symbol in preference.required_symbols:
                choose(symbol, "required_manual", "manual_approved", True)
                if metrics[symbol]["latest_close"] is None:
                    warnings.append(f"required_latest_eod_missing:{symbol}")
            self._choose_etf(pool, preference, metrics, choose, warnings)
            self._choose_large_caps(preference, metrics, choose, warnings)
            for reason, count, metric_key, status_key in (("fastest_20d_rebound", preference.auto_rebound_slots, "rebound_pct", "rebound_status"), ("highest_latest_turnover", preference.auto_turnover_slots, "latest_amount_yuan", "turnover_status")):
                ranked = sorted((candidate for candidate in pool.stock_candidates if candidate.enabled and candidate.symbol not in preference.excluded_symbols and metrics[candidate.symbol][status_key] == "available" and isinstance(metrics[candidate.symbol][metric_key], Decimal)), key=lambda item: (-metrics[item.symbol][metric_key], item.symbol))  # type: ignore[operator]
                count_before = len(selected)
                for candidate in ranked:
                    choose(candidate.symbol, reason, "dynamic_eod_metric")
                    if len(selected) >= count_before + count:
                        break
                if len(selected) < count_before + count:
                    warnings.append(f"insufficient_{reason}_candidates")
            result.append(SecurityProxySelectionSnapshot(key, calculation_date, next_day, tuple(selected), preference.policy_version, self.now(), tuple(warnings)))
        return tuple(result)

    def _choose_etf(self, pool, preference, metrics, choose, warnings) -> None:
        # ETFs are configuration-curated observation instruments. They are never
        # ranked by AUM, shares, EOD turnover, return, or any same-day metric.
        del pool, metrics, warnings
        if preference.curated_etf_symbol:
            choose(preference.curated_etf_symbol, "curated_observation_etf", "curated_configuration")

    def _choose_large_caps(self, preference, metrics, choose, warnings) -> None:
        candidates = [symbol for symbol in preference.eligible_large_cap_symbols if symbol not in preference.excluded_symbols]
        verified = [symbol for symbol in candidates if self.verified_market_caps.get(symbol, Decimal("0")) > 0]
        for index, symbol in enumerate(sorted(verified, key=lambda value: (-self.verified_market_caps[value], value))[:2]):
            choose(symbol, "highest_verified_market_cap" if index == 0 else "second_verified_market_cap", "automatic_verified_metric")
        for symbol in candidates:
            if len(verified) >= 2: break
            if symbol not in verified:
                choose(symbol, "approved_large_cap_candidate", "approved_candidate")
                warnings.append(f"market_cap_unverified:{symbol}")
                verified.append(symbol)


def _to_dict(value: SecurityProxySelectionSnapshot) -> dict[str, object]:
    data = asdict(value)
    data["calculation_trading_date"] = value.calculation_trading_date.isoformat()
    data["effective_from_trading_date"] = value.effective_from_trading_date.isoformat()
    data["generated_at"] = value.generated_at.isoformat()
    return data


def _from_dict(raw: Mapping[str, object]) -> SecurityProxySelectionSnapshot:
    instruments = tuple(SecurityProxySelectedInstrumentSnapshot(
        str(item["symbol"]), str(item["security_name"]), str(item["instrument_type"]), str(item["proxy_coverage"]), tuple(item["selection_reasons"]), str(item["selection_source"]), bool(item["required_manual"]), dict(item["metric_values"]), dict(item["metric_statuses"]),
    ) for item in raw["selected_instruments"])  # type: ignore[index]
    return SecurityProxySelectionSnapshot(str(raw["market_path_key"]), date.fromisoformat(str(raw["calculation_trading_date"])), date.fromisoformat(str(raw["effective_from_trading_date"])), instruments, str(raw["policy_version"]), datetime.fromisoformat(str(raw["generated_at"])), tuple(raw.get("warnings", [])))
