# Architecture — Phase 0

## Boundary

The Leopard Project separates source acquisition, deterministic calculation, persistence, API delivery, and later commentary verification. Phase 0 implements only the domain foundation and offline fixtures.

```text
Versioned config -> Config loader -> Eligibility policy
                                      |
Fake Provider -> normalized DailyBar -> indicator pure functions -> snapshot models
                                      |
                              future repository/API/export layers
```

Business code does not import a Tonghuashun, Tushare, AKShare, RQData, or other production client. A future provider adapter must implement `MarketDataProvider` and return normalized `DailyBar` records with provider, acquisition time, payload hash, market, and data status.

## Modules

- `config/`: versioned sectors, aliases, researched mappings, and custom-composition rules.
- `backend/leopard_project/models.py`: Pydantic domain contracts.
- `backend/leopard_project/config.py`: loading, structural validation, alias lookup, and mapping admission.
- `backend/leopard_project/providers/`: provider abstraction, error taxonomy, and offline Fake Provider.
- `backend/leopard_project/indicators.py`: deterministic numeric calculations and ranking.
- `backend/leopard_project/mappings.py`: immutable, version-producing batch approval.
- `backend/migrations/versions/`: SQL migration design draft for Phase 1.
- `tests/` and `data/fixtures/`: offline deterministic verification.

## Deployment naming reservation

The future Compose project is `leopard_project`, database is `leopard_project`, and reserved container names are `leopard-api`, `leopard-web`, `leopard-scheduler`, and `leopard-db`. The API prefix is `/api/v1/`.

The deployment path must be an isolated new path selected during Phase 3. The old project-book path is not authoritative after the project rename. No server connection or deployment occurred in Phase 0.

## Future data flow

1. Scheduler selects the correct market calendar (A-share or Hong Kong).
2. Repository loads only mappings passing the admission policy for the trade date.
3. Provider validates symbols and returns normalized bars.
4. Validator rejects missing, duplicated, misdated, or malformed records.
5. Pure functions calculate indicators from ordered trading-session data.
6. A transaction stores raw bars, indicator snapshots, anomalies, and a job run.
7. Exporters produce traceable Excel/JSON artifacts and an `ExportManifest`.
8. `/api/v1/` exposes stored results; the frontend never recalculates core indicators.
