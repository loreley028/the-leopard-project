from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from .config import CONFIG_DIR, PROJECT_ROOT
from .eod import EodAssessment, EodStatus
from .provider_lineage import IndependenceStatus, ProviderLineage, compare_lineages, lineage_by_name


RECONCILIATION_POLICY_PATH = CONFIG_DIR / "reconciliation_policy_v1.json"
RECONCILIATION_OUTPUT_DIR = PROJECT_ROOT / "data" / "reconciliation-validation"


class ReconciliationStatus(StrEnum):
    MATCHED = "matched"
    ACCEPTABLE_DIFFERENCE = "acceptable_difference"
    MATERIAL_DIFFERENCE = "material_difference"
    SOURCE_NOT_INDEPENDENT = "source_not_independent"
    ONE_SOURCE_MISSING = "one_source_missing"
    BOTH_SOURCES_MISSING = "both_sources_missing"
    INTRADAY_EXCLUDED = "intraday_excluded"
    STALE_SOURCE = "stale_source"
    FUTURE_SNAPSHOT = "future_snapshot"
    FIELD_MISSING = "field_missing"
    CALENDAR_MISMATCH = "calendar_mismatch"
    PROVIDER_FAILED = "provider_failed"
    MANUAL_REVIEW = "manual_review"


class ReconciliationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    reconciliation_version: str
    validation_only: bool
    close_difference_pct_matched: Decimal
    close_difference_pct_acceptable: Decimal
    pct_change_difference_matched: Decimal
    pct_change_difference_acceptable: Decimal
    volume_difference_pct_acceptable: Decimal
    amount_difference_pct_acceptable: Decimal
    missing_optional_field_policy: str
    shared_upstream_policy: str
    intraday_policy: str
    stale_policy: str
    manual_review_threshold: Decimal
    production_thresholds_approved: bool


class ReconciliationValues(BaseModel):
    model_config = ConfigDict(frozen=True)
    close: Decimal | None = None
    pct_change: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None


class SourceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_name: str
    eod: EodAssessment
    values: ReconciliationValues | None = None


class ReconciliationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    reconciliation_version: str
    reconciliation_run_id: str
    requested_as_of: datetime
    expected_trade_date: date
    actual_trade_date: date | None
    sector_key: str
    sector_name: str
    canonical_symbol: str
    source_a_provider: str
    source_b_provider: str
    source_a_lineage: str
    source_b_lineage: str
    source_independence_status: IndependenceStatus
    source_a_eod_status: EodStatus | None
    source_b_eod_status: EodStatus | None
    source_a_values: ReconciliationValues | None
    source_b_values: ReconciliationValues | None
    close_difference_abs: Decimal | None
    close_difference_pct: Decimal | None
    pct_change_difference_abs: Decimal | None
    volume_difference_abs: Decimal | None
    volume_difference_pct: Decimal | None
    amount_difference_abs: Decimal | None
    amount_difference_pct: Decimal | None
    missing_fields_a: tuple[str, ...]
    missing_fields_b: tuple[str, ...]
    anomaly_codes: tuple[str, ...]
    reconciliation_status: ReconciliationStatus
    created_at: datetime


def load_reconciliation_policy(path: Path = RECONCILIATION_POLICY_PATH) -> ReconciliationPolicy:
    return ReconciliationPolicy(**json.loads(path.read_text(encoding="utf-8")))


def deterministic_run_id(version: str, mode: str, trade_date: date) -> str:
    payload = f"{version}|{mode}|{trade_date.isoformat()}|ths_public_validation|akshare_ths_research"
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _absolute(first: Decimal | None, second: Decimal | None) -> Decimal | None:
    return None if first is None or second is None else abs(first - second)


def _percent(first: Decimal | None, second: Decimal | None) -> Decimal | None:
    if first is None or second is None or first == 0:
        return None
    return abs(first - second) / abs(first) * Decimal("100")


