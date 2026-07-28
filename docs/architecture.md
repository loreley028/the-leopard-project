# Architecture — Phase 2A-0

PDF文本层依次形成普通文本、layout文本和页面坐标片段；解析器恢复结构并输出证据与质量状态，发布Service执行fail-closed闸门。Viewer只消费不可变的published报告快照；最新行情在独立研究表中，绝不覆盖历史报告快照。

Phase 2A-0 增强层在现有 FastAPI、SQLAlchemy、SQLite、Repository/Service 结构上扩展。核心实体为 `SectorPathEntry`、`SectorAssessment`、`SectorDailyBar`、`SectorIndicatorSnapshot`、`ReportSectorMarketSnapshot`、`MarketRefreshRun/Item` 和 `EnhancedReportRevision`。

前端只访问 `/api/v1/`；页面不直接访问数据库、不计算指标、不访问 Provider。运行数据库和上传仍位于 `var/`，可迁移 PostgreSQL；受控 fixture 与真实运行数据分离。

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
## Interpretation orchestration

The FastAPI upload boundary orchestrates a synchronous, recoverable local pipeline for the current small PDFs: validation/deduplication → durable original-file save → text-layer extraction → deterministic V2.3/V2.3.1/V2.4 parsing → date confidence → sector mapping → 66-path initialization → interpretation result. Internal stages remain auditable but are collapsed into one user operation.

SQLAlchemy models persist the user-facing status and interpretation provenance. Repository/Service layers retain database ownership; React never reads SQLite or computes interpretation fields. External AI, OCR, Provider access and scheduling are absent from this path.
## Real-local isolation and evolving catalog

Runtime mode is explicit (`test` or `real_local`). Real-local has an isolated database and upload root plus a startup contamination guard. Reports have same-date revisions and only one current Viewer version. Catalog versions carry validity dates and entries; adding a 67th entry creates a new version rather than rewriting historical report structure.

Real-local market ingestion is an explicit Admin subsystem separated from the upload parser. It accepts either a serial low-rate `diagnostic_provider` refresh or a preview/confirmed file import, stores only `complete_eod`, calculates indicators server-side, and never runs on a schedule. Viewer consumes stored rows and immutable report snapshots only.

Specification backups use their own model and ignored runtime directory. Version selection does not feed parser input, quality gates or report history. PDF preview and attachment are separate HTTP routes, while React defers creation of the preview iframe until explicit user action.

The acceptance revision adds a frozen `SectorPathHistoryEntry` ledger and limited-retention `SectorIntradaySnapshot` cache. `SectorPathEntry`/`SectorAssessment` remain tied to uploaded detailed reports; the history ledger also represents report dates whose source PDF has not yet been uploaded. `IntradayRefreshCoordinator` is process-local, single-cycle and Admin-controlled, while audit rows remain in `MarketRefreshRun/Item`. A restart never restores the runtime session.

Data flows are deliberately isolated: PDF matrix -> frozen path ledger; Provider/import -> `complete_eod` bars -> formal indicators/snapshots; Admin intraday session -> cached intraday snapshots -> Viewer read APIs. No intraday edge points into formal indicators or published snapshots.

The domain layer derives strict/broad holding intervals and low-attention visibility from the frozen ledger. `SectorResearchPreference` stores only Admin pin state; it cannot alter catalog or report data.
