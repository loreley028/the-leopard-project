# The Leopard Project

The Leopard Project (`the-leopard-project`) is a configuration-driven, deterministic after-market sector analytics system. Phase 1B-1 adds complete-session gating, CN A-share calendar abstraction, Provider lineage and an offline dual-source reconciliation foundation. It does not enable production collection, scheduling, database writes, cloud access, or deployment.

## Current boundary

- Business catalog: 66 sectors across 8 groups.
- Automatic A-share support and daily denominator: 65.
- Hang Seng Tech (`HSTECH`, HK): `unsupported`, reason `cross_market_not_integrated`; zero collection or reconciliation requests.
- Transcript-driven daily PDF reporting remains independent.
- No `production_primary` or `production_fallback` is approved.

Phase 1B-1 classifies a current-session row before 16:30 Asia/Shanghai as `intraday_snapshot`; it cannot enter normal EOD data or reconciliation. The controlled calendar is a versioned fixture for tests and replay, not a production exchange calendar.

## Provider result

- `ths_public_validation`: `diagnostic_provider`.
- `akshare_ths_research`: `research_provider`.
- `tushare_ths_daily`: historical `candidate_primary` only; no Token, implementation or purchase is required.

AKShare 1.18.64 source shows that its Tonghuashun industry and concept history functions ultimately call the same `d.10jqka.com.cn/v4/line/bk_...` chart endpoint as the current adapter. Their lineage is therefore `shared_upstream`, not an independent fallback. No production Provider is approved.

## Offline commands

```bash
PYTHONPATH=backend python3.12 -m pytest -p no:cacheprovider -m "not live"
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1a.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b1.py
python3.12 scripts/validate_json.py
python3.12 scripts/validate_workflow.py
python3.12 scripts/check_sensitive_files.py
```

Deterministic inspection and replay commands do not access the network:

```bash
PYTHONPATH=backend python3.12 -m leopard_project.cli market eod-status --provider ths_public --as-of 2026-07-22T15:30:00+08:00
PYTHONPATH=backend python3.12 -m leopard_project.cli provider compare --sector-key semiconductor --as-of 2026-07-22T15:30:00+08:00
PYTHONPATH=backend python3.12 -m leopard_project.cli reconcile run --mode replay --trade-date 2026-07-21
```

Live tests remain explicit:

```bash
LEOPARD_RUN_LIVE=1 PYTHONPATH=backend python3.12 -m pytest -m live
```

See [EOD gating](docs/end-of-day-gating.md), [Provider lineage](docs/provider-lineage.md), [secondary-source validation](docs/secondary-source-validation.md), and the [reconciliation contract](docs/reconciliation-contract.md).
