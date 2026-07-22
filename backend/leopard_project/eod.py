from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from .config import CONFIG_DIR
from .models import DailyBar, Market


EOD_POLICY_PATH = CONFIG_DIR / "end_of_day_policy_v1.json"
CALENDAR_FIXTURE_PATH = CONFIG_DIR / "cn_a_trading_calendar_fixture_v1.json"


class EodStatus(StrEnum):
    COMPLETE_EOD = "complete_eod"
    INTRADAY_SNAPSHOT = "intraday_snapshot"
    STALE_SNAPSHOT = "stale_snapshot"
    FUTURE_SNAPSHOT = "future_snapshot"
    MISSING_EXPECTED_TRADE_DATE = "missing_expected_trade_date"
    INCOMPLETE_FIELDS = "incomplete_fields"
    PROVIDER_FAILED = "provider_failed"
    UNSUPPORTED = "unsupported"


class CalendarCoverageError(ValueError):
    pass


class EodPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy_version: str
    market: Market
    timezone: str
    market_close_time: str
    safe_accept_after: str
    expected_trade_date_rule: str
    future_date_policy: str
    intraday_snapshot_policy: str
    stale_snapshot_policy: str
    missing_expected_date_policy: str
    minimum_required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    provider_specific_overrides: dict[str, dict[str, str]]
    calendar_fixture: str
    production_calendar_approved: bool

    def safe_time(self, provider_name: str | None = None) -> time:
        configured = self.safe_accept_after
        if provider_name and provider_name in self.provider_specific_overrides:
            configured = self.provider_specific_overrides[provider_name].get("safe_accept_after", configured)
        return time.fromisoformat(configured)


class EodAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy_version: str
    provider_name: str
    market: Market
    requested_as_of: datetime
    expected_trade_date: date
    actual_trade_date: date | None
    status: EodStatus
    eligible_for_eod: bool
    anomaly_codes: tuple[str, ...] = ()
    missing_required_fields: tuple[str, ...] = ()
    row_count: int = 0


class TradingCalendar(ABC):
    market: Market
    timezone: ZoneInfo

    @abstractmethod
    def is_trading_day(self, day: date) -> bool: ...

    @abstractmethod
    def expected_trade_date(self, as_of: datetime, safe_accept_after: time) -> date: ...


class FixtureTradingCalendar(TradingCalendar):
    def __init__(
        self,
        *,
        trading_dates: Sequence[date],
        non_trading_dates: Sequence[date],
        timezone: str = "Asia/Shanghai",
        market: Market = Market.CN_A,
        calendar_version: str = "fixture",
    ) -> None:
        self.market = market
        self.timezone = ZoneInfo(timezone)
        self.calendar_version = calendar_version
        self._trading_dates = tuple(sorted(set(trading_dates)))
        self._non_trading_dates = frozenset(non_trading_dates)
        overlap = set(self._trading_dates) & self._non_trading_dates
        if overlap:
            raise ValueError(f"calendar dates cannot be both trading and non-trading: {sorted(overlap)}")
        if not self._trading_dates:
            raise ValueError("calendar fixture requires at least one trading date")
        self._covered_dates = frozenset(self._trading_dates) | self._non_trading_dates

    @classmethod
    def from_file(cls, path: Path = CALENDAR_FIXTURE_PATH) -> "FixtureTradingCalendar":
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["production_approved"]:
            raise ValueError("controlled fixture must not claim production approval")
        return cls(
            trading_dates=tuple(date.fromisoformat(value) for value in document["trading_dates"]),
            non_trading_dates=tuple(date.fromisoformat(value) for value in document["non_trading_dates"]),
            timezone=document["timezone"],
            market=Market(document["market"]),
            calendar_version=document["calendar_version"],
        )

    def is_trading_day(self, day: date) -> bool:
        if day not in self._covered_dates:
            raise CalendarCoverageError(f"date is outside controlled calendar fixture: {day.isoformat()}")
        return day in self._trading_dates

    def expected_trade_date(self, as_of: datetime, safe_accept_after: time) -> date:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        local = as_of.astimezone(self.timezone)
        current = local.date()
        current_is_trading = self.is_trading_day(current)
        if current_is_trading and local.timetz().replace(tzinfo=None) >= safe_accept_after:
            return current
        prior = tuple(day for day in self._trading_dates if day < current)
        if not prior:
            raise CalendarCoverageError(f"fixture has no prior trading date for {current.isoformat()}")
        return prior[-1]


