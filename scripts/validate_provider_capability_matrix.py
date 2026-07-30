from __future__ import annotations

import json

from leopard_project.config import CONFIG_DIR
from leopard_project.providers.capabilities import load_provider_capabilities


def main() -> None:
    document = json.loads((CONFIG_DIR / "provider_capability_matrix_v1.json").read_text(encoding="utf-8"))
    rows = load_provider_capabilities()
    summary = document["validation_summary"]
    validated_direct = sum(row.mapping_type == "direct" and bool(row.selectable_candidates) for row in rows.values())
    validated_proxy = sum(row.mapping_type == "proxy" and bool(row.selectable_candidates) for row in rows.values())
    validated_composite = sum(row.mapping_type == "composite" and bool(row.selectable_candidates) for row in rows.values())
    unverified = sum(not row.selectable_candidates for row in rows.values())
    expected = {
        "validated_direct": validated_direct,
        "validated_proxy": validated_proxy,
        "validated_composite": validated_composite,
        "unverified": unverified,
        "no_mapping": 0,
    }
    if summary != expected or sum(expected.values()) != 65:
        raise SystemExit(f"capability summary mismatch: {summary!r} != {expected!r}")
    print(f"Provider capability matrix valid: 65 rows; selectable={65 - unverified}; unverified={unverified}")


if __name__ == "__main__":
    main()
