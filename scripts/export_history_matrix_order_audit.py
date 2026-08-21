"""Export the versioned Reader history-matrix order for manual review."""
from __future__ import annotations

import argparse
from pathlib import Path

from leopard_project.history_matrix_ordering import write_history_matrix_order_review
from leopard_project.report_registry import load_report_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("var/audit/history_matrix_order_review.csv"))
    args = parser.parse_args()
    path = write_history_matrix_order_review(args.output, load_report_registry())
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
