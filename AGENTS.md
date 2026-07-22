# AGENTS.md

## Project identity

- Display name: The Leopard Project
- Slug: `the-leopard-project`
- Python package: `leopard_project`
- API prefix: `/api/v1/`

Do not reintroduce superseded project codenames.

## Current phase

The repository is at Phase 1B-1: complete-session gating, Provider lineage, secondary-source research, and offline reconciliation foundations.

- Do not connect to Alibaba Cloud, deploy, start production collection, write a production database, or enable a scheduler.
- Do not request Tushare credentials or purchases and do not implement a formal Tushare Provider.
- Do not approve `production_primary` or `production_fallback`.
- Do not run network collection by default; live tests and scans require explicit confirmation.
- Do not modify the PDF specification/business logic or integrate HSTECH.
- Do not simulate or wait for five production trading days.

## Invariants

- Catalog/support/unsupported/denominator remain 66/65/1/65.
- HSTECH remains `unsupported` and is excluded from EOD gating and reconciliation.
- `safe_accept_after` and reconciliation thresholds live in versioned config, not business code.
- Business logic uses the CN A-share `TradingCalendar` abstraction, never weekday guesses.
- The checked-in calendar is a controlled test/replay fixture and is not production-approved.
- AKShare Tonghuashun history and the current adapter are `shared_upstream`; different adapters are not independent sources.
- Amount remains optional and missing values are recorded, never fabricated.
- Phase 1A and Phase 1B-0 evidence remains immutable.
- `ci_action_runtime_upgrade_pending` remains a maintenance item; do not change Actions versions in this phase.

## Validation

```bash
PYTHONPATH=backend python3.12 -m pytest -p no:cacheprovider -m "not live"
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1a.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b1.py
python3.12 scripts/validate_json.py
python3.12 scripts/validate_workflow.py
python3.12 scripts/check_sensitive_files.py
python3.12 -m compileall -q backend tests scripts
git diff --check
```
