from __future__ import annotations

import json
from collections import Counter

from leopard_project.config import CONFIG_DIR, load_seed_bundle
from leopard_project.models import MappingStatus


def main() -> int:
    bundle = load_seed_bundle()
    custom = json.loads((CONFIG_DIR / "custom_compositions_v2_3.json").read_text(encoding="utf-8"))
    statuses = Counter(mapping.mapping_status for mapping in bundle.mappings)
    assertions = {
        "sector_count_66": len(bundle.sectors) == 66,
        "group_count_8": len({sector.group_order for sector in bundle.sectors}) == 8,
        "mapping_count_66": len(bundle.mappings) == 66,
        "research_confirmed_62": statuses[MappingStatus.CONFIRMED] == 62,
        "custom_candidate_4": statuses[MappingStatus.CANDIDATE] == 4,
        "production_approved_0": not any(mapping.user_confirmed for mapping in bundle.mappings),
        "effective_dates_0": not any(mapping.effective_date for mapping in bundle.mappings),
        "source_urls_66": all(mapping.primary_source_url for mapping in bundle.mappings),
        "custom_compositions_4": len(custom["compositions"]) == 4,
    }
    failed = [name for name, passed in assertions.items() if not passed]
    print(json.dumps({"checks": assertions, "passed": not failed}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
