from __future__ import annotations

import json
from dataclasses import dataclass

from ..config import CONFIG_DIR


CAPABILITY_PATH = CONFIG_DIR / "provider_capability_matrix_v1.json"
ALLOWED_MAPPING_TYPES = frozenset({"direct", "proxy", "composite"})


@dataclass(frozen=True)
class ProviderCandidate:
    provider: str
    symbol: str
    provider_name: str
    mapping_type: str
    priority: int
    spot_supported: bool
    history_supported: bool
    exact_mapping: bool
    validation_status: str
    components: tuple[dict, ...]

    @property
    def selectable(self) -> bool:
        return (
            self.validation_status == "validated"
            and self.spot_supported
            and self.history_supported
            and self.exact_mapping
        )


@dataclass(frozen=True)
class SectorCapability:
    sector_key: str
    display_name: str
    mapping_type: str
    primary_provider: str
    candidates: tuple[ProviderCandidate, ...]

    @property
    def selectable_candidates(self) -> tuple[ProviderCandidate, ...]:
        return tuple(sorted((item for item in self.candidates if item.selectable), key=lambda item: item.priority))


def load_provider_capabilities() -> dict[str, SectorCapability]:
    document = json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))
    if document.get("supported_sector_count") != 65 or document.get("unsupported_sector_key") != "hang_seng_tech":
        raise ValueError("provider_capability_matrix_scope_invalid")
    rows = document.get("sectors", [])
    if len(rows) != 65:
        raise ValueError("provider_capability_matrix_count_invalid")
    output: dict[str, SectorCapability] = {}
    for row in rows:
        sector_key = str(row["canonical_sector_key"])
        mapping_type = str(row["mapping_type"])
        if sector_key == "hang_seng_tech" or mapping_type not in ALLOWED_MAPPING_TYPES or sector_key in output:
            raise ValueError("provider_capability_matrix_row_invalid")
        candidates = tuple(ProviderCandidate(
            provider=str(item["provider"]), symbol=str(item["symbol"]),
            provider_name=str(item["provider_name"]), mapping_type=str(item["mapping_type"]),
            priority=int(item["priority"]), spot_supported=bool(item["spot_supported"]),
            history_supported=bool(item["history_supported"]), exact_mapping=bool(item["exact_mapping"]),
            validation_status=str(item["validation_status"]), components=tuple(item.get("components", [])),
        ) for item in row.get("candidates", []))
        if any(item.mapping_type != mapping_type or item.mapping_type not in ALLOWED_MAPPING_TYPES for item in candidates):
            raise ValueError("provider_capability_candidate_semantics_invalid")
        output[sector_key] = SectorCapability(
            sector_key=sector_key, display_name=str(row["display_name"]), mapping_type=mapping_type,
            primary_provider=str(row["primary_provider"]), candidates=candidates,
        )
    return output
