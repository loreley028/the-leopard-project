# AGENTS.md

## Project identity

- Display name: The Leopard Project
- Slug: `the-leopard-project`
- Python package: `leopard_project`
- API prefix: `/api/v1/`

Do not reintroduce superseded project codenames.

## Current phase

The repository is at Phase 2A-0: PDF-driven research Web MVP foundation and local publication loop.

- PDF upload, local parsing, human review, publication and Viewer display are the product mainline.
- Market data is auxiliary; do not start collection, scheduling or Provider promotion.
- Do not connect to Alibaba Cloud, deploy, expose public access or write a production database.
- Do not request Tushare credentials, implement a formal Tushare Provider or approve candidate/production roles.
- Do not call an external LLM or online AI service for PDF parsing.
- Do not modify the PDF specification/business logic or integrate HSTECH market data.
- `animal-island-ui` is approved only as the exact npm dependency `1.3.0` for the
  current private, noncommercial research scope. Keep attribution and the
  commercialization review gate in force; do not copy its source or assets.
- Do not use Nintendo characters, logos, screenshots, audio, icons, fonts or
  other official game assets, and do not imply endorsement or affiliation.
- Do not start Phase 1B-2, five-day observation or Phase 2A-1 without explicit approval.

## Invariants

- Catalog/support/unsupported/denominator remain 66/65/1/65.
- HSTECH opinions may display; HSTECH market data remains `unsupported` and excluded from EOD/reconciliation.
- Viewer reads only `published`; Admin operations require backend role authorization.
- Upload time is not report date; administrator confirmation is mandatory.
- Friday and Saturday are normal no-report days with no missing alert.
- Runtime SQLite and PDF uploads remain ignored under `var/`.
- Phase 1A and Phase 1B-0 evidence remains immutable.
- `ci_action_runtime_upgrade_pending` remains a maintenance item; do not change existing Action versions in this phase.

## Validation

```bash
PYTHONPATH=backend python3.12 -m pytest -p no:cacheprovider -m "not live"
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1a.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b1.py
PYTHONPATH=backend python3.12 scripts/validate_phase2a0.py
python3.12 scripts/validate_json.py
python3.12 scripts/validate_workflow.py
python3.12 scripts/check_sensitive_files.py
python3.12 scripts/check_ui_license_boundary.py
python3.12 -m compileall -q backend tests scripts
git diff --check
cd frontend && npm ci && npm run lint && npm run typecheck && npm run test && npm run build
```
