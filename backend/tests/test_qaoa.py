import numpy as np
import pytest

from qopt.core import QUBO, Model, quicksum
from qopt.quantum import (QAOAConfig, StatevectorQAOA, XMixer, XYRingMixer, counts_from_qiskit,
                          run_qaoa)
from qopt.quantum.circuits import bind, build_qaoa_circuit, circuit_summary, gate_list, to_qasm3
from qopt.quantum.qaoa import interp_next, linear_ramp


def rq(n, seed):
    rng = np.random.default_rng(seed)
    return QUBO([f"x{i}" for i in range(n)], {i: float(rng.normal()) for i in range(n)},
                {(i, j): float(rng.normal()) for i in range(n) for j in range(i + 1, n) if rng.random() < .6},
                0.4)


def maxcut_qubo(edges, n):
    # maximise cut  ⇔ minimise  Σ_{(i,j)} (2 x_i x_j - x_i - x_j)
    lin, quad = {}, {}
    for i, j in edges:
        lin[i] = lin.get(i, 0) - 1; lin[j] = lin.get(j, 0) - 1
        quad[(i, j)] = quad.get((i, j), 0) + 2
    return QUBO([f"v{i}" for i in range(n)], lin, quad)


def fidelity(a, b):
    return abs(np.vdot(a, b)) ** 2


# ------------------------------------------------------------ Hamiltonian / statevector
def test_cost_diagonal_matches_qubo_and_pauli_operator():
    from qiskit.quantum_info import SparsePauliOp
    q = rq(5, 0)
    sim = StatevectorQAOA(q)
    I = q.to_ising()
    op = SparsePauliOp.from_list(I.to_pauli_terms() + [("I" * 5, I.offset)])
    diag = np.real(np.diag(op.to_matrix()))
    assert np.allclose(diag, sim.energies)   # same basis ordering as Qiskit


def test_initial_state_and_p0_energy_is_mean():
    q = rq(6, 1)
    sim = StatevectorQAOA(q)
    assert np.allclose(np.abs(sim._init) ** 2, 1 / 64)
    # γ=β=0 → uniform superposition → expectation = mean energy
    assert sim.expectation([0.0, 0.0]) == pytest.approx(sim.energies.mean())


@pytest.mark.parametrize("seed", range(3))
def test_numpy_simulator_matches_qiskit_statevector(seed):
    from qiskit.quantum_info import Statevector
    q = rq(5, seed)
    p = 3
    rng = np.random.default_rng(seed)
    params = rng.uniform(-1, 1, 2 * p)
    sim = StatevectorQAOA(q)
    qc, g, b, scale = build_qaoa_circuit(q, p)
    assert scale == pytest.approx(sim.scale)
    sv = Statevector(bind(qc, g, b, params[:p], params[p:])).data
    assert fidelity(sv, sim.state(params)) == pytest.approx(1.0, abs=1e-10)


def test_xy_mixer_matches_qiskit_and_preserves_one_hot():
    from qiskit.quantum_info import Statevector
    q = rq(5, 7)
    mixer = XYRingMixer([[0, 1, 2]])
    sim = StatevectorQAOA(q, mixer)
    params = np.array([0.3, -0.7, 0.9, 0.2])
    psi = sim.state(params)
    idx = np.arange(32)
    onehot = sum(((idx >> k) & 1) for k in (0, 1, 2)) == 1
    assert np.sum(np.abs(psi[~onehot]) ** 2) < 1e-12        # never leaves feasible subspace
    qc, g, b, _ = build_qaoa_circuit(q, 2, mixer)
    sv = Statevector(bind(qc, g, b, params[:2], params[2:])).data
    assert fidelity(sv, psi) == pytest.approx(1.0, abs=1e-10)


@pytest.mark.parametrize("mixer", [XMixer(), XYRingMixer([[0, 1, 2], [3, 4]])])
def test_adjoint_gradient_matches_finite_difference(mixer):
    q = rq(6, 3)
    sim = StatevectorQAOA(q, mixer)
    x = np.array([0.4, -0.2, 0.7, 0.1, 0.5, -0.3])
    _, g = sim.expectation_and_gradient(x)
    eps = 1e-6
    fd = np.array([(sim.expectation(x + eps * e) - sim.expectation(x - eps * e)) / (2 * eps)
                   for e in np.eye(len(x))])
    assert np.allclose(g, fd, atol=1e-6)


def test_bitstring_ordering_against_qiskit_sampler():
    """A circuit preparing |x⟩ = X on qubit 0 only must decode to assignment '100'."""
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator
    qc = QuantumCircuit(3)
    qc.x(0)
    qc.measure_all()
    backend = AerSimulator()
    counts = backend.run(transpile(qc, backend), shots=10).result().get_counts()
    assert counts_from_qiskit(counts, 3) == {"100": 10}


