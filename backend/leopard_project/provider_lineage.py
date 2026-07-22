from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import PROJECT_ROOT


LINEAGE_PATH = PROJECT_ROOT / "data" / "reconciliation-validation" / "provider_lineage.json"


class IndependenceStatus(StrEnum):
    INDEPENDENT = "independent"
    LIKELY_INDEPENDENT = "likely_independent"
    SHARED_UPSTREAM = "shared_upstream"
    LIKELY_SHARED_UPSTREAM = "likely_shared_upstream"
    UNKNOWN = "unknown"


class ProviderLineage(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_name: str
    adapter_name: str
    provider_role: str
    upstream_vendor: str | None
    upstream_endpoint_family: str | None
    endpoint_host: str | None
    transport_type: str
    authentication_required: bool
    documented_api: bool
    service_sla: str
    licensing_status: str
    observed_response_signature: str | None
    observed_field_signature: tuple[str, ...]
    independence_status: IndependenceStatus
    independence_confidence: str
    compared_with: tuple[str, ...]
    evidence: tuple[str, ...]
    verified_at: datetime
    notes: str


def compare_lineages(first: ProviderLineage, second: ProviderLineage) -> IndependenceStatus:
    if first.provider_name == second.provider_name:
        return IndependenceStatus.SHARED_UPSTREAM
    if not first.upstream_vendor or not second.upstream_vendor:
        return IndependenceStatus.UNKNOWN
    if first.upstream_vendor.casefold() == second.upstream_vendor.casefold():
        if (
            first.endpoint_host == second.endpoint_host
            and first.upstream_endpoint_family == second.upstream_endpoint_family
        ):
            return IndependenceStatus.SHARED_UPSTREAM
        return IndependenceStatus.LIKELY_SHARED_UPSTREAM
    if (
        first.documented_api
        and second.documented_api
        and first.licensing_status == "authorized"
        and second.licensing_status == "authorized"
    ):
        return IndependenceStatus.LIKELY_INDEPENDENT
    return IndependenceStatus.UNKNOWN


def load_provider_lineages(path: Path = LINEAGE_PATH) -> tuple[ProviderLineage, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return tuple(ProviderLineage(**row) for row in document["providers"])


def lineage_by_name(provider_name: str, path: Path = LINEAGE_PATH) -> ProviderLineage:
    try:
        return next(row for row in load_provider_lineages(path) if row.provider_name == provider_name)
    except StopIteration as exc:
        raise ValueError(f"provider lineage is not recorded: {provider_name}") from exc
