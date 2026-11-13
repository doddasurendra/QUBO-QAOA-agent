import itertools
import json

import numpy as np
import pytest

from qopt.core import (QUBO, Expr, Ising, Model, all_assignments, bits_to_spins,
                       check_qubo_ising_equivalence, enumerate_energies, quicksum, reduce_qubo,
                       spins_to_bits, validate_compiled, validate_qubo)


def random_qubo(n, seed=0, density=0.6):
    rng = np.random.default_rng(seed)
    lin = {i: float(rng.normal()) for i in range(n)}
    quad = {(i, j): float(rng.normal()) for i in range(n) for j in range(i + 1, n)
            if rng.random() < density}
    return QUBO([f"x{i}" for i in range(n)], lin, quad, float(rng.normal()))


def brute(q):
    best = None
    for bits in itertools.product([0, 1], repeat=q.num_variables):
        e = q.energy(np.array(bits))
        if best is None or e < best[0]:
            best = (e, bits)
    return best


# ---------------------------------------------------------------- expressions
def test_binary_idempotence_and_degree_limit():
    x, y = Expr.var("x"), Expr.var("y")
    e = x * x
    assert e.lin == {"x": 1.0} and not e.quad
    with pytest.raises(ValueError):
        (x * y) * x
    sq = (x + y - 1) ** 2  # = x + y + 2xy - 2x - 2y + 1 = -x - y + 2xy + 1
    assert sq.const == 1 and sq.lin == {"x": -1.0, "y": -1.0} and sq.quad == {("x", "y"): 2.0}


def test_expression_evaluation_matches_direct():
    x, y, z = (Expr.var(v) for v in "xyz")
    e = 3 * x - 2 * y * z + 0.5 + z
    for bits in itertools.product([0, 1], repeat=3):
        a = dict(zip("xyz", bits))
        assert e.evaluate(a) == pytest.approx(3 * a["x"] - 2 * a["y"] * a["z"] + 0.5 + a["z"])


# ---------------------------------------------------------------- matrices
def test_matrix_conventions_agree():
    q = random_qubo(7, seed=1)
    U, S = q.to_matrix("upper"), q.to_matrix("symmetric")
    assert np.allclose(np.tril(U, -1), 0)
    assert np.allclose(S, S.T)
    for x in all_assignments(7):
        e = q.energy(x)
        assert x @ U @ x + q.offset == pytest.approx(e)
        assert x @ S @ x + q.offset == pytest.approx(e)


def test_from_matrix_accepts_any_square_form():
    rng = np.random.default_rng(3)
    M = rng.normal(size=(5, 5))
    q = QUBO.from_matrix(M, offset=1.5)
    for x in all_assignments(5):
        assert q.energy(x) == pytest.approx(x @ M @ x + 1.5)
    with pytest.raises(ValueError):
        QUBO.from_matrix(M, convention="upper")
    with pytest.raises(ValueError):
        QUBO.from_matrix(M, convention="symmetric")


def test_vectorised_energies_match_scalar():
    q = random_qubo(9, seed=2)
    X = all_assignments(9)
    E = q.energies(X)
    for k in range(0, len(X), 37):
        assert E[k] == pytest.approx(q.energy(X[k]))


def test_rejects_non_binary_assignment():
    q = random_qubo(3)
    with pytest.raises(ValueError):
        q.energy([0, 2, 1])


def test_serialization_roundtrip_and_sparse():
    q = random_qubo(6, seed=4)
    q2 = QUBO.from_json(json.dumps(json.loads(q.to_json())))
    assert np.allclose(q.to_matrix(), q2.to_matrix()) and q.offset == q2.offset
    assert np.allclose(q.to_sparse().toarray(), q.to_matrix())
    assert np.allclose(q.to_sparse("symmetric").toarray(), q.to_matrix("symmetric"))


