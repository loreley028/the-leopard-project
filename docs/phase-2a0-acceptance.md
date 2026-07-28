# Phase 2A-0 acceptance

本地验收覆盖：2026-07-27 V2.4真实PDF 29条详细观点、37条本场未更新、66行35期历史矩阵可追溯；阻塞异常禁止发布；Viewer只见published；桌面矩阵默认20期实心色；板块研究为高密度表格；详细汇总保留五个核心字段。当前仍无`production_primary`。

验收修订增加：增强报告主体、原生历史路径矩阵、五字段板块解读、报告/行情日期分离、完整 EOD 指标、不可变报告快照、板块当前最新行情、确定性跨期对比、Admin 手工 fixture 刷新和 5 期独立演示数据。

边界保持 66/65/1；恒生科技观点与行情分离；酒店餐饮 proxy；玻璃基板 short_history；无生产 Provider、外部 LLM、生产调度、阿里云连接或部署。服务器统一五分钟盘中研究缓存和EOD缺口补齐不构成生产Provider批准。

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
## Upload-to-Interpretation acceptance revision

Acceptance now requires the ordinary Admin path to expose only upload-and-interpret, a populated interpretation result and one confirm-and-publish action. High-confidence dates are filled automatically. Low/conflicting dates, probable/unmapped/conflicting mappings, unknown statuses and missing key fields are the only default attention items.

The raw text, parser diagnostics, technical reparse buttons and complete 66-sector dropdown/matrix are preserved but collapsed. Market binding remains optional. External LLM and OCR calls remain zero.
## Combined real-use acceptance revision

The ten acceptance targets are handled together: latest complete report at `/`, five PDF fields visible, status plus optional real daily return in the matrix, ten-period research and active holding interval, strict test/real-local separation, JSON upload without download, V2.3.1 Insurance/CPO regression, date-based Admin, Friday/Saturday skip-or-upload, and zero fixture content in real-local.

The final local revision additionally requires lazy inline PDF preview with one explicit attachment endpoint, Viewer/Admin provenance separation, manually confirmed real-market refresh/import, warning-confirmed publication without weakening true blockers, and isolated specification backup versions. No behavior in this list starts scheduling or promotes a Provider.

Acceptance now includes 34-period recovery from the 2026-07-26 PDF, 66 records per path date, 10/20/40/all matrix ranges, 10/20/40/60 sector path ranges, separate 20/40/60 market charts, compounded five-day returns with daily detail, EOD-only holding intervals, and an Admin-controlled five-minute intraday cache. `real_local` must remain free of fixtures and the PR remains Draft.

Final acceptance additionally covers compact 80px matrix dates, V2.4 cross-page parsing, explicit judgment precedence, centralized Provider-failure display, strict/broad EOD holding intervals, ten-period low-attention filtering, in-memory PDF page previews and Admin pinning without catalog deletion.
