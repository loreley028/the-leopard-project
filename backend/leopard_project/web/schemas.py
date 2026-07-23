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
    core_view: str | None = None
    market_path: str | None = None
    risk_warning: str | None = None
    focus_sectors: list[str] | None = None


class WithdrawRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class ResolveTermRequest(BaseModel):
    sector_key: str = Field(min_length=1, max_length=120)
