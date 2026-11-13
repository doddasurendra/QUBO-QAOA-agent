"""Tools that agents can call. Every tool executes real platform code (no LLM-made results).

A tool returns a JSON-serialisable dict. Tools flagged ``requires_approval`` never perform the
sensitive action themselves: they create an approval request through the context hook.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ..core.model import CompiledModel, Model
from ..core.validation import validate_compiled, validate_qubo
from ..hybrid.engine import HybridRequest, recommend_solvers, run_hybrid
from ..industries import PROBLEMS, get_problem
from ..providers.registry import registry
from ..quantum.circuits import build_qaoa_circuit, circuit_summary, draw_text
from ..quantum.qaoa import QAOAConfig, run_qaoa
from ..solvers.classical import SOLVERS


class NeedsUserInput(Exception):
    def __init__(self, questions: List[str], reason: str):
        super().__init__(reason)
        self.questions = questions
        self.reason = reason


@dataclass
class StoredModel:
    model_id: str
    compiled: CompiledModel
    industry_key: Optional[str] = None
    industry_data: Any = None
    assumptions: List[str] = field(default_factory=list)


@dataclass
class AgentContext:
    """Per-run workspace + hooks supplied by the API layer (DB persistence, approvals, research)."""
    user_id: Optional[int] = None
    models: Dict[str, StoredModel] = field(default_factory=dict)
    on_model_created: Optional[Callable[[StoredModel], None]] = None
    request_approval: Optional[Callable[[dict], str]] = None       # returns approval id
    search_research: Optional[Callable[[str, int], List[dict]]] = None
    audit_summary: Optional[Callable[[], dict]] = None
    artifacts: List[dict] = field(default_factory=list)

    def store(self, compiled: CompiledModel, **kw) -> StoredModel:
        sm = StoredModel(f"m_{uuid.uuid4().hex[:10]}", compiled, **kw)
        self.models[sm.model_id] = sm
        if self.on_model_created:
            self.on_model_created(sm)
        return sm

    def get(self, model_id: str) -> StoredModel:
        if model_id not in self.models:
            raise KeyError(f"unknown model_id {model_id!r}; formulate a model first "
                           f"(known: {sorted(self.models)})")
        return self.models[model_id]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[[AgentContext, dict], dict]
    requires_approval: bool = False

    def api_definition(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def _clean(o):
    """Make numpy / nested objects JSON-safe and bounded."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, float) and not np.isfinite(o):
        return str(o)
    return o


def _model_summary(sm: StoredModel) -> dict:
    s = sm.compiled.summary()
    s["model_id"] = sm.model_id
    s["assumptions"] = sm.assumptions
    return s


# ----------------------------------------------------------------------------- tool functions
def t_list_industry_problems(ctx, inp):
    return {"problems": [{"key": p.key, "industry": p.industry, "title": p.title,
                          "description": p.description} for p in PROBLEMS.values()]}


def t_describe_industry_problem(ctx, inp):
    return get_problem(inp["key"]).describe()


def t_formulate_industry_problem(ctx, inp):
    prob = get_problem(inp["key"])
    data, cm = prob.compile(inp["data"], float(inp.get("penalty_scale", 1.0)))
    sm = ctx.store(cm, industry_key=prob.key, industry_data=data, assumptions=list(inp.get("assumptions", [])))
    return {**_model_summary(sm), "formulation": prob.formulation, "limitations": prob.limitations}


def t_formulate_custom_model(ctx, inp):
    m = Model.from_spec(inp["spec"])
    cm = m.compile(float(inp.get("penalty_scale", 1.0)))
    sm = ctx.store(cm, assumptions=list(inp.get("assumptions", [])))
    return _model_summary(sm)


def t_validate_formulation(ctx, inp):
    sm = ctx.get(inp["model_id"])
    out = {"structural": validate_qubo(sm.compiled.qubo)}
    if sm.compiled.num_decision <= 20 and sm.compiled.qubo.num_variables <= 22:
        out["exhaustive"] = validate_compiled(sm.compiled).to_dict()
    else:
        out["exhaustive"] = {"skipped": "too many variables for exhaustive validation (>20 decision)"}
    return out


def t_inspect_qubo(ctx, inp):
    sm = ctx.get(inp["model_id"])
    q = sm.compiled.qubo
    lim = int(inp.get("max_terms", 60))
    ising = q.to_ising()
    return {"variables": q.variables, "stats": q.stats(),
            "linear": dict(list({q.variables[i]: c for i, c in q.linear.items()}.items())[:lim]),
            "quadratic": [[q.variables[i], q.variables[j], c] for (i, j), c in list(q.quadratic.items())[:lim]],
            "offset": q.offset,
            "ising": {"h": dict(list({q.variables[i]: c for i, c in ising.h.items()}.items())[:lim]),
                      "J": [[q.variables[i], q.variables[j], c] for (i, j), c in list(ising.J.items())[:lim]],
                      "offset": ising.offset},
            "truncated": len(q.quadratic) > lim}


