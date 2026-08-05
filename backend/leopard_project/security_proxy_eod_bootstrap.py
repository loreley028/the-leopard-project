"""Controlled, offline bootstrap imports for security-proxy EOD history.

The importer accepts only a user-supplied CSV/JSON file in a deliberately
narrow contract.  It never discovers files, reaches a market Provider, or
writes the formal application database.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from .security_proxy_eod import SHANGHAI, SecurityProxyEodError, SecurityProxyEodFileStore, SecurityProxyEodRecord, candidate_symbols, validate_capture_date


REQUIRED_COLUMNS = (
    "symbol", "trading_date", "open", "high", "low", "close", "source_name", "source_reference", "imported_at",
)
ALL_COLUMNS = (*REQUIRED_COLUMNS, "security_name", "amount_yuan", "adjustment_mode", "verified")


@dataclass(frozen=True)
class SecurityProxyEodBootstrapRow:
    symbol: str
    security_name: str | None
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    amount_yuan: Decimal | None
    source_name: str
    source_reference: str
    imported_at: datetime
    verified: bool
    adjustment_mode: str = "unadjusted"


class SecurityProxyBootstrapError(SecurityProxyEodError):
    pass


def _decimal(value: object, field: str, *, optional: bool = False) -> Decimal | None:
    if optional and value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SecurityProxyBootstrapError("invalid_number", f"{field} is not numeric") from exc
    if not result.is_finite():
        raise SecurityProxyBootstrapError("invalid_number", f"{field} is not finite")
    return result


def _datetime(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise SecurityProxyBootstrapError("invalid_imported_at", "imported_at must be ISO-8601") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise SecurityProxyBootstrapError("invalid_imported_at", "imported_at must be timezone-aware")
    return result.astimezone(SHANGHAI)


def _bool(value: object) -> bool:
    if value is True or str(value).strip().lower() in {"true", "1", "yes"}:
        return True
    if value is False or str(value).strip().lower() in {"false", "0", "no"}:
        return False
    raise SecurityProxyBootstrapError("invalid_verified", "verified must be boolean")


def bootstrap_row(raw: dict[str, object], *, today: date | None = None) -> SecurityProxyEodBootstrapRow:
    missing = [name for name in REQUIRED_COLUMNS if raw.get(name) in (None, "")]
    if missing:
        raise SecurityProxyBootstrapError("missing_required_field", f"missing required fields: {', '.join(missing)}")
    symbol = str(raw["symbol"]).lower()
    if symbol not in set(candidate_symbols()):
        raise SecurityProxyBootstrapError("symbol_not_approved", f"symbol is not in the approved candidate pool: {symbol}")
    try:
        trading_date = date.fromisoformat(str(raw["trading_date"]))
    except ValueError as exc:
        raise SecurityProxyBootstrapError("invalid_trading_date", "trading_date must be ISO-8601") from exc
    try:
        validate_capture_date(trading_date)
    except SecurityProxyEodError as exc:
        raise SecurityProxyBootstrapError(exc.code, str(exc)) from exc
    if trading_date > (today or date.today()):
        raise SecurityProxyBootstrapError("future_date", "bootstrap input cannot contain future data")
    if str(raw.get("adjustment_mode", "unadjusted")).lower() != "unadjusted":
        raise SecurityProxyBootstrapError("adjusted_price_not_allowed", "only explicitly unadjusted prices are accepted")
    open_, high, low, close = (_decimal(raw[name], name) for name in ("open", "high", "low", "close"))
    assert open_ is not None and high is not None and low is not None and close is not None
    amount = _decimal(raw.get("amount_yuan"), "amount_yuan", optional=True)
    if any(value <= 0 for value in (open_, high, low, close)) or amount is not None and amount < 0:
        raise SecurityProxyBootstrapError("invalid_ohlc", "OHLC must be positive and amount must be non-negative")
    if not (low <= open_ <= high and low <= close <= high):
        raise SecurityProxyBootstrapError("invalid_ohlc", "OHLC relationship is invalid")
    # Row-level manual attestation is intentionally not an input gate.  The
    # source metadata is user-confirmed once; every row then passes the same
    # deterministic candidate, calendar, OHLC, unit and adjustment checks.
    return SecurityProxyEodBootstrapRow(
        symbol=symbol, security_name=str(raw["security_name"]) if raw.get("security_name") else None,
        trading_date=trading_date, open=open_, high=high, low=low, close=close, amount_yuan=amount,
        source_name=str(raw["source_name"]), source_reference=str(raw["source_reference"]),
        imported_at=_datetime(raw["imported_at"]), verified=True,
    )


def load_bootstrap_rows(input_file: Path, *, today: date | None = None) -> tuple[SecurityProxyEodBootstrapRow, ...]:
    if input_file.suffix.lower() == ".csv":
        with input_file.open(encoding="utf-8", newline="") as handle:
            raw_rows = list(csv.DictReader(handle))
    elif input_file.suffix.lower() == ".json":
        raw = json.loads(input_file.read_text(encoding="utf-8"))
        raw_rows = raw["records"] if isinstance(raw, dict) else raw
        if not isinstance(raw_rows, list):
            raise SecurityProxyBootstrapError("invalid_input", "JSON input must be a record list or a document with records")
    else:
        raise SecurityProxyBootstrapError("unsupported_input", "bootstrap input must be CSV or JSON")
    rows: list[SecurityProxyEodBootstrapRow] = []
    errors: list[str] = []
    for index, raw in enumerate(raw_rows, start=2):
        try:
            if not isinstance(raw, dict):
                raise SecurityProxyBootstrapError("invalid_input", "each input row must be an object")
            rows.append(bootstrap_row(raw, today=today))
        except SecurityProxyBootstrapError as exc:
            errors.append(f"row {index}: {exc.code}")
    if errors:
        raise SecurityProxyBootstrapError("bootstrap_rejected", "; ".join(errors))
    seen = {(row.symbol, row.trading_date) for row in rows}
    if len(seen) != len(rows):
        raise SecurityProxyBootstrapError("duplicate_security_date", "input has duplicate symbol/trading_date rows")
    return tuple(sorted(rows, key=lambda row: (row.trading_date, row.symbol)))


def import_bootstrap_rows(
    rows: Iterable[SecurityProxyEodBootstrapRow], *, store: SecurityProxyEodFileStore,
    dry_run: bool = False, allow_research_overwrite: bool = False,
) -> tuple[Path, ...]:
    grouped: dict[date, list[SecurityProxyEodRecord]] = {}
    for row in rows:
        quote_datetime = datetime.combine(row.trading_date, time(15, 1), tzinfo=SHANGHAI)
        grouped.setdefault(row.trading_date, []).append(SecurityProxyEodRecord(
            symbol=row.symbol, security_name=row.security_name or row.symbol, trading_date=row.trading_date,
            open=row.open, high=row.high, low=row.low, close=row.close,
            amount_yuan=row.amount_yuan,
            quote_datetime=quote_datetime, fetched_at=row.imported_at, source="controlled_bootstrap_import",
            completeness_status="complete" if row.amount_yuan is not None else "partial_amount_missing",
            validation_errors=() if row.amount_yuan is not None else ("amount_missing",),
        ))
    if dry_run:
        return tuple(store.day_path(day) for day in sorted(grouped))
    return tuple(store.write_day(day, records, allow_research_overwrite=allow_research_overwrite) for day, records in sorted(grouped.items()))


def write_import_template(path: Path, *, trading_dates: Iterable[date]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"symbol": symbol, "security_name": "", "trading_date": day.isoformat(), "open": "", "high": "", "low": "", "close": "", "amount_yuan": "", "source_name": "", "source_reference": "", "imported_at": "", "verified": "", "adjustment_mode": "unadjusted"}
        for day in trading_dates for symbol in candidate_symbols()
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ALL_COLUMNS)
        writer.writeheader(); writer.writerows(rows)
    return path