def test_measured_aer_distribution_matches_statevector():
    from qiskit import transpile
    from qiskit_aer import AerSimulator
    q = rq(4, 5)
    params = [0.5, 0.3]
    sim = StatevectorQAOA(q)
    probs = sim.probabilities(params)
    qc, g, b, _ = build_qaoa_circuit(q, 1, measure=True)
    bound = bind(qc, g, b, params[:1], params[1:])
    be = AerSimulator(seed_simulator=11)
    counts = counts_from_qiskit(be.run(transpile(bound, be), shots=40000).result().get_counts(), 4)
    for k in range(16):
        s = "".join(str((k >> i) & 1) for i in range(4))
        assert counts.get(s, 0) / 40000 == pytest.approx(probs[k], abs=0.012)


# ------------------------------------------------------------ optimisation behaviour
def test_maxcut_triangle_p1_known_value():
    # triangle: max cut = 2. Best p=1 QAOA expectation is known analytically: <C> = 2 * ... ;
    # we check that QAOA beats random guessing (expected cut 1.5) and samples the optimum.
    q = maxcut_qubo([(0, 1), (1, 2), (0, 2)], 3)
    r = run_qaoa(q, QAOAConfig(p=1, restarts=3, seed=0))
    assert r.e_min == -2
    assert r.expected_energy < -1.5 - 0.1
    assert r.best_sample["qubo_energy"] == -2


def test_ring_maxcut_p1_matches_analytic_optimum():
    # For 2-regular graphs (rings, n ≥ 6 so no wrap-around light-cone effects at p=1)
    # the optimal p=1 cut fraction is 3/4 (Farhi et al. 2014): ⟨C⟩ = 0.75 * |E|.
    n = 8
    edges = [(i, (i + 1) % n) for i in range(n)]
    q = maxcut_qubo([(min(a, b), max(a, b)) for a, b in edges], n)
    r = run_qaoa(q, QAOAConfig(p=1, restarts=5, optimizer="L-BFGS-B", seed=1))
    assert -r.expected_energy == pytest.approx(0.75 * n, abs=1e-4)


@pytest.mark.parametrize("opt", ["COBYLA", "Nelder-Mead", "L-BFGS-B", "SPSA", "ADAM", "Powell"])
def test_all_optimizers_improve_on_uniform(opt):
    q = rq(5, 2)
    r = run_qaoa(q, QAOAConfig(p=2, optimizer=opt, maxiter=150, restarts=2, seed=3))
    sim = StatevectorQAOA(q)
    assert r.expected_energy < sim.energies.mean()
    assert r.history and len(r.gammas) == 2 and r.nfev > 0
    assert r.execution_kind == "statevector_simulator" and r.is_real_hardware is False


def test_interp_init_and_helpers():
    assert linear_ramp(2).shape == (4,)
    nxt = interp_next(np.array([0.2, 0.4, 0.6, 0.2]))
    assert nxt.shape == (6,)
    q = rq(5, 4)
    r = run_qaoa(q, QAOAConfig(p=3, init="interp", restarts=1, optimizer="L-BFGS-B"))
    assert len(r.params) == 6


def test_deeper_p_not_assumed_better_but_optimum_is_monotone_with_warm_start():
    """Exact optimum over params is non-decreasing in p (p+1 contains p with γ=β=0),
    but a *given* optimiser run need not be — we check the warm-started INTERP property."""
    q = rq(6, 8)
    e = []
    for p in (1, 2, 3):
        e.append(run_qaoa(q, QAOAConfig(p=p, init="interp", restarts=1, optimizer="L-BFGS-B",
                                       maxiter=300)).expected_energy)
    assert e[1] <= e[0] + 1e-6 and e[2] <= e[1] + 1e-6


def test_constrained_problem_qaoa_reports_feasibility():
    m = Model("assign")
    xs = m.binaries(["a", "b", "c"])
    m.minimize(3 * xs[0] + 1 * xs[1] + 2 * xs[2])
    m.add_one_hot(["a", "b", "c"], "one")
    cm = m.compile()
    rx = run_qaoa(cm.qubo, QAOAConfig(p=2, seed=0), compiled=cm)
    rxy = run_qaoa(cm.qubo, QAOAConfig(p=2, mixer="xy_ring", seed=0), compiled=cm)
    assert rxy.mixer["name"] == "xy_ring"
    # XY mixer never produces infeasible samples
    assert all(s["feasible"] for s in rxy.ranked_samples)
    assert rxy.best_sample["decision_bitstring"] == "010"
    assert rx.best_sample["feasible"]


def test_circuit_exports():
    q = rq(4, 0)
    qc, g, b, _ = build_qaoa_circuit(q, 2, measure=True)
    s = circuit_summary(qc)
    assert s["num_qubits"] == 4 and s["ops"]["h"] == 4 and s["ops"]["rx"] == 8
    gl = gate_list(qc)
    assert gl[0]["gate"] == "h"
    bound = bind(qc, g, b, [0.1, 0.2], [0.3, 0.4])
    assert "OPENQASM 3" in to_qasm3(bound)


def test_qubit_limit_enforced():
    with pytest.raises(ValueError, match="limited"):
        StatevectorQAOA(rq(10, 0), max_qubits=8)
