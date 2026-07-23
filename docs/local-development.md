# Local development

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