def load_eod_policy(path: Path = EOD_POLICY_PATH) -> EodPolicy:
    return EodPolicy(**json.loads(path.read_text(encoding="utf-8")))


def assess_eod(
    bars: Sequence[DailyBar],
    *,
    provider_name: str,
    as_of: datetime,
    calendar: TradingCalendar,
    policy: EodPolicy | None = None,
    expected_trade_date: date | None = None,
    provider_failed: bool = False,
    unsupported: bool = False,
) -> EodAssessment:
    policy = policy or load_eod_policy()
    if policy.market != Market.CN_A or calendar.market != Market.CN_A:
        raise ValueError("Phase 1B-1 EOD gating supports only the CN_A calendar")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    local = as_of.astimezone(ZoneInfo(policy.timezone))
    expected = expected_trade_date or calendar.expected_trade_date(as_of, policy.safe_time(provider_name))

    def result(
        status: EodStatus,
        *,
        actual: date | None = None,
        anomalies: Sequence[str] = (),
        missing: Sequence[str] = (),
    ) -> EodAssessment:
        return EodAssessment(
            policy_version=policy.policy_version,
            provider_name=provider_name,
            market=Market.CN_A,
            requested_as_of=as_of,
            expected_trade_date=expected,
            actual_trade_date=actual,
            status=status,
            eligible_for_eod=status == EodStatus.COMPLETE_EOD,
            anomaly_codes=tuple(anomalies),
            missing_required_fields=tuple(missing),
            row_count=len(bars),
        )

    if unsupported:
        return result(EodStatus.UNSUPPORTED, anomalies=("product_scope_unsupported",))
    if provider_failed:
        return result(EodStatus.PROVIDER_FAILED, anomalies=("provider_request_failed",))
    if not bars:
        return result(EodStatus.MISSING_EXPECTED_TRADE_DATE, anomalies=("no_rows", "missing_expected_trade_date"))

    days = [bar.trade_date for bar in bars]
    latest = max(days)
    if days != sorted(days):
        return result(EodStatus.INCOMPLETE_FIELDS, actual=latest, anomalies=("dates_not_sorted",))
    if len(days) != len(set(days)):
        return result(EodStatus.INCOMPLETE_FIELDS, actual=latest, anomalies=("duplicate_dates",))

    missing_fields = tuple(sorted({
        field
        for field in policy.minimum_required_fields
        if any(getattr(bar, field, None) is None for bar in bars)
    }))
    if missing_fields:
        return result(
            EodStatus.INCOMPLETE_FIELDS,
            actual=latest,
            anomalies=("minimum_required_fields_missing",),
            missing=missing_fields,
        )

    before_safe = local.timetz().replace(tzinfo=None) < policy.safe_time(provider_name)
    if latest > expected:
        if latest == local.date() and before_safe and calendar.is_trading_day(local.date()):
            return result(EodStatus.INTRADAY_SNAPSHOT, actual=latest, anomalies=("current_session_before_safe_accept_after",))
        return result(EodStatus.FUTURE_SNAPSHOT, actual=latest, anomalies=("latest_date_after_expected",))
    if latest < expected:
        return result(EodStatus.STALE_SNAPSHOT, actual=latest, anomalies=("latest_date_before_expected", "missing_expected_trade_date"))
    if expected not in days:
        return result(EodStatus.MISSING_EXPECTED_TRADE_DATE, actual=latest, anomalies=("missing_expected_trade_date",))

    safe_reached_for_expected = local.date() > expected or not before_safe
    if not safe_reached_for_expected:
        return result(EodStatus.INTRADAY_SNAPSHOT, actual=latest, anomalies=("safe_accept_after_not_reached",))
    return result(EodStatus.COMPLETE_EOD, actual=latest)
