from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from http.client import RemoteDisconnected

from sqlalchemy import select

from leopard_project.config import load_seed_bundle
from leopard_project.models import DailyBar, DataStatus, LiquidityStatus, Market, ProviderNativeClose
from leopard_project.providers.base import ProviderError, ProviderErrorCategory
from leopard_project.providers.capabilities import ProviderCandidate, SectorCapability, load_provider_capabilities
from leopard_project.providers.health import ProviderCircuitBreaker, classify_provider_failure
from leopard_project.providers.intraday_chain import ResearchIntradayProviderChain
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import ProviderHealthRecord


NOW = datetime(2026, 7, 30, 2, 0, tzinfo=timezone.utc)


def candidate(provider: str, priority: int = 10, status: str = "validated") -> ProviderCandidate:
    return ProviderCandidate(
        provider=provider, symbol="881121", provider_name="半导体", mapping_type="direct",
        priority=priority, spot_supported=True, history_supported=True, exact_mapping=True,
        validation_status=status, components=(),
    )


def capability(*candidates: ProviderCandidate) -> dict[str, SectorCapability]:
    return {"semiconductor": SectorCapability(
        sector_key="semiconductor", display_name="半导体", mapping_type="direct",
        primary_provider=candidates[0].provider, candidates=tuple(candidates),
    )}


def complete_bar(provider: str, symbol: str = "881121") -> DailyBar:
    history = tuple(ProviderNativeClose(
        provider=provider, provider_symbol=symbol, trade_date=date(2026, 7, day),
        close=Decimal(str(100 + day)), source_payload_hash=str(day) * 64,
        lineage=f"{provider}:{symbol}",
    ) for day in (24, 27, 28, 29))
    return DailyBar(
        symbol=symbol, symbol_name="半导体", market=Market.CN_A, trade_date=date(2026, 7, 30),
        open=Decimal("130"), high=Decimal("132"), low=Decimal("129"), close=Decimal("131"),
        pre_close=Decimal("130"), change=Decimal("1"), pct_change=Decimal("0.769231"),
        volume=Decimal("100"), amount=None, turnover_rate=None, liquidity_status=LiquidityStatus.PARTIAL,
        provider=provider, fetched_at=NOW, source_payload_hash="a" * 64, data_status=DataStatus.NORMAL,
        provider_symbol=symbol, lineage=f"provider={provider}", provider_native_history=history,
        provider_native_history_status="complete",
    )


class StubProvider:
    def __init__(self, key: str, result: DailyBar | Exception) -> None:
        self.provider_key, self.result, self.request_count = key, result, 0

    def begin_cycle(self) -> None:
        self.request_count = 0

    def fetch_intraday_snapshot(self, _mapping, _as_of):
        self.request_count += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def policy(threshold: int = 2, recovery: int = 2) -> dict:
    return {
        "failure_threshold": threshold, "base_cooldown_seconds": 30, "max_cooldown_seconds": 60,
        "half_open_success_threshold": recovery, "manual_probe_min_interval_seconds": 300,
        "providers": {
            "eastmoney_board_spot": {"endpoint_family": "east", "probe_sector_key": "semiconductor"},
            "ths_exact_spot": {"endpoint_family": "ths", "probe_sector_key": "semiconductor"},
        },
    }


def test_capability_matrix_is_exact_mutually_scoped_and_fail_closed() -> None:
    rows = load_provider_capabilities()
    assert len(rows) == 65 and "hang_seng_tech" not in rows
    assert sum(bool(row.selectable_candidates) for row in rows.values()) == 47
    assert rows["hotel_catering"].mapping_type == "proxy"
    assert rows["food_beverage"].mapping_type == "composite"
    assert not rows["hotel_catering"].selectable_candidates
    assert all(item.validation_status == "validated" for row in rows.values() for item in row.selectable_candidates)


