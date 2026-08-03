#!/usr/bin/env python3
"""Bounded anonymous THS public-board probe for an isolated cloud container.

The default mode is a no-network runbook.  `--run-live` is deliberately gated
to an `aliyun_isolated` environment label and sends one anonymous GET per
dynamic representative only.  It does not import formal Providers, use cookies
or Tokens, start application services, or persist raw response bodies.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from analyze_ths_official_board_mapping import DEFAULT_CONFIG, build_audit, load_audit_config


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "var/provider-research/ths-public-board-audit"
REQUIRED_ENVIRONMENT = "aliyun_isolated"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str | None
    body: bytes


Transport = Callable[[str, float], HttpResponse]


class VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored and data.strip():
            self.parts.append(data.strip())


def anonymous_get(url: str, timeout: float) -> HttpResponse:
    """One GET without caller-supplied Cookie, Token or browser impersonation."""
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(int(response.status), response.headers.get_content_type(), response.read())
    except HTTPError as error:
        return HttpResponse(error.code, error.headers.get_content_type() if error.headers else None, b"")
    except (URLError, TimeoutError, OSError) as error:
        raise ConnectionError(type(error).__name__) from error


def error_class_for_status(status: int) -> str:
    return {
        401: "http_401", 403: "http_403", 404: "http_404", 429: "http_429",
    }.get(status, "http_error")


def _visible_text(payload: bytes) -> str:
    decoded = None
    for encoding in ("utf-8", "gb18030"):
        try:
            decoded = payload.decode(encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        decoded = payload.decode("gb18030", errors="replace")
    parser = VisibleText()
    parser.feed(decoded)
    return re.sub(r"\s+", " ", " ".join(parser.parts))


def parse_detail(payload: bytes, *, board_name: str, board_code: str) -> dict[str, Any]:
    text = _visible_text(payload)
    number = r"(-?\d+(?:\.\d+)?)"
    name_present = board_name in text and board_code in text
    current_match = re.search(rf"{re.escape(board_name)}\s*{re.escape(board_code)}\s+{number}", text)
    pre_close_match = re.search(rf"昨收\s+{number}", text)
    as_of_match = re.search(r"(?:更新时间|交易日期|日期)\s*[:：]?\s*(\d{4}[-/]\d{2}[-/]\d{2})", text)
    return {
        "board_name_readable": name_present,
        "current": current_match.group(1) if current_match else None,
        "pre_close": pre_close_match.group(1) if pre_close_match else None,
        "as_of": as_of_match.group(1).replace("/", "-") if as_of_match else None,
        "constituents_readable": "成分股涨跌排行榜" in text,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }


def representative_rows(audit: dict[str, Any], preferences: list[str]) -> list[dict[str, Any]]:
    rows = {row["market_path_key"]: row for row in audit["rows"]}
    selected: list[dict[str, Any]] = []
    for key in preferences:
        row = rows.get(key)
        if row is None or not row["current_symbol"] or "+" in row["current_symbol"]:
            raise ValueError(f"representative_requires_single_board_symbol:{key}")
        selected.append(row)
    if len({row["current_symbol"] for row in selected}) != len(selected):
        raise ValueError("representative_symbols_must_be_unique")
    return selected


def probe_representatives(
    audit: dict[str, Any],
    config: dict[str, Any],
    *,
    transport: Transport,
    timeout: float,
    environment_label: str,
) -> dict[str, Any]:
    if environment_label != config["cloud_probe_policy"]["required_environment_label"]:
        raise ValueError("live_probe_requires_aliyun_isolated_environment")
    access_path = next(item for item in config["public_access_paths"] if item["access_path_id"] == "ths_detail_html")
    results: list[dict[str, Any]] = []
    for row in representative_rows(audit, config["representative_path_preferences"]):
        url = access_path["url_template"].format(symbol=row["current_symbol"])
        started = time.monotonic()
        try:
            response = transport(url, timeout)
            latency_ms = round((time.monotonic() - started) * 1000, 3)
            result = {
                "market_path": row["market_path_key"], "board_name": row["ths_official_board_name"],
                "board_code": row["current_symbol"], "access_path": access_path["access_path_id"],
                "url_template": access_path["url_template"], "http_status": response.status,
                "content_type": response.content_type, "response_length": len(response.body),
                "latency_ms": latency_ms, "current": None, "pre_close": None, "as_of": None,
                "parser_status": "not_attempted", "error_class": None, "summary": {},
            }
            if response.status != 200:
                result.update({"parser_status": "not_attempted", "error_class": error_class_for_status(response.status)})
            else:
                parsed = parse_detail(response.body, board_name=row["ths_official_board_name"], board_code=row["current_symbol"])
                result.update({
                    "current": parsed["current"], "pre_close": parsed["pre_close"], "as_of": parsed["as_of"],
                    "summary": {key: parsed[key] for key in ("board_name_readable", "constituents_readable", "payload_sha256")},
                })
                result["parser_status"] = "success" if all(parsed[key] is not None for key in ("current", "pre_close", "as_of")) else "insufficient_fields"
                result["error_class"] = None if result["parser_status"] == "success" else "insufficient_fields"
        except ConnectionError as error:
            result = {
                "market_path": row["market_path_key"], "board_name": row["ths_official_board_name"],
                "board_code": row["current_symbol"], "access_path": access_path["access_path_id"],
                "url_template": access_path["url_template"], "http_status": None, "content_type": None,
                "response_length": 0, "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "current": None, "pre_close": None, "as_of": None, "parser_status": "not_attempted",
                "error_class": "network_error", "summary": {"network_exception": str(error)},
            }
        results.append(result)
    success_count = sum(row["parser_status"] == "success" for row in results)
    return {
        "schema_version": "1.0.0", "analysis_type": "ths_public_representative_probe",
        "generated_at": datetime.now(timezone.utc).isoformat(), "environment_label": environment_label,
        "research_only": True, "production_approved": False, "cookie_used": False, "token_accessed": False,
        "concurrency": 1, "retries": 0, "request_count": len(results), "results": results,
        "summary": {
            "representative_count": len(results), "complete_field_count": success_count,
            "expansion_gate": "4_of_5", "full_expansion_permitted": success_count >= 4,
            "full_expansion_executed": False,
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# THS public-board representative probe", "",
        "> Isolated research evidence only. Raw response bodies are not persisted.", "",
        "| Path | Code | HTTP | Current | Pre-close | Source as-of | Parser | Error |", "|---|---|---:|---|---|---|---|---|",
    ]
    for row in result["results"]:
        lines.append(
            f"| `{row['market_path']}` | {row['board_code']} | {row['http_status'] or '—'} | "
            f"{bool(row['current'])} | {bool(row['pre_close'])} | {bool(row['as_of'])} | "
            f"{row['parser_status']} | {row['error_class'] or '—'} |"
        )
    lines.extend(["", f"Full expansion permitted: **{result['summary']['full_expansion_permitted']}**.", ""])
    return "\n".join(lines)


def write_outputs(result: dict[str, Any], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ths-public-board-probe.json"
    csv_path = output_dir / "ths-public-board-probe.csv"
    markdown_path = output_dir / "ths-public-board-probe.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    fields = ["market_path", "board_name", "board_code", "access_path", "http_status", "content_type", "response_length", "current", "pre_close", "as_of", "parser_status", "latency_ms", "error_class"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{field: row[field] for field in fields} for row in result["results"]])
    return json_path, csv_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--environment-label", default="not_live")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--run-live", action="store_true")
    args = parser.parse_args()
    config = load_audit_config(DEFAULT_CONFIG)
    audit = build_audit(DEFAULT_CONFIG)
    if not args.run_live:
        plan = {
            "research_only": True, "network_requests": 0, "live_probe_executed": False,
            "representatives": [row["market_path_key"] for row in representative_rows(audit, config["representative_path_preferences"])],
            "required_environment_label": REQUIRED_ENVIRONMENT,
        }
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        return
    result = probe_representatives(audit, config, transport=anonymous_get, timeout=args.timeout, environment_label=args.environment_label)
    for path in write_outputs(result, args.output_dir):
        print(path)
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
