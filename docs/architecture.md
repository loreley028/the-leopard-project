# Architecture — Phase 1B-1

```text
66-sector catalog
  ├─ HSTECH/HK → unsupported display only
  ├─ 65 CN_A collection plan
  │    ├─ MarketDataProvider adapter
  │    ├─ CN_A TradingCalendar + EOD policy
  │    ├─ complete_eod-only snapshot boundary
  │    └─ Provider lineage → reconciliation engine
  └─ transcript + V2.3 PDF rules → daily PDF summary (independent path)
```

## Complete-session boundary

`config/end_of_day_policy_v1.json` supplies timezone, market close, 16:30 safe acceptance time, minimum fields and anomaly policies. `backend/leopard_project/eod.py` accepts an injected, timezone-aware `as_of`; no system-clock dependency is required by business logic.

`TradingCalendar` is an abstraction. The checked-in CN_A calendar is deliberately incomplete and only supports controlled tests and the 2026-07-21 replay. Dates outside its declared fixture fail closed. A complete authoritative calendar Provider is required before scheduling.

Only `complete_eod` is eligible for normal EOD data. Intraday, stale, future, missing, incomplete, failed and unsupported states are blocked.

## Provider and lineage boundary

Business code continues to depend on `MarketDataProvider`. `AkshareResearchProvider` is network-disabled unless an explicit fetcher is injected. Source inspection shows that AKShare ultimately calls the same Tonghuashun `d.10jqka.com.cn` v4 board chart endpoint as `ThsPublicValidationProvider`, so the pair is `shared_upstream` and cannot prove independent availability.

## Reconciliation boundary

`config/reconciliation_policy_v1.json` contains validation thresholds. `backend/leopard_project/reconciliation.py` records source states, values, missing optional fields, numeric differences, lineage and anomaly codes. Shared upstream takes precedence over a numerical match: identical values cannot become independent dual-source success.

The checked-in 65-sector result is a metadata replay of immutable Phase 1B-0 evidence. It does not reconstruct prices from hashes and does not claim an AKShare live success.

## CI boundary

CI remains read-only and offline. It adds Phase 1B-1 policy, lineage and reconciliation validation without removing Phase 0, Phase 1A or Phase 1B-0 checks. `ci_action_runtime_upgrade_pending` is recorded for later maintenance.
