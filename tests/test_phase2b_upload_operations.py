from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import SectorPathHistoryEntry
from leopard_project.web.services import _history_shape_matches_report_date, extract_layout_text, extract_positioned_pages, extract_text_layer, parse_report_text


def pseudo_pdf(text: str) -> bytes:
    return f"%PDF-1.4\n%LEOPARD_TEXT_BEGIN\n{text}\n%LEOPARD_TEXT_END\n%%EOF".encode()


def report_text(day: str, version: str, freeze: str, primary: str, secondary: str) -> str:
    year, month, calendar_day = day.split("-")
    chinese_day = f"{year}年{int(month)}月{int(calendar_day)}日"
    return f"""大盘猎豹 {chinese_day}直播总结 {version}
历史冻结至{freeze}，仅新增{day[5:].replace('-', '/')}。
核心结论：严格校验后的最终报告。
行情结论：核心攻防线：{primary}；次攻防线：{secondary}。
板块主线
半导体
"""


@pytest.fixture()
def automatic_web(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'automatic.sqlite3'}"
    settings = WebSettings(
        database_url=database_url,
        upload_dir=tmp_path / "uploads",
        session_secret="test-only-phase2b-session-secret-at-least-32",
        admin_username="admin",
        admin_password="admin-test-password",
        viewer_username="viewer",
        viewer_password="viewer-test-password",
        auto_publish_uploads=True,
    )
    with TestClient(create_app(settings, create_session_factory(database_url))) as client:
        assert client.post("/api/v1/auth/admin/login", json={"username": "admin", "password": "admin-test-password"}).status_code == 200
        yield client, settings


def upload(client: TestClient, filename: str, text: str):
    return client.post("/api/v1/admin/reports/interpret", files={"file": (filename, pseudo_pdf(text), "application/pdf")})


def test_v29_0810_contract_is_metadata_not_date_specific() -> None:
    fields, *_ = parse_report_text(
        report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09"),
        "v29-contract",
    )
    metadata = fields["interpretation_meta"]
    assert fields["candidate_report_date"].isoformat() == "2026-08-10"
    assert metadata["template_version"] == "V2.9"
    assert metadata["history_freeze"]["through"] == "2026-08-09"
    assert metadata["defense_lines"]["primary_defense_line"] == 3864.27
    assert metadata["defense_lines"]["secondary_defense_line"] == 3847.09
    assert metadata["matrix_statistics"] == {"display_rows": None, "active_objects": None}


def test_v29_0811_matrix_statistics_contract_is_not_hardcoded() -> None:
    fields, *_ = parse_report_text(
        report_text("2026-08-11", "V2.9", "2026-08-10", "3878.83", "3864.27")
        + "\ndisplay_rows: 74\nactive_objects: 71\n",
        "v29-0811-matrix-contract",
    )
    metadata = fields["interpretation_meta"]
    assert fields["candidate_report_date"].isoformat() == "2026-08-11"
    assert metadata["history_freeze"]["through"] == "2026-08-10"
    assert metadata["defense_lines"]["primary_defense_line"] == 3878.83
    assert metadata["defense_lines"]["secondary_defense_line"] == 3864.27
    assert metadata["matrix_statistics"] == {"display_rows": 74, "active_objects": 71}


def test_v28_and_v29_version_metadata_are_compatible() -> None:
    for version in ("V2.8", "V2.9"):
        fields, *_ = parse_report_text(report_text("2026-08-11", version, "2026-08-10", "3878.83", "3864.27"), version)
        assert fields["interpretation_meta"]["template_version"] == version
        assert fields["interpretation_meta"]["history_freeze"]["through"] == "2026-08-10"


def test_v29_semantic_defense_line_moves_are_not_first_number_heuristics() -> None:
    text = "核心成本线由 3864.27 点继续上移至 3878.83 点。3878.83点成为第一层纪律线，3864.27点退居第二层地板。"
    fields, *_ = parse_report_text(f"大盘猎豹 2026年8月11日直播总结 V2.9\n{text}", "semantic-line")
    defense = fields["interpretation_meta"]["defense_lines"]
    assert defense["primary_defense_line"] == 3878.83
    assert defense["secondary_defense_line"] == 3864.27
    assert len(defense["primary_evidence"]) >= 2 and defense["conflict"] is False


