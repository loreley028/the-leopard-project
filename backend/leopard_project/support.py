from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from .config import CONFIG_DIR, load_seed_bundle
from .models import DataStatus, Market, SupportStatus


SUPPORT_POLICY_PATH = CONFIG_DIR / "system_support_policy_v1.json"


class UnsupportedSector(BaseModel):
    model_config = ConfigDict(frozen=True)
    sector_key: str
    sector_name: str
    canonical_symbol: str
    market: Market
    support_status: SupportStatus
    data_status: DataStatus
    reason_code: str
    display_text: str
    display_detail: str
    exclude_from: tuple[str, ...]


class CollectionTask(BaseModel):
    model_config = ConfigDict(frozen=True)
    sector_key: str
    sector_name: str
    market: Market
    mapping_type: str
    provider_symbols: tuple[str, ...]
    data_status: DataStatus


class CollectionPlan(BaseModel):
    model_config = ConfigDict(frozen=True)
    policy_version: str
    trade_date: date
    total_business_sectors: int
    supported_market_sectors: int
    collection_denominator: int
    tasks: tuple[CollectionTask, ...]
    unsupported_sectors: tuple[UnsupportedSector, ...]


def load_support_policy(path: Path = SUPPORT_POLICY_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_support_policy(policy: dict[str, object] | None = None) -> None:
    policy = policy or load_support_policy()
    unsupported = tuple(UnsupportedSector(**row) for row in policy["unsupported_sectors"])  # type: ignore[arg-type]
    allowed = set(policy["allowed_provider_roles"])  # type: ignore[arg-type]
    roles = set(policy["provider_roles"].values())  # type: ignore[union-attr]
    if policy["total_business_sectors"] != 66:
        raise ValueError("business catalog must contain 66 sectors")
    if policy["supported_market_sectors"] != 65 or policy["collection_denominator"] != 65:
        raise ValueError("automatic market-data support and denominator must both be 65")
    if len(unsupported) != 1 or unsupported[0].sector_key != "hang_seng_tech":
        raise ValueError("HSTECH must be the sole explicitly unsupported sector")
    if unsupported[0].support_status != SupportStatus.UNSUPPORTED or unsupported[0].data_status != DataStatus.UNSUPPORTED:
        raise ValueError("unsupported support and data states must be explicit")
    if not roles <= allowed or "production_primary" in roles or "production_fallback" in roles:
        raise ValueError("provider roles exceed the Phase 1B-0 allow-list")
    if policy["production_primary_approved"] or policy["production_fallback_approved"]:
        raise ValueError("no production provider role is approved")


def _custom_components() -> dict[str, tuple[str, ...]]:
    document = json.loads((CONFIG_DIR / "custom_compositions_v2_3.json").read_text(encoding="utf-8"))
    result: dict[str, tuple[str, ...]] = {}
    for row in document["compositions"]:
        if row["symbol"] == "CUSTOM_HOTEL_CATERING":
            result[row["symbol"]] = ("881160",)
        else:
            result[row["symbol"]] = tuple(component["symbol"] for component in row["components"])
    return result


def build_collection_plan(trade_date: date, policy: dict[str, object] | None = None) -> CollectionPlan:
    policy = policy or load_support_policy()
    validate_support_policy(policy)
    bundle = load_seed_bundle()
    unsupported_rows = tuple(UnsupportedSector(**row) for row in policy["unsupported_sectors"])  # type: ignore[arg-type]
    unsupported_keys = {row.sector_key for row in unsupported_rows}
    mappings = {mapping.sector_key: mapping for mapping in bundle.mappings}
    custom = _custom_components()
    tasks: list[CollectionTask] = []
    for sector in sorted(bundle.sectors, key=lambda item: item.overall_order):
        if sector.sector_key in unsupported_keys:
            continue
        mapping = mappings[sector.sector_key]
        if mapping.primary_symbol == "CUSTOM_HOTEL_CATERING":
            mapping_type, status = "proxy", DataStatus.PROXY
        elif mapping.primary_symbol.startswith("CUSTOM_"):
            mapping_type, status = "custom_composite", DataStatus.NORMAL
        elif mapping.sector_key == "glass_substrate":
            mapping_type, status = "direct", DataStatus.SHORT_HISTORY
        else:
            mapping_type, status = "direct", DataStatus.NORMAL
        symbols = custom.get(mapping.primary_symbol, (mapping.primary_symbol,))
        tasks.append(CollectionTask(
            sector_key=sector.sector_key,
            sector_name=sector.sector_name,
            market=Market.CN_A,
            mapping_type=mapping_type,
            provider_symbols=symbols,
            data_status=status,
        ))
    expected = int(policy["supported_market_sectors"])
    if len(tasks) != expected or len({task.sector_key for task in tasks}) != expected:
        raise ValueError(f"collection plan must contain exactly {expected} unique supported sectors")
    if any(task.market != Market.CN_A or "HS2083" in task.provider_symbols or "HSTECH" in task.provider_symbols for task in tasks):
        raise ValueError("unsupported cross-market symbols must not generate provider requests")
    return CollectionPlan(
        policy_version=str(policy["policy_version"]), trade_date=trade_date,
        total_business_sectors=int(policy["total_business_sectors"]),
        supported_market_sectors=expected, collection_denominator=int(policy["collection_denominator"]),
        tasks=tuple(tasks), unsupported_sectors=unsupported_rows,
    )


def collection_success_rate(success_count: int, plan: CollectionPlan) -> Decimal:
    if not 0 <= success_count <= plan.collection_denominator:
        raise ValueError("success_count must be within the collection denominator")
    return Decimal(success_count) / Decimal(plan.collection_denominator)


def supported_indicator_keys(plan: CollectionPlan) -> tuple[str, ...]:
    return tuple(task.sector_key for task in plan.tasks)


def ranking_keys(plan: CollectionPlan, *, require_full_history: bool = False) -> tuple[str, ...]:
    return tuple(
        task.sector_key for task in plan.tasks
        if not require_full_history or task.data_status != DataStatus.SHORT_HISTORY
    )


def failure_alert_keys(failed_sector_keys: Iterable[str], plan: CollectionPlan) -> tuple[str, ...]:
    supported = set(supported_indicator_keys(plan))
    return tuple(sorted(set(failed_sector_keys) & supported))


def retry_keys(failed_sector_keys: Iterable[str], plan: CollectionPlan) -> tuple[str, ...]:
    return failure_alert_keys(failed_sector_keys, plan)


def pdf_report_includes_sector(sector_key: str, policy: dict[str, object] | None = None) -> bool:
    policy = policy or load_support_policy()
    bundle = load_seed_bundle()
    return bool(policy["pdf_report_independence"]["independent"]) and sector_key in {sector.sector_key for sector in bundle.sectors}  # type: ignore[index]
