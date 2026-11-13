from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from ..agents import AGENTS, TOOLS, credentials_status
from ..config import get_settings
from ..db import ApprovalRequest, AuditLog, Dataset, Experiment, Job, ResearchDocument, UsageRecord, User, get_db
from ..providers.registry import registry
from ..services.agent_bridge import agent_spend_today
from ..services.audit import audit
from ..services.jobs import runner
from ..services.security import rate_limiter
from .deps import admin, researcher, viewer
from .routes_data import job_out

router = APIRouter()
def docs_dir() -> Path:
    return get_settings().docs_path()


# ------------------------------------------------------------------ agents
@router.get("/agents")
def agents(_: User = Depends(viewer)):
    return {"credentials": credentials_status(),
            "agents": [{"name": a.name, "title": a.title, "role": a.role, "effort": a.effort,
                        "tools": [{"name": t, "requires_approval": TOOLS[t].requires_approval} for t in a.tools],
                        "can_delegate": a.can_delegate} for a in AGENTS.values()],
            "budgets": {"per_run_usd": get_settings().agent_run_budget_usd,
                        "per_user_daily_usd": get_settings().agent_daily_budget_usd}}


class AgentRunIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    continue_job_id: Optional[int] = None


@router.post("/agents/{name}/run")
def run_agent(name: str, body: AgentRunIn, user: User = Depends(researcher), db: Session = Depends(get_db)):
    if name not in AGENTS:
        raise HTTPException(404, f"unknown agent {name!r}")
    if not credentials_status()["api_credentials_in_env"]:
        raise HTTPException(503, "AI agents are unavailable: no Anthropic API credentials are configured on the "
                                 "server (ANTHROPIC_API_KEY). Optimisation tools remain usable directly.")
    s = get_settings()
    ok, retry = rate_limiter.allow(f"agent:{user.id}", s.agent_rate_limit_per_minute)
    if not ok:
        raise HTTPException(429, "agent rate limit exceeded", headers={"Retry-After": str(int(retry) + 1)})
    spent = agent_spend_today(user.id)
    if spent >= s.agent_daily_budget_usd:
        raise HTTPException(429, f"daily agent budget reached (${spent:.2f} of ${s.agent_daily_budget_usd:.2f})")
    history = None
    if body.continue_job_id:
        prev = db.get(Job, body.continue_job_id)
        if prev is None or prev.owner_id != user.id or prev.kind != "agent" or not prev.result:
            raise HTTPException(404, "previous agent job not found")
        history = prev.result.get("messages")
    try:
        j = runner.create(db, user.id, "agent", {"agent": name, "message": body.message, "history": history})
    except PermissionError as e:
        raise HTTPException(429, str(e))
    audit("agent_run", user.id, f"job:{j.id}", detail={"agent": name}, db=db)
    db.refresh(j)
    return job_out(j, True)


# ------------------------------------------------------------------ approvals (hardware jobs)
class ApprovalIn(BaseModel):
    experiment_id: int
    provider: str
    backend: str = Field(min_length=1, max_length=256)
    shots: int = Field(default=1000, ge=1, le=100000)
    p: int = Field(default=1, ge=1, le=10)
    justification: str = Field(default="", max_length=2000)


class ReviewIn(BaseModel):
    note: str = Field(default="", max_length=2000)


def apr_out(a: ApprovalRequest) -> dict:
    return {"id": a.id, "requester_id": a.requester_id, "kind": a.kind, "payload": a.payload, "status": a.status,
            "reviewer_id": a.reviewer_id, "review_note": a.review_note, "job_id": a.job_id,
            "created_at": a.created_at.isoformat(), "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None}


@router.get("/approvals")
def list_approvals(user: User = Depends(viewer), db: Session = Depends(get_db)):
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.id.desc())
    if user.role != "admin":
        stmt = stmt.where(ApprovalRequest.requester_id == user.id)
    return [apr_out(a) for a in db.scalars(stmt).all()]


@router.post("/approvals")
def request_hardware(body: ApprovalIn, user: User = Depends(researcher), db: Session = Depends(get_db)):
    try:
        registry.get(body.provider)
    except KeyError as e:
        raise HTTPException(404, str(e))
    exp = db.get(Experiment, body.experiment_id)
    if exp is None or (exp.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "experiment not found")
    a = ApprovalRequest(requester_id=user.id, payload=body.model_dump())
    db.add(a)
    db.commit()
    audit("approval_requested", user.id, f"approval:{a.id}", detail=body.model_dump(), db=db)
    return apr_out(a)


@router.post("/approvals/{aid}/approve")
def approve(aid: int, body: ReviewIn, me_: User = Depends(admin), db: Session = Depends(get_db)):
    a = db.get(ApprovalRequest, aid)
    if a is None:
        raise HTTPException(404, "not found")
    if a.status != "pending":
        raise HTTPException(409, f"approval is already {a.status}")
    prov = registry.get(a.payload["provider"])
    st = prov.status()
    if not st.get("available"):
        raise HTTPException(409, f"provider {a.payload['provider']} unavailable: SDK installed="
                                 f"{st.get('sdk_installed')}, missing credentials={st.get('missing_credentials')}")
    a.status, a.reviewer_id, a.review_note = "approved", me_.id, body.note
    a.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    params = {**a.payload, "approval_id": a.id}
    j = runner.create(db, a.requester_id, "hardware", params, a.payload.get("experiment_id"), enforce_quota=False)
    a.job_id = j.id
    db.commit()
    audit("approval_approved", me_.id, f"approval:{aid}", detail={"job_id": j.id}, db=db)
    return apr_out(a)


