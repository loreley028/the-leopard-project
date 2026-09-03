from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from leopard_project.web.viewer_cache import (
    ENHANCED_CACHE_SECONDS,
    PATH_MATRIX_CACHE_SECONDS,
    REPORTS_CACHE_SECONDS,
    SECTORS_CACHE_SECONDS,
    ViewerResponseCache,
    ViewerResponseCacheMiddleware,
)


def cached_app() -> tuple[FastAPI, dict[str, int]]:
    calls = {"sectors": 0, "matrix": 0, "reports": 0, "enhanced": 0, "latest": 0, "realtime": 0}
    state = {"version": 1}
    app = FastAPI()
    app.add_middleware(ViewerResponseCacheMiddleware, cache=ViewerResponseCache())

    @app.get("/api/v1/sectors")
    def sectors() -> dict:
        calls["sectors"] += 1
        return {"items": ["semiconductor", "cpo"], "version": state["version"]}

    @app.get("/api/v1/reports/report-1/path-matrix")
    def matrix() -> dict:
        calls["matrix"] += 1
        return {"dates": ["2026-09-01"], "rows": [{"sector": "半导体", "status": "强观"}], "version": state["version"]}

    @app.get("/api/v1/reports")
    def reports() -> dict:
        calls["reports"] += 1
        return {"reports": ["report-1"], "version": state["version"]}

    @app.get("/api/v1/reports/report-1/enhanced")
    def enhanced() -> dict:
        calls["enhanced"] += 1
        return {"report_id": "report-1", "version": state["version"]}

    @app.get("/api/v1/reports/latest")
    def latest() -> dict:
        calls["latest"] += 1
        return {"report_id": f"report-{state['version']}", "version": state["version"]}

    @app.get("/api/v1/market/current/matrix")
    def realtime() -> dict:
        calls["realtime"] += 1
        return {"quote": calls["realtime"]}

    @app.post("/api/v1/admin/reports/report-2/publish")
    def publish() -> dict:
        state["version"] += 1
        return {"status": "published"}

    @app.post("/api/v1/admin/report-days/2026-09-03/no-live")
    def no_live() -> dict:
        state["version"] += 1
        return {"state": "no_live"}

    return app, calls


def test_anonymous_stable_payloads_are_reused_without_changing_content() -> None:
    app, calls = cached_app()
    with TestClient(app) as client:
        first = client.get("/api/v1/reports/report-1/path-matrix?periods=20")
        second = client.get("/api/v1/reports/report-1/path-matrix?periods=20")
    assert first.status_code == 200
    assert first.headers["x-leopard-cache"] == "miss"
    assert second.headers["x-leopard-cache"] == "hit"
    assert second.content == first.content
    assert calls["matrix"] == 1


def test_successful_report_publish_invalidates_viewer_payload_cache() -> None:
    app, calls = cached_app()
    with TestClient(app) as client:
        assert client.get("/api/v1/sectors").headers["x-leopard-cache"] == "miss"
        assert client.get("/api/v1/sectors").headers["x-leopard-cache"] == "hit"
        assert client.post("/api/v1/admin/reports/report-2/publish").status_code == 200
        refreshed = client.get("/api/v1/sectors")
    assert refreshed.headers["x-leopard-cache"] == "miss"
    assert calls["sectors"] == 2


def test_publish_immediately_exposes_new_latest_and_all_report_derived_payloads() -> None:
    app, calls = cached_app()
    cached_paths = (
        "/api/v1/sectors",
        "/api/v1/reports",
        "/api/v1/reports/report-1/enhanced",
        "/api/v1/reports/report-1/path-matrix?periods=20",
    )
    with TestClient(app) as client:
        for path in cached_paths:
            assert client.get(path).json()["version"] == 1
            assert client.get(path).headers["x-leopard-cache"] == "hit"
        assert client.get("/api/v1/reports/latest").json()["version"] == 1
        assert client.post("/api/v1/admin/reports/report-2/publish").status_code == 200
        assert client.get("/api/v1/reports/latest").json()["version"] == 2
        for path in cached_paths:
            refreshed = client.get(path)
            assert refreshed.headers["x-leopard-cache"] == "miss"
            assert refreshed.json()["version"] == 2
    assert calls == {"sectors": 2, "matrix": 2, "reports": 2, "enhanced": 2, "latest": 2, "realtime": 0}


def test_no_live_mutation_immediately_invalidates_path_matrix() -> None:
    app, calls = cached_app()
    path = "/api/v1/reports/report-1/path-matrix?periods=20"
    with TestClient(app) as client:
        assert client.get(path).headers["x-leopard-cache"] == "miss"
        assert client.get(path).headers["x-leopard-cache"] == "hit"
        assert client.post("/api/v1/admin/report-days/2026-09-03/no-live").status_code == 200
        refreshed = client.get(path)
    assert refreshed.headers["x-leopard-cache"] == "miss"
    assert refreshed.json()["version"] == 2
    assert calls["matrix"] == 2


def test_realtime_market_endpoint_is_never_held_by_viewer_response_cache() -> None:
    app, calls = cached_app()
    with TestClient(app) as client:
        first = client.get("/api/v1/market/current/matrix")
        second = client.get("/api/v1/market/current/matrix")
    assert first.json()["quote"] == 1
    assert second.json()["quote"] == 2
    assert "x-leopard-cache" not in first.headers
    assert "x-leopard-cache" not in second.headers
    assert calls["realtime"] == 2


def test_ttls_follow_payload_dynamicity_and_use_invalidation_as_primary_policy() -> None:
    assert ENHANCED_CACHE_SECONDS == 5
    assert SECTORS_CACHE_SECONDS == 15 * 60
    assert PATH_MATRIX_CACHE_SECONDS == 90 * 60
    assert REPORTS_CACHE_SECONDS == 12 * 60 * 60


def test_low_traffic_safety_ttls_cover_ten_minute_sectors_and_one_hour_path_visits() -> None:
    now = [0.0]
    cache = ViewerResponseCache(clock=lambda: now[0])
    cache.put(b"sectors", 200, [], b"sectors", SECTORS_CACHE_SECONDS, cache.generation())
    cache.put(b"path", 200, [], b"path", PATH_MATRIX_CACHE_SECONDS, cache.generation())

    now[0] = 10 * 60
    assert cache.get(b"sectors") is not None
    now[0] = 60 * 60
    assert cache.get(b"path") is not None
    now[0] = PATH_MATRIX_CACHE_SECONDS + 1
    assert cache.get(b"path") is None


def test_authenticated_requests_bypass_shared_anonymous_cache() -> None:
    app, calls = cached_app()
    with TestClient(app) as client:
        first = client.get("/api/v1/sectors", headers={"Cookie": "leopard_session=viewer"})
        second = client.get("/api/v1/sectors", headers={"Cookie": "leopard_session=viewer"})
    assert "x-leopard-cache" not in first.headers
    assert "x-leopard-cache" not in second.headers
    assert calls["sectors"] == 2


def test_response_started_before_publish_cannot_repopulate_stale_cache() -> None:
    cache = ViewerResponseCache()
    generation = cache.generation()
    cache.clear()
    cache.put(b"/api/v1/sectors?", 200, [], b'{"stale":true}', 30, generation)

    assert cache.get(b"/api/v1/sectors?") is None
