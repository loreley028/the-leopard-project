from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.models import Report, SectorAssessment, SectorPathEntry, SectorPathHistoryEntry
from leopard_project.web.repository import ReportRepository
from leopard_project.security_proxy_daily import market_core_security_symbols
from leopard_project.live_market_anchor_daily import intraday_defense_overlay
from leopard_project.web.live_market_anchor import structure_leopard_defense_line
from leopard_project.web.services import ReportService, _active_report_object_keys_in_text, _history_shape_matches_report_date, _main_fields, extract_layout_text, extract_positioned_pages, extract_text_layer, parse_report_text


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


def test_existing_published_report_reconciliation_preserves_identity(automatic_web) -> None:
    client, settings = automatic_web
    response = upload(client, "authoritative.pdf", report_text("2026-08-10", "V2.9", "2026-08-09", "3864.27", "3847.09"))
    assert response.status_code == 201
    report_id = response.json()["report"]["id"]
    factory = create_session_factory(settings.database_url)
    with factory() as session:
        report = session.scalar(select(Report).where(Report.id == report_id))
        assert report is not None and report.status == "published" and report.file is not None
        identity = (report.id, report.report_date, report.file.sha256, report.published_at, report.published_by)
        report.core_view = "旧解析错误"
        session.commit()
    with factory() as session:
        report = session.scalar(select(Report).where(Report.id == report_id))
        assert report is not None
        result = ReportService(ReportRepository(session), settings.upload_dir).reconcile_existing_report_facts(report, "reconciliation-test")
        assert result["publication"] == "published"
    with factory() as session:
        report = session.scalar(select(Report).where(Report.id == report_id))
        assert report is not None and report.file is not None
        assert (report.id, report.report_date, report.file.sha256, report.published_at, report.published_by) == identity
        assert report.core_view != "旧解析错误"


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


def test_report_object_name_matching_respects_generic_split_boundaries() -> None:
    assert _active_report_object_keys_in_text("电池/锂电池", date(2026, 7, 29)) == {"battery_lithium"}
    assert _active_report_object_keys_in_text("电池/锂电池", date(2026, 7, 30)) == set()
    assert _active_report_object_keys_in_text("电 池 ／ 锂 电 池", date(2026, 7, 30)) == set()
    assert _active_report_object_keys_in_text("电池、锂电池", date(2026, 7, 30)) == {"battery", "lithium_battery"}


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


@pytest.mark.parametrize("wording", ("为", "是", "提高到", "仍为"))
def test_explicit_core_defense_line_continuity_wording_is_supported(wording: str) -> None:
    fields, *_ = parse_report_text(
        f"大盘猎豹 2026年8月27日直播总结 V3.0\n核心攻防线{wording} 3930.1 点。",
        f"defense-line-{wording}",
    )
    assert fields["interpretation_meta"]["defense_lines"]["primary_defense_line"] == 3930.1


def test_v30_discipline_routing_is_fallback_only() -> None:
    fields, _ = _main_fields(
        "趋势纪律\n核心攻防线仍为3930.1点，站稳转进攻。\n量能结构\n已放量。\n"
        "下一交易日新纪律：收盘站在3930.1点之上转进攻；收盘跌回3930.1点下方继续防守。\n"
        "三、后续正文\n不得进入执行结论。"
    )
    assert fields["market_path"] == "收盘站在3930.1点之上转进攻；收盘跌回3930.1点下方继续防守。"

    explicit, _ = _main_fields(
        "执行结论：旧路由保持权威。\n数据与历史说明\n下一交易日新纪律：不得抢占。\n三、后续正文"
    )
    assert explicit["market_path"] == "旧路由保持权威。"


