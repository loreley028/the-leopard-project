# AGENTS.md

## Project identity

- Display name: The Leopard Project
- Slug: `the-leopard-project`
- Python package: `leopard_project`
- API prefix: `/api/v1/`

Do not reintroduce superseded project codenames in code, examples, deployment names, or documentation.

## Current phase

The repository is at Phase 1B-0: CI, support-scope policy, deterministic collection planning, and provider selection. Until the user explicitly authorizes a later phase:

- do not connect to Alibaba Cloud or any production host;
- do not deploy, start production collection, write a production database, or enable a formal scheduler;
- do not request Tushare credentials, points, or purchases and do not implement a formal Tushare Provider;
- do not label any source `production_primary` or `production_fallback`;
- do not build a complete frontend or modify the daily PDF specification/business logic;
- do not read unrelated projects, credentials, `.env` files, databases, containers, or volumes;
- do not guess or silently replace market symbols;
- live network tests require explicit user authorization and must remain separated from the default offline suite.

## Support boundary

- Keep all 66 business sectors in the catalog.
- Generate automatic collection work for exactly 65 A-share sectors.
- Hang Seng Tech remains in the catalog as `HSTECH/HK`, but its first-release automatic status is `unsupported` with reason `cross_market_not_integrated`.
- Unsupported is a product decision, never a fetch failure. It must not trigger collection, indicators, rankings, alerts, retries, provider statistics, reconciliation, or freshness checks.
- Daily PDF summarization remains transcript-driven and independent of automatic market-data support.

## Architecture rules

- Sector definitions, mappings, support policies, and provider roles belong in versioned `config/` files.
- Business services depend on `MarketDataProvider`, not a concrete data library.
- Numeric indicators and collection plans are deterministic code, not model-generated output.
- Mapping changes create a new version with an effective date; historical Phase 1A evidence is immutable.
- Custom/proxy data records `data_status`; hotel catering remains explicit proxy `881160`.
- Glass substrate remains `886111` with short-history handling.

## Validation

Run before handoff:

```bash
PYTHONPATH=backend python3.12 -m pytest -m "not live"
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1a.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b0.py
python3.12 scripts/validate_json.py
python3.12 scripts/check_sensitive_files.py
python3.12 -m compileall -q backend tests scripts
git diff --check
```
