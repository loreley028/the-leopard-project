"""Backfill exact-date historical daily bars for the fixed Market Core universe."""
from __future__ import annotations

import argparse
import json
import os

from leopard_project.historical_market_daily import backfill_market_history
from leopard_project.providers.sina_public_daily import SinaPublicDailyMarketProvider
from leopard_project.web.database import create_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--database-url", default=os.getenv("LEOPARD_DATABASE_URL"))
    parser.add_argument("--enable-provider", action="store_true")
    parser.add_argument("--replace", action="store_true", help="explicitly replace a conflicting preview-only row")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or LEOPARD_DATABASE_URL is required")
    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        result = backfill_market_history(
            session, provider=SinaPublicDailyMarketProvider(), days=args.days,
            enable_provider=args.enable_provider, replace=args.replace,
        )
    print(json.dumps(result.__dict__, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
