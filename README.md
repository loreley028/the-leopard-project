# The Leopard Project

The Leopard Project is a PDF-driven research Web MVP. Its primary workflow is:

```text
Admin uploads PDF → confirms report date → local parsing → human review → publish → Viewer reads reports and sector opinions
```

Market snapshots are secondary research context, not the product. Phase 2A-0 does not deploy, schedule collection, approve a production Provider, call an external LLM, or connect to Alibaba Cloud.

## Product boundary

- One React + TypeScript + Vite application with Viewer and Admin route areas.
- One FastAPI backend and versioned `/api/v1/` contract.
- SQLite through SQLAlchemy Repository for local MVP use; runtime DB and uploads stay under ignored `var/` paths.
- PDF parsing is local, text-layer first, never auto-published.
- Reports are normally uploaded Sunday through Thursday evenings. Friday and Saturday are normal no-report days and never create missing-report alerts.
- Viewer sees only `published`; Admin can upload, parse, review, publish and withdraw.
- The 66-sector opinion catalog remains intact. Market support remains 65/1; HSTECH opinions display normally while automatic HK market data stays `unsupported`.

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

Passwords and session secrets are supplied only through the untracked `.env`. There is no registration, recovery, OAuth, email, SMS or SSO in this local research MVP.

## Offline validation

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
cd frontend && npm ci && npm run lint && npm run typecheck && npm run test && npm run build
```

See [product scope](docs/product-mvp-scope.md), [upload workflow](docs/pdf-upload-workflow.md), [API v1](docs/web-api-v1.md), [design system](docs/frontend-design-system.md), and [local development](docs/local-development.md).
