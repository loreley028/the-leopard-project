"""Public Sina daily-bar provider for the fixed Market Core universe.

This adapter is deliberately narrow: it accepts complete ``sh`` / ``sz``
symbols only, uses one ordinary public request per symbol, and returns
unadjusted daily bars.  It is not a sector provider, a scheduler input, or a
production-primary designation.  Consumers must opt in explicitly.
"""
from __future__ import annotations

import json
import re
import socket
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import CONFIG_DIR
from ..trading_calendar import CalendarStatus, evaluate_cn_a_day


CONFIG_PATH = CONFIG_DIR / "sina_public_daily_provider_v1.json"
Transport = Callable[[str, float], bytes]


class SinaDailyError(RuntimeError):
    """A classified, fail-closed Sina daily-bar error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SinaDailyBar:
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None


def load_sina_daily_config(path: Path = CONFIG_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ipv4_transport(url: str, timeout: float) -> bytes:
    """Use the provider's ordinary IPv4 route; ECS has no usable IPv6 path."""

    original = socket.getaddrinfo
    try:
        socket.getaddrinfo = lambda host, port, family=0, type=0, proto=0, flags=0: original(
            host, port, socket.AF_INET, type, proto, flags
        )
        with urlopen(Request(url), timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        raise SinaDailyError(f"http_{exc.code}") from exc
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise SinaDailyError("timeout") from exc
        raise SinaDailyError("transport_unavailable") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise SinaDailyError("timeout") from exc
    finally:
        socket.getaddrinfo = original


def _decimal(value: object, *, positive: bool = False, non_negative: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SinaDailyError("malformed_bar") from exc
    if not result.is_finite() or (positive and result <= 0) or (non_negative and result < 0):
        raise SinaDailyError("malformed_bar")
    return result


class SinaPublicDailyMarketProvider:
    """Explicit, opt-in unadjusted daily history reader."""

    provider_key = "sina_public_daily_http"
    # This role is intentionally narrower than production_primary: the route
    # is validated only for the fixed Market Core daily-history universe.
    provider_role = "validated_historical_provider"
    price_adjustment_policy = "unadjusted_daily_bar"

    def __init__(self, *, transport: Transport | None = None, config: dict[str, object] | None = None) -> None:
        self.config = config or load_sina_daily_config()
        self.transport = transport or _ipv4_transport
        self.timeout = float(self.config["timeout_seconds"])
        self.maximum_days = int(self.config["maximum_days"])
        self.pattern = re.compile(str(self.config["supported_symbol_pattern"]))

    def fetch_history(self, symbol: str, *, days: int, allow_network: bool = False) -> tuple[SinaDailyBar, ...]:
        if not allow_network:
            raise PermissionError("explicit historical Provider enablement is required")
        if not self.pattern.fullmatch(symbol):
            raise ValueError("only complete shXXXXXX and szXXXXXX symbols are supported")
        if not 20 <= days <= self.maximum_days:
            raise ValueError(f"days must be between 20 and {self.maximum_days}")
        url = str(self.config["endpoint_template"]).format(symbol=symbol, days=days)
        payload = self.transport(url, self.timeout)
        try:
            rows = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SinaDailyError("decode_error") from exc
        if not isinstance(rows, list):
            raise SinaDailyError("malformed_payload")
        by_day: dict[date, SinaDailyBar] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise SinaDailyError("malformed_bar")
            try:
                trading_date = date.fromisoformat(str(row["day"]))
                open_ = _decimal(row["open"], positive=True)
                high = _decimal(row["high"], positive=True)
                low = _decimal(row["low"], positive=True)
                close = _decimal(row["close"], positive=True)
                volume = _decimal(row["volume"], non_negative=True)
            except (KeyError, ValueError, SinaDailyError) as exc:
                raise SinaDailyError("malformed_bar") from exc
            calendar = evaluate_cn_a_day(trading_date)
            if (
                trading_date.weekday() >= 5
                or calendar.status != CalendarStatus.TRADING_DAY
                or not (low <= open_ <= high and low <= close <= high)
            ):
                raise SinaDailyError("invalid_daily_structure")
            if trading_date in by_day:
                raise SinaDailyError("duplicate_trading_date")
            by_day[trading_date] = SinaDailyBar(trading_date, open_, high, low, close, volume)
        return tuple(by_day[day] for day in sorted(by_day))
