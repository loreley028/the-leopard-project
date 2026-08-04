from __future__ import annotations

import copy
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analyze_tencent_standard_quote_contract.py"
SPEC = importlib.util.spec_from_file_location("tencent_contract", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def contract() -> dict:
    value = MODULE.load_contract()
    value.update({"current_index": 3, "pre_close_index": 4, "pct_change_index": 5, "quote_datetime_index": 6})
    return value


def full_record(symbol: str = "510050", *, current: str = "2.01", previous: str = "2.00", pct: str = "0.50", timestamp: str = "20260804135057"):
    fields = [""] * 88
    fields[1:7] = ["示例ETF", symbol, current, previous, pct, timestamp]
    return MODULE.WireRecord(f"sh{symbol}", tuple(fields))


def compact_record(symbol: str = "510050", pct: str = "0.50"):
    return MODULE.WireRecord(f"s_sh{symbol}", ("", "示例ETF", symbol, "", "", pct, "", "", "", "", "", ""))


def test_gbk_decode() -> None:
    assert MODULE.decode_gbk("示例".encode("gbk")) == "示例"


def test_multiple_semicolon_records_and_tilde_fields() -> None:
    text = 'v_sh510050="~甲~510050";v_sz159915="~乙~159915";'
    rows = MODULE.split_records(text)
    assert [row.fields[1] for row in rows] == ["甲", "乙"]
    assert rows[0].fields[2] == "510050"


def test_full_record_minimum_88_fields() -> None:
    with pytest.raises(MODULE.QuoteContractError, match="full_record_too_short"):
        MODULE.parse_full_record(MODULE.WireRecord("sh510050", ("",) * 87), contract())


def test_name_symbol_and_quote_fields_parse() -> None:
    row = MODULE.parse_full_record(full_record(), contract(), expected_trade_date="2026-08-04")
    assert (row["name"], row["symbol"]) == ("示例ETF", "510050")
    assert (row["current"], row["pre_close"], row["pct_change"]) == ("2.01", "2.00", "0.50")
    assert row["quote_datetime"] == "2026-08-04T13:50:57"
    assert row["stale"] is False


def test_formula_cross_validation() -> None:
    assert Decimal(MODULE.parse_full_record(full_record(), contract())["formula_error"]) == 0


def test_compact_and_full_percentage_agree() -> None:
    parsed = MODULE.parse_full_record(full_record(), contract())
    assert MODULE.compact_and_full_agree(compact_record(), parsed, Decimal("0.05"))


def test_missing_configured_field_is_rejected() -> None:
    broken = copy.deepcopy(contract())
    broken["current_index"] = 100
    with pytest.raises(MODULE.QuoteContractError, match="configured_index_out_of_range"):
        MODULE.parse_full_record(full_record(), broken)


def test_unresolved_production_config_fails_closed() -> None:
    with pytest.raises(MODULE.QuoteContractError, match="field_contract_unresolved"):
        MODULE.parse_full_record(full_record(), MODULE.load_contract())


def test_illegal_numeric_value_is_rejected() -> None:
    with pytest.raises(MODULE.QuoteContractError, match="invalid_current"):
        MODULE.parse_full_record(full_record(current="not-a-number"), contract())


def test_percentage_mismatch_is_rejected() -> None:
    with pytest.raises(MODULE.QuoteContractError, match="percentage_formula_mismatch"):
        MODULE.parse_full_record(full_record(pct="9.99"), contract())


def test_stale_quote_is_marked() -> None:
    assert MODULE.parse_full_record(full_record(), contract(), expected_trade_date="2026-08-05")["stale"] is True


def test_invalid_quote_datetime_is_rejected() -> None:
    with pytest.raises(MODULE.QuoteContractError, match="invalid_quote_datetime"):
        MODULE.parse_full_record(full_record(timestamp="invalid"), contract())


def test_ambiguous_candidate_tuples_are_rejected() -> None:
    candidates = {(3, 4, 5), (78, 4, 5)}
    with pytest.raises(MODULE.QuoteContractError, match="field_contract_ambiguous"):
        MODULE.require_unique_tuple(candidates)


def test_unique_candidate_tuple_can_be_selected() -> None:
    assert MODULE.require_unique_tuple({(3, 4, 5)}) == (3, 4, 5)


def test_synthetic_inference_finds_expected_tuple() -> None:
    fields = list(full_record().fields)
    for index in range(len(fields)):
        if index not in {1, 2, 3, 4, 5, 6}:
            fields[index] = "x"
    candidates = MODULE.infer_common_price_tuples(
        [MODULE.WireRecord("sh510050", tuple(fields))], [compact_record()]
    )
    assert candidates == {(3, 4, 5)}


def test_parser_has_no_raw_response_persistence_api() -> None:
    assert not hasattr(MODULE, "save_raw_response")


def anchored_full_record(*, current: str = "1022.00", pre_close: str = "902.50", change: str = "119.50", pct: str = "13.24", p78: str = ""):
    fields = [""] * 88
    fields[1] = "示例证券"
    fields[2] = "300308"
    fields[3] = current
    fields[4] = pre_close
    fields[30] = "20260804141733"
    fields[31] = change
    fields[32] = pct
    fields[35] = f"{current}/1000/100000"
    fields[78] = p78
    return MODULE.WireRecord("sz300308", tuple(fields))


def anchored_compact_record(*, current: str = "1022.00", change: str = "119.50", pct: str = "13.24"):
    return MODULE.WireRecord("s_sz300308", ("", "示例证券", "300308", current, change, pct, "", "", "", "", "", ""))


def test_semantic_anchors_confirm_p3_p31_p32_and_p35() -> None:
    result = MODULE.validate_semantic_anchors(
        anchored_full_record(), anchored_compact_record(), minute_last_price="1022.00",
        minute_last_datetime="2026-08-04T14:18:00+08:00", expected_trade_date="2026-08-04",
    )
    assert result["confirmed"] is True
    assert all(result["checks"].values())


def test_semantic_anchor_rejects_compact_current_mismatch() -> None:
    result = MODULE.validate_semantic_anchors(
        anchored_full_record(), anchored_compact_record(current="1021.88", change="119.38", pct="13.23"),
        minute_last_price="1022.00", minute_last_datetime="2026-08-04T14:18:00+08:00",
        expected_trade_date="2026-08-04",
    )
    assert result["confirmed"] is False
    assert result["checks"]["full_p3_equals_compact_p3"] is False
    assert result["checks"]["full_p31_equals_compact_p4"] is False


def test_semantic_anchor_rejects_failed_formula_or_composite() -> None:
    with pytest.raises(MODULE.QuoteContractError, match="percentage_formula_mismatch"):
        MODULE.parse_full_record(full_record(pct="9.99"), contract())
    broken = list(anchored_full_record().fields)
    broken[35] = "999.99/1000/100000"
    result = MODULE.validate_semantic_anchors(
        MODULE.WireRecord("sz300308", tuple(broken)), anchored_compact_record(), minute_last_price="1022.00",
        minute_last_datetime="2026-08-04T14:18:00+08:00", expected_trade_date="2026-08-04",
    )
    assert result["confirmed"] is False
    assert result["checks"]["composite_p35_price"] is False


def test_p78_duplicate_does_not_create_ambiguity() -> None:
    assert MODULE.p78_observation("10.00", "10.00") == "duplicate_or_extension_price_field"


def test_p78_difference_never_overwrites_p3() -> None:
    result = MODULE.validate_semantic_anchors(
        anchored_full_record(p78="1022.10"), anchored_compact_record(), minute_last_price="1022.00",
        minute_last_datetime="2026-08-04T14:18:00+08:00", expected_trade_date="2026-08-04",
    )
    assert result["current"] == "1022.00"
    assert result["p78_observation"] == "different_not_adopted"


def test_semantic_anchor_rejects_stale_minute_date() -> None:
    result = MODULE.validate_semantic_anchors(
        anchored_full_record(), anchored_compact_record(), minute_last_price="1022.00",
        minute_last_datetime="2026-08-03T14:18:00+08:00", expected_trade_date="2026-08-04",
    )
    assert result["confirmed"] is False
    assert result["checks"]["minute_datetime_current_day"] is False


def test_unconfirmed_config_stays_nonproduction() -> None:
    value = MODULE.load_contract()
    assert value["contract_status"] == "unresolved"
    assert value["production_approved"] is False
    assert value["research_only"] is True
    assert value["current_index"] is None
    assert value["change_index"] is None


def test_proxy_research_scope_and_safety_flags() -> None:
    proxy = json.loads((ROOT / "config/research/market_path_security_proxies_v1.json").read_text(encoding="utf-8"))
    expected = {
        "cpo", "commercial_space", "computing_power_rental", "liquid_cooling",
        "glass_substrate", "ai_applications", "internet_finance", "optical_fiber_theme",
        "rare_earth", "innovative_drug_medicine", "semiconductor", "hotel",
    }
    assert proxy["research_only"] is True
    assert proxy["production_approved"] is False
    assert {row["market_path_key"] for row in proxy["paths"]} == expected
    assert all(row["preferred_source_mode"] == "official_board" for row in proxy["paths"])
    assert all(row["requires_user_review"] is True for row in proxy["paths"])
    assert all(row["production_approved"] is False for row in proxy["paths"])


def test_proxy_candidates_are_not_aggregated_and_cpo_yizhongtian_is_explicit() -> None:
    proxy = json.loads((ROOT / "config/research/market_path_security_proxies_v1.json").read_text(encoding="utf-8"))
    rows = {row["market_path_key"]: row for row in proxy["paths"]}
    assert proxy["methodology"]["aggregation_rule"].startswith("Do not calculate")
    assert [item["symbol"] for item in rows["cpo"]["leader_candidates"]] == ["300308", "300502", "300394"]
    assert all(item["market_shorthand"].startswith("易中天-") for item in rows["cpo"]["leader_candidates"])
    assert rows["glass_substrate"]["recommended_display_mode"] == "no_reliable_proxy"
    assert rows["glass_substrate"]["etf_candidates"] == []
    assert rows["glass_substrate"]["leader_candidates"] == []
