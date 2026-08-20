#!/usr/bin/env python3
"""Write a non-runtime CSV review artifact for fixed primary observations."""
from __future__ import annotations

import argparse
from pathlib import Path

from leopard_project.primary_observation_audit import build_primary_observation_audit, write_primary_observation_audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-completed-date", required=True)
    parser.add_argument("--output", type=Path, default=Path("var/audit/primary_observation_audit.csv"))
    parser.add_argument("--tencent-result", choices=("pass", "fail"), default="pass")
    parser.add_argument("--sina-historical-result", choices=("pass", "fail"), default="pass")
    args = parser.parse_args()
    rows = build_primary_observation_audit(
        latest_completed_date=args.latest_completed_date,
        tencent_result=args.tencent_result,
        sina_historical_result=args.sina_historical_result,
    )
    write_primary_observation_audit(args.output, rows)
    print(f"wrote {len(rows)} active primary-observation rows to {args.output}")


if __name__ == "__main__":
    main()
