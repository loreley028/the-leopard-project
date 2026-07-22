from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .config import CONFIG_DIR
from .mappings import approve_research_version


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="leopard-project")
    commands = parser.add_subparsers(dest="command", required=True)
    mappings = commands.add_parser("mappings")
    mapping_commands = mappings.add_subparsers(dest="mapping_command", required=True)
    approve = mapping_commands.add_parser("approve-research-version")
    approve.add_argument("--version", required=True)
    approve.add_argument("--effective-date", type=date.fromisoformat)
    approve.add_argument("--output", type=Path, help="write a new versioned preview; never updates the seed in place")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "mappings" and args.mapping_command == "approve-research-version":
        source = CONFIG_DIR / "sector_mappings_v2_3.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        approved = approve_research_version(document, args.version, effective_date=args.effective_date)
        if args.output:
            if args.output.resolve() == source.resolve():
                raise SystemExit("refusing to overwrite the checked-in research seed")
            if args.output.exists():
                raise SystemExit(f"refusing to overwrite existing output: {args.output}")
            args.output.write_text(json.dumps(approved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        eligible = sum(1 for row in approved["mappings"] if row["included_in_daily_job"])
        print(json.dumps({"new_version": approved["mapping_version"], "approved": 66, "daily_job_eligible": eligible}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
