from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Iterable, Mapping, Sequence

from .models import DailyBar, DataStatus, IndicatorSnapshot


HUNDRED = Decimal("100")


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def percent_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (current / previous - 1) * HUNDRED


def period_return(closes: Sequence[Decimal], sessions: int) -> Decimal | None:
    if len(closes) < sessions + 1:
        return None
    return percent_change(closes[-1], closes[-sessions - 1])


def moving_average(values: Sequence[Decimal], sessions: int) -> Decimal | None:
    if len(values) < sessions:
        return None
    return sum(values[-sessions:], Decimal("0")) / Decimal(sessions)


def distance_from_average(value: Decimal, average: Decimal | None) -> Decimal | None:
    if average in (None, Decimal("0")):
        return None
    return percent_change(value, average)


def optional_ratio(values: Sequence[Decimal | None], sessions: int) -> Decimal | None:
    window = values[-sessions:]
    if len(window) < sessions or any(value is None for value in window):
        return None
    complete = [value for value in window if value is not None]
    average = moving_average(complete, sessions)
    if average in (None, Decimal("0")):
        return None
    return complete[-1] / average


def amount_ratio(amounts: Sequence[Decimal | None], sessions: int) -> Decimal | None:
    return optional_ratio(amounts, sessions)


def classify_volume(ratio: Decimal | None, high: Decimal = Decimal("1.2"), low: Decimal = Decimal("0.8")) -> str | None:
    if ratio is None:
        return None
    if ratio >= high:
        return "放量"
    if ratio <= low:
        return "缩量"
    return "正常"


def crossed_ma20(closes: Sequence[Decimal]) -> tuple[bool | None, bool | None]:
    if len(closes) < 21:
        return None, None
    current_ma = moving_average(closes, 20)
    previous_ma = moving_average(closes[:-1], 20)
    assert current_ma is not None and previous_ma is not None
    above = closes[-1] > current_ma and closes[-2] <= previous_ma
    below = closes[-1] < current_ma and closes[-2] >= previous_ma
    return above, below


def calculate_indicators(
    bars: Sequence[DailyBar],
    *,
    volume_high: Decimal = Decimal("1.2"),
    volume_low: Decimal = Decimal("0.8"),
) -> IndicatorSnapshot:
    if not bars:
        raise ValueError("at least one bar is required")
    bars = tuple(sorted(bars, key=lambda bar: bar.trade_date))
    closes = [bar.close for bar in bars]
    amounts = [bar.amount for bar in bars]
    volumes = [bar.volume for bar in bars]
    current = bars[-1]
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    high_20d = max(closes[-20:]) if len(closes) >= 20 else None
    low_20d = min(closes[-20:]) if len(closes) >= 20 else None
    amount_ratio20 = amount_ratio(amounts, 20)
    volume_ratio5 = optional_ratio(volumes, 5)
    volume_ratio20 = optional_ratio(volumes, 20)
    crossed_above, crossed_below = crossed_ma20(closes)
    complete = len(bars) >= 120
    return IndicatorSnapshot(
        trade_date=current.trade_date,
        pct_change_1d=percent_change(current.close, current.pre_close),
        return_5d=period_return(closes, 5),
        return_10d=period_return(closes, 10),
        return_20d=period_return(closes, 20),
        return_60d=period_return(closes, 60),
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma60=ma60,
        distance_ma20_pct=distance_from_average(current.close, ma20),
        distance_ma60_pct=distance_from_average(current.close, ma60),
        amount_change_pct=percent_change(amounts[-1], amounts[-2]) if len(amounts) >= 2 and amounts[-1] is not None and amounts[-2] is not None else None,
        amount_vs_5d_avg=amount_ratio(amounts, 5),
        amount_vs_20d_avg=amount_ratio20,
        volume_vs_5d_avg=volume_ratio5,
        volume_vs_20d_avg=volume_ratio20,
        volume_label_5d=classify_volume(volume_ratio5, volume_high, volume_low),
        volume_label_20d=classify_volume(volume_ratio20, volume_high, volume_low),
        volume_label=classify_volume(volume_ratio20, volume_high, volume_low),
        high_20d=high_20d,
        low_20d=low_20d,
        new_high_20d=current.close == high_20d if high_20d is not None else None,
        new_low_20d=current.close == low_20d if low_20d is not None else None,
        crossed_above_ma20=crossed_above,
        crossed_below_ma20=crossed_below,
        data_status=DataStatus.NORMAL if complete else DataStatus.HISTORY_INSUFFICIENT,
    )


