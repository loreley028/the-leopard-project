# Indicator definitions

All windows use ordered trading sessions, never calendar days. Percentage outputs are percentage points (for example, `2.5` means 2.5%). Missing history returns `None`, and the snapshot carries `data_status=insufficient_data` until 61 bars are present.

| Indicator | Definition |
|---|---|
| 1-day return | `close_t / pre_close_t - 1` |
| N-session return | `close_t / close_(t-N) - 1`; requires N+1 observations |
| MA N | Arithmetic mean of the latest N closes |
| Distance to MA | `close_t / MA_N - 1` |
| Amount change | `amount_t / amount_(t-1) - 1` |
| Amount vs N-day average | `amount_t / average(latest N amounts)` |
| Volume label | `放量` at ratio >= 1.20; `缩量` at ratio <= 0.80; otherwise `正常` |
| 20-day high/low | Maximum/minimum close across the latest 20 sessions |
| New 20-day high/low | Current close equals the corresponding 20-session extreme |
| MA20 breakout | Current close above current MA20 and previous close at/below previous MA20 |
| MA20 breakdown | Current close below current MA20 and previous close at/above previous MA20 |
| Cross-sectional rank | Competition rank (`1,2,2,4`); missing values are excluded |

The volume thresholds are function parameters and reserved environment/config values, so Phase 1 can place them in a versioned indicator configuration.

## Custom indices

The first effective observation is fixed at 1000. Subsequent levels multiply the previous level by `1 + weighted component return`. Component order is sorted before calculation, and Decimal arithmetic makes the same input deterministic.

- `CUSTOM_FOOD_BEVERAGE`: `881134` 50% + `881133` 50%.
- `CUSTOM_PV_STORAGE`: `881279` 50% + `885921` 50%.
- `CUSTOM_OIL_PETROCHEM`: `881180` 50% + `881107` 50%.
- `CUSTOM_HOTEL_CATERING`: equal-weight available constituents of `881161`; unavailable/delisted members are excluded with re-normalization and an anomaly. If constituents cannot be obtained, `881160` may be used only with `data_status=proxy`.
