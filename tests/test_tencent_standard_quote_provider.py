from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from leopard_project.config import CONFIG_DIR
from leopard_project.providers.tencent_standard_quote import (
    TencentQuoteErrorCode,
    TencentStandardSecurityQuoteProvider,
    load_tencent_quote_config,
)


NOW = datetime.fromisoformat("2026-08-04T14:20:00+08:00")


def config() -> dict[str, object]:
    return deepcopy(load_tencent_quote_config())


def record(symbol: str, *, name: str = "示例证券", current: str = "10.02", pre_close: str = "10.00", open_: str = "10.01", high: str = "10.20", low: str = "9.90", change: str = "0.02", pct: str = "0.20", p35: str | None = None, p78: str = "777.77", timestamp: str = "20260804141930", fields: int = 88) -> str:
    values = [""] * fields
    values[1], values[2], values[3], values[4] = name, symbol[2:], current, pre_close
    if fields > 30: values[30] = timestamp
    if fields > 31: values[31] = change
    if fields > 32: values[32] = pct
    if fields > 33: values[33] = high
    if fields > 34: values[34] = low
    if fields > 35: values[35] = p35 if p35 is not None else f"{current}/1000/10000"
    if fields > 5: values[5] = open_
    if fields > 78: values[78] = p78
    return f'v_{symbol}="{"~".join(values)}";'


def payload(*items: str) -> bytes:
    return "\n".join(items).encode("gbk")


def provider(payload_value: bytes, *, config_value: dict[str, object] | None = None) -> TencentStandardSecurityQuoteProvider:
    return TencentStandardSecurityQuoteProvider(transport=lambda _url, _timeout: payload_value, config=config_value or config(), now=lambda: NOW)


def fetch(value: TencentStandardSecurityQuoteProvider, symbols: list[str]):
    return value.fetch_batch(symbols, allow_network=True)


def test_gbk_decode_and_contract_fields() -> None:
    batch = fetch(provider(payload(record("sh510300", name="沪深300ETF"))), ["sh510300"])
    quote = batch.quotes[0]
    assert quote.name == "沪深300ETF" and quote.symbol == "510300"
    assert quote.current == Decimal("10.02") and quote.pre_close == Decimal("10.00")
    assert quote.change == Decimal("0.02") and quote.pct_change == Decimal("0.20")
    assert quote.quote_datetime == datetime.fromisoformat("2026-08-04T14:19:30+08:00")


def test_multiple_records_are_split_and_one_bad_record_does_not_poison_others() -> None:
    bad = record("sz300308", fields=32)
    batch = fetch(provider(payload(record("sh510300"), bad, record("sh600111"))), ["sh510300", "sz300308", "sh600111"])
    assert [quote.requested_symbol for quote in batch.quotes] == ["sh510300", "sh600111"]
    assert batch.failures == {"sz300308": TencentQuoteErrorCode.INSUFFICIENT_FIELDS}


def test_p35_is_an_internal_price_check_and_p78_is_ignored() -> None:
    accepted = fetch(provider(payload(record("sh510300", p78="1.00"))), ["sh510300"])
    rejected = fetch(provider(payload(record("sh510300", p35="9.00/1000/10000"))), ["sh510300"])
    assert len(accepted.quotes) == 1
    assert rejected.failures == {"sh510300": TencentQuoteErrorCode.CALCULATION_INCONSISTENT}


def test_optional_eod_fields_are_normalized_without_using_p78() -> None:
    batch = fetch(provider(payload(record("sh510300", open_="10.01", high="10.20", low="9.90", p35="10.02/1000/12345678", p78="0"))), ["sh510300"])
    quote = batch.quotes[0]
    assert (quote.open, quote.high, quote.low, quote.amount_yuan) == (
        Decimal("10.01"), Decimal("10.20"), Decimal("9.90"), Decimal("12345678"),
    )


