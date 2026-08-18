from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from leopard_project.config import load_seed_bundle
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import Report, ReportFile, SectorPathHistoryEntry
from leopard_project.web.path_history import audit_frozen_path_history, sync_path_history


def _matrix(report_date: date, *, rare_earth: str, oil_petrochemical: str) -> dict:
    bundle = load_seed_bundle()
    statuses = {
        "rare_earth": rare_earth,
        "oil_petrochemical": oil_petrochemical,
    }
    dates = ["8/03"] if report_date == date(2026, 8, 3) else ["8/03", f"{report_date.month}/{report_date.day:02d}"]
    return {
        "quality_status": "verified_structure",
        "dates": dates,
        "rows": [
            {
                "sector_key": item.sector_key,
                "sector_name": item.sector_name,
                "statuses": [
                    statuses.get(item.sector_key, "not_mentioned"),
                    statuses.get(item.sector_key, "not_mentioned"),
                ][:len(dates)],
            }
            for item in bundle.sectors
        ],
    }


def _report(session, report_date: date, *, sha_seed: str, rare_earth: str, oil_petrochemical: str) -> Report:
    report = Report(
        title=f"formal-{report_date.isoformat()}",
        report_date=report_date,
        report_date_confirmed=True,
        status="published",
        is_current=True,
        template_version="V2.9",
        interpretation_meta_json=json.dumps({"pdf_history_matrix": _matrix(
            report_date, rare_earth=rare_earth, oil_petrochemical=oil_petrochemical,
        )}),
        created_by="test",
        data_origin="real_upload",
    )
    report.file = ReportFile(
        sha256=sha_seed.ljust(64, "0"),
        original_filename=f"{report_date}.pdf",
        storage_filename=f"{report_date}.pdf",
        content_type="application/pdf",
        size_bytes=1,
    )
    session.add(report)
    session.flush()
    return report


def _entry(session, sector_key: str) -> SectorPathHistoryEntry:
    return session.scalar(select(SectorPathHistoryEntry).where(
        SectorPathHistoryEntry.sector_key == sector_key,
        SectorPathHistoryEntry.path_report_date == date(2026, 8, 3),
    ))


def test_newer_formal_pdf_supersedes_older_history_snapshot_and_preserves_local_snapshot(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'authority.sqlite3'}")
    with sessions() as session:
        august_3 = _report(session, date(2026, 8, 3), sha_seed="aug03", rare_earth="hold", oil_petrochemical="hold")
        session.commit()
        sync_path_history(session, august_3)
        august_4 = _report(session, date(2026, 8, 4), sha_seed="aug04", rare_earth="watch", oil_petrochemical="turn_weak")
        session.commit()
        sync_path_history(session, august_4)
        assert _entry(session, "rare_earth").path_status == "watch"
        assert _entry(session, "oil_petrochemical").path_status == "turn_weak"

        august_17 = _report(session, date(2026, 8, 17), sha_seed="aug17", rare_earth="hold", oil_petrochemical="hold")
        session.commit()
        result = sync_path_history(session, august_17)
        rare_earth = _entry(session, "rare_earth")
        oil = _entry(session, "oil_petrochemical")
        assert rare_earth.path_status == oil.path_status == "hold"
        assert rare_earth.source_report_id == oil.source_report_id == august_17.id
        assert result.difference_count == 0
        assert result.status == "canonical_reconciled"
        assert {item["sector_key"] for item in result.differences} == {"rare_earth", "oil_petrochemical"}
        assert all(item["resolution_reason"] == "newer_formal_history_baseline" for item in result.differences)
        # The 8/4 source snapshot is untouched; only the derived ledger moved.
        august_4_matrix = json.loads(august_4.interpretation_meta_json)["pdf_history_matrix"]
        by_sector = {item["sector_key"]: item["statuses"][0] for item in august_4_matrix["rows"]}
        assert by_sector["rare_earth"] == "watch"
        assert by_sector["oil_petrochemical"] == "turn_weak"


def test_canonical_history_is_import_order_independent(tmp_path: Path) -> None:
    expected: list[tuple[str, str, str]] | None = None
    for label, order in (("forward", (3, 4, 17)), ("reverse", (17, 4, 3))):
        sessions = create_session_factory(f"sqlite:///{tmp_path / f'{label}.sqlite3'}")
        with sessions() as session:
            specs = {
                3: (date(2026, 8, 3), "hold", "hold"),
                4: (date(2026, 8, 4), "watch", "turn_weak"),
                17: (date(2026, 8, 17), "hold", "hold"),
            }
            for key in order:
                report_date, rare_earth, oil = specs[key]
                current = _report(session, report_date, sha_seed=f"{label}{key}", rare_earth=rare_earth, oil_petrochemical=oil)
                session.commit()
                sync_path_history(session, current)
            actual = [
                (item.sector_key, item.path_status, item.source_report_id)
                for item in session.scalars(select(SectorPathHistoryEntry).where(
                    SectorPathHistoryEntry.sector_key.in_(("rare_earth", "oil_petrochemical")),
                    SectorPathHistoryEntry.path_report_date == date(2026, 8, 3),
                ).order_by(SectorPathHistoryEntry.sector_key))
            ]
            # The matrix test uses each report's own date.  Its point is the
            # authoritative value, not the non-overlapping source identifiers.
            values = [(item.sector_key, item.path_status) for item in session.scalars(select(SectorPathHistoryEntry).where(
                SectorPathHistoryEntry.sector_key.in_(("rare_earth", "oil_petrochemical")),
                SectorPathHistoryEntry.path_report_date == date(2026, 8, 3),
            ).order_by(SectorPathHistoryEntry.sector_key))]
            assert values == [("oil_petrochemical", "hold"), ("rare_earth", "hold")]
            assert session.scalar(select(func.count()).select_from(SectorPathHistoryEntry)) == 3 * 66
            if expected is None:
                expected = actual
            else:
                assert [(key, value) for key, value, _ in actual] == [(key, value) for key, value, _ in expected]


def test_same_date_different_sha_stays_fail_closed(tmp_path: Path) -> None:
    sessions = create_session_factory(f"sqlite:///{tmp_path / 'same-date.sqlite3'}")
    with sessions() as session:
        _report(session, date(2026, 8, 17), sha_seed="first", rare_earth="hold", oil_petrochemical="hold")
        incoming = _report(session, date(2026, 8, 17), sha_seed="second", rare_earth="hold", oil_petrochemical="hold")
        session.commit()
        conflicts = audit_frozen_path_history(session, incoming)
        assert len(conflicts) == 1
        assert conflicts[0]["reason"] == "same_date_different_sha"
