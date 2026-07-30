from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


SQLITE_ADDITIVE_COLUMNS = {
    "market_refresh_runs": {
        "short_history_count": "INTEGER NOT NULL DEFAULT 0",
        "unsupported_count": "INTEGER NOT NULL DEFAULT 0",
    },
    "sector_intraday_snapshots": {
        "provider_symbol": "VARCHAR(120)",
        "lineage": "TEXT",
        "source_status": "VARCHAR(40) NOT NULL DEFAULT 'available'",
        "freshness_status": "VARCHAR(40) NOT NULL DEFAULT 'intraday_fresh'",
        "intraday_ma5": "NUMERIC(20, 6)",
        "intraday_vs_ma5": "NUMERIC(16, 6)",
        "native_history_status": "VARCHAR(40) NOT NULL DEFAULT 'unavailable'",
    },
    "market_refresh_items": {
        "provider": "VARCHAR(100)",
        "provider_symbol": "VARCHAR(120)",
        "lineage": "TEXT",
        "error_code": "VARCHAR(80)",
        "error_message": "TEXT",
        "expected_trade_date": "DATE",
        "attempt_number": "INTEGER NOT NULL DEFAULT 1",
        "attempted_at": "DATETIME",
        "next_retry_at": "DATETIME",
        "completed_at": "DATETIME",
    },
    "intraday_refresh_sessions": {
        "heartbeat_at": "DATETIME",
        "lease_expires_at": "DATETIME",
        "owner_instance_id": "VARCHAR(64)",
        "finished_at": "DATETIME",
        "terminal_reason": "VARCHAR(80)",
    },
}


def _apply_sqlite_additive_columns(engine) -> None:
    """Upgrade the ignored local SQLite database without rebuilding its data."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in SQLITE_ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing_columns = {item["name"] for item in inspector.get_columns(table)}
            for name, declaration in columns.items():
                if name not in existing_columns:
                    connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    if database_url.startswith("sqlite:///"):
        path = Path(database_url.removeprefix("sqlite:///"))
        if path != Path(":memory:"):
            path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10.0} if database_url.startswith("sqlite") else {},
    )
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=10000")
            if database_url != "sqlite:///:memory:":
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    Base.metadata.create_all(engine)
    if database_url.startswith("sqlite"):
        _apply_sqlite_additive_columns(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE intraday_refresh_sessions SET status='cancelled', "
                "finished_at=COALESCE(finished_at, paused_at), "
                "terminal_reason=COALESCE(terminal_reason, 'legacy_pause_migration') "
                "WHERE status='paused'"
            )
    return sessionmaker(bind=engine, expire_on_commit=False)