def t_recommend_solvers(ctx, inp):
    sm = ctx.get(inp["model_id"])
    return {"recommendations": recommend_solvers(sm.compiled.qubo, registry.status(), int(inp.get("p", 1)))}


def t_run_classical_solver(ctx, inp):
    sm = ctx.get(inp["model_id"])
    solver = inp["solver"]
    if solver not in SOLVERS:
        raise ValueError(f"solver must be one of {sorted(SOLVERS)}")
    r = SOLVERS[solver](sm.compiled.qubo, **(inp.get("options") or {}))
    ev = sm.compiled.evaluate(r.best_x)
    out = {"result": r.to_dict(max_samples=5), "evaluation": ev.to_dict()}
    if sm.industry_key:
        out["interpretation"] = get_problem(sm.industry_key).interpret(sm.industry_data, ev.assignment)
    return out


def t_run_qaoa_simulation(ctx, inp):
    sm = ctx.get(inp["model_id"])
    cfg = QAOAConfig(p=int(inp.get("p", 1)), optimizer=inp.get("optimizer", "COBYLA"),
                     maxiter=int(inp.get("maxiter", 150)), restarts=int(inp.get("restarts", 2)),
                     mixer=inp.get("mixer", "x"), shots=int(inp.get("shots", 2048)), seed=inp.get("seed", 7))
    r = run_qaoa(sm.compiled.qubo, cfg, sm.compiled)
    d = r.to_dict()
    d["ranked_samples"] = d["ranked_samples"][:8]
    d.pop("counts"); d["history"] = d["history"][-20:]
    for rs in d["restarts"]:
        rs["history"] = rs["history"][-5:]
    if sm.industry_key and r.best_sample and r.best_sample.get("feasible"):
        a = sm.compiled.evaluate(np.array([int(c) for c in r.best_sample["bitstring"]])).assignment
        d["interpretation"] = get_problem(sm.industry_key).interpret(sm.industry_data, a)
    return d


def t_run_hybrid(ctx, inp):
    sm = ctx.get(inp["model_id"])
    req = HybridRequest(solvers=inp.get("solvers") or ["auto"],
                        qaoa=QAOAConfig(p=int(inp.get("p", 1)), restarts=2, maxiter=120))
    rep = run_hybrid(sm.compiled.qubo, req, sm.compiled)
    for r in rep["results"]:
        r.pop("history", None); r.pop("assignment", None)
    rep.pop("solver_selection", None)
    return rep


def t_qaoa_circuit(ctx, inp):
    sm = ctx.get(inp["model_id"])
    qc, *_ = build_qaoa_circuit(sm.compiled.qubo, int(inp.get("p", 1)))
    out = {"summary": circuit_summary(qc)}
    if qc.num_qubits <= 8:
        out["diagram"] = draw_text(qc, fold=100)
    return out


def t_list_providers(ctx, inp):
    return {"providers": registry.status()}


def t_submit_hardware_job(ctx, inp):
    """Never submits: creates an approval request that an admin must approve."""
    sm = ctx.get(inp["model_id"])
    if ctx.request_approval is None:
        return {"status": "approval_unavailable",
                "message": "no approval workflow is configured; hardware jobs cannot be submitted by agents"}
    req = {"model_id": sm.model_id, "provider": inp["provider"], "backend": inp["backend"],
           "shots": int(inp.get("shots", 1000)), "p": int(inp.get("p", 1)),
           "num_qubits": sm.compiled.qubo.num_variables, "justification": inp.get("justification", "")}
    aid = ctx.request_approval(req)
    return {"status": "approval_required", "approval_id": aid,
            "message": "An administrator must approve this hardware job before it is submitted. "
                       "No job has been sent to any quantum provider."}


def t_request_missing_information(ctx, inp):
    raise NeedsUserInput(list(inp["questions"]), inp.get("reason", "missing information"))


def t_search_research_library(ctx, inp):
    if ctx.search_research is None:
        return {"results": [], "note": "research library not connected"}
    return {"results": ctx.search_research(inp["query"], int(inp.get("limit", 5)))}


def t_security_audit_summary(ctx, inp):
    if ctx.audit_summary is None:
        return {"note": "audit log not connected"}
    return ctx.audit_summary()


def t_record_finding(ctx, inp):
    ctx.artifacts.append({"type": "finding", "title": inp["title"], "body": inp["body"],
                          "severity": inp.get("severity", "info")})
    return {"recorded": True, "count": len(ctx.artifacts)}


S = lambda props, req: {"type": "object", "properties": props, "required": req}
MID = {"model_id": {"type": "string", "description": "id returned by a formulate_* tool"}}

