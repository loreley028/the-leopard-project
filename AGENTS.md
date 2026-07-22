# AGENTS.md

## Project identity

- Display name: The Leopard Project
- Slug: `the-leopard-project`
- Python package: `leopard_project`
- API prefix: `/api/v1/`

Do not reintroduce superseded project codenames in code, examples, deployment names, or documentation.

## Current phase

The repository is at Phase 0. Until the user explicitly authorizes a later phase:

- do not connect to Alibaba Cloud or any production host;
- do not fetch production market data;
- do not deploy, push, merge, or operate remote infrastructure;
- do not build a complete frontend;
- do not read unrelated projects, credentials, `.env` files, databases, containers, or volumes;
- do not guess or silently replace market symbols;
- use only fixed local fixtures in tests.

## Architecture rules

- Sector definitions and mappings belong in versioned files under `config/`, never scattered through business logic.
- Business services depend on `MarketDataProvider`, not a concrete data library.
- Numeric indicators are deterministic code, not model-generated output.
- A mapping enters a daily job only when research status is confirmed, user approval is true, provider and primary symbol are present, and the effective date is present and active.
- Mapping changes create a new version with an effective date; never overwrite historical meaning.
- Hang Seng Tech uses an HK calendar and must not be filtered by the A-share calendar.
- Physical deletion of historical sectors is forbidden; use effective dates and enabled state.
- Custom/proxy data must record `data_status`; proxy substitution must never be silent.

## Validation

Run before handoff:

```bash
PYTHONPATH=backend python3.12 -m unittest discover -s tests -v
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
git diff --check
```
