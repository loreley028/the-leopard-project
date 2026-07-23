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
    if not isinstance(jobs, dict) or not {"offline-validation", "frontend-validation"}.issubset(jobs):
        raise ValueError("offline-validation and frontend-validation jobs are required")

    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    required_steps = (
        "validate_phase0.py", "validate_phase1a.py", "validate_phase1b0.py", "validate_phase1b1.py",
        "validate_phase2a0.py", "check_ui_license_boundary.py", "npm ci", "npm run lint",
        "npm run typecheck", "npm run test", "npm run build",
    )
    if not all(step in text for step in required_steps):
        raise ValueError("CI workflow is missing a required historical or Phase 2A-0 validation")
    if "LEOPARD_RUN_LIVE" in text or "secrets." in text:
        raise ValueError("CI must remain offline and token-independent")

    print(f"Workflow YAML valid: {WORKFLOW_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
