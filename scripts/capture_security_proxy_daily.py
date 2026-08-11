"""Explicit post-close capture for the fixed security-proxy registry."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_daily import capture_fixed_security_proxy_daily
from leopard_project.web.database import create_session_factory


SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="target_date", type=date.fromisoformat, default=datetime.now(SHANGHAI).date())
    parser.add_argument("--database-url", default=os.getenv("LEOPARD_DATABASE_URL"))
    parser.add_argument("--enable-provider", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or LEOPARD_DATABASE_URL is required")
    sessions = create_session_factory(args.database_url)
    with sessions() as session:
        summary = capture_fixed_security_proxy_daily(
            session,
            target_trading_date=args.target_date,
            provider=TencentStandardSecurityQuoteProvider(),
            now=lambda: datetime.now(SHANGHAI),
            enable_provider=args.enable_provider,
        )
    print(json.dumps({**summary.__dict__, "target_trading_date": summary.target_trading_date.isoformat()}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
