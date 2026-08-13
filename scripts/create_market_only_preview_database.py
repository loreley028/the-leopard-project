"""Create a zero-report SQLite preview containing only objective market tables.

The source remains read-only.  The target starts from the application's schema
and receives only ``live_market_anchor_daily`` and ``security_proxy_daily``.
No report, assessment, PDF, path, or legacy sector-validation row is copied.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from leopard_project.web.database import create_session_factory


MARKET_TABLES = ("live_market_anchor_daily", "security_proxy_daily")
ZERO_REPORT_TABLES = ("reports", "report_days", "sector_assessments", "sector_path_history_entries")


def _columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))


def create_market_only_database(source: Path, target: Path) -> dict[str, int]:
    source, target = source.resolve(), target.resolve()
    if not source.is_file():
        raise ValueError("source database does not exist")
    if target.exists():
        raise ValueError("target database already exists; refusing to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if temporary.exists():
        raise ValueError("temporary target already exists")
    try:
        create_session_factory(f"sqlite:///{temporary}").kw["bind"].dispose()
        connection = sqlite3.connect(temporary)
        source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            source_tables = {row[0] for row in source_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            copied: dict[str, int] = {}
            for table in MARKET_TABLES:
                if table not in source_tables:
                    copied[table] = 0
                    continue
                target_columns, source_columns = _columns(connection, table), _columns(source_connection, table)
                columns = tuple(column for column in target_columns if column in source_columns)
                if not columns:
                    copied[table] = 0
                    continue
                quoted = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)
                rows = source_connection.execute(f"SELECT {quoted} FROM {table}").fetchall()
                connection.executemany(f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})", rows)
                copied[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ZERO_REPORT_TABLES:
                copied[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            connection.commit()
        finally:
            source_connection.close()
            connection.close()
        os.replace(temporary, target)
        return copied
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(create_market_only_database(args.source, args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
