from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import ApiKey, User, get_db
from ..services.security import ROLE_RANK, decode_token, hash_api_key, rate_limiter

bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def current_user(request: Request, creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    user: Optional[User] = None
    api_key = request.headers.get("x-api-key")
    if api_key:
        k = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key), ApiKey.revoked.is_(False)))
        if k:
            user = db.get(User, k.user_id)
            k.last_used_at = datetime.now(timezone.utc)
            db.commit()
    elif creds:
        try:
            claims = decode_token(creds.credentials)
            user = db.get(User, int(claims["sub"]))
        except (jwt.PyJWTError, KeyError, ValueError):
            user = None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    ok, retry = rate_limiter.allow(f"user:{user.id}", get_settings().rate_limit_per_minute)
    if not ok:
        raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(int(retry) + 1)})
    request.state.user_id = user.id
    return user


def require(role: str) -> Callable:
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_RANK.get(user.role, -1) < ROLE_RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role '{role}'")
        return user
    return dep


viewer = require("viewer")
researcher = require("researcher")
admin = require("admin")
