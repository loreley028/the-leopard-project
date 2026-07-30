from __future__ import annotations

import json
from dataclasses import dataclass

from .config import CONFIG_DIR, SeedBundle, load_seed_bundle
from .models import Market, Sector, SectorMapping, SupportStatus


REGISTRY_PATH = CONFIG_DIR / "market_path_registry_v1.json"


@dataclass(frozen=True)
class MarketPath:
    market_path_key: str
    display_name: str
    parent_report_topic: str
    category_level_1: str
    group_order: int
    overall_order: int
    mapping_type: str
    support_status: SupportStatus
    market: Market
    provider_symbol: str
    provider_name: str
    semantic_difference: str
    display_detail: str


@dataclass(frozen=True)
class MarketPathRegistry:
    registry_version: str
    report_topic_count: int
    market_paths: tuple[MarketPath, ...]

    @property
    def market_path_count(self) -> int:
        return len(self.market_paths)

    @property
    def supported_market_paths(self) -> tuple[MarketPath, ...]:
        return tuple(item for item in self.market_paths if item.support_status == SupportStatus.SUPPORTED)

    @property
    def unsupported_market_paths(self) -> tuple[MarketPath, ...]:
        return tuple(item for item in self.market_paths if item.support_status == SupportStatus.UNSUPPORTED)


def _document() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_market_path_registry(bundle: SeedBundle | None = None) -> MarketPathRegistry:
    bundle = bundle or load_seed_bundle()
    document = _document()
    split = {key: tuple(value) for key, value in document["report_topic_market_paths"].items()}
    overrides = {item["market_path_key"]: item for item in document["market_path_overrides"]}
    mappings = {item.sector_key: item for item in bundle.mappings}
    unsupported = set(document["unsupported_market_paths"])
    paths: list[MarketPath] = []
    for topic in sorted(bundle.sectors, key=lambda item: item.overall_order):
        path_keys = split.get(topic.sector_key, (topic.sector_key,))
        for offset, path_key in enumerate(path_keys):
            override = overrides.get(path_key, {})
            status = SupportStatus.UNSUPPORTED if path_key in unsupported else SupportStatus(str(override.get("support_status", "supported")))
            paths.append(MarketPath(
                market_path_key=path_key,
                display_name=str(override.get("display_name", topic.sector_name)),
                parent_report_topic=topic.sector_key,
                category_level_1=topic.category_level_1,
                group_order=topic.group_order,
                overall_order=topic.overall_order * 10 + offset,
                mapping_type=str(override.get(
                    "mapping_type",
                    "composite" if mappings[topic.sector_key].primary_symbol.startswith("CUSTOM_") else "direct",
                )),
                support_status=status,
                market=Market.HK if path_key == "hang_seng_tech" else Market.CN_A,
                provider_symbol=str(override.get("provider_symbol", "")),
                provider_name=str(override.get("provider_name", "")),
                semantic_difference=str(override.get("semantic_difference", "")),
                display_detail=str(override.get("display_detail", "研究辅助数据，非生产级行情服务。")),
            ))
    registry = MarketPathRegistry(
        registry_version=str(document["registry_version"]),
        report_topic_count=len(bundle.sectors),
        market_paths=tuple(paths),
    )
    if registry.report_topic_count != len({item.sector_key for item in bundle.sectors}):
        raise ValueError("report_topic_registry_invalid")
    if len({item.market_path_key for item in paths}) != registry.market_path_count:
        raise ValueError("market_path_keys_must_be_unique")
    if {item.parent_report_topic for item in paths} != {item.sector_key for item in bundle.sectors}:
        raise ValueError("every_report_topic_must_have_a_market_path_relation")
    if len(registry.unsupported_market_paths) != 1 or registry.unsupported_market_paths[0].market_path_key != "hang_seng_tech":
        raise ValueError("hstech_must_be_the_only_unsupported_market_path")
    if any(item.market_path_key == "hotel_catering" for item in paths):
        raise ValueError("hotel_catering_is_report_only_not_an_active_market_path")
    return registry


def market_path_for_key(key: str) -> MarketPath | None:
    return next((item for item in load_market_path_registry().market_paths if item.market_path_key == key), None)


def report_topic_for_market_path(key: str) -> str | None:
    item = market_path_for_key(key)
    return item.parent_report_topic if item else None


def market_path_mapping(path: MarketPath, bundle: SeedBundle | None = None) -> SectorMapping:
    bundle = bundle or load_seed_bundle()
    parent = next(item for item in bundle.mappings if item.sector_key == path.parent_report_topic)
    symbol = path.provider_symbol or parent.primary_symbol
    if path.market_path_key == "hotel":
        symbol = "881160"
    elif path.market_path_key == "catering":
        symbol = "UNVERIFIED_CATERING"
    return parent.model_copy(update={
        "mapping_version": f"{parent.mapping_version}+{load_market_path_registry(bundle).registry_version}",
        "sector_key": path.market_path_key,
        "sector_name": path.display_name,
        "ths_candidate_name": path.provider_name or path.display_name,
        "ths_display_code": symbol,
        "primary_symbol": symbol,
        "backup_symbols": (),
        "methodology_note": path.semantic_difference or parent.methodology_note,
    })


def report_topic_sector(path: MarketPath, bundle: SeedBundle | None = None) -> Sector:
    bundle = bundle or load_seed_bundle()
    return next(item for item in bundle.sectors if item.sector_key == path.parent_report_topic)
