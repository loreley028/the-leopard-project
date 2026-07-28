# Web API v1

验收扩展保持`/api/v1/`：路径矩阵支持`period=10|20|40|all`（默认20）；板块研究支持搜索、分组、路径、提及、行情状态、排序和分页参数；板块详情返回最近5期路径与最近20日行情。观点五字段包含PDF页码、原文摘录及质量状态。

增强 Viewer API：`/reports/{id}/enhanced`、`/path-matrix`、`/sector-assessments`、`/market-snapshots`、`/comparison`，以及 `/sectors/{sector_key}/research` 和 `/market/latest`。

增强 Admin API：`/enhance/parse`、路径和解读 PATCH、`/market-binding`、`/admin/market/refresh`、刷新记录、`/market-snapshot` 与 `/enhanced-ready`。Viewer 只能读取 published；Admin 操作继续验证角色。错误代码稳定，不返回服务器绝对路径，指标不在前端计算。

All Web data uses `/api/v1/`; pages never read local files directly.

Authentication:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Viewer:

- `GET /api/v1/reports`
- `GET /api/v1/reports/latest`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/pdf/preview`
- `GET /api/v1/reports/{report_id}/pdf/preview/pages/{page_number}`
- `GET /api/v1/reports/{report_id}/pdf/download`
- `GET /api/v1/sectors`
- `GET /api/v1/sectors/{sector_key}`

Admin:

- `POST|GET /api/v1/admin/reports`
- `GET|PATCH /api/v1/admin/reports/{report_id}`
- `POST /api/v1/admin/reports/{report_id}/parse|ready|publish|withdraw`
- `POST /api/v1/admin/unmapped-terms/{term_id}/resolve`
- `GET /api/v1/admin/summary`

Errors use `{ "error": { "code": "stable_code", "message": "safe message" } }`. Viewer report queries filter to `published`. Admin endpoints require the `admin` role. Upload errors never return server paths.
## Automatic interpretation

- `POST /api/v1/admin/reports/interpret`: validates, deduplicates, stores and interprets one PDF in a single Admin request.
- `GET /api/v1/admin/reports/{report_id}/interpretation`: returns the populated result, confidence, attention items, mentioned assessments and preserved 66-path structure.
- `GET /api/v1/admin/reports/{report_id}/interpretation-status`: returns the recoverable user-facing processing state.
- `PATCH /api/v1/admin/reports/{report_id}/interpretation`: applies exceptional manual corrections such as a low-confidence report date.
- `POST /api/v1/admin/reports/{report_id}/publish`: performs the minimum publication gate and the required internal transition in one confirmed action.

Duplicate upload is SHA-256 idempotent. Interpretation failure retains the stored PDF. Admin authorization applies to every interpretation endpoint; Viewer continues to read only published reports. Missing `market_as_of_date` or market snapshots does not block PDF interpretation or publication.
## Real-local daily endpoints

- `GET /runtime`: data mode and production-provider state.
- `GET /admin/report-days?start=&end=`: dynamic date states.
- `POST|DELETE /admin/report-days/{date}/skip`: confirm or cancel skip.
- `POST /admin/reports`: multipart upload, JSON response only.
- `GET /reports/{id}/pdf/preview`: page-image preview metadata.
- `GET /reports/{id}/pdf/preview/pages/{page_number}`: in-memory PNG page.
- `GET /reports/{id}/pdf/download`: explicit attachment.

Matrix cells include nullable `daily_return` and `market_as_of_date`; sector research includes reported/effective status and the backend-computed active holding interval.

Additional Admin-only real-local endpoints:

- `POST /admin/market/refresh`: explicitly confirmed low-rate historical diagnostic refresh.
- `POST /admin/market/import`: CSV/XLSX preview or confirmed import.
- `GET /market/status`: stored real-market and indicator counts.
- `GET|POST /admin/specifications`: list or add versioned local specification backups.
- `GET /admin/specifications/{id}` and `/file`: metadata and explicit attachment download.
- `POST /admin/specifications/{id}/current`: select the current backup version without affecting parsing.

`POST /admin/reports/{id}/publish` accepts explicit warning confirmation and an audit note. True blocking parse errors remain rejected.

`GET /reports/{report_id}/path-matrix?periods=20` accepts 10/20/40/all and returns separate report/market dates plus weekday metadata. `GET /sectors/{sector_key}/research?path_periods=20&market_days=20` accepts path periods 10/20/40/60 and market days 20/40/60; it returns recent five complete days, formal/historical holding intervals and a separate intraday cache object.

Viewer cache APIs are `GET /market/intraday/status` and `GET /market/intraday/sectors`. Admin controls are `POST /admin/market/intraday/start`, `/pause` and `/refresh-now`. Viewer calls never invoke the Provider.

`GET /sectors` supports `include_low_attention` and `low_attention_only`. Admin pin endpoints are `POST/DELETE /admin/sectors/{sector_key}/pin`. Research responses expose strict/broad current and historical intervals.
