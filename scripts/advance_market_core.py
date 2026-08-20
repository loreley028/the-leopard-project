"""Run one independent, controlled Market Core daily advance or reconciliation."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from leopard_project.daily_market_advance import advance_market_core
from leopard_project.providers.sina_public_daily import SinaPublicDailyMarketProvider
from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.web.database import create_session_factory


SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("advance", "reconcile"), required=True)
    parser.add_argument("--database-url", default=os.getenv("LEOPARD_DATABASE_URL"))
    parser.add_argument("--enable-tencent-provider", action="store_true")
    parser.add_argument("--enable-sina-provider", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or LEOPARD_DATABASE_URL is required")
    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        result = advance_market_core(
            session, mode=args.mode, now=datetime.now(SHANGHAI),
            tencent_provider=TencentStandardSecurityQuoteProvider(),
            sina_provider=SinaPublicDailyMarketProvider(),
            enable_tencent_provider=args.enable_tencent_provider,
            enable_sina_provider=args.enable_sina_provider,
        )
    payload = asdict(result)
    payload["expected_trading_date"] = result.expected_trading_date.isoformat()
    payload["coverage"] = {**asdict(result.coverage), "expected_trading_date": result.coverage.expected_trading_date.isoformat()}
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 0 if result.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
