from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT_PATH = ROOT / "scripts/validate_ths_public_board_paths.py"
SPEC = importlib.util.spec_from_file_location("ths_public_probe", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _audit_and_config() -> tuple[dict, dict]:
    config = MODULE.load_audit_config(MODULE.DEFAULT_CONFIG)
    return MODULE.build_audit(MODULE.DEFAULT_CONFIG, generated_at="fixed"), config


def _html(name: str, code: str, *, as_of: bool = True) -> bytes:
    suffix = "交易日期 2026-08-03" if as_of else ""
    return f"<html><body>{name} {code} 123.45 今开 120 昨收 120.00 最低 119 最高 125 成分股涨跌排行榜 {suffix}</body></html>".encode()


def _success_transport(audit: dict):
    by_code = {row["current_symbol"]: row for row in audit["rows"] if row["current_symbol"] and "+" not in row["current_symbol"]}
    def transport(url: str, _timeout: float):
        code = url.rstrip("/").split("/")[-1]
        row = by_code[code]
        return MODULE.HttpResponse(200, "text/html", _html(row["ths_official_board_name"], code))
    return transport


def test_representatives_are_dynamic_and_unique() -> None:
    audit, config = _audit_and_config()
    rows = MODULE.representative_rows(audit, config["representative_path_preferences"])
    assert [row["market_path_key"] for row in rows] == ["cpo", "commercial_space", "hotel", "semiconductor", "computing_power_rental"]
    assert len({row["current_symbol"] for row in rows}) == 5


def test_probe_rejects_nonisolated_environment() -> None:
    audit, config = _audit_and_config()
    with pytest.raises(ValueError, match="live_probe_requires_aliyun_isolated_environment"):
        MODULE.probe_representatives(audit, config, transport=_success_transport(audit), timeout=1, environment_label="local")


def test_http_401_is_classified_exactly() -> None:
    audit, config = _audit_and_config()
    result = MODULE.probe_representatives(audit, config, transport=lambda *_: MODULE.HttpResponse(401, "text/html", b""), timeout=1, environment_label="aliyun_isolated")
    assert all(row["error_class"] == "http_401" for row in result["results"])
    assert result["summary"]["full_expansion_permitted"] is False


def test_html_success_without_source_as_of_is_insufficient_fields() -> None:
    audit, config = _audit_and_config()
    by_code = {row["current_symbol"]: row for row in audit["rows"] if row["current_symbol"] and "+" not in row["current_symbol"]}
    def transport(url: str, _timeout: float):
        code = url.rstrip("/").split("/")[-1]
        return MODULE.HttpResponse(200, "text/html", _html(by_code[code]["ths_official_board_name"], code, as_of=False))
    result = MODULE.probe_representatives(audit, config, transport=transport, timeout=1, environment_label="aliyun_isolated")
    assert all(row["parser_status"] == "insufficient_fields" for row in result["results"])
    assert all(row["error_class"] == "insufficient_fields" for row in result["results"])


def test_complete_html_fields_passes_the_representative_gate() -> None:
    audit, config = _audit_and_config()
    result = MODULE.probe_representatives(audit, config, transport=_success_transport(audit), timeout=1, environment_label="aliyun_isolated")
    assert result["request_count"] == 5
    assert result["summary"]["complete_field_count"] == 5
    assert result["summary"]["full_expansion_permitted"] is True
    assert result["summary"]["full_expansion_executed"] is False


def test_three_of_five_does_not_permit_expansion() -> None:
    audit, config = _audit_and_config()
    calls = 0
    success = _success_transport(audit)
    def transport(url: str, timeout: float):
        nonlocal calls
        calls += 1
        return success(url, timeout) if calls <= 3 else MODULE.HttpResponse(401, "text/html", b"")
    result = MODULE.probe_representatives(audit, config, transport=transport, timeout=1, environment_label="aliyun_isolated")
    assert result["summary"]["complete_field_count"] == 3
    assert result["summary"]["full_expansion_permitted"] is False


def test_network_failure_and_parser_failure_are_distinct() -> None:
    audit, config = _audit_and_config()
    network = MODULE.probe_representatives(audit, config, transport=lambda *_: (_ for _ in ()).throw(ConnectionError("redacted")), timeout=1, environment_label="aliyun_isolated")
    assert all(row["error_class"] == "network_error" for row in network["results"])
    parsed = MODULE.probe_representatives(audit, config, transport=lambda *_: MODULE.HttpResponse(200, "text/html", b"<html>empty</html>"), timeout=1, environment_label="aliyun_isolated")
    assert all(row["error_class"] == "insufficient_fields" for row in parsed["results"])


def test_no_cookie_token_or_raw_response_persistence() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8").lower()
    assert "os.environ" not in source
    assert "cookie" in source  # Explicitly recorded as forbidden/false, not used as an HTTP header.
    assert "authorization" not in source
    assert "response.read" in source
    assert "raw_response" not in source


def test_probe_outputs_are_consistent_and_redacted(tmp_path: Path) -> None:
    audit, config = _audit_and_config()
    result = MODULE.probe_representatives(audit, config, transport=_success_transport(audit), timeout=1, environment_label="aliyun_isolated")
    json_path, csv_path, markdown_path = MODULE.write_outputs(result, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == payload["summary"]["representative_count"] == 5
    assert "raw_response" not in json_path.read_text(encoding="utf-8")
    assert "Full expansion permitted: **True**" in markdown_path.read_text(encoding="utf-8")
