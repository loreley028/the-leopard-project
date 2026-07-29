from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

from leopard_project.config import load_seed_bundle


def configured_groups() -> list[dict[str, Any]]:
    """Return groups in the versioned catalog order used by every Viewer surface."""
    sectors = load_seed_bundle().sectors
    names = {item.group_order: item.category_level_1 for item in sectors}
    return [
        {
            "group_order": group_order,
            "group_name": names[group_order],
            "sector_count": sum(item.group_order == group_order for item in sectors),
        }
        for group_order in sorted(names)
    ]


def configured_catalog(version: str = "v2.3", valid_from: date = date(2026, 6, 9)) -> dict[str, Any]:
    entries = [
        {
            "sector_key": item.sector_key,
            "display_name": item.sector_name,
            "group_key": item.category_level_1,
            "display_order": item.overall_order,
            "aliases": [],
            "valid_from": valid_from.isoformat(),
            "valid_to": None,
            "support_status": "unsupported" if item.sector_key == "hang_seng_tech" else "supported",
            "catalog_version": version,
        }
        for item in sorted(load_seed_bundle().sectors, key=lambda value: value.overall_order)
    ]
    return {"catalog_version": version, "valid_from": valid_from.isoformat(), "entries": entries}


def add_catalog_entry(catalog: dict[str, Any], entry: dict[str, Any], *, new_version: str, valid_from: date) -> dict[str, Any]:
    if any(item["sector_key"] == entry["sector_key"] for item in catalog["entries"]):
        raise ValueError("sector_key already exists")
    output = deepcopy(catalog)
    output["catalog_version"] = new_version
    output["valid_from"] = valid_from.isoformat()
    output["entries"].append({
        **entry,
        "catalog_version": new_version,
        "valid_from": valid_from.isoformat(),
        "valid_to": None,
    })
    return output
