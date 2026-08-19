from __future__ import annotations

import os
import json
import hashlib
import struct
import threading
import zlib
from dataclasses import dataclass
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import Cookie, Depends, FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from leopard_project.config import PROJECT_ROOT
from leopard_project.market_paths import load_market_path_registry, report_topic_for_market_path

from .auth import AuthenticationError, Principal, SessionAuth
from .database import create_session_factory
from .models import (
    LiveMarketAnchorDaily, Report, ReportDay, ReportStatus, SecurityProxyDaily,
    SectorDailyBar, SectorPathHistoryEntry, SectorResearchPreference, SpecificationDocument,
)
from .schedule import ReportSchedulePolicy
from .repository import ReportRepository
from .schemas import LoginRequest, PrincipalResponse, PublishConfirmationRequest, ReportPatch, ResolveTermRequest, ReviewIssueResolutionRequest, WithdrawRequest
from .serializers import objective_change_summary, report_payload, sector_payloads
from .services import ReportService, WebDomainError
from .enhanced import EnhancedReportService
from .enhanced_routes import register_enhanced_routes
from .intraday import IntradayRefreshCoordinator
from .market_automation import EodBackfillCoordinator
from .review_workflow import ReviewWorkflowService
from .enhanced import EnhancedReportService
from .intraday import intraday_policy, resolve_intraday_data_status
from .security_proxy_viewer import OfficialBoardAvailability, SecurityProxyViewerCache, SecurityProxyViewerService
from .live_market_anchor import LiveMarketAnchorCache, LiveShanghaiMarketAnchorService
from .market_core import MarketCoreReadService
from leopard_project.providers.tencent_standard_quote import TencentStandardSecurityQuoteProvider
from leopard_project.security_proxy_observation import SecurityProxyObservationService
from leopard_project.live_market_anchor_daily import SHANGHAI_COMPOSITE_SYMBOL


COOKIE_NAME = "leopard_session"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _pdf_bitmap_png(bitmap) -> bytes:
    """Encode PDFium's in-memory bitmap without persisting a derived preview."""
    mode = bitmap.mode
    source_channels = bitmap.n_channels
    if mode not in {"BGR", "BGRA", "BGRX", "RGB", "RGBA"}:
        raise WebDomainError("pdf_preview_unavailable", f"Unsupported PDF preview bitmap mode: {mode}", 422)
    alpha = mode in {"BGRA", "RGBA"}
    output_channels = 4 if alpha else 3
    raw = bytes(bitmap.buffer)
    scanlines = bytearray()
    for row_index in range(bitmap.height):
        row = raw[row_index * bitmap.stride : row_index * bitmap.stride + bitmap.width * source_channels]
        scanlines.append(0)
        for offset in range(0, len(row), source_channels):
            pixel = row[offset : offset + source_channels]
            if mode.startswith("BGR"):
                scanlines.extend((pixel[2], pixel[1], pixel[0]))
            else:
                scanlines.extend(pixel[:3])
            if alpha:
                scanlines.append(pixel[3])
    header = struct.pack(">IIBBBBB", bitmap.width, bitmap.height, 8, 6 if output_channels == 4 else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), 6)) + _png_chunk(b"IEND", b"")


@dataclass(frozen=True)
class WebSettings:
    database_url: str
    upload_dir: Path
    session_secret: str
    admin_username: str
    admin_password: str
    viewer_username: str
    viewer_password: str
    cookie_secure: bool = False
    data_mode: str = "test"
    market_automation_enabled: bool = False
    security_proxy_viewer_enabled: bool = False
    security_proxy_cache_ttl_seconds: int = 5
    security_proxy_error_cache_ttl_seconds: int = 30
    live_market_anchor_enabled: bool = False
    live_market_anchor_cache_ttl_seconds: int = 5
    live_market_anchor_error_cache_ttl_seconds: int = 30
    build_commit: str = "unknown"
    auto_publish_uploads: bool = False

    @classmethod
    def from_env(cls) -> "WebSettings":
        required = ("LEOPARD_SESSION_SECRET", "LEOPARD_ADMIN_PASSWORD", "LEOPARD_VIEWER_PASSWORD")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Missing local authentication environment variables: {', '.join(missing)}")
        data_mode = os.getenv("LEOPARD_DATA_MODE", "real_local")
        if data_mode not in {"test", "real_local"}:
            raise RuntimeError("LEOPARD_DATA_MODE must be test or real_local")
        default_db = "sqlite:///var/real-local/leopard_project.sqlite3" if data_mode == "real_local" else "sqlite:///var/test/leopard_project.sqlite3"
        default_upload = "var/real-local/uploads" if data_mode == "real_local" else "var/test/uploads"
        return cls(
            database_url=os.getenv("LEOPARD_DATABASE_URL", default_db),
            upload_dir=PROJECT_ROOT / os.getenv("LEOPARD_UPLOAD_DIR", default_upload),
            session_secret=os.environ["LEOPARD_SESSION_SECRET"],
            admin_username=os.getenv("LEOPARD_ADMIN_USERNAME", "admin"),
            admin_password=os.environ["LEOPARD_ADMIN_PASSWORD"],
            viewer_username=os.getenv("LEOPARD_VIEWER_USERNAME", "viewer"),
            viewer_password=os.environ["LEOPARD_VIEWER_PASSWORD"],
            cookie_secure=os.getenv("LEOPARD_COOKIE_SECURE", "false").lower() == "true",
            data_mode=data_mode,
            # Phase 2B uses a single host timer for post-close persistence.
            # Do not resurrect the legacy in-process backfill/scheduler by default.
            market_automation_enabled=os.getenv("LEOPARD_MARKET_AUTOMATION_ENABLED", "false").lower() == "true",
            security_proxy_viewer_enabled=os.getenv("SECURITY_PROXY_VIEWER_ENABLED", "false").lower() == "true",
            security_proxy_cache_ttl_seconds=int(os.getenv("SECURITY_PROXY_CACHE_TTL_SECONDS", "5")),
            security_proxy_error_cache_ttl_seconds=int(os.getenv("SECURITY_PROXY_ERROR_CACHE_TTL_SECONDS", "30")),
            live_market_anchor_enabled=os.getenv("LEOPARD_LIVE_MARKET_ANCHOR_ENABLED", "false").lower() == "true",
            live_market_anchor_cache_ttl_seconds=int(os.getenv("LEOPARD_LIVE_MARKET_ANCHOR_CACHE_TTL_SECONDS", "5")),
            live_market_anchor_error_cache_ttl_seconds=int(os.getenv("LEOPARD_LIVE_MARKET_ANCHOR_ERROR_CACHE_TTL_SECONDS", "30")),
            build_commit=os.getenv("LEOPARD_BUILD_COMMIT", "unknown"),
            auto_publish_uploads=os.getenv(
                "LEOPARD_AUTO_PUBLISH_UPLOADS", "true" if data_mode == "real_local" else "false",
            ).lower() == "true",
        )


