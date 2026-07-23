from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class ReportStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    NEEDS_REVIEW = "needs_review"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    PARSE_FAILED = "parse_failed"


ALLOWED_TRANSITIONS: dict[ReportStatus, set[ReportStatus]] = {
    ReportStatus.UPLOADED: {ReportStatus.PARSING},
    ReportStatus.PARSING: {ReportStatus.NEEDS_REVIEW, ReportStatus.PARSE_FAILED},
    ReportStatus.NEEDS_REVIEW: {ReportStatus.PARSING, ReportStatus.READY_TO_PUBLISH},
    ReportStatus.READY_TO_PUBLISH: {ReportStatus.NEEDS_REVIEW, ReportStatus.PUBLISHED},
    ReportStatus.PUBLISHED: {ReportStatus.WITHDRAWN},
    ReportStatus.WITHDRAWN: set(),
    ReportStatus.PARSE_FAILED: {ReportStatus.PARSING},
}


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), default="待复核报告")
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    candidate_report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_date_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default=ReportStatus.UPLOADED.value)
    core_view: Mapped[str] = mapped_column(Text, default="")
    market_path: Mapped[str] = mapped_column(Text, default="")
    risk_warning: Mapped[str] = mapped_column(Text, default="")
    focus_sectors_json: Mapped[str] = mapped_column(Text, default="[]")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    parse_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120))
    published_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    file: Mapped["ReportFile"] = relationship(back_populates="report", uselist=False, cascade="all, delete-orphan")
    sections: Mapped[list["ReportSection"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    mentions: Mapped[list["SectorMention"]] = relationship(back_populates="report", cascade="all, delete-orphan")
    unmapped_terms: Mapped[list["UnmappedTerm"]] = relationship(back_populates="report", cascade="all, delete-orphan")


class ReportFile(Base):
    __tablename__ = "report_files"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(300))
    storage_filename: Mapped[str] = mapped_column(String(100))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    report: Mapped[Report] = relationship(back_populates="file")


class ReportSection(Base):
    __tablename__ = "report_sections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    section_type: Mapped[str] = mapped_column(String(60))
    heading: Mapped[str] = mapped_column(String(200))
    raw_text: Mapped[str] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(30), default="explicit")
    report: Mapped[Report] = relationship(back_populates="sections")


class SectorMention(Base):
    __tablename__ = "sector_mentions"
    __table_args__ = (UniqueConstraint("report_id", "sector_key", name="uq_report_sector"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    sector_name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    source_text: Mapped[str] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(30), default="explicit")
    manually_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    report: Mapped[Report] = relationship(back_populates="mentions")


class UnmappedTerm(Base):
    __tablename__ = "unmapped_terms"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    term: Mapped[str] = mapped_column(String(200))
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="unresolved")
    resolved_sector_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report: Mapped[Report] = relationship(back_populates="unmapped_terms")


class ReportRevision(Base):
    __tablename__ = "report_revisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    changed_by: Mapped[str] = mapped_column(String(120))
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PublishEvent(Base):
    __tablename__ = "publish_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(64))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