def competition_ranks(values: Mapping[str, Decimal | None], *, descending: bool = True) -> dict[str, int]:
    valid = [(key, value) for key, value in values.items() if value is not None]
    valid.sort(key=lambda item: item[1], reverse=descending)
    result: dict[str, int] = {}
    previous_value: Decimal | None = None
    previous_rank = 0
    for position, (key, value) in enumerate(valid, start=1):
        rank = previous_rank if value == previous_value else position
        result[key] = rank
        previous_value = value
        previous_rank = rank
    return result


def complete_history_ranks(
    values: Mapping[str, Decimal | None],
    history_lengths: Mapping[str, int],
    *,
    minimum_sessions: int = 120,
    descending: bool = True,
) -> dict[str, int]:
    eligible = {
        key: value for key, value in values.items()
        if history_lengths.get(key, 0) >= minimum_sessions
    }
    return competition_ranks(eligible, descending=descending)


def weighted_return(returns: Iterable[Decimal], weights: Iterable[Decimal]) -> Decimal:
    pairs = list(zip(returns, weights, strict=True))
    total_weight = sum((weight for _, weight in pairs), Decimal("0"))
    if total_weight != Decimal("1"):
        raise ValueError("component weights must sum to 1")
    return sum((value * weight for value, weight in pairs), Decimal("0"))


def equal_weight_available_return(returns: Iterable[Decimal | None]) -> Decimal | None:
    """Exclude unavailable constituents and re-normalize; return None when none are available."""
    available = tuple(value for value in returns if value is not None)
    if not available:
        return None
    return sum(available, Decimal("0")) / Decimal(len(available))


def build_weighted_index(
    component_returns: Mapping[str, Sequence[Decimal]],
    component_weights: Mapping[str, Decimal],
    *,
    baseline: Decimal = Decimal("1000"),
) -> tuple[Decimal, ...]:
    if set(component_returns) != set(component_weights):
        raise ValueError("returns and weights must contain the same component symbols")
    lengths = {len(series) for series in component_returns.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise ValueError("all return series must have the same non-zero length")
    symbols = tuple(sorted(component_returns))
    weights = tuple(component_weights[symbol] for symbol in symbols)
    if sum(weights, Decimal("0")) != Decimal("1"):
        raise ValueError("component weights must sum to 1")
    levels = [baseline]
    count = next(iter(lengths))
    for index in range(1, count):
        daily = weighted_return((component_returns[symbol][index] for symbol in symbols), weights)
        levels.append(levels[-1] * (Decimal("1") + daily))
    return tuple(levels)


def build_weighted_index_by_date(
    component_returns: Mapping[str, Mapping[date, Decimal]],
    component_weights: Mapping[str, Decimal],
    *,
    baseline: Decimal = Decimal("1000"),
) -> tuple[tuple[date, Decimal], ...]:
    """Build on the strict date intersection; a missing component is never hidden."""
    if set(component_returns) != set(component_weights):
        raise ValueError("returns and weights must contain the same component symbols")
    if not component_returns or any(not series for series in component_returns.values()):
        raise ValueError("every component must provide a non-empty return series")
    if sum(component_weights.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("component weights must sum to 1")
    common_dates = set.intersection(*(set(series) for series in component_returns.values()))
    if not common_dates:
        raise ValueError("component return series have no common dates")
    symbols = tuple(sorted(component_returns))
    levels: list[tuple[date, Decimal]] = []
    current = baseline
    for position, day in enumerate(sorted(common_dates)):
        if position:
            daily = weighted_return(
                (component_returns[symbol][day] for symbol in symbols),
                (component_weights[symbol] for symbol in symbols),
            )
            current *= Decimal("1") + daily
        levels.append((day, current))
    return tuple(levels)
