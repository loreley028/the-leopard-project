from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from fastapi import Cookie, Depends, FastAPI, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from leopard_project.config import PROJECT_ROOT, load_seed_bundle

from .auth import AuthenticationError, Principal, SessionAuth
from .database import create_session_factory
from .models import ReportStatus
from .repository import ReportRepository
from .schemas import LoginRequest, PrincipalResponse, ReportPatch, ResolveTermRequest, WithdrawRequest
from .serializers import objective_change_summary, report_payload, sector_payloads
from .services import ReportService, WebDomainError


COOKIE_NAME = "leopard_session"


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

    @classmethod
    def from_env(cls) -> "WebSettings":
        required = ("LEOPARD_SESSION_SECRET", "LEOPARD_ADMIN_PASSWORD", "LEOPARD_VIEWER_PASSWORD")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Missing local authentication environment variables: {', '.join(missing)}")
        return cls(
            database_url=os.getenv("LEOPARD_DATABASE_URL", "sqlite:///var/leopard_project.sqlite3"),
            upload_dir=PROJECT_ROOT / os.getenv("LEOPARD_UPLOAD_DIR", "var/uploads"),
            session_secret=os.environ["LEOPARD_SESSION_SECRET"],
            admin_username=os.getenv("LEOPARD_ADMIN_USERNAME", "admin"),
            admin_password=os.environ["LEOPARD_ADMIN_PASSWORD"],
            viewer_username=os.getenv("LEOPARD_VIEWER_USERNAME", "viewer"),
            viewer_password=os.environ["LEOPARD_VIEWER_PASSWORD"],
            cookie_secure=os.getenv("LEOPARD_COOKIE_SECURE", "false").lower() == "true",
        )


def create_app(settings: WebSettings | None = None, session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    settings = settings or WebSettings.from_env()
    sessions = session_factory or create_session_factory(settings.database_url)
    auth = SessionAuth(settings.session_secret, {
        settings.admin_username: (settings.admin_password, "admin"),
        settings.viewer_username: (settings.viewer_password, "viewer"),
    })
    app = FastAPI(title="The Leopard Project", version="2A-0", docs_url="/api/v1/docs")

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

    def admin(current: Principal = Depends(principal)) -> Principal:
        if current.role != "admin":
            raise WebDomainError("admin_required", "Administrator permission is required", 403)
        return current

    @app.post("/api/v1/auth/login", response_model=PrincipalResponse)
    def login(payload: LoginRequest, response: Response) -> PrincipalResponse:
        try:
            current = auth.authenticate(payload.username, payload.password)
        except AuthenticationError as exc:
            raise WebDomainError("invalid_credentials", "Invalid username or password", 401) from exc
        response.set_cookie(COOKIE_NAME, auth.issue(current), httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=28_800, path="/")
        return PrincipalResponse(username=current.username, role=current.role)

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/")

    @app.get("/api/v1/auth/me", response_model=PrincipalResponse)
    def me(current: Principal = Depends(principal)) -> PrincipalResponse:
        return PrincipalResponse(username=current.username, role=current.role)

    @app.get("/api/v1/reports")
    def reports(current: Principal = Depends(principal), session: Session = Depends(db_session)) -> list[dict]:
        return [report_payload(item) for item in ReportRepository(session).list_reports(published_only=True)]

    @app.get("/api/v1/reports/latest")
    def latest_report(current: Principal = Depends(principal), session: Session = Depends(db_session)) -> dict:
        items = ReportRepository(session).list_reports(published_only=True)
        if not items:
            raise WebDomainError("no_published_report", "No report has been published", 404)
        payload = report_payload(items[0])
        payload["change_summary"] = objective_change_summary(items[0], items[1] if len(items) > 1 else None)
        return payload

    @app.get("/api/v1/reports/{report_id}")
    def report_detail(report_id: str, current: Principal = Depends(principal), session: Session = Depends(db_session)) -> dict:
        item = ReportRepository(session).by_id(report_id)
        if item is None or (item.status != ReportStatus.PUBLISHED.value and current.role != "admin"):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        return report_payload(item)

    @app.get("/api/v1/reports/{report_id}/pdf")
    def report_pdf(report_id: str, current: Principal = Depends(principal), session: Session = Depends(db_session)) -> FileResponse:
        item = ReportRepository(session).by_id(report_id)
        if item is None or (item.status != ReportStatus.PUBLISHED.value and current.role != "admin"):
            raise WebDomainError("report_not_found", "Published report not found", 404)
        return FileResponse(settings.upload_dir / item.file.storage_filename, media_type="application/pdf", filename=f"report-{item.report_date}.pdf")

    @app.get("/api/v1/sectors")
    def sectors(current: Principal = Depends(principal), session: Session = Depends(db_session)) -> list[dict]:
        return sector_payloads(ReportRepository(session))

    @app.get("/api/v1/sectors/{sector_key}")
    def sector_detail(sector_key: str, current: Principal = Depends(principal), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        sector = next((item for item in sector_payloads(repo) if item["sector_key"] == sector_key), None)
        if sector is None:
            raise WebDomainError("sector_not_found", "Sector not found", 404)
        sector["timeline"] = [
            {"report_id": report.id, "report_date": report.report_date.isoformat(), "report_title": report.title, "summary": mention.summary}
            for report, mention in repo.sector_timeline(sector_key)
        ]
        return sector

    @app.post("/api/v1/admin/reports", status_code=201)
    async def upload_report(
        current: Principal = Depends(admin),
        session: Session = Depends(db_session),
        file: UploadFile = File(...),
    ) -> dict:
        payload = await file.read()
        report, duplicate = ReportService(ReportRepository(session), settings.upload_dir).upload(file.filename or "upload.pdf", file.content_type or "", payload, current.username)
        return {"report": report_payload(report, admin=True), "duplicate": duplicate}

    @app.get("/api/v1/admin/reports")
    def admin_reports(current: Principal = Depends(admin), session: Session = Depends(db_session)) -> list[dict]:
        return [report_payload(item, admin=True) for item in ReportRepository(session).list_reports()]

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

    @app.post("/api/v1/admin/reports/{report_id}/ready")
    def ready_report(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        return report_payload(ReportService(repo, settings.upload_dir).ready(required_report(report_id, session), current.username), admin=True)

    @app.post("/api/v1/admin/reports/{report_id}/publish")
    def publish_report(report_id: str, current: Principal = Depends(admin), session: Session = Depends(db_session)) -> dict:
        repo = ReportRepository(session)
        return report_payload(ReportService(repo, settings.upload_dir).publish(required_report(report_id, session), current.username), admin=True)

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

    return app