def create_app(settings: WebSettings | None = None, session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    settings = settings or WebSettings.from_env()
    sessions = session_factory or create_session_factory(settings.database_url)
    auth = SessionAuth(settings.session_secret, {
        settings.admin_username: (settings.admin_password, "admin"),
        settings.viewer_username: (settings.viewer_password, "viewer"),
    })
    app = FastAPI(title="The Leopard Project", version="2A-0", docs_url="/api/v1/docs")
    app.state.data_mode = settings.data_mode
    intraday = IntradayRefreshCoordinator(sessions)
    eod_backfill = EodBackfillCoordinator(sessions)
    app.state.intraday_coordinator = intraday
    app.state.eod_backfill_coordinator = eod_backfill
    app.state.security_proxy_viewer = SecurityProxyViewerService(
        observation_service=SecurityProxyObservationService(provider=TencentStandardSecurityQuoteProvider()),
        enabled=settings.security_proxy_viewer_enabled,
        cache=SecurityProxyViewerCache(ttl_seconds=settings.security_proxy_cache_ttl_seconds, error_ttl_seconds=settings.security_proxy_error_cache_ttl_seconds),
    )
    app.state.live_market_anchor = LiveShanghaiMarketAnchorService(
        provider=TencentStandardSecurityQuoteProvider(),
        enabled=settings.live_market_anchor_enabled,
        cache=LiveMarketAnchorCache(
            ttl_seconds=settings.live_market_anchor_cache_ttl_seconds,
            error_ttl_seconds=settings.live_market_anchor_error_cache_ttl_seconds,
        ),
    )
    app.state.market_core = MarketCoreReadService(
        provider=TencentStandardSecurityQuoteProvider(),
        live_anchor=app.state.live_market_anchor,
        enabled=settings.security_proxy_viewer_enabled and settings.live_market_anchor_enabled,
        cache=SecurityProxyViewerCache(
            ttl_seconds=settings.security_proxy_cache_ttl_seconds,
            error_ttl_seconds=settings.security_proxy_error_cache_ttl_seconds,
        ),
    )

    def stop_market_automation() -> None:
        intraday.shutdown()
        eod_backfill.shutdown()
    app.router.add_event_handler("shutdown", stop_market_automation)

    if settings.data_mode == "real_local":
        safety_session = sessions()
        try:
            fixture_report = safety_session.scalar(select(Report).where(Report.data_origin != "real_upload").limit(1))
            fixture_bar = safety_session.scalar(select(SectorDailyBar).where(SectorDailyBar.data_source.like("%fixture%")).limit(1))
            if fixture_report or fixture_bar:
                raise RuntimeError("real_local refused to start because fixture data was detected")
        finally:
            safety_session.close()
        if settings.market_automation_enabled:
            def start_market_automation() -> None:
                # Both coordinators fetch outside SQLite transactions and use
                # short coordinated write phases.  Do not delay intraday
                # registration while a public EOD endpoint is responding.
                intraday.start("system_auto_resume")
                eod_backfill.run_async_if_needed()

            startup_thread = threading.Thread(
                target=start_market_automation,
                name="leopard-market-automation-startup",
                daemon=True,
            )
            app.state.market_automation_startup_thread = startup_thread
            startup_thread.start()

    @app.exception_handler(WebDomainError)
    async def domain_error(_: Request, exc: WebDomainError) -> JSONResponse:
        return JSONResponse({"error": {"code": exc.code, "message": str(exc)}}, status_code=exc.status_code)

    def db_session():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    def principal(session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> Principal:
        if not session_cookie:
            raise WebDomainError("authentication_required", "Authentication is required", 401)
        try:
            return auth.verify(session_cookie)
        except AuthenticationError as exc:
            raise WebDomainError("invalid_session", "The session is invalid or expired", 401) from exc

    def optional_principal(session_cookie: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> Principal | None:
        """Return an authenticated identity when present, without gating public reads.

        Published research is intentionally public-read.  A malformed or expired
        reader cookie is treated like an anonymous visit, while every mutation
        still goes through the strict ``admin`` dependency below.
        """
        if not session_cookie:
            return None
        try:
            return auth.verify(session_cookie)
        except AuthenticationError:
            return None

    def admin(current: Principal = Depends(principal)) -> Principal:
        if current.role != "admin":
            raise WebDomainError("admin_required", "Administrator permission is required", 403)
        return current

    @app.get("/api/v1/runtime")
    def runtime(current: Principal = Depends(principal)) -> dict:
        return {
            "data_mode": settings.data_mode,
            "environment": os.getenv("LEOPARD_ENVIRONMENT", settings.data_mode),
            "build_commit": settings.build_commit,
            "production_primary": None,
            "fixture_seeded": False,
            "security_proxy_viewer_enabled": settings.security_proxy_viewer_enabled,
        }

    @app.get("/api/v1/market/shanghai")
    def standalone_shanghai_market(
        current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session), limit: int = Query(default=20, ge=1, le=20),
    ) -> dict:
        """Objective Shanghai facts only; no report or PDF input is accepted."""
        return app.state.market_core.shanghai(session, limit=limit)

    @app.get("/api/v1/market/broad")
    def standalone_broad_market(
        current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session), limit: int = Query(default=20, ge=1, le=20),
    ) -> dict:
        """Independent fixed broad-market ETFs; never derived from a report."""
        return app.state.market_core.broad_market(session, limit=limit)

    @app.get("/api/v1/market/current/{scope}")
    def standalone_current_market(scope: str, current: Principal | None = Depends(optional_principal)) -> dict:
        """Current fixed-symbol quotes only; callers never provide symbols."""
        try:
            return app.state.market_core.current_quotes(scope=scope)
        except KeyError as exc:
            raise WebDomainError("market_current_scope_not_found", "Fixed market current scope not found", 404) from exc

    @app.get("/api/v1/market/proxies/{proxy_set}")
    def standalone_proxy_market(
        proxy_set: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session), limit: int = Query(default=20, ge=1, le=20),
    ) -> dict:
        """Fixed server-side proxy set only; callers never select symbols."""
        try:
            return app.state.market_core.proxies(session, proxy_set=proxy_set, limit=limit)
        except KeyError as exc:
            raise WebDomainError("market_proxy_set_not_found", "Fixed proxy set not found", 404) from exc

    def official_board_availability(session: Session, market_path_key: str) -> OfficialBoardAvailability:
        if not any(item.market_path_key == market_path_key for item in load_market_path_registry().market_paths):
            raise WebDomainError("market_path_not_found", "Market path not found", 404)
        snapshot = EnhancedReportService(session).latest_intraday(market_path_key)
        status = resolve_intraday_data_status(
            phase=intraday.status()["market_phase"], snapshot=snapshot, latest_result=None,
            now=datetime.now(timezone.utc), stale_after_minutes=intraday_policy()["stale_after_minutes"], unsupported=False,
        )
        fresh = status == "intraday_fresh"
        return OfficialBoardAvailability(market_path_key, fresh, fresh, status, None if fresh else status, snapshot.get("observed_at") if snapshot else None)

    @app.get("/api/v1/market-paths/{market_path_key}/viewer-observation")
    def viewer_observation(market_path_key: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        return app.state.security_proxy_viewer.observe(official_board_availability(session, market_path_key), session=session)

    @app.post("/api/v1/market-paths/viewer-observations/query")
    def viewer_observations_query(payload: dict, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        keys = payload.get("market_path_keys")
        if not isinstance(keys, list) or not all(isinstance(item, str) for item in keys) or not keys or len(keys) > 20:
            raise WebDomainError("invalid_market_path_keys", "market_path_keys must contain 1..20 path keys", 422)
        ordered = list(dict.fromkeys(keys))
        results = []
        for key in ordered:
            try: results.append(app.state.security_proxy_viewer.observe(official_board_availability(session, key), session=session))
            except WebDomainError as exc: results.append({"market_path_key": key, "viewer_source_mode": "unavailable", "fallback_reason": exc.code, "official_board": None, "security_proxy": None, "disclosure": None, "generated_at": datetime.now(timezone.utc).isoformat()})
        return {"items": results}

    @app.post("/api/v1/auth/login", response_model=PrincipalResponse)
    def login(payload: LoginRequest, response: Response) -> PrincipalResponse:
        try:
            current = auth.authenticate(payload.username, payload.password)
        except AuthenticationError as exc:
            raise WebDomainError("invalid_credentials", "Invalid username or password", 401) from exc
        response.set_cookie(COOKIE_NAME, auth.issue(current), httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=28_800, path="/")
        return PrincipalResponse(username=current.username, role=current.role)

    @app.post("/api/v1/auth/admin/login", response_model=PrincipalResponse)
    def admin_login(payload: LoginRequest, response: Response) -> PrincipalResponse:
        """Issue a session only for the dedicated management entry point."""
        try:
            current = auth.authenticate(payload.username, payload.password)
        except AuthenticationError as exc:
            raise WebDomainError("invalid_credentials", "Invalid username or password", 401) from exc
        if current.role != "admin":
            raise WebDomainError("admin_required", "Administrator permission is required", 403)
        response.set_cookie(COOKIE_NAME, auth.issue(current), httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=28_800, path="/")
        return PrincipalResponse(username=current.username, role=current.role)

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/")

    @app.get("/api/v1/auth/me", response_model=PrincipalResponse)
    def me(current: Principal = Depends(principal)) -> PrincipalResponse:
        return PrincipalResponse(username=current.username, role=current.role)

    @app.get("/api/v1/reports")
    def reports(current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> list[dict]:
        return [report_payload(item) for item in ReportRepository(session).list_reports(published_only=True)]

    @app.get("/api/v1/reports/latest")
    def latest_report(current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        items = ReportRepository(session).list_reports(published_only=True)
        if not items:
            raise WebDomainError("no_published_report", "No report has been published", 404)
        payload = report_payload(items[0])
        payload["change_summary"] = objective_change_summary(items[0], items[1] if len(items) > 1 else None)
        return payload

    @app.get("/api/v1/reports/{report_id}")
    def report_detail(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        item = ReportRepository(session).by_id(report_id)
        if item is None or (item.status != ReportStatus.PUBLISHED.value and (current is None or current.role != "admin")):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        return report_payload(item)

    @app.get("/api/v1/reports/{report_id}/pdf/preview")
    def report_pdf_preview_info(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        item = ReportRepository(session).by_id(report_id)
        if item is None or (item.status != ReportStatus.PUBLISHED.value and (current is None or current.role != "admin")):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        from pypdfium2 import PdfDocument

        document = PdfDocument(settings.upload_dir / item.file.storage_filename)
        try:
            page_count = len(document)
        finally:
            document.close()
        return {
            "page_count": page_count,
            "page_urls": [f"/api/v1/reports/{item.id}/pdf/preview/pages/{page}" for page in range(1, page_count + 1)],
            "source_pdf_requested": False,
            "render_mode": "server_memory_png",
        }

    @app.get("/api/v1/reports/{report_id}/pdf/preview/pages/{page_number}")
    def report_pdf_preview_page(
        report_id: str,
        page_number: int,
        current: Principal | None = Depends(optional_principal),
        session: Session = Depends(db_session),
    ) -> Response:
        item = ReportRepository(session).by_id(report_id)
        if item is None or (item.status != ReportStatus.PUBLISHED.value and (current is None or current.role != "admin")):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        from pypdfium2 import PdfDocument

        document = PdfDocument(settings.upload_dir / item.file.storage_filename)
        try:
            if page_number < 1 or page_number > len(document):
                raise WebDomainError("pdf_page_not_found", "PDF page not found", 404)
            bitmap = document[page_number - 1].render(scale=1.6)
            png = _pdf_bitmap_png(bitmap)
        finally:
            document.close()
        return Response(
            png, media_type="image/png",
            headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline"},
        )

    @app.get("/api/v1/reports/{report_id}/pdf/download")
    def report_pdf_download(report_id: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> FileResponse:
        item = ReportRepository(session).by_id(report_id)
        if item is None or (item.status != ReportStatus.PUBLISHED.value and (current is None or current.role != "admin")):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        return FileResponse(
            settings.upload_dir / item.file.storage_filename,
            media_type="application/pdf",
            filename=f"report-{item.report_date}.pdf",
            content_disposition_type="attachment",
        )

    @app.get("/api/v1/sectors")
    def sectors(
        search: str = "",
        group: str | None = None,
        path_status: str | None = None,
        mentioned: bool | None = None,
        data_status: str | None = None,
        include_low_attention: bool = False,
        low_attention_only: bool = False,
        sort: str = Query(default="research", pattern="^(research|status|daily|five_day|view_date|group)$"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=100),
        current: Principal | None = Depends(optional_principal),
        session: Session = Depends(db_session),
    ) -> list[dict]:
        rows = sector_payloads(ReportRepository(session))
        rows = [item for item in rows if search.strip() in item["sector_name"]]
        if low_attention_only:
            rows = [item for item in rows if item["is_low_attention"]]
        elif not include_low_attention and not search.strip():
            rows = [item for item in rows if not item["is_low_attention"]]
        if group:
            rows = [item for item in rows if item["group_name"] == group]
        if path_status:
            rows = [item for item in rows if item["current_path_status"] == path_status]
        if mentioned is not None:
            rows = [item for item in rows if item["mentioned_in_latest_published"] is mentioned]
        if data_status:
            rows = [item for item in rows if item["data_status"] == data_status]
        status_rank = {"turn_hold": 0, "hold": 1, "strong_watch": 2, "watch": 3, "weak_watch": 4, "turn_weak": 5, "exit": 6, "avoid": 7, "not_mentioned": 8}
        if sort == "research":
            rows.sort(key=lambda item: (
                item["group_order"],
                -int(item["is_pinned_for_research"]),
                -int(item["mentioned_in_latest_published"]),
                -int(bool(item.get("active_holding_interval"))),
                status_rank.get(item.get("effective_status") or item["current_path_status"], 99),
                -int(item.get("recent_mention_count") or 0),
                -(int((item.get("latest_view_date") or "0000-00-00").replace("-", ""))),
                item["overall_order"],
            ))
        elif sort == "status":
            rows.sort(key=lambda item: (item["group_order"], status_rank.get(item["current_path_status"], 99), -(int((item.get("latest_view_date") or "0000-00-00").replace("-", ""))), item["overall_order"]))
        elif sort == "daily":
            rows.sort(key=lambda item: (item["group_order"], -(item.get("latest_market", {}).get("daily_pct_change", -10_000) if item.get("latest_market") else -10_000), item["overall_order"]))
        elif sort == "five_day":
            rows.sort(key=lambda item: (item["group_order"], -(item.get("latest_market", {}).get("return_5d", -10_000) if item.get("latest_market") else -10_000), item["overall_order"]))
        elif sort == "view_date":
            rows.sort(key=lambda item: (item["group_order"], -(int((item.get("latest_view_date") or "0000-00-00").replace("-", ""))), item["overall_order"]))
        elif sort == "group":
            rows.sort(key=lambda item: (item["group_order"], item["overall_order"]))
        start = (page - 1) * page_size
        return rows[start:start + page_size]

    @app.post("/api/v1/admin/sectors/{sector_key}/pin")
    def pin_sector(sector_key: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        if not any(item.market_path_key == sector_key for item in load_market_path_registry().market_paths):
            raise WebDomainError("sector_not_found", "Sector not found", 404)
        item = session.get(SectorResearchPreference, sector_key)
        if item is None:
            item = SectorResearchPreference(sector_key=sector_key, is_pinned_for_research=True, updated_by=current.username)
            session.add(item)
        else:
            item.is_pinned_for_research = True
            item.updated_by = current.username
        session.commit()
        return {"sector_key": sector_key, "is_pinned_for_research": True}

    @app.delete("/api/v1/admin/sectors/{sector_key}/pin", status_code=204)
    def unpin_sector(sector_key: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> Response:
        item = session.get(SectorResearchPreference, sector_key)
        if item:
            item.is_pinned_for_research = False
            item.updated_by = current.username
            session.commit()
        return Response(status_code=204)

    @app.get("/api/v1/sectors/{sector_key}")
    def sector_detail(sector_key: str, current: Principal | None = Depends(optional_principal), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        sector = next((item for item in sector_payloads(repo) if item["sector_key"] == sector_key), None)
        if sector is None:
            raise WebDomainError("sector_not_found", "Sector not found", 404)
        sector["timeline"] = [
            {"report_id": report.id, "report_date": report.report_date.isoformat(), "report_title": report.title, "summary": mention.summary}
            for report, mention in repo.sector_timeline(report_topic_for_market_path(sector_key) or sector_key)
        ]
        return sector

    @app.post("/api/v1/admin/reports", status_code=201)
    @app.post("/api/v1/admin/reports/interpret", status_code=201)
    async def upload_report(
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
        file: UploadFile = File(...),
        report_date_hint: date | None = Form(default=None),
    ) -> dict:
        payload = await file.read()
        repo = ReportRepository(session)
        service = ReportService(repo, settings.upload_dir)
        report, duplicate = service.upload(file.filename or "upload.pdf", file.content_type or "", payload, current.username)
        interpretation_error = None
        should_interpret = not duplicate or report.status in {
            ReportStatus.UPLOADED.value,
            ReportStatus.PARSING.value,
            ReportStatus.PARSE_FAILED.value,
        }
        if should_interpret:
            try:
                report = service.parse(report, current.username)
                if report_date_hint and report.report_date and report_date_hint != report.report_date:
                    metadata = json.loads(report.interpretation_meta_json or "{}")
                    metadata.setdefault("attention_items", []).append({
                        "kind": "report_date_conflict",
                        "severity": "blocking",
                        "message": f"所选直播日期{report_date_hint}与PDF识别日期{report.report_date}不一致",
                    })
                    metadata["quality_status"] = "blocking_parse_error"
                    report.interpretation_meta_json = json.dumps(metadata, ensure_ascii=False)
                    report.interpretation_status = "needs_attention"
                    session.commit()
                EnhancedReportService(session).parse_structured_text(report, current.username)
                report = repo.by_id(report.id) or report
                if settings.auto_publish_uploads:
                    service.reject_same_date_conflict(report)
                    # The daily Admin route is intentionally fail-closed: any
                    # warning or blocking condition leaves the report out of
                    # publication and returns the ordinary review payload.
                    service.publish_strict(report, current.username)
                    report = repo.by_id(report.id) or report
            except WebDomainError as exc:
                if exc.code == "report_date_conflict":
                    service.mark_staged_conflict(report, current.username)
                    raise
                interpretation_error = {"code": exc.code, "message": str(exc)}
                report = repo.by_id(report.id) or report
        else:
            EnhancedReportService(session).ensure_structure(report, current.username)
        enhanced = EnhancedReportService(session)
        interpretation = enhanced.interpretation(report)
        interpretation["review_workflow"] = ReviewWorkflowService(session).payload(report, interpretation["path_entry_count"])
        return {
            "report": report_payload(report, admin=True),
            "interpretation": interpretation,
            "duplicate": duplicate,
            "publication": "already_published" if duplicate and report.status == ReportStatus.PUBLISHED.value else (
                "published" if report.status == ReportStatus.PUBLISHED.value else "needs_review"
            ),
            "interpretation_error": interpretation_error,
            "processing_steps": [
                "正在校验PDF",
                "正在读取报告",
                "正在识别日期和章节",
                "正在整理板块观点",
                "解读完成" if report.interpretation_status != "failed" else "解读失败",
            ],
        }

    @app.get("/api/v1/admin/reports")
    def admin_reports(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> list[dict]:
        return [report_payload(item, admin=True) for item in ReportRepository(session).list_reports()]

    @app.get("/api/v1/admin/report-days")
    def report_days(
        start: date,
        end: date,
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
    ) -> list[dict]:
        if end < start or (end - start).days > 62:
            raise WebDomainError("invalid_date_range", "日期范围必须为正且不超过63天", 422)
        policy = ReportSchedulePolicy.load_v2()
        reports = ReportRepository(session).list_reports()
        persisted = {
            item.report_date: item
            for item in session.scalars(select(ReportDay).where(ReportDay.report_date >= start, ReportDay.report_date <= end))
        }
        output = []
        day = start
        while day <= end:
            day_reports = [item for item in reports if item.report_date == day]
            record = persisted.get(day)
            default = "pending_upload" if policy.report_expected(day) else "normally_no_report"
            state = record.state if record else (
                "published" if any(item.status == "published" and item.is_current for item in day_reports)
                else "needs_confirmation" if day_reports
                else default
            )
            output.append({
                "report_date": day.isoformat(),
                "weekday": day.strftime("%A").upper(),
                "expected_status": default,
                "state": state,
                "skip_reason": record.skip_reason if record else "",
                "reports": [report_payload(item, admin=True) for item in day_reports],
            })
            day += timedelta(days=1)
        return output

    @app.post("/api/v1/admin/report-days/{report_date}/skip")
    def skip_report_day(report_date: date, payload: dict, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        record = session.scalar(select(ReportDay).where(ReportDay.report_date == report_date))
        if record is None:
            record = ReportDay(report_date=report_date)
            session.add(record)
        record.state = "skipped"
        record.skip_reason = str(payload.get("reason", ""))[:1000]
        record.confirmed_by = current.username
        session.commit()
        return {"report_date": report_date.isoformat(), "state": record.state, "skip_reason": record.skip_reason}

    @app.delete("/api/v1/admin/report-days/{report_date}/skip", status_code=204)
    def cancel_report_day_skip(report_date: date, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> None:
        record = session.scalar(select(ReportDay).where(ReportDay.report_date == report_date))
        if record:
            session.delete(record)
            session.commit()

    @app.get("/api/v1/admin/reports/{report_id}")
    def admin_report(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        item = ReportRepository(session).by_id(report_id)
        if item is None:
            raise WebDomainError("report_not_found", "Report not found", 404)
        return report_payload(item, admin=True)

    def required_report(report_id: str, session: Session):
        item = ReportRepository(session).by_id(report_id)
        if item is None:
            raise WebDomainError("report_not_found", "Report not found", 404)
        return item

    @app.post("/api/v1/admin/reports/{report_id}/parse")
    def parse_report(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        return report_payload(ReportService(repo, settings.upload_dir).parse(required_report(report_id, session), current.username), admin=True)

    @app.patch("/api/v1/admin/reports/{report_id}")
    def patch_report(report_id: str, payload: ReportPatch, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        updated = ReportService(repo, settings.upload_dir).patch(required_report(report_id, session), payload.model_dump(exclude_unset=True), current.username)
        return report_payload(updated, admin=True)

    @app.get("/api/v1/admin/reports/{report_id}/interpretation")
    def interpretation_result(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        interpretation = EnhancedReportService(session).interpretation(report)
        interpretation["review_workflow"] = ReviewWorkflowService(session).payload(
            report, interpretation["path_entry_count"]
        )
        return {
            "report": report_payload(report, admin=True),
            "interpretation": interpretation,
        }

    @app.post("/api/v1/admin/reports/{report_id}/review-issues/{issue_key}/resolve")
    def resolve_review_issue(
        report_id: str,
        issue_key: str,
        payload: ReviewIssueResolutionRequest,
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
    ) -> dict:
        report = required_report(report_id, session)
        ReviewWorkflowService(session).resolve(
            report, issue_key, payload.final_value, current.username,
            source=payload.resolution_source, note=payload.optional_note,
        )
        interpretation = EnhancedReportService(session).interpretation(report)
        interpretation["review_workflow"] = ReviewWorkflowService(session).payload(report, interpretation["path_entry_count"])
        return {"report": report_payload(report, admin=True), "interpretation": interpretation}

    @app.post("/api/v1/admin/reports/{report_id}/review-issues/bulk-accept")
    def bulk_accept_review_issues(
        report_id: str,
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
    ) -> dict:
        report = required_report(report_id, session)
        ReviewWorkflowService(session).bulk_accept(report, current.username)
        interpretation = EnhancedReportService(session).interpretation(report)
        interpretation["review_workflow"] = ReviewWorkflowService(session).payload(report, interpretation["path_entry_count"])
        return {"report": report_payload(report, admin=True), "interpretation": interpretation}

    @app.get("/api/v1/admin/reports/{report_id}/interpretation-status")
    def interpretation_status(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        report = required_report(report_id, session)
        metadata = json.loads(report.interpretation_meta_json or "{}")
        return {
            "report_id": report.id,
            "status": report.interpretation_status,
            "attention_count": len(metadata.get("attention_items", [])),
            "recoverable": report.interpretation_status in {"failed", "needs_attention"},
        }

    @app.patch("/api/v1/admin/reports/{report_id}/interpretation")
    def patch_interpretation(
        report_id: str,
        payload: ReportPatch,
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
    ) -> dict:
        repo = ReportRepository(session)
        report = ReportService(repo, settings.upload_dir).patch(
            required_report(report_id, session),
            payload.model_dump(exclude_unset=True),
            current.username,
        )
        interpretation = EnhancedReportService(session).interpretation(report)
        interpretation["review_workflow"] = ReviewWorkflowService(session).payload(report, interpretation["path_entry_count"])
        return {
            "report": report_payload(report, admin=True),
            "interpretation": interpretation,
        }

    @app.post("/api/v1/admin/reports/{report_id}/ready")
    def ready_report(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        return report_payload(ReportService(repo, settings.upload_dir).ready(required_report(report_id, session), current.username), admin=True)

    @app.post("/api/v1/admin/reports/{report_id}/publish")
    def publish_report(report_id: str, payload: PublishConfirmationRequest | None = None, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        confirmation = payload or PublishConfirmationRequest()
        report = required_report(report_id, session)
        # Snapshotting is an internal part of the one-click publication path.
        # Missing auxiliary market data remains non-blocking, while any bars
        # already available for the confirmed date become immutable evidence.
        if report.market_as_of_date_confirmed and report.market_as_of_date:
            EnhancedReportService(session).freeze_market_snapshot(report, current.username)
        return report_payload(ReportService(repo, settings.upload_dir).publish(
            report, current.username,
            confirm_warnings=confirmation.confirm_warnings, warning_note=confirmation.warning_note,
        ), admin=True)

    @app.post("/api/v1/admin/reports/{report_id}/withdraw")
    def withdraw_report(report_id: str, payload: WithdrawRequest, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        return report_payload(ReportService(repo, settings.upload_dir).withdraw(required_report(report_id, session), current.username, payload.reason), admin=True)

    @app.post("/api/v1/admin/unmapped-terms/{term_id}/resolve")
    def resolve_term(term_id: str, payload: ResolveTermRequest, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        term = repo.get_unmapped(term_id)
        if term is None:
            raise WebDomainError("unmapped_term_not_found", "Unmapped term not found", 404)
        resolved = ReportService(repo, settings.upload_dir).resolve_term(term, payload.sector_key, current.username)
        return {"id": resolved.id, "status": resolved.status, "resolved_sector_key": resolved.resolved_sector_key}

    @app.get("/api/v1/admin/summary")
    def admin_summary(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        reports = ReportRepository(session).list_reports()
        return {
            "drafts": sum(item.status not in {"published", "withdrawn"} for item in reports),
            "needs_review": sum(item.status == "needs_review" for item in reports),
            "published": sum(item.status == "published" for item in reports),
            "parse_failed": sum(item.status == "parse_failed" for item in reports),
            "unmapped_terms": sum(term.status == "unresolved" for item in reports for term in item.unmapped_terms),
        }

    @app.get("/api/v1/admin/operations/status")
    def admin_operations_status(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        """Small, read-only daily-operation status; it never triggers a capture."""
        latest_report = session.scalar(select(Report).where(
            Report.status == ReportStatus.PUBLISHED.value,
            Report.is_current.is_(True),
        ).order_by(Report.report_date.desc(), Report.published_at.desc()))
        snapshot_dates = [
            latest_report.report_date if latest_report and latest_report.report_date else None,
            session.scalar(select(func.max(LiveMarketAnchorDaily.trading_date))),
            session.scalar(select(func.max(SecurityProxyDaily.trading_date))),
        ]
        data_snapshot_date = max((item for item in snapshot_dates if item is not None), default=None)
        from leopard_project.historical_market_daily import expected_latest_completed_trading_day
        from leopard_project.security_proxy_daily import market_core_security_symbols
        from leopard_project.security_proxy_observation import APPROVED, load_security_proxy_registry
        from leopard_project.report_registry import load_report_registry
        from leopard_project.dormant_sectors import classify_dormant_sector
        from .market_date_axis import market_core_completed_dates
        expected = expected_latest_completed_trading_day(datetime.now(SHANGHAI))
        symbols = market_core_security_symbols()
        current_symbols = set(session.scalars(select(SecurityProxyDaily.symbol).where(
            SecurityProxyDaily.symbol.in_(symbols), SecurityProxyDaily.trading_date == expected,
        )))
        shanghai_fresh = session.scalar(select(LiveMarketAnchorDaily.id).where(
            LiveMarketAnchorDaily.symbol == SHANGHAI_COMPOSITE_SYMBOL,
            LiveMarketAnchorDaily.trading_date == expected,
        )) is not None
        active_objects = [item for item in load_report_registry() if item.lifecycle == "active"]
        definitions = {item.market_path_key: item for item in load_security_proxy_registry() if item.status == APPROVED}
        mapped_active = [item for item in active_objects if item.sector_key in definitions]
        entries_by_sector = {
            item.sector_key: []
            for item in active_objects
        }
        for entry in session.scalars(select(SectorPathHistoryEntry).where(SectorPathHistoryEntry.sector_key.in_(entries_by_sector))):
            entries_by_sector[entry.sector_key].append(entry)
        completed_dates = market_core_completed_dates(session)
        dormant_count = sum(classify_dormant_sector(entries_by_sector[item.sector_key], completed_dates).is_dormant for item in active_objects)
        return {
            "build_commit": settings.build_commit,
            "data_snapshot_date": data_snapshot_date.isoformat() if data_snapshot_date else None,
            "latest_published_report_date": latest_report.report_date.isoformat() if latest_report and latest_report.report_date else None,
            "latest_live_market_anchor_eod_date": session.scalar(select(func.max(LiveMarketAnchorDaily.trading_date))),
            "latest_security_proxy_eod_date": session.scalar(select(func.max(SecurityProxyDaily.trading_date))),
            "capture_mode": "host_systemd_timer",
            "capture_schedule": "Mon-Fri 15:20 Asia/Shanghai; controlled calendar may skip",
            "market_history_status": {
                "expected_latest_completed": expected.isoformat(),
                "shanghai": "fresh" if shanghai_fresh else "stale_history",
                "security_coverage": {"through_expected": len(current_symbols), "required": len(symbols)},
                "report_active_sectors": len(active_objects),
                "market_mapped": len(mapped_active),
                "market_ready_through_expected": sum(
                    definition.primary_observation_symbol in current_symbols
                    for definition in (definitions[item.sector_key] for item in mapped_active)
                ),
                "unavailable": len(active_objects) - len(mapped_active),
                "dormant_20d": dormant_count,
            },
        }

    specification_dir = settings.upload_dir.parent / "specifications"

    @app.get("/api/v1/admin/specifications")
    def specifications(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> list[dict]:
        rows = list(session.scalars(select(SpecificationDocument).order_by(SpecificationDocument.uploaded_at.desc())))
        return [{
            "id": item.id, "specification_name": item.specification_name, "version": item.version,
            "effective_date": item.effective_date.isoformat() if item.effective_date else None,
            "original_filename": item.original_filename, "sha256": item.sha256, "note": item.note,
            "is_current": item.is_current, "replaces_specification_id": item.replaces_specification_id,
            "uploaded_by": item.uploaded_by, "uploaded_at": item.uploaded_at.isoformat(),
            "file_url": f"/api/v1/admin/specifications/{item.id}/file",
        } for item in rows]

    @app.post("/api/v1/admin/specifications", status_code=201)
    async def upload_specification(
        specification_name: str = Form(...), version: str = Form(...),
        effective_date: date | None = Form(default=None), note: str = Form(default=""),
        file: UploadFile = File(...), current: Principal = Depends(admin), session: Session = Depends(db_session),
    ) -> dict:
        filename = file.filename or "specification"
        suffix = Path(filename).suffix.lower()
        allowed = {".pdf", ".docx", ".md", ".txt"}
        if suffix not in allowed:
            raise WebDomainError("specification_type", "制作规范只支持PDF、DOCX、Markdown或TXT", 422)
        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise WebDomainError("specification_too_large", "制作规范不得超过20MB", 413)
        digest = hashlib.sha256(content).hexdigest()
        existing = session.scalar(select(SpecificationDocument).where(SpecificationDocument.sha256 == digest))
        if existing:
            return {"id": existing.id, "duplicate": True, "sha256": digest}
        current_spec = session.scalar(select(SpecificationDocument).where(
            SpecificationDocument.specification_name == specification_name,
            SpecificationDocument.is_current.is_(True),
        ))
        specification_dir.mkdir(parents=True, exist_ok=True)
        storage_name = f"{uuid4().hex}{suffix}"
        (specification_dir / storage_name).write_bytes(content)
        item = SpecificationDocument(
            specification_name=specification_name.strip(), version=version.strip(), effective_date=effective_date,
            original_filename=filename, storage_filename=storage_name,
            content_type=file.content_type or "application/octet-stream", size_bytes=len(content), sha256=digest,
            note=note.strip(), is_current=False,
            replaces_specification_id=current_spec.id if current_spec else None, uploaded_by=current.username,
        )
        session.add(item); session.commit()
        return {"id": item.id, "duplicate": False, "sha256": digest}

    @app.get("/api/v1/admin/specifications/{spec_id}")
    def specification(spec_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        item = session.get(SpecificationDocument, spec_id)
        if item is None: raise WebDomainError("specification_not_found", "制作规范不存在", 404)
        return {"id": item.id, "specification_name": item.specification_name, "version": item.version,
                "effective_date": item.effective_date.isoformat() if item.effective_date else None,
                "original_filename": item.original_filename, "sha256": item.sha256, "note": item.note,
                "is_current": item.is_current, "replaces_specification_id": item.replaces_specification_id}

    @app.get("/api/v1/admin/specifications/{spec_id}/file")
    def specification_file(spec_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> FileResponse:
        item = session.get(SpecificationDocument, spec_id)
        if item is None: raise WebDomainError("specification_not_found", "制作规范不存在", 404)
        return FileResponse(specification_dir / item.storage_filename, media_type=item.content_type,
                            filename=item.original_filename, content_disposition_type="attachment")

    @app.post("/api/v1/admin/specifications/{spec_id}/set-current")
    def set_current_specification(spec_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        item = session.get(SpecificationDocument, spec_id)
        if item is None: raise WebDomainError("specification_not_found", "制作规范不存在", 404)
        for previous in session.scalars(select(SpecificationDocument).where(SpecificationDocument.specification_name == item.specification_name)):
            previous.is_current = previous.id == item.id
        session.commit()
        return {"id": item.id, "is_current": True}

    register_enhanced_routes(
        app, sessions, optional_principal, admin, required_report, data_mode=settings.data_mode,
        intraday=intraday, eod_backfill=eod_backfill, live_market_anchor=app.state.live_market_anchor,
    )
    return app
