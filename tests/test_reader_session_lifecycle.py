from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from starlette.testclient import TestClient
from sqlalchemy import event

from leopard_project.security_proxy_observation import SecurityProxyObservation, load_security_proxy_registry
from leopard_project.web.app import WebSettings, create_app
from leopard_project.web.database import create_session_factory
from leopard_project.web.security_proxy_viewer import SecurityProxyViewerService


def _settings(tmp_path) -> WebSettings:
    return WebSettings(
        database_url=f"sqlite:///{tmp_path / 'reader.sqlite3'}",
        upload_dir=tmp_path / "uploads",
        session_secret="reader-session-lifecycle-test-secret",
        admin_username="admin",
        admin_password="admin-password",
        viewer_username="viewer",
        viewer_password="viewer-password",
        security_proxy_viewer_enabled=True,
    )


class _PoolProbe:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.checked_out = 0
        self.maximum_checked_out = 0
        event.listen(engine, "checkout", self._checkout)
        event.listen(engine, "checkin", self._checkin)

    def _checkout(self, *_args) -> None:
        self.checked_out += 1
        self.maximum_checked_out = max(self.maximum_checked_out, self.checked_out)

    def _checkin(self, *_args) -> None:
        self.checked_out -= 1

    def close(self) -> None:
        event.remove(self.engine, "checkout", self._checkout)
        event.remove(self.engine, "checkin", self._checkin)


def test_sector_detail_repeated_requests_do_not_exhaust_pool(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    engine = sessions.kw["bind"]
    probe = _PoolProbe(engine)
    try:
        with TestClient(create_app(settings, sessions)) as client:
            for _ in range(100):
                response = client.get("/api/v1/sectors/cpo/research?path_periods=20&market_days=20")
                assert response.status_code == 200
        assert probe.maximum_checked_out == 1
        assert probe.checked_out == 0
        assert engine.pool.checkedout() == 0
    finally:
        probe.close()


def test_reader_light_concurrency_bounds_connections_and_returns_them(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    engine = sessions.kw["bind"]
    probe = _PoolProbe(engine)
    app = create_app(settings, sessions)
    paths = (
        "/api/v1/reports",
        "/api/v1/market/shanghai",
        "/api/v1/sectors/cpo/research?path_periods=20&market_days=20",
        "/api/v1/sectors/semiconductor/research?path_periods=20&market_days=20",
        "/api/v1/sectors/liquid_cooling/research?path_periods=20&market_days=20",
    )
    try:
        with TestClient(app) as client:
            with ThreadPoolExecutor(max_workers=5) as executor:
                responses = list(executor.map(client.get, paths))
        assert [response.status_code for response in responses] == [200] * 5
        assert probe.maximum_checked_out <= 5
        assert probe.checked_out == 0
        assert engine.pool.checkedout() == 0
    finally:
        probe.close()


def test_preview_viewer_releases_database_before_proxy_fetch(tmp_path) -> None:
    """The Reader route must not retain SQLite while a proxy fetch waits."""
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    engine = sessions.kw["bind"]
    registry = load_security_proxy_registry()

    class InspectingObservationService:
        def __init__(self) -> None:
            self.registry = registry
            self.checked_out_during_fetch: int | None = None

        def observe(self, keys, *, enable_provider=False):
            self.checked_out_during_fetch = engine.pool.checkedout()
            definition = next(item for item in self.registry if item.market_path_key == keys[0])
            now = datetime(2026, 8, 20, tzinfo=timezone.utc)
            return (SecurityProxyObservation(
                definition.market_path_key, definition.display_name, "security_proxy", "代理观察",
                definition.recommended_display_mode, True, now, now, (), definition.disclosure, "available",
            ),)

    observation_service = InspectingObservationService()
    app = create_app(settings, sessions)
    app.state.security_proxy_viewer = SecurityProxyViewerService(observation_service=observation_service, enabled=True)
    with TestClient(app) as client:
        response = client.get("/api/v1/market-paths/cpo/viewer-observation")
    assert response.status_code == 200
    assert observation_service.checked_out_during_fetch == 0
    assert engine.pool.checkedout() == 0


def test_market_refresh_status_cycles_keep_pool_at_steady_state(tmp_path) -> None:
    settings = _settings(tmp_path)
    sessions = create_session_factory(settings.database_url)
    engine = sessions.kw["bind"]
    probe = _PoolProbe(engine)
    app = create_app(settings, sessions)
    try:
        for _ in range(30):
            assert app.state.intraday_coordinator.status()["session_status"] == "paused"
        assert probe.maximum_checked_out == 1
        assert probe.checked_out == 0
        assert engine.pool.checkedout() == 0
    finally:
        probe.close()
