#!/usr/bin/env python3
"""Run one isolated, scheduler-triggered cloud-readiness live acceptance."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from pathlib import Path

from sqlalchemy import func, select
from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.models import MarketRefreshItem, MarketRefreshRun, SectorIntradaySnapshot


def main() -> int:
    if os.environ.get("LEOPARD_RUN_LIVE") != "1":
        raise SystemExit("Set LEOPARD_RUN_LIVE=1 to confirm an intentional live Provider request.")

    with tempfile.TemporaryDirectory(prefix="leopard-cloud-readiness-live-") as temporary_root:
        root = Path(temporary_root)
        admin_password = secrets.token_urlsafe(24)
        viewer_password = secrets.token_urlsafe(24)
        settings = WebSettings(
            database_url=f"sqlite:///{root / 'acceptance.sqlite3'}",
            upload_dir=root / "uploads",
            session_secret=secrets.token_urlsafe(32),
            admin_username="acceptance-admin",
            admin_password=admin_password,
            viewer_username="acceptance-viewer",
            viewer_password=viewer_password,
            data_mode="real_local",
            market_automation_enabled=False,
        )
        app = create_app(settings)
        coordinator = app.state.intraday_coordinator
        start = coordinator.start("system_auto_resume")
        deadline = time.monotonic() + 240
        result: MarketRefreshRun | None = None
        try:
            while time.monotonic() < deadline:
                with coordinator.sessions() as session:
                    latest = session.scalar(
                        select(MarketRefreshRun).order_by(MarketRefreshRun.started_at.desc())
                    )
                    if latest is not None and latest.finished_at is not None:
                        result = latest
                        break
                time.sleep(0.5)
            if result is None:
                raise RuntimeError("scheduler_live_round_timeout")

            with coordinator.sessions() as session:
                snapshot_count = session.scalar(select(func.count()).select_from(SectorIntradaySnapshot)) or 0
                ma5_count = session.scalar(
                    select(func.count())
                    .select_from(SectorIntradaySnapshot)
                    .where(SectorIntradaySnapshot.intraday_ma5.is_not(None))
                ) or 0
                hstech_items = session.scalar(
                    select(func.count())
                    .select_from(MarketRefreshItem)
                    .where(MarketRefreshItem.sector_key == "hang_seng_tech")
                ) or 0

            provider_requests_before_viewer = coordinator._provider.request_count
            with TestClient(app) as client:
                login = client.post(
                    "/api/v1/auth/login",
                    json={"username": "acceptance-viewer", "password": viewer_password},
                )
                login.raise_for_status()
                for _ in range(10):
                    response = client.get("/api/v1/market/intraday/sectors")
                    response.raise_for_status()
            provider_requests_after_viewer = coordinator._provider.request_count

            payload = {
                "calendar_status": start["calendar_status"],
                "scheduler_registered": start["scheduler_registered"],
                "run_id": result.id,
                "requested_count": result.requested_count,
                "success_count": result.success_count,
                "failure_count": result.failure_count,
                "fresh_count": result.intraday_count,
                "stale_count": result.stale_count,
                "unsupported_count": result.unsupported_count,
                "snapshot_count": snapshot_count,
                "intraday_ma5_count": ma5_count,
                "hstech_request_count": hstech_items,
                "viewer_requests": 10,
                "viewer_provider_request_increment": (
                    provider_requests_after_viewer - provider_requests_before_viewer
                ),
                "temporary_database_removed_on_exit": True,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            denominator = len(coordinator._provider.capabilities)
            passed = (
                result.requested_count == denominator
                and result.success_count == denominator
                and result.failure_count == 0
                and result.intraday_count == denominator
                and result.stale_count == 0
                and result.unsupported_count == 1
                and snapshot_count == denominator
                and ma5_count == denominator
                and hstech_items == 0
                and provider_requests_after_viewer == provider_requests_before_viewer
            )
            return 0 if passed else 1
        finally:
            coordinator.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
