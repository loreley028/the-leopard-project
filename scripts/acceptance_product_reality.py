"""Read-only product reality acceptance checks for a running Viewer preview.

This deliberately exercises the same public endpoints the browser uses.  It
does not write a database, schedule a capture, or make a Provider request other
than the Viewer observation requested by the product page itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


PENDING_REVIEW_MARKERS = ("等待管理员复核", "等待人工复核", "pending_review")


def get_json(base_url: str, path: str) -> Any:
    url = f"{base_url.rstrip('/')}/api/v1{path}"
    try:
        with urlopen(url, timeout=15) as response:  # noqa: S310 - operator supplied local preview URL
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} for {path}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed for {path}: {exc.reason}") from exc


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in strings(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in strings(nested)]
    return []


def evaluate(payloads: dict[str, Any]) -> dict[str, Any]:
    sectors = payloads["sectors"]
    enhanced = payloads["enhanced"]
    anchor = payloads["anchor"]
    history = payloads["history"]
    cpo = payloads["cpo"]
    matrix = payloads["matrix"]
    failures: list[str] = []
    report_topics = {item.get("parent_report_topic") for item in sectors if item.get("parent_report_topic")}
    if len(sectors) != 67 or len(report_topics) != 66:
        failures.append(f"catalog expected 67 market paths / 66 report topics, got {len(sectors)} / {len(report_topics)}")
    visible_pending = [item for item in strings(enhanced) if item.strip() in PENDING_REVIEW_MARKERS]
    if visible_pending:
        failures.append(f"Viewer enhanced report still exposes {len(visible_pending)} pending-review placeholders")
    if anchor.get("quote_status") != "available" or anchor.get("data_mode") not in {"live", "completed_eod"}:
        failures.append("Shanghai anchor is neither a live nor a completed-EOD fact")
    if int(history.get("completed_days") or 0) < 1 or not history.get("items"):
        failures.append("Shanghai completed-history lane has no genuine completed day")
    cpo_proxy = cpo.get("security_proxy") or {}
    if cpo.get("viewer_source_mode") != "security_proxy" or len(cpo_proxy.get("instruments") or []) != 4:
        failures.append("CPO does not expose its four fixed proxy securities")
    dates = {item.get("report_date"): item.get("market_as_of_date") for item in matrix.get("dates", [])}
    future_0728 = 0
    mismatched_market_dates = 0
    for row in matrix.get("rows", []):
        for cell in row.get("cells", []):
            report_date = cell.get("report_date")
            market_date = cell.get("market_as_of_date")
            if cell.get("daily_return") is not None and market_date != dates.get(report_date):
                mismatched_market_dates += 1
            if report_date and report_date > "2026-07-28" and market_date == "2026-07-28":
                future_0728 += 1
    if mismatched_market_dates:
        failures.append(f"path matrix contains {mismatched_market_dates} market facts whose date differs from the requested report column")
    if future_0728:
        failures.append(f"path matrix contains {future_0728} prohibited post-2026-07-28 fallback facts")
    return {
        "passed": not failures,
        "failures": failures,
        "report_topic_count": len(report_topics),
        "market_path_count": len(sectors),
        "visible_pending_review_count": len(visible_pending),
        "anchor_data_mode": anchor.get("data_mode"),
        "completed_shanghai_history_days": history.get("completed_days"),
        "cpo_proxy_count": len(cpo_proxy.get("instruments") or []),
        "cpo_proxy_status": cpo_proxy.get("status"),
        "mismatched_market_dates": mismatched_market_dates,
        "future_2026_07_28_fallback_count": future_0728,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18083/leopard", help="isolated preview base URL")
    args = parser.parse_args()
    latest = get_json(args.base_url, "/reports/latest")
    report_id = latest["id"]
    payloads = {
        "sectors": get_json(args.base_url, "/sectors?include_low_attention=true"),
        "enhanced": get_json(args.base_url, f"/reports/{report_id}/enhanced"),
        "anchor": get_json(args.base_url, "/market/anchor"),
        "history": get_json(args.base_url, "/market/anchor/history"),
        "cpo": get_json(args.base_url, "/market-paths/cpo/viewer-observation"),
        "matrix": get_json(args.base_url, f"/reports/{report_id}/path-matrix?periods=20"),
    }
    result = evaluate(payloads)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
