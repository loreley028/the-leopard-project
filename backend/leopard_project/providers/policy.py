from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from ..config import CONFIG_DIR


class ProviderRole(StrEnum):
    RESEARCH_PROVIDER = "research_provider"
    CANDIDATE_PRIMARY = "candidate_primary"
    DIAGNOSTIC_PROVIDER = "diagnostic_provider"
    UNSUPPORTED = "unsupported"
    PRODUCTION_PRIMARY = "production_primary"


class SnapshotAnomaly(StrEnum):
    STALE_SNAPSHOT = "stale_snapshot"
    HISTORY_LENGTH_CHANGED = "history_length_changed"


POLICY_PATH = CONFIG_DIR / "provider_policy_phase1a_v1.json"


def load_provider_policy(path: Path = POLICY_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def provider_role(provider_key: str) -> ProviderRole:
    policy = load_provider_policy()
    roles = policy["provider_roles"]
    try:
        return ProviderRole(roles[provider_key])  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"provider role is not configured: {provider_key}") from exc


def provider_symbol(canonical_symbol: str, provider_key: str) -> str:
    policy = load_provider_policy()
    try:
        mapping = policy["symbol_mappings"][canonical_symbol]  # type: ignore[index]
        return str(mapping[provider_key])
    except KeyError as exc:
        raise ValueError(f"symbol mapping is not configured: {canonical_symbol}/{provider_key}") from exc


def production_admission_met(completed_checks: Sequence[str]) -> bool:
    policy = load_provider_policy()
    required = set(policy["production_primary_admission"])  # type: ignore[arg-type]
    return bool(policy["production_primary_approved"]) and required.issubset(completed_checks)


def detect_snapshot_anomaly(
    previous_latest: date,
    previous_count: int,
    current_latest: date,
    current_count: int,
) -> SnapshotAnomaly | None:
    if current_latest < previous_latest:
        return SnapshotAnomaly.STALE_SNAPSHOT
    if current_count < previous_count:
        return SnapshotAnomaly.HISTORY_LENGTH_CHANGED
    return None
