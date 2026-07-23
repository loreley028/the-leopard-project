from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PACKAGE = "animal-island-ui"
VERSION = "1.3.0"
FORBIDDEN_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".wav", ".mp4"}


def candidates() -> list[Path]:
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True
    ).splitlines()
    return [ROOT / name for name in names]


def main() -> int:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((FRONTEND / "package-lock.json").read_text(encoding="utf-8"))
    policy = json.loads((ROOT / "config/ui_dependency_policy_v1.json").read_text(encoding="utf-8"))
    main_source = (FRONTEND / "src/main.tsx").read_text(encoding="utf-8")
    failures: list[str] = []

    if package.get("dependencies", {}).get(PACKAGE) != VERSION:
        failures.append(f"{PACKAGE} must be an exact dependency at {VERSION}")
    lock_entry = lock.get("packages", {}).get(f"node_modules/{PACKAGE}", {})
    if lock_entry.get("version") != VERSION:
        failures.append(f"package lock must resolve {PACKAGE} to {VERSION}")
    all_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (FRONTEND / "src").rglob("*") if path.is_file()
    )
    style_import = re.compile(r"^import\s+['\"]animal-island-ui/style['\"];?\s*$", re.MULTILINE)
    style_imports = sum(len(style_import.findall(path.read_text(encoding="utf-8"))) for path in (FRONTEND / "src").rglob("*.tsx"))
    if style_imports != 1 or "import 'animal-island-ui/style';" not in main_source:
        failures.append("animal-island-ui/style must be imported exactly once in frontend/src/main.tsx")
    for required in (ROOT / "THIRD_PARTY_NOTICES.md", ROOT / "docs/ui-license-assessment.md"):
        if not required.is_file():
            failures.append(f"missing attribution record: {required.relative_to(ROOT)}")
    required_policy = {
        "pinned_version": VERSION,
        "license": "CC-BY-NC-4.0",
        "usage_scope": "private_noncommercial_research",
        "usage_is_commercial": False,
        "company_use": False,
        "public_registration": False,
        "paid_access": False,
        "attribution_required": True,
        "modification_notice_required": True,
        "commercialization_review_required": True,
        "approved_for_current_scope": True,
    }
    for key, expected in required_policy.items():
        if policy.get(key) != expected:
            failures.append(f"ui dependency policy mismatch: {key}")
    if (ROOT / ".gitmodules").exists():
        failures.append("Git submodules are not allowed for the UI dependency")

    project_files = candidates()
    copied_dirs = [
        path for path in project_files
        if PACKAGE in path.relative_to(ROOT).parts and "node_modules" not in path.relative_to(ROOT).parts
    ]
    if copied_dirs:
        failures.extend(f"copied dependency source path: {path.relative_to(ROOT)}" for path in copied_dirs)
    assets = [
        path for path in project_files
        if path.is_file() and path.is_relative_to(FRONTEND) and path.suffix.lower() in FORBIDDEN_ASSET_SUFFIXES
    ]
    if assets:
        failures.extend(f"unapproved binary frontend asset: {path.relative_to(ROOT)}" for path in assets)
    if "Nintendo" in all_source:
        failures.append("frontend runtime source must not use Nintendo names or assets")
    for page in (FRONTEND / "src/pages").rglob("*.tsx"):
        if 'from "animal-island-ui"' in page.read_text(encoding="utf-8"):
            failures.append(f"business page bypasses Island adapter: {page.relative_to(ROOT)}")

    if failures:
        print("\n".join(failures))
        return 1
    print(f"UI dependency policy passed: {PACKAGE}@{VERSION}, attribution present, noncommercial gate closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
