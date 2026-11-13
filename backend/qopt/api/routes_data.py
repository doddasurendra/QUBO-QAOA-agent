from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.tools import _clean
from ..config import get_settings
from ..db import Dataset, Experiment, Job, ResearchDocument, User, get_db
from ..industries import PROBLEMS
from ..services import research
from ..services.audit import audit
from ..services.jobs import resolve_model, runner
from ..services.reports import job_report_markdown
from .deps import researcher, viewer
from .routes_opt import ModelInput

router = APIRouter()


def _own(obj, user: User):
    if obj is None or (getattr(obj, "owner_id", None) not in (user.id, None) and user.role != "admin"):
        raise HTTPException(404, "not found")
    return obj


# ------------------------------------------------------------------ experiments
class ExperimentIn(ModelInput):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    tags: List[str] = []


def exp_out(e: Experiment, full: bool = False) -> dict:
    d = {"id": e.id, "name": e.name, "description": e.description, "source": e.source, "tags": e.tags or [],
         "created_at": e.created_at.isoformat(), "summary": e.summary}
    if full:
        d.update({"model_spec": e.model_spec, "input_data": e.input_data, "qubo": e.qubo})
    return d


@router.get("/experiments")
def list_experiments(user: User = Depends(viewer), db: Session = Depends(get_db)):
    stmt = select(Experiment).order_by(Experiment.id.desc())
    if user.role != "admin":
        stmt = stmt.where(Experiment.owner_id == user.id)
    return [exp_out(e) for e in db.scalars(stmt).all()]


@router.post("/experiments")
def create_experiment(body: ExperimentIn, user: User = Depends(researcher), db: Session = Depends(get_db)):
    params = body.model_dump(exclude={"name", "description", "tags"}, exclude_none=True)
    params.pop("experiment_id", None)
    try:
        q, cm, ind = resolve_model(params)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"invalid model: {e}")
    source = f"industry:{body.industry['key']}" if body.industry else ("custom" if body.spec else "matrix")
    e = Experiment(owner_id=user.id, name=body.name, description=body.description, source=source,
                   model_spec=body.spec, input_data=(ind[1].model_dump() if ind else None), qubo=q.to_dict(),
                   summary=_clean(cm.summary() if cm else q.stats()), tags=body.tags)
    db.add(e)
    db.commit()
    audit("experiment_create", user.id, f"experiment:{e.id}", db=db)
    return exp_out(e, True)


@router.get("/experiments/{eid}")
def get_experiment(eid: int, user: User = Depends(viewer), db: Session = Depends(get_db)):
    e = _own(db.get(Experiment, eid), user)
    jobs = db.scalars(select(Job).where(Job.experiment_id == eid).order_by(Job.id.desc())).all()
    return {**exp_out(e, True), "jobs": [job_out(j) for j in jobs]}


@router.delete("/experiments/{eid}")
def delete_experiment(eid: int, user: User = Depends(researcher), db: Session = Depends(get_db)):
    e = _own(db.get(Experiment, eid), user)
    db.delete(e)
    db.commit()
    audit("experiment_delete", user.id, f"experiment:{eid}", db=db)
    return {"deleted": True}


# ------------------------------------------------------------------ jobs
class JobIn(BaseModel):
    kind: str = Field(pattern="^(classical|qaoa|hybrid|benchmark|agent)$")
    params: Dict[str, Any] = {}
    experiment_id: Optional[int] = None


def job_out(j: Job, full: bool = False) -> dict:
    d = {"id": j.id, "kind": j.kind, "status": j.status, "experiment_id": j.experiment_id,
         "execution_kind": j.execution_kind, "is_real_hardware": j.is_real_hardware, "error": j.error,
         "created_at": j.created_at.isoformat(), "runtime_s": j.runtime_s,
         "finished_at": j.finished_at.isoformat() if j.finished_at else None,
         "solver": (j.params or {}).get("solver") or (j.params or {}).get("agent")}
    if full:
        d["params"] = j.params
        d["result"] = j.result
    return d


