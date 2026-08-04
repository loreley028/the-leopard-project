#!/usr/bin/env python3
"""Research-only Tencent quote-contract analysis.

This module deliberately fails closed when the configured price indices have not
been uniquely established. It is not imported by the production Provider layer.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "config/research/tencent_standard_quote_contract_v1.json"
ASSIGNMENT = re.compile(r'^v_(?P<wire_symbol>[a-z0-9_]+)="(?P<payload>.*)"$')


class QuoteContractError(ValueError):
    """Raised when a response cannot safely satisfy the research contract."""


class WireRecord(NamedTuple):
    wire_symbol: str
    fields: tuple[str, ...]


def decode_gbk(payload: bytes) -> str:
    return payload.decode("gbk", errors="strict")


def split_records(text: str) -> list[WireRecord]:
    records: list[WireRecord] = []
    for statement in text.replace("\r", "").replace("\n", "").split(";"):
        statement = statement.strip()
        if not statement:
            continue
        match = ASSIGNMENT.fullmatch(statement)
        if not match:
            raise QuoteContractError("invalid_tencent_assignment")
        records.append(WireRecord(match.group("wire_symbol"), tuple(match.group("payload").split("~"))))
    if not records:
        raise QuoteContractError("empty_tencent_response")
    return records


def _decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise QuoteContractError(f"invalid_{label}") from exc
    if not parsed.is_finite():
        raise QuoteContractError(f"invalid_{label}")
    return parsed


def _required_index(contract: dict, key: str) -> int:
    value = contract.get(key)
    if not isinstance(value, int):
        raise QuoteContractError("tencent_quote_field_contract_unresolved")
    return value


def parse_full_record(
    record: WireRecord,
    contract: dict,
    *,
    expected_trade_date: str | None = None,
) -> dict:
    minimum = int(contract["expected_minimum_field_count"])
    if len(record.fields) < minimum:
        raise QuoteContractError("full_record_too_short")
    name_index = _required_index(contract, "name_index")
    symbol_index = _required_index(contract, "symbol_index")
    current_index = _required_index(contract, "current_index")
    pre_close_index = _required_index(contract, "pre_close_index")
    pct_index = _required_index(contract, "pct_change_index")
    time_index = _required_index(contract, "quote_datetime_index")
    maximum = max(name_index, symbol_index, current_index, pre_close_index, pct_index, time_index)
    if maximum >= len(record.fields):
        raise QuoteContractError("configured_index_out_of_range")

    current = _decimal(record.fields[current_index], "current")
    pre_close = _decimal(record.fields[pre_close_index], "pre_close")
    pct_change = _decimal(record.fields[pct_index], "pct_change")
    if current <= 0 or pre_close <= 0:
        raise QuoteContractError("nonpositive_price")
    calculated = (current / pre_close - Decimal("1")) * Decimal("100")
    tolerance = Decimal(str(contract["percentage_tolerance"]))
    if abs(calculated - pct_change) > tolerance:
        raise QuoteContractError("percentage_formula_mismatch")
    try:
        quote_datetime = datetime.strptime(record.fields[time_index], "%Y%m%d%H%M%S")
    except ValueError as exc:
        raise QuoteContractError("invalid_quote_datetime") from exc
    stale = expected_trade_date is not None and quote_datetime.date().isoformat() != expected_trade_date
    return {
        "name": record.fields[name_index],
        "symbol": record.fields[symbol_index],
        "current": str(current),
        "pre_close": str(pre_close),
        "pct_change": str(pct_change),
        "quote_datetime": quote_datetime.isoformat(),
        "stale": stale,
        "formula_error": str(abs(calculated - pct_change)),
    }


def compact_pct_change(record: WireRecord) -> Decimal:
    if len(record.fields) <= 5:
        raise QuoteContractError("compact_record_too_short")
    return _decimal(record.fields[5], "compact_pct_change")


def compact_and_full_agree(compact: WireRecord, parsed_full: dict, tolerance: Decimal) -> bool:
    return abs(compact_pct_change(compact) - Decimal(parsed_full["pct_change"])) <= tolerance


def infer_common_price_tuples(
    full_records: Iterable[WireRecord],
    compact_records: Iterable[WireRecord],
    *,
    tolerance: Decimal = Decimal("0.05"),
) -> set[tuple[int, int, int]]:
    """Return every common numeric tuple; callers must reject size != 1."""
    compact_by_symbol = {record.fields[2]: compact_pct_change(record) for record in compact_records}
    common: set[tuple[int, int, int]] | None = None
    for record in full_records:
        symbol = record.fields[2] if len(record.fields) > 2 else ""
        if symbol not in compact_by_symbol:
            raise QuoteContractError("compact_full_symbol_mismatch")
        candidates: set[tuple[int, int, int]] = set()
        for current_index, current_text in enumerate(record.fields):
            for pre_close_index, pre_close_text in enumerate(record.fields):
                try:
                    current = Decimal(current_text)
                    pre_close = Decimal(pre_close_text)
                except InvalidOperation:
                    continue
                if not current.is_finite() or not pre_close.is_finite() or current <= 0 or pre_close <= 0:
                    continue
                calculated = (current / pre_close - Decimal("1")) * Decimal("100")
                for pct_index, pct_text in enumerate(record.fields):
                    try:
                        pct = Decimal(pct_text)
                    except InvalidOperation:
                        continue
                    if not pct.is_finite():
                        continue
                    if abs(calculated - pct) <= tolerance and abs(compact_by_symbol[symbol] - pct) <= tolerance:
                        candidates.add((current_index, pre_close_index, pct_index))
        common = candidates if common is None else common & candidates
    return common or set()


def require_unique_tuple(candidates: set[tuple[int, int, int]]) -> tuple[int, int, int]:
    if len(candidates) != 1:
        raise QuoteContractError("tencent_quote_field_contract_ambiguous")
    return next(iter(candidates))


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract = load_contract(args.contract)
    print(json.dumps({
        "research_only": contract["research_only"],
        "production_approved": contract["production_approved"],
        "field_contract_status": contract["evidence_summary"]["field_contract_status"],
        "price_indices_resolved": all(isinstance(contract[key], int) for key in (
            "current_index", "pre_close_index", "pct_change_index"
        )),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
