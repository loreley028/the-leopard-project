"""Fill an isolated Market Core database through its exact latest completed day."""
from __future__ import annotations

import argparse
import json
import os

from leopard_project.historical_market_daily import refresh_market_history_to_latest_completed
from leopard_project.providers.sina_public_daily import SinaPublicDailyMarketProvider
from leopard_project.web.database import create_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("LEOPARD_DATABASE_URL"))
    parser.add_argument("--enable-provider", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or LEOPARD_DATABASE_URL is required")
    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        result = refresh_market_history_to_latest_completed(
            session, provider=SinaPublicDailyMarketProvider(), enable_provider=args.enable_provider,
        )
    payload = {**result.__dict__, "expected_latest_completed_trading_day": result.expected_latest_completed_trading_day.isoformat()}
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
