from __future__ import annotations

import argparse
import json
from pathlib import Path

from leopard_project.web.services import extract_layout_text, extract_positioned_pages, extract_text_layer, parse_report_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate one local, untracked V2.3/V2.4 PDF against the deterministic quality gate.")
    parser.add_argument("--pdf", required=True, type=Path)
    args = parser.parse_args()
    payload = args.pdf.read_bytes()
    text = extract_text_layer(payload)
    layout = extract_layout_text(payload)
    positioned = extract_positioned_pages(payload)
    fields, _, _, _ = parse_report_text(text, "local-fidelity-check", args.pdf.name, layout, positioned)
    meta = fields["interpretation_meta"]
    records = {item["sector_name"]: item for item in meta["assessment_records"]}
    dates = meta["pdf_history_matrix"].get("dates", [])
    template_version = meta["template_version"]
    # V2.9 makes the native 66-topic history matrix authoritative.  Its
    # short prose assessment table is not a 33-row replacement for V2.3,
    # so applying that legacy row-count gate would reject a sound upload.
    expected_assessments = 29 if template_version == "V2.4" else 33 if template_version != "V2.9" else None
    expected_dates = 35 if template_version == "V2.4" else 20
    status_counts = {
        status: sum(item["path_status"] == status for item in records.values())
        for status in ("hold", "turn_hold", "strong_watch", "watch", "weak_watch")
    }
    checks = {
        "report_structure_verified": meta["quality_status"] == "verified_structure",
        "assessment_row_count": (
            len(records) == expected_assessments
            if expected_assessments is not None
            else True
        ),
        "history_rows_66": meta["quality_summary"]["history_matrix_rows"] == 66,
        "history_date_count": len(dates) >= expected_dates,
        "all_assessments_verified": (
            all(item["quality_status"] == "verified_structure" for item in records.values())
            if template_version != "V2.9"
            else meta["pdf_history_matrix"].get("quality_status") == "verified_structure"
        ),
        "no_blocking_attention": not any(item.get("severity") == "blocking" for item in meta["attention_items"]),
        "freeze_append_contract": (
            meta["history_freeze"].get("through") == "2026-07-26"
            and meta["history_freeze"].get("appended_report_date") == "2026-07-27"
        ) if meta["template_version"] == "V2.4" else True,
        "v24_status_distribution": status_counts == {
            "hold": 6, "turn_hold": 3, "strong_watch": 4, "watch": 14, "weak_watch": 2,
        } if meta["template_version"] == "V2.4" else True,
        "no_external_ai": meta["external_llm_calls"] == 0 and meta["ocr_used"] is False,
    }
    result = {
        "pdf": args.pdf.name, "template_version": meta["template_version"],
        "checks": checks, "quality_summary": meta["quality_summary"],
        "status_counts": status_counts, "history_freeze": meta["history_freeze"],
        "passed": all(checks.values()),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
