"""Generate a review-only audit for fixed primary market observations.

The audit derives identity and semantic caveats from the versioned registry.
It is not a runtime selection input and cannot change a configured mapping.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from leopard_project.report_registry import load_report_registry
from leopard_project.security_proxy_observation import APPROVED, SecurityProxyDefinition, SecurityProxyInstrument, load_security_proxy_registry


CSV_COLUMNS = (
    "一级分类", "sector_key", "板块中文名", "primary security name", "human code", "type",
    "mapping origin", "Market status", "Tencent", "Sina historical", "latest completed date",
    "mapping rationale", "confidence", "possible alternative", "review flag",
)


@dataclass(frozen=True)
class PrimaryObservationAuditRow:
    一级分类: str
    sector_key: str
    板块中文名: str
    primary_security_name: str
    human_code: str
    type: str
    mapping_origin: str
    market_status: str
    tencent: str
    sina_historical: str
    latest_completed_date: str
    mapping_rationale: str
    confidence: str
    possible_alternative: str
    review_flag: str

    def as_csv_row(self) -> dict[str, str]:
        values = asdict(self)
        return dict(zip(CSV_COLUMNS, (str(values[_field_name(column)]) for column in CSV_COLUMNS), strict=True))


def _field_name(column: str) -> str:
    return {
        "一级分类": "一级分类", "sector_key": "sector_key", "板块中文名": "板块中文名",
        "primary security name": "primary_security_name", "human code": "human_code", "type": "type",
        "mapping origin": "mapping_origin", "Market status": "market_status", "Tencent": "tencent",
        "Sina historical": "sina_historical", "latest completed date": "latest_completed_date",
        "mapping rationale": "mapping_rationale", "confidence": "confidence",
        "possible alternative": "possible_alternative", "review flag": "review_flag",
    }[column]


def _origin(definition: SecurityProxyDefinition) -> str:
    if definition.version == "1.2.0":
        return "M3.18 manual_registry_review"
    return "M3.14 newly_added" if definition.version == "1.1.0" else "existing"


def _rationale(definition: SecurityProxyDefinition, primary: SecurityProxyInstrument) -> str:
    risk = definition.semantic_risks[0] if definition.semantic_risks else "不代表完整板块"
    if primary.proxy_role == "etf":
        return f"{primary.rationale}；以固定{primary.security_name}观察{definition.display_name}相关产业链，{risk}。"
    return f"{primary.rationale}；{primary.security_name}与{definition.display_name}业务关联度较高，作为固定核心公司观察，{risk}。"


def _unavailable_rationale(definition: SecurityProxyDefinition) -> str:
    risk = definition.semantic_risks[0] if definition.semantic_risks else "未确认可靠主观察标的"
    return f"当前保持不可用：{risk}。"


def build_primary_observation_audit(
    *,
    latest_completed_date: str,
    tencent_result: str = "pass",
    sina_historical_result: str = "pass",
) -> tuple[PrimaryObservationAuditRow, ...]:
    """Build the active-only audit without mutating either source registry."""
    definitions = {item.market_path_key: item for item in load_security_proxy_registry()}
    rows: list[PrimaryObservationAuditRow] = []
    for report_object in (item for item in load_report_registry() if item.lifecycle == "active"):
        definition = definitions[report_object.sector_key]
        primary = definition.primary_observation
        if definition.status != APPROVED or primary is None:
            rows.append(PrimaryObservationAuditRow(
                report_object.group_name, report_object.sector_key, report_object.sector_name,
                "—", "—", "UNAVAILABLE", _origin(definition), "unavailable", "fail", "fail", "—",
                _unavailable_rationale(definition), "low", "—", "OK",
            ))
            continue
        is_direct = primary.coverage_type == "direct_or_close"
        rows.append(PrimaryObservationAuditRow(
            report_object.group_name, report_object.sector_key, report_object.sector_name,
            primary.security_name, primary.reader_code, "ETF" if primary.proxy_role == "etf" else "STOCK",
            _origin(definition), "ready", tencent_result, sina_historical_result, latest_completed_date,
            _rationale(definition, primary), "high" if is_direct else "medium", "—",
            "OK" if is_direct else "NEEDS_HUMAN_REVIEW",
        ))
    return tuple(rows)


def write_primary_observation_audit(path: Path, rows: Iterable[PrimaryObservationAuditRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(row.as_csv_row() for row in rows)
