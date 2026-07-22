from __future__ import annotations

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT / ".github/workflows/ci.yml"


def main() -> int:
    document = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("CI workflow must be a YAML mapping")

    # YAML 1.1 loaders may parse the unquoted GitHub key `on` as boolean true.
    triggers = document.get("on", document.get(True))
    if not isinstance(triggers, dict) or not {"push", "pull_request"}.issubset(triggers):
        raise ValueError("CI workflow must run for push and pull_request")

    permissions = document.get("permissions")
    if permissions != {"contents": "read"}:
        raise ValueError("CI workflow permissions must be exactly contents: read")

    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or "offline-validation" not in jobs:
        raise ValueError("offline-validation job is required")

    print(f"Workflow YAML valid: {WORKFLOW_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
