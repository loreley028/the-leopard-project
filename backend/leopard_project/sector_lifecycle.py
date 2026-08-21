"""Versioned Reader lifecycle rules for manually maintained report topics."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from leopard_project.config import CONFIG_DIR


@dataclass(frozen=True)
class SectorLifecycleSplit:
    parent_sector_key: str
    child_sector_keys: tuple[str, ...]
    effective_report_date: date


@lru_cache(maxsize=1)
def load_sector_lifecycle_splits() -> tuple[SectorLifecycleSplit, ...]:
    document = json.loads((CONFIG_DIR / "report_sector_lifecycle_v1.json").read_text(encoding="utf-8"))
    return tuple(SectorLifecycleSplit(
        parent_sector_key=str(item["parent_sector_key"]),
        child_sector_keys=tuple(str(key) for key in item["child_sector_keys"]),
        effective_report_date=date.fromisoformat(str(item["effective_report_date"])),
    ) for item in document["splits"])


def parent_status_lineage_for_child(sector_key: str) -> SectorLifecycleSplit | None:
    return next((item for item in load_sector_lifecycle_splits() if sector_key in item.child_sector_keys), None)