@router.post("/jobs")
def create_job(body: JobIn, user: User = Depends(researcher), db: Session = Depends(get_db)):
    if body.kind == "agent":
        raise HTTPException(400, "use POST /api/agents/{name}/run for agent jobs")
    params = dict(body.params)
    if body.experiment_id is not None:
        _own(db.get(Experiment, body.experiment_id), user)
        params["experiment_id"] = body.experiment_id
    try:
        j = runner.create(db, user.id, body.kind, params, body.experiment_id)
    except PermissionError as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit("job_create", user.id, f"job:{j.id}", detail={"kind": body.kind}, db=db)
    db.refresh(j)
    return job_out(j, True)


@router.get("/jobs")
def list_jobs(kind: Optional[str] = None, status: Optional[str] = None, limit: int = Query(100, le=500),
              user: User = Depends(viewer), db: Session = Depends(get_db)):
    stmt = select(Job).order_by(Job.id.desc()).limit(limit)
    if user.role != "admin":
        stmt = stmt.where(Job.owner_id == user.id)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    if status:
        stmt = stmt.where(Job.status == status)
    return [job_out(j) for j in db.scalars(stmt).all()]


@router.get("/jobs/{jid}")
def get_job(jid: int, user: User = Depends(viewer), db: Session = Depends(get_db)):
    return job_out(_own(db.get(Job, jid), user), True)


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: int, user: User = Depends(researcher), db: Session = Depends(get_db)):
    j = _own(db.get(Job, jid), user)
    if j.status not in ("queued", "running"):
        raise HTTPException(409, f"job is already {j.status}")
    st = runner.cancel(db, j)
    audit("job_cancel", user.id, f"job:{jid}", db=db)
    return {"status": st, "error": j.error}


