from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Deque, Dict, Tuple

import bcrypt
import jwt

from ..config import get_settings

ROLES = ("admin", "researcher", "viewer")
ROLE_RANK = {"viewer": 0, "researcher": 1, "admin": 2}


def hash_password(pw: str) -> str:
    if len(pw) < 10:
        raise ValueError("password must be at least 10 characters")
    if len(pw.encode()) > 72:
        raise ValueError("password must be at most 72 bytes (bcrypt limit)")
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], h.encode())
    except ValueError:
        return False


def create_token(user_id: int, role: str) -> Tuple[str, int]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expiry_minutes)
    tok = jwt.encode({"sub": str(user_id), "role": role, "exp": exp, "iat": datetime.now(timezone.utc),
                      "typ": "access"}, s.effective_jwt_secret(), algorithm="HS256")
    return tok, s.jwt_expiry_minutes * 60


def decode_token(tok: str) -> dict:
    return jwt.decode(tok, get_settings().effective_jwt_secret(), algorithms=["HS256"],
                      options={"require": ["exp", "sub"]})


def new_api_key() -> Tuple[str, str, str]:
    """Returns (plaintext key shown once, prefix, sha256 hash stored)."""
    raw = "qopt_" + secrets.token_urlsafe(32)
    return raw, raw[:12], hashlib.sha256(raw.encode()).hexdigest()


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class RateLimiter:
    """Sliding-window limiter (in-process). For multi-replica deployments use a shared store."""

    def __init__(self):
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_s: float = 60.0) -> Tuple[bool, float]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return False, window_s - (now - q[0])
            q.append(now)
            return True, 0.0

    def reset(self):
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
