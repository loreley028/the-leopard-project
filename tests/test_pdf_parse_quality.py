from __future__ import annotations

from leopard_project.web.services import (
    _assessment_quality,
    _parse_positioned_assessments,
    _validate_assessment_set,
)


def assessment(**changes):
    value = {
        "sector_key": "insurance",
        "sector_name": "保险",
        "recent_path_summary": "7/1观察到7/22持有",
        "current_judgement": "持有",
        "main_basis": "资金状态偏强，板块保持承接。",
        "observation_condition": "若资金明确离场则调整。",
        "source_page": 6,
        "source_text_start": 120,
        "source_text_end": 220,
    }
    value.update(changes)
    return value


def test_complete_evidence_row_is_verified() -> None:
    quality, confidence, flags = _assessment_quality(assessment())
    assert (quality, confidence, flags) == ("verified_structure", "high", [])


def test_multiple_neighbor_sector_names_are_blocking_row_bleed() -> None:
    quality, confidence, flags = _assessment_quality(assessment(
        main_basis="保险保持承接，石油石化走弱，贵金属继续持有，酒店餐饮等待观察。",
    ))
    assert quality == "blocking_parse_error"
    assert confidence == "low"
    assert "multiple_other_sector_names" in flags


def test_missing_source_evidence_cannot_be_marked_verified() -> None:
    quality, confidence, flags = _assessment_quality(assessment(source_page=None, source_text_start=None, source_text_end=None))
    assert quality == "needs_attention"
    assert confidence == "medium"
    assert {"missing_source_page", "missing_source_range"} <= set(flags)


def test_abnormal_status_density_and_outlier_length_are_blocking() -> None:
    quality, _, flags = _assessment_quality(assessment(
        main_basis=("不碰 强观 观察 弱观 转持 持有 转弱 离场 未提 " * 30),
    ))
    assert quality == "blocking_parse_error"
    assert {"abnormal_status_sequence", "field_length_outlier"} <= set(flags)


def test_adjacent_duplicate_content_requires_attention() -> None:
    repeated = "量价结构仍需等待进一步确认，只有完整收盘数据满足既定条件后才继续跟踪该方向，同时严格执行既有风险边界。"
    first = {**assessment(main_basis=repeated), "path_status": "hold", "quality_status": "verified_structure", "confidence": "high", "validation_flags": []}
    second = {**assessment(sector_key="bank", sector_name="银行", main_basis=repeated), "path_status": "watch", "quality_status": "verified_structure", "confidence": "high", "validation_flags": []}
    checked = _validate_assessment_set([first, second])
    assert all(item["quality_status"] == "needs_attention" for item in checked)
    assert all("adjacent_content_highly_repeated" in item["validation_flags"] for item in checked)


def _item(x: float, y: float, text: str, size: float = 6.5) -> dict:
    return {"x": x, "y": y, "text": text, "font_size": size}


def _v24_header(y: float) -> list[dict]:
    return [
        _item(80, y, "板块"), _item(160, y, "历史路径（"), _item(205, y, "最近转折）"),
        _item(284, y, "7/27"), _item(299, y, "判断"),
        _item(390, y, "主"), _item(397, y, "要依据"),
        _item(496, y, "观察"), _item(509, y, "条件"),
    ]


def test_v24_split_headers_cross_page_and_explicit_status_cell_wins() -> None:
    page6 = _v24_header(740) + [
        _item(36, 710, "创新药/医药", 7),
        _item(142, 710, "7/26 强观 → 7/27 持有"),
        _item(291, 710, "持有", 7),
        _item(353, 710, "风险复核后恢复；辅助文本含观察但不改写状态。"),
        _item(458, 710, "若转弱再调整。"),
    ]
    page7 = _v24_header(797) + [
        _item(36, 760, "半导体", 7),
        _item(142, 760, "7/26 不碰 → 7/27 观察"),
        _item(291, 760, "观察", 7),
        _item(353, 760, "修复后继续确认。"),
        _item(458, 760, "等待连续资金。"),
        # B3 prose contains a sector name but has no judgement cell.
        _item(36, 330, "钢铁、玻璃玻纤本场未更新。", 7),
    ]
    records = _parse_positioned_assessments([
        {"page": 6, "items": page6},
        {"page": 7, "items": page7},
    ])
    assert [(item["sector_name"], item["path_status"]) for item in records] == [
        ("半导体", "watch"),
        ("创新药/医药", "hold"),
    ]
    assert all(item["quality_status"] == "verified_structure" for item in records)
