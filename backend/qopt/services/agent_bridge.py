"""Connect the agent runtime to persistence: experiments, approvals, research search, usage."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ..agents.tools import AgentContext, StoredModel
from ..db import ApprovalRequest, Experiment, SessionLocal, UsageRecord
from . import research
from .audit import audit, audit_summary


def make_context(user_id: int) -> AgentContext:
    def on_model(sm: StoredModel):
        with SessionLocal() as db:
            src = f"industry:{sm.industry_key}" if sm.industry_key else "agent"
            data = sm.industry_data.model_dump() if sm.industry_data is not None else None
            exp = Experiment(owner_id=user_id, name=f"Agent model {sm.model_id}", source=src,
                             model_spec=None if sm.industry_key else sm.compiled.model.to_spec(),
                             input_data=data, qubo=sm.compiled.qubo.to_dict(), summary=sm.compiled.summary(),
                             description="Created by an AI agent. Assumptions: " + "; ".join(sm.assumptions),
                             tags=["agent", sm.model_id])
            db.add(exp)
            db.commit()

    def request_approval(req: dict) -> str:
        with SessionLocal() as db:
            payload = dict(req)
            exps = db.scalars(select(Experiment).where(Experiment.owner_id == user_id)
                              .order_by(Experiment.id.desc())).all()
            match = next((e for e in exps if e.tags and req["model_id"] in e.tags), None)
            if match is None:
                raise ValueError(f"model {req['model_id']} was not persisted; cannot request hardware execution")
            payload["experiment_id"] = match.id
            apr = ApprovalRequest(requester_id=user_id, kind="hardware_job", payload=payload)
            db.add(apr)
            db.commit()
            audit("approval_requested", user_id, f"approval:{apr.id}", detail={"by": "agent", **req})
            return str(apr.id)

    return AgentContext(user_id=user_id, on_model_created=on_model, request_approval=request_approval,
                        search_research=lambda q, k: research.search(q, k, owner_id=None),
                        audit_summary=audit_summary)


def record_agent_usage(user_id: int, agent: str, usage) -> None:
    with SessionLocal() as db:
        db.add(UsageRecord(user_id=user_id, category="agent", input_tokens=usage.input_tokens,
                           output_tokens=usage.output_tokens, cost_usd=usage.cost_usd,
                           detail={"agent": agent, "requests": usage.requests,
                                   "cache_read_tokens": usage.cache_read_tokens}))
        db.commit()


def agent_spend_today(user_id: int) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=1)
    with SessionLocal() as db:
        return float(db.scalar(select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
            UsageRecord.user_id == user_id, UsageRecord.category == "agent", UsageRecord.ts >= since)) or 0.0)


def serialize_messages(messages) -> list:
    """Convert SDK content blocks to plain dicts so a conversation can be continued later."""
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, list):
            blocks = []
            for b in c:
                if isinstance(b, dict):
                    blocks.append(b)
                elif hasattr(b, "model_dump"):
                    blocks.append(b.model_dump(exclude_none=True))
                else:
                    blocks.append({k: v for k, v in vars(b).items()})
            c = blocks
        out.append({"role": m["role"], "content": c})
    return out
