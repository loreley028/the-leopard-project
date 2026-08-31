"""Validate PDF -> persistence -> Reader report-fact parity in isolation.

The command uploads authoritative PDFs through the normal Admin endpoint into
a temporary SQLite database. It may accept suggestion-only review cards in
that disposable database so historically approved reports can reach the same
published Reader state; it never reads or writes production data.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from leopard_project.report_registry import load_report_registry, reader_report_registry
from leopard_project.sector_lifecycle import load_sector_lifecycle_splits
from leopard_project.trading_calendar import report_market_date
from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import LiveMarketAnchorDaily
from audit_report_ingestion_fidelity import _input_paths, pdf_snapshot


SUBSTANTIVE_FIELDS = (
    "current_path_status",
    "current_judgement",
    "main_basis",
    "observation_condition",
    "source_text_reference",
    "source_page",
)


def _facts_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left.get(field) == right.get(field) for field in SUBSTANTIVE_FIELDS)


def validate(paths: list[Path]) -> dict[str, Any]:
    documents = sorted((pdf_snapshot(path) for path in paths), key=lambda item: item.report_date)
    if len({item.report_date for item in documents}) != len(documents):
        raise ValueError("report_dates_must_be_unique")
    active_keys = {item.sector_key for item in reader_report_registry()}
    historical_only_keys = {
        item.sector_key for item in load_report_registry()
        if item.lifecycle == "historical_only"
    }
    split_child_keys = {
        child_key
        for split in load_sector_lifecycle_splits()
        for child_key in split.child_sector_keys
    }
    mismatches: list[dict[str, Any]] = []
    checked_facts = checked_matrix_overlays = reviewed_publications = additional_mention_fallback_facts = 0

    with tempfile.TemporaryDirectory(prefix="leopard-reader-consistency-") as directory:
        root = Path(directory)
        database_url = f"sqlite:///{root / 'reader.sqlite3'}"
        settings = WebSettings(
            database_url=database_url,
            upload_dir=root / "uploads",
            session_secret="reader-consistency-session-secret-at-least-32",
            admin_username="reader-consistency-admin",
            admin_password="reader-consistency-password-at-least-16",
            viewer_username="reader-consistency-viewer",
            viewer_password="reader-consistency-viewer-password",
            auto_publish_uploads=True,
        )
        factory = create_session_factory(database_url)
        with TestClient(create_app(settings, factory)) as client:
            login = client.post("/api/v1/auth/admin/login", json={
                "username": settings.admin_username,
                "password": settings.admin_password,
            })
            if login.status_code != 200:
                raise RuntimeError(f"admin_login_failed:{login.status_code}")
            with factory() as session:
                for trading_date in (date(2026, 7, 23), date(2026, 8, 28)):
                    session.add(LiveMarketAnchorDaily(
                        symbol="sh000001",
                        trading_date=trading_date,
                        close=Decimal("3900"),
                        pre_close=Decimal("3890"),
                        pct_change=Decimal("0.25"),
                        high=Decimal("3910"),
                        low=Decimal("3880"),
                        quote_datetime=datetime.combine(trading_date, datetime.min.time(), timezone.utc),
                        fetched_at=datetime.now(timezone.utc),
                        source="isolated_reader_consistency_axis",
                    ))
                session.commit()

            for document in documents:
                upload = client.post(
                    "/api/v1/admin/reports/interpret",
                    files={"file": (document.path.name, document.path.read_bytes(), "application/pdf")},
                )
                if upload.status_code != 201:
                    raise RuntimeError(f"upload_failed:{document.path.name}:{upload.status_code}:{upload.text[:300]}")
                payload = upload.json()
                report_id = payload["report"]["id"]
                if payload.get("publication") != "published":
                    accepted = client.post(f"/api/v1/admin/reports/{report_id}/review-issues/bulk-accept")
                    if accepted.status_code != 200:
                        raise RuntimeError(f"review_accept_failed:{document.report_date}:{accepted.status_code}")
                    published = client.post(f"/api/v1/admin/reports/{report_id}/publish")
                    if published.status_code != 200:
                        raise RuntimeError(f"publish_failed:{document.report_date}:{published.status_code}:{published.text[:300]}")
                    reviewed_publications += 1

                enhanced = client.get(f"/api/v1/reports/{report_id}/enhanced").json()
                latest = {
                    item["sector_key"]: item
                    for item in enhanced["sector_assessments"]
                    if item["explicitly_mentioned"]
                }
                direct_active = set(document.snapshot["direct_assessment_keys"]) & active_keys
                if not direct_active <= set(latest):
                    mismatches.append({
                        "report_date": document.report_date,
                        "surface": "LATEST_REPORT",
                        "missing": sorted(direct_active - set(latest)),
                    })
                additional_mention_fallback_facts += len(set(latest) - direct_active)
                board = {item["sector_key"]: item for item in client.get("/api/v1/sectors").json()}
                matrix = client.get(f"/api/v1/reports/{report_id}/path-matrix", params={"periods": "all"}).json()
                matrix_rows = {item["sector_key"]: item for item in matrix["rows"]}
                target_market_date = report_market_date(date.fromisoformat(document.report_date))

                for sector_key in sorted(direct_active):
                    checked_facts += 1
                    latest_fact = latest.get(sector_key)
                    board_fact = board.get(sector_key, {}).get("latest_explicit_view")
                    detail = client.get(f"/api/v1/sectors/{sector_key}/research").json()
                    detail_fact = detail.get("latest_explicit_view")
                    for surface, fact in (("BOARD_RESEARCH", board_fact), ("SECTOR_DETAIL", detail_fact)):
                        if (
                            latest_fact is None
                            or fact is None
                            or fact.get("report_id") != report_id
                            or fact.get("report_date") != document.report_date
                            or fact.get("path", {}).get("path_status") != latest_fact["current_path_status"]
                            or not _facts_equal(fact.get("assessment", {}), latest_fact)
                        ):
                            mismatches.append({
                                "report_date": document.report_date,
                                "sector_key": sector_key,
                                "surface": surface,
                            })
                    row = matrix_rows.get(sector_key, {})
                    cell = next((
                        item for item in row.get("cells", [])
                        if target_market_date is not None and item.get("trading_date") == target_market_date.isoformat()
                    ), None)
                    checked_matrix_overlays += 1
                    if (
                        latest_fact is None
                        or cell is None
                        or cell.get("report_id") != report_id
                        or cell.get("path_status") != latest_fact["current_path_status"]
                    ):
                        mismatches.append({
                            "report_date": document.report_date,
                            "sector_key": sector_key,
                            "surface": "HISTORY_MATRIX_REPORT_OVERLAY",
                            "expected_report_id": report_id,
                            "actual_report_id": cell.get("report_id") if cell else None,
                            "expected_path_status": latest_fact.get("current_path_status") if latest_fact else None,
                            "actual_path_status": cell.get("path_status") if cell else None,
                            "actual_review_status": cell.get("review_status") if cell else None,
                        })

            latest_report_id = payload["report"]["id"]
            final_latest = client.get(f"/api/v1/reports/{latest_report_id}/enhanced").json()
            final_latest_keys = {item["sector_key"] for item in final_latest["sector_assessments"]}
            final_board = client.get(
                "/api/v1/sectors",
                params={"include_low_attention": "true", "page_size": 100},
            ).json()
            final_board_keys = {item["sector_key"] for item in final_board}
            final_matrix = client.get(
                f"/api/v1/reports/{latest_report_id}/path-matrix",
                params={"periods": "all"},
            ).json()
            final_matrix_keys = {item["sector_key"] for item in final_matrix["rows"]}
            for surface, keys in (
                ("LATEST_REPORT_CURRENT_CATALOG", final_latest_keys),
                ("BOARD_RESEARCH_CURRENT_CATALOG", final_board_keys),
                ("HISTORY_MATRIX_CURRENT_CATALOG", final_matrix_keys),
            ):
                leaked = sorted(keys & historical_only_keys)
                if leaked:
                    mismatches.append({"surface": surface, "historical_only_leaks": leaked})
            if final_board_keys != active_keys:
                mismatches.append({
                    "surface": "BOARD_RESEARCH_CURRENT_CATALOG",
                    "missing_active": sorted(active_keys - final_board_keys),
                    "unexpected": sorted(final_board_keys - active_keys),
                })
            if final_matrix_keys != active_keys:
                mismatches.append({
                    "surface": "HISTORY_MATRIX_CURRENT_CATALOG",
                    "missing_active": sorted(active_keys - final_matrix_keys),
                    "unexpected": sorted(final_matrix_keys - active_keys),
                })
            if not split_child_keys <= final_board_keys or not split_child_keys <= final_matrix_keys:
                mismatches.append({
                    "surface": "SPLIT_CHILD_CURRENT_CATALOG",
                    "board_missing": sorted(split_child_keys - final_board_keys),
                    "matrix_missing": sorted(split_child_keys - final_matrix_keys),
                })
            for sector_key in sorted(historical_only_keys):
                if client.get(f"/api/v1/sectors/{sector_key}/research").status_code != 404:
                    mismatches.append({
                        "surface": "SECTOR_DETAIL_CURRENT_CATALOG",
                        "historical_only_leak": sector_key,
                    })

    return {
        "report_count": len(documents),
        "first_report_date": documents[0].report_date if documents else None,
        "last_report_date": documents[-1].report_date if documents else None,
        "reviewed_publication_count": reviewed_publications,
        "additional_mention_fallback_facts": additional_mention_fallback_facts,
        "checked_reader_facts": checked_facts,
        "checked_matrix_overlays": checked_matrix_overlays,
        "current_active_object_count": len(active_keys),
        "historical_only_object_count": len(historical_only_keys),
        "split_child_object_count": len(split_child_keys),
        "unexpected_substantive_diff": len(mismatches),
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path)
    parser.add_argument("--pdf", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = _input_paths(args.pdf_dir, args.pdf)
    if not paths:
        parser.error("at least one --pdf or --pdf-dir PDF is required")
    result = validate(paths)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["unexpected_substantive_diff"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