# ---------------------------------------------------------------- ising
@pytest.mark.parametrize("seed", range(5))
def test_qubo_ising_equivalence_exhaustive(seed):
    q = random_qubo(8, seed=seed)
    rep = check_qubo_ising_equivalence(q)
    assert rep["passed"] and rep["mode"] == "exhaustive" and rep["checked"] == 256


def test_ising_hand_computed_coefficients():
    # E = 2 x0 - 3 x0 x1 + 1
    q = QUBO(["a", "b"], {0: 2.0}, {(0, 1): -3.0}, 1.0)
    I = q.to_ising()
    # h0 = -2/2 - (-3)/4 = -0.25 ; h1 = 0.75 ; J = -0.75 ; c = 1 + 1 - 0.75 = 1.25
    assert I.h[0] == pytest.approx(-0.25) and I.h[1] == pytest.approx(0.75)
    assert I.J[(0, 1)] == pytest.approx(-0.75) and I.offset == pytest.approx(1.25)
    # bit 0 ↔ spin +1
    assert list(bits_to_spins([0, 1])) == [1, -1]
    assert list(spins_to_bits([1, -1])) == [0, 1]


def test_ising_to_qubo_roundtrip_from_random_ising():
    rng = np.random.default_rng(9)
    I = Ising([f"s{i}" for i in range(5)], {i: float(rng.normal()) for i in range(5)},
              {(i, j): float(rng.normal()) for i in range(5) for j in range(i + 1, 5)}, 0.3)
    q = I.to_qubo()
    X = all_assignments(5)
    assert np.allclose(q.energies(X), I.energies(bits_to_spins(X)))


def test_pauli_terms_are_qiskit_ordered():
    q = QUBO(["a", "b", "c"], {0: 1.0}, {(0, 2): 1.0})
    terms = dict(q.to_ising().to_pauli_terms())
    assert "IIZ" in terms  # qubit 0 is rightmost
    assert "ZIZ" in terms


# ---------------------------------------------------------------- constraints / penalties
def test_equality_constraint_penalty_exact():
    m = Model("pick2")
    xs = m.binaries([f"x{i}" for i in range(4)])
    m.minimize(quicksum((i + 1) * x for i, x in enumerate(xs)))
    m.add_constraint(quicksum(xs) == 2, "pick_two")
    cm = m.compile()
    assert cm.penalties["pick_two"] == pytest.approx(1 + 2 + 3 + 4 + 1)
    rep = validate_compiled(cm)
    assert rep.passed, rep.issues
    assert rep.best_feasible == ["1100"] and rep.best_feasible_objective == pytest.approx(3)


def test_inequality_slack_encoding_is_exact():
    # knapsack: maximise value s.t. weight ≤ 7
    values, weights = [5, 4, 3, 7], [4, 3, 2, 5]
    m = Model("knap")
    xs = m.binaries([f"i{k}" for k in range(4)])
    m.maximize(quicksum(v * x for v, x in zip(values, xs)))
    m.add_constraint(quicksum(w * x for w, x in zip(weights, xs)) <= 7, "cap")
    cm = m.compile()
    # slack range [0, 7] → weights 1,2,4
    assert cm.slacks[0].weights == [1.0, 2.0, 4.0]
    rep = validate_compiled(cm)
    assert rep.passed, rep.issues
    # brute-force optimum computed independently
    best = max((sum(v * b for v, b in zip(values, bits)), bits)
               for bits in itertools.product([0, 1], repeat=4)
               if sum(w * b for w, b in zip(weights, bits)) <= 7)
    assert rep.best_feasible_objective == pytest.approx(best[0])


def test_binary_expansion_never_exceeds_range():
    from qopt.core.model import _binary_expansion_weights
    for mx in range(0, 40):
        w = _binary_expansion_weights(mx)
        reachable = {sum(c * b for c, b in zip(w, bits))
                     for bits in itertools.product([0, 1], repeat=len(w))}
        assert reachable == set(range(mx + 1))