@router.post("/approvals/{aid}/reject")
def reject(aid: int, body: ReviewIn, me_: User = Depends(admin), db: Session = Depends(get_db)):
    a = db.get(ApprovalRequest, aid)
    if a is None:
        raise HTTPException(404, "not found")
    if a.status != "pending":
        raise HTTPException(409, f"approval is already {a.status}")
    a.status, a.reviewer_id, a.review_note = "rejected", me_.id, body.note
    a.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    audit("approval_rejected", me_.id, f"approval:{aid}", db=db)
    return apr_out(a)


# ------------------------------------------------------------------ admin / usage / dashboard
@router.get("/admin/audit")
def audit_log(limit: int = Query(200, le=2000), action: Optional[str] = None, _: User = Depends(admin),
              db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [{"id": r.id, "ts": r.ts.isoformat(), "user_id": r.user_id, "action": r.action, "resource": r.resource,
             "success": r.success, "ip": r.ip, "detail": r.detail} for r in db.scalars(stmt).all()]


@router.get("/admin/config")
def admin_config(_: User = Depends(admin)):
    s = get_settings()
    return {"version": __version__, "environment": s.environment,
            "database": s.database_url.split("://", 1)[0], "jwt_secret_configured": bool(s.jwt_secret),
            "allow_registration": s.allow_registration, "worker_threads": s.worker_threads,
            "job_timeout_s": s.job_timeout_s, "max_concurrent_jobs_per_user": s.max_concurrent_jobs_per_user,
            "max_statevector_qubits": s.max_statevector_qubits, "rate_limit_per_minute": s.rate_limit_per_minute,
            "agent_daily_budget_usd": s.agent_daily_budget_usd, "agent_run_budget_usd": s.agent_run_budget_usd,
            "max_upload_bytes": s.max_upload_bytes, "anthropic": credentials_status(),
            "providers": registry.status()}


@router.get("/usage/summary")
def usage(days: int = Query(30, ge=1, le=365), user: User = Depends(viewer), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(UsageRecord).where(UsageRecord.ts >= since)
    if user.role != "admin":
        stmt = stmt.where(UsageRecord.user_id == user.id)
    rows = db.scalars(stmt).all()
    by_day: dict = {}
    for r in rows:
        d = r.ts.date().isoformat()
        e = by_day.setdefault(d, {"date": d, "agent_cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0,
                                  "compute_s": 0.0, "hardware_jobs": 0})
        e["agent_cost_usd"] += r.cost_usd
        e["input_tokens"] += r.input_tokens
        e["output_tokens"] += r.output_tokens
        e["compute_s"] += r.compute_s
        e["hardware_jobs"] += 1 if r.category == "hardware" else 0
    totals = {"agent_cost_usd": sum(r.cost_usd for r in rows), "input_tokens": sum(r.input_tokens for r in rows),
              "output_tokens": sum(r.output_tokens for r in rows), "compute_s": sum(r.compute_s for r in rows)}
    return {"days": days, "totals": totals, "by_day": sorted(by_day.values(), key=lambda e: e["date"]),
            "agent_cost_note": "estimated from token counts × list prices",
            "hardware_cost_note": "QPU costs are billed by providers and are not estimated here"}


@router.get("/dashboard/overview")
def overview(user: User = Depends(viewer), db: Session = Depends(get_db)):
    own = (lambda col: col == user.id) if user.role != "admin" else (lambda col: True)
    cnt = lambda model, *w: db.scalar(select(func.count()).select_from(model).where(*w)) or 0
    jobs_by = db.execute(select(Job.status, func.count()).where(own(Job.owner_id)).group_by(Job.status)).all()
    kinds = db.execute(select(Job.kind, func.count()).where(own(Job.owner_id)).group_by(Job.kind)).all()
    recent = db.scalars(select(Job).where(own(Job.owner_id)).order_by(Job.id.desc()).limit(10)).all()
    return {"experiments": cnt(Experiment, own(Experiment.owner_id)),
            "datasets": cnt(Dataset), "research_documents": cnt(ResearchDocument),
            "jobs_by_status": {s: c for s, c in jobs_by}, "jobs_by_kind": {k: c for k, c in kinds},
            "real_hardware_jobs": cnt(Job, own(Job.owner_id), Job.is_real_hardware.is_(True)),
            "pending_approvals": cnt(ApprovalRequest, ApprovalRequest.status == "pending"),
            "users": cnt(User) if user.role == "admin" else None,
            "providers_available": [p["name"] for p in registry.status() if p.get("available")],
            "agents_available": credentials_status()["api_credentials_in_env"],
            "recent_jobs": [job_out(j) for j in recent], "data_source": "live application database"}


# ------------------------------------------------------------------ documentation
@router.get("/docs-content")
def docs_list(_: User = Depends(viewer)):
    d = docs_dir()
    if not d.is_dir():
        return []
    return [{"slug": p.stem, "title": (p.read_text(encoding="utf-8").splitlines() or [p.stem])[0].lstrip("# ")}
            for p in sorted(d.glob("*.md"))]


@router.get("/docs-content/{slug}")
def docs_get(slug: str, _: User = Depends(viewer)):
    if not slug.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "invalid slug")
    p = docs_dir() / f"{slug}.md"
    if not p.is_file():
        raise HTTPException(404, "not found")
    return {"slug": slug, "markdown": p.read_text(encoding="utf-8")}
