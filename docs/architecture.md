# Architecture — Phase 1B-0

## Two independent product paths

```text
66-sector business catalog
        |
        +--> system support policy --> 65-sector A-share collection plan
        |                                  |
        |                         MarketDataProvider diagnostics
        |                                  |
        |                         normalized bars / indicators / rankings
        |
        +--> live transcript + V2.3 PDF specification --> daily PDF summary
```

The automatic market-data path and the daily live-report PDF path are deliberately independent. HSTECH is `unsupported` by the first automatic release, but a live transcript may still mention Hang Seng Tech and its content remains eligible for the PDF. Phase 1B-0 does not modify the PDF specification or generation logic.

## Support scope

`config/system_support_policy_v1.json` is the current product decision:

- catalog: 66;
- supported A-share sectors: 65;
- unsupported: HSTECH/HK only;
- collection and success-rate denominator: 65.

`backend/leopard_project/support.py` generates an immutable, ordered plan. Unsupported entries cannot create Provider symbols. Hotel catering produces an `881160` proxy task, glass substrate produces an `886111` short-history task, and the other three custom sectors retain component-based calculation tasks.

## Provider boundary

Business code depends on `MarketDataProvider`. Public THS access remains diagnostic. AKShare is research-only and Tushare remains an unbound candidate; no production role is approved. Phase 1A coverage under `data/provider-validation/` remains historical evidence. Phase 1B-0 selection artifacts live separately under `data/provider-selection/`.

## State semantics

`unsupported` is a support decision and is strictly different from `provider_failed`. Unsupported entries remain serializable for catalog display but are excluded from requests, alerts, retries, rankings, indicators, reconciliation, freshness checks, and provider success statistics.

## CI boundary

GitHub Actions runs with `contents: read`, installs project test dependencies, and executes only `pytest -m "not live"` plus versioned configuration, JSON, compilation, and credential checks. It has no cloud access, secrets, write permission, or live requests.
