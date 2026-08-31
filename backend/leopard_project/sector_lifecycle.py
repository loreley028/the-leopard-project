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


def lifecycle_split_for_child(sector_key: str) -> SectorLifecycleSplit | None:
    return next((item for item in load_sector_lifecycle_splits() if sector_key in item.child_sector_keys), None)


def lifecycle_role_on_report_date(
    sector_key: str,
    report_date: date | None,
    *,
    splits: tuple[SectorLifecycleSplit, ...] | None = None,
) -> str:
    """Resolve a report object's role without transferring facts across objects.

    A split parent is valid only before the configured effective date.  Each
    child becomes independently valid on that date.  With no historical date,
    the result describes the current catalogue.
    """
    configured = splits if splits is not None else load_sector_lifecycle_splits()
    parent = next((item for item in configured if item.parent_sector_key == sector_key), None)
    if parent is not None:
        if report_date is not None and report_date < parent.effective_report_date:
            return "active"
        return "historical_only"
    child = next((item for item in configured if sector_key in item.child_sector_keys), None)
    if child is not None and report_date is not None and report_date < child.effective_report_date:
        return "not_yet_active"
    return "active"


def is_active_report_object_on(
    sector_key: str,
    report_date: date | None,
    *,
    splits: tuple[SectorLifecycleSplit, ...] | None = None,
) -> bool:
    return lifecycle_role_on_report_date(sector_key, report_date, splits=splits) == "active"
