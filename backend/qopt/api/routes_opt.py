from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..agents.tools import _clean
from ..core.preprocess import reduce_qubo
from ..core.qubo import QUBO, Ising
from ..core.validation import validate_compiled, validate_qubo
from ..db import Experiment, User, get_db
from ..hybrid.engine import recommend_solvers
from ..industries import PROBLEMS, get_problem
from ..providers.base import ProviderUnavailable
from ..providers.registry import registry
from ..quantum.circuits import bind, build_qaoa_circuit, circuit_summary, draw_text, gate_list, to_qasm3
from ..quantum.mixers import make_mixer
from ..quantum.qaoa import OPTIMIZERS, StatevectorQAOA
from ..services.jobs import resolve_model
from .deps import researcher, viewer

router = APIRouter()
SYNC_QUBO_LIMIT = 400


class ModelInput(BaseModel):
    spec: Optional[Dict[str, Any]] = None
    qubo: Optional[Dict[str, Any]] = None
    industry: Optional[Dict[str, Any]] = None       # {"key": ..., "data": {...}}
    experiment_id: Optional[int] = None
    penalty_scale: float = Field(default=1.0, gt=0, le=1000)


def _resolve(m: ModelInput, db: Session, user: User):
    if m.experiment_id is not None:
        exp = db.get(Experiment, m.experiment_id)
        if exp is None or (exp.owner_id != user.id and user.role != "admin"):
            raise HTTPException(404, "experiment not found")
    try:
        q, cm, ind = resolve_model(m.model_dump(exclude_none=True), db)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"invalid model: {e}")
    if q.num_variables > SYNC_QUBO_LIMIT:
        raise HTTPException(413, f"model has {q.num_variables} variables; interactive endpoints are limited to "
                                 f"{SYNC_QUBO_LIMIT} (submit a job instead)")
    return q, cm, ind


def _qubo_view(q: QUBO, include_matrix: bool) -> dict:
    out = {"qubo": q.to_dict(), "stats": q.stats(), "ising": q.to_ising().to_dict()}
    if include_matrix and q.num_variables <= 120:
        out["matrix_upper"] = q.to_matrix("upper").tolist()
        out["matrix_symmetric"] = q.to_matrix("symmetric").tolist()
    return out


# ------------------------------------------------------------------ QUBO
class CompileReq(ModelInput):
    include_matrix: bool = True