def _missing(values: ReconciliationValues | None) -> tuple[str, ...]:
    if values is None:
        return ("close", "pct_change", "volume", "amount")
    return tuple(name for name in ("close", "pct_change", "volume", "amount") if getattr(values, name) is None)


def reconcile_sector(
    *,
    reconciliation_run_id: str,
    requested_as_of: datetime,
    expected_trade_date: date,
    sector_key: str,
    sector_name: str,
    canonical_symbol: str,
    source_a: SourceSnapshot | None,
    source_b: SourceSnapshot | None,
    lineage_a: ProviderLineage,
    lineage_b: ProviderLineage,
    created_at: datetime,
    policy: ReconciliationPolicy | None = None,
) -> ReconciliationRecord:
    policy = policy or load_reconciliation_policy()
    independence = compare_lineages(lineage_a, lineage_b)
    values_a = source_a.values if source_a else None
    values_b = source_b.values if source_b else None
    missing_a = _missing(values_a)
    missing_b = _missing(values_b)
    close_abs = _absolute(values_a.close if values_a else None, values_b.close if values_b else None)
    close_pct = _percent(values_a.close if values_a else None, values_b.close if values_b else None)
    pct_abs = _absolute(values_a.pct_change if values_a else None, values_b.pct_change if values_b else None)
    volume_abs = _absolute(values_a.volume if values_a else None, values_b.volume if values_b else None)
    volume_pct = _percent(values_a.volume if values_a else None, values_b.volume if values_b else None)
    amount_abs = _absolute(values_a.amount if values_a else None, values_b.amount if values_b else None)
    amount_pct = _percent(values_a.amount if values_a else None, values_b.amount if values_b else None)
    anomalies: list[str] = []

    status_a = source_a.eod.status if source_a else None
    status_b = source_b.eod.status if source_b else None
    if status_a == EodStatus.INTRADAY_SNAPSHOT or status_b == EodStatus.INTRADAY_SNAPSHOT:
        status = ReconciliationStatus.INTRADAY_EXCLUDED
        anomalies.append("intraday_source_excluded")
    elif status_a == EodStatus.FUTURE_SNAPSHOT or status_b == EodStatus.FUTURE_SNAPSHOT:
        status = ReconciliationStatus.FUTURE_SNAPSHOT
        anomalies.append("future_snapshot_blocked")
    elif status_a in {EodStatus.STALE_SNAPSHOT, EodStatus.MISSING_EXPECTED_TRADE_DATE} or status_b in {
        EodStatus.STALE_SNAPSHOT,
        EodStatus.MISSING_EXPECTED_TRADE_DATE,
    }:
        status = ReconciliationStatus.STALE_SOURCE
        anomalies.append("stale_or_missing_expected_date")
    elif status_a == EodStatus.PROVIDER_FAILED or status_b == EodStatus.PROVIDER_FAILED:
        status = ReconciliationStatus.PROVIDER_FAILED
        anomalies.append("provider_failed")
    elif source_a is None and source_b is None:
        status = ReconciliationStatus.BOTH_SOURCES_MISSING
        anomalies.extend(("both_sources_missing", "manual_review_required"))
    elif source_a is None or source_b is None:
        status = ReconciliationStatus.ONE_SOURCE_MISSING
        anomalies.extend(("one_source_missing", "manual_review_required"))
    elif source_a.eod.actual_trade_date != source_b.eod.actual_trade_date:
        status = ReconciliationStatus.CALENDAR_MISMATCH
        anomalies.append("actual_trade_date_mismatch")
    elif any(field in {"close", "pct_change", "volume"} for field in (*missing_a, *missing_b)):
        status = ReconciliationStatus.FIELD_MISSING
        anomalies.extend(("required_reconciliation_field_missing", "manual_review_required"))
    elif independence in {IndependenceStatus.SHARED_UPSTREAM, IndependenceStatus.LIKELY_SHARED_UPSTREAM}:
        status = ReconciliationStatus.SOURCE_NOT_INDEPENDENT
        anomalies.append("shared_upstream_not_independent_validation")
    else:
        if "amount" in missing_a or "amount" in missing_b:
            anomalies.append("optional_amount_missing")
        assert close_pct is not None and pct_abs is not None and volume_pct is not None
        if close_pct <= policy.close_difference_pct_matched and pct_abs <= policy.pct_change_difference_matched:
            status = ReconciliationStatus.MATCHED
        elif (
            close_pct <= policy.close_difference_pct_acceptable
            and pct_abs <= policy.pct_change_difference_acceptable
            and volume_pct <= policy.volume_difference_pct_acceptable
            and (amount_pct is None or amount_pct <= policy.amount_difference_pct_acceptable)
        ):
            status = ReconciliationStatus.ACCEPTABLE_DIFFERENCE
        elif close_pct > policy.manual_review_threshold:
            status = ReconciliationStatus.MANUAL_REVIEW
            anomalies.append("difference_exceeds_manual_review_threshold")
        else:
            status = ReconciliationStatus.MATERIAL_DIFFERENCE
            anomalies.append("material_numeric_difference")

    actual = source_a.eod.actual_trade_date if source_a else source_b.eod.actual_trade_date if source_b else None
    return ReconciliationRecord(
        reconciliation_version=policy.reconciliation_version,
        reconciliation_run_id=reconciliation_run_id,
        requested_as_of=requested_as_of,
        expected_trade_date=expected_trade_date,
        actual_trade_date=actual,
        sector_key=sector_key,
        sector_name=sector_name,
        canonical_symbol=canonical_symbol,
        source_a_provider=lineage_a.provider_name,
        source_b_provider=lineage_b.provider_name,
        source_a_lineage=lineage_a.provider_name,
        source_b_lineage=lineage_b.provider_name,
        source_independence_status=independence,
        source_a_eod_status=status_a,
        source_b_eod_status=status_b,
        source_a_values=values_a,
        source_b_values=values_b,
        close_difference_abs=close_abs,
        close_difference_pct=close_pct,
        pct_change_difference_abs=pct_abs,
        volume_difference_abs=volume_abs,
        volume_difference_pct=volume_pct,
        amount_difference_abs=amount_abs,
        amount_difference_pct=amount_pct,
        missing_fields_a=missing_a,
        missing_fields_b=missing_b,
        anomaly_codes=tuple(anomalies),
        reconciliation_status=status,
        created_at=created_at,
    )


