#!/usr/bin/env python3
"""Export fixed-security composition, primary, reuse, and review audit artifacts."""
from __future__ import annotations

import argparse
from pathlib import Path

from leopard_project.primary_observation_audit import build_primary_observation_audit, write_primary_observation_audit
from leopard_project.sector_security_composition_audit import write_composition_audit, write_mapping_review_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-completed-date", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("var/audit"))
    args = parser.parse_args()
    output_dir = args.output_dir
    primary_path = output_dir / "primary_observation_audit.csv"
    write_primary_observation_audit(
        primary_path,
        build_primary_observation_audit(latest_completed_date=args.latest_completed_date),
    )
    paths = [
        *write_composition_audit(output_dir, latest_completed_date=args.latest_completed_date),
        primary_path,
        write_mapping_review_summary(output_dir / "sector_security_mapping_review.md", latest_completed_date=args.latest_completed_date),
    ]
    print("\n".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
