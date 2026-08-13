from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from leopard_project.security_proxy_observation import SecurityProxyObservationService
from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.web.security_proxy_viewer import OfficialBoardAvailability, SecurityProxyViewerCache, SecurityProxyViewerService
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import SecurityProxyDaily


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


def test_proxy_viewer_adds_recent_history_and_metrics_without_using_current_in_ma(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'viewer.sqlite3'}")
    with sessions() as session:
        for index in range(21):
            session.add(SecurityProxyDaily(symbol="sh515880", trading_date=date(2026, 7, 1).fromordinal(date(2026, 7, 1).toordinal() + index), close=Decimal(index + 1), fetched_at=datetime(2026, 8, 4, 14, 30), source="fixture"))
        session.commit()
        result = SecurityProxyViewerService(observation_service=StubObservationService(), enabled=True).observe(unavailable(), session=session)
    instrument = result["security_proxy"]["instruments"][0]
    assert instrument["recent_closes"] == [
        {
            "trading_date": (date(2026, 7, 1).fromordinal(date(2026, 7, 1).toordinal() + index)).isoformat(),
            "close": float(Decimal(index + 1)),
            "change_pct_from_previous_close": float((Decimal(index + 1) / Decimal(index) - 1) * 100),
        }
        for index in range(11, 21)
    ]
    assert instrument["ma5"] == 19 and instrument["ma10"] == 16.5 and instrument["ma20"] == 11.5
    # Stale/live-unavailable quotes use the last captured completed close for
    # display only; the MA itself still uses completed daily history.
    assert instrument["data_mode"] == "completed_eod"
    assert instrument["quote_status"] == "completed_eod"
    assert instrument["distance_to_ma5_pct"] == pytest.approx(10.526315789473685)


def test_proxy_trend_distance_is_fact_only_and_history_is_optional() -> None:
    payload = SecurityProxyViewerService._trend_payload(
        [type("Daily", (), {"trading_date": date(2026, 8, day), "close": Decimal(day)})() for day in range(1, 6)],
        Decimal("6"),
    )
    assert payload["ma5"] == 3 and payload["distance_to_ma5_pct"] == 100
    empty = SecurityProxyViewerService._trend_payload((), Decimal("6"))
    assert empty == {"recent_closes": [], "ma5": None, "ma10": None, "ma20": None, "distance_to_ma5_pct": None, "distance_to_ma10_pct": None, "distance_to_ma20_pct": None}


def test_stale_live_quote_falls_back_to_completed_eod_without_zero_fill(tmp_path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'viewer.sqlite3'}")
    with sessions() as session:
        session.add_all([
            SecurityProxyDaily(symbol="sh515880", trading_date=date(2026, 8, 10), close=Decimal("10"), fetched_at=datetime(2026, 8, 10, 15, 20), source="fixture"),
            SecurityProxyDaily(symbol="sh515880", trading_date=date(2026, 8, 11), close=Decimal("11"), fetched_at=datetime(2026, 8, 11, 15, 20), source="fixture"),
        ])
        session.commit()
        result = SecurityProxyViewerService(
            observation_service=StubObservationService(), enabled=True,
            now=lambda: datetime(2026, 8, 5, 18, 0),
        ).observe(unavailable(), session=session)
    item = result["security_proxy"]["instruments"][0]
    assert item["data_mode"] == "completed_eod"
    assert item["quote_status"] == "completed_eod"
    assert Decimal(item["current"]) == Decimal("11")
    assert Decimal(item["pct_change"]) == Decimal("10")
