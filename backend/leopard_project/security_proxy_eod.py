"""Explicit, file-backed EOD accumulation for approved security-proxy candidates."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

from .providers.tencent_standard_quote import StandardSecurityQuote, TencentStandardSecurityQuoteProvider
from .security_proxy_eod_selection import load_security_proxy_candidate_pool
from .trading_calendar import CalendarStatus, evaluate_cn_a_day


SOURCE = "tencent_standard_quote"
SHANGHAI = ZoneInfo("Asia/Shanghai")
CAPTURE_SAFE_TIME = time(15, 10)


class SecurityProxyEodError(ValueError):
    """Fail-closed EOD validation error with a machine-readable category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SecurityProxyEodRecord:
    symbol: str
    security_name: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    amount_yuan: Decimal
    quote_datetime: datetime
    fetched_at: datetime
    source: str = SOURCE
    completeness_status: str = "complete"
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SecurityProxyEodMetrics:
    symbol: str
    accumulated_trading_days: int
    latest_close: Decimal | None
    latest_amount_yuan: Decimal | None
    rolling_20d_low: Decimal | None
    rebound_pct: Decimal | None
    fastest_rebound_status: str
    turnover_slot_status: str
    market_cap_slot_status: str = "missing_verified_shares"
    etf_scale_slot_status: str = "missing_verified_aum"


@dataclass(frozen=True)
class SecurityProxyEodCaptureResult:
    records: tuple[SecurityProxyEodRecord, ...]
    failures: dict[str, str]
    request_count: int
    batch_count: int


