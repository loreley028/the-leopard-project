from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class Principal:
    username: str
    role: str


class SessionAuth:
    def __init__(self, secret: str, users: dict[str, tuple[str, str]], ttl_seconds: int = 28_800) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 characters")
        self._secret = secret.encode()
        self._users = users
        self._ttl_seconds = ttl_seconds

    def authenticate(self, username: str, password: str) -> Principal:
        stored = self._users.get(username)
        if stored is None or not hmac.compare_digest(stored[0], password):
            raise AuthenticationError("invalid credentials")
        return Principal(username=username, role=stored[1])

    def issue(self, principal: Principal, now: int | None = None) -> str:
        payload = {"sub": principal.username, "role": principal.role, "exp": (now or int(time.time())) + self._ttl_seconds}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
        signature = hmac.new(self._secret, encoded, hashlib.sha256).hexdigest().encode()
        return (encoded + b"." + signature).decode()

    def verify(self, token: str, now: int | None = None) -> Principal:
        try:
            encoded, supplied = token.encode().split(b".", 1)
            expected = hmac.new(self._secret, encoded, hashlib.sha256).hexdigest().encode()
            if not hmac.compare_digest(supplied, expected):
                raise AuthenticationError("invalid session")
            padded = encoded + b"=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            if int(payload["exp"]) < (now or int(time.time())):
                raise AuthenticationError("expired session")
            if payload["role"] not in {"viewer", "admin"}:
                raise AuthenticationError("invalid role")
            return Principal(username=payload["sub"], role=payload["role"])
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            if isinstance(exc, AuthenticationError):
                raise
            raise AuthenticationError("invalid session") from exc
