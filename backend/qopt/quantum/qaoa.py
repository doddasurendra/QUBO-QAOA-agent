"""QAOA on an exact statevector simulator with adjoint gradients.

|ψ(γ,β)⟩ = Π_{l=1..p} e^{-iβ_l H_M} e^{-iγ_l H_C} |s⟩,   objective  ⟨ψ|H_C|ψ⟩  (minimised).

H_C is diagonal in the computational basis with eigenvalue E(x(k)) on |k⟩, where
x_i(k) = (k >> i) & 1 — the same function as the QUBO energy (bit 0 ↔ Z=+1).
For numerical conditioning QAOA angles act on the *scaled* Hamiltonian H_C / s with
s = max |Ising coefficient| (reported as ``hamiltonian_scale``); all energies reported in
results are in the original units.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
from scipy.optimize import minimize

from ..core.model import CompiledModel
from ..core.qubo import QUBO
from ..core.validation import enumerate_energies
from .bitstrings import index_to_assignment
from .mixers import Mixer, XMixer, make_mixer

MAX_STATEVECTOR_QUBITS = 22
SCIPY_METHODS = {"COBYLA", "Nelder-Mead", "Powell", "L-BFGS-B", "BFGS", "SLSQP"}
GRADIENT_METHODS = {"L-BFGS-B", "BFGS", "SLSQP"}
OPTIMIZERS = sorted(SCIPY_METHODS | {"SPSA", "ADAM"})


@dataclass
class QAOAConfig:
    p: int = 1
    optimizer: str = "COBYLA"
    maxiter: int = 200
    restarts: int = 3
    init: str = "linear_ramp"     # 'linear_ramp' | 'random' | 'interp' | 'given'
    initial_params: Optional[List[float]] = None  # [γ1..γp, β1..βp]
    mixer: str = "x"               # 'x' | 'xy_ring'
    shots: int = 2048              # final sampling shots
    seed: Optional[int] = 7
    optimization_shots: Optional[int] = None  # None → exact expectation; int → shot-noise estimate
    max_qubits: int = MAX_STATEVECTOR_QUBITS

    def validate(self):
        if not 1 <= self.p <= 50:
            raise ValueError("p must be between 1 and 50")
        if self.optimizer not in OPTIMIZERS:
            raise ValueError(f"optimizer must be one of {OPTIMIZERS}")
        if self.init not in ("linear_ramp", "random", "interp", "given"):
            raise ValueError("init must be linear_ramp, random, interp or given")
        if self.init == "given" and (not self.initial_params or len(self.initial_params) != 2 * self.p):
            raise ValueError("init='given' requires 2p initial_params [γ..., β...]")
        if self.restarts < 1 or self.maxiter < 1 or self.shots < 0:
            raise ValueError("restarts and maxiter must be ≥ 1, shots ≥ 0")


class StatevectorQAOA:
    def __init__(self, qubo: QUBO, mixer: Optional[Mixer] = None, max_qubits: int = MAX_STATEVECTOR_QUBITS):
        self.qubo = qubo
        self.n = qubo.num_variables
        if self.n == 0:
            raise ValueError("QUBO has no variables")
        if self.n > max_qubits:
            raise ValueError(f"statevector QAOA limited to {max_qubits} qubits (problem needs {self.n}); "
                             "use a classical solver, reduce the problem, or a hardware backend")
        self.mixer = mixer or XMixer()
        self.energies = enumerate_energies(qubo, max_vars=max_qubits)  # diag(H_C) incl. offset
        ising = qubo.to_ising()
        coeffs = [abs(v) for v in ising.h.values()] + [abs(v) for v in ising.J.values()]
        self.scale = max(coeffs) if coeffs else 1.0
        # constant shift is a global phase; scaled diagonal used for phases
        self.phase_diag = (self.energies - ising.offset) / self.scale
        self._components = self.mixer.components(self.n)
        self._init = self.mixer.initial_state(self.n)
        self.e_min = float(self.energies.min())
        self.e_max = float(self.energies.max())
        self.nfev = 0

    # ---------------------------------------------------------------- simulation
    def state(self, params: Sequence[float]) -> np.ndarray:
        p = len(params) // 2
        g, b = params[:p], params[p:]
        psi = self._init.copy()
        for l in range(p):
            psi *= np.exp(-1j * g[l] * self.phase_diag)
            for u, _ in self._components:
                psi = u(psi, b[l])
        return psi

    def probabilities(self, params) -> np.ndarray:
        pr = np.abs(self.state(params)) ** 2
        return pr / pr.sum()

    def expectation(self, params) -> float:
        self.nfev += 1
        return float(self.probabilities(params) @ self.energies)

    def expectation_and_gradient(self, params):
        """Adjoint differentiation: exact ∂⟨H⟩/∂θ in O(p · components) state operations."""
        self.nfev += 1
        p = len(params) // 2
        g, b = np.asarray(params[:p], float), np.asarray(params[p:], float)
        psi = self._init.copy()
        for l in range(p):
            psi *= np.exp(-1j * g[l] * self.phase_diag)
            for u, _ in self._components:
                psi = u(psi, b[l])
        E = float(np.real(np.vdot(psi, self.energies * psi)))
        lam = self.energies * psi
        grad_g, grad_b = np.zeros(p), np.zeros(p)
        phi = psi
        for l in reversed(range(p)):
            for u, gen in reversed(self._components):
                # ∂/∂β of e^{-iβA}: contribution 2 Re ⟨λ| (-iA) |φ⟩
                grad_b[l] += 2 * np.real(np.vdot(lam, -1j * gen(phi)))
                phi = u(phi, -b[l]); lam = u(lam, -b[l])
            grad_g[l] = 2 * np.real(np.vdot(lam, -1j * self.phase_diag * phi))
            ph = np.exp(1j * g[l] * self.phase_diag)
            phi = phi * ph; lam = lam * ph
        return E, np.concatenate([grad_g, grad_b])

    def sample(self, params, shots: int, rng: np.random.Generator) -> Dict[str, int]:
        pr = self.probabilities(params)
        counts = rng.multinomial(shots, pr)
        nz = np.flatnonzero(counts)
        return {index_to_assignment(int(k), self.n): int(counts[k]) for k in nz}

    def shot_expectation(self, params, shots: int, rng) -> float:
        self.nfev += 1
        pr = self.probabilities(params)
        counts = rng.multinomial(shots, pr)
        return float(counts @ self.energies / shots)


# ---------------------------------------------------------------------- initialisation
def linear_ramp(p: int, delta: float = 0.75) -> np.ndarray:
    t = (np.arange(p) + 0.5) / p
    return np.concatenate([delta * t, delta * (1 - t)])


def interp_next(params: np.ndarray) -> np.ndarray:
    """INTERP heuristic (Zhou et al., PRX 10, 021067): p → p+1 by linear interpolation."""
    p = len(params) // 2
    out = []
    for arr in (params[:p], params[p:]):
        a = np.concatenate([[0.0], arr, [0.0]])
        new = [((i) / p) * a[i] + ((p - i) / p) * a[i + 1] for i in range(p + 1)]
        out.append(np.array(new))
    return np.concatenate(out)


# ---------------------------------------------------------------------- optimisers
def spsa(fun: Callable, x0: np.ndarray, maxiter: int, rng, a: float = 0.2, c: float = 0.1,
         alpha: float = 0.602, gamma: float = 0.101, callback=None):
    """Simultaneous Perturbation Stochastic Approximation (Spall 1998) with standard gains."""
    x = x0.copy()
    A = 0.1 * maxiter
    best_x, best_f = x.copy(), fun(x)
    for k in range(maxiter):
        ak = a / (k + 1 + A) ** alpha
        ck = c / (k + 1) ** gamma
        delta = rng.choice([-1.0, 1.0], size=x.shape)
        gk = (fun(x + ck * delta) - fun(x - ck * delta)) / (2 * ck) * delta
        x = x - ak * gk
        f = fun(x)
        if f < best_f:
            best_f, best_x = f, x.copy()
        if callback:
            callback(x, f)
    return best_x, best_f


def adam(fun_grad: Callable, x0: np.ndarray, maxiter: int, lr: float = 0.05, callback=None, tol=1e-8):
    x = x0.copy()
    m = np.zeros_like(x); v = np.zeros_like(x)
    b1, b2, eps = 0.9, 0.999, 1e-8
    best_x, best_f = x.copy(), np.inf
    for t in range(1, maxiter + 1):
        f, g = fun_grad(x)
        if f < best_f:
            best_f, best_x = f, x.copy()
        if callback:
            callback(x, f)
        if np.linalg.norm(g) < tol:
            break
        m = b1 * m + (1 - b1) * g
        v = b2 * v + (1 - b2) * g * g
        x = x - lr * (m / (1 - b1 ** t)) / (np.sqrt(v / (1 - b2 ** t)) + eps)
    return best_x, best_f


# ---------------------------------------------------------------------- driver
@dataclass
class QAOAResult:
    params: List[float]
    gammas: List[float]
    betas: List[float]
    expected_energy: float
    e_min: float
    e_max: float
    approximation_ratio: Optional[float]
    ground_state_probability: float
    counts: Dict[str, int]
    best_sample: Optional[dict]
    ranked_samples: List[dict]
    history: List[float]
    restarts: List[dict]
    nfev: int
    runtime_s: float
    config: dict
    hamiltonian_scale: float
    mixer: dict
    num_qubits: int
    execution_kind: str = "statevector_simulator"
    is_real_hardware: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["bit_order"] = "assignment strings list variable 0 first (NOT Qiskit big-endian)"
        d["angle_convention"] = ("gammas act on H_C / hamiltonian_scale; "
                                 "U_C = exp(-i γ H_C/scale), U_M = exp(-i β H_M)")
        return d


def run_qaoa(qubo: QUBO, config: QAOAConfig, compiled: Optional[CompiledModel] = None,
             mixer: Optional[Mixer] = None, progress: Optional[Callable[[dict], None]] = None) -> QAOAResult:
    config.validate()
    t0 = time.perf_counter()
    rng = np.random.default_rng(config.seed)
    warnings: List[str] = []
    if mixer is None:
        groups = compiled.one_hot_groups() if compiled is not None and config.mixer != "x" else None
        mixer = make_mixer(config.mixer, groups)
    sim = StatevectorQAOA(qubo, mixer, config.max_qubits)
    p_target = config.p
    use_grad = config.optimizer in GRADIENT_METHODS or config.optimizer == "ADAM"
    if use_grad and config.optimization_shots:
        warnings.append("gradient optimisers use exact adjoint gradients; optimization_shots ignored")

    def objective(x):
        if config.optimization_shots and not use_grad:
            return sim.shot_expectation(x, config.optimization_shots, rng)
        return sim.expectation(x)

    def optimise(x0: np.ndarray, hist: List[float]):
        cb = lambda x, f=None: hist.append(float(sim.expectation(x) if f is None else f))
        m = config.optimizer
        if m == "SPSA":
            return spsa(objective, x0, config.maxiter, rng, callback=lambda x, f: hist.append(f))
        if m == "ADAM":
            return adam(sim.expectation_and_gradient, x0, config.maxiter, callback=lambda x, f: hist.append(f))
        kwargs: Dict[str, Any] = {"method": m, "options": {"maxiter": config.maxiter}}
        if m in GRADIENT_METHODS:
            kwargs["jac"] = True
            res = minimize(lambda x: sim.expectation_and_gradient(x), x0, **kwargs,
                           callback=lambda xk: hist.append(float(sim.expectation(xk))))
        else:
            wrapped = lambda x: (lambda f: (hist.append(f), f)[1])(objective(x))
            res = minimize(wrapped, x0, **kwargs)
        return res.x, float(res.fun)

    restarts_out: List[dict] = []
    best = None
    for r in range(config.restarts):
        hist: List[float] = []
        if config.init == "given" and r == 0:
            x0 = np.array(config.initial_params, float)
            x, f = optimise(x0, hist)
        elif config.init == "interp":
            x = linear_ramp(1) if r == 0 else rng.uniform(0, np.pi, 2)
            x, f = optimise(x, hist)
            for _ in range(1, p_target):
                x, f = optimise(interp_next(x), hist)
        elif config.init == "linear_ramp" and r == 0:
            x, f = optimise(linear_ramp(p_target), hist)
        else:
            x0 = np.concatenate([rng.uniform(0, np.pi, p_target), rng.uniform(0, np.pi / 2, p_target)])
            x, f = optimise(x0, hist)
        f_exact = sim.expectation(x)
        restarts_out.append({"restart": r, "expected_energy": f_exact, "params": list(map(float, x)),
                             "evaluations": len(hist), "history": hist})
        if progress:
            progress({"restart": r, "expected_energy": f_exact})
        if best is None or f_exact < best[1]:
            best = (x, f_exact, hist)
    x, f, hist = best
    probs = sim.probabilities(x)
    gs = float(probs[np.abs(sim.energies - sim.e_min) <= 1e-9 * max(1.0, abs(sim.e_min))].sum())
    counts = sim.sample(x, config.shots, rng) if config.shots else {}
    ranked = rank_samples(qubo, counts, compiled)
    span = sim.e_max - sim.e_min
    ratio = (sim.e_max - f) / span if span > 0 else None
    p = len(x) // 2
    return QAOAResult(
        params=list(map(float, x)), gammas=list(map(float, x[:p])), betas=list(map(float, x[p:])),
        expected_energy=float(f), e_min=sim.e_min, e_max=sim.e_max, approximation_ratio=ratio,
        ground_state_probability=gs, counts=counts, best_sample=ranked[0] if ranked else None,
        ranked_samples=ranked[:50], history=hist, restarts=restarts_out, nfev=sim.nfev,
        runtime_s=time.perf_counter() - t0, config=dict(config.__dict__),
        hamiltonian_scale=sim.scale, mixer=mixer.describe(), num_qubits=sim.n, warnings=warnings)


def rank_samples(qubo: QUBO, counts: Dict[str, int], compiled: Optional[CompiledModel] = None) -> List[dict]:
    """Rank measured assignments: feasible first, then by QUBO energy, then by frequency."""
    total = sum(counts.values()) or 1
    rows = []
    for s, c in counts.items():
        x = np.array([int(ch) for ch in s])
        row = {"bitstring": s, "count": c, "frequency": c / total, "qubo_energy": qubo.energy(x)}
        if compiled is not None:
            rep = compiled.evaluate(x)
            row.update({"feasible": rep.feasible, "objective": rep.objective,
                        "violations": rep.violations, "decision_bitstring": rep.bitstring})
        rows.append(row)
    rows.sort(key=lambda r: (not r.get("feasible", True), r["qubo_energy"], -r["count"]))
    return rows