@router.post("/qubo/compile")
def compile_model(body: CompileReq, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, cm, ind = _resolve(body, db, user)
    out = _qubo_view(q, body.include_matrix)
    out["structural_validation"] = validate_qubo(q)
    if cm is not None:
        out["summary"] = cm.summary()
        out["decision_variables"] = cm.decision_variables
        out["slack_variables"] = cm.slack_variables
    if ind is not None:
        out["formulation"] = ind[0].formulation
        out["limitations"] = ind[0].limitations
    return _clean(out)


@router.post("/qubo/validate")
def validate(body: ModelInput, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, cm, _ = _resolve(body, db, user)
    out = {"structural": validate_qubo(q)}
    if cm is not None:
        if cm.num_decision <= 20 and q.num_variables <= 22:
            out["exhaustive"] = validate_compiled(cm).to_dict()
        else:
            out["exhaustive"] = {"skipped": f"{cm.num_decision} decision / {q.num_variables} QUBO variables exceed "
                                            "the exhaustive validation limit (20 / 22)"}
    return _clean(out)


class MatrixReq(BaseModel):
    matrix: List[List[float]]
    offset: float = 0.0
    variables: Optional[List[str]] = None
    convention: str = Field(default="auto", pattern="^(auto|upper|symmetric)$")


@router.post("/qubo/from-matrix")
def from_matrix(body: MatrixReq, _: User = Depends(viewer)):
    if len(body.matrix) > SYNC_QUBO_LIMIT:
        raise HTTPException(413, "matrix too large")
    try:
        q = QUBO.from_matrix(np.array(body.matrix, float), body.offset, body.variables, body.convention)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _clean({**_qubo_view(q, True), "structural_validation": validate_qubo(q)})


class IsingReq(BaseModel):
    variables: List[str]
    h: Dict[str, float] = {}
    J: List[List[float]] = []
    offset: float = 0.0


@router.post("/qubo/from-ising")
def from_ising(body: IsingReq, _: User = Depends(viewer)):
    try:
        I = Ising.from_dict(body.model_dump())
        q = I.to_qubo()
    except (ValueError, KeyError, IndexError) as e:
        raise HTTPException(422, str(e))
    return _clean({**_qubo_view(q, True), "structural_validation": validate_qubo(q)})


@router.post("/qubo/reduce")
def reduce(body: ModelInput, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, _, _ = _resolve(body, db, user)
    red = reduce_qubo(q)
    return _clean({**red.to_dict(), "fixed_variables": {q.variables[i]: v for i, v in red.fixed.items()},
                   "reduced_qubo": red.reduced.to_dict(),
                   "rule": "first-order dominance (a_i + Σ min(0,b_ij) ≥ 0 ⇒ x_i=0; a_i + Σ max(0,b_ij) ≤ 0 ⇒ x_i=1)"})


class EvalReq(ModelInput):
    bitstring: str = Field(pattern="^[01]+$")


@router.post("/qubo/evaluate")
def evaluate(body: EvalReq, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, cm, ind = _resolve(body, db, user)
    x = np.array([int(c) for c in body.bitstring])
    if cm is not None:
        if len(x) not in (cm.num_decision, q.num_variables):
            raise HTTPException(422, f"bitstring must have {cm.num_decision} (decision) or {q.num_variables} bits")
        rep = cm.evaluate(x)
        out = rep.to_dict()
        if ind:
            out["interpretation"] = ind[0].interpret(ind[1], rep.assignment)
        return _clean(out)
    if len(x) != q.num_variables:
        raise HTTPException(422, f"bitstring must have {q.num_variables} bits")
    return {"qubo_energy": q.energy(x), "ising_energy": q.to_ising().energy(1 - 2 * x)}


# ------------------------------------------------------------------ solvers / QAOA
@router.get("/solvers")
def solvers(_: User = Depends(viewer)):
    return {
        "classical": [
            {"name": "exhaustive", "exact": True, "limit": "≤ 24 variables", "description": "enumerates all 2^n states"},
            {"name": "milp", "exact": True, "limit": "quadratic terms ≤ ~5000",
             "description": "Fortet linearisation solved by HiGHS (SciPy)"},
            {"name": "simulated_annealing", "exact": False, "options": ["num_reads", "num_sweeps", "seed"]},
            {"name": "tabu_search", "exact": False, "options": ["max_iter", "restarts", "tenure", "seed"]},
            {"name": "greedy_descent", "exact": False, "options": ["restarts", "seed"]}],
        "quantum": [{"name": "qaoa_statevector", "execution_kind": "statevector_simulator",
                     "limit": "≤ 22 qubits", "optimizers": OPTIMIZERS, "mixers": ["x", "xy_ring"]}],
    }


class CircuitReq(ModelInput):
    p: int = Field(default=1, ge=1, le=10)
    mixer: str = "x"
    gammas: Optional[List[float]] = None
    betas: Optional[List[float]] = None


def _mixer_for(name, cm):
    return make_mixer(name, cm.one_hot_groups() if (cm is not None and name != "x") else None)


@router.post("/qaoa/circuit")
def circuit(body: CircuitReq, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, cm, _ = _resolve(body, db, user)
    if q.num_variables > 64:
        raise HTTPException(413, "circuit rendering limited to 64 qubits")
    try:
        mixer = _mixer_for(body.mixer, cm)
    except ValueError as e:
        raise HTTPException(422, str(e))
    qc, g, b, scale = build_qaoa_circuit(q, body.p, mixer, measure=False)
    out = {"summary": circuit_summary(qc), "gates": gate_list(qc), "hamiltonian_scale": scale,
           "num_qubits": q.num_variables, "variables": q.variables,
           "pauli_terms": q.to_ising().to_pauli_terms()[:200],
           "conventions": {"cost": "RZ(2γh_i/scale), RZZ(2γJ_ij/scale)", "mixer": mixer.describe(),
                           "qubit_order": "qubit i = variable i"}}
    if body.gammas is not None and body.betas is not None:
        if len(body.gammas) != body.p or len(body.betas) != body.p:
            raise HTTPException(422, "gammas and betas must each have p entries")
        qc_m, g2, b2, _ = build_qaoa_circuit(q, body.p, mixer, measure=True, scale=scale)
        out["qasm3"] = to_qasm3(bind(qc_m, g2, b2, body.gammas, body.betas))
    if q.num_variables <= 10:
        out["text_diagram"] = draw_text(qc, fold=140)
    return _clean(out)


class StateReq(ModelInput):
    gammas: List[float]
    betas: List[float]
    mixer: str = "x"
    top_k: int = Field(default=32, ge=1, le=256)


@router.post("/simulator/state")
def state(body: StateReq, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, cm, _ = _resolve(body, db, user)
    if q.num_variables > 18:
        raise HTTPException(413, "interactive statevector inspection limited to 18 qubits; submit a QAOA job")
    if len(body.gammas) != len(body.betas) or not body.gammas:
        raise HTTPException(422, "gammas and betas must have equal, non-zero length")
    sim = StatevectorQAOA(q, _mixer_for(body.mixer, cm))
    params = list(body.gammas) + list(body.betas)
    pr = sim.probabilities(params)
    order = np.argsort(-pr)[: body.top_k]
    from ..quantum.bitstrings import index_to_assignment
    rows = []
    for k in order:
        s = index_to_assignment(int(k), q.num_variables)
        row = {"bitstring": s, "probability": float(pr[k]), "energy": float(sim.energies[k])}
        if cm is not None:
            row["feasible"] = cm.evaluate(np.array([int(c) for c in s])).feasible
        rows.append(row)
    return {"execution_kind": "statevector_simulator", "is_real_hardware": False,
            "expected_energy": float(pr @ sim.energies), "e_min": sim.e_min, "e_max": sim.e_max,
            "ground_state_probability": float(pr[np.abs(sim.energies - sim.e_min) < 1e-9].sum()),
            "top_states": rows, "num_qubits": q.num_variables, "bit_order": "variable 0 first"}


class LandscapeReq(ModelInput):
    resolution: int = Field(default=25, ge=5, le=60)
    mixer: str = "x"


@router.post("/qaoa/landscape")
def landscape(body: LandscapeReq, user: User = Depends(viewer), db: Session = Depends(get_db)):
    """⟨H_C⟩ over a p=1 (γ, β) grid — exact statevector."""
    q, cm, _ = _resolve(body, db, user)
    if q.num_variables > 14:
        raise HTTPException(413, "landscape scan limited to 14 qubits")
    sim = StatevectorQAOA(q, _mixer_for(body.mixer, cm))
    gs = np.linspace(0, np.pi, body.resolution)
    bs = np.linspace(0, np.pi / 2, body.resolution)
    Z = [[sim.expectation([g, b]) for g in gs] for b in bs]
    return {"gammas": gs.tolist(), "betas": bs.tolist(), "energies": Z, "e_min": sim.e_min, "e_max": sim.e_max,
            "execution_kind": "statevector_simulator"}


# ------------------------------------------------------------------ providers / hybrid
@router.get("/providers")
def providers(_: User = Depends(viewer)):
    return {"providers": registry.status(),
            "note": "Real hardware requires provider SDKs, credentials on the server, and admin approval per job."}


@router.get("/providers/{name}/backends")
def backends(name: str, _: User = Depends(viewer)):
    try:
        prov = registry.get(name)
    except KeyError as e:
        raise HTTPException(404, str(e))
    try:
        return {"provider": name, "backends": [b.to_dict() for b in prov.list_backends()]}
    except ProviderUnavailable as e:
        return {"provider": name, "backends": [], "unavailable": str(e)}
    except Exception as e:  # noqa: BLE001 — provider API errors are surfaced, not hidden
        return {"provider": name, "backends": [], "error": f"{type(e).__name__}: {e}"}


class RecommendReq(ModelInput):
    p: int = Field(default=1, ge=1, le=10)


@router.post("/hybrid/recommend")
def recommend(body: RecommendReq, user: User = Depends(viewer), db: Session = Depends(get_db)):
    q, _, _ = _resolve(body, db, user)
    return {"num_variables": q.num_variables, "recommendations": recommend_solvers(q, registry.status(), body.p)}


# ------------------------------------------------------------------ industries
@router.get("/industries")
def industries(_: User = Depends(viewer)):
    return [{"key": p.key, "industry": p.industry, "title": p.title, "description": p.description}
            for p in PROBLEMS.values()]


@router.get("/industries/{key}")
def industry(key: str, _: User = Depends(viewer)):
    try:
        return get_problem(key).describe()
    except KeyError as e:
        raise HTTPException(404, str(e))


class FormulateReq(BaseModel):
    data: Dict[str, Any]
    penalty_scale: float = Field(default=1.0, gt=0, le=1000)
    save_as: Optional[str] = Field(default=None, max_length=255)


@router.post("/industries/{key}/formulate")
def formulate(key: str, body: FormulateReq, user: User = Depends(researcher), db: Session = Depends(get_db)):
    try:
        prob = get_problem(key)
        data, cm = prob.compile(body.data, body.penalty_scale)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:  # pydantic ValidationError / ValueError
        raise HTTPException(422, f"invalid input: {e}")
    out = {"summary": cm.summary(), "formulation": prob.formulation, "limitations": prob.limitations,
           **_qubo_view(cm.qubo, cm.qubo.num_variables <= 60)}
    if body.save_as:
        exp = Experiment(owner_id=user.id, name=body.save_as, source=f"industry:{key}", input_data=data.model_dump(),
                         qubo=cm.qubo.to_dict(), summary=cm.summary(), description=prob.title,
                         tags=[prob.industry])
        db.add(exp)
        db.commit()
        out["experiment_id"] = exp.id
    return _clean(out)
