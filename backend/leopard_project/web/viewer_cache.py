from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Successful HTTP mutations are the primary invalidation mechanism.  These
# TTLs are safety bounds for non-HTTP database writers and process/topology
# changes, selected according to the least-stable field in each payload.
ENHANCED_CACHE_SECONDS = 5
SECTORS_CACHE_SECONDS = 15 * 60
SECTOR_VIEW_CACHE_SECONDS = 12 * 60 * 60
PATH_MATRIX_CACHE_SECONDS = 90 * 60
REPORTS_CACHE_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class CachedHttpResponse:
    status: int
    headers: tuple[tuple[bytes, bytes], ...]
    body: bytes
    expires_at: float


class ViewerResponseCache:
    """Small process-local cache for expensive anonymous, read-only payloads."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._items: dict[bytes, CachedHttpResponse] = {}
        self._generation = 0

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def get(self, key: bytes) -> CachedHttpResponse | None:
        now = self.clock()
        with self._lock:
            item = self._items.get(key)
            if item is None or item.expires_at <= now:
                self._items.pop(key, None)
                return None
            return item

    def put(
        self,
        key: bytes,
        status: int,
        headers: list[tuple[bytes, bytes]],
        body: bytes,
        ttl_seconds: int,
        expected_generation: int,
    ) -> None:
        with self._lock:
            if self._generation != expected_generation:
                return
            self._items[key] = CachedHttpResponse(status, tuple(headers), body, self.clock() + ttl_seconds)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._generation += 1


def _replace_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> list[tuple[bytes, bytes]]:
    lowered = name.lower()
    return [(key, item) for key, item in headers if key.lower() != lowered] + [(name, value)]


class ViewerResponseCacheMiddleware:
    """Cache only anonymous GETs; every successful mutation invalidates them."""

    def __init__(self, app: ASGIApp, cache: ViewerResponseCache) -> None:
        self.app = app
        self.cache = cache

    @staticmethod
    def _ttl(scope: Scope) -> int | None:
        if scope["method"] != "GET":
            return None
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        if headers.get(b"cookie"):
            return None
        path = scope["path"]
        if path == "/api/v1/sectors/view":
            return SECTOR_VIEW_CACHE_SECONDS
        if path == "/api/v1/sectors":
            return SECTORS_CACHE_SECONDS
        if path == "/api/v1/reports":
            return REPORTS_CACHE_SECONDS
        if path.startswith("/api/v1/reports/") and path.endswith("/path-matrix"):
            return PATH_MATRIX_CACHE_SECONDS
        if path.startswith("/api/v1/reports/") and path.endswith("/enhanced"):
            return ENHANCED_CACHE_SECONDS
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ttl = self._ttl(scope)
        if ttl is None:
            await self._pass_through(scope, receive, send)
            return
        key = scope["path"].encode() + b"?" + scope.get("query_string", b"")
        cached = self.cache.get(key)
        if cached is not None:
            headers = _replace_header(list(cached.headers), b"x-leopard-cache", b"hit")
            await send({"type": "http.response.start", "status": cached.status, "headers": headers})
            await send({"type": "http.response.body", "body": cached.body})
            return

        generation = self.cache.generation()
        status = 0
        response_headers: list[tuple[bytes, bytes]] = []
        body = bytearray()
        complete = False

        async def capture(message: Message) -> None:
            nonlocal status, response_headers, complete
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = _replace_header(list(message.get("headers", [])), b"x-leopard-cache", b"miss")
                message = {**message, "headers": response_headers}
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                complete = not message.get("more_body", False)
            await send(message)

        await self.app(scope, receive, capture)
        if status == 200 and complete:
            self.cache.put(key, status, response_headers, bytes(body), ttl, generation)

    async def _pass_through(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        status = 0

        async def invalidate_after_success(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            if message["type"] == "http.response.body" and not message.get("more_body", False) and 200 <= status < 400:
                self.cache.clear()
            await send(message)

        await self.app(scope, receive, invalidate_after_success)
