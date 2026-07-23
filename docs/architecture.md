# Architecture — Phase 2A-0

```text
React Viewer/Admin routes
        │ /api/v1/
        ▼
FastAPI auth + report endpoints
        │
ReportService ── local PDF text-layer parser
        │
ReportRepository ── SQLAlchemy ── local SQLite
        │                              │
versioned config                  ignored var/uploads
        │
66-sector catalog + 65/1 auxiliary market status
```

Viewer and Admin are areas of one Web application, backed by the same API and repository. The browser never reads JSON or SQLite directly and never computes lifecycle or market status.

The PDF workflow is primary. Uploaded files are validated by filename, MIME, header and configured size; SHA-256 prevents silent duplicate reports. Parsing is local and cannot publish. Report date confirmation, unresolved-term handling and lifecycle transitions are enforced by services.

SQLite is isolated behind SQLAlchemy and `ReportRepository`; the schema avoids SQLite-only business semantics so a future PostgreSQL migration remains possible. Runtime files are never tracked.

Existing Provider, EOD, TradingCalendar and reconciliation boundaries remain intact. HSTECH is excluded from market collection/EOD/reconciliation but not from PDF opinion mapping. Phase 1A and Phase 1B-0 evidence is immutable.

CI remains offline and read-only. It runs historical backend checks, Phase 2A-0/API/PDF tests, UI license checks, frontend lint/typecheck/unit/accessibility tests and production build. `ci_action_runtime_upgrade_pending` remains recorded; existing Action versions are unchanged.
