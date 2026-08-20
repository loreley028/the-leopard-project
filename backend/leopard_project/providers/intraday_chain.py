from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from ..models import DailyBar, SectorMapping
from .eastmoney_spot import EastmoneyBoardSpotProvider
from .base import ProviderError, ProviderErrorCategory
from .capabilities import SectorCapability, load_provider_capabilities
from .health import ProviderCircuitBreaker, classify_provider_failure
from .ths_exact_spot import ThsExactSpotProvider


class ResearchIntradayProviderChain:
    """Explicit local research chain; never promotes either source to production."""

    provider_key = "research_intraday_chain"
    provider_role = "research_provider"
    def __init__(
        self,
        *,
        eastmoney: EastmoneyBoardSpotProvider | None = None,
        ths_exact: ThsExactSpotProvider | None = None,
        sessions: sessionmaker[Session] | None = None,
        capabilities: dict[str, SectorCapability] | None = None,
        breaker: ProviderCircuitBreaker | None = None,
    ) -> None:
        self.eastmoney = eastmoney or EastmoneyBoardSpotProvider()
        self.ths_exact = ths_exact or ThsExactSpotProvider()
        self.providers = {
            self.eastmoney.provider_key: self.eastmoney,
            self.ths_exact.provider_key: self.ths_exact,
        }
        self.capabilities = capabilities or load_provider_capabilities()
        self.breaker = breaker or (ProviderCircuitBreaker(sessions) if sessions is not None else None)
        self._cycle_unavailable: dict[str, str] = {}
        self._cycle_checked: set[str] = set()
        self._stats: dict[str, int] = {
            "health_probe_count": 0,
            "primary_skipped_count": 0,
            "fallback_success_count": 0,
            "no_fallback_count": 0,
        }

    @property
    def request_count(self) -> int:
        return self.eastmoney.request_count + self.ths_exact.request_count

    def begin_cycle(self) -> None:
        self.eastmoney.begin_cycle()
        self.ths_exact.begin_cycle()
        self._cycle_unavailable = {}
        self._cycle_checked = set()
        self._stats = {
            "health_probe_count": 0,
            "primary_skipped_count": 0,
            "fallback_success_count": 0,
            "no_fallback_count": 0,
        }

    @property
    def cycle_stats(self) -> dict[str, int]:
        return dict(self._stats)

    def health_rows(self, session: Session | None = None) -> list[dict]:
        """Use the caller's short-lived Reader session when available."""
        return self.breaker.rows(session=session) if self.breaker else []

    def probe_provider(self, provider_key: str, mappings: dict[str, SectorMapping], as_of: datetime) -> dict:
        """Run exactly one configured representative request; never marks healthy by fiat."""
        if self.breaker is None or provider_key not in self.providers:
            raise ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "provider health probe unavailable", retryable=False)
        decision = self.breaker.manual_probe_decision(provider_key)
        if not decision.allowed:
            return {"provider": provider_key, "status": "cooldown_active", "reason": decision.reason}
        probe_key = str(self.breaker.policy["providers"][provider_key]["probe_sector_key"])
        capability = self.capabilities[probe_key]
        candidate = next((item for item in capability.selectable_candidates if item.provider == provider_key), None)
        if candidate is None:
            return {"provider": provider_key, "status": "unverified_probe_mapping"}
        provider = self.providers[provider_key]
        try:
            bar = provider.fetch_intraday_snapshot(self._candidate_mapping(mappings[probe_key], candidate.symbol), as_of)
            if bar.provider_native_history_status != "complete" or len(bar.provider_native_history) != 4:
                raise ProviderError(ProviderErrorCategory.NO_DATA, "probe history unavailable", retryable=True)
            self.breaker.record_success(provider_key)
            return {"provider": provider_key, "status": "probe_succeeded", "symbol": candidate.symbol}
        except Exception as exc:
            error_class = self.breaker.record_failure(provider_key, exc)
            return {"provider": provider_key, "status": "probe_failed", "error_class": error_class}

    @staticmethod
    def _candidate_mapping(mapping: SectorMapping, symbol: str) -> SectorMapping:
        return mapping.model_copy(update={"primary_symbol": symbol})

    def fetch_intraday_snapshot(self, mapping: SectorMapping, as_of: datetime) -> DailyBar:
        capability = self.capabilities.get(mapping.sector_key)
        if capability is None or mapping.sector_key == "hang_seng_tech":
            raise ProviderError(ProviderErrorCategory.INVALID_SYMBOL, "no provider capability", retryable=False)
        candidates = capability.selectable_candidates
        if not candidates:
            self._stats["no_fallback_count"] += 1
            raise ProviderError(ProviderErrorCategory.PROVIDER_UNAVAILABLE, "no_valid_fallback", retryable=False)
        primary = candidates[0]
        last_error: Exception | None = None
        for candidate in candidates:
            provider = self.providers.get(candidate.provider)
            if provider is None:
                continue
            skip_reason = self._cycle_unavailable.get(candidate.provider)
            decision_state = "closed"
            if skip_reason is None and self.breaker:
                decision = self.breaker.decision(candidate.provider)
                decision_state = decision.state
                if not decision.allowed:
                    skip_reason = decision.reason or "primary_provider_circuit_open"
            if skip_reason:
                if candidate == primary:
                    self._stats["primary_skipped_count"] += 1
                continue
            first_provider_attempt = candidate.provider not in self._cycle_checked
            if first_provider_attempt:
                self._stats["health_probe_count"] += 1
            try:
                bar = provider.fetch_intraday_snapshot(self._candidate_mapping(mapping, candidate.symbol), as_of)
                if bar.provider_native_history_status != "complete" or len(bar.provider_native_history) != 4:
                    raise ProviderError(ProviderErrorCategory.NO_DATA, "same-provider four-close history unavailable", retryable=True)
                if any(item.provider != bar.provider or item.provider_symbol != candidate.symbol for item in bar.provider_native_history):
                    raise ProviderError(ProviderErrorCategory.MALFORMED_RESPONSE, "cross-provider or cross-symbol history rejected", retryable=False)
                if self.breaker and first_provider_attempt:
                    self.breaker.record_success(candidate.provider)
                self._cycle_checked.add(candidate.provider)
                if decision_state == "half_open" and self.breaker:
                    recovered = next(
                        (row for row in self.breaker.rows() if row["provider"] == candidate.provider),
                        None,
                    )
                    if recovered and recovered["state"] != "closed":
                        self._cycle_unavailable[candidate.provider] = "provider_recovery_pending"
                fallback_used = candidate != primary
                if fallback_used:
                    self._stats["fallback_success_count"] += 1
                lineage = ";".join(filter(None, [
                    bar.lineage,
                    f"canonical_sector={capability.display_name}",
                    f"selected_provider={candidate.provider}",
                    f"selected_symbol={candidate.symbol}",
                    f"mapping_type={candidate.mapping_type}",
                    f"candidate_priority={candidate.priority}",
                    f"primary_provider={primary.provider}",
                    f"primary_skipped_reason={self._cycle_unavailable.get(primary.provider, '')}",
                    f"fallback_used={str(fallback_used).lower()}",
                    f"spot_source={candidate.provider}:{candidate.symbol}",
                    f"history_source={candidate.provider}:{candidate.symbol}",
                    "same_provider_same_symbol=true",
                    f"current_as_of={as_of.isoformat()}",
                    "historical_dates=" + ",".join(item.trade_date.isoformat() for item in bar.provider_native_history),
                ]))
                return bar.model_copy(update={"lineage": lineage})
            except Exception as exc:
                last_error = exc
                # One endpoint-family failure suppresses fan-out for the rest of
                # this cycle, even before the persistent threshold is reached.
                self._cycle_unavailable[candidate.provider] = classify_provider_failure(exc)
                if self.breaker and first_provider_attempt:
                    self.breaker.record_failure(candidate.provider, exc)
                self._cycle_checked.add(candidate.provider)
                if candidate == primary:
                    self._stats["primary_skipped_count"] += 1
        self._stats["no_fallback_count"] += 1
        raise ProviderError(
            ProviderErrorCategory.PROVIDER_UNAVAILABLE,
            "all_providers_unavailable" if last_error else "no_valid_fallback",
            retryable=True,
        ) from last_error
