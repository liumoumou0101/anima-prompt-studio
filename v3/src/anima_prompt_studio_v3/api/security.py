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
    recovery_token: str = ""


class SessionManager:
    """One-time bootstrap, idle-expiring sessions and origin-scoped recovery keys.

    Recovery keys are returned only to an already authenticated client. The web
    client keeps them in localStorage (origin includes the port), never a cookie.
    All credentials disappear when this local server stops.
    """

    def __init__(self, *, bootstrap_ttl: int = 120, session_ttl: int = 3600,
                 recovery_ttl: int = 30 * 24 * 3600) -> None:
        if bootstrap_ttl <= 0 or session_ttl <= 0 or recovery_ttl <= 0:
            raise ValueError("session TTL 必须为正数。")
        self.bootstrap_ttl = bootstrap_ttl
        self.session_ttl = session_ttl
        self.recovery_ttl = recovery_ttl
        self._bootstrap: dict[str, float] = {}
        self._sessions: dict[str, float] = {}
        self._gallery: dict[str, str] = {}
        self._recovery: dict[str, float] = {}
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
            return self._issue_session(now)

    def restore(self, *, recovery_token: str = "", session_token: str = "") -> SessionExchange:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if recovery_token and _digest(recovery_token) in self._recovery:
                return self._issue_session(now, recovery_token)
            # Upgrade clients launched before recovery support without making
            # cookies sufficient to obtain a new bearer credential.
            if session_token and _digest(session_token) in self._sessions:
                return self._issue_session(now)
            raise SessionInvalidError("恢复凭据无效或已过期，请从桌面入口重新打开。")

    def create_local_session(self) -> SessionExchange:
        """Create a session after the desktop HTTP boundary has accepted a local client."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            return self._issue_session(now)

    def _issue_session(self, now: float, recovery_token: str = "") -> SessionExchange:
        session_token = secrets.token_urlsafe(32)
        recovery_token = recovery_token or secrets.token_urlsafe(32)
        self._sessions[_digest(session_token)] = now + self.session_ttl
        self._recovery[_digest(recovery_token)] = now + self.recovery_ttl
        return SessionExchange(session_token, self.session_ttl, recovery_token)

    def validate(self, session_token: str) -> bool:
        now = time.monotonic()
        digest = _digest(session_token)
        with self._lock:
            self._prune(now)
            expires_at = self._sessions.get(digest)
            if expires_at is None or expires_at <= now:
                return False
            self._sessions[digest] = now + self.session_ttl
            return True

    def revoke(self, session_token: str) -> None:
        with self._lock:
            self._sessions.pop(_digest(session_token), None)

    def gallery_token(self, session_token: str) -> str:
        """Derive an image-only credential; never put the API bearer in a cookie."""
        token = _digest("anima-v3-gallery:" + session_token)
        with self._lock:
            self._gallery[_digest(token)] = _digest(session_token)
        return token

    def validate_gallery(self, gallery_token: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            session_digest = self._gallery.get(_digest(gallery_token))
            if session_digest is None or session_digest not in self._sessions:
                return False
            self._sessions[session_digest] = now + self.session_ttl
            return True

    def _prune(self, now: float) -> None:
        self._bootstrap = {key: expiry for key, expiry in self._bootstrap.items() if expiry > now}
        self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
        self._gallery = {key: session for key, session in self._gallery.items() if session in self._sessions}
        self._recovery = {key: expiry for key, expiry in self._recovery.items() if expiry > now}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
