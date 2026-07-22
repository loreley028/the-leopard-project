from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MappingStatus(StrEnum):
    UNMATCHED = "未匹配"
    CANDIDATE = "候选待确认"
    CONFIRMED = "已确认"
    NO_DIRECT_MATCH = "无直接匹配"
    EXCLUDED = "暂不纳入"


class MappingMethod(StrEnum):
    ONE_TO_ONE = "一对一"
    SELECT_ONE = "一对多择一"
    COMPOSITE = "组合口径"
    REPRESENTATIVE_INDEX = "代表指数"
    REPRESENTATIVE_ETF = "代表 ETF"
    REPRESENTATIVE_ETF_COMPACT = "代表ETF"
    CUSTOM = "自定义组合"


class DataStatus(StrEnum):
    NORMAL = "normal"
    PROXY = "proxy"
    INSUFFICIENT = "insufficient_data"
    MISSING = "missing"
    HISTORY_INSUFFICIENT = "history_insufficient"
    STALE_SNAPSHOT = "stale_snapshot"
    PROVIDER_ANOMALY = "provider_anomaly"


class LiquidityStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class Market(StrEnum):
    CN_A = "CN_A"
    HK = "HK"


class Sector(BaseModel):
    model_config = ConfigDict(frozen=True)
    sector_key: str
    sector_name: str
    category_level_1: str
    group_order: int = Field(ge=1)
    within_group_order: int = Field(ge=1)
    overall_order: int = Field(ge=1)
    enabled: bool = False
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None


class SectorAlias(BaseModel):
    model_config = ConfigDict(frozen=True)
    alias: str
    canonical_sector_name: str
    sector_key: str
    confirmed: bool
    basis: str
    note: str | None = None


class SectorMapping(BaseModel):
    model_config = ConfigDict(frozen=True)
    mapping_version: str
    sector_key: str
    sector_name: str
    ths_candidate_name: str
    ths_display_code: str
    ths_sector_type: str
    mapping_method: str
    mapping_status: MappingStatus
    primary_symbol: str
    backup_symbols: tuple[str, ...] = ()
    provider_key: str
    effective_date: date | None = None
    user_confirmed: bool = False
    methodology_note: str
    research_confidence: str
    primary_source_url: str
    backup_source_url: str | None = None
    research_date: date


class DailyBar(BaseModel):
    model_config = ConfigDict(frozen=True)
    symbol: str
    symbol_name: str
    market: Market = Market.CN_A
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pre_close: Decimal
    change: Decimal
    pct_change: Decimal
    volume: Decimal | None = None
    turnover_rate: Decimal | None = None
    amount: Decimal | None = None
    liquidity_status: LiquidityStatus
    provider: str
    fetched_at: datetime
    source_payload_hash: str
    data_status: DataStatus = DataStatus.NORMAL

    @model_validator(mode="after")
    def validate_liquidity_status(self) -> "DailyBar":
        expected = (
            LiquidityStatus.COMPLETE if self.volume is not None and self.amount is not None
            else LiquidityStatus.PARTIAL if any(value is not None for value in (self.volume, self.turnover_rate, self.amount))
            else LiquidityStatus.UNAVAILABLE
        )
        if self.liquidity_status != expected:
            raise ValueError(f"liquidity_status must be {expected.value} for available liquidity fields")
        return self


class IndicatorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    trade_date: date
    pct_change_1d: Decimal | None = None
    return_5d: Decimal | None = None
    return_10d: Decimal | None = None
    return_20d: Decimal | None = None
    return_60d: Decimal | None = None
    ma5: Decimal | None = None
    ma10: Decimal | None = None
    ma20: Decimal | None = None
    ma60: Decimal | None = None
    distance_ma20_pct: Decimal | None = None
    distance_ma60_pct: Decimal | None = None
    amount_change_pct: Decimal | None = None
    amount_vs_5d_avg: Decimal | None = None
    amount_vs_20d_avg: Decimal | None = None
    volume_vs_5d_avg: Decimal | None = None
    volume_vs_20d_avg: Decimal | None = None
    volume_label_5d: str | None = None
    volume_label_20d: str | None = None
    volume_label: str | None = None
    high_20d: Decimal | None = None
    low_20d: Decimal | None = None
    new_high_20d: bool | None = None
    new_low_20d: bool | None = None
    crossed_above_ma20: bool | None = None
    crossed_below_ma20: bool | None = None
    rank_1d: int | None = None
    rank_5d: int | None = None
    rank_20d: int | None = None
    amount_ratio_rank: int | None = None
    rank_sample_size: int | None = None
    data_status: DataStatus = DataStatus.NORMAL


class DailySectorSnapshot(BaseModel):
    sector_key: str
    mapping_version: str
    trade_date: date
    bar: DailyBar
    indicators: IndicatorSnapshot
    job_run_id: str


class JobRun(BaseModel):
    job_run_id: str
    job_type: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    configuration_version: str
    indicator_version: str
    program_version: str
    success_count: int = 0
    failure_count: int = 0


class DataAnomaly(BaseModel):
    anomaly_id: str
    job_run_id: str
    sector_key: str | None = None
    symbol: str | None = None
    category: str
    severity: str
    message: str
    detected_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)


class ExportManifest(BaseModel):
    export_id: str
    job_run_id: str
    trade_date: date
    format: str
    relative_path: str
    sha256: str
    created_at: datetime
    row_count: int
    configuration_version: str
