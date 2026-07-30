from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError


# The production topology intentionally has one API worker.  This process-wide
# lock coordinates short SQLite write phases; Provider network I/O must never
# occur while it is held.
BACKGROUND_WRITE_LOCK = threading.RLock()

T = TypeVar("T")


class SQLiteWriteLockExhausted(RuntimeError):
    """Raised after the bounded SQLite lock retry budget is exhausted."""


def coordinated_write(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    initial_delay_seconds: float = 0.05,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Serialize short writes and retry only SQLite lock conflicts with backoff."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            with BACKGROUND_WRITE_LOCK:
                return operation()
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            if attempt + 1 == attempts:
                raise SQLiteWriteLockExhausted(f"sqlite_write_lock_exhausted_after_{attempts}_attempts") from exc
            sleep(initial_delay_seconds * (2 ** attempt))
    raise AssertionError("unreachable")