def atomic_write_text(path: Path, content: str, *, allow_overwrite: bool = True) -> None:
    """Durably write a file without exposing a partially written final path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if allow_overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise FileExistsError(f"EOD day already exists: {path}") from exc
            temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_capture_date(trading_date: date) -> None:
    evaluation = evaluate_cn_a_day(trading_date)
    if evaluation.status == CalendarStatus.OUT_OF_RANGE:
        raise SecurityProxyEodError("calendar_date_not_covered", f"date is outside controlled calendar: {trading_date.isoformat()}")
    if evaluation.status != CalendarStatus.TRADING_DAY:
        code = "non_trading_day" if evaluation.status == CalendarStatus.CONFIRMED_NON_TRADING_DAY else "invalid_trading_date"
        raise SecurityProxyEodError(code, f"target date is not a controlled trading day: {trading_date.isoformat()}")


def candidate_symbols(*, market_path_keys: Iterable[str] | None = None) -> tuple[str, ...]:
    """Return only enabled, manually approved candidates from the versioned pool."""

    _, pools = load_security_proxy_candidate_pool()
    requested = set(market_path_keys) if market_path_keys is not None else None
    if requested is not None:
        known = {pool.market_path_key for pool in pools}
        unknown = requested - known
        if unknown:
            raise SecurityProxyEodError("invalid_market_path", f"unknown security-proxy path keys: {', '.join(sorted(unknown))}")
        pools = tuple(pool for pool in pools if pool.market_path_key in requested)
    return tuple(
        dict.fromkeys(
            candidate.symbol
            for pool in pools
            for candidate in (*pool.etf_candidates, *pool.stock_candidates)
            if candidate.enabled
        )
    )


def _shanghai(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SecurityProxyEodError("naive_quote_datetime", f"{field} must be timezone-aware")
    return value.astimezone(SHANGHAI)


def record_from_quote(quote: StandardSecurityQuote, *, trading_date: date, fetched_at: datetime) -> SecurityProxyEodRecord:
    quote_local = _shanghai(quote.quote_datetime, field="quote_datetime")
    if quote_local.date() != trading_date:
        raise SecurityProxyEodError("quote_date_mismatch", "quote date does not match target trading date")
    if quote_local.timetz().replace(tzinfo=None) < time(15):
        raise SecurityProxyEodError("market_not_closed", "quote is earlier than the EOD close boundary")
    values = (quote.open, quote.high, quote.low, quote.current, quote.amount_yuan)
    if any(value is None for value in values):
        raise SecurityProxyEodError("incomplete_eod_fields", "quote has incomplete EOD fields")
    open_, high, low, close, amount = values
    assert open_ is not None and high is not None and low is not None and close is not None and amount is not None
    if any(not value.is_finite() or value <= 0 for value in (open_, high, low, close)) or not amount.is_finite() or amount < 0:
        raise SecurityProxyEodError("invalid_eod_values", "EOD values are not finite positive prices and non-negative amount")
    if not (low <= open_ <= high and low <= close <= high):
        raise SecurityProxyEodError("invalid_ohlc", "EOD OHLC relationship is invalid")
    return SecurityProxyEodRecord(
        quote.requested_symbol,
        quote.name,
        quote_local.date(),
        open_,
        high,
        low,
        close,
        amount,
        quote_local,
        fetched_at,
        validation_errors=quote.eod_extension_errors,
    )


class SecurityProxyEodFileStore:
    def __init__(self, root: Path = Path("var/security-proxy-eod")) -> None:
        self.root = root

    def day_path(self, day: date) -> Path:
        return self.root / str(day.year) / f"{day.isoformat()}.json"

    def write_day(self, day: date, records: Sequence[SecurityProxyEodRecord], *, allow_research_overwrite: bool = False) -> Path:
        if not records:
            raise SecurityProxyEodError("empty_capture", "refusing to create an empty EOD success file")
        path = self.day_path(day)
        ordered = tuple(sorted(records, key=lambda item: item.symbol))
        if len({item.symbol for item in ordered}) != len(ordered):
            raise SecurityProxyEodError("duplicate_security_date", "duplicate security record for one EOD date")
        if any(item.trading_date != day for item in ordered):
            raise SecurityProxyEodError("invalid_trading_date", "record trading date does not match file date")
        document = {"trading_date": day.isoformat(), "source": SOURCE, "records": [_serialize(item) for item in ordered]}
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        atomic_write_text(path, content, allow_overwrite=allow_research_overwrite)
        atomic_write_text(self.root / "latest.json", content)
        return path

    def records(self) -> tuple[SecurityProxyEodRecord, ...]:
        result: list[SecurityProxyEodRecord] = []
        for path in sorted(self.root.glob("*/*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for row in document.get("records", []):
                result.append(_deserialize(row))
        return tuple(result)


class SecurityProxyEodCaptureService:
    def __init__(self, provider: TencentStandardSecurityQuoteProvider, store: SecurityProxyEodFileStore, now: Callable[[], datetime]) -> None:
        self.provider, self.store, self.now = provider, store, now

    def capture(
        self,
        trading_date: date,
        *,
        enable_provider: bool = False,
        allow_research_overwrite: bool = False,
        market_path_keys: Iterable[str] | None = None,
    ) -> SecurityProxyEodCaptureResult:
        if not enable_provider:
            raise PermissionError("explicit provider enablement is required")
        validate_capture_date(trading_date)
        now_local = _shanghai(self.now(), field="capture time")
        if now_local.date() != trading_date or now_local.timetz().replace(tzinfo=None) < CAPTURE_SAFE_TIME:
            raise SecurityProxyEodError("market_not_closed", "capture requires target-day Asia/Shanghai time at or after 15:10")
        records: list[SecurityProxyEodRecord] = []
        failures: dict[str, str] = {}
        request_count = 0
        symbols = candidate_symbols(market_path_keys=market_path_keys)
        for index in range(0, len(symbols), self.provider.max_batch_size):
            batch = self.provider.fetch_batch(symbols[index:index + self.provider.max_batch_size], allow_network=True)
            request_count += batch.request_count
            failures.update({symbol: error.value for symbol, error in batch.failures.items()})
            for quote in batch.quotes:
                try:
                    records.append(record_from_quote(quote, trading_date=trading_date, fetched_at=now_local))
                except SecurityProxyEodError as exc:
                    failures[quote.requested_symbol] = exc.code
        if not records:
            raise SecurityProxyEodError("empty_capture", "no complete EOD records were captured")
        self.store.write_day(trading_date, records, allow_research_overwrite=allow_research_overwrite)
        return SecurityProxyEodCaptureResult(tuple(records), failures, request_count, (len(symbols) + self.provider.max_batch_size - 1) // self.provider.max_batch_size)


def metrics_for(records: Iterable[SecurityProxyEodRecord], symbol: str) -> SecurityProxyEodMetrics:
    rows = sorted((row for row in records if row.symbol == symbol and row.completeness_status == "complete"), key=lambda item: item.trading_date)
    unique = {row.trading_date: row for row in rows}
    if len(unique) != len(rows):
        raise SecurityProxyEodError("duplicate_security_date", "duplicate dated EOD records cannot form a rolling metric")
    rows = [unique[key] for key in sorted(unique)]
    latest = rows[-1] if rows else None
    if len(rows) < 20:
        return SecurityProxyEodMetrics(symbol, len(rows), latest.close if latest else None, latest.amount_yuan if latest else None, None, None, "insufficient_history", "available" if latest else "missing_amount")
    rolling_low = min(row.low for row in rows[-20:])
    rebound_pct = latest.close / rolling_low - Decimal("1")
    return SecurityProxyEodMetrics(symbol, len(rows), latest.close, latest.amount_yuan, rolling_low, rebound_pct, "available", "available")


def _serialize(value: SecurityProxyEodRecord) -> dict[str, object]:
    data = asdict(value)
    return {
        key: item.isoformat() if isinstance(item, (date, datetime)) else str(item) if isinstance(item, Decimal) else list(item) if isinstance(item, tuple) else item
        for key, item in data.items()
    }


def _deserialize(row: dict[str, object]) -> SecurityProxyEodRecord:
    return SecurityProxyEodRecord(
        str(row["symbol"]), str(row["security_name"]), date.fromisoformat(str(row["trading_date"])),
        *(Decimal(str(row[key])) for key in ("open", "high", "low", "close", "amount_yuan")),
        datetime.fromisoformat(str(row["quote_datetime"])), datetime.fromisoformat(str(row["fetched_at"])),
        str(row.get("source", SOURCE)), str(row.get("completeness_status", "complete")), tuple(row.get("validation_errors", [])),
    )
