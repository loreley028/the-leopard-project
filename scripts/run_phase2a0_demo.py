from __future__ import annotations

import json
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")

from starlette.testclient import TestClient

from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="leopard-phase2a0-demo-") as temporary:
        runtime = Path(temporary)
        settings = WebSettings(
            database_url=f"sqlite:///{runtime / 'demo.sqlite3'}",
            upload_dir=runtime / "uploads",
            session_secret="fixture-only-session-secret-never-for-real-use",
            admin_username="fixture-admin",
            admin_password="fixture-admin-pass!",
            viewer_username="fixture-viewer",
            viewer_password="fixture-viewer-pass!",
        )
        sessions = create_session_factory(settings.database_url)
        with TestClient(create_app(settings, sessions)) as client:
            assert client.post("/api/v1/auth/login", json={"username": settings.admin_username, "password": settings.admin_password}).status_code == 200
            payload = (ROOT / "tests/fixtures/sample_report_fixture.pdf").read_bytes()
            uploaded = client.post("/api/v1/admin/reports", files={"file": ("fixture.pdf", payload, "application/pdf")})
            report_id = uploaded.json()["report"]["id"]
            assert client.post(f"/api/v1/admin/reports/{report_id}/parse").status_code == 200
            assert client.patch(f"/api/v1/admin/reports/{report_id}", json={"report_date": "2026-07-19", "report_date_confirmed": True}).status_code == 200
            assert client.post(f"/api/v1/admin/reports/{report_id}/ready").status_code == 200
            assert client.post(f"/api/v1/admin/reports/{report_id}/publish").status_code == 200
            client.post("/api/v1/auth/logout")
            assert client.post("/api/v1/auth/login", json={"username": settings.viewer_username, "password": settings.viewer_password}).status_code == 200
            latest = client.get("/api/v1/reports/latest").json()
            sectors = client.get("/api/v1/sectors").json()
            semiconductor = client.get("/api/v1/sectors/semiconductor").json()
            result = {
                "fixture_only": True,
                "network_access": False,
                "external_ai": False,
                "flow": ["admin_login", "upload", "parse", "review", "publish", "viewer_read", "sector_timeline"],
                "published_report_visible": latest["id"] == report_id,
                "sector_count": len(sectors),
                "semiconductor_timeline_count": len(semiconductor["timeline"]),
                "runtime_persisted": False,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if all((result["published_report_visible"], result["sector_count"] == 66, result["semiconductor_timeline_count"] == 1)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
