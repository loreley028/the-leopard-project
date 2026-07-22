from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any


class MappingApprovalError(ValueError):
    pass


def approve_research_version(
    mapping_document: dict[str, Any],
    requested_version: str,
    *,
    effective_date: date | None = None,
) -> dict[str, Any]:
    """Return a new approved version; never mutate or overwrite the research seed."""
    if mapping_document.get("mapping_version") != requested_version:
        raise MappingApprovalError("requested mapping version does not match the loaded research version")
    if not mapping_document.get("research_complete"):
        raise MappingApprovalError("only a completed research version can be batch-approved")

    approved = deepcopy(mapping_document)
    approved["parent_mapping_version"] = requested_version
    approved["mapping_version"] = f"{requested_version}-approved"
    approved["production_approved"] = True
    approved["production_approval_date"] = effective_date.isoformat() if effective_date else None
    for mapping in approved["mappings"]:
        mapping["mapping_status"] = "已确认"
        mapping["user_confirmed"] = True
        mapping["effective_date"] = effective_date.isoformat() if effective_date else None
        mapping["included_in_daily_job"] = bool(
            effective_date and mapping.get("primary_symbol") and mapping.get("provider_key")
        )
    return approved
