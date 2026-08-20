"""Read-only composition exports for the fixed Reader security universe.

The audit intentionally consumes the same versioned registry as Market Core.
It is never a runtime selection input and cannot mutate configured mappings.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
import json
from typing import Iterable

from .config import CONFIG_DIR
from .report_registry import load_report_registry
from .security_proxy_observation import APPROVED, SecurityProxyDefinition, SecurityProxyInstrument, load_security_proxy_registry


MAPPING_REVIEW_PATH = CONFIG_DIR / "security_proxy_mapping_review_v1.json"


DETAIL_COLUMNS = (
    "level1_group", "sector_key", "sector_name", "sector_status", "security_role", "security_name", "human_code",
    "provider_symbol", "security_type", "is_primary", "show_in_matrix_current", "show_in_sector_detail", "mapping_source",
    "mapping_origin", "tencent_status", "historical_status", "latest_completed_date", "mapping_note", "role_inferred",
)
SUMMARY_COLUMNS = (
    "level1_group", "sector_key", "sector_name", "ETF_count", "stock_count", "total_security_count", "primary_security",
    "primary_code", "matrix_current_primary", "matrix_current_stock", "all_ETFs", "all_stocks", "all_codes", "composition_pattern", "market_ready",
)
REUSE_COLUMNS = ("security_name", "human_code", "security_type", "used_by_sector_count", "used_by_sectors", "roles")

REUSE_REVIEW_NOTES = {
    "sh515880": "合理：仅用于通信设备、CPO和光纤题材；通信服务已改用电信ETF。",
    "sz300750": "合理：锂电池增加锂电池ETF后，宁德时代只作为共同的代表公司。",
    "sh600547": "合理：贵金属增加兴业银锡后，山东黄金不再是唯一观察标的。",
    "sz159766": "合理：酒店餐饮增加锦江酒店后，旅游ETF仅保留部分旅游覆盖。",
    "sz002475": "需持续人工审核：元器件与消费电子存在供应链交集。",
    "sz300274": "合理：储能增加储能电池ETF后，阳光电源仅作为共同的代表公司。",
}


def _origin(definition: SecurityProxyDefinition) -> str:
    if definition.version == "1.2.0":
        return "M3.18 manual_registry_review"
    return "M3.14 newly_added" if definition.version == "1.1.0" else "existing"


def _role(item: SecurityProxyInstrument, definition: SecurityProxyDefinition) -> str:
    primary = item.symbol == definition.primary_observation_symbol
    return f"{'PRIMARY' if primary else 'RELATED'}_{'ETF' if item.proxy_role == 'etf' else 'STOCK'}"


def _matrix_stock(definition: SecurityProxyDefinition) -> SecurityProxyInstrument | None:
    primary = definition.primary_observation
    if primary is not None and primary.proxy_role == "leader":
        return primary
    return next((item for item in definition.leader_proxies if item.enabled), None)


def build_composition_audit(*, latest_completed_date: str, tencent_status: str = "ready", historical_status: str = "ready") -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Return active-only detail, summary, and reuse rows without network I/O."""
    definitions = {item.market_path_key: item for item in load_security_proxy_registry()}
    details: list[dict[str, str]] = []
    summaries: list[dict[str, str]] = []
    reuse: dict[str, list[dict[str, str]]] = defaultdict(list)
    active = [item for item in load_report_registry() if item.lifecycle == "active"]
    for report_object in active:
        definition = definitions[report_object.sector_key]
        primary = definition.primary_observation
        matrix_stock = _matrix_stock(definition)
        instruments = tuple(item for item in definition.instruments if item.enabled)
        for item in instruments:
            row = {
                "level1_group": report_object.group_name,
                "sector_key": report_object.sector_key,
                "sector_name": report_object.sector_name,
                "sector_status": "ready" if definition.status == APPROVED else "unavailable",
                "security_role": _role(item, definition),
                "security_name": item.security_name,
                "human_code": item.reader_code,
                "provider_symbol": item.symbol,
                "security_type": "ETF" if item.proxy_role == "etf" else "STOCK",
                "is_primary": str(item is primary).lower(),
                "show_in_matrix_current": str(item is primary or item is matrix_stock).lower(),
                "show_in_sector_detail": "true",
                "mapping_source": "config/security_proxy_registry_v1.json",
                "mapping_origin": _origin(definition),
                "tencent_status": tencent_status if definition.status == APPROVED else "unavailable",
                "historical_status": historical_status if definition.status == APPROVED else "unavailable",
                "latest_completed_date": latest_completed_date if definition.status == APPROVED else "—",
                "mapping_note": item.rationale,
                "role_inferred": "false",
            }
            details.append(row)
            reuse[item.symbol].append(row)
        etfs = [item for item in instruments if item.proxy_role == "etf"]
        stocks = [item for item in instruments if item.proxy_role == "leader"]
        if definition.status != APPROVED:
            pattern = "UNAVAILABLE"
        elif etfs and stocks:
            pattern = "ETF_PLUS_STOCKS"
        elif etfs:
            pattern = "ETF_ONLY"
        elif len(stocks) > 1:
            pattern = "MULTI_STOCK"
        else:
            pattern = "STOCK_ONLY"
        summaries.append({
            "level1_group": report_object.group_name,
            "sector_key": report_object.sector_key,
            "sector_name": report_object.sector_name,
            "ETF_count": str(len(etfs)), "stock_count": str(len(stocks)), "total_security_count": str(len(instruments)),
            "primary_security": primary.security_name if primary else "—",
            "primary_code": primary.reader_code if primary else "—",
            "matrix_current_primary": primary.reader_code if primary else "—",
            "matrix_current_stock": matrix_stock.reader_code if matrix_stock and matrix_stock is not primary else "—",
            "all_ETFs": " | ".join(item.security_name for item in etfs) or "—",
            "all_stocks": " | ".join(item.security_name for item in stocks) or "—",
            "all_codes": " | ".join(item.reader_code for item in instruments) or "—",
            "composition_pattern": pattern,
            "market_ready": str(definition.status == APPROVED).lower(),
        })
    reuse_rows = []
    for items in sorted(reuse.values(), key=lambda value: (-len({item['sector_key'] for item in value}), value[0]["security_name"])):
        sample = items[0]
        reuse_rows.append({
            "security_name": sample["security_name"], "human_code": sample["human_code"], "security_type": sample["security_type"],
            "used_by_sector_count": str(len({item["sector_key"] for item in items})),
            "used_by_sectors": " | ".join(sorted({item["sector_name"] for item in items})),
            "roles": " | ".join(sorted({item["security_role"] for item in items})),
        })
    if len(summaries) != 71:
        raise ValueError("composition audit requires exactly 71 active report objects")
    return details, summaries, reuse_rows


