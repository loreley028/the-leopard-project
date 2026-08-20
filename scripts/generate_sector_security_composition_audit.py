#!/usr/bin/env python3
"""Write non-runtime fixed-security composition audit CSVs."""
from __future__ import annotations

import argparse
from pathlib import Path

from leopard_project.sector_security_composition_audit import write_composition_audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-completed-date", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("var/audit"))
    args = parser.parse_args()
    paths = write_composition_audit(args.output_dir, latest_completed_date=args.latest_completed_date)
    print("\n".join(str(path) for path in paths))


if __name__ == "__main__":
    main()
