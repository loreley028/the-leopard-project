# Product MVP scope

Phase 2A-0 is a small internal research product for roughly ten read-only viewers and one primary administrator. The product is organized around published PDF research, not real-time quotes.

Viewer can read the latest and historical published reports, open the published PDF, browse all 66 sectors and follow published opinion timelines. Viewer never sees drafts or withdrawn reports.

Admin can upload a PDF, run local parsing, confirm the report date, edit controlled structured fields, resolve an unmapped term to an existing sector, mark ready, publish and withdraw. The formal sector catalog is not editable in the Web MVP.

Viewer and Admin share one React application, one FastAPI backend and one SQLite repository. Phase 2A-0 is local only: no cloud deployment, public access, production database, scheduler, live market request, external LLM, HSTECH integration or Phase 1B-2 observation.
