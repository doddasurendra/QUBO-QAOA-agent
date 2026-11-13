"""Classical QUBO solvers: exhaustive, simulated annealing, tabu, greedy, MILP (HiGHS)."""
from __future__ import annotations

from typing import Optional

import numpy as np
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, milp

from ..core.qubo import QUBO, all_assignments
from ..core.validation import CHUNK
from .base import SolverResult, Timer, aggregate, dense_parts

KIND = "classical"


def exhaustive(qubo: QUBO, max_vars: int = 24, keep: int = 16) -> SolverResult:
    """Exact minimisation by enumerating all 2^n states (chunked, vectorised)."""
    n = qubo.num_variables
    if n > max_vars:
        raise ValueError(f"exhaustive search limited to {max_vars} variables (got {n})")
    with Timer() as t:
        best_E, best_k = np.inf, 0
        top_E = np.array([]); top_k = np.array([], dtype=np.int64)
        for start in range(0, 1 << n, CHUNK):
            stop = min(start + CHUNK, 1 << n)
            E = qubo.energies(all_assignments(n, start, stop))
            k = int(np.argmin(E))
            if E[k] < best_E:
                best_E, best_k = float(E[k]), start + k
            sel = np.argsort(E, kind="stable")[:keep]
            top_E = np.concatenate([top_E, E[sel]]); top_k = np.concatenate([top_k, sel + start])
            o = np.argsort(top_E, kind="stable")[:keep]
            top_E, top_k = top_E[o], top_k[o]
    X = np.vstack([all_assignments(n, int(k), int(k) + 1) for k in top_k]) if len(top_k) else np.zeros((1, n))
    samples = aggregate(qubo, X)
    best_x = all_assignments(n, best_k, best_k + 1)[0].astype(int)
    return SolverResult("exhaustive", KIND, False, best_x, best_E, samples, t.elapsed, True,
                        {"states_evaluated": 1 << n})


def simulated_annealing(qubo: QUBO, num_reads: int = 20, num_sweeps: int = 1000,
                        beta_range: Optional[tuple] = None, seed: Optional[int] = None) -> SolverResult:
    """Single-spin-flip Metropolis annealing with a geometric β schedule.

    Default β range follows the common heuristic: β_min so the largest single-flip energy
    change is accepted with prob ~0.5, β_max so the smallest non-zero change is accepted
    with prob ~0.01."""
    n = qubo.num_variables
    rng = np.random.default_rng(seed)
    a, W = dense_parts(qubo)
    with Timer() as t:
        if n == 0:
            return SolverResult("simulated_annealing", KIND, False, np.zeros(0, int), qubo.offset, [], 0.0)
        max_delta = np.abs(a) + np.abs(W).sum(axis=1)
        nz = np.concatenate([np.abs(a[a != 0]), np.abs(W[W != 0])])
        if beta_range is None:
            hi = float(max_delta.max()) or 1.0
            lo = float(nz.min()) if nz.size else 1.0
            beta_range = (np.log(2) / hi, np.log(100) / lo)
        betas = np.geomspace(beta_range[0], beta_range[1], num_sweeps)
        # all reads evolve in parallel (independent Markov chains, vectorised over reads)
        R = num_reads
        x = rng.integers(0, 2, (R, n)).astype(float)
        field = a[None, :] + x @ W        # ∂E/∂x_i excluding self-term (W_ii = 0)
        e = qubo.energies(x)
        best_x, best_e = x.copy(), e.copy()
        for beta in betas:
            for i in rng.permutation(n):
                dx = 1 - 2 * x[:, i]
                d = dx * field[:, i]            # energy change of flipping bit i
                acc = (d <= 0) | (rng.random(R) < np.exp(-beta * np.maximum(d, 0)))
                if not acc.any():
                    continue
                step = np.where(acc, dx, 0.0)
                x[:, i] += step
                field += step[:, None] * W[i][None, :]
                e += np.where(acc, d, 0.0)
            better = e < best_e - 1e-12
            if better.any():
                best_e[better] = e[better]
                best_x[better] = x[better]
        X = best_x.astype(np.int8)
    samples = aggregate(qubo, X)
    return SolverResult("simulated_annealing", KIND, False, samples[0].x, samples[0].energy, samples,
                        t.elapsed, None, {"num_reads": num_reads, "num_sweeps": num_sweeps,
                                          "beta_range": list(map(float, beta_range)), "seed": seed})