def run_controlled_replay(
    *,
    trade_date: date = date(2026, 7, 21),
    output_dir: Path = RECONCILIATION_OUTPUT_DIR,
) -> tuple[dict[str, object], dict[str, object]]:
    """Replay immutable Phase 1B-0 metadata; no network or raw price fabrication."""
    if trade_date != date(2026, 7, 21):
        raise ValueError("checked-in replay evidence is available only for 2026-07-21")
    coverage = json.loads((PROJECT_ROOT / "data/provider-selection/coverage_65.json").read_text(encoding="utf-8"))
    historical_rows = list(coverage["results"])
    requested_as_of = datetime.fromisoformat("2026-07-22T15:30:00+08:00")
    created_at = datetime.fromisoformat("2026-07-22T16:00:00+08:00")
    policy = load_reconciliation_policy()
    lineage_a = lineage_by_name("ths_public_validation")
    lineage_b = lineage_by_name("akshare_ths_research")
    run_id = deterministic_run_id(policy.reconciliation_version, "replay", trade_date)
    records: list[ReconciliationRecord] = []
    for evidence in historical_rows:
        latest = date.fromisoformat(evidence["latest_trade_date"])
        eod_status = EodStatus.INTRADAY_SNAPSHOT if latest > trade_date else EodStatus.COMPLETE_EOD
        assessment = EodAssessment(
            policy_version="eod-v1-20260722",
            provider_name="ths_public_validation",
            market="CN_A",
            requested_as_of=requested_as_of,
            expected_trade_date=trade_date,
            actual_trade_date=latest,
            status=eod_status,
            eligible_for_eod=eod_status == EodStatus.COMPLETE_EOD,
            anomaly_codes=("phase1b0_intraday_record_reclassified",) if eod_status == EodStatus.INTRADAY_SNAPSHOT else (),
            row_count=sum(int(component.get("audit", {}).get("row_count", 0)) for component in evidence["components"]),
        )
        source_a = SourceSnapshot(provider_name="ths_public_validation", eod=assessment, values=None)
        provider_symbols = tuple(evidence["provider_symbols"])
        canonical_symbol = "+".join(provider_symbols) if len(provider_symbols) > 1 else provider_symbols[0]
        records.append(reconcile_sector(
            reconciliation_run_id=run_id,
            requested_as_of=requested_as_of,
            expected_trade_date=trade_date,
            sector_key=evidence["sector_key"],
            sector_name=evidence["sector_name"],
            canonical_symbol=canonical_symbol,
            source_a=source_a,
            source_b=None,
            lineage_a=lineage_a,
            lineage_b=lineage_b,
            created_at=created_at,
            policy=policy,
        ))

    statuses = {status.value: sum(row.reconciliation_status == status for row in records) for status in ReconciliationStatus}
    summary = {
        "schema_version": 1,
        "reconciliation_version": policy.reconciliation_version,
        "reconciliation_run_id": run_id,
        "mode": "replay",
        "trade_date": trade_date.isoformat(),
        "requested_as_of": requested_as_of.isoformat(),
        "plan_sector_count": len(historical_rows),
        "provider_a_success_count": len(historical_rows),
        "provider_b_success_count": 0,
        "provider_b_live_status": "blocked_by_dependency_network",
        "complete_eod_count": sum(row.source_a_eod_status == EodStatus.COMPLETE_EOD for row in records),
        "intraday_snapshot_count": sum(row.source_a_eod_status == EodStatus.INTRADAY_SNAPSHOT for row in records),
        "stale_snapshot_count": 0,
        "future_snapshot_count": 0,
        "missing_count": len(historical_rows),
        "reconcilable_count": 0,
        "matched_count": statuses[ReconciliationStatus.MATCHED],
        "acceptable_difference_count": statuses[ReconciliationStatus.ACCEPTABLE_DIFFERENCE],
        "material_difference_count": statuses[ReconciliationStatus.MATERIAL_DIFFERENCE],
        "source_not_independent_count": statuses[ReconciliationStatus.SOURCE_NOT_INDEPENDENT],
        "manual_review_count": sum("manual_review_required" in row.anomaly_codes for row in records),
        "insufficient_120_day_count": sum(not bool(row["has_120_days"]) for row in historical_rows),
        "proxy_count": sum(row["mapping_type"] == "proxy" for row in historical_rows),
        "short_history_count": sum(row["data_status"] == "short_history" for row in historical_rows),
        "status_counts": statuses,
        "source_independence_status": compare_lineages(lineage_a, lineage_b).value,
        "independent_secondary_source_available": False,
        "production_primary_approved": False,
        "evidence_limitations": [
            "Provider A status is replayed from immutable Phase 1B-0 metadata.",
            "Price values are not reconstructed from summary hashes.",
            "Provider B live execution was not available, so no numeric dual-source claim is made."
        ]
    }
    details = {
        "schema_version": 1,
        "reconciliation_version": policy.reconciliation_version,
        "reconciliation_run_id": run_id,
        "mode": "replay",
        "records": [row.model_dump(mode="json") for row in records],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reconciliation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "reconciliation_details.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    samples = output_dir / "sample_responses"
    samples.mkdir(exist_ok=True)
    for key in ("semiconductor", "glass_substrate", "advertising"):
        record = next(row for row in records if row.sector_key == key)
        (samples / f"{key}.json").write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary, details
