from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=300)


class PrincipalResponse(BaseModel):
    username: str
    role: str


class ReportPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    report_date: date | None = None
    report_date_confirmed: bool | None = None
    market_as_of_date: date | None = None
    market_as_of_date_confirmed: bool | None = None
    core_view: str | None = None
    market_path: str | None = None
    risk_warning: str | None = None
    focus_sectors: list[str] | None = None


class WithdrawRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class ResolveTermRequest(BaseModel):
    sector_key: str = Field(min_length=1, max_length=120)


class PathEntryPatch(BaseModel):
    path_status: str | None = None
    explicitly_mentioned: bool | None = None
    judgement_summary: str | None = None
    source_text_reference: str | None = None
    review_status: str | None = None


class SectorAssessmentPatch(BaseModel):
    current_path_status: str | None = None
    explicitly_mentioned: bool | None = None
    recent_path_summary: str | None = None
    current_judgement: str | None = None
    main_basis: str | None = None
    observation_condition: str | None = None
    source_section: str | None = None
    source_text_reference: str | None = None
    review_status: str | None = None


class MarketBindingRequest(BaseModel):
    market_as_of_date: date
    confirmed: bool


class MarketRefreshRequest(BaseModel):
    mode: str = "controlled_fixture"
    confirmed_research_only: bool = False
    sector_keys: list[str] | None = None
    as_of_date: date | None = None


class PublishConfirmationRequest(BaseModel):
    confirm_warnings: bool = False
    warning_note: str = Field(default="", max_length=1000)


class ReviewIssueResolutionRequest(BaseModel):
    final_value: str | bool | int | float | None = None
    resolution_source: str = Field(pattern="^(accepted_suggestion|manual_override)$")
    optional_note: str = Field(default="", max_length=1000)


class ApiObjectResponse(BaseModel):
    model_config = {"extra": "allow"}


class ApiListItem(BaseModel):
    model_config = {"extra": "allow"}
