from __future__ import annotations

from datetime import datetime

from leopard_project.security_proxy_observation import SecurityProxyObservationService
from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.web.security_proxy_viewer import OfficialBoardAvailability, SecurityProxyViewerCache, SecurityProxyViewerService


def available(key: str = "cpo") -> OfficialBoardAvailability:
    return OfficialBoardAvailability(key, True, True, "intraday_fresh", None, "2026-08-04T14:30:00+08:00")


def unavailable(key: str = "cpo") -> OfficialBoardAvailability:
    return OfficialBoardAvailability(key, False, False, "provider_failed", "provider_failed", None)


class StubObservationService:
    def __init__(self) -> None:
        self.registry = SecurityProxyObservationService(provider=TencentStandardSecurityQuoteProvider()).registry
        self.calls = 0

    def observe(self, keys, *, enable_provider=False):
        self.calls += 1
        return SecurityProxyObservationService(provider=TencentStandardSecurityQuoteProvider(transport=lambda _url, _timeout: b""), registry=self.registry, now=lambda: datetime(2026, 8, 4, 14, 30)).observe(keys, enable_provider=True)


def test_official_board_is_always_preferred_without_proxy_call() -> None:
    stub = StubObservationService(); service = SecurityProxyViewerService(observation_service=stub, enabled=True)
    result = service.observe(available())
    assert result["viewer_source_mode"] == "official_board" and result["security_proxy"] is None and stub.calls == 0


def test_disabled_and_no_reliable_paths_never_call_provider() -> None:
    stub = StubObservationService()
    assert SecurityProxyViewerService(observation_service=stub, enabled=False).observe(unavailable())["fallback_reason"] == "security_proxy_viewer_disabled"
    assert SecurityProxyViewerService(observation_service=stub, enabled=True).observe(unavailable("glass_substrate"))["fallback_reason"] == "no_reliable_security_proxy"
    assert stub.calls == 0


def test_official_innovative_medicine_board_never_requests_its_static_proxy_list() -> None:
    stub = StubObservationService(); service = SecurityProxyViewerService(observation_service=stub, enabled=True)
    result = service.observe(available("innovative_drug_medicine"))
    assert result["viewer_source_mode"] == "official_board" and result["security_proxy"] is None and stub.calls == 0


def test_proxy_response_has_independent_quotes_disclosure_and_no_aggregate() -> None:
    stub = StubObservationService(); result = SecurityProxyViewerService(observation_service=stub, enabled=True).observe(unavailable())
    assert result["viewer_source_mode"] == "security_proxy" and result["disclosure"]
    assert "aggregate_pct_change" not in result and "synthetic_market_return" not in result
    assert all(item["current"] is None and item["quote_status"] == "unavailable" for item in result["security_proxy"]["instruments"])


def test_cache_hit_and_short_error_ttl() -> None:
    now = [0.0]; cache = SecurityProxyViewerCache(ttl_seconds=300, error_ttl_seconds=30, clock=lambda: now[0]); calls = [0]
    def failed(): calls[0] += 1; return (type("X", (), {"status": "unavailable"})(),)
    assert cache.get_or_fetch(("x",), failed)[1] is False
    assert cache.get_or_fetch(("x",), failed)[1] is True and calls[0] == 1
    now[0] = 31; assert cache.get_or_fetch(("x",), failed)[1] is False and calls[0] == 2
