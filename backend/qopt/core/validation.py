"""Independent mathematical validation by exhaustive enumeration.

Everything here recomputes quantities from first principles (direct evaluation of the
user's objective and constraints, independent Ising evaluation) rather than trusting the
compiled QUBO, so it can detect formulation errors.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from .model import CompiledModel
from .qubo import QUBO, all_assignments, bits_to_spins

MAX_EXHAUSTIVE = 24
CHUNK = 1 << 16


def enumerate_energies(qubo: QUBO, max_vars: int = MAX_EXHAUSTIVE) -> np.ndarray:
    n = qubo.num_variables
    if n > max_vars:
        raise ValueError(f"exhaustive enumeration limited to {max_vars} variables (got {n})")
    out = np.empty(1 << n)
    for start in range(0, 1 << n, CHUNK):
        stop = min(start + CHUNK, 1 << n)
        out[start:stop] = qubo.energies(all_assignments(n, start, stop))
    return out


def check_qubo_ising_equivalence(qubo: QUBO, max_vars: int = 16, tol: float = 1e-8) -> dict:
    """E_qubo(x) == H_ising(1 - 2x) for every x (exhaustively for n ≤ max_vars, else
    on 2000 random samples)."""
    ising = qubo.to_ising()
    n = qubo.num_variables
    if n <= max_vars:
        X = all_assignments(n)
        mode = "exhaustive"
    else:
        X = np.random.default_rng(0).integers(0, 2, size=(2000, n)).astype(np.int8)
        mode = "random_sample_2000"
    eq = qubo.energies(X)
    ei = ising.energies(bits_to_spins(X))
    err = float(np.max(np.abs(eq - ei))) if len(X) else 0.0
    back = ising.to_qubo()
    err_back = float(np.max(np.abs(back.energies(X) - eq))) if len(X) else 0.0
    return {"mode": mode, "checked": int(len(X)), "max_abs_error": err,
            "roundtrip_max_abs_error": err_back, "passed": err <= tol and err_back <= tol}


@dataclass
class ExhaustiveReport:
    passed: bool
    checks: Dict[str, dict]
    num_states: int
    qubo_min_energy: float
    qubo_argmin: List[str]
    best_feasible_objective: Optional[float]
    best_feasible: List[str]
    num_feasible: int
    issues: List[str]

    def to_dict(self) -> dict:
        return self.__dict__


def validate_compiled(cm: CompiledModel, tol: float = 1e-7) -> ExhaustiveReport:
    """Full validation of a compiled constrained model on the decision space.

    1. For every decision assignment, compute the true objective and feasibility directly
       from the Model's expressions.
    2. Minimise the QUBO over slack bits (by exhaustive enumeration of the full QUBO when
       small enough, otherwise via the exact slack completion) and verify:
       a. feasible assignments: QUBO energy == ±objective (penalty exactly zero)
       b. infeasible assignments: QUBO energy > best feasible energy (penalty dominates)
       c. QUBO global minimum is a feasible optimum of the original problem.
    3. QUBO ↔ Ising equivalence.
    """
    m = cm.model
    nd = cm.num_decision
    if nd > MAX_EXHAUSTIVE:
        raise ValueError(f"exhaustive validation limited to {MAX_EXHAUSTIVE} decision variables")
    sign = 1.0 if m.sense == "min" else -1.0
    issues: List[str] = []
    D = all_assignments(nd)
    names = cm.decision_variables

    # (1) ground truth straight from the model expressions, vectorised
    def eval_expr(e) -> np.ndarray:
        idx = {v: i for i, v in enumerate(names)}
        val = np.full(len(D), e.const)
        for v, c in e.lin.items():
            val += c * D[:, idx[v]]
        for (u, v), c in e.quad.items():
            val += c * D[:, idx[u]] * D[:, idx[v]]
        return val

    obj = eval_expr(m.objective)
    feasible = np.ones(len(D), dtype=bool)
    for c in m.constraints:
        lv = eval_expr(c.lhs)
        if c.sense == "==":
            feasible &= np.abs(lv) <= 1e-9
        elif c.sense == "<=":
            feasible &= lv <= 1e-9
        else:
            feasible &= lv >= -1e-9

    # (2) QUBO energy minimised over slack bits
    ns = len(cm.slack_variables)
    if ns == 0:
        E = cm.qubo.energies(D)
        full_min_mode = "no_slack"
    elif nd + ns <= 20:
        Eall = enumerate_energies(cm.qubo)
        E = Eall.reshape(1 << ns, 1 << nd).min(axis=0)  # decision bits are low-order
        full_min_mode = "exhaustive_over_slack"
    else:
        E = cm.qubo.energies(_vectorised_slack_completion(cm, D, eval_expr))
        full_min_mode = "analytic_slack_completion"

    checks: Dict[str, dict] = {}
    if feasible.any():
        err = float(np.max(np.abs(E[feasible] - sign * obj[feasible])))
        checks["feasible_energy_equals_objective"] = {"max_abs_error": err, "passed": err <= tol}
        best_feas_E = float(E[feasible].min())
        if (~feasible).any():
            min_infeas = float(E[~feasible].min())
            ok = min_infeas > best_feas_E + tol
            checks["penalty_dominates"] = {"min_infeasible_energy": min_infeas,
                                           "best_feasible_energy": best_feas_E, "passed": ok}
            if not ok:
                issues.append("an infeasible assignment has energy ≤ the best feasible one: "
                              "penalty weights are too small")
        bf_obj = sign * best_feas_E
        best_feasible = ["".join(map(str, D[k])) for k in np.flatnonzero(
            feasible & (np.abs(E - best_feas_E) <= tol))]
    else:
        issues.append("no feasible assignment exists for the original constraints")
        bf_obj, best_feasible = None, []
    gmin = float(E.min())
    argmin = ["".join(map(str, D[k])) for k in np.flatnonzero(np.abs(E - gmin) <= tol)]
    if feasible.any():
        ok = all(feasible[int(s[::-1], 2)] for s in argmin)
        checks["qubo_minimum_is_feasible_optimum"] = {"passed": ok}
        if not ok:
            issues.append("QUBO global minimum is not feasible for the original problem")
    eqv = check_qubo_ising_equivalence(cm.qubo)
    checks["qubo_ising_equivalence"] = eqv
    if not eqv["passed"]:
        issues.append("QUBO ↔ Ising conversion mismatch")
    checks["slack_minimisation"] = {"mode": full_min_mode, "passed": True}
    passed = all(c.get("passed", True) for c in checks.values()) and not issues
    return ExhaustiveReport(passed, checks, int(len(D)), gmin, argmin, bf_obj, best_feasible,
                            int(feasible.sum()), issues)


def _vectorised_slack_completion(cm: CompiledModel, D: np.ndarray, eval_expr) -> np.ndarray:
    """Same result as CompiledModel.best_slack_completion for every row of D, computed in bulk.

    Each slack block appears only in its own constraint's penalty, so its optimal value is
    clamp(−lhs, 0, max_slack); the greedy decomposition over weights sorted descending is exact
    because the weights are 1, 2, 4, …, remainder."""
    full = np.zeros((len(D), cm.qubo.num_variables), dtype=np.int8)
    full[:, : cm.num_decision] = D
    idx = cm.qubo.index
    for info in cm.slacks:
        c = next(cc for cc in cm.model.constraints if cc.label == info.constraint)
        lhs = c.lhs if c.sense == "<=" else -c.lhs
        if c.resolution is not None and not lhs.is_integral():
            lhs = lhs * (1.0 / c.resolution)
        target = np.rint(np.clip(-eval_expr(lhs), 0.0, info.max_slack)).astype(np.int64)
        for n, w in sorted(zip(info.variables, info.weights), key=lambda t: -t[1]):
            bit = (target >= int(w)).astype(np.int8)
            target -= int(w) * bit
            full[:, idx[n]] = bit
    return full


def validate_qubo(qubo: QUBO) -> dict:
    """Structural validation for raw QUBOs (no constraint information)."""
    issues = []
    vals = list(qubo.linear.values()) + list(qubo.quadratic.values()) + [qubo.offset]
    if not np.all(np.isfinite(vals)):
        issues.append("non-finite coefficient")
    nz = [abs(v) for v in vals[:-1] if v != 0]
    dyn = (max(nz) / min(nz)) if nz else 1.0
    if dyn > 1e6:
        issues.append(f"coefficient dynamic range {dyn:.2e} is very large; precision on "
                      "hardware and annealers will be poor")
    isolated = [qubo.variables[i] for i in range(qubo.num_variables)
                if i not in qubo.linear and not any(i in k for k in qubo.quadratic)]
    report = {"stats": qubo.stats(), "dynamic_range": dyn, "unused_variables": isolated,
              "issues": issues, "passed": not [i for i in issues if "non-finite" in i]}
    if qubo.num_variables <= 16:
        report["ising_equivalence"] = check_qubo_ising_equivalence(qubo)
        report["passed"] &= report["ising_equivalence"]["passed"]
    return report