def test_circuit_opens_persists_and_suppresses_until_cooldown(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'health.sqlite3'}")
    clock = [NOW]
    breaker = ProviderCircuitBreaker(sessions, now=lambda: clock[0], policy=policy())
    assert breaker.decision("eastmoney_board_spot").state == "closed"
    breaker.record_failure("eastmoney_board_spot", RemoteDisconnected("empty"))
    assert breaker.decision("eastmoney_board_spot").allowed
    breaker.record_failure("eastmoney_board_spot", RemoteDisconnected("empty"))
    assert breaker.decision("eastmoney_board_spot").reason == "primary_provider_circuit_open"
    restored = ProviderCircuitBreaker(sessions, now=lambda: clock[0], policy=policy())
    assert not restored.decision("eastmoney_board_spot").allowed
    clock[0] += timedelta(seconds=31)
    assert restored.decision("eastmoney_board_spot").state == "half_open"


def test_half_open_requires_two_successes_and_failure_reopens(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'recovery.sqlite3'}")
    clock = [NOW]
    breaker = ProviderCircuitBreaker(sessions, now=lambda: clock[0], policy=policy(threshold=1))
    breaker.record_failure("ths_exact_spot", TimeoutError("timeout"))
    clock[0] += timedelta(seconds=31)
    breaker.record_success("ths_exact_spot")
    assert breaker.rows()[0]["state"] == "half_open"
    breaker.record_failure("ths_exact_spot", TimeoutError("again"))
    assert breaker.rows()[0]["state"] == "open"
    clock[0] += timedelta(seconds=61)
    breaker.record_success("ths_exact_spot")
    breaker.record_success("ths_exact_spot")
    assert breaker.rows()[0]["state"] == "closed"


def test_endpoint_families_are_isolated_and_cooldown_is_capped(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'isolation.sqlite3'}")
    breaker = ProviderCircuitBreaker(sessions, now=lambda: NOW, policy=policy(threshold=1))
    breaker.record_failure("eastmoney_board_spot", ConnectionResetError())
    assert not breaker.decision("eastmoney_board_spot").allowed
    assert breaker.decision("ths_exact_spot").allowed
    with sessions() as session:
        row = session.scalar(select(ProviderHealthRecord).where(ProviderHealthRecord.provider == "eastmoney_board_spot"))
        assert row and row.cooldown_seconds <= 60


def test_admin_probe_cannot_bypass_minimum_interval(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'probe.sqlite3'}")
    breaker = ProviderCircuitBreaker(sessions, now=lambda: NOW, policy=policy())
    breaker.record_success("ths_exact_spot")
    decision = breaker.manual_probe_decision("ths_exact_spot")
    assert not decision.allowed and decision.reason == "manual_probe_rate_limited"


def test_error_classification_is_not_flattened_to_network() -> None:
    assert classify_provider_failure(RemoteDisconnected()) == "remote_disconnected"
    assert classify_provider_failure(ConnectionResetError()) == "connection_reset"
    assert classify_provider_failure(TimeoutError()) == "timeout"
    try:
        try:
            raise RemoteDisconnected("empty")
        except RemoteDisconnected as cause:
            raise ProviderError(ProviderErrorCategory.NETWORK, "sanitized", retryable=True) from cause
    except ProviderError as wrapped:
        assert classify_provider_failure(wrapped) == "remote_disconnected"


def test_chain_uses_validated_fallback_and_same_provider_symbol() -> None:
    primary = StubProvider("eastmoney_board_spot", RemoteDisconnected("empty"))
    fallback = StubProvider("ths_exact_spot", complete_bar("ths_exact_spot"))
    chain = ResearchIntradayProviderChain(
        eastmoney=primary, ths_exact=fallback,
        capabilities=capability(candidate("eastmoney_board_spot"), candidate("ths_exact_spot", 20)),
    )
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    chain.begin_cycle()
    result = chain.fetch_intraday_snapshot(mapping, NOW)
    assert result.provider == "ths_exact_spot"
    assert "fallback_used=true" in result.lineage and "same_provider_same_symbol=true" in result.lineage
    assert chain.cycle_stats["fallback_success_count"] == 1


