from __future__ import annotations

import json
from dataclasses import dataclass

from ..config import CONFIG_DIR


CAPABILITY_PATH = CONFIG_DIR / "provider_capability_matrix_v2.json"
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
    parent_report_topic: str | None = None
    validation_status: str = "unverified"

    @property
    def selectable_candidates(self) -> tuple[ProviderCandidate, ...]:
        return tuple(sorted((item for item in self.candidates if item.selectable), key=lambda item: item.priority))


def _resolved_document() -> dict:
    overlay = json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))
    base_path = CONFIG_DIR / str(overlay["base_matrix"])
    base = json.loads(base_path.read_text(encoding="utf-8"))
    removed = set(overlay.get("remove_sector_keys", []))
    validated = set(overlay.get("cloud_validated_sector_keys", []))
    rows = [dict(row) for row in base.get("sectors", []) if row["canonical_sector_key"] not in removed]
    for row in rows:
        if row["canonical_sector_key"] not in validated:
            continue
        row.update({
            "spot_supported": True,
            "daily_history_supported": True,
            "validation_status": "validated",
            "validation_time": overlay["cloud_validation"]["validated_at"],
            "evidence_summary": "Aliyun Docker exact-symbol spot, pre_close, four-close same-source history and intraday MA5 passed.",
        })
        for candidate in row.get("candidates", []):
            if candidate["provider"] == "ths_exact_spot":
                candidate.update({
                    "spot_supported": True,
                    "history_supported": True,
                    "validation_status": "validated",
                })
    rows.extend(overlay.get("replacement_market_paths", []))
    return {**overlay, "sectors": rows}


def load_provider_capabilities() -> dict[str, SectorCapability]:
    from ..market_paths import load_market_path_registry

    document = _resolved_document()
    registry = load_market_path_registry()
    rows = document.get("sectors", [])
    if len(rows) != len(registry.supported_market_paths):
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
            parent_report_topic=str(row.get("parent_report_topic") or sector_key),
            validation_status=str(row.get("validation_status", "unverified")),
        )
    if set(output) != {item.market_path_key for item in registry.supported_market_paths}:
        raise ValueError("provider_capability_matrix_scope_invalid")
    return output


def provider_capability_summary(capabilities: dict[str, SectorCapability] | None = None) -> dict[str, int]:
    rows = capabilities or load_provider_capabilities()
    validated = [item for item in rows.values() if item.selectable_candidates]
    return {
        "matrix_total": len(rows),
        "validated_direct": sum(item.mapping_type == "direct" for item in validated),
        "validated_proxy": sum(item.mapping_type == "proxy" for item in validated),
        "validated_composite": sum(item.mapping_type == "composite" for item in validated),
        "operational_coverage": len(validated),
        "unverified": len(rows) - len(validated),
        "no_mapping": sum(not item.candidates for item in rows.values()),
        "spot_complete": sum(any(candidate.selectable for candidate in item.candidates) for item in rows.values()),
        "history_complete": sum(any(candidate.selectable for candidate in item.candidates) for item in rows.values()),
        "ma5_capable": sum(any(candidate.selectable for candidate in item.candidates) for item in rows.values()),
    }