def test_ge_constraint_and_evaluate_reports_violations():
    m = Model()
    a, b, c = m.binaries(["a", "b", "c"])
    m.minimize(a + b + c)
    m.add_constraint(a + b + c >= 2, "atleast2")
    cm = m.compile()
    r = cm.evaluate([1, 0, 0])
    assert not r.feasible and r.violations["atleast2"] == pytest.approx(1)
    assert cm.evaluate([1, 1, 0]).feasible
    assert validate_compiled(cm).passed


def test_non_integer_inequality_requires_resolution():
    m = Model()
    a, b = m.binaries(["a", "b"])
    m.minimize(-a - b)
    m.add_constraint(0.5 * a + 0.75 * b <= 1.0, "cap")
    with pytest.raises(ValueError, match="resolution"):
        m.compile()
    m2 = Model()
    a, b = m2.binaries(["a", "b"])
    m2.minimize(-a - b)
    m2.add_constraint(0.5 * a + 0.75 * b <= 1.0, "cap", resolution=0.25)
    cm = m2.compile()
    assert any("scaled" in w for w in cm.warnings)
    rep = validate_compiled(cm)
    assert rep.passed and rep.best_feasible_objective == pytest.approx(-1)


def test_infeasible_equality_detected_at_compile():
    m = Model()
    a, b = m.binaries(["a", "b"])
    m.minimize(a)
    m.add_constraint(a + b == 3, "impossible")
    with pytest.raises(ValueError, match="infeasible"):
        m.compile()


def test_too_small_manual_penalty_is_detected():
    m = Model()
    xs = m.binaries(["a", "b", "c"])
    m.minimize(-10 * xs[0] - 10 * xs[1] - 10 * xs[2])
    m.add_constraint(quicksum(xs) == 1, "one", penalty=0.5)
    rep = validate_compiled(m.compile())
    assert not rep.passed
    assert any("penalty" in i for i in rep.issues)


def test_spec_roundtrip():
    spec = {"variables": ["a", "b", "c"], "sense": "max",
            "objective": {"linear": {"a": 3, "b": 2, "c": 1}, "quadratic": [["a", "b", -4]]},
            "constraints": [{"label": "k", "lhs": {"linear": {"a": 1, "b": 1, "c": 1}},
                             "sense": "<=", "rhs": 2}]}
    m = Model.from_spec(spec)
    m2 = Model.from_spec(m.to_spec())
    r1, r2 = validate_compiled(m.compile()), validate_compiled(m2.compile())
    assert r1.passed and r2.passed and r1.best_feasible == r2.best_feasible


# ---------------------------------------------------------------- validation & preprocessing
def test_enumerate_matches_brute_force():
    q = random_qubo(10, seed=5)
    E = enumerate_energies(q)
    e, bits = brute(q)
    assert E.min() == pytest.approx(e)
    assert int(np.argmin(E)) == int("".join(map(str, bits[::-1])), 2)


def test_validate_qubo_flags_dynamic_range():
    q = QUBO(["a", "b"], {0: 1e-8, 1: 1e3})
    assert any("dynamic range" in i for i in validate_qubo(q)["issues"])


@pytest.mark.parametrize("seed", range(8))
def test_reduction_preserves_optimum(seed):
    rng = np.random.default_rng(seed)
    n = 10
    # strongly biased linear terms so some fixing rules fire
    lin = {i: float(rng.normal(scale=4)) for i in range(n)}
    quad = {(i, j): float(rng.normal()) for i in range(n) for j in range(i + 1, n) if rng.random() < 0.3}
    q = QUBO([f"x{i}" for i in range(n)], lin, quad, 0.0)
    red = reduce_qubo(q)
    full_min = enumerate_energies(q).min()
    if red.reduced.num_variables:
        Er = enumerate_energies(red.reduced)
        k = int(np.argmin(Er))
        xr = all_assignments(red.reduced.num_variables, k, k + 1)[0]
        assert Er.min() == pytest.approx(full_min)
        assert q.energy(red.expand(xr)) == pytest.approx(full_min)
    else:
        assert q.energy(red.expand([])) == pytest.approx(full_min)
