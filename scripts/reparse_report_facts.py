"""Deterministically fill missing five-column V2.9 reader facts in a preview.

The command is intentionally opt-in and preview-scoped.  It does not alter
publication state, report dates, path statuses, frozen history, PDFs, or any
manually edited assessment.  It only reads an already-uploaded PDF and fills
blank structured table fields in the target SQLite database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from leopard_project.web.database import create_session_factory
from leopard_project.web.enhanced import EnhancedReportService
from leopard_project.web.models import Report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--upload-dir", type=Path, required=True)
    parser.add_argument("--report-date", required=True, help="ISO report date to reparse")
    parser.add_argument("--preview-only", action="store_true", help="required acknowledgement for a preview database")
    args = parser.parse_args()
    if not args.preview_only:
        parser.error("--preview-only is required; this maintenance command is not for production databases")
    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        report = session.scalar(select(Report).where(Report.report_date == args.report_date, Report.is_current.is_(True)))
        if report is None or report.file is None:
            raise SystemExit("current_report_or_pdf_not_found")
        payload_path = args.upload_dir / report.file.storage_filename
        if not payload_path.is_file():
            raise SystemExit("preview_pdf_not_found")
        result = EnhancedReportService(session).reparse_missing_assessment_facts(
            report, payload_path.read_bytes(), "preview_deterministic_maintenance",
        )
    print(json.dumps({"report_date": args.report_date, "preview_only": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
