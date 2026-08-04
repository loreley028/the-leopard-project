"""Explicit, database-free EOD selection for manually approved security proxies.

This module deliberately consumes a research-only EOD input contract.  Existing
``complete_eod`` data is sector-level, so it cannot be silently repurposed for
security-level market-cap, AUM, or leader selection.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .config import CONFIG_DIR
CANDIDATE_POOL_PATH = CONFIG_DIR / "security_proxy_candidate_pool_v1.json"
REGISTRY_PATH = CONFIG_DIR / "security_proxy_registry_v1.json"
SYMBOL = re.compile(r"^(?:sh|sz)\d{6}$")
SLOTS = ("largest_market_cap", "fastest_rebound", "highest_turnover")
DISCLOSURE = "日终证券代理选择仅限人工批准候选池，不替代正式板块，不构成合成指数、综合涨跌幅或投资建议。"


class SecurityProxySelectionError(ValueError):
    """The candidate pool or its research-only input violates the fail-closed contract."""


@dataclass(frozen=True)
class SecurityProxyCandidate:
    symbol: str
    security_name: str
    security_type: str
    semantic_role: str
    semantic_rationale: str
    coverage_type: str
    eligible_for_market_cap_slot: bool
    eligible_for_rebound_slot: bool
    eligible_for_turnover_slot: bool
    enabled: bool
    display_priority: int


@dataclass(frozen=True)
class SecurityProxyExcludedInstrument:
    symbol: str
    reason: str


@dataclass(frozen=True)
class SecurityProxySelectionPolicy:
    policy_version: str
    lookback_trading_days: int = 20
    aum_stale_after_days: int = 60
    tie_break_order: tuple[str, ...] = ("metric", "average_amount", "total_market_cap", "symbol")


@dataclass(frozen=True)
class SecurityProxyCandidatePool:
    market_path_key: str
    display_name: str
    candidate_pool_version: str
    selection_mode: str
    maximum_etfs: int
    maximum_leaders: int
    etf_candidates: tuple[SecurityProxyCandidate, ...]
    stock_candidates: tuple[SecurityProxyCandidate, ...]
    required_instruments: tuple[str, ...]
    excluded_instruments: tuple[SecurityProxyExcludedInstrument, ...]
    auto_fill_rules: tuple[str, ...]
    effective_date: date
    requires_product_review: bool


@dataclass(frozen=True)
class SecurityProxyCandidateMetrics:
    symbol: str
    data_as_of: date
    close: Decimal | None = None
    rolling_low: Decimal | None = None
    rebound_pct: Decimal | None = None
    amount: Decimal | None = None
    total_market_cap: Decimal | None = None
    average_amount: Decimal | None = None
    aum: Decimal | None = None
    aum_as_of: date | None = None
    aum_source: str | None = None
    coverage_type: str | None = None


@dataclass(frozen=True)
class SecurityProxyEodBar:
    """Research-only, security-level complete EOD row; never a formal database model."""

    symbol: str
    trade_date: date
    close: Decimal | None
    low: Decimal | None
    amount: Decimal | None
    total_market_cap: Decimal | None
    eod_status: str = "complete_eod"


@dataclass(frozen=True)
class SecurityProxyEtfAum:
    symbol: str
    aum: Decimal | None
    aum_as_of: date | None
    aum_source: str
    coverage_type: str


@dataclass(frozen=True)
class SecurityProxySelectedInstrument:
    symbol: str
    security_name: str
    proxy_role: str
    selection_source: str
    selection_reasons: tuple[str, ...]
    display_reason: str
    display_order: int
    metrics: SecurityProxyCandidateMetrics
    metrics_as_of: date | None
    semantic_rationale: str
    coverage_type: str


@dataclass(frozen=True)
class SecurityProxyDailySelection:
    market_path_key: str
    display_name: str
    selection_date: date
    data_as_of: date
    candidate_pool_version: str
    policy_version: str
    selection_mode: str
    selected_etf: SecurityProxySelectedInstrument | None
    selected_leaders: tuple[SecurityProxySelectedInstrument, ...]
    excluded_candidates: tuple[SecurityProxyExcludedInstrument, ...]
    warnings: tuple[str, ...]
    disclosure: str
    generated_at: datetime
    status: str


@dataclass(frozen=True)
class SecurityProxySelectionComparison:
    market_path_key: str
    added_symbols: tuple[str, ...]
    retained_symbols: tuple[str, ...]
    removed_symbols: tuple[str, ...]
    reason: str
    changes: tuple["SecurityProxySelectionChange", ...]


@dataclass(frozen=True)
class SecurityProxySelectionChange:
    symbol: str
    change_type: str
    reason: str


def _positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > 0


def _candidate(value: Mapping[str, object]) -> SecurityProxyCandidate:
    return SecurityProxyCandidate(
        symbol=str(value["symbol"]), security_name=str(value["security_name"]), security_type=str(value["security_type"]),
        semantic_role=str(value["semantic_role"]), semantic_rationale=str(value["semantic_rationale"]),
        coverage_type=str(value["coverage_type"]), eligible_for_market_cap_slot=bool(value["eligible_for_market_cap_slot"]),
        eligible_for_rebound_slot=bool(value["eligible_for_rebound_slot"]), eligible_for_turnover_slot=bool(value["eligible_for_turnover_slot"]),
        enabled=bool(value["enabled"]), display_priority=int(value["display_priority"]),
    )


def _pool(value: Mapping[str, object]) -> SecurityProxyCandidatePool:
    excluded = tuple(SecurityProxyExcludedInstrument(symbol=str(item["symbol"]), reason=str(item["reason"])) for item in value["excluded_instruments"])  # type: ignore[index]
    return SecurityProxyCandidatePool(
        market_path_key=str(value["market_path_key"]), display_name=str(value["display_name"]), candidate_pool_version=str(value["candidate_pool_version"]),
        selection_mode=str(value["selection_mode"]), maximum_etfs=int(value["maximum_etfs"]), maximum_leaders=int(value["maximum_leaders"]),
        etf_candidates=tuple(_candidate(item) for item in value["etf_candidates"]),  # type: ignore[arg-type]
        stock_candidates=tuple(_candidate(item) for item in value["stock_candidates"]),  # type: ignore[arg-type]
        required_instruments=tuple(str(item) for item in value["required_instruments"]),  # type: ignore[arg-type]
        excluded_instruments=excluded, auto_fill_rules=tuple(str(item) for item in value["auto_fill_rules"]),  # type: ignore[arg-type]
        effective_date=date.fromisoformat(str(value["effective_date"])), requires_product_review=bool(value["requires_product_review"]),
    )


def validate_security_proxy_candidate_pool(
    document: Mapping[str, object], *, approved_registry_keys: Iterable[str] | None = None,
) -> tuple[SecurityProxySelectionPolicy, tuple[SecurityProxyCandidatePool, ...]]:
    if approved_registry_keys is None:
        registry_document = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        approved_registry_keys = (str(item["market_path_key"]) for item in registry_document["paths"] if item["status"] == "approved_fallback")
    if not document.get("candidate_pool_version") or not document.get("policy_version") or not document.get("disclosure"):
        raise SecurityProxySelectionError("candidate pool requires versioned policy and disclosure")
    policy = SecurityProxySelectionPolicy(
        policy_version=str(document["policy_version"]), lookback_trading_days=int(document.get("default_lookback_trading_days", 20)),
        aum_stale_after_days=int(document.get("aum_stale_after_days", 60)),
    )
    if policy.lookback_trading_days != 20 or policy.aum_stale_after_days <= 0:
        raise SecurityProxySelectionError("the current policy requires a 20-day low and positive AUM staleness window")
    pools = tuple(_pool(value) for value in document.get("paths", []))  # type: ignore[arg-type]
    approved = set(approved_registry_keys)
    if {item.market_path_key for item in pools} != approved or len(pools) != len(approved):
        raise SecurityProxySelectionError("candidate pools must exactly cover approved registry paths and no others")
    if len({item.market_path_key for item in pools}) != len(pools):
        raise SecurityProxySelectionError("candidate pool path keys must be unique")
    forbidden = {"current", "pre_close", "pct_change", "quote_datetime", "price", "fetched_at"}
    for pool in pools:
        if pool.selection_mode not in {"auto", "hybrid", "manual"}:
            raise SecurityProxySelectionError("selection mode is invalid")
        if pool.maximum_etfs not in {0, 1} or not 0 <= pool.maximum_leaders <= 3:
            raise SecurityProxySelectionError("selection maxima exceed the product contract")
        if not pool.auto_fill_rules or any(rule not in SLOTS for rule in pool.auto_fill_rules):
            raise SecurityProxySelectionError("auto fill rules must be explicit ranking slots")
        instruments = pool.etf_candidates + pool.stock_candidates
        symbols = [item.symbol for item in instruments]
        if len(symbols) != len(set(symbols)) or any(not SYMBOL.fullmatch(symbol) for symbol in symbols):
            raise SecurityProxySelectionError("candidate symbols must be unique complete sh/sz securities")
        if any(item.security_type != "etf" for item in pool.etf_candidates) or any(item.security_type != "stock" for item in pool.stock_candidates):
            raise SecurityProxySelectionError("candidate security types do not match their pool")
        if any(item.display_priority < 1 for item in instruments):
            raise SecurityProxySelectionError("candidate display priority must be positive")
        if any(key in forbidden for value in document.get("paths", []) for candidate in (*value.get("etf_candidates", []), *value.get("stock_candidates", [])) for key in candidate):  # type: ignore[union-attr]
            raise SecurityProxySelectionError("candidate config must not contain quote or price fields")
        stock_symbols = {item.symbol for item in pool.stock_candidates if item.enabled}
        excluded_symbols = {item.symbol for item in pool.excluded_instruments}
        if not set(pool.required_instruments) <= stock_symbols or set(pool.required_instruments) & excluded_symbols:
            raise SecurityProxySelectionError("required instruments must be enabled stocks and cannot be excluded")
        if len(pool.required_instruments) > pool.maximum_leaders:
            raise SecurityProxySelectionError("required instruments exceed maximum leaders")
        if pool.selection_mode == "manual" and not pool.required_instruments:
            raise SecurityProxySelectionError("manual paths require explicit instruments")
    by_key = {item.market_path_key: item for item in pools}
    cpo = by_key["cpo"]
    if cpo.selection_mode not in {"manual", "hybrid"} or cpo.maximum_leaders != 3 or cpo.required_instruments != ("sz300308", "sz300502", "sz300394"):
        raise SecurityProxySelectionError("CPO must retain its fixed three-leader contract")
    innovative = by_key["innovative_drug_medicine"]
    if innovative.selection_mode != "hybrid" or innovative.maximum_leaders != 3 or innovative.required_instruments != ("sh603259", "sz300760"):
        raise SecurityProxySelectionError("innovative drug must retain its two required core leaders")
    return policy, pools


def load_security_proxy_candidate_pool(path: Path = CANDIDATE_POOL_PATH) -> tuple[SecurityProxySelectionPolicy, tuple[SecurityProxyCandidatePool, ...]]:
    return validate_security_proxy_candidate_pool(json.loads(path.read_text(encoding="utf-8")))


class SecurityProxyEodSelectionService:
    """Explicit EOD-only selection; it never calls a Provider, scheduler, Viewer, or database."""

    def __init__(self, *, policy: SecurityProxySelectionPolicy | None = None, pools: Sequence[SecurityProxyCandidatePool] | None = None, now: Callable[[], datetime] | None = None) -> None:
        loaded_policy, loaded_pools = load_security_proxy_candidate_pool() if policy is None or pools is None else (policy, tuple(pools))
        self.policy = loaded_policy
        self.pools = {item.market_path_key: item for item in loaded_pools}
        self.now = now or (lambda: datetime.now(timezone.utc))

    def select(
        self, market_path_key: str, *, selection_date: date, data_as_of: date,
        eod_bars: Mapping[str, Sequence[SecurityProxyEodBar]], etf_aums: Mapping[str, SecurityProxyEtfAum],
        previous: SecurityProxyDailySelection | None = None,
    ) -> tuple[SecurityProxyDailySelection, SecurityProxySelectionComparison]:
        if market_path_key not in self.pools:
            raise KeyError(f"security proxy candidate pool is not configured: {market_path_key}")
        if data_as_of > selection_date:
            raise SecurityProxySelectionError("data_as_of cannot be after selection date")
        pool = self.pools[market_path_key]
        warnings: list[str] = []
        metrics = {candidate.symbol: self._metrics(candidate, data_as_of, eod_bars.get(candidate.symbol, ())) for candidate in pool.stock_candidates}
        selected_etf = self._select_etf(pool, data_as_of, etf_aums, previous, warnings)
        excluded = {item.symbol: item for item in pool.excluded_instruments}
        leaders: list[SecurityProxySelectedInstrument] = []
        for symbol in pool.required_instruments:
            candidate = self._stock(pool, symbol)
            if metrics[symbol].close is None:
                warnings.append(f"required_instrument_eod_incomplete:{symbol}")
            leaders.append(self._selected(candidate, "manual_required", ("manual_required",), "固定核心观察", len(leaders) + 1, metrics[symbol], data_as_of))
        if pool.selection_mode in {"auto", "hybrid"}:
            self._fill_auto(pool, metrics, excluded, leaders, data_as_of, warnings)
        status = "complete" if not any(item.startswith("required_instrument_eod_incomplete") for item in warnings) else "partial"
        selection = SecurityProxyDailySelection(
            market_path_key=pool.market_path_key, display_name=pool.display_name, selection_date=selection_date, data_as_of=data_as_of,
            candidate_pool_version=pool.candidate_pool_version, policy_version=self.policy.policy_version, selection_mode=pool.selection_mode,
            selected_etf=selected_etf, selected_leaders=tuple(leaders), excluded_candidates=pool.excluded_instruments,
            warnings=tuple(warnings), disclosure=DISCLOSURE, generated_at=self.now(), status=status,
        )
        return selection, compare_selections(selection, previous)

    def _stock(self, pool: SecurityProxyCandidatePool, symbol: str) -> SecurityProxyCandidate:
        return next(item for item in pool.stock_candidates if item.symbol == symbol)

    def _metrics(self, candidate: SecurityProxyCandidate, data_as_of: date, bars: Sequence[SecurityProxyEodBar]) -> SecurityProxyCandidateMetrics:
        if any(bar.symbol != candidate.symbol for bar in bars):
            raise SecurityProxySelectionError(f"EOD symbol does not match candidate: {candidate.symbol}")
        valid = sorted((bar for bar in bars if bar.eod_status == "complete_eod" and bar.trade_date <= data_as_of), key=lambda item: item.trade_date)
        dates = [bar.trade_date for bar in valid]
        if len(dates) != len(set(dates)):
            raise SecurityProxySelectionError(f"duplicate EOD dates for {candidate.symbol}")
        latest = next((bar for bar in reversed(valid) if bar.trade_date == data_as_of), None)
        if latest is None:
            return SecurityProxyCandidateMetrics(symbol=candidate.symbol, data_as_of=data_as_of)
        recent = valid[-self.policy.lookback_trading_days:]
        lows = [bar.low for bar in recent if _positive(bar.low)]
        rolling_low = min(lows) if len(recent) == self.policy.lookback_trading_days and len(lows) == len(recent) else None
        rebound = ((latest.close / rolling_low) - 1) * Decimal("100") if _positive(latest.close) and _positive(rolling_low) else None
        amounts = [bar.amount for bar in recent if _positive(bar.amount)]
        average_amount = sum(amounts, Decimal("0")) / Decimal(len(amounts)) if amounts else None
        return SecurityProxyCandidateMetrics(
            symbol=candidate.symbol, data_as_of=data_as_of, close=latest.close if _positive(latest.close) else None,
            rolling_low=rolling_low, rebound_pct=rebound, amount=latest.amount if _positive(latest.amount) else None,
            total_market_cap=latest.total_market_cap if _positive(latest.total_market_cap) else None, average_amount=average_amount,
            coverage_type=candidate.coverage_type,
        )

    def _select_etf(self, pool: SecurityProxyCandidatePool, data_as_of: date, etf_aums: Mapping[str, SecurityProxyEtfAum], previous: SecurityProxyDailySelection | None, warnings: list[str]) -> SecurityProxySelectedInstrument | None:
        if pool.maximum_etfs == 0:
            return None
        previous_symbol = previous.selected_etf.symbol if previous and previous.selected_etf else None
        eligible: list[tuple[SecurityProxyCandidate, SecurityProxyEtfAum]] = []
        stale_previous: tuple[SecurityProxyCandidate, SecurityProxyEtfAum] | None = None
        for candidate in pool.etf_candidates:
            data = etf_aums.get(candidate.symbol)
            if not candidate.enabled or data is None or not _positive(data.aum) or data.aum_as_of is None:
                continue
            stale = (data_as_of - data.aum_as_of).days > self.policy.aum_stale_after_days
            if stale:
                warnings.append(f"aum_stale:{candidate.symbol}:{data.aum_as_of.isoformat()}")
                if candidate.symbol == previous_symbol:
                    stale_previous = (candidate, data)
                continue
            eligible.append((candidate, data))
        if eligible:
            candidate, data = sorted(eligible, key=lambda item: (-item[1].aum, item[0].symbol))[0]  # type: ignore[operator]
            metrics = SecurityProxyCandidateMetrics(candidate.symbol, data_as_of, aum=data.aum, aum_as_of=data.aum_as_of, aum_source=data.aum_source, coverage_type=data.coverage_type)
            return self._selected(candidate, "auto_eod", ("largest_aum",), "候选ETF中最新AUM最大", 1, metrics, data.aum_as_of)
        if stale_previous:
            candidate, data = stale_previous
            warnings.append(f"aum_stale_retained_previous:{candidate.symbol}")
            metrics = SecurityProxyCandidateMetrics(candidate.symbol, data_as_of, aum=data.aum, aum_as_of=data.aum_as_of, aum_source=data.aum_source, coverage_type=data.coverage_type)
            return self._selected(candidate, "previous_stale", ("previous_valid_etf",), "沿用上一期有效ETF；AUM已过期", 1, metrics, data.aum_as_of)
        warnings.append("no_eligible_etf")
        return None

    def _fill_auto(self, pool: SecurityProxyCandidatePool, metrics: Mapping[str, SecurityProxyCandidateMetrics], excluded: Mapping[str, SecurityProxyExcludedInstrument], leaders: list[SecurityProxySelectedInstrument], data_as_of: date, warnings: list[str]) -> None:
        selected = {item.symbol: item for item in leaders}
        limit = pool.maximum_leaders
        for slot in pool.auto_fill_rules:
            if len(selected) >= limit:
                break
            ranked = self._rank(pool.stock_candidates, metrics, excluded, slot)
            picked = False
            for candidate in ranked:
                if candidate.symbol in selected:
                    existing = selected[candidate.symbol]
                    if slot not in existing.selection_reasons:
                        replacement = replace(existing, selection_reasons=(*existing.selection_reasons, slot))
                        selected[candidate.symbol] = replacement
                        leaders[leaders.index(existing)] = replacement
                    continue
                metric = metrics[candidate.symbol]
                item = self._selected(candidate, "auto_eod", (slot,), self._reason(slot), len(leaders) + 1, metric, data_as_of)
                leaders.append(item)
                selected[candidate.symbol] = item
                picked = True
                break
            if not picked and not ranked:
                warnings.append(f"no_eligible_candidate:{slot}")

    def _rank(self, candidates: Iterable[SecurityProxyCandidate], metrics: Mapping[str, SecurityProxyCandidateMetrics], excluded: Mapping[str, SecurityProxyExcludedInstrument], slot: str) -> list[SecurityProxyCandidate]:
        eligibility = {
            "largest_market_cap": "eligible_for_market_cap_slot", "fastest_rebound": "eligible_for_rebound_slot", "highest_turnover": "eligible_for_turnover_slot",
        }[slot]
        value = {"largest_market_cap": "total_market_cap", "fastest_rebound": "rebound_pct", "highest_turnover": "amount"}[slot]
        usable = [candidate for candidate in candidates if candidate.enabled and candidate.symbol not in excluded and bool(getattr(candidate, eligibility)) and _positive(getattr(metrics[candidate.symbol], value))]
        def order(candidate: SecurityProxyCandidate) -> tuple[Decimal, Decimal, Decimal, str]:
            metric = metrics[candidate.symbol]
            return (-getattr(metric, value), -(metric.average_amount or Decimal("0")), -(metric.total_market_cap or Decimal("0")), candidate.symbol)
        return sorted(usable, key=order)

    @staticmethod
    def _reason(slot: str) -> str:
        return {"largest_market_cap": "候选池内日终总市值最大", "fastest_rebound": "候选池内20日低点反弹最快", "highest_turnover": "候选池内当日成交额最高"}[slot]

    @staticmethod
    def _selected(candidate: SecurityProxyCandidate, source: str, reasons: tuple[str, ...], display_reason: str, display_order: int, metrics: SecurityProxyCandidateMetrics, metrics_as_of: date | None) -> SecurityProxySelectedInstrument:
        actual_metrics_as_of = metrics_as_of if any(value is not None for value in (metrics.close, metrics.rolling_low, metrics.rebound_pct, metrics.amount, metrics.total_market_cap, metrics.aum)) else None
        return SecurityProxySelectedInstrument(candidate.symbol, candidate.security_name, "etf" if candidate.security_type == "etf" else "leader", source, reasons, display_reason, display_order, metrics, actual_metrics_as_of, candidate.semantic_rationale, candidate.coverage_type)


def compare_selections(current: SecurityProxyDailySelection, previous: SecurityProxyDailySelection | None) -> SecurityProxySelectionComparison:
    current_symbols = {item.symbol for item in current.selected_leaders}
    if current.selected_etf: current_symbols.add(current.selected_etf.symbol)
    previous_symbols = set()
    if previous:
        previous_symbols = {item.symbol for item in previous.selected_leaders}
        if previous.selected_etf: previous_symbols.add(previous.selected_etf.symbol)
    added, retained, removed = tuple(sorted(current_symbols - previous_symbols)), tuple(sorted(current_symbols & previous_symbols)), tuple(sorted(previous_symbols - current_symbols))
    changes = tuple(
        [SecurityProxySelectionChange(symbol, "added", "selected_by_current_eod_policy") for symbol in added]
        + [SecurityProxySelectionChange(symbol, "retained", "remains_in_current_eod_selection") for symbol in retained]
        + [SecurityProxySelectionChange(symbol, "removed", "not_selected_by_current_eod_policy") for symbol in removed]
    )
    return SecurityProxySelectionComparison(current.market_path_key, added, retained, removed, "same_candidate_pool_required_for_future_stability_policy", changes)


def selection_to_dict(value: SecurityProxyDailySelection | SecurityProxySelectionComparison) -> dict[str, object]:
    def normalize(item: object) -> object:
        if isinstance(item, Decimal): return str(item)
        if isinstance(item, (date, datetime)): return item.isoformat()
        if isinstance(item, tuple): return [normalize(value) for value in item]
        if isinstance(item, list): return [normalize(value) for value in item]
        if isinstance(item, dict): return {key: normalize(value) for key, value in item.items()}
        return item
    return normalize(asdict(value))  # type: ignore[return-value]
