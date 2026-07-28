from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from leopard_project.config import CONFIG_DIR


@dataclass(frozen=True)
class ReportSchedulePolicy:
    timezone: str
    expected_upload_weekdays: frozenset[str]
    no_report_expected_weekdays: frozenset[str]
    missing_report_alert_enabled: bool
    upload_time_is_report_date: bool
    report_date_requires_confirmation: bool
    report_date_confirmation_required_for: frozenset[str]

    @classmethod
    def load(cls) -> "ReportSchedulePolicy":
        data = json.loads((CONFIG_DIR / "report_schedule_policy_v1.json").read_text(encoding="utf-8"))
        return cls(
            timezone=data["timezone"],
            expected_upload_weekdays=frozenset(data["expected_upload_weekdays"]),
            no_report_expected_weekdays=frozenset(data["no_report_expected_weekdays"]),
            missing_report_alert_enabled=data["missing_report_alert_enabled"],
            upload_time_is_report_date=data["upload_time_is_report_date"],
            report_date_requires_confirmation=data["report_date_requires_confirmation"],
            report_date_confirmation_required_for=frozenset(data["report_date_confirmation_required_for"]),
        )

    @classmethod
    def load_v2(cls) -> "ReportSchedulePolicy":
        data = json.loads((CONFIG_DIR / "report_schedule_policy_v2.json").read_text(encoding="utf-8"))
        return cls(
            timezone=data["timezone"],
            expected_upload_weekdays=frozenset(data["expected_upload_weekdays"]),
            no_report_expected_weekdays=frozenset(data["normally_no_report_weekdays"]),
            missing_report_alert_enabled=data["missing_report_alert_enabled"],
            upload_time_is_report_date=False,
            report_date_requires_confirmation=False,
            report_date_confirmation_required_for=frozenset({"low", "conflict"}),
        )

    def report_expected(self, day: date) -> bool:
        return day.strftime("%A").upper() in self.expected_upload_weekdays

    def missing_report_alert(self, day: date) -> bool:
        return self.missing_report_alert_enabled and self.report_expected(day)