@pytest.mark.parametrize("current,pre_close,change,pct", [("10.02", "10.00", "0.02", "0.20"), ("10.021", "10.00", "0.02", "0.21")])
def test_formula_validation_allows_configured_display_tolerance(current: str, pre_close: str, change: str, pct: str) -> None:
    batch = fetch(provider(payload(record("sh510300", current=current, pre_close=pre_close, change=change, pct=pct, p35=f"{current}/1/1"))), ["sh510300"])
    assert len(batch.quotes) == 1


def test_formula_mismatch_is_classified() -> None:
    batch = fetch(provider(payload(record("sh510300", change="0.50"))), ["sh510300"])
    assert batch.failures == {"sh510300": TencentQuoteErrorCode.CALCULATION_INCONSISTENT}


def test_insufficient_empty_decode_stale_and_malformed_are_classified() -> None:
    assert fetch(provider(b""), ["sh510300"]).failures["sh510300"] == TencentQuoteErrorCode.EMPTY_REPLY
    assert fetch(provider(b"\xff"), ["sh510300"]).failures["sh510300"] == TencentQuoteErrorCode.DECODE_ERROR
    assert fetch(provider(payload(record("sh510300", timestamp="20260804130000"))), ["sh510300"]).failures["sh510300"] == TencentQuoteErrorCode.STALE_QUOTE
    assert fetch(provider(payload(record("sh510300", current="zero"))), ["sh510300"]).failures["sh510300"] == TencentQuoteErrorCode.MALFORMED_RECORD


def test_requested_symbols_are_deduplicated_and_compact_format_is_rejected() -> None:
    urls: list[str] = []
    value = payload(record("sh510300"), record("sz300308"))
    item = TencentStandardSecurityQuoteProvider(transport=lambda url, _timeout: urls.append(url) or value, config=config(), now=lambda: NOW)
    batch = item.fetch_batch(["sh510300", "sz300308", "sh510300"], allow_network=True)
    assert [quote.requested_symbol for quote in batch.quotes] == ["sh510300", "sz300308"]
    assert urls == ["http://qt.gtimg.cn/q=sh510300,sz300308"]
    with pytest.raises(ValueError, match="complete sh"):
        item.fetch_batch(["s_sh510300"], allow_network=True)


def test_batch_limit_and_no_sensitive_transport_configuration() -> None:
    document = config()
    provider_value = TencentStandardSecurityQuoteProvider(transport=lambda _url, _timeout: b"", config=document, now=lambda: NOW)
    with pytest.raises(ValueError, match="maximum"):
        provider_value.fetch_batch([f"sh{index:06d}" for index in range(21)], allow_network=True)
    serialized = json.dumps(document).lower()
    assert "cookie" not in serialized and "token" not in serialized and "referer" not in serialized


def test_provider_is_default_disabled_and_not_registered_with_scheduler_or_market_paths() -> None:
    document = config()
    assert document["enabled"] is False and document["production_approved"] is False
    assert document["scheduler_integrated"] is False and document["market_path_registry_integrated"] is False
    registry = json.loads((CONFIG_DIR / "market_path_registry_v1.json").read_text(encoding="utf-8"))
    assert "tencent_standard_security_quote" not in json.dumps(registry)
    assert document["provider_role"] != "production_primary"
    with pytest.raises(PermissionError, match="disabled"):
        provider(payload(record("sh510300"))).fetch_batch(["sh510300"])


def test_contract_indices_are_frozen_and_full_only() -> None:
    document = config()
    assert document["field_contract"] == {
        "name_index": 1, "symbol_index": 2, "current_index": 3, "pre_close_index": 4,
        "quote_datetime_index": 30, "change_index": 31, "pct_change_index": 32,
        "open_index": 5, "high_index": 33, "low_index": 34,
        "p35_amount": "third_component_is_amount_yuan_when_finite_non_negative",
        "p35_validation": "first_price_component_must_match_current_when_present", "p78_policy": "permanently_ignored",
    }
    assert "s_sh" not in Path("backend/leopard_project/providers/tencent_standard_quote.py").read_text(encoding="utf-8")