def tabu_search(qubo: QUBO, max_iter: int = 2000, tenure: Optional[int] = None,
                restarts: int = 5, seed: Optional[int] = None) -> SolverResult:
    """Single-flip tabu search with aspiration (best-improving non-tabu move each step)."""
    n = qubo.num_variables
    rng = np.random.default_rng(seed)
    a, W = dense_parts(qubo)
    tenure = tenure or max(1, min(20, n // 4 + 1))
    with Timer() as t:
        X = []
        for _ in range(restarts):
            x = rng.integers(0, 2, n).astype(float)
            field = a + W @ x
            e = qubo.energy(x)
            best_x, best_e = x.copy(), e
            tabu = np.zeros(n, dtype=int)
            for it in range(max_iter):
                deltas = (1 - 2 * x) * field
                allowed = (tabu <= it) | (e + deltas < best_e - 1e-12)
                if not allowed.any():
                    allowed[:] = True
                cand = np.where(allowed, deltas, np.inf)
                i = int(np.argmin(cand))
                dx = 1 - 2 * x[i]
                x[i] += dx
                field += W[:, i] * dx
                e += deltas[i]
                tabu[i] = it + tenure
                if e < best_e - 1e-12:
                    best_e, best_x = e, x.copy()
            X.append(best_x)
    samples = aggregate(qubo, np.array(X))
    return SolverResult("tabu_search", KIND, False, samples[0].x, samples[0].energy, samples, t.elapsed,
                        None, {"max_iter": max_iter, "tenure": tenure, "restarts": restarts, "seed": seed})


def greedy_descent(qubo: QUBO, restarts: int = 10, seed: Optional[int] = None) -> SolverResult:
    """Steepest-descent 1-flip local search from the all-zero state and random starts."""
    n = qubo.num_variables
    rng = np.random.default_rng(seed)
    a, W = dense_parts(qubo)
    with Timer() as t:
        X = []
        starts = [np.zeros(n)] + [rng.integers(0, 2, n).astype(float) for _ in range(restarts - 1)]
        for x in starts:
            field = a + W @ x
            while True:
                deltas = (1 - 2 * x) * field
                i = int(np.argmin(deltas)) if n else 0
                if n == 0 or deltas[i] >= -1e-12:
                    break
                dx = 1 - 2 * x[i]
                x[i] += dx
                field += W[:, i] * dx
            X.append(x.copy())
    samples = aggregate(qubo, np.array(X).reshape(len(X), n))
    return SolverResult("greedy_descent", KIND, False, samples[0].x, samples[0].energy, samples,
                        t.elapsed, None, {"restarts": restarts, "seed": seed, "local_optimum": "1-flip"})


def milp_solve(qubo: QUBO, time_limit: float = 60.0) -> SolverResult:
    """Exact MILP via SciPy/HiGHS with the standard (sign-aware) Fortet linearisation.

    y_ij replaces x_i x_j. For b_ij > 0 minimisation pushes y down, so only
    y ≥ x_i + x_j − 1, y ≥ 0 are needed; for b_ij < 0 only y ≤ x_i, y ≤ x_j."""
    n = qubo.num_variables
    pairs = list(qubo.quadratic.items())
    m = len(pairs)
    with Timer() as t:
        c = np.concatenate([qubo.linear_vector(), np.array([b for _, b in pairs])])
        rows, cols, vals, lb, ub = [], [], [], [], []
        r = 0
        for k, ((i, j), b) in enumerate(pairs):
            y = n + k
            if b > 0:   # x_i + x_j - y ≤ 1
                rows += [r, r, r]; cols += [i, j, y]; vals += [1, 1, -1]; lb.append(-np.inf); ub.append(1); r += 1
            else:       # y - x_i ≤ 0 ; y - x_j ≤ 0
                rows += [r, r]; cols += [y, i]; vals += [1, -1]; lb.append(-np.inf); ub.append(0); r += 1
                rows += [r, r]; cols += [y, j]; vals += [1, -1]; lb.append(-np.inf); ub.append(0); r += 1
        constraints = []
        if r:
            A = sparse.csr_matrix((vals, (rows, cols)), shape=(r, n + m))
            constraints = [LinearConstraint(A, lb, ub)]
        integrality = np.concatenate([np.ones(n), np.zeros(m)])
        res = milp(c, constraints=constraints, integrality=integrality, bounds=Bounds(0, 1),
                   options={"time_limit": time_limit, "disp": False})
    if res.x is None:
        raise RuntimeError(f"MILP solver failed: {res.message}")
    x = np.round(res.x[:n]).astype(int)
    e = qubo.energy(x)
    proven = bool(res.status == 0)
    samples = aggregate(qubo, x[None, :])
    return SolverResult("milp_highs", KIND, False, x, e, samples, t.elapsed, proven,
                        {"status": int(res.status), "message": str(res.message),
                         "mip_gap": getattr(res, "mip_gap", None), "aux_variables": m,
                         "linear_constraints": r, "time_limit_s": time_limit})


SOLVERS = {
    "exhaustive": exhaustive,
    "simulated_annealing": simulated_annealing,
    "tabu_search": tabu_search,
    "greedy_descent": greedy_descent,
    "milp": milp_solve,
}


def solve(qubo: QUBO, solver: str, **kwargs) -> SolverResult:
    if solver not in SOLVERS:
        raise ValueError(f"unknown classical solver {solver!r}; choose from {sorted(SOLVERS)}")
    return SOLVERS[solver](qubo, **kwargs)
