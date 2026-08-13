# Market Core Historical Daily Provider

## Scope

Market Core history is independent of PDF reports, report snapshots, path
history, and sector-provider validation assets.  The only permitted universe is
the single Shanghai anchor (`sh000001`) plus enabled securities from
`config/security_proxy_registry_v1.json`.

## Historical contract

- Provider: `sina_public_daily_http`.
- Authentication: none.
- Source mode: one ordinary public request for each fixed symbol; no retry,
  cookies, token, Referer, special user-agent, raw-response persistence, or
  user-selectable symbols.
- Records: CN-A trading date, open, high, low, close, volume when supplied.
- Minimum accepted field: `trading_date` plus a positive `close`.
- All accepted records are unique, ascending CN-A trading dates.  Weekends,
  controlled non-trading days, invalid OHLC relationships, and duplicate dates
  fail closed.
- A same-day bar is not a completed record until 15:10 Asia/Shanghai.  Before
  then the backfill rejects a result with fewer than twenty completed dates.

## Price adjustment policy

`unadjusted_daily_bar` is used for both equities and ETFs.  It is the only
policy currently compatible with the unadjusted Tencent current quote used by
Market Lab.  The latest twenty completed dates are required for MA5/10/20, so
the UI never mixes a live quote into an MA.

The public sequence can show older split or ex-rights discontinuities (for
example earlier than the current 20-date window for `sh515880` and
`sz159995`).  This release does not silently splice, back-adjust, or forward
fill across them.  A future longer-horizon metric that crosses such an event
needs an explicit adjustment policy and validation first.

## 2026-08-12 cross-check gate

Before an import is approved, every Market Core symbol's 2026-08-12 close is
compared to the existing completed Tencent record.  Values match at the
security tick tolerance (0.005 below price 10; otherwise 0.01).  A conflict is
reported and is never overwritten by default.

## Backfill semantics

`scripts/backfill_market_history.py --days 30 --enable-provider` only imports
the fixed universe and uses the existing `live_market_anchor_daily` and
`security_proxy_daily` tables.  No schema migration, report table, or PDF data
is involved.  Existing equal values are `skip_existing_same`; different values
are `conflict` by default.  `--replace` is the only explicit opt-in path for a
preview-only correction, and must never be used against production without a
separate approval.
