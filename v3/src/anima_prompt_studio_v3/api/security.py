from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass


class SessionInvalidError(ValueError):
    pass


@dataclass(frozen=True)
class SessionExchange:
    token: str
    expires_in: int


class SessionManager:
    """In-memory, one-time bootstrap and short-lived API sessions."""

    def __init__(self, *, bootstrap_ttl: int = 120, session_ttl: int = 3600) -> None:
        if bootstrap_ttl <= 0 or session_ttl <= 0:
            raise ValueError("session TTL 必须为正数。")
        self.bootstrap_ttl = bootstrap_ttl
        self.session_ttl = session_ttl
        self._bootstrap: dict[str, float] = {}
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    def issue_bootstrap_token(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._prune(time.monotonic())
            self._bootstrap[_digest(token)] = time.monotonic() + self.bootstrap_ttl
        return token

    def exchange(self, bootstrap_token: str) -> SessionExchange:
        now = time.monotonic()
        digest = _digest(bootstrap_token)
        with self._lock:
            self._prune(now)
            expires_at = self._bootstrap.pop(digest, None)
            if expires_at is None or expires_at <= now:
                raise SessionInvalidError("bootstrap token 无效、已使用或已过期。")
            session_token = secrets.token_urlsafe(32)
            self._sessions[_digest(session_token)] = now + self.session_ttl
        return SessionExchange(token=session_token, expires_in=self.session_ttl)

    def validate(self, session_token: str) -> bool:
        now = time.monotonic()
        digest = _digest(session_token)
        with self._lock:
            self._prune(now)
            expires_at = self._sessions.get(digest)
            return expires_at is not None and expires_at > now

    def revoke(self, session_token: str) -> None:
        with self._lock:
            self._sessions.pop(_digest(session_token), None)

    def _prune(self, now: float) -> None:
        self._bootstrap = {key: expiry for key, expiry in self._bootstrap.items() if expiry > now}
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
