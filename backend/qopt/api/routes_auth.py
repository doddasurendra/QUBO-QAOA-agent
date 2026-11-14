from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import ApiKey, User, get_db
from ..services.audit import audit
from ..services.security import ROLES, create_token, hash_password, new_api_key, rate_limiter, verify_password
from .deps import admin, client_ip, current_user

router = APIRouter()


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class NewUser(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=72)
    name: str = Field(default="", max_length=255)
    role: str = "researcher"


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    name: Optional[str] = None


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None}


def _create(db: Session, body: NewUser, role: str) -> User:
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "email already registered")
    try:
        ph = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    u = User(email=body.email.lower(), name=body.name, password_hash=ph, role=role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@router.get("/auth/status")
def auth_status(db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).select_from(User)) or 0
    s = get_settings()
    return {"bootstrap_required": n == 0, "registration_open": s.allow_registration,
            "bootstrap_token_required": n == 0 and s.bootstrap_token_required()}


@router.post("/auth/bootstrap")
def bootstrap(body: NewUser, request: Request, db: Session = Depends(get_db)):
    """Create the first administrator. Only works while the user table is empty."""
    if (db.scalar(select(func.count()).select_from(User)) or 0) > 0:
        raise HTTPException(403, "bootstrap already completed")
    s = get_settings()
    if s.bootstrap_token_required():
        ip = client_ip(request)
        ok, retry = rate_limiter.allow(f"bootstrap:{ip}", 10)
        if not ok:
            raise HTTPException(429, "too many attempts", headers={"Retry-After": str(int(retry) + 1)})
        if not s.bootstrap_token:
            raise HTTPException(403, "administrator setup is disabled: set QOPT_BOOTSTRAP_TOKEN on the server")
        supplied = request.headers.get("x-bootstrap-token", "")
        if not hmac.compare_digest(supplied.encode(), s.bootstrap_token.encode()):
            audit("bootstrap_admin", None, body.email.lower(), success=False, ip=ip, db=db)
            raise HTTPException(403, "invalid setup token")
    u = _create(db, body, "admin")
    audit("bootstrap_admin", u.id, f"user:{u.id}", ip=client_ip(request), db=db)
    tok, exp = create_token(u.id, u.role)
    return {"access_token": tok, "token_type": "bearer", "expires_in": exp, "user": user_out(u)}


@router.post("/auth/login")
def login(body: Credentials, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    ok, retry = rate_limiter.allow(f"login:{ip}", 10)
    if not ok:
        raise HTTPException(429, "too many login attempts", headers={"Retry-After": str(int(retry) + 1)})
    u = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        audit("login", u.id if u else None, body.email.lower(), success=False, ip=ip, db=db)
        raise HTTPException(401, "invalid email or password")
    audit("login", u.id, f"user:{u.id}", ip=ip, db=db)
    tok, exp = create_token(u.id, u.role)
    return {"access_token": tok, "token_type": "bearer", "expires_in": exp, "user": user_out(u)}


@router.post("/auth/register")
def register(body: NewUser, request: Request, db: Session = Depends(get_db)):
    if not get_settings().allow_registration:
        raise HTTPException(403, "self-registration is disabled; ask an administrator")
    u = _create(db, body, "researcher")
    audit("register", u.id, f"user:{u.id}", ip=client_ip(request), db=db)
    return user_out(u)


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


# ------------------------------------------------------------------ users (admin)
@router.get("/users")
def list_users(_: User = Depends(admin), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users")
def create_user(body: NewUser, me_: User = Depends(admin), db: Session = Depends(get_db)):
    u = _create(db, body, body.role)
    audit("user_create", me_.id, f"user:{u.id}", detail={"role": u.role}, db=db)
    return user_out(u)


@router.patch("/users/{uid}")
def update_user(uid: int, body: UserUpdate, me_: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "user not found")
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, f"role must be one of {ROLES}")
        if u.id == me_.id and body.role != "admin":
            raise HTTPException(400, "you cannot remove your own admin role")
        u.role = body.role
    if body.is_active is not None:
        if u.id == me_.id and not body.is_active:
            raise HTTPException(400, "you cannot deactivate yourself")
        u.is_active = body.is_active
    if body.name is not None:
        u.name = body.name
    db.commit()
    audit("user_update", me_.id, f"user:{uid}", detail=body.model_dump(exclude_none=True), db=db)
    return user_out(u)


# ------------------------------------------------------------------ API keys
class NewKey(BaseModel):
    name: str = Field(min_length=1, max_length=128)


@router.get("/apikeys")
def list_keys(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ks = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc())).all()
    return [{"id": k.id, "name": k.name, "prefix": k.prefix, "revoked": k.revoked,
             "created_at": k.created_at.isoformat(), "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}
            for k in ks]


@router.post("/apikeys")
def create_key(body: NewKey, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "viewer":
        raise HTTPException(403, "viewers cannot create API keys")
    raw, prefix, h = new_api_key()
    k = ApiKey(user_id=user.id, name=body.name, prefix=prefix, key_hash=h)
    db.add(k)
    db.commit()
    audit("apikey_create", user.id, f"apikey:{k.id}", db=db)
    return {"id": k.id, "name": k.name, "prefix": prefix, "key": raw,
            "note": "Store this key now; it is not shown again. Send it as the X-API-Key header."}


@router.delete("/apikeys/{kid}")
def revoke_key(kid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    k = db.get(ApiKey, kid)
    if not k or (k.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "key not found")
    k.revoked = True
    db.commit()
    audit("apikey_revoke", user.id, f"apikey:{kid}", db=db)
    return {"revoked": True}
