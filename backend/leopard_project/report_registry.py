from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from leopard_project.config import CONFIG_DIR, load_seed_bundle


@dataclass(frozen=True)
class ReportObject:
    sector_key: str
    sector_name: str
    group_name: str
    group_order: int
    within_group_order: int
    display_order: int
    lifecycle: str
    market_sector_key: str | None


@lru_cache(maxsize=1)
def load_report_registry() -> tuple[ReportObject, ...]:
    """Return the V2.9 Report universe without coupling it to market support."""
    document = json.loads((CONFIG_DIR / "v29_report_registry_v1.json").read_text(encoding="utf-8"))
    carry = set(document["historical_carry_sector_keys"])
    base = sorted(load_seed_bundle().sectors, key=lambda item: item.overall_order)
    objects = [
        ReportObject(
            sector_key=item.sector_key,
            sector_name=item.sector_name,
            group_name=item.category_level_1,
            group_order=item.group_order,
            within_group_order=item.within_group_order,
            display_order=item.overall_order,
            lifecycle="historical_carry" if item.sector_key in carry else "active",
            market_sector_key=item.sector_key,
        )
        for item in base
    ]
    offset = len(objects)
    objects.extend(
        ReportObject(
            sector_key=str(item["sector_key"]),
            sector_name=str(item["display_name"]),
            group_name=str(item["group_name"]),
            group_order=int(item["group_order"]),
            within_group_order=int(item["within_group_order"]),
            display_order=offset + index,
            lifecycle="active",
            market_sector_key=None,
        )
        for index, item in enumerate(document["supplemental_rows"], start=1)
    )
    if len(objects) != int(document["display_row_count"]):
        raise ValueError("V2.9 Report display registry count mismatch")
    if sum(item.lifecycle == "active" for item in objects) != int(document["active_object_count"]):
        raise ValueError("V2.9 Report active registry count mismatch")
    return tuple(sorted(objects, key=lambda item: (item.group_order, item.within_group_order, item.display_order)))


def report_object_by_key() -> dict[str, ReportObject]:
    return {item.sector_key: item for item in load_report_registry()}


def report_object_by_name() -> dict[str, ReportObject]:
    return {item.sector_name: item for item in load_report_registry()}


def reader_report_registry() -> tuple[ReportObject, ...]:
    """Return the active Reader universe without deleting audit-only parents."""
    return tuple(item for item in load_report_registry() if item.lifecycle == "active")
