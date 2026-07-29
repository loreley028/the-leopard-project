# Local development

增强演示数据使用独立目录，绝不覆盖默认 `var/leopard_project.sqlite3`：

```bash
PYTHONPATH=backend python3.12 scripts/run_enhanced_demo.py
```

若 `var/demo-enhanced/leopard_demo.sqlite3` 已存在，脚本会拒绝覆盖。启动时将 `LEOPARD_DATABASE_URL` 指向该数据库、`LEOPARD_UPLOAD_DIR` 指向 `var/demo-enhanced/uploads`。

高保真页面验收使用隔离的20期演示：

```bash
PYTHONPATH=backend python3.12 scripts/run_enhanced_demo.py --runtime-dir var/demo-fidelity
```

该目录包含20份脱敏虚构报告、1320个路径单元格和65个受控行情 fixture，不访问网络；已有数据库同样拒绝覆盖。

Requirements: Python 3.12 and Node 22+.

```bash
cp .env.example .env
python3.12 -m pip install -e ".[dev]"
set -a && source .env && set +a
PYTHONPATH=backend python3.12 -m uvicorn leopard_project.web.app:create_app --factory --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` to `127.0.0.1:8000`. Use only localhost. Admin/viewer usernames and passwords are configured in the untracked `.env`; no demo password is committed.

Manual UI acceptance routes:

- Viewer: `/`, `/reports`, `/reports/:reportId`, `/sectors`, `/sectors/:sectorKey`, `/about`
- Admin: `/admin`, `/admin/reports/new`, `/admin/reports`, `/admin/reports/:reportId/review`

Verify the footer license link from both route areas, the About attribution links, keyboard focus and Escape behavior, the 390px mobile layout, PDF upload/review/publish, and the published report in Viewer. The local server must not be exposed outside `127.0.0.1`.

For the fixture walkthrough, log in as the environment-configured admin, upload `tests/fixtures/sample_report_fixture.pdf`, parse, confirm `2026-07-19`, mark ready, publish, log in as viewer and open the report plus the semiconductor/HSTECH sector pages.

The same lifecycle can be verified without persisting a DB or upload:

```bash
PYTHONPATH=backend python3.12 scripts/run_phase2a0_demo.py
```
## Upload-to-Interpretation demo

Use a separate ignored SQLite path when validating a real local PDF. The upload request itself initializes the report and interpretation; do not copy the PDF into the repository or add it to a fixture. The Admin flow is available at `/admin/reports/new`, and the resulting route is `/admin/reports/{reportId}/interpretation`.

The browser must reach only `127.0.0.1`; Vite proxies `/api` to the local FastAPI process. Neither upload nor page rendering makes an external network or LLM request.
## Real local usage

Use the ignored `.env` with:

```text
LEOPARD_DATA_MODE=real_local
LEOPARD_DATABASE_URL=sqlite:///var/real-local/leopard_project.sqlite3
LEOPARD_UPLOAD_DIR=var/real-local/uploads
```

This path is separate from every demo database. Startup fails if fixture-origin reports or fixture market rows are found. Do not run `run_enhanced_demo.py` against this directory.

In `real_local`, open `/admin/market` to inspect the server intraday cache and gap-only EOD backfill, pause/resume the loop, perform an explicitly confirmed low-rate historical refresh, or preview/confirm a CSV/XLSX import. Automatic intraday refresh is enabled by default, starts one process-local scheduler, refreshes stale/missing open-market cache on startup, and then runs every five minutes. An Admin pause is persisted; `LEOPARD_MARKET_AUTOMATION_ENABLED=false` is only a process-level temporary disable and does not write a permanent pause. Market break, close and non-trading days are displayed separately and never become an Admin pause. Open `/admin/specifications` to keep ignored local copies of PDF-production specifications; those files are versioned independently and never enter the report parser.

The PDF preview is lazy: report navigation and refresh do not request the PDF. `/api/v1/reports/{id}/pdf/preview` returns page metadata and `/pdf/preview/pages/{page}` renders an in-memory PNG without persisting it. `/pdf/download` is the only endpoint that returns the original PDF and always uses attachment disposition.

The intraday session safely starts in `real_local` when enabled. An Admin may pause or resume it from the market page; only controlled CN-A sessions issue research-grade requests. The five-minute loop and cache are local-only and must not be exposed on `0.0.0.0`.

The SQLite schema gains additive Phase 2A-0 tables for frozen path history, review decisions, runtime pause control and intraday cache. Existing reports, decisions, PDFs, EOD rows, indicators and snapshots are retained. Back up `var/real-local/leopard_project.sqlite3` before the first revised start.

Migration `0010` adds only review decisions and runtime pause control. Local Provider evaluation outputs remain under temporary directories and must not be committed.
