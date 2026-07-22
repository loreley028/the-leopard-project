# Data model

## Phase 0 contracts

| Model | Responsibility |
|---|---|
| `Sector` | Stable canonical sector identity, group, order, enabled/effective state |
| `SectorAlias` | Confirmed input name to canonical `sector_key` |
| `SectorMapping` | Versioned provider symbol, method, research status, approval, sources, effective date |
| `DailyBar` | Immutable normalized daily OHLCV/amount record with provenance |
| `IndicatorSnapshot` | Deterministic indicators for one date |
| `DailySectorSnapshot` | Sector, mapping version, bar, indicators, and job linkage |
| `JobRun` | Reproducibility metadata and success/failure counts |
| `DataAnomaly` | Classified data-quality or processing exception |
| `ExportManifest` | Export path, hash, row count, and version lineage |

Amounts are stored as numeric values in the provider-normalized unit. A production provider must document and test that unit before admission. Phase 0 does not select a production unit or silently rescale unknown input.

## Persistence design

The SQL draft uses PostgreSQL tables for sectors, aliases, mapping versions, mappings, daily bars, indicator snapshots, daily sector snapshots, job runs, anomalies, and export manifests. Mapping versions are append-only. Natural uniqueness includes `(provider, symbol, market, trade_date)` for bars and `(sector_key, trade_date, mapping_version)` for snapshots.

Phase 1 should translate the draft into SQLAlchemy 2 models and Alembic revisions, add transaction-bound repositories, and verify rollback/idempotency. No database was created in Phase 0.
