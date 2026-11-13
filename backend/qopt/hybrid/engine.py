"""Hybrid quantum-classical execution engine with a transparent solver-selection policy."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.model import CompiledModel
from ..core.qubo import QUBO
from ..core.validation import validate_compiled, validate_qubo
from ..providers.base import ApprovalRequired, ProviderUnavailable
from ..providers.registry import ProviderRegistry, registry as default_registry
from ..quantum.circuits import bind, build_qaoa_circuit, circuit_summary
from ..quantum.qaoa import MAX_STATEVECTOR_QUBITS, QAOAConfig, rank_samples, run_qaoa
from ..solvers.classical import SOLVERS

NO_ADVANTAGE_NOTE = ("No quantum advantage is claimed. Small instances that fit a statevector simulator are "
                     "solved exactly by classical methods; QAOA results are reported for research comparison.")


# ---------------------------------------------------------------------------- selection
def recommend_solvers(qubo: QUBO, providers: Optional[List[dict]] = None, p: int = 1) -> List[dict]:
    """Return every candidate with `recommended`, human-readable `reasons` and estimates."""
    n = qubo.num_variables
    nq = len(qubo.quadratic)
    providers = providers if providers is not None else default_registry.status()
    recs: List[dict] = []

    def add(name, kind, ok, reasons, **est):
        recs.append({"solver": name, "execution_kind": kind, "recommended": ok, "reasons": reasons, **est})

    add("exhaustive", "classical", n <= 22,
        [f"n={n} {'≤' if n <= 22 else '>'} 22: " + ("enumerates all 2^n states and proves optimality"
                                                     if n <= 22 else "2^n states is intractable")],
        estimated_states=2 ** min(n, 62))
    add("milp", "classical", nq <= 5000,
        [f"Fortet linearisation adds {nq} auxiliary variables; HiGHS branch-and-bound gives a proven optimum "
         "or a gap when time-limited" + ("" if nq <= 5000 else " — too many quadratic terms for a quick solve")])
    add("simulated_annealing", "classical", True, ["robust general-purpose heuristic; scales to large n"])
    add("tabu_search", "classical", True, ["strong single-flip local search heuristic for dense QUBOs"])
    add("greedy_descent", "classical", True, ["fast baseline; returns a 1-flip local optimum"])
    mem = (2 ** n) * 16 / 1e6 if n <= 40 else math.inf
    add("qaoa_statevector", "statevector_simulator", n <= MAX_STATEVECTOR_QUBITS,
        [f"exact simulation needs {mem:.1f} MB for the statevector" if n <= 40 else "statevector infeasible",
         f"circuit per layer: {len(qubo.to_ising().h)} RZ + {nq} RZZ + {n} RX"],
        two_qubit_gates=p * nq, qubits=n)
    for pr in providers:
        if pr.get("indirect") or pr["name"] in ("local_statevector",):
            continue
        if pr["name"] == "qiskit_aer":
            add("qaoa_aer", "shot_simulator", n <= 28, [f"shot-based Aer simulation of {n} qubits",
                                                      "can use a synthetic noise model"])
        elif pr["technology"] == "annealer":
            add(f"annealer:{pr['name']}", "qpu_annealer", bool(pr.get("available")),
                ["quantum annealing (not QAOA)"] + ([] if pr.get("available") else
                                                    [f"unavailable: missing {pr.get('missing_credentials')} "
                                                     f"or SDK installed={pr.get('sdk_installed')}"]),
                requires_approval=True)
        else:
            reasons = [f"gate-model QPU execution of {n} qubits, {p * nq} two-qubit interactions before routing"]
            if not pr.get("available"):
                reasons.append(f"unavailable: sdk_installed={pr.get('sdk_installed')}, "
                               f"missing credentials {pr.get('missing_credentials')}")
            if p * nq > 200:
                reasons.append("deep circuit: on current noisy hardware results are likely dominated by noise")
            add(f"qaoa_qpu:{pr['name']}", "qpu_gate", bool(pr.get("available")) and p * nq <= 200, reasons,
                requires_approval=True)
    return recs


# ---------------------------------------------------------------------------- execution
@dataclass
class HybridRequest:
    solvers: List[str] = field(default_factory=lambda: ["auto"])
    qaoa: QAOAConfig = field(default_factory=QAOAConfig)
    hardware: Optional[Dict[str, Any]] = None     # {"provider","backend","shots","approval_id"}
    classical_options: Dict[str, dict] = field(default_factory=dict)
    validate: bool = True
    seed: Optional[int] = 7


def _summarise(name: str, kind: str, real: bool, x: Optional[np.ndarray], energy: Optional[float],
               runtime: float, compiled: Optional[CompiledModel], extra: dict) -> dict:
    row = {"solver": name, "execution_kind": kind, "is_real_hardware": real, "runtime_s": runtime,
           "qubo_energy": energy, **extra}
    if x is not None:
        row["bitstring"] = "".join(str(int(b)) for b in x)
        if compiled is not None:
            rep = compiled.evaluate(np.asarray(x))
            row.update({"objective": rep.objective, "feasible": rep.feasible, "violations": rep.violations,
                        "decision_bitstring": rep.bitstring, "assignment": rep.assignment})
    return row


def execute_qaoa_on_provider(qubo: QUBO, gammas, betas, provider_name: str, backend: str, shots: int,
                             approval_id: Optional[str], reg: ProviderRegistry, scale: float,
                             compiled: Optional[CompiledModel] = None, seed: Optional[int] = None) -> dict:
    prov = reg.get(provider_name)
    if provider_name == "aws_braket":
        from ..providers.braket import build_braket_qaoa
        circ = build_braket_qaoa(qubo, gammas, betas, scale)
        jid = prov.submit_circuit(circ, backend, shots, approval_id)
        summary = {}
    else:
        qc, g, b, _ = build_qaoa_circuit(qubo, len(gammas), measure=True, scale=scale)
        bound = bind(qc, g, b, gammas, betas)
        kwargs = {"seed": seed} if provider_name == "qiskit_aer" else {}
        jid = prov.submit_circuit(bound, backend, shots, approval_id, **kwargs)
        summary = circuit_summary(bound)
    res = prov.job_result(jid, qubo.num_variables, wait=True)
    ranked = rank_samples(qubo, res.counts, compiled) if res.counts else []
    return {"job": res.to_dict(), "circuit": summary, "ranked_samples": ranked[:50]}


def run_hybrid(qubo: QUBO, req: HybridRequest, compiled: Optional[CompiledModel] = None,
               reg: Optional[ProviderRegistry] = None) -> dict:
    reg = reg or default_registry
    t0 = time.perf_counter()
    report: Dict[str, Any] = {"num_variables": qubo.num_variables, "qubo_stats": qubo.stats(),
                              "notes": [NO_ADVANTAGE_NOTE], "errors": []}
    # 1. validation
    if req.validate:
        report["qubo_validation"] = validate_qubo(qubo)
        if compiled is not None and compiled.num_decision <= 18 and qubo.num_variables <= 22:
            report["exhaustive_validation"] = validate_compiled(compiled).to_dict()
    # 2. selection
    recs = recommend_solvers(qubo, reg.status(), req.qaoa.p)
    report["solver_selection"] = recs
    chosen = list(req.solvers)
    if "auto" in chosen:
        chosen = [r["solver"] for r in recs if r["recommended"] and r["execution_kind"] in
                  ("classical", "statevector_simulator")]
        report["notes"].append("auto selection runs recommended classical solvers and statevector QAOA; "
                               "hardware runs must be requested explicitly with an approval")
    results: List[dict] = []
    qaoa_params = None
    for name in chosen:
        try:
            if name in SOLVERS:
                opts = dict(req.classical_options.get(name, {}))
                if name in ("simulated_annealing", "tabu_search", "greedy_descent"):
                    opts.setdefault("seed", req.seed)
                r = SOLVERS[name](qubo, **opts)
                results.append(_summarise(name, r.execution_kind, r.is_real_hardware, r.best_x, r.best_energy,
                                          r.runtime_s, compiled, {"proven_optimal": r.optimal,
                                                                  "metadata": r.metadata}))
            elif name == "qaoa_statevector":
                qr = run_qaoa(qubo, req.qaoa, compiled)
                qaoa_params = (qr.gammas, qr.betas, qr.hamiltonian_scale)
                best = qr.best_sample
                x = np.array([int(c) for c in best["bitstring"]]) if best else None
                results.append(_summarise(name, qr.execution_kind, False, x, best["qubo_energy"] if best else None,
                                          qr.runtime_s, compiled, {
                                              "expected_energy": qr.expected_energy,
                                              "approximation_ratio": qr.approximation_ratio,
                                              "ground_state_probability": qr.ground_state_probability,
                                              "p": req.qaoa.p, "shots": req.qaoa.shots, "nfev": qr.nfev,
                                              "gammas": qr.gammas, "betas": qr.betas,
                                              "history": qr.history[-200:], "mixer": qr.mixer}))
            else:
                raise ValueError(f"unknown solver {name!r}")
        except Exception as exc:  # noqa: BLE001 — every failure is reported, never hidden
            report["errors"].append({"solver": name, "error": f"{type(exc).__name__}: {exc}"})
    # 3. hardware / shot-based execution
    if req.hardware:
        hw = req.hardware
        try:
            prov = reg.get(hw["provider"])
            prov.require_available()   # fail fast before spending compute on parameter optimisation
            if prov.technology == "annealer":
                jid = prov.submit_qubo(qubo, hw.get("backend", ""), int(hw.get("shots", 100)), hw.get("approval_id"))
                jr = prov.job_result(jid, qubo.num_variables)
                ranked = rank_samples(qubo, jr.counts, compiled)
                out = {"job": jr.to_dict(), "ranked_samples": ranked[:50]}
            else:
                if qaoa_params is None:
                    if qubo.num_variables > MAX_STATEVECTOR_QUBITS:
                        from ..quantum.qaoa import linear_ramp
                        pr = linear_ramp(req.qaoa.p)
                        ising = qubo.to_ising()
                        cs = [abs(v) for v in list(ising.h.values()) + list(ising.J.values())] or [1.0]
                        qaoa_params = (list(pr[:req.qaoa.p]), list(pr[req.qaoa.p:]), max(cs))
                        report["notes"].append("hardware QAOA used un-optimised linear-ramp parameters "
                                               "(problem too large for statevector pre-optimisation)")
                    else:
                        qr = run_qaoa(qubo, req.qaoa, compiled)
                        qaoa_params = (qr.gammas, qr.betas, qr.hamiltonian_scale)
                report["notes"].append("hardware/shot QAOA parameters were optimised on the exact statevector "
                                       "simulator, then sampled on the target backend")
                out = execute_qaoa_on_provider(qubo, qaoa_params[0], qaoa_params[1], hw["provider"],
                                               hw["backend"], int(hw.get("shots", 2048)), hw.get("approval_id"),
                                               reg, qaoa_params[2], compiled, req.seed)
            best = out["ranked_samples"][0] if out["ranked_samples"] else None
            x = np.array([int(c) for c in best["bitstring"]]) if best else None
            job = out["job"]
            results.append(_summarise(f"{hw['provider']}:{hw['backend']}", job["execution_kind"],
                                      job["is_real_hardware"], x, best["qubo_energy"] if best else None,
                                      0.0, compiled, {"job_id": job["job_id"], "shots": hw.get("shots"),
                                                      "circuit": out.get("circuit"),
                                                      "top_samples": out["ranked_samples"][:10]}))
        except (ApprovalRequired, ProviderUnavailable, KeyError, NotImplementedError, ValueError, ImportError,
                RuntimeError) as exc:
            report["errors"].append({"solver": f"hardware:{hw.get('provider')}", "error": f"{type(exc).__name__}: {exc}"})
    # 4. comparison & ranking
    report["results"] = results
    report["ranking"] = rank_results(results, compiled)
    report["runtime_s"] = time.perf_counter() - t0
    return report


def rank_results(results: List[dict], compiled: Optional[CompiledModel]) -> List[dict]:
    rows = [r for r in results if r.get("qubo_energy") is not None]
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (not r.get("feasible", True), r["qubo_energy"]))
    best_e = rows[0]["qubo_energy"]
    proven = any(r.get("proven_optimal") for r in rows if abs(r["qubo_energy"] - best_e) < 1e-9)
    out = []
    for k, r in enumerate(rows):
        gap = r["qubo_energy"] - best_e
        rel = gap / abs(best_e) if best_e else None
        out.append({"rank": k + 1, "solver": r["solver"], "execution_kind": r["execution_kind"],
                    "is_real_hardware": r["is_real_hardware"], "qubo_energy": r["qubo_energy"],
                    "objective": r.get("objective"), "feasible": r.get("feasible"),
                    "gap_to_best": gap, "relative_gap": rel,
                    "reference": "proven optimum" if proven else "best found (optimality not proven)"})
    return out
