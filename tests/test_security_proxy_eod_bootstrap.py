from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from leopard_project.security_proxy_eod import SecurityProxyEodFileStore
from leopard_project.security_proxy_eod_bootstrap import (
    ALL_COLUMNS, SecurityProxyBootstrapError, import_bootstrap_rows, load_bootstrap_rows, write_import_template,
)


DAY = date(2026, 8, 4)


def row(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {"symbol": "sz300308", "security_name": "中际旭创", "trading_date": DAY.isoformat(), "open": "10", "high": "12", "low": "9", "close": "11", "amount_yuan": "100", "source_name": "controlled_import", "source_reference": "user-reviewed-file", "imported_at": "2026-08-05T16:00:00+08:00", "verified": "true", "adjustment_mode": "unadjusted"}
    value.update(changes); return value


def csv_file(tmp_path: Path, values: list[dict[str, object]]) -> Path:
    path = tmp_path / "history.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ALL_COLUMNS); writer.writeheader(); writer.writerows(values)
    return path


def code(path: Path, **kwargs: object) -> str:
    with pytest.raises(SecurityProxyBootstrapError) as exc:
        load_bootstrap_rows(path, today=date(2026, 8, 5), **kwargs)
    return exc.value.code


def test_csv_json_dry_run_and_atomic_import(tmp_path: Path) -> None:
    rows = load_bootstrap_rows(csv_file(tmp_path, [row()]), today=date(2026, 8, 5))
    store = SecurityProxyEodFileStore(tmp_path / "out")
    assert import_bootstrap_rows(rows, store=store, dry_run=True) == (store.day_path(DAY),) and not store.day_path(DAY).exists()
    assert import_bootstrap_rows(rows, store=store) == (store.day_path(DAY),)
    assert store.records()[0].source == "controlled_bootstrap_import"
    document = tmp_path / "history.json"; document.write_text(json.dumps({"records": [row(symbol="sz300502")]}), encoding="utf-8")
    assert load_bootstrap_rows(document, today=date(2026, 8, 5))[0].symbol == "sz300502"


@pytest.mark.parametrize(("changes", "expected"), [
    ({"symbol": "sh510300"}, "bootstrap_rejected"), ({"trading_date": "2026-08-01"}, "bootstrap_rejected"),
    ({"trading_date": "2026-08-06"}, "bootstrap_rejected"), ({"adjustment_mode": "qfq"}, "bootstrap_rejected"),
    ({"low": "13"}, "bootstrap_rejected"), ({"source_reference": ""}, "bootstrap_rejected"),
])
def test_invalid_rows_reject_the_whole_batch(tmp_path: Path, changes: dict[str, object], expected: str) -> None:
    assert code(csv_file(tmp_path, [row(**changes)])) == expected


def test_duplicates_and_default_non_overwrite_fail_closed(tmp_path: Path) -> None:
    duplicate = csv_file(tmp_path, [row(), row()])
    assert code(duplicate) == "duplicate_security_date"
    values = load_bootstrap_rows(csv_file(tmp_path, [row()]), today=date(2026, 8, 5))
    store = SecurityProxyEodFileStore(tmp_path / "out")
    import_bootstrap_rows(values, store=store)
    with pytest.raises(FileExistsError): import_bootstrap_rows(values, store=store)


def test_missing_amount_preserves_price_history_but_disables_turnover(tmp_path: Path) -> None:
    values = load_bootstrap_rows(csv_file(tmp_path, [row(amount_yuan="")]), today=date(2026, 8, 5))
    store = SecurityProxyEodFileStore(tmp_path / "out"); import_bootstrap_rows(values, store=store)
    record = store.records()[0]
    assert record.amount_yuan is None and record.completeness_status == "partial_amount_missing"


def test_source_metadata_replaces_row_level_manual_verified_gate(tmp_path: Path) -> None:
    value = row(); value.pop("verified")
    assert load_bootstrap_rows(csv_file(tmp_path, [value]), today=date(2026, 8, 5))[0].verified is True


def test_template_has_every_approved_symbol_and_no_invented_prices(tmp_path: Path) -> None:
    path = write_import_template(tmp_path / "template.csv", trading_dates=(DAY, date(2026, 8, 5)))
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows and all(not item["close"] and item["adjustment_mode"] == "unadjusted" for item in rows)
