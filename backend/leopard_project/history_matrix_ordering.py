"""Versioned manual Reader ordering for the history matrix.

The order is an editorial presentation decision only.  It never consumes
market prices, report text, recency scores, or live attention signals.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Protocol

from .config import CONFIG_DIR


ORDERING_CONFIG_PATH = CONFIG_DIR / "history_matrix_order_v1.json"
AUDIT_COLUMNS = ("group_key", "group_name", "sector_key", "sector_name", "manual_order", "rationale_short")


class _ReportObject(Protocol):
    sector_key: str
    sector_name: str
    group_name: str
    group_order: int
    lifecycle: str


@dataclass(frozen=True)
class ManualHistoryMatrixOrder:
    group_order: int
    group_name: str
    sector_key: str
    manual_order: int
    rationale_short: str


@lru_cache(maxsize=1)
def load_history_matrix_ordering() -> tuple[ManualHistoryMatrixOrder, ...]:
    document = json.loads(ORDERING_CONFIG_PATH.read_text(encoding="utf-8"))
    if document.get("ordering_mode") != "manual_static":
        raise ValueError("history matrix ordering must remain manual_static")
    rows: list[ManualHistoryMatrixOrder] = []
    for group in document.get("groups", []):
        group_order = int(group["group_order"])
        group_name = str(group["group_name"])
        for manual_order, sector in enumerate(group.get("sectors", []), start=1):
            rows.append(ManualHistoryMatrixOrder(
                group_order=group_order,
                group_name=group_name,
                sector_key=str(sector["sector_key"]),
                manual_order=manual_order,
                rationale_short=str(sector["rationale_short"]),
            ))
    if not rows or len({item.sector_key for item in rows}) != len(rows):
        raise ValueError("history matrix ordering must contain unique sector keys")
    return tuple(rows)


def apply_history_matrix_order(items: Iterable[_ReportObject]) -> tuple[_ReportObject, ...]:
    """Return active Reader objects in the configured static order."""

    active = tuple(item for item in items if item.lifecycle == "active")
    configured = load_history_matrix_ordering()
    configured_by_key = {item.sector_key: item for item in configured}
    active_keys = {item.sector_key for item in active}
    if active_keys != set(configured_by_key):
        missing = sorted(active_keys - set(configured_by_key))
        unknown = sorted(set(configured_by_key) - active_keys)
        raise ValueError(f"history matrix ordering mismatch: missing={missing}, unknown={unknown}")
    ordered = []
    for item in active:
        configured_item = configured_by_key[item.sector_key]
        if (item.group_order, item.group_name) != (configured_item.group_order, configured_item.group_name):
            raise ValueError(f"history matrix group mismatch for {item.sector_key}")
        ordered.append(replace(item, within_group_order=configured_item.manual_order, display_order=configured_item.group_order * 100 + configured_item.manual_order))
    return tuple(sorted(ordered, key=lambda item: (item.group_order, item.within_group_order, item.display_order)))


def write_history_matrix_order_review(output: Path, items: Iterable[_ReportObject]) -> Path:
    """Export the exact static order used by the Reader; no runtime data is read."""

    configured = {item.sector_key: item for item in load_history_matrix_ordering()}
    ordered = apply_history_matrix_order(items)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        for item in ordered:
            order = configured[item.sector_key]
            writer.writerow({
                "group_key": str(order.group_order),
                "group_name": order.group_name,
                "sector_key": item.sector_key,
                "sector_name": item.sector_name,
                "manual_order": order.manual_order,
                "rationale_short": order.rationale_short,
            })
    return output
