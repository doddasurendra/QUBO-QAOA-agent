"""Background job execution with status persisted in the database.

Jobs run on a bounded thread pool. Python threads cannot be killed, so a job exceeding the
timeout is marked ``timeout`` (its late result is stored with ``late=True`` if it ever
finishes). Queued jobs can be cancelled; running jobs record ``cancel_requested``.
``worker_threads = 0`` executes jobs inline (used by tests and the CLI).
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
from sqlalchemy import func, select

from ..agents.tools import AgentContext, _clean
from ..config import get_settings
from ..core.model import CompiledModel, Model
from ..core.qubo import QUBO
from ..db import ApprovalRequest, Experiment, Job, SessionLocal, UsageRecord
from ..industries import get_problem
from .audit import audit

log = logging.getLogger("qopt.jobs")
ACTIVE = ("queued", "running")


# ------------------------------------------------------------------------------ model resolution
def resolve_model(params: dict, db=None) -> Tuple[QUBO, Optional[CompiledModel], Optional[tuple]]:
    """Return (qubo, compiled_model_or_None, (industry_problem, data)_or_None) from job params."""
    if params.get("experiment_id"):
        own = db is None
        db = db or SessionLocal()
        try:
            exp = db.get(Experiment, int(params["experiment_id"]))
            if exp is None:
                raise ValueError(f"experiment {params['experiment_id']} not found")
            params = {**({"industry": {"key": exp.source.split(":", 1)[1], "data": exp.input_data}}
                         if exp.source.startswith("industry:") else {}),
                      **({"spec": exp.model_spec} if exp.model_spec and not exp.source.startswith("industry:") else {}),
                      **({"qubo": exp.qubo} if not exp.model_spec and exp.qubo else {})}
        finally:
            if own:
                db.close()
    if params.get("industry"):
        prob = get_problem(params["industry"]["key"])
        data, cm = prob.compile(params["industry"]["data"], float(params.get("penalty_scale", 1.0)))
        return cm.qubo, cm, (prob, data)
    if params.get("spec"):
        cm = Model.from_spec(params["spec"]).compile(float(params.get("penalty_scale", 1.0)))
        return cm.qubo, cm, None
    if params.get("qubo"):
        return QUBO.from_dict(params["qubo"]), None, None
    raise ValueError("job needs one of experiment_id, industry, spec or qubo")


def interpret(industry: Optional[tuple], cm: Optional[CompiledModel], bitstring: Optional[str]):
    if not (industry and cm and bitstring):
        return None
    ev = cm.evaluate(np.array([int(c) for c in bitstring]))
    return {"evaluation": ev.to_dict(), "interpretation": industry[0].interpret(industry[1], ev.assignment)}


# ------------------------------------------------------------------------------ executors
def _exec_classical(job: Job, params: dict) -> dict:
    from ..solvers.classical import SOLVERS
    q, cm, ind = resolve_model(params)
    s = params.get("solver", "simulated_annealing")
    if s not in SOLVERS:
        raise ValueError(f"unknown solver {s!r}")
    r = SOLVERS[s](q, **(params.get("options") or {}))
    out = r.to_dict()
    if cm is not None:
        out["evaluation"] = cm.evaluate(r.best_x).to_dict()
    out["domain"] = interpret(ind, cm, out["best_bitstring"])
    return out


def _qaoa_cfg(d: dict):
    from ..quantum.qaoa import QAOAConfig
    allowed = set(QAOAConfig.__dataclass_fields__)
    cfg = QAOAConfig(**{k: v for k, v in (d or {}).items() if k in allowed})
    cfg.max_qubits = min(cfg.max_qubits, get_settings().max_statevector_qubits)
    return cfg


def _exec_qaoa(job: Job, params: dict) -> dict:
    from ..quantum.circuits import build_qaoa_circuit, circuit_summary
    from ..quantum.qaoa import run_qaoa
    q, cm, ind = resolve_model(params)
    cfg = _qaoa_cfg(params.get("config"))
    r = run_qaoa(q, cfg, cm)
    out = r.to_dict()
    qc, *_ = build_qaoa_circuit(q, cfg.p)
    out["circuit"] = circuit_summary(qc)
    best = r.best_sample["bitstring"] if r.best_sample else None
    out["domain"] = interpret(ind, cm, best)
    return out


def _exec_hybrid(job: Job, params: dict) -> dict:
    from ..hybrid.engine import HybridRequest, run_hybrid
    q, cm, ind = resolve_model(params)
    hw = params.get("hardware")
    if hw and not hw.get("provider", "").startswith("qiskit_aer"):
        raise PermissionError("hardware execution must go through the approval workflow (POST /api/approvals)")
    req = HybridRequest(solvers=params.get("solvers") or ["auto"], qaoa=_qaoa_cfg(params.get("qaoa")),
                        hardware=hw, classical_options=params.get("classical_options") or {})
    rep = run_hybrid(q, req, cm)
    if rep["ranking"]:
        top = next((r for r in rep["results"] if r["solver"] == rep["ranking"][0]["solver"]), None)
        rep["domain"] = interpret(ind, cm, top.get("bitstring") if top else None)
    return rep


def _exec_hardware(job: Job, params: dict) -> dict:
    """Only reachable from an approved ApprovalRequest (see approve endpoint)."""
    from ..hybrid.engine import HybridRequest, run_hybrid
    with SessionLocal() as db:
        apr = db.get(ApprovalRequest, int(params["approval_id"]))
        if apr is None or apr.status != "approved":
            raise PermissionError("hardware job is not approved")
    q, cm, ind = resolve_model(params)
    hw = {"provider": params["provider"], "backend": params["backend"], "shots": int(params.get("shots", 1000)),
          "approval_id": str(params["approval_id"])}
    rep = run_hybrid(q, HybridRequest(solvers=[], qaoa=_qaoa_cfg({"p": params.get("p", 1)}), hardware=hw), cm)
    if rep["errors"]:
        raise RuntimeError("; ".join(e["error"] for e in rep["errors"]))
    return rep


def _exec_benchmark(job: Job, params: dict) -> dict:
    from ..benchmark import run_benchmark, to_markdown
    rep = run_benchmark(params.get("problems", ["maxcut_gnp"]), params.get("sizes", [6, 8]),
                        int(params.get("seeds", 3)), params.get("solvers"), params.get("qaoa_depths", [1, 2]),
                        int(params.get("qaoa_shots", 1024)), int(params.get("qaoa_maxiter", 80)))
    rep["markdown"] = to_markdown(rep)
    return rep


def _exec_agent(job: Job, params: dict) -> dict:
    from ..agents.runtime import AgentRuntime, Budget
    from .agent_bridge import make_context, record_agent_usage, serialize_messages
    s = get_settings()
    ctx = make_context(job.owner_id)
    rt = AgentRuntime(budget=Budget(max_cost_usd=s.agent_run_budget_usd),
                      logger=lambda e: log.info("agent %s", e))
    r = rt.run(params["agent"], params["message"], ctx, history=params.get("history"))
    record_agent_usage(job.owner_id, params["agent"], r.usage)
    out = r.to_dict()
    out["messages"] = serialize_messages(getattr(r, "messages", []))
    return out


EXECUTORS: Dict[str, Callable[[Job, dict], dict]] = {
    "classical": _exec_classical, "qaoa": _exec_qaoa, "hybrid": _exec_hybrid, "hardware": _exec_hardware,
    "benchmark": _exec_benchmark, "agent": _exec_agent,
}


# ------------------------------------------------------------------------------ runner
class JobRunner:
    def __init__(self):
        self._pool: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[int, Future] = {}
        self._lock = threading.Lock()

    def _ensure(self):
        n = get_settings().worker_threads
        if n > 0 and self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=n, thread_name_prefix="qopt-job")

    def create(self, db, owner_id: int, kind: str, params: dict, experiment_id: Optional[int] = None,
               enforce_quota: bool = True) -> Job:
        if kind not in EXECUTORS:
            raise ValueError(f"unknown job kind {kind!r}")
        if enforce_quota:
            active = db.scalar(select(func.count()).select_from(Job).where(Job.owner_id == owner_id,
                                                                          Job.status.in_(ACTIVE))) or 0
            if active >= get_settings().max_concurrent_jobs_per_user:
                raise PermissionError(f"quota: at most {get_settings().max_concurrent_jobs_per_user} "
                                      "concurrent jobs per user")
        job = Job(owner_id=owner_id, kind=kind, params=_clean(params), experiment_id=experiment_id,
                  status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        self.submit(job.id)
        return job

    def submit(self, job_id: int):
        self._ensure()
        if self._pool is None:
            self._run(job_id)
            return
        fut = self._pool.submit(self._run, job_id)
        with self._lock:
            self._futures[job_id] = fut
        t = threading.Timer(get_settings().job_timeout_s, self._timeout, args=(job_id,))
        t.daemon = True
        t.start()

    def _timeout(self, job_id: int):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job and job.status in ACTIVE:
                job.status = "timeout"
                job.error = f"exceeded {get_settings().job_timeout_s}s timeout"
                job.finished_at = datetime.now(timezone.utc)
                db.commit()

    def cancel(self, db, job: Job) -> str:
        with self._lock:
            fut = self._futures.get(job.id)
        if job.status == "queued" and (fut is None or fut.cancel()):
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
        elif job.status == "running":
            job.status = "running"
            job.error = "cancel_requested (running computations cannot be interrupted; result will be discarded)"
            job.params = {**job.params, "_cancel_requested": True}
        db.commit()
        return job.status

    def _run(self, job_id: int):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "queued":
                return
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.commit()
            params, kind, owner = dict(job.params), job.kind, job.owner_id
        t0 = time.perf_counter()
        result, error = None, None
        try:
            result = _clean(EXECUTORS[kind](job, params))
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            log.warning("job %s failed: %s\n%s", job_id, error, traceback.format_exc())
        elapsed = time.perf_counter() - t0
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            late = job.status == "timeout"
            if job.params.get("_cancel_requested"):
                job.status, result = "cancelled", None
            elif late:
                if result is not None:
                    job.result = {"late": True, **result}
            else:
                job.status = "error" if error else "done"
                job.result, job.error = result, error
            job.finished_at = datetime.now(timezone.utc)
            job.runtime_s = elapsed
            if result:
                kinds = _execution_kinds(result)
                job.execution_kind = ",".join(sorted(kinds)) if kinds else None
                job.is_real_hardware = _any_real(result)
            db.add(UsageRecord(user_id=owner, category="hardware" if kind == "hardware" else "compute",
                               compute_s=elapsed, detail={"job_id": job_id, "kind": kind}))
            db.commit()
        audit(f"job_{'error' if error else 'done'}", owner, f"job:{job_id}", success=error is None,
              detail={"kind": kind, "error": error})


def _execution_kinds(result: Any) -> set:
    out = set()
    if isinstance(result, dict):
        if isinstance(result.get("execution_kind"), str):
            out.add(result["execution_kind"])
        for r in result.get("results", []) or []:
            if isinstance(r, dict) and r.get("execution_kind"):
                out.add(r["execution_kind"])
    return out


def _any_real(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("is_real_hardware") is True:
        return True
    return any(isinstance(r, dict) and r.get("is_real_hardware") is True for r in result.get("results", []) or [])


runner = JobRunner()
