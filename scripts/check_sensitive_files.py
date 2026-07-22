from __future__ import annotations

import re
import subprocess
from pathlib import Path


FORBIDDEN_PATHS = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"(^|/)\.env\.(?!example$).+"),
    re.compile(r"\.(pem|key|p12|pfx)$", re.I),
    re.compile(r"(^|/)(logs|backups|data/runtime)/.+"),
    re.compile(r"(^|/)output/(?!\.gitkeep$).+"),
)
SECRET_PATTERNS = (
    re.compile(r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9+/]{8,}"),
)


def main() -> int:
    candidates = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        text=True,
    ).splitlines()
    failures: list[str] = []
    for name in candidates:
        if any(pattern.search(name) for pattern in FORBIDDEN_PATHS):
            failures.append(f"forbidden tracked path: {name}")
            continue
        path = Path(name)
        if not path.is_file() or path.stat().st_size > 1_000_000:
            if path.is_file() and path.stat().st_size > 1_000_000:
                failures.append(f"tracked file exceeds 1 MB: {name}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            failures.append(f"possible credential in: {name}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"sensitive-file check passed for {len(candidates)} tracked or untracked candidate files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