# ------------------------------------------------------------------ reports
@router.get("/reports/jobs/{jid}")
def report(jid: int, format: str = Query("md", pattern="^(md|json)$"), user: User = Depends(viewer),
           db: Session = Depends(get_db)):
    j = _own(db.get(Job, jid), user)
    if j.status != "done":
        raise HTTPException(409, f"job is {j.status}; reports are generated for completed jobs")
    if format == "json":
        return PlainTextResponse(json.dumps(job_out(j, True), indent=2, default=str), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="job-{jid}.json"'})
    return PlainTextResponse(job_report_markdown(j), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="job-{jid}-report.md"'})


# ------------------------------------------------------------------ datasets
class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    problem_key: Optional[str] = None
    content: Any


def ds_out(d: Dataset, full=False) -> dict:
    o = {"id": d.id, "name": d.name, "description": d.description, "problem_key": d.problem_key,
         "is_sample": d.is_sample, "created_at": d.created_at.isoformat(), "owner_id": d.owner_id}
    if full:
        o["content"] = d.content
    return o


def _check_dataset(problem_key, content):
    if problem_key:
        if problem_key not in PROBLEMS:
            raise HTTPException(422, f"unknown problem_key {problem_key!r}")
        try:
            PROBLEMS[problem_key].parse(content)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"content does not match {problem_key} schema: {e}")


@router.get("/datasets")
def list_datasets(user: User = Depends(viewer), db: Session = Depends(get_db)):
    stmt = select(Dataset).order_by(Dataset.is_sample.desc(), Dataset.id.desc())
    if user.role != "admin":
        stmt = stmt.where((Dataset.owner_id == user.id) | (Dataset.owner_id.is_(None)))
    return [ds_out(d) for d in db.scalars(stmt).all()]


@router.get("/datasets/{did}")
def get_dataset(did: int, user: User = Depends(viewer), db: Session = Depends(get_db)):
    return ds_out(_own(db.get(Dataset, did), user), True)


@router.post("/datasets")
def create_dataset(body: DatasetIn, user: User = Depends(researcher), db: Session = Depends(get_db)):
    if len(json.dumps(body.content)) > get_settings().max_upload_bytes:
        raise HTTPException(413, "dataset too large")
    _check_dataset(body.problem_key, body.content)
    d = Dataset(owner_id=user.id, name=body.name, description=body.description, problem_key=body.problem_key,
                content=body.content)
    db.add(d)
    db.commit()
    audit("dataset_create", user.id, f"dataset:{d.id}", db=db)
    return ds_out(d, True)


@router.post("/datasets/upload")
async def upload_dataset(file: UploadFile = File(...), name: str = Form(...), problem_key: str = Form(""),
                         description: str = Form(""), user: User = Depends(researcher),
                         db: Session = Depends(get_db)):
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(413, "file too large")
    fn = (file.filename or "").lower()
    try:
        if fn.endswith(".json"):
            content = json.loads(data.decode("utf-8"))
        elif fn.endswith(".csv"):
            rows = list(csv.reader(io.StringIO(data.decode("utf-8"))))
            content = {"columns": rows[0] if rows else [], "rows": rows[1:]}
        else:
            raise HTTPException(415, "only .json and .csv datasets are accepted")
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as e:
        raise HTTPException(422, f"could not parse file: {e}")
    _check_dataset(problem_key or None, content)
    d = Dataset(owner_id=user.id, name=name[:255], description=description[:5000], problem_key=problem_key or None,
                content=content)
    db.add(d)
    db.commit()
    audit("dataset_upload", user.id, f"dataset:{d.id}", detail={"filename": file.filename, "bytes": len(data)}, db=db)
    return ds_out(d)


@router.delete("/datasets/{did}")
def delete_dataset(did: int, user: User = Depends(researcher), db: Session = Depends(get_db)):
    d = db.get(Dataset, did)
    if d is None or d.is_sample and user.role != "admin":
        raise HTTPException(403 if d else 404, "sample datasets can only be removed by admins" if d else "not found")
    _own(d, user)
    db.delete(d)
    db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ research library
@router.get("/research")
def list_docs(user: User = Depends(viewer), db: Session = Depends(get_db)):
    return [{"id": d.id, "title": d.title, "filename": d.filename, "size_bytes": d.size_bytes,
             "created_at": d.created_at.isoformat(), "preview": d.content[:300]}
            for d in db.scalars(select(ResearchDocument).order_by(ResearchDocument.id.desc())).all()]


@router.post("/research/upload")
async def upload_doc(file: UploadFile = File(...), title: str = Form(""), user: User = Depends(researcher),
                     db: Session = Depends(get_db)):
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(413, "file too large")
    try:
        text = research.extract_text(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(415, str(e))
    if not text.strip():
        raise HTTPException(422, "no extractable text")
    d = ResearchDocument(owner_id=user.id, title=(title or file.filename or "document")[:255],
                         filename=(file.filename or "")[:255], content=text, size_bytes=len(data))
    db.add(d)
    db.commit()
    audit("research_upload", user.id, f"research:{d.id}", db=db)
    return {"id": d.id, "title": d.title, "characters": len(text)}


@router.get("/research/search")
def search_docs(q: str = Query(min_length=2, max_length=500), limit: int = Query(5, le=20),
                _: User = Depends(viewer)):
    return {"query": q, "results": research.search(q, limit), "method": "BM25 over 160-word passages"}


@router.get("/research/{did}")
def get_doc(did: int, _: User = Depends(viewer), db: Session = Depends(get_db)):
    d = db.get(ResearchDocument, did)
    if d is None:
        raise HTTPException(404, "not found")
    return {"id": d.id, "title": d.title, "filename": d.filename, "content": d.content}


@router.delete("/research/{did}")
def delete_doc(did: int, user: User = Depends(researcher), db: Session = Depends(get_db)):
    d = _own(db.get(ResearchDocument, did), user)
    db.delete(d)
    db.commit()
    return {"deleted": True}