TOOLS: Dict[str, Tool] = {t.name: t for t in [
    Tool("list_industry_problems", "List the built-in industry optimisation templates.", S({}, []),
         t_list_industry_problems),
    Tool("describe_industry_problem", "Get the input JSON schema, mathematical formulation, limitations and "
         "a SAMPLE example for one industry template.", S({"key": {"type": "string"}}, ["key"]),
         t_describe_industry_problem),
    Tool("formulate_industry_problem", "Build and compile a QUBO from an industry template using user-provided "
         "data that matches the template's input schema. Returns model_id and compile summary.",
         S({"key": {"type": "string"}, "data": {"type": "object"},
            "penalty_scale": {"type": "number", "description": "multiplier on automatic penalty (default 1)"},
            "assumptions": {"type": "array", "items": {"type": "string"},
                            "description": "every assumption you made, stated explicitly"}}, ["key", "data"]),
         t_formulate_industry_problem),
    Tool("formulate_custom_model", "Compile a custom binary model spec into a QUBO. spec = {variables:[names], "
         "sense:'min'|'max', objective:{constant, linear:{var:coef}, quadratic:[[u,v,coef]]}, constraints:[{label, "
         "lhs:{linear:{...}, quadratic:[...]}, sense:'=='|'<='|'>=', rhs:number, kind?:'one_hot'}]}. Inequalities "
         "need integer coefficients.",
         S({"spec": {"type": "object"}, "penalty_scale": {"type": "number"},
            "assumptions": {"type": "array", "items": {"type": "string"}}}, ["spec"]), t_formulate_custom_model),
    Tool("validate_formulation", "Independently validate a compiled model: structural checks, QUBO↔Ising "
         "equivalence, and (small models) exhaustive check that penalties dominate and the QUBO optimum is the "
         "true constrained optimum.", S(MID, ["model_id"]), t_validate_formulation),
    Tool("inspect_qubo", "Return QUBO coefficients and the equivalent Ising h, J, offset.",
         S({**MID, "max_terms": {"type": "integer"}}, ["model_id"]), t_inspect_qubo),
    Tool("recommend_solvers", "Transparent solver recommendations with reasons for a model.",
         S({**MID, "p": {"type": "integer"}}, ["model_id"]), t_recommend_solvers),
    Tool("run_classical_solver", "Run a classical solver: exhaustive | milp | simulated_annealing | tabu_search | "
         "greedy_descent. Returns the best solution evaluated against the ORIGINAL constraints.",
         S({**MID, "solver": {"type": "string"}, "options": {"type": "object"}}, ["model_id", "solver"]),
         t_run_classical_solver),
    Tool("run_qaoa_simulation", "Run QAOA on the exact statevector SIMULATOR (≤22 qubits). Not real hardware.",
         S({**MID, "p": {"type": "integer"}, "optimizer": {"type": "string"}, "maxiter": {"type": "integer"},
            "restarts": {"type": "integer"}, "mixer": {"type": "string", "enum": ["x", "xy_ring"]},
            "shots": {"type": "integer"}, "seed": {"type": "integer"}}, ["model_id"]), t_run_qaoa_simulation),
    Tool("run_hybrid_benchmark", "Run several solvers (default: auto-selected classical + QAOA simulation), "
         "validate and rank them.", S({**MID, "solvers": {"type": "array", "items": {"type": "string"}},
                                       "p": {"type": "integer"}}, ["model_id"]), t_run_hybrid),
    Tool("get_qaoa_circuit", "Build the QAOA circuit for a model and return gate counts/depth (and a text "
         "diagram for ≤8 qubits).", S({**MID, "p": {"type": "integer"}}, ["model_id"]), t_qaoa_circuit),
    Tool("list_quantum_providers", "List quantum providers with SDK/credential availability (honest status).",
         S({}, []), t_list_providers),
    Tool("submit_hardware_job", "Request execution on real quantum hardware. ALWAYS creates an approval request "
         "for an administrator; never submits directly.",
         S({**MID, "provider": {"type": "string"}, "backend": {"type": "string"}, "shots": {"type": "integer"},
            "p": {"type": "integer"}, "justification": {"type": "string"}}, ["model_id", "provider", "backend"]),
         t_submit_hardware_job, requires_approval=True),
    Tool("request_missing_information", "Stop and ask the user for essential data you do not have. Use instead "
         "of inventing numbers or business constraints.",
         S({"questions": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}},
           ["questions"]), t_request_missing_information),
    Tool("search_research_library", "Search documents users uploaded to the research library.",
         S({"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]), t_search_research_library),
    Tool("security_audit_summary", "Summarise recent audit-log activity (failed logins, approvals, hardware "
         "requests, agent tool usage).", S({}, []), t_security_audit_summary),
    Tool("record_finding", "Record a structured finding (review result, risk, limitation) in the run output.",
         S({"title": {"type": "string"}, "body": {"type": "string"},
            "severity": {"type": "string", "enum": ["info", "low", "medium", "high"]}}, ["title", "body"]),
         t_record_finding),
]}


def execute_tool(name: str, ctx: AgentContext, inp: dict) -> dict:
    return _clean(TOOLS[name].fn(ctx, inp or {}))


def to_json(result: dict, limit: int = 30000) -> str:
    s = json.dumps(result, default=str)
    if len(s) > limit:
        s = s[:limit] + f'... [truncated {len(s) - limit} chars]'
    return s
