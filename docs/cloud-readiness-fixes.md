# Phase 2A-0 cloud-readiness patch

This patch is intentionally limited to the private Phase 2A-0 runtime. It does
not approve a production Provider, enable public access, or change the three
market-data lanes.

## Controlled CN A calendar

Runtime scheduling reads `config/cn_a_trading_calendar_rules_2026.json`. The
rule set covers 2026-01-01 through 2026-12-31 and combines weekends, official
exchange closure ranges, and explicit open/closed overrides. A missing source
or a date outside that interval fails closed without being described as a
holiday. Admin runtime status exposes the source, coverage boundaries, current
status, and the 30-day maintenance warning.

Run `PYTHONPATH=backend python3.12 scripts/validate_trading_calendar.py` after
each annual update. A new annual version must be prepared after the exchange
publishes the next schedule, and temporary exchange notices must be represented
as explicit overrides. The validator deliberately fails when the current date
or any of the next 30 days is not controlled.

## Scheduler and EOD resilience

Intraday sessions now own a heartbeat-backed lease. Startup preserves audit
records while converting expired `running` rows to `interrupted`; a live lease
prevents a second scheduler from registering. Graceful shutdown records a
terminal state.

EOD publication gaps are classified as `pending_publication`. Retries use the
versioned policy in `config/eod_retry_policy_v1.json`, request only missing
sectors, and stop after the configured attempt budget. Provider network calls
finish before a short coordinated SQLite write phase begins. HSTECH remains
outside the dynamically derived supported-market-path denominator.

SQLite file databases initialize idempotently with WAL, `synchronous=NORMAL`,
and a 10-second busy timeout. Process-local bulk writes are serialized; the
bounded lock helper retries only `database is locked` errors with exponential
backoff and propagates all other database failures.

## Hotel and catering market-path split

The report topic `hotel_catering` remains one immutable PDF, review, path-ledger,
confirmation, and frozen-snapshot key. It is no longer an active market path.
The market registry now relates that report topic to two research paths:
`hotel` and `catering`. This adds one net supported market path, so runtime scope
is derived as 66 supported paths plus unsupported HSTECH rather than from a
hard-coded denominator.

Aliyun isolated-Docker evidence identifies `881160` as **旅游及酒店**, not
酒店餐饮. It is admitted only as the explicit `hotel` proxy and must be shown as
“酒店（旅游及酒店代理口径）”. No independent, semantically valid catering
board was found in the controlled THS industry and concept directories;
`catering` therefore remains `unverified` with no runnable candidate. No hotel
and catering composite or stock basket is synthesized.

## Proxy and frontend security

The hotel path uses the explicit `881160` proxy. Intraday and historical lineage
include `canonical_market_path=hotel`, proxy mapping type, Provider identity,
the official 旅游及酒店 name, semantic difference, symbol, timestamp, and
same-Provider/same-symbol status. Catering fails closed until an independent
legal candidate is approved.

The current npm advisory set has no non-vulnerable stable React Router 7.x
release: older 7.x versions retain prior high-severity findings while 7.12+
is affected by the newer RSC-mode advisory. The app does not use RSC, but the
strict acceptance gate requires zero production high findings. The external
router dependency is therefore removed and replaced with the small internal
client-side router needed by this fixed route table. Navigation, authorization,
route parameters, query parameters, link state, accessibility, and production
build remain covered by frontend tests. Remaining audit findings are confined
to ESLint/minimatch development tooling and require a separate major-version
toolchain review.

## Deferred live acceptance

After the public Provider recovers, run the following command during an open
A-share session:

```bash
LEOPARD_RUN_LIVE=1 PYTHONPATH=backend python3.12 scripts/validate_cloud_readiness_live.py
```

The command uses an isolated temporary `real_local` database and exits non-zero
unless one normal Scheduler cycle produces every dynamically registered
supported path as fresh with same-source intraday MA5,
intraday MA5 values, zero HSTECH requests, and zero Provider request increase
across ten Viewer reads. It does not retain raw responses or touch reports,
frozen snapshots, or the normal runtime database.
