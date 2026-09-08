"""Bounded PDF preview calls; native PDFium never runs in the API process."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

from .services import WebDomainError

_LOG = logging.getLogger(__name__)
_SLOTS = threading.BoundedSemaphore(2)
_WORKER_TIMEOUT_SECONDS = 30
_QUEUE_TIMEOUT_SECONDS = 30
_UNAVAILABLE = "PDF预览暂不可用，可打开原始PDF"


def _worker_command(path: Path, page: int | None) -> list[str]:
    return [sys.executable, "-m", "leopard_project.web._pdf_preview_worker", str(path.resolve()), str(page) if page is not None else "info"]


def _run_worker(path: Path, page: int | None) -> bytes:
    if not _SLOTS.acquire(timeout=_QUEUE_TIMEOUT_SECONDS):
        raise WebDomainError("pdf_preview_unavailable", _UNAVAILABLE, 503)
    try:
        try:
            # No shell, inherited credentials, DB handles, or shared PDFium state.
            result = subprocess.run(
                _worker_command(path, page), capture_output=True,
                timeout=_WORKER_TIMEOUT_SECONDS, check=False,
                env={"PATH": os.defpath, "PYTHONPATH": os.pathsep.join(sys.path), "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            _LOG.warning("PDF preview worker unavailable: %s", type(exc).__name__)
            raise WebDomainError("pdf_preview_unavailable", _UNAVAILABLE, 503) from exc
        if result.returncode == 4:
            raise WebDomainError("pdf_page_not_found", "PDF page not found", 404)
        if result.returncode != 0:
            _LOG.warning("PDF preview worker exited with code %s", result.returncode)
            raise WebDomainError("pdf_preview_unavailable", _UNAVAILABLE, 503)
        return result.stdout
    finally:
        _SLOTS.release()


def preview_page_count(path: Path) -> int:
    try:
        count = json.loads(_run_worker(path, None))["page_count"]
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("invalid preview page count")
        return count
    except (ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, WebDomainError):
            raise
        raise WebDomainError("pdf_preview_unavailable", _UNAVAILABLE, 503) from exc


def preview_page_png(path: Path, page: int) -> bytes:
    if page < 1:
        raise WebDomainError("pdf_page_not_found", "PDF page not found", 404)
    png = _run_worker(path, page)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise WebDomainError("pdf_preview_unavailable", _UNAVAILABLE, 503)
    return png
