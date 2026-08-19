from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from starlette.testclient import TestClient
from sqlalchemy import text

from leopard_project.providers.tencent_standard_quote import StandardSecurityQuote, TencentQuoteBatch
from leopard_project.live_market_anchor_daily import capture_live_market_anchor_daily
from leopard_project.security_proxy_daily import capture_fixed_security_proxy_daily, fixed_proxy_symbols
from leopard_project.security_proxy_observation import SecurityProxyObservationService
from leopard_project.broad_market_anchors import load_broad_market_anchors
from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.live_market_anchor import LiveShanghaiMarketAnchorService
from leopard_project.web.market_core import MarketCoreReadService
from leopard_project.web.market_date_axis import market_core_completed_dates
from leopard_project.web.market_session import cn_a_session_state
from leopard_project.web.models import LiveMarketAnchorDaily, SecurityProxyDaily


NOW = datetime(2026, 8, 13, 6, 0, tzinfo=timezone.utc)


class StubProvider:
    provider_key = "tencent_standard_security_quote"
    provider_role = "diagnostic_provider"
    max_batch_size = 20

    def __init__(self, quote_datetime: datetime = NOW.astimezone(timezone(timedelta(hours=8)))) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.quote_datetime = quote_datetime

    def fetch_batch(self, symbols, *, allow_network=False):
        requested = tuple(symbols)
        self.calls.append(requested)
        quotes = tuple(StandardSecurityQuote(
            requested_symbol=symbol, name=f"名称{symbol}", symbol=symbol[2:],
            current=Decimal("10.20"), pre_close=Decimal("10.00"),
            quote_datetime=self.quote_datetime, change=Decimal("0.20"), pct_change=Decimal("2.00"),
            response_field_count=88, payload_sha256="a" * 64,
        ) for symbol in requested)
        return TencentQuoteBatch(quotes, {}, 1)


def _settings(tmp_path) -> WebSettings:
    return WebSettings(
        database_url=f"sqlite:///{tmp_path / 'zero-report.sqlite3'}", upload_dir=tmp_path / "uploads",
        session_secret="market-core-test-session-secret-is-long-enough", admin_username="admin", admin_password="admin-password",
        viewer_username="viewer", viewer_password="viewer-password",
        security_proxy_viewer_enabled=True, live_market_anchor_enabled=True,
    )


def _anchor(provider: StubProvider) -> LiveShanghaiMarketAnchorService:
    return LiveShanghaiMarketAnchorService(provider=provider, enabled=True, now=lambda: NOW)


def _seed_completed(session, count: int = 1) -> None:
    for offset in range(count):
        day = date(2026, 7, 20) + timedelta(days=offset)
        session.add(LiveMarketAnchorDaily(
            symbol="sh000001", trading_date=day, close=Decimal(3900 + offset), pre_close=Decimal(3899 + offset), pct_change=Decimal("0.03"),
            high=None, low=None, quote_datetime=NOW, fetched_at=NOW, source="tencent_standard_security_quote",
        ))
        session.add(SecurityProxyDaily(
            symbol="sh515880", trading_date=day, close=Decimal(10 + offset),
            quote_datetime=NOW, fetched_at=NOW, source="tencent_standard_security_quote",
        ))
    session.commit()


