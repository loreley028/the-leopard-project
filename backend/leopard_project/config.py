from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .models import MappingStatus, Sector, SectorAlias, SectorMapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"


class ConfigurationError(ValueError):
    """Raised when a checked-in configuration violates Phase 0 invariants."""


@dataclass(frozen=True)
class SeedBundle:
    configuration_version: str
    sectors: tuple[Sector, ...]
    aliases: tuple[SectorAlias, ...]
    mappings: tuple[SectorMapping, ...]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_seed_bundle(config_dir: Path = CONFIG_DIR) -> SeedBundle:
    sector_doc = _read_json(config_dir / "sectors_v2_3.json")
    alias_doc = _read_json(config_dir / "sector_aliases_v2_3.json")
    mapping_doc = _read_json(config_dir / "sector_mappings_v2_3.json")

    sectors = tuple(
        Sector(
            sector_key=row["sector_key"],
            sector_name=row["sector_name"],
            category_level_1=group["group_name"],
            group_order=row["group_order"],
            within_group_order=row["within_group_order"],
            overall_order=row["overall_order"],
            enabled=False,
            description=row.get("note"),
        )
        for group in sector_doc["groups"]
        for row in group["sectors"]
    )
    aliases = tuple(SectorAlias(**row) for row in alias_doc["aliases"])
    mappings = tuple(
        SectorMapping(
            mapping_version=mapping_doc["mapping_version"],
            **{key: value for key, value in row.items() if key not in {
                "overall_order", "group_order", "group_name", "within_group_order",
                "included_in_daily_job", "research_conclusion", "review_recommendation",
            }},
        )
        for row in mapping_doc["mappings"]
    )
    bundle = SeedBundle(sector_doc["configuration_version"], sectors, aliases, mappings)
    validate_seed_bundle(bundle)
    return bundle


def validate_seed_bundle(bundle: SeedBundle) -> None:
    if len(bundle.sectors) != 66:
        raise ConfigurationError(f"expected 66 sectors, got {len(bundle.sectors)}")
    group_orders = sorted({sector.group_order for sector in bundle.sectors})
    if group_orders != list(range(1, 9)):
        raise ConfigurationError(f"expected group orders 1..8, got {group_orders}")
    keys = [sector.sector_key for sector in bundle.sectors]
    names = [sector.sector_name for sector in bundle.sectors]
    if len(keys) != len(set(keys)):
        raise ConfigurationError("sector_key values must be unique")
    if len(names) != len(set(names)):
        raise ConfigurationError("sector names must be unique")
    ordered = sorted(bundle.sectors, key=lambda item: item.overall_order)
    if [item.overall_order for item in ordered] != list(range(1, 67)):
        raise ConfigurationError("overall sector order must be consecutive from 1 through 66")
    for group_order in group_orders:
        within = sorted(item.within_group_order for item in bundle.sectors if item.group_order == group_order)
        if within != list(range(1, len(within) + 1)):
            raise ConfigurationError(f"group {group_order} order is not consecutive")
    if {mapping.sector_key for mapping in bundle.mappings} != set(keys):
        raise ConfigurationError("mapping seed and sector seed must contain the same sector keys")
    if len(bundle.mappings) != 66:
        raise ConfigurationError("every sector must have exactly one mapping row")
    if any(not mapping.primary_source_url for mapping in bundle.mappings):
        raise ConfigurationError("every mapping must retain a primary source URL")


def normalize_alias(raw_name: str, bundle: SeedBundle) -> str | None:
    canonical = {sector.sector_name: sector.sector_key for sector in bundle.sectors}
    if raw_name in canonical:
        return canonical[raw_name]
    lookup = {alias.alias: alias.sector_key for alias in bundle.aliases if alias.confirmed}
    return lookup.get(raw_name)


def mapping_is_eligible(mapping: SectorMapping, trade_date: date) -> bool:
    return bool(
        mapping.mapping_status == MappingStatus.CONFIRMED
        and mapping.user_confirmed
        and mapping.primary_symbol
        and mapping.provider_key
        and mapping.effective_date
        and mapping.effective_date <= trade_date
    )