def test_provider_failure_does_not_fan_out_within_cycle() -> None:
    failed = StubProvider("eastmoney_board_spot", RemoteDisconnected("empty"))
    fallback = StubProvider("ths_exact_spot", complete_bar("ths_exact_spot"))
    chain = ResearchIntradayProviderChain(
        eastmoney=failed, ths_exact=fallback,
        capabilities=capability(candidate("eastmoney_board_spot"), candidate("ths_exact_spot", 20)),
    )
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    chain.begin_cycle()
    chain.fetch_intraday_snapshot(mapping, NOW)
    chain.fetch_intraday_snapshot(mapping, NOW)
    assert failed.request_count == 1
    assert fallback.request_count == 2


def test_half_open_allows_one_probe_then_recovers_on_next_cycle(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'half-open-chain.sqlite3'}")
    clock = [NOW]
    breaker = ProviderCircuitBreaker(sessions, now=lambda: clock[0], policy=policy(threshold=1, recovery=2))
    breaker.record_failure("ths_exact_spot", TimeoutError())
    clock[0] += timedelta(seconds=31)
    provider = StubProvider("ths_exact_spot", complete_bar("ths_exact_spot"))
    chain = ResearchIntradayProviderChain(
        eastmoney=StubProvider("eastmoney_board_spot", RemoteDisconnected()), ths_exact=provider,
        capabilities=capability(candidate("ths_exact_spot")), breaker=breaker,
    )
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    chain.begin_cycle()
    chain.fetch_intraday_snapshot(mapping, clock[0])
    try:
        chain.fetch_intraday_snapshot(mapping, clock[0])
    except ProviderError:
        pass
    else:
        raise AssertionError("half-open provider must not fan out after one recovery probe")
    assert provider.request_count == 1 and breaker.rows()[0]["state"] == "half_open"
    chain.begin_cycle()
    chain.fetch_intraday_snapshot(mapping, clock[0])
    chain.fetch_intraday_snapshot(mapping, clock[0])
    assert provider.request_count == 2 and breaker.rows()[0]["state"] == "closed"


def test_unverified_candidate_is_never_called_and_no_fallback_fails_closed() -> None:
    unverified = StubProvider("eastmoney_board_spot", complete_bar("eastmoney_board_spot"))
    chain = ResearchIntradayProviderChain(
        eastmoney=unverified, ths_exact=StubProvider("ths_exact_spot", complete_bar("ths_exact_spot")),
        capabilities=capability(candidate("eastmoney_board_spot", status="unverified_rate_limited")),
    )
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    chain.begin_cycle()
    try:
        chain.fetch_intraday_snapshot(mapping, NOW)
    except ProviderError as exc:
        assert "no_valid_fallback" in str(exc)
    else:
        raise AssertionError("unverified candidate must fail closed")
    assert unverified.request_count == 0


def test_cross_provider_history_is_rejected() -> None:
    bad = complete_bar("ths_exact_spot").model_copy(update={
        "provider_native_history": tuple(item.model_copy(update={"provider": "other"}) for item in complete_bar("ths_exact_spot").provider_native_history)
    })
    provider = StubProvider("ths_exact_spot", bad)
    chain = ResearchIntradayProviderChain(
        eastmoney=StubProvider("eastmoney_board_spot", RemoteDisconnected()), ths_exact=provider,
        capabilities=capability(candidate("ths_exact_spot")),
    )
    mapping = next(item for item in load_seed_bundle().mappings if item.sector_key == "semiconductor")
    chain.begin_cycle()
    try:
        chain.fetch_intraday_snapshot(mapping, NOW)
    except ProviderError as exc:
        assert "all_providers_unavailable" in str(exc)
    else:
        raise AssertionError("cross-provider history must fail closed")