def test_v29_defense_conflict_has_evidence_and_never_becomes_auto_review_free() -> None:
    text = "核心线由 3864.27 点上移至 3878.83 点。核心攻防线提高到 3900 点。"
    fields, *_ = parse_report_text(f"大盘猎豹 2026年8月11日直播总结 V2.9\n{text}", "conflicting-line")
    attention = fields["interpretation_meta"]["attention_items"]
    issue = next(item for item in attention if item["kind"] == "defense_line_conflict")
    assert issue["severity"] == "blocking" and issue["candidates"]


def test_real_v29_pdf_layout_has_74_display_rows_71_active_and_66_canonical_rows() -> None:
    source = Path("/Users/cailei/Downloads/猎豹pef/大盘猎豹8月10日直播总结-V2.9版.pdf")
    if not source.exists():
        pytest.skip("user-provided V2.9 acceptance PDF is not present")
    payload = source.read_bytes()
    fields, *_ = parse_report_text(
        extract_text_layer(payload), "real-v29", source.name, extract_layout_text(payload), extract_positioned_pages(payload),
    )
    matrix = fields["interpretation_meta"]["pdf_history_matrix"]
    assert matrix["quality_status"] == "verified_structure"
    assert (matrix["display_row_count"], matrix["active_object_count"], matrix["row_count"]) == (74, 71, 66)
    assert all("blank" not in row["statuses"] for row in matrix["rows"])


@pytest.mark.parametrize(("filename", "expected_date", "expected_template", "expected_shape"), [
    ("大盘猎豹7月30日直播总结-V2.4板块拆分修正版(5).pdf", "2026-07-30", "V2.4", (68, 68, 66)),
    ("大盘猎豹8月2日直播总结-V2.6板块复核版(2).pdf", "2026-08-02", "V2.6", (73, 70, 66)),
    ("大盘猎豹8月3日直播总结-V2.6版(4).pdf", "2026-08-03", "V2.6", (73, 70, 66)),
    ("大盘猎豹8月4日直播总结-V2.6版(3).pdf", "2026-08-04", "V2.6", (74, 71, 66)),
])
def test_real_historical_pdf_matrix_shapes_are_explicitly_accepted(
    filename: str, expected_date: str, expected_template: str, expected_shape: tuple[int, int, int],
) -> None:
    source = Path("/Users/cailei/Downloads/猎豹pef") / filename
    if not source.exists():
        pytest.skip("user-provided historical acceptance PDF is not present")
    payload = source.read_bytes()
    fields, *_ = parse_report_text(
        extract_text_layer(payload), "historical-shape", source.name, extract_layout_text(payload), extract_positioned_pages(payload),
    )
    matrix = fields["interpretation_meta"]["pdf_history_matrix"]
    assert fields["candidate_report_date"].isoformat() == expected_date
    assert fields["interpretation_meta"]["template_version"] == expected_template
    assert (matrix["display_row_count"], matrix["active_object_count"], matrix["row_count"]) == expected_shape
    assert matrix["quality_status"] == "verified_structure"


def test_legacy_history_shape_is_bound_to_its_lifecycle_window() -> None:
    shape = {"accepted_structure": {"effective_from": "2026-07-30", "effective_through": "2026-07-30"}}
    assert _history_shape_matches_report_date(shape, date(2026, 7, 30)) is True
    assert _history_shape_matches_report_date(shape, date(2026, 8, 2)) is False


@pytest.mark.parametrize("filename", [
    "大盘猎豹8月2日直播总结-V2.6板块复核版(2).pdf",
    "大盘猎豹8月3日直播总结-V2.6版(4).pdf",
    "大盘猎豹8月4日直播总结-V2.6版(3).pdf",
])
def test_v26_execution_conclusion_is_preserved_as_market_path(filename: str) -> None:
    source = Path("/Users/cailei/Downloads/猎豹pef") / filename
    if not source.exists():
        pytest.skip("user-provided historical acceptance PDF is not present")
    payload = source.read_bytes()
    fields, *_ = parse_report_text(
        extract_text_layer(payload), "v26-market-path", source.name,
        extract_layout_text(payload), extract_positioned_pages(payload),
    )
    assert fields["market_path"].startswith(("3832", "3833"))
    assert not any(item["kind"] == "market_path" for item in fields["interpretation_meta"]["attention_items"])


