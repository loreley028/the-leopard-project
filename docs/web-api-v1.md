# Web API v1

All Web data uses `/api/v1/`; pages never read local files directly.

Authentication:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Viewer:

- `GET /api/v1/reports`
- `GET /api/v1/reports/latest`
- `GET /api/v1/reports/{report_id}`
- `GET /api/v1/reports/{report_id}/pdf`
- `GET /api/v1/sectors`
- `GET /api/v1/sectors/{sector_key}`

Admin:

- `POST|GET /api/v1/admin/reports`
- `GET|PATCH /api/v1/admin/reports/{report_id}`
- `POST /api/v1/admin/reports/{report_id}/parse|ready|publish|withdraw`
- `POST /api/v1/admin/unmapped-terms/{term_id}/resolve`
- `GET /api/v1/admin/summary`

Errors use `{ "error": { "code": "stable_code", "message": "safe message" } }`. Viewer report queries filter to `published`. Admin endpoints require the `admin` role. Upload errors never return server paths.
