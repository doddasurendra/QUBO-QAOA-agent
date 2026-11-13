import numpy as np
import pytest

from qopt.core import QUBO, enumerate_energies
from qopt.solvers import exhaustive, greedy_descent, milp_solve, simulated_annealing, solve, tabu_search


def rq(n, seed):
    rng = np.random.default_rng(seed)
    return QUBO([f"x{i}" for i in range(n)], {i: float(rng.normal()) for i in range(n)},
                {(i, j): float(rng.normal()) for i in range(n) for j in range(i + 1, n) if rng.random() < .5},
                float(rng.normal()))


@pytest.mark.parametrize("seed", range(6))
def test_exhaustive_and_milp_find_true_optimum(seed):
    q = rq(12, seed)
    truth = enumerate_energies(q).min()
    ex = exhaustive(q)
    assert ex.best_energy == pytest.approx(truth) and ex.optimal
    assert q.energy(ex.best_x) == pytest.approx(truth)
    mi = milp_solve(q)
    assert mi.optimal and mi.best_energy == pytest.approx(truth, abs=1e-6)
    assert mi.execution_kind == "classical" and not mi.is_real_hardware


@pytest.mark.parametrize("seed", range(4))
def test_heuristics_reach_optimum_on_small_instances(seed):
    q = rq(14, seed + 10)
    truth = enumerate_energies(q).min()
    sa = simulated_annealing(q, num_reads=20, num_sweeps=300, seed=seed)
    tb = tabu_search(q, max_iter=500, seed=seed)
    assert sa.best_energy == pytest.approx(truth)
    assert tb.best_energy == pytest.approx(truth)
    gd = greedy_descent(q, seed=seed)
    assert gd.best_energy >= truth - 1e-9      # heuristic, never below the optimum
    for r in (sa, tb, gd):
        assert q.energy(r.best_x) == pytest.approx(r.best_energy)   # reported energy is honest


def test_samples_sorted_and_counts_sum():
    q = rq(8, 3)
    r = simulated_annealing(q, num_reads=30, num_sweeps=50, seed=1)
    es = [s.energy for s in r.samples]
    assert es == sorted(es) and sum(s.count for s in r.samples) == 30


def test_exhaustive_limit_and_unknown_solver():
    with pytest.raises(ValueError):
        exhaustive(rq(30, 0), max_vars=24)
    with pytest.raises(ValueError):
        solve(rq(3, 0), "magic")


def test_milp_on_larger_sparse_instance_agrees_with_tabu():
    q = rq(40, 99)
    mi = milp_solve(q, time_limit=60)
    tb = tabu_search(q, max_iter=3000, restarts=10, seed=0)
    assert mi.best_energy <= tb.best_energy + 1e-6