def test_explicit_unknown_sector_candidate_is_preserved_without_mapping() -> None:
    fields, _, _, terms = parse_report_text(
        "大盘猎豹 2026年8月16日直播总结 V2.9\n新增候选：工程机械。\n板块观点详细汇总\n",
        "candidate-audit",
        "candidate.pdf",
    )
    candidate = fields["interpretation_meta"]["sector_candidates"]
    assert candidate == [{
        "raw_name": "工程机械", "normalized_name": "工程机械", "status": "candidate_only",
        "report_date": "2026-08-16", "source_pdf": "candidate.pdf", "source_page": 1,
        "evidence": "新增候选：工程机械",
    }]
    assert [(item.term, item.status) for item in terms] == [("工程机械", "candidate")]
    assert fields["interpretation_meta"]["mapping_summary"]["candidate"] == 1


@pytest.mark.parametrize(("filename", "expected_candidates"), [
    ("大盘猎豹7月29日直播总结-V2.4版(8).pdf", ["脑机接口", "航空机场", "乳业"]),
    ("大盘猎豹7月30日直播总结-V2.4板块拆分修正版(5).pdf", ["脑机接口"]),
    ("大盘猎豹8月2日直播总结-V2.6板块复核版(2).pdf", ["跨境支付"]),
    # 核电已经有显式的正式展示行，因此不得降格或重复记为候选。
    ("大盘猎豹8月3日直播总结-V2.6版(4).pdf", []),
    ("大盘猎豹8月16日直播总结-V2.9版(4).pdf", ["工程机械"]),
])
def test_real_historical_pdf_candidates_remain_audit_only(
    filename: str, expected_candidates: list[str],
) -> None:
    source = Path("/Users/cailei/Downloads/猎豹pef") / filename
    if not source.exists():
        pytest.skip("user-provided historical acceptance PDF is not present")
    payload = source.read_bytes()
    fields, _, mentions, terms = parse_report_text(
        extract_text_layer(payload), "historical-candidates", source.name,
        extract_layout_text(payload), extract_positioned_pages(payload),
    )
    candidates = fields["interpretation_meta"]["sector_candidates"]
    assert [item["normalized_name"] for item in candidates] == expected_candidates
    assert all(item["status"] == "candidate_only" for item in candidates)
    assert not {item["normalized_name"] for item in candidates} & {item.sector_name for item in mentions}
    assert [(item.term, item.status) for item in terms if item.status == "candidate"] == [
        (item["raw_name"], "candidate") for item in candidates
    ]


def test_v29_downward_defense_line_move_keeps_new_line_as_primary() -> None:
    fields, *_ = parse_report_text(
        "大盘猎豹 2026年8月16日直播总结 V2.9\n核心攻防线从 3900 点下调到 3896.49 点。",
        "defense-line-down",
    )
    defense = fields["interpretation_meta"]["defense_lines"]
    assert defense["primary_defense_line"] == 3896.49
    assert defense["secondary_defense_line"] == 3900.0


def test_real_v29_uploads_gap_import_then_appends_without_review(automatic_web) -> None:
    first_pdf = Path("/Users/cailei/Downloads/猎豹pef/大盘猎豹8月10日直播总结-V2.9版.pdf")
    second_pdf = Path("/Users/cailei/Downloads/猎豹pef/大盘猎豹8月11日直播总结-V2.9版.pdf")
    if not first_pdf.exists() or not second_pdf.exists():
        pytest.skip("user-provided V2.9 acceptance PDFs are not present")
    client, settings = automatic_web
    first = client.post("/api/v1/admin/reports/interpret", files={"file": (first_pdf.name, first_pdf.read_bytes(), "application/pdf")}).json()
    second = client.post("/api/v1/admin/reports/interpret", files={"file": (second_pdf.name, second_pdf.read_bytes(), "application/pdf")}).json()
    assert first["publication"] == second["publication"] == "published"
    assert first["interpretation"]["review_workflow"]["summary"]["must_handle"] == 0
    assert second["interpretation"]["review_workflow"]["summary"]["suggested_review"] == 0
    # The formal V2.9 display registry can retain split Report objects in
    # addition to the legacy 66 market-mapped topics.  They must load even
    # when no market helper is available.
    assert first["interpretation"]["ingestion_summary"]["history_matrix"]["inserted_cells"] >= 45 * 66
    assert second["interpretation"]["ingestion_summary"]["history_matrix"]["inserted_cells"] >= 66
    assert second["interpretation"]["ingestion_summary"]["history_matrix"]["verified_same_cells"] >= 45 * 66
    assert second["interpretation"]["ingestion_summary"]["history_matrix"]["conflicts"] == 0
    with create_session_factory(settings.database_url)() as session:
        assert session.query(SectorPathHistoryEntry).count() >= 46 * 66


