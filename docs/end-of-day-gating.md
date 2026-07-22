# End-of-day gating

## Policy

- Market: `CN_A`
- Timezone: `Asia/Shanghai`
- Market close: 15:00
- Safe acceptance: 16:30
- Configuration: `config/end_of_day_policy_v1.json`
- Calendar fixture: `config/cn_a_trading_calendar_fixture_v1.json`

The 16:30 boundary is an engineering buffer and is never hard-coded into the decision engine. Callers inject a timezone-aware `as_of` value.

Only `complete_eod` is accepted. `intraday_snapshot`, `stale_snapshot`, `future_snapshot`, `missing_expected_trade_date`, `incomplete_fields`, `provider_failed`, and `unsupported` are excluded.

## Calendar limits

The first calendar implementation is a controlled fixture, not a weekday heuristic and not a production conclusion. It explicitly represents trading and non-trading dates used by tests and replay, including a weekday holiday. Unknown dates fail closed. A full exchange calendar Provider must replace it before a scheduler is approved.

## Phase 1B-0 intraday evidence

The three records dated 2026-07-22 (`advertising`, `glass_fiber`, and `aerospace_equipment`) are evaluated at replay `as_of=2026-07-22T15:30:00+08:00`. Because the safe acceptance time had not arrived, all three become `intraday_snapshot` and `intraday_excluded`; none is accepted as a 2026-07-21 EOD record or treated as a future snapshot.
