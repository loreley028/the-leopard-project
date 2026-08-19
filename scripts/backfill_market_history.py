"""Backfill exact-date historical daily bars for the fixed Market Core universe."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from leopard_project.historical_market_daily import backfill_market_history, backfill_selected_market_history
from leopard_project.providers.sina_public_daily import SinaPublicDailyMarketProvider
from leopard_project.web.database import create_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--database-url", default=os.getenv("LEOPARD_DATABASE_URL"))
    parser.add_argument("--enable-provider", action="store_true")
    parser.add_argument("--replace", action="store_true", help="explicitly replace a conflicting preview-only row")
    parser.add_argument("--symbols", help="comma-separated fixed symbols for a preview-only selected backfill")
    parser.add_argument("--paced", action="store_true", help="sequentially pause 3 seconds between provider requests")
    parser.add_argument("--checkpoint", type=Path, help="write response-free per-symbol progress for resume")
    parser.add_argument("--resume", action="store_true", help="resume safely from database preflight and checkpoint state")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or LEOPARD_DATABASE_URL is required")
    if args.resume and not args.checkpoint:
        parser.error("--resume requires --checkpoint")
    selected = tuple(dict.fromkeys(item.strip().lower() for item in (args.symbols or "").split(",") if item.strip()))
    if (args.paced or args.checkpoint or args.resume) and not selected:
        parser.error("--paced, --checkpoint and --resume require --symbols")
    checkpoint_state: dict[str, str] = {}
    if args.checkpoint and args.checkpoint.exists():
        checkpoint_state = json.loads(args.checkpoint.read_text(encoding="utf-8"))

    def checkpoint(symbol: str, status: str) -> None:
        if not args.checkpoint:
            return
        checkpoint_state[symbol] = status
        args.checkpoint.write_text(json.dumps(checkpoint_state, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        result = (
            backfill_selected_market_history(
                session, provider=SinaPublicDailyMarketProvider(), symbols=selected, days=args.days,
                enable_provider=args.enable_provider, paced_seconds=3 if args.paced else 0,
                checkpoint=checkpoint if args.checkpoint else None, sleep=time.sleep,
            ) if selected else backfill_market_history(
                session, provider=SinaPublicDailyMarketProvider(), days=args.days,
                enable_provider=args.enable_provider, replace=args.replace,
            )
        )
    print(json.dumps(result.__dict__, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