def test_v29_fidelity_validator_uses_the_authoritative_history_matrix() -> None:
    source = Path("/Users/cailei/Downloads/猎豹pef/大盘猎豹8月10日直播总结-V2.9版.pdf")
    if not source.exists():
        pytest.skip("user-provided V2.9 acceptance PDF is not present")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_real_pdf_fidelity.py",
            "--pdf",
            str(source),
        ],
        env={**__import__("os").environ, "PYTHONPATH": "backend"},
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[1],
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["template_version"] == "V2.9"
    assert payload["checks"]["assessment_row_count"] is True
    assert payload["checks"]["all_assessments_verified"] is True


def test_final_upload_publishes_automatically_and_duplicate_is_idempotent(automatic_web) -> None:
    client, settings = automatic_web
    payload = report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09")
    first = upload(client, "final-0810.pdf", payload)
    assert first.status_code == 201
    body = first.json()
    assert body["publication"] == "published"
    assert body["report"]["status"] == "published"
    assert len(list(settings.upload_dir.rglob("*.pdf"))) == 1
    assert len(list((settings.upload_dir / "published").glob("*.pdf"))) == 1
    assert not list((settings.upload_dir / ".staging").glob("*.pdf"))
    duplicate = upload(client, "final-0810.pdf", payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["publication"] == "already_published"
    assert duplicate.json()["report"]["id"] == body["report"]["id"]
    assert len(client.get("/api/v1/admin/reports").json()) == 1


def test_same_date_different_pdf_is_blocked_without_changing_latest(automatic_web) -> None:
    client, settings = automatic_web
    first = upload(client, "final-0810.pdf", report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09"))
    assert first.status_code == 201
    conflict = upload(client, "replacement-0810.pdf", report_text("2026-08-10", "V2.9", "2026-08-09", "3865.27", "3847.09"))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "report_date_conflict"
    latest = client.get("/api/v1/reports/latest").json()
    assert latest["id"] == first.json()["report"]["id"]
    assert len(list((settings.upload_dir / "published").glob("*.pdf"))) == 1
    assert len(list((settings.upload_dir / ".staging").glob("*.pdf"))) == 1


def test_automatic_publish_stops_for_incomplete_or_ambiguous_input(automatic_web) -> None:
    client, _ = automatic_web
    incomplete = "大盘猎豹 2026年8月10日直播总结 V2.9\n板块历史路径图\n"
    response = upload(client, "incomplete.pdf", incomplete)
    assert response.status_code == 201
    assert response.json()["publication"] == "needs_review"
    assert response.json()["report"]["status"] != "published"


def test_operations_status_is_read_only_and_has_empty_state(automatic_web) -> None:
    client, _ = automatic_web
    response = client.get("/api/v1/admin/operations/status")
    assert response.status_code == 200
    assert response.json()["latest_published_report_date"] is None
    assert response.json()["latest_live_market_anchor_eod_date"] is None
    assert response.json()["latest_security_proxy_eod_date"] is None
    assert response.json()["capture_mode"] == "host_systemd_timer"
    freshness = response.json()["market_history_status"]
    assert freshness["expected_latest_completed"]
    assert freshness["shanghai"] == "stale_history"
    assert freshness["security_coverage"] == {"through_expected": 0, "required": 27}
