from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    app = (ROOT / "backend/leopard_project/web/app.py").read_text(encoding="utf-8")
    services = (ROOT / "backend/leopard_project/web/services.py").read_text(encoding="utf-8")
    enhanced = (ROOT / "backend/leopard_project/web/enhanced.py").read_text(encoding="utf-8")
    upload_page = (ROOT / "frontend/src/pages/admin/AdminNewReportPage.tsx").read_text(encoding="utf-8")
    result_page = (ROOT / "frontend/src/pages/admin/AdminInterpretationPage.tsx").read_text(encoding="utf-8")
    schedule = json.loads((ROOT / "config/report_schedule_policy_v1.json").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    checks = {
        "single_interpret_upload": "/api/v1/admin/reports/interpret" in app and "service.parse" in app and "parse_structured_text" in app,
        "interpretation_read_status_patch": all(route in app for route in (
            "/api/v1/admin/reports/{report_id}/interpretation",
            "/api/v1/admin/reports/{report_id}/interpretation-status",
        )),
        "date_confidence_contract": all(name in services for name in (
            "detected_report_date", "report_date_source", "report_date_confidence", "report_date_confirmed_by_user",
        )),
        "v23_section_variants": all(label in services for label in (
            "核心结论速览", "核心观点", "核心攻防线", "风险提示", "板块观点详细汇总", "板块历史路径图",
        )),
        "mapping_classification": all(value in services for value in ("confirmed", "probable", "unmapped", "conflict")),
        "all_66_preserved": "path_entry_count" in enhanced and "all_path_entries" in enhanced,
        "no_external_llm_or_ocr": '"external_llm_calls": 0' in enhanced and '"ocr_used": False' in enhanced,
        "date_auto_policy": schedule["automatic_report_date_detection"] is True
        and schedule["report_date_requires_confirmation"] is False
        and schedule["report_date_confirmation_required_for"] == ["low", "conflict"],
        "one_primary_upload_action": "上传并自动发布" in upload_page
        and "auto_publish_uploads" in app
        and "publish_strict" in app
        and "本地解析" not in upload_page
        and "增强解析" not in upload_page,
        "result_page_has_one_publish_action": result_page.count("确认并发布") == 1,
        "advanced_default_collapsed": "<details" in result_page and "查看全部66个板块路径" in result_page and "高级技术信息" in result_page,
        "market_not_blocking": "行情辅助数据缺失不影响确认与发布" in result_page,
        "parse_quality_gate": all(value in services for value in ("verified_structure", "blocking_parse_error", "history_matrix_quality")),
        "admin_anomaly_first": all(value in result_page for value in ("自动确认", "建议检查", "必须处理", "查看PDF原文")),
        "ci_includes_validator": "validate_upload_interpretation.py" in workflow,
        "documents_present": all((ROOT / path).is_file() for path in (
            "docs/pdf-upload-workflow.md",
            "docs/pdf-parsing-contract.md",
            "docs/report-lifecycle.md",
            "docs/enhanced-report-product.md",
        )),
    }
    result = {"checks": checks, "passed": all(checks.values())}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
