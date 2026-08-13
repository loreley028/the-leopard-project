"""Read-only current-market context for an enhanced report overview.

The report remains the source of the Leopard view and defense line.  This
module only adds a clearly labelled *current* Shanghai Composite quote so a
reader can see where the market is relative to that report's line.  It never
persists upstream data and it is intentionally separate from report snapshots.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from leopard_project.providers.tencent_standard_quote import TencentQuoteError, TencentStandardSecurityQuoteProvider


SHANGHAI_COMPOSITE_SYMBOL = "sh000001"
SHANGHAI_COMPOSITE_NAME = "上证指数"

_NUMBER = r"(?<!\d)(\d{3,5}(?:\.\d+)?)"
_DEFENSE_PATTERNS = (
    re.compile(r"(?:攻防(?:线|点)?|关键(?:点位|位置)?|防守(?:线|点)?)[^\d]{0,8}" + _NUMBER + r"\s*点?"),
    re.compile(_NUMBER + r"\s*点?\s*(?:以下|上方|附近|上下|作为|为|是|继续防守|攻防)"),
    re.compile(r"(?:站上|跌破|失守|收复|突破)\s*" + _NUMBER + r"\s*点?"),
)


@dataclass(frozen=True)
class DefenseLine:
    value: Decimal | None
    source: str | None
    stand_above_condition: str | None
    break_below_condition: str | None
    validation_conditions: str | None

    def payload(self) -> dict:
        return {
            "defense_line_value": float(self.value) if self.value is not None else None,
            "defense_line_source": self.source,
            "stand_above_condition": self.stand_above_condition,
            "break_below_condition": self.break_below_condition,
            "validation_conditions": self.validation_conditions,
        }


def _sentences(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in re.split(r"[。；;\n]+", value or "") if item.strip())


def _candidate_values(value: str) -> set[Decimal]:
    candidates: set[Decimal] = set()
    for pattern in _DEFENSE_PATTERNS:
        for match in pattern.finditer(value or ""):
            candidates.add(Decimal(match.group(1)))
    return candidates


def _structured_defense_line(value: str, source: str) -> DefenseLine | None:
    candidates = _candidate_values(value)
    # A number is accepted only when report wording marks it as a level and it
    # is unique.  This deliberately refuses to guess among several figures.
    if len(candidates) != 1:
        return None
    sentences = _sentences(value)
    return DefenseLine(
        value=next(iter(candidates)),
        source=source,
        stand_above_condition=next((item for item in sentences if re.search(r"站上|收复|突破", item)), None),
        break_below_condition=next((item for item in sentences if re.search(r"跌破|失守|以下|下方", item)), None),
        validation_conditions=next((item for item in sentences if re.search(r"时间|宽度|量能|成交量|资金|持续", item)), None),
    )


def structure_leopard_defense_line(
    market_path: str,
    core_view: str,
    parsed_primary: object | None = None,
) -> DefenseLine:
    """Prefer a parser-verified primary line; safely fall back to prose."""
    try:
        primary = Decimal(str(parsed_primary)) if parsed_primary is not None else None
    except Exception:
        primary = None
    if primary is not None and primary.is_finite() and primary > 0:
        sentences = _sentences(f"{market_path}。{core_view}")
        return DefenseLine(
            primary,
            "parsed_defense_line",
            next((item for item in sentences if re.search(r"站上|收复|突破", item)), None),
            next((item for item in sentences if re.search(r"跌破|失守|以下|下方", item)), None),
            next((item for item in sentences if re.search(r"时间|宽度|量能|成交量|资金|持续", item)), None),
        )
    return (
        _structured_defense_line(market_path, "market_path")
        or _structured_defense_line(core_view, "core_view")
        or DefenseLine(None, None, None, None, None)
    )


class LiveMarketAnchorCache:
    """Small per-process cache with one in-flight request for the single index."""

    def __init__(self, *, ttl_seconds: int = 300, error_ttl_seconds: int = 30, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_seconds, self.error_ttl_seconds, self.clock = ttl_seconds, error_ttl_seconds, clock
        self._cached: tuple[float, dict] | None = None
        self._lock = threading.Lock()

    def get_or_fetch(self, fetcher: Callable[[], dict]) -> tuple[dict, bool]:
        now = self.clock()
        if self._cached and self._cached[0] > now:
            return self._cached[1], True
        with self._lock:
            now = self.clock()
            if self._cached and self._cached[0] > now:
                return self._cached[1], True
            value = fetcher()
            ttl = self.ttl_seconds if value["quote_status"] == "available" else self.error_ttl_seconds
            self._cached = (now + ttl, value)
            return value, False


class LiveShanghaiMarketAnchorService:
    """Fetch exactly one current Tencent index quote when explicitly enabled."""

    def __init__(
        self,
        *,
        provider: TencentStandardSecurityQuoteProvider,
        enabled: bool = False,
        cache: LiveMarketAnchorCache | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.provider, self.enabled, self.cache, self.now = provider, enabled, cache or LiveMarketAnchorCache(), now

    @staticmethod
    def _unavailable(error_code: str) -> dict:
        return {
            "market_context": "live_market_anchor",
            "quote_status": "unavailable",
            "symbol": SHANGHAI_COMPOSITE_SYMBOL,
            "index_name": SHANGHAI_COMPOSITE_NAME,
            "current": None,
            "pre_close": None,
            "change": None,
            "pct_change": None,
            "quote_datetime": None,
            "provider": TencentStandardSecurityQuoteProvider.provider_key,
            "provider_role": TencentStandardSecurityQuoteProvider.provider_role,
            "error_code": error_code,
        }

    def _fetch_quote(self) -> dict:
        if not self.enabled:
            return self._unavailable("live_market_anchor_disabled")
        try:
            batch = self.provider.fetch_batch((SHANGHAI_COMPOSITE_SYMBOL,), allow_network=True)
        except (TencentQuoteError, PermissionError):
            return self._unavailable("provider_unavailable")
        except Exception:
            # The report endpoint must stay readable even if an upstream
            # transport has an unexpected failure.
            return self._unavailable("provider_unavailable")
        if not batch.quotes:
            failure = batch.failures.get(SHANGHAI_COMPOSITE_SYMBOL)
            return self._unavailable(failure.value if failure is not None else "provider_unavailable")
        quote = batch.quotes[0]
        return {
            "market_context": "live_market_anchor",
            "quote_status": "available",
            "symbol": SHANGHAI_COMPOSITE_SYMBOL,
            "index_name": quote.name or SHANGHAI_COMPOSITE_NAME,
            "current": float(quote.current),
            "pre_close": float(quote.pre_close),
            "change": float(quote.change),
            "pct_change": float(quote.pct_change),
            # This is always Tencent's quote time, never the cache time.
            "quote_datetime": quote.quote_datetime.isoformat(),
            "provider": self.provider.provider_key,
            "provider_role": self.provider.provider_role,
            "error_code": None,
        }

    @staticmethod
    def _position_payload(quote: dict, defense: DefenseLine) -> dict:
        result = defense.payload()
        result.update({"distance_points": None, "distance_pct": None, "defense_position": None})
        if quote["quote_status"] != "available" or defense.value is None:
            return result
        current = Decimal(str(quote["current"]))
        distance = current - defense.value
        result["distance_points"] = float(distance)
        result["distance_pct"] = float((current / defense.value - Decimal("1")) * Decimal("100"))
        result["defense_position"] = (
            "above_defense_line" if distance > 0 else "below_defense_line" if distance < 0 else "at_defense_line"
        )
        return result

    def enrich_with_defense(
        self,
        quote: dict,
        *,
        market_path: str,
        core_view: str,
        parsed_primary: object | None = None,
    ) -> dict:
        """Attach report interpretation to already-read objective market facts.

        This deliberately does not fetch another quote.  A report defense line is
        interpretation metadata; the index quote remains an independent market
        fact and can be read without a report.
        """
        defense = structure_leopard_defense_line(market_path, core_view, parsed_primary)
        return {
            **quote,
            **self._position_payload(quote, defense),
            "market_context_note": "当前市场辅助：实时上证指数用于对照本报告攻防线，不代表报告日期的历史指数。",
        }

    def defense_payload(
        self,
        *,
        market_path: str,
        core_view: str,
        parsed_primary: object | None = None,
    ) -> dict:
        """Return report interpretation only, without reading a market quote."""
        return self.enrich_with_defense(
            self._unavailable("not_requested"),
            market_path=market_path,
            core_view=core_view,
            parsed_primary=parsed_primary,
        )

    def observe(self, *, market_path: str, core_view: str, parsed_primary: object | None = None) -> dict:
        quote, cache_hit = self.cache.get_or_fetch(self._fetch_quote)
        return {
            **self.enrich_with_defense(
                quote,
                market_path=market_path,
                core_view=core_view,
                parsed_primary=parsed_primary,
            ),
            "cache_hit": cache_hit,
        }
