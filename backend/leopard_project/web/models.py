from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid4().hex


class ReportStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"
    PARSE_FAILED = "parse_failed"


ALLOWED_TRANSITIONS: dict[ReportStatus, set[ReportStatus]] = {
    ReportStatus.UPLOADED: {ReportStatus.PARSING},
    ReportStatus.PARSING: {ReportStatus.NEEDS_REVIEW, ReportStatus.BLOCKED, ReportStatus.PARSE_FAILED},
    ReportStatus.NEEDS_REVIEW: {ReportStatus.PARSING, ReportStatus.BLOCKED, ReportStatus.READY_TO_PUBLISH},
    ReportStatus.BLOCKED: {ReportStatus.PARSING, ReportStatus.NEEDS_REVIEW, ReportStatus.READY_TO_PUBLISH},
    ReportStatus.READY_TO_PUBLISH: {ReportStatus.PARSING, ReportStatus.NEEDS_REVIEW, ReportStatus.PUBLISHED},
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
    detected_report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_date_source: Mapped[str] = mapped_column(String(40), default="unavailable")
    report_date_confidence: Mapped[str] = mapped_column(String(20), default="low")
    report_date_confirmed_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    target_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    market_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    candidate_market_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    market_as_of_date_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    interpretation_status: Mapped[str] = mapped_column(String(30), default="uploading")
    interpretation_meta_json: Mapped[str] = mapped_column(Text, default="{}")
    enhanced_status: Mapped[str] = mapped_column(String(30), default="not_started")
    enhanced_revision_number: Mapped[int] = mapped_column(Integer, default=0)
    template_version: Mapped[str] = mapped_column(String(20), default="unknown")
    revision_number: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    replaces_report_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision_note: Mapped[str] = mapped_column(Text, default="")
    data_origin: Mapped[str] = mapped_column(String(30), default="real_upload")
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


class ReportReviewIssue(Base):
    __tablename__ = "report_review_issues"
    __table_args__ = (UniqueConstraint("report_id", "issue_key", name="uq_report_review_issue"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    issue_key: Mapped[str] = mapped_column(String(240))
    issue_type: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(30), default="suggestion")
    subject_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    subject_label: Mapped[str] = mapped_column(String(200), default="报告内容")
    explanation: Mapped[str] = mapped_column(Text)
    original_value_json: Mapped[str] = mapped_column(Text, default="null")
    suggested_value_json: Mapped[str] = mapped_column(Text, default="null")
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    final_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    optional_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ReportDay(Base):
    __tablename__ = "report_days"
    __table_args__ = (UniqueConstraint("report_date", name="uq_report_day_date"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    state: Mapped[str] = mapped_column(String(30), default="pending_upload")
    skip_reason: Mapped[str] = mapped_column(Text, default="")
    confirmed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SectorCatalogVersion(Base):
    __tablename__ = "sector_catalog_versions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(40), unique=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(120), default="configured_catalog")


class SectorCatalogEntry(Base):
    __tablename__ = "sector_catalog_entries"
    __table_args__ = (UniqueConstraint("catalog_version", "sector_key", name="uq_catalog_version_sector"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    catalog_version: Mapped[str] = mapped_column(String(40), index=True)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    group_key: Mapped[str] = mapped_column(String(120))
    display_order: Mapped[int] = mapped_column(Integer)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    support_status: Mapped[str] = mapped_column(String(40))


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


class SectorPathEntry(Base):
    __tablename__ = "sector_path_entries"
    __table_args__ = (UniqueConstraint("report_id", "sector_key", name="uq_report_path_sector"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    sector_name: Mapped[str] = mapped_column(String(120))
    path_status: Mapped[str] = mapped_column(String(30))
    explicitly_mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    judgement_summary: Mapped[str] = mapped_column(Text, default="")
    source_text_reference: Mapped[str] = mapped_column(Text, default="")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    validation_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    quality_status: Mapped[str] = mapped_column(String(40), default="needs_attention")
    review_status: Mapped[str] = mapped_column(String(30), default="needs_review")
    manually_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_id: Mapped[str] = mapped_column(String(32), default="initial")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SectorPathHistoryEntry(Base):
    """Frozen per-report-date path ledger recovered from a complete PDF matrix.

    This is deliberately separate from ``SectorPathEntry``: the latter belongs
    to an uploaded detailed report, while this ledger also contains dates for
    which the original PDF has not yet been uploaded.
    """

    __tablename__ = "sector_path_history_entries"
    __table_args__ = (
        UniqueConstraint("sector_key", "path_report_date", name="uq_sector_path_history_date"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    sector_name: Mapped[str] = mapped_column(String(120))
    path_report_date: Mapped[date] = mapped_column(Date, index=True)
    path_status: Mapped[str] = mapped_column(String(30))
    source_report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    detail_report_id: Mapped[str | None] = mapped_column(ForeignKey("reports.id"), nullable=True, index=True)
    market_as_of_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    frozen_daily_pct_change: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    market_data_status: Mapped[str] = mapped_column(String(40), default="unavailable")
    source_pdf_sha256: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(20), default="unknown")
    source_kind: Mapped[str] = mapped_column(String(40), default="full_pdf_matrix")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PathHistoryImport(Base):
    __tablename__ = "path_history_imports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), unique=True, index=True)
    source_pdf_sha256: Mapped[str] = mapped_column(String(64), index=True)
    template_version: Mapped[str] = mapped_column(String(20), default="unknown")
    date_count: Mapped[int] = mapped_column(Integer)
    sector_count: Mapped[int] = mapped_column(Integer)
    inserted_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    difference_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="initialized")
    differences_json: Mapped[str] = mapped_column(Text, default="[]")
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SectorAssessment(Base):
    __tablename__ = "sector_assessments"
    __table_args__ = (UniqueConstraint("report_id", "sector_key", name="uq_report_assessment_sector"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    sector_name: Mapped[str] = mapped_column(String(120))
    current_path_status: Mapped[str] = mapped_column(String(30))
    explicitly_mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    recent_path_summary: Mapped[str] = mapped_column(Text, default="")
    current_judgement: Mapped[str] = mapped_column(Text, default="")
    main_basis: Mapped[str] = mapped_column(Text, default="")
    observation_condition: Mapped[str] = mapped_column(Text, default="")
    source_section: Mapped[str] = mapped_column(String(120), default="板块详细汇总")
    source_text_reference: Mapped[str] = mapped_column(Text, default="")
    extraction_method: Mapped[str] = mapped_column(String(60), default="unavailable")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text_excerpt: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    validation_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    quality_status: Mapped[str] = mapped_column(String(40), default="needs_attention")
    review_status: Mapped[str] = mapped_column(String(30), default="needs_review")
    manually_modified: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_id: Mapped[str] = mapped_column(String(32), default="initial")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SectorDailyBar(Base):
    __tablename__ = "sector_daily_bars"
    __table_args__ = (UniqueConstraint("sector_key", "trade_date", name="uq_sector_trade_date"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    high: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    low: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    close: Mapped[float] = mapped_column(Numeric(20, 6))
    pre_close: Mapped[float] = mapped_column(Numeric(20, 6))
    daily_pct_change: Mapped[float] = mapped_column(Numeric(16, 6))
    volume: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    turnover_rate: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    liquidity_status: Mapped[str] = mapped_column(String(30), default="unavailable")
    eod_status: Mapped[str] = mapped_column(String(40))
    data_source: Mapped[str] = mapped_column(String(100))
    provider_role: Mapped[str] = mapped_column(String(60))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_response_hash: Mapped[str] = mapped_column(String(64))


class SecurityProxyDaily(Base):
    """Completed daily closes for the fixed, manually curated proxy securities."""

    __tablename__ = "security_proxy_daily"
    __table_args__ = (UniqueConstraint("symbol", "trading_date", name="uq_security_proxy_daily_symbol_date"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Numeric(20, 6))
    open: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    high: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    low: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    amount_yuan: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    quote_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[str] = mapped_column(String(100))


class SectorIndicatorSnapshot(Base):
    __tablename__ = "sector_indicator_snapshots"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    daily_bar_id: Mapped[str] = mapped_column(ForeignKey("sector_daily_bars.id"), unique=True, index=True)
    return_5d: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    return_10d: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    return_20d: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    ma5: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    ma10: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    ma20: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    close_vs_ma5_pct: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    close_vs_ma10_pct: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    close_vs_ma20_pct: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    volume_average_5d: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    volume_average_20d: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    volume_ratio_5d: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    volume_ratio_20d: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    history_status: Mapped[str] = mapped_column(String(40), default="complete")


class ReportSectorMarketSnapshot(Base):
    __tablename__ = "report_sector_market_snapshots"
    __table_args__ = (UniqueConstraint("report_id", "sector_key", "revision_number", name="uq_report_sector_snapshot_revision"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    market_as_of_date: Mapped[date] = mapped_column(Date)
    snapshot_json: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    revision_number: Mapped[int] = mapped_column(Integer, default=1)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MarketRefreshRun(Base):
    __tablename__ = "market_refresh_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    mode: Mapped[str] = mapped_column(String(40))
    provider_role: Mapped[str] = mapped_column(String(60))
    requested_count: Mapped[int] = mapped_column(Integer)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    intraday_count: Mapped[int] = mapped_column(Integer, default=0)
    stale_count: Mapped[int] = mapped_column(Integer, default=0)
    short_history_count: Mapped[int] = mapped_column(Integer, default=0)
    unsupported_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    requested_by: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderHealthRecord(Base):
    __tablename__ = "provider_health_records"
    __table_args__ = (UniqueConstraint("provider", "endpoint_family", name="uq_provider_health_family"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    endpoint_family: Mapped[str] = mapped_column(String(120), index=True)
    state: Mapped[str] = mapped_column(String(20), default="closed")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    recovery_successes: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MarketRefreshItem(Base):
    __tablename__ = "market_refresh_items"
    __table_args__ = (UniqueConstraint("run_id", "sector_key", name="uq_refresh_run_sector"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("market_refresh_runs.id"), index=True)
    sector_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40))
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_symbol: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lineage: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class SectorProviderNativeClose(Base):
    __tablename__ = "sector_provider_native_closes"
    __table_args__ = (
        UniqueConstraint(
            "sector_key", "provider", "provider_symbol", "trade_date",
            name="uq_sector_provider_native_close",
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    provider_symbol: Mapped[str] = mapped_column(String(120), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Numeric(20, 6))
    source_response_hash: Mapped[str] = mapped_column(String(64))
    lineage: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SectorIntradaySnapshot(Base):
    __tablename__ = "sector_intraday_snapshots"
    __table_args__ = (
        UniqueConstraint("sector_key", "observed_at", name="uq_sector_intraday_observed"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sector_key: Mapped[str] = mapped_column(String(120), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    index_value: Mapped[float] = mapped_column(Numeric(20, 6))
    pre_close: Mapped[float] = mapped_column(Numeric(20, 6))
    pct_change: Mapped[float] = mapped_column(Numeric(16, 6))
    volume: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    amount: Mapped[float | None] = mapped_column(Numeric(24, 4), nullable=True)
    provider: Mapped[str] = mapped_column(String(100))
    provider_symbol: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_role: Mapped[str] = mapped_column(String(60))
    lineage: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_status: Mapped[str] = mapped_column(String(40), default="available")
    freshness_status: Mapped[str] = mapped_column(String(40), default="intraday_fresh")
    intraday_ma5: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    intraday_vs_ma5: Mapped[float | None] = mapped_column(Numeric(16, 6), nullable=True)
    native_history_status: Mapped[str] = mapped_column(String(40), default="unavailable")
    data_status: Mapped[str] = mapped_column(String(40))
    response_hash: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_run_id: Mapped[str | None] = mapped_column(ForeignKey("market_refresh_runs.id"), nullable=True, index=True)


class IntradayRefreshSession(Base):
    __tablename__ = "intraday_refresh_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=5)
    provider_role: Mapped[str] = mapped_column(String(60), default="diagnostic_provider")
    started_by: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_instance_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)


class MarketAutomationControl(Base):
    __tablename__ = "market_automation_controls"
    control_key: Mapped[str] = mapped_column(String(40), primary_key=True, default="intraday")
    admin_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SectorResearchPreference(Base):
    __tablename__ = "sector_research_preferences"
    sector_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    is_pinned_for_research: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SpecificationDocument(Base):
    __tablename__ = "specification_documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    specification_name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[str] = mapped_column(String(80))
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(300))
    storage_filename: Mapped[str] = mapped_column(String(120), unique=True)
    content_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    replaces_specification_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(120))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReportComparison(Base):
    __tablename__ = "report_comparisons"
    __table_args__ = (UniqueConstraint("report_id", "previous_report_id", name="uq_report_comparison"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    previous_report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    comparison_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EnhancedReportRevision(Base):
    __tablename__ = "enhanced_report_revisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer)
    changed_by: Mapped[str] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
