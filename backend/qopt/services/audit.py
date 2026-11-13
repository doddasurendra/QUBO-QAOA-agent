from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select

from ..db import AuditLog, SessionLocal

log = logging.getLogger("qopt.audit")
_SECRET = re.compile(r"(sk-ant-[\w-]+|qopt_[\w-]{10,}|(?i:password|token|secret|api_key)\"?\s*[:=]\s*\"?[^\s\",}]+)")


def redact(obj):
    """Remove anything that looks like a credential before it reaches logs or the DB."""
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if re.search(r"(?i)password|secret|token|api_key", str(k)) else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET.sub("[REDACTED]", obj)
    return obj


def audit(action: str, user_id: Optional[int] = None, resource: str = "", success: bool = True,
          ip: str = "", detail: Optional[dict] = None, db=None):
    own = db is None
    db = db or SessionLocal()
    try:
        db.add(AuditLog(action=action, user_id=user_id, resource=resource, success=success, ip=ip,
                        detail=redact(detail or {})))
        db.commit()
    finally:
        if own:
            db.close()
    log.info("audit action=%s user=%s resource=%s success=%s", action, user_id, resource, success)


def audit_summary(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with SessionLocal() as db:
        rows = db.execute(select(AuditLog.action, AuditLog.success, func.count())
                          .where(AuditLog.ts >= since).group_by(AuditLog.action, AuditLog.success)).all()
        failed_logins = db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.ts >= since, AuditLog.action == "login", AuditLog.success.is_(False))) or 0
    return {"window_hours": hours, "failed_logins": failed_logins,
            "events": [{"action": a, "success": s, "count": c} for a, s, c in rows]}
