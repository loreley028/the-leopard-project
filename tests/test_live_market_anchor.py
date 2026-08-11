from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider, load_tencent_quote_config
from leopard_project.web.live_market_anchor import (
    LiveMarketAnchorCache,
    LiveShanghaiMarketAnchorService,
    structure_leopard_defense_line,
)


NOW = datetime.fromisoformat("2026-08-11T13:42:00+08:00")


def _record(*, current: str = "3856.47", pre_close: str = "3842.12", timestamp: str = "20260811134200") -> bytes:
    values = [""] * 88
    values[1], values[2], values[3], values[4] = "上证指数", "000001", current, pre_close
    values[30] = timestamp
    values[31] = str(float(current) - float(pre_close))
    values[32] = str(round((float(current) / float(pre_close) - 1) * 100, 2))
    values[35] = f"{current}/1/1"
    return f'v_sh000001="{"~".join(values)}";'.encode("gbk")


def _provider(payload: bytes, calls: list[str]) -> TencentStandardSecurityQuoteProvider:
    return TencentStandardSecurityQuoteProvider(
        transport=lambda url, _timeout: calls.append(url) or payload,
        config=deepcopy(load_tencent_quote_config()),
        now=lambda: NOW,
    )


def _service(payload: bytes, calls: list[str], *, cache: LiveMarketAnchorCache | None = None) -> LiveShanghaiMarketAnchorService:
    return LiveShanghaiMarketAnchorService(provider=_provider(payload, calls), enabled=True, cache=cache, now=lambda: NOW)


def test_shanghai_composite_reuses_complete_tencent_security_contract() -> None:
    calls: list[str] = []
    result = _service(_record(), calls).observe(market_path="", core_view="3844点以下继续防守；即使站上，也必须通过时间、市场宽度和量能验证。")
    assert calls == ["http://qt.gtimg.cn/q=sh000001"]
    assert result["quote_status"] == "available"
    assert result["symbol"] == "sh000001" and result["index_name"] == "上证指数"
    assert result["current"] == 3856.47 and result["pre_close"] == 3842.12 and result["pct_change"] == 0.37
    assert result["quote_datetime"] == "2026-08-11T13:42:00+08:00"


def test_market_path_precedes_core_view_and_core_view_is_safe_fallback() -> None:
    market = structure_leopard_defense_line("攻防线3900点；站上3900点观察宽度。", "3844点以下继续防守")
    fallback = structure_leopard_defense_line("无明确结构化攻防点。", "3844点以下继续防守；即使站上，也必须通过时间、市场宽度和量能验证。")
    assert (market.value, market.source) == (3900, "market_path")
    assert fallback.value == 3844 and fallback.source == "core_view"
    assert fallback.break_below_condition == "3844点以下继续防守"
    assert fallback.validation_conditions == "即使站上，也必须通过时间、市场宽度和量能验证"


def test_ambiguous_numbers_are_not_guessed() -> None:
    result = structure_leopard_defense_line("攻防线3844点，另一关键点3900点。", "")
    assert result.value is None and result.source is None


def test_distance_and_objective_position_are_calculated_in_read_model() -> None:
    calls: list[str] = []
    above = _service(_record(), calls).observe(market_path="3844点以下继续防守", core_view="")
    below = _service(_record(current="3830.00", pre_close="3842.12"), calls).observe(market_path="3844点以下继续防守", core_view="")
    at = _service(_record(current="3844.00", pre_close="3842.12"), calls).observe(market_path="3844点以下继续防守", core_view="")
    assert above["distance_points"] == 12.47 and round(above["distance_pct"], 2) == 0.32 and above["defense_position"] == "above_defense_line"
    assert below["defense_position"] == "below_defense_line"
    assert at["distance_points"] == 0 and at["distance_pct"] == 0 and at["defense_position"] == "at_defense_line"


def test_anchor_cache_single_flight_window_and_graceful_provider_failure() -> None:
    now = [0.0]
    calls: list[str] = []
    service = _service(_record(), calls, cache=LiveMarketAnchorCache(clock=lambda: now[0]))
    first = service.observe(market_path="3844点以下继续防守", core_view="")
    second = service.observe(market_path="3844点以下继续防守", core_view="")
    assert first["cache_hit"] is False and second["cache_hit"] is True and len(calls) == 1
    unavailable = LiveShanghaiMarketAnchorService(provider=_provider(b"", []), enabled=True, now=lambda: NOW).observe(market_path="3844点以下继续防守", core_view="")
    assert unavailable["quote_status"] == "unavailable" and unavailable["current"] is None
    assert unavailable["defense_line_value"] == 3844 and unavailable["distance_points"] is None