def test_market_core_is_report_independent_and_reports_actual_history_coverage(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    with sessions() as session:
        _seed_completed(session)
        assert session.execute(text("SELECT count(*) FROM reports")).scalar_one() == 0
        service = MarketCoreReadService(provider=StubProvider(), live_anchor=_anchor(StubProvider()), enabled=False, now=lambda: NOW)
        shanghai = service.shanghai(session)
        proxies = service.proxies(session, proxy_set="cpo")
    assert shanghai["coverage"] == {"available_days": 1, "first_date": "2026-07-20", "latest_date": "2026-07-20", "missing_dates": []}
    assert shanghai["indicators"]["ma5"] is None and shanghai["history"][0]["trading_date"] == "2026-07-20"
    etf = proxies["groups"][0]["instruments"][0]
    assert etf["coverage"]["available_days"] == 1 and etf["indicators"]["ma20"] is None
    assert all("report" not in key for key in shanghai) and all("report" not in key for key in proxies)


def test_broad_market_dates_from_market_core_without_report_rows(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    with sessions() as session:
        _seed_completed(session, 5)
        assert session.execute(text("SELECT count(*) FROM reports")).scalar_one() == 0
        service = MarketCoreReadService(provider=StubProvider(), live_anchor=_anchor(StubProvider()), enabled=False, now=lambda: NOW)
        broad = service.broad_market(session)
        axis = market_core_completed_dates(session)
    assert broad["date_axis_kind"] == "market_trading_day"
    assert broad["trading_date_axis"] == [day.isoformat() for day in axis[-10:]]
    assert broad["trading_date_axis"][-1] == "2026-07-24"


def test_market_core_uses_fixed_server_side_cpo_symbols_and_batches_at_twenty(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    provider = StubProvider()
    with sessions() as session:
        _seed_completed(session, 5)
        service = MarketCoreReadService(provider=provider, live_anchor=_anchor(provider), enabled=True, now=lambda: NOW)
        result = service.proxies(session, proxy_set="cpo")
        cached = service.proxies(session, proxy_set="cpo")
    assert provider.calls == [("sh515880", "sz300308", "sz300502", "sz300394")]
    assert result["provider_request_count"] == 1 and cached["cache_hit"] is True and cached["provider_request_count"] == 0
    assert [item["symbol"] for item in result["groups"][0]["instruments"]] == ["sh515880", "sz300308", "sz300502", "sz300394"]
    assert all(item["live"]["status"] == "available" for item in result["groups"][0]["instruments"])


def test_market_core_keeps_same_day_lunch_quotes_visible_without_relaxing_continuous_freshness(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    lunch = datetime(2026, 8, 18, 4, 30, tzinfo=timezone.utc)  # 12:30 Asia/Shanghai
    quote_time = datetime(2026, 8, 18, 11, 30, tzinfo=timezone(timedelta(hours=8)))
    provider = StubProvider(quote_time)
    anchor = LiveShanghaiMarketAnchorService(provider=provider, enabled=True, now=lambda: lunch)
    with sessions() as session:
        _seed_completed(session, 5)
        service = MarketCoreReadService(provider=provider, live_anchor=anchor, enabled=True, now=lambda: lunch)
        shanghai = service.shanghai(session)
        cpo = service.proxies(session, proxy_set="cpo")
    assert shanghai["live"]["status"] == "available"
    assert shanghai["live"]["freshness"] == "session_latest"
    assert shanghai["live"]["display_mode"] == "same_day_session_latest"
    assert shanghai["live"]["session_state"] == "lunch_break"
    assert shanghai["live"]["current"] == 10.2
    assert all(item["live"]["display_mode"] == "same_day_session_latest" for item in cpo["groups"][0]["instruments"])


def test_market_core_keeps_same_day_after_close_quotes_visible_but_refuses_old_or_continuous_stale_quotes(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    quote_time = datetime(2026, 8, 18, 11, 30, tzinfo=timezone(timedelta(hours=8)))
    after_close = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)  # 16:00 Asia/Shanghai
    after_provider = StubProvider(quote_time)
    after_anchor = LiveShanghaiMarketAnchorService(provider=after_provider, enabled=True, now=lambda: after_close)
    with sessions() as session:
        _seed_completed(session, 5)
        after_service = MarketCoreReadService(provider=after_provider, live_anchor=after_anchor, enabled=True, now=lambda: after_close)
        after_shanghai = after_service.shanghai(session)
        broad = after_service.broad_market(session)
    assert after_shanghai["live"]["status"] == "available"
    assert after_shanghai["live"]["session_state"] == "after_close"
    assert all(anchor["live"]["status"] == "available" and anchor["live"]["freshness"] == "session_latest" for anchor in broad["anchors"])

    continuous = datetime(2026, 8, 18, 2, 30, tzinfo=timezone.utc)  # 10:30 Asia/Shanghai
    old_provider = StubProvider(datetime(2026, 8, 17, 15, 0, tzinfo=timezone(timedelta(hours=8))))
    old_anchor = LiveShanghaiMarketAnchorService(provider=old_provider, enabled=True, now=lambda: continuous)
    with sessions() as session:
        old_service = MarketCoreReadService(provider=old_provider, live_anchor=old_anchor, enabled=True, now=lambda: continuous)
        stale = old_service.shanghai(session)
    assert stale["live"]["status"] == "unavailable"
    assert stale["live"]["freshness"] == "stale"
    assert stale["live"]["error_code"] == "stale_quote"


def test_market_session_boundaries_do_not_misclassify_afternoon_as_lunch() -> None:
    assert cn_a_session_state(datetime(2026, 8, 18, 4, 29, 59, tzinfo=timezone.utc)) == "lunch_break"
    assert cn_a_session_state(datetime(2026, 8, 18, 5, 0, tzinfo=timezone.utc)) == "afternoon_trading"
    assert cn_a_session_state(datetime(2026, 8, 18, 5, 11, tzinfo=timezone.utc)) == "afternoon_trading"
    assert cn_a_session_state(datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)) == "after_close"


def test_market_current_overview_batches_shanghai_and_four_broad_anchors_once(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    provider = StubProvider()
    service = MarketCoreReadService(provider=provider, live_anchor=_anchor(provider), enabled=True, now=lambda: NOW)
    first = service.current_quotes(scope="overview")
    second = service.current_quotes(scope="overview")
    expected = ("sh000001", *(item.symbol for item in load_broad_market_anchors()))
    assert provider.calls == [expected]
    assert [item["symbol"] for item in first["quotes"]] == list(expected)
    assert first["provider_request_count"] == 1 and second["cache_hit"] is True and second["provider_request_count"] == 0


def test_market_core_ma_uses_completed_eod_only_and_requires_full_windows(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    with sessions() as session:
        _seed_completed(session, 20)
        service = MarketCoreReadService(provider=StubProvider(), live_anchor=_anchor(StubProvider()), enabled=False, now=lambda: NOW)
        result = service.proxies(session, proxy_set="cpo")
    etf = result["groups"][0]["instruments"][0]
    assert etf["history"][-1]["close"] == 29.0
    assert etf["indicators"]["ma5"] == 27.0
    assert etf["indicators"]["ma10"] == 24.5
    assert etf["indicators"]["ma20"] == 19.5
    assert etf["live"]["current"] is None
    assert etf["indicators"]["distance_to_ma5_pct"] == 7.407407407407407


def test_zero_report_fastapi_market_endpoints_are_anonymous_and_have_no_report_id(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    with sessions() as session:
        _seed_completed(session)
    app = create_app(settings, sessions)
    provider = StubProvider()
    app.state.live_market_anchor = _anchor(provider)
    app.state.market_core = MarketCoreReadService(provider=provider, live_anchor=app.state.live_market_anchor, enabled=True, now=lambda: NOW)
    with TestClient(app) as client:
        shanghai = client.get("/api/v1/market/shanghai")
        proxies = client.get("/api/v1/market/proxies/cpo")
        broad = client.get("/api/v1/market/broad")
        current = client.get("/api/v1/market/current/overview")
    assert shanghai.status_code == 200 and proxies.status_code == 200 and broad.status_code == 200 and current.status_code == 200
    assert shanghai.json()["coverage"]["available_days"] == 1
    assert len(proxies.json()["groups"][0]["instruments"]) == 4
    assert [item["symbol"] for item in broad.json()["anchors"]] == [item.symbol for item in load_broad_market_anchors()]
    assert all(item["security_code"].endswith((".SH", ".SZ")) for item in broad.json()["anchors"])
    assert [item["symbol"] for item in current.json()["quotes"]] == ["sh000001", *(item.symbol for item in load_broad_market_anchors())]


def test_zero_report_eod_collectors_plan_shanghai_and_all_fixed_proxies_without_report_gate(tmp_path) -> None:
    sessions = create_session_factory(_settings(tmp_path).database_url)
    closed = datetime(2026, 8, 12, 15, 20, tzinfo=timezone(timedelta(hours=8)))
    provider = StubProvider(closed)
    with sessions() as session:
        anchor = capture_live_market_anchor_daily(
            session, target_trading_date=date(2026, 8, 12), provider=provider, now=lambda: closed, enable_provider=True,
        )
        proxies = capture_fixed_security_proxy_daily(
            session, target_trading_date=date(2026, 8, 12), provider=provider, now=lambda: closed, enable_provider=True,
        )
        assert session.execute(text("SELECT COUNT(*) FROM reports")).scalar_one() == 0
    assert anchor.requested_count == 1 and anchor.inserted_count == 1
    assert proxies.candidate_count == 27
    assert proxies.inserted_count == 27 and proxies.provider_batch_count == 2