def test_authoritative_v30_0827_defense_line_and_conditions_regression() -> None:
    source = Path(__file__).parent / "fixtures" / "authoritative" / "大盘猎豹8月27日直播总结-V3.0版.pdf"
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == "d26d403d180f95abf0ac17c171b53536fefbb4304462ab8e579bda321c937742"
    fields, *_ = parse_report_text(
        extract_text_layer(payload), "v30-0827-regression", source.name,
        extract_layout_text(payload), extract_positioned_pages(payload),
    )
    defense = fields["interpretation_meta"]["defense_lines"]
    structured = structure_leopard_defense_line(
        fields["market_path"], fields["core_view"], defense["primary_defense_line"],
    )

    assert fields["candidate_report_date"].isoformat() == "2026-08-27"
    assert fields["interpretation_meta"]["template_version"] == "V3.0"
    assert defense["primary_defense_line"] == 3930.1
    assert "收盘站在3930.1点之上" in (structured.stand_above_condition or "")
    assert "收盘跌回3930.1点下方" in (structured.break_below_condition or "")
    assert "放量验证" in (structured.validation_conditions or "").replace(" ", "")
    records = {item["sector_key"]: item for item in fields["interpretation_meta"]["assessment_records"]}
    assert len(records) == 19
    assert records["medical_biology"]["current_judgement"] == "持有"
    assert records["battery"]["current_judgement"] == "观察"
    assert records["medical_biology"]["main_basis"].startswith("主播明确当前医药波段")
    assert records["agriculture_breeding"]["main_basis"].startswith("主播再次确认种植业/农业/猪肉")
    assert records["securities"]["main_basis"].endswith("只有非常离谱的暴跌才否定。")
    assert all(item["quality_status"] == "verified_structure" for item in records.values())


