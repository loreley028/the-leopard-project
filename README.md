# The Leopard Project

Phase 2A-0验收修订以PDF忠实还原为最低要求：管理端默认只处理解析异常，Viewer只展示published；增强报告提供默认20期实心色历史矩阵、五字段板块详细汇总及高密度板块研究表。行情仅作辅助，不调用外部LLM，不启用`production_primary`。

The Leopard Project is the dynamic enhanced edition of the 大盘猎豹直播总结. The PDF remains the evidence and business mainline; each enhanced Web report is the product body, while the archive and 66-sector catalog are entry layers. Its primary workflow is:

```text
Admin selects PDF → uploads and automatically interprets locally → checks the populated result → confirms publication → Viewer reads the enhanced report and longitudinal sector research
```

Market snapshots and MA/return/volume metrics are secondary research context, not the product. Historical report snapshots are immutable; sector latest market state may change only after an explicit Admin refresh. Phase 2A-0 does not deploy, schedule collection, approve a production Provider, call an external LLM, or connect to Alibaba Cloud.

## Product boundary

- One React + TypeScript + Vite application with Viewer and Admin route areas.
- One FastAPI backend and versioned `/api/v1/` contract.
- SQLite through SQLAlchemy Repository for local MVP use; runtime DB and uploads stay under ignored `var/` paths.
- PDF parsing is local and text-layer first. Upload automatically creates the structured interpretation, but publication always remains an explicit one-click confirmation.
- Reports are normally uploaded Sunday through Thursday evenings. Friday and Saturday are normal no-report days and never create missing-report alerts.
- Viewer sees only `published`; Admin normally uses the three-step upload → question review → publication flow. Each question has a stable persisted decision, while PDF evidence, technical diagnostics, reparse and full 66-sector review remain collapsed advanced operations.
- The 66-sector opinion catalog remains intact. Market support remains 65/1; HSTECH opinions display normally while automatic HK market data stays `unsupported`.
- Versioned path states, native cross-report matrix, five-field sector assessments and deterministic report comparison are first-class structures.

## Controlled noncommercial UI dependency

Selected interface primitives use the exactly pinned `animal-island-ui` 1.3.0 package under CC BY-NC 4.0 for the current private, noncommercial research scope. Application pages depend on the local Island adapter layer, and original business components remain where accessibility or workflow semantics require them. See [third-party notices](THIRD_PARTY_NOTICES.md) and the [UI license assessment](docs/ui-license-assessment.md). No Nintendo official asset is copied into this repository, and commercial use remains gated pending a new review.

## Local development

```bash
cp .env.example .env
python3.12 -m pip install -e ".[dev]"
set -a && source .env && set +a
PYTHONPATH=backend python3.12 -m uvicorn leopard_project.web.app:create_app --factory --reload
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Create an isolated five-report enhanced fixture demo without touching the normal local database:

```bash
PYTHONPATH=backend python3.12 scripts/run_enhanced_demo.py
```

The script refuses to overwrite an existing `var/demo-enhanced/leopard_demo.sqlite3`.

Passwords and session secrets are supplied only through the untracked `.env`. There is no registration, recovery, OAuth, email, SMS or SSO in this local research MVP.

## Offline validation

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
cd frontend && npm ci && npm run lint && npm run typecheck && npm run test && npm run build
```

See [product scope](docs/product-mvp-scope.md), [upload workflow](docs/pdf-upload-workflow.md), [API v1](docs/web-api-v1.md), [design system](docs/frontend-design-system.md), and [local development](docs/local-development.md).
## Phase 2A-0 real-local acceptance mode

Daily use runs with `LEOPARD_DATA_MODE=real_local`, `var/real-local/leopard_project.sqlite3`, and `var/real-local/uploads/`. This mode refuses fixture reports or fixture market bars. The root page is the latest complete published report; Admin is organized by live date. Friday and Saturday are normal no-report days that can be skipped or changed to upload.

Supported templates are V2.3, V2.3.1 and V2.4. Upload returns JSON; PDF navigation does not request the file, preview uses server-rendered in-memory page images, and only the explicit download endpoint returns the original PDF as an attachment. `report_date`, `market_as_of_date`, latest complete EOD date and current intraday date are distinct. In `real_local`, the server can run a controlled five-minute intraday cache and gap-only EOD backfill; Admin can pause/resume or trigger a refresh. No production market provider exists. Specification backups are versioned separately and never influence parsing.

## Phase 2A-0 data lanes

The local acceptance build keeps three independent lanes: frozen PDF path history, `complete_eod` market history, and cached intraday snapshots. A complete V2.4 PDF can initialize all reliable historical path dates without requiring every older PDF to be uploaded. Weekend reports retain their own `report_date` while market cells use the separately frozen `market_as_of_date`.

Intraday refresh is a process-local five-minute server cache which starts automatically in `real_local`, refreshes stale or missing open-market data on startup, and remains persistently pausable by Admin. Test/process-level disabling and natural market closure do not persist an Admin pause. Viewer requests only poll the local cache and never call a Provider; intraday values never enter formal moving averages, multi-day returns, holding-period EOD returns, or report snapshots. Eastmoney board spot is retained as a research-only line; existing public historical endpoints remain diagnostic and `production_primary` does not exist.

The final acceptance view adds compact dual-date matrix headers, centralized intraday status, strict/broad holding intervals and reversible low-attention filtering. No researched intraday source is yet `live_validated`.
