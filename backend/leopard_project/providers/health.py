from __future__ import annotations

import json
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.client import RemoteDisconnected
from urllib.error import HTTPError, URLError

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import CONFIG_DIR
from ..web.models import ProviderHealthRecord
from ..web.write_coordination import BACKGROUND_WRITE_LOCK
from .base import ProviderError, ProviderErrorCategory


POLICY_PATH = CONFIG_DIR / "provider_resilience_policy_v1.json"


def resilience_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def classify_provider_failure(exc: Exception) -> str:
    if isinstance(exc, ProviderError) and isinstance(exc.__cause__, Exception):
        caused = classify_provider_failure(exc.__cause__)
        if caused != "provider_data_unavailable":
            return caused
    if isinstance(exc, RemoteDisconnected):
        return "remote_disconnected"
    if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
        return "connection_reset"
    if isinstance(exc, socket.gaierror):
        return "dns_error"
    if isinstance(exc, ssl.SSLError):
        return "tls_error"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, HTTPError):
        if exc.code == 429:
            return "rate_limited"
        return "http_5xx" if exc.code >= 500 else "http_4xx"
    if isinstance(exc, URLError):
        reason = exc.reason
        return classify_provider_failure(reason) if isinstance(reason, Exception) else "network_empty_reply"
    if isinstance(exc, ProviderError):
        return {
            ProviderErrorCategory.RATE_LIMIT: "rate_limited",
            ProviderErrorCategory.TIMEOUT: "timeout",
            ProviderErrorCategory.NETWORK: "network_empty_reply",
            ProviderErrorCategory.MALFORMED_RESPONSE: "parse_error",
            ProviderErrorCategory.NO_DATA: "missing_required_fields",
        }.get(exc.category, "provider_data_unavailable")
    if isinstance(exc, ValueError) and str(exc) == "stale_snapshot":
        return "stale_payload"
    return "provider_data_unavailable"


@dataclass(frozen=True)
class CircuitDecision:
    allowed: bool
    state: str
    reason: str | None = None


class ProviderCircuitBreaker:
    """Persistent provider-family circuit with short SQLite transactions."""

    def __init__(self, sessions: sessionmaker[Session], *, now=None, policy: dict | None = None) -> None:
        self.sessions = sessions
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.policy = policy or resilience_policy()

    def _provider_policy(self, provider: str) -> tuple[str, dict]:
        item = self.policy["providers"].get(provider)
        if item is None:
            raise ValueError("provider_resilience_policy_missing")
        return str(item["endpoint_family"]), item

    def _record(self, session: Session, provider: str) -> ProviderHealthRecord:
        family, _ = self._provider_policy(provider)
        record = session.scalar(select(ProviderHealthRecord).where(
            ProviderHealthRecord.provider == provider,
            ProviderHealthRecord.endpoint_family == family,
        ))
        if record is None:
            record = ProviderHealthRecord(
                provider=provider, endpoint_family=family,
                cooldown_seconds=int(self.policy["base_cooldown_seconds"]),
            )
            session.add(record)
            session.flush()
        return record

    def decision(self, provider: str) -> CircuitDecision:
        now = self.now()
        with self.sessions() as session:
            record = self._record(session, provider)
            if record.state == "open" and record.next_probe_at and now < _aware(record.next_probe_at):
                return CircuitDecision(False, "open", "primary_provider_circuit_open")
            if record.state == "open":
                return CircuitDecision(True, "half_open")
            return CircuitDecision(True, record.state)

    def manual_probe_decision(self, provider: str) -> CircuitDecision:
        decision = self.decision(provider)
        if not decision.allowed:
            return decision
        now = self.now()
        with self.sessions() as session:
            record = self._record(session, provider)
            latest = max(
                (_aware(value) for value in (record.last_success_at, record.last_failure_at) if value is not None),
                default=None,
            )
            minimum = int(self.policy.get("manual_probe_min_interval_seconds", 300))
            if latest and (now - latest).total_seconds() < minimum:
                return CircuitDecision(False, record.state, "manual_probe_rate_limited")
        return decision

    def record_success(self, provider: str) -> None:
        now = self.now()
        with BACKGROUND_WRITE_LOCK, self.sessions() as session:
            record = self._record(session, provider)
            was_recovery = record.state in {"open", "half_open"}
            record.state = "half_open" if was_recovery else "closed"
            record.recovery_successes = record.recovery_successes + 1 if was_recovery else 0
            record.last_success_at = now
            record.last_error_class = None
            record.last_error_summary = None
            if not was_recovery:
                record.consecutive_failures = 0
            if record.recovery_successes >= int(self.policy["half_open_success_threshold"]):
                record.state, record.consecutive_failures, record.recovery_successes = "closed", 0, 0
                record.opened_at = record.next_probe_at = None
                record.cooldown_seconds = int(self.policy["base_cooldown_seconds"])
            session.commit()

    def record_failure(self, provider: str, exc: Exception) -> str:
        now = self.now()
        error_class = classify_provider_failure(exc)
        with BACKGROUND_WRITE_LOCK, self.sessions() as session:
            record = self._record(session, provider)
            record.consecutive_failures += 1
            record.recovery_successes = 0
            record.last_failure_at = now
            record.last_error_class = error_class
            record.last_error_summary = f"{type(exc).__name__}: {str(exc)[:180]}"
            if record.state == "half_open" or record.consecutive_failures >= int(self.policy["failure_threshold"]):
                previous = record.cooldown_seconds or int(self.policy["base_cooldown_seconds"])
                cooldown = previous * 2 if record.opened_at else previous
                record.cooldown_seconds = min(int(self.policy["max_cooldown_seconds"]), cooldown)
                record.state, record.opened_at = "open", now
                record.next_probe_at = now + timedelta(seconds=record.cooldown_seconds)
            session.commit()
        return error_class

    def rows(self) -> list[dict]:
        now = self.now()
        with self.sessions() as session:
            rows = list(session.scalars(select(ProviderHealthRecord).order_by(ProviderHealthRecord.provider)))
            return [{
                "provider": row.provider, "endpoint_family": row.endpoint_family, "state": row.state,
                "consecutive_failures": row.consecutive_failures,
                "last_success_at": _iso(row.last_success_at), "last_failure_at": _iso(row.last_failure_at),
                "next_probe_at": _iso(row.next_probe_at), "last_error_class": row.last_error_class,
                "last_error_summary": row.last_error_summary, "cooldown_seconds": row.cooldown_seconds,
                "cooldown_remaining_seconds": max(0, int((_aware(row.next_probe_at) - now).total_seconds())) if row.next_probe_at else 0,
                "recovery_successes": row.recovery_successes,
            } for row in rows]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None
