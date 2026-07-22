from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    roots = (Path("config"), Path("data/provider-validation"), Path("data/provider-selection"))
    paths = sorted(path for root in roots if root.exists() for path in root.rglob("*.json"))
    for path in paths:
        json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({"json_files": len(paths), "passed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
