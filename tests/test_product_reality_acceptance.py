from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / "scripts" / "acceptance_product_reality.py"
    spec = spec_from_file_location("product_reality_acceptance", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payloads() -> dict:
    return {
        "sectors": [{"parent_report_topic": f"topic-{index}"} for index in range(66)] + [{"parent_report_topic": "topic-0"}],
        "enhanced": {"sector_assessments": [{"main_basis": "报告原文依据", "observation_condition": "—"}]},
        "anchor": {"quote_status": "available", "data_mode": "completed_eod"},
        "history": {"completed_days": 1, "items": [{"trading_date": "2026-08-12"}]},
        "cpo": {"viewer_source_mode": "security_proxy", "security_proxy": {"status": "completed_eod", "instruments": [{}, {}, {}, {}]}},
        "matrix": {"dates": [{"report_date": "2026-08-11", "market_as_of_date": "2026-08-11"}], "rows": [{"cells": [{"report_date": "2026-08-11", "market_as_of_date": "2026-08-11", "daily_return": None}]}]},
    }


def test_product_reality_acceptance_accepts_honest_preview_payload() -> None:
    result = _module().evaluate(_payloads())
    assert result["passed"] is True
    assert result["report_topic_count"] == 66
    assert result["visible_pending_review_count"] == 0


def test_product_reality_acceptance_rejects_pending_review_and_future_fallback() -> None:
    payloads = _payloads()
    payloads["enhanced"] = {"sector_assessments": [{"main_basis": "等待管理员复核"}]}
    payloads["matrix"] = {"dates": [{"report_date": "2026-08-11", "market_as_of_date": "2026-08-11"}], "rows": [{"cells": [{"report_date": "2026-08-11", "market_as_of_date": "2026-07-28", "daily_return": 1.0}]}]}
    result = _module().evaluate(payloads)
    assert result["passed"] is False
    assert result["visible_pending_review_count"] == 1
    assert result["future_2026_07_28_fallback_count"] == 1
