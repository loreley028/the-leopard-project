# The Leopard Project

The Leopard Project (`the-leopard-project`) is a configuration-driven, deterministic after-market sector analytics system. The current Phase 1B-0 baseline defines CI, the first-release support boundary, a deterministic 65-sector collection plan, and evidence-backed provider selection. It does not enable production collection, scheduling, database writes, cloud access, or deployment.

## Current support boundary

- Business catalog: 66 sectors across 8 groups.
- Automatic A-share market-data support: 65 sectors.
- Unsupported in the first automatic release: Hang Seng Tech (`HSTECH`, HK), displayed as `暂不支持` with reason `cross_market_not_integrated`.
- Daily collection denominator: 65; for example, 64 successes produce `64 / 65`.
- Hang Seng Tech remains available to the transcript-driven daily PDF report. Market-data support never removes transcript content.

The Phase 1A validation record remains immutable historical evidence. Phase 1B-0 adds a versioned product-support policy; it does not rewrite the earlier finding that HSTECH data was technically obtainable.

## Provider status

- `ths_public_validation`: `diagnostic_provider`
- `akshare_ths`: `research_provider`
- `tushare_ths_daily`: `candidate_primary` only; no Token, account test, or implementation is required in this phase.
- No `production_primary` or `production_fallback` is approved.

The current selection conclusion is that free/public sources are not yet sufficient for stable production. See [provider selection](docs/provider-selection.md) and the [comparison matrix](docs/provider-comparison-matrix.md).

## Naming contract

| Item | Value |
|---|---|
| Display name | `The Leopard Project` |
| Slug | `the-leopard-project` |
| Python package | `leopard_project` |
| Compose project | `leopard_project` |
| Database | `leopard_project` |
| Containers | `leopard-api`, `leopard-web`, `leopard-scheduler`, `leopard-db` |
| API prefix | `/api/v1/` |

## Local validation

Python 3.12 is required. The default suite is offline; live tests require an explicit marker and environment opt-in.

```bash
PYTHONPATH=backend python3.12 -m pytest -m "not live"
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1a.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b0.py
python3.12 scripts/validate_json.py
python3.12 scripts/check_sensitive_files.py
```

Explicit diagnostic live test and controlled selection scan:

```bash
LEOPARD_RUN_LIVE=1 PYTHONPATH=backend python3.12 -m pytest -m live
PYTHONPATH=backend python3.12 -m leopard_project.cli providers select-phase1b0 --output-dir data/provider-selection
```

CI runs only the offline suite and has read-only repository permissions. See [CI documentation](docs/ci.md).