def test_authoritative_v30_0827_reader_uses_parsed_defense_line(automatic_web) -> None:
    client, settings = automatic_web
    source = Path(__file__).parent / "fixtures" / "authoritative" / "大盘猎豹8月27日直播总结-V3.0版.pdf"
    response = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": (source.name, source.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 201
    assert response.json()["publication"] == "published"

    enhanced = client.get(f"/api/v1/reports/{response.json()['report']['id']}/enhanced")
    assert enhanced.status_code == 200
    defense = enhanced.json()["report_defense"]
    assert defense["defense_line_value"] == 3930.1
    assert defense["defense_line_source"] == "parsed_defense_line"
    assert "收盘站在3930.1点之上" in defense["stand_above_condition"]
    assert "收盘跌回3930.1点下方" in defense["break_below_condition"]
    assert "放量验证" in defense["validation_conditions"].replace(" ", "")
    with create_session_factory(settings.database_url)() as session:
        intraday_now = datetime(2026, 8, 28, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        overlay = intraday_defense_overlay(session, quote={
            "quote_status": "available",
            "quote_datetime": intraday_now.isoformat(),
            "current": "3935.20",
        }, now=intraday_now)
    assert overlay is not None
    assert overlay["trading_date"] == "2026-08-28"
    assert overlay["defense_line_value"] == 3930.1
    assert overlay["source_report_id"] == response.json()["report"]["id"]
    assert overlay["source_report_date"] == "2026-08-27"


def test_authoritative_v30_0827_latest_board_and_sector_detail_have_substantive_parity(automatic_web) -> None:
    client, _ = automatic_web
    source = Path(__file__).parent / "fixtures" / "authoritative" / "大盘猎豹8月27日直播总结-V3.0版.pdf"
    response = client.post(
        "/api/v1/admin/reports/interpret",
        files={"file": (source.name, source.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 201
    report_id = response.json()["report"]["id"]
    assert response.json()["publication"] == "published"

    latest = client.get(f"/api/v1/reports/{report_id}/enhanced").json()
    historical_parents = {"innovative_drug_medicine", "battery_lithium", "photovoltaic_energy_storage"}
    assert not historical_parents & {item["sector_key"] for item in latest["sector_assessments"]}
    latest_facts = {
        item["sector_key"]: item
        for item in latest["sector_assessments"]
        if item["explicitly_mentioned"]
    }
    assert len(latest_facts) == 19
    assert {"medical_biology", "battery"} <= set(latest_facts)
    assert not {"innovative_drug_medicine", "battery_lithium"} & set(latest_facts)
    assert "医药" not in latest_facts["agriculture_breeding"]["main_basis"]
    assert "医药" not in latest_facts["securities"]["main_basis"]
    board_rows = client.get("/api/v1/sectors?include_low_attention=true&page_size=100").json()
    board_keys = {item["sector_key"] for item in board_rows}
    assert len(board_keys) == 71
    assert not historical_parents & board_keys
    for parent_key in historical_parents:
        assert client.get(f"/api/v1/sectors/{parent_key}").status_code == 404
        assert client.get(f"/api/v1/sectors/{parent_key}/research").status_code == 404
    matrix_keys = {
        item["sector_key"]
        for item in client.get(f"/api/v1/reports/{report_id}/path-matrix?periods=20").json()["rows"]
    }
    assert not historical_parents & matrix_keys
    assert {"innovative_drug", "medical_biology", "battery", "lithium_battery", "photovoltaic", "energy_storage"} <= matrix_keys
    board_facts = {
        item["sector_key"]: item
        for item in client.get("/api/v1/sectors").json()
        if item["latest_view_report_id"] == report_id
    }
    assert set(board_facts) == set(latest_facts)

    substantive_fields = (
        "current_path_status", "current_judgement", "main_basis",
        "observation_condition", "source_text_reference", "source_page",
    )
    for sector_key, latest_fact in latest_facts.items():
        board = board_facts[sector_key]
        board_fact = board["latest_explicit_view"]
        assert board["latest_view_date"] == board_fact["report_date"] == "2026-08-27"
        assert board_fact["report_id"] == report_id
        assert board_fact["path"]["path_status"] == latest_fact["current_path_status"]
        assert {key: board_fact["assessment"][key] for key in substantive_fields} == {
            key: latest_fact[key] for key in substantive_fields
        }

        detail_fact = client.get(f"/api/v1/sectors/{sector_key}/research").json()["latest_explicit_view"]
        assert detail_fact["report_id"] == report_id
        assert detail_fact["report_date"] == "2026-08-27"
        assert detail_fact["path"]["path_status"] == latest_fact["current_path_status"]
        assert {key: detail_fact["assessment"][key] for key in substantive_fields} == {
            key: latest_fact[key] for key in substantive_fields
        }


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
        for report_date, expected in {
            "2026-08-10": {
                "semiconductor": "hold", "cpo": "hold", "pcb": "hold",
                "electronic_components": "hold", "consumer_electronics": "hold",
                "communication_equipment": "hold",
            },
            "2026-08-11": {
                "semiconductor": "hold", "cpo": "hold", "electronic_components": "hold",
                "consumer_electronics": "hold", "computing_power_rental": "hold",
            },
        }.items():
            report = session.scalar(select(Report).where(Report.report_date == date.fromisoformat(report_date)))
            assert report is not None
            assert "历史核对" not in report.market_path
            for sector_key, expected_status in expected.items():
                assessment = session.scalar(select(SectorAssessment).where(
                    SectorAssessment.report_id == report.id, SectorAssessment.sector_key == sector_key,
                ))
                entry = session.scalar(select(SectorPathEntry).where(
                    SectorPathEntry.report_id == report.id, SectorPathEntry.sector_key == sector_key,
                ))
                assert assessment is not None and entry is not None
                assert assessment.current_path_status == entry.path_status == expected_status
                assert assessment.explicitly_mentioned is entry.explicitly_mentioned is True


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
    assert freshness["security_coverage"] == {"through_expected": 0, "required": len(market_core_security_symbols())}
    assert freshness["broad"] == {"through_expected": 0, "required": 4}
    assert freshness["market_core"]["through_expected"] == 0
    assert freshness["market_core"]["required"] == len(market_core_security_symbols()) + 1
    assert freshness["last_daily_advance"] is None
    assert freshness["last_reconciliation"] is None
    assert freshness["next_scheduled"] is not None
