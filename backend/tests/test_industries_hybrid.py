import pytest

from qopt.core import Model, validate_compiled
from qopt.hybrid import HybridRequest, recommend_solvers, run_hybrid
from qopt.industries import PROBLEMS, get_problem
from qopt.providers import ApprovalRequired, registry
from qopt.quantum import QAOAConfig
from qopt.solvers import exhaustive


@pytest.mark.parametrize("key", sorted(PROBLEMS))
def test_industry_example_formulations_are_exact(key):
    """Every industry example: QUBO optimum == best feasible solution of the original model,
    penalties dominate, and the decoded solution satisfies the domain checks."""
    prob = get_problem(key)
    data, cm = prob.compile(prob.example())
    assert cm.num_decision <= 18, f"example too big for exhaustive validation: {cm.num_decision}"
    rep = validate_compiled(cm)
    assert rep.passed, rep.issues
    assert rep.num_feasible > 0
    best = exhaustive(cm.qubo)
    ev = cm.evaluate(best.best_x)
    assert ev.feasible
    interp = prob.interpret(data, ev.assignment)
    for k, v in interp.items():
        if k.endswith("_ok") or k in ("valid_tour", "within_budget", "each_user_assigned_once",
                                       "requirements_met", "all_jobs_assigned_once"):
            assert v is True, (k, interp)


def test_industry_describe_has_schema_and_marks_sample_data():
    for p in PROBLEMS.values():
        d = p.describe()
        assert d["input_schema"]["properties"] and d["example_is_sample_data"] is True


def test_invalid_industry_inputs_rejected():
    port = get_problem("finance.portfolio")
    bad = port.example(); bad["covariance"][0][1] = 99
    with pytest.raises(Exception):
        port.parse(bad)
    ev = get_problem("energy.ev_charging")
    bad = ev.example(); bad["grid_limit"] = [0, 0, 0, 1]
    with pytest.raises(Exception):
        ev.parse(bad)


def test_routing_known_optimum():
    prob = get_problem("logistics.delivery_routing")
    data, cm = prob.compile(prob.example())
    best = exhaustive(cm.qubo)
    out = prob.interpret(data, cm.evaluate(best.best_x).assignment)
    # tours of the 4-node example: 0-1-2-3-0 = 4+3+2+5 = 14 (optimal), 0-1-3-2-0 = 4+7+2+9 = 22, 0-2-1-3-0 = 9+3+7+5 = 24
    assert out["valid_tour"] and out["tour_length"] == 14


def test_quadratic_equality_conflict_constraint():
    m = Model()
    a, b = m.binaries(["a", "b"])
    m.minimize(-a - b)
    m.add_constraint(a * b == 0, "conflict")
    rep = validate_compiled(m.compile())
    assert rep.passed and rep.best_feasible_objective == -1
    m2 = Model()
    a, b = m2.binaries(["a", "b"])
    m2.minimize(a)
    m2.add_constraint(a * b - b == 0, "bad")
    with pytest.raises(ValueError, match="non-negative"):
        m2.compile()


def test_hybrid_end_to_end_portfolio():
    prob = get_problem("finance.portfolio")
    data, cm = prob.compile(prob.example())
    rep = run_hybrid(cm.qubo, HybridRequest(solvers=["exhaustive", "simulated_annealing", "milp", "qaoa_statevector"],
                                            qaoa=QAOAConfig(p=1, restarts=1, maxiter=60, shots=2000)), cm)
    assert not rep["errors"], rep["errors"]
    assert rep["exhaustive_validation"]["passed"]
    top = rep["ranking"][0]
    assert top["feasible"] and top["reference"] == "proven optimum"
    kinds = {r["solver"]: r["execution_kind"] for r in rep["results"]}
    assert kinds["qaoa_statevector"] == "statevector_simulator"
    assert all(not r["is_real_hardware"] for r in rep["results"])
    assert any("No quantum advantage" in n for n in rep["notes"])


def test_hybrid_aer_backend_is_labelled_simulator():
    prob = get_problem("manufacturing.machine_scheduling")
    data, cm = prob.compile(prob.example())
    rep = run_hybrid(cm.qubo, HybridRequest(solvers=["exhaustive"], qaoa=QAOAConfig(p=1, restarts=1, maxiter=40),
                                            hardware={"provider": "qiskit_aer", "backend": "aer_noisy_depolarizing",
                                                      "shots": 1000}), cm)
    assert not rep["errors"], rep["errors"]
    hw = [r for r in rep["results"] if r["solver"].startswith("qiskit_aer")][0]
    assert hw["execution_kind"] == "shot_simulator" and hw["is_real_hardware"] is False


def test_hardware_without_credentials_reports_unavailable_not_fake_result():
    from qopt.core import QUBO
    q = QUBO(["a", "b"], {0: 1.0}, {(0, 1): -2.0})
    for prov in ("ibm_quantum", "aws_braket", "dwave"):
        rep = run_hybrid(q, HybridRequest(solvers=["exhaustive"], hardware={"provider": prov, "backend": "x"}))
        assert rep["errors"] and all(r["solver"] == "exhaustive" for r in rep["results"])


def test_real_hardware_requires_approval():
    """Mocked IBM backend that reports simulator=False must be refused without approval."""
    from qopt.providers.ibm import IBMRuntimeProvider

    class FakeBackend:
        name = "ibm_fake_qpu"; simulator = False; num_qubits = 127

    class FakeService:
        def backend(self, name): return FakeBackend()
        def backends(self): return [FakeBackend()]

    p = IBMRuntimeProvider(service=FakeService())
    infos = p.list_backends()
    assert infos[0].to_dict()["execution_kind"] == "qpu_gate"
    from qiskit import QuantumCircuit
    with pytest.raises(ApprovalRequired):
        p.submit_circuit(QuantumCircuit(1), "ibm_fake_qpu", 100, approval_id=None)


def test_solver_recommendations_are_explained():
    from qopt.problems import random_qubo
    small = recommend_solvers(random_qubo(8), registry.status())
    big = recommend_solvers(random_qubo(40, density=0.1), registry.status())
    get = lambda recs, n: next(r for r in recs if r["solver"] == n)
    assert get(small, "exhaustive")["recommended"] and not get(big, "exhaustive")["recommended"]
    assert get(small, "qaoa_statevector")["recommended"] and not get(big, "qaoa_statevector")["recommended"]
    assert all(r["reasons"] for r in small)
