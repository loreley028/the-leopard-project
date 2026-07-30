# AGENTS.md

Acceptance fidelity: PDF structure is the minimum product contract. Preserve the five detailed sector fields and evidence locations; fail closed on row bleed or unverified matrix structure. Viewer matrices default to 20 periods with solid configured colors, and sector research stays a dense table with numeric return bars.

## Project identity

- Display name: The Leopard Project
- Slug: `the-leopard-project`
- Python package: `leopard_project`
- API prefix: `/api/v1/`

Do not reintroduce superseded project codenames.

## Current phase

The repository is at Phase 2A-0 Upload-to-Interpretation acceptance revision.

- Each enhanced report is the product body. The primary Admin path is PDF upload → automatic local interpretation → populated result → one-click confirmed publication.
- Do not expose local parse, enhanced parse, date entry, 66 dropdowns or market snapshot freezing as ordinary required steps. Keep them collapsed as advanced recovery/review capabilities.
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

- Report topics remain 66. The explicit `hotel_catering` report-topic split yields
  67 market paths: 66 supported CN-A paths and one unsupported HSTECH path. Runtime
  denominators must be derived from `config/market_path_registry_v1.json`.
- HSTECH opinions may display; HSTECH market data remains `unsupported` and excluded from EOD/reconciliation.
- Viewer reads only `published`; Admin operations require backend role authorization.
- Upload time is not report date. High-confidence PDF dates are accepted automatically; only low-confidence or conflicting dates require confirmation.
- `report_date` and `market_as_of_date` remain separate. Missing market data never blocks PDF interpretation or publication; controlled calendars still fail closed.
- Path status comes only from `config/sector_path_status_v1.json`; `not_mentioned` never means a view expired.
- Indicators use only `complete_eod`; amount stays optional and is never fabricated.
- Published report market snapshots are immutable; sector latest market state is separate.
- Frozen PDF path history, `complete_eod` bars and intraday snapshots are three separate data lanes. Intraday data never enters formal indicators, report snapshots or the path matrix.
- A complete PDF matrix may initialize historical path dates without older detailed PDFs. Missing detailed PDFs must be labelled as path-only records.
- Intraday refresh is server-cached at five minutes, safely auto-started in `real_local`, and supports Admin pause/resume; Viewer access never calls a Provider.
- Viewer never triggers Provider access. Manual refresh requires Admin confirmation and is fixture-only in the local demo.
- Friday and Saturday are normal no-report days with no missing alert.
- Runtime SQLite and PDF uploads remain ignored under `var/`.
- Phase 1A and Phase 1B-0 evidence remains immutable.
- `real_local` uses only `var/real-local/` and must refuse fixture reports or fixture market bars.
- V2.3, V2.3.1 and V2.4 are approved parser routes; V2.4 explicit judgment cells are authoritative and cross-page tables are supported.
- Same-date files are revisions; Viewer sees only the current published revision.
- `reported_status=not_mentioned` carries the last explicit `effective_status` and does not end a holding interval.
- `ci_action_runtime_upgrade_pending` remains a maintenance item; do not change existing Action versions in this phase.

## Validation

```bash
PYTHONPATH=backend python3.12 -m pytest -p no:cacheprovider -m "not live"
PYTHONPATH=backend python3.12 scripts/validate_phase0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1a.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b0.py
PYTHONPATH=backend python3.12 scripts/validate_phase1b1.py
PYTHONPATH=backend python3.12 scripts/validate_phase2a0.py
PYTHONPATH=backend python3.12 scripts/validate_enhanced_report.py
PYTHONPATH=backend python3.12 scripts/validate_upload_interpretation.py
python3.12 scripts/validate_json.py
python3.12 scripts/validate_workflow.py
python3.12 scripts/check_sensitive_files.py
python3.12 scripts/check_ui_license_boundary.py
python3.12 -m compileall -q backend tests scripts
git diff --check
cd frontend && npm ci && npm run lint && npm run typecheck && npm run test && npm run build
```

Acceptance invariants: strict/broad holding intervals read the frozen full path ledger; low-attention hiding never changes the 66-item catalog; open-session Provider failure is never labelled market closed.