def write_csv(path: Path, columns: tuple[str, ...], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_composition_audit(output_dir: Path, *, latest_completed_date: str, tencent_status: str = "ready", historical_status: str = "ready") -> tuple[Path, Path, Path]:
    details, summaries, reuse = build_composition_audit(
        latest_completed_date=latest_completed_date,
        tencent_status=tencent_status,
        historical_status=historical_status,
    )
    paths = (
        output_dir / "sector_security_composition_audit.csv",
        output_dir / "sector_security_composition_summary.csv",
        output_dir / "security_reuse_audit.csv",
    )
    write_csv(paths[0], DETAIL_COLUMNS, details)
    write_csv(paths[1], SUMMARY_COLUMNS, summaries)
    write_csv(paths[2], REUSE_COLUMNS, reuse)
    return paths


def write_mapping_review_summary(output: Path, *, latest_completed_date: str) -> Path:
    """Write a human-readable, config-backed record of manual mapping review.

    It reports facts from the versioned fixed registry only.  No market
    provider, database, or automatic selection path is involved.
    """

    details, summaries, reuse = build_composition_audit(latest_completed_date=latest_completed_date)
    review = json.loads(MAPPING_REVIEW_PATH.read_text(encoding="utf-8"))
    active_keys = {item["sector_key"] for item in summaries}
    changes = list(review.get("changes", []))
    if not changes or any(item.get("sector_key") not in active_keys for item in changes):
        raise ValueError("mapping review must describe active registry sectors")
    summary_by_pattern: dict[str, list[str]] = defaultdict(list)
    for item in summaries:
        summary_by_pattern[item["composition_pattern"]].append(item["sector_name"])
    lines = [
        "# 固定证券映射人工维护汇总",
        "",
        f"- 生效日期：{review.get('effective_date')}",
        f"- 最新完整交易日：{latest_completed_date}",
        "- 口径：仅人工维护的固定 registry；不包含 PDF 自动拆分、动态选标或自动替换。",
        "",
        "## 本轮修改",
        "",
    ]
    for item in changes:
        lines.extend((
            f"### {item['sector_name']}",
            f"- 修改前：{item['before']}",
            f"- 修改后：{item['after']}",
            f"- 原因：{item['reason']}",
            "",
        ))
    lines.extend((
        "## 当前组合形态",
        "",
        f"- ETF_ONLY（{len(summary_by_pattern['ETF_ONLY'])}）：{'、'.join(summary_by_pattern['ETF_ONLY']) or '—'}",
        f"- STOCK_ONLY（{len(summary_by_pattern['STOCK_ONLY'])}）：{'、'.join(summary_by_pattern['STOCK_ONLY']) or '—'}",
        f"- MULTI_STOCK（{len(summary_by_pattern['MULTI_STOCK'])}）：{'、'.join(summary_by_pattern['MULTI_STOCK']) or '—'}",
        f"- ETF_PLUS_STOCKS（{len(summary_by_pattern['ETF_PLUS_STOCKS'])}）：{'、'.join(summary_by_pattern['ETF_PLUS_STOCKS']) or '—'}",
        f"- UNAVAILABLE（{len(summary_by_pattern['UNAVAILABLE'])}）：{'、'.join(summary_by_pattern['UNAVAILABLE']) or '—'}",
        "",
        "## 复用证券（事实）",
        "",
    ))
    for item in reuse:
        count = int(item["used_by_sector_count"])
        if count > 1:
            provider_symbol = next(
                detail["provider_symbol"]
                for detail in details
                if detail["human_code"] == item["human_code"]
            )
            note = REUSE_REVIEW_NOTES.get(provider_symbol, "需持续人工审核：当前 registry 未设置自动替换规则。")
            lines.append(
                f"- {item['security_name']} · {item['human_code']}：{count} 个板块（{item['used_by_sectors']}）。{note}"
            )
    lines.extend((
        "说明：复用结论来自本次版本化人工审核；不构成运行时自动选标或自动替换规则。",
        f"配置组合明细：{len(details)} 条证券记录 / {len(summaries)} 个 active sector。",
        "",
    ))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return output
