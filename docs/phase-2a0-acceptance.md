# Phase 2A-0 acceptance

- [x] React + TypeScript + Vite and FastAPI + SQLAlchemy + SQLite foundation
- [x] Viewer/Admin in one application with backend role enforcement
- [x] Sunday–Thursday upload rhythm; Friday/Saturday normal no-report days
- [x] PDF MIME/header/size/path validation, SHA-256 deduplication and ignored storage
- [x] Local text extraction, explicit review, confirmed date and lifecycle controls
- [x] Viewer published-only reports, list/detail/PDF access
- [x] 8-group/66-sector views and published opinion timeline
- [x] HSTECH opinion display separated from `unsupported` market status
- [x] Responsive Island adapter design system with keyboard, text status and reduced motion
- [x] Controlled `animal-island-ui` 1.3.0 integration with attribution and closed commercialization gate
- [x] No external LLM, market network request, copied third-party source or official game asset
- [x] Offline backend/frontend/API/end-to-end tests and CI coverage

Known limitations: local authentication is not production identity; the fixture calendar is not production-approved; image-only PDFs have no OCR; rich text editing is intentionally absent; SQLite and local upload storage are for MVP only; no production Provider is approved.

UI dependency verification: `animal-island-ui` is pinned to 1.3.0 in both package manifests, React 19 uses one installed React/ReactDOM instance, and the production build succeeds. Compared with the pre-integration build, JavaScript increased from approximately 249.13 kB to 274.69 kB (gzip 79.85 kB to 88.19 kB). The required global stylesheet produces 109.20 kB CSS and includes three Simplified Chinese font weights, making the complete build approximately 3.9 MB. This font cost and the upstream `AI_USAGE.md` heading/version drift are accepted review risks for this private Phase 2A-0 baseline, not approval for commercial use.

Phase 2A-1 should be considered only after human acceptance of the complete local walkthrough, parser behavior on sanitized representative PDFs, and the Viewer/Admin information architecture.
