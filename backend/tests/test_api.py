"""End-to-end API tests (database, auth/RBAC, jobs, approvals, reports)."""
import pytest

from qopt.industries import get_problem

SPEC = {"variables": ["a", "b", "c"], "sense": "max",
        "objective": {"linear": {"a": 5, "b": 4, "c": 3}},
        "constraints": [{"label": "cap", "lhs": {"linear": {"a": 4, "b": 3, "c": 2}}, "sense": "<=", "rhs": 5}]}


def login(api, email, pw):
    r = api.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_bootstrap_only_once_and_auth_required(api):
    assert api.get("/api/auth/status").json()["bootstrap_required"] is True
    assert api.get("/api/experiments").status_code == 401
    r = api.post("/api/auth/bootstrap", json={"email": "a@b.co", "password": "longenough1"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert api.post("/api/auth/bootstrap", json={"email": "c@d.co", "password": "longenough1"}).status_code == 403
    assert api.post("/api/auth/login", json={"email": "a@b.co", "password": "wrong-password"}).status_code == 401
    assert api.post("/api/auth/register", json={"email": "x@y.co", "password": "longenough1"}).status_code == 403


def test_rbac_viewer_cannot_run_jobs_and_researcher_cannot_admin(admin_client):
    api = admin_client
    for email, role in (("v@x.co", "viewer"), ("r@x.co", "researcher")):
        assert api.post("/api/users", json={"email": email, "password": "password123", "role": role}).status_code == 200
    hv, hr = login(api, "v@x.co", "password123"), login(api, "r@x.co", "password123")
    assert api.post("/api/jobs", json={"kind": "classical", "params": {"spec": SPEC, "solver": "exhaustive"}},
                    headers=hv).status_code == 403
    assert api.get("/api/users", headers=hr).status_code == 403
    assert api.post("/api/qubo/compile", json={"spec": SPEC}, headers=hv).status_code == 200


def test_compile_validate_and_solve_custom_spec(admin_client):
    api = admin_client
    c = api.post("/api/qubo/compile", json={"spec": SPEC}).json()
    assert c["summary"]["num_slack_variables"] == 3 and len(c["matrix_upper"]) == 6
    v = api.post("/api/qubo/validate", json={"spec": SPEC}).json()
    # weights (4,3,2) cap 5: {a}=5, {b,c}=7 (w=5), {a,c} w=6 infeasible  →  optimum 7 with b,c
    assert v["exhaustive"]["passed"] and v["exhaustive"]["best_feasible_objective"] == 7
    assert v["exhaustive"]["best_feasible"] == ["011"]
    j = api.post("/api/jobs", json={"kind": "classical", "params": {"spec": SPEC, "solver": "exhaustive"}}).json()
    assert j["status"] == "done", j
    assert j["result"]["evaluation"]["feasible"] and j["result"]["evaluation"]["objective"] == 7
    assert j["is_real_hardware"] is False and j["execution_kind"] == "classical"


def test_matrix_and_ising_endpoints_are_consistent(admin_client):
    api = admin_client
    r = api.post("/api/qubo/from-matrix", json={"matrix": [[1, -2], [0, 3]], "offset": 0.5}).json()
    assert r["structural_validation"]["ising_equivalence"]["passed"]
    back = api.post("/api/qubo/from-ising", json=r["ising"]).json()
    assert back["matrix_upper"] == [[1.0, -2.0], [0.0, 3.0]] and back["qubo"]["offset"] == pytest.approx(0.5)
    assert api.post("/api/qubo/from-matrix", json={"matrix": [[1, 2], [3, 4]], "convention": "symmetric"}
                    ).status_code == 422


def test_industry_experiment_qaoa_job_and_report(admin_client):
    api = admin_client
    key = "manufacturing.machine_scheduling"
    f = api.post(f"/api/industries/{key}/formulate", json={"data": get_problem(key).example(), "save_as": "ms"}).json()
    eid = f["experiment_id"]
    j = api.post("/api/jobs", json={"kind": "qaoa", "experiment_id": eid,
                                    "params": {"config": {"p": 1, "restarts": 1, "maxiter": 40, "shots": 500}}}).json()
    assert j["status"] == "done", j.get("error")
    res = j["result"]
    assert res["execution_kind"] == "statevector_simulator" and res["is_real_hardware"] is False
    assert res["circuit"]["num_qubits"] == res["num_qubits"]
    assert res["domain"]["interpretation"]["all_jobs_assigned_once"] in (True, False)
    md = api.get(f"/api/reports/jobs/{j['id']}").text
    assert "Real quantum hardware used: **NO" in md
    exp = api.get(f"/api/experiments/{eid}").json()
    assert exp["jobs"][0]["id"] == j["id"]


def test_hybrid_job_with_aer_noisy_simulator(admin_client):
    api = admin_client
    j = api.post("/api/jobs", json={"kind": "hybrid", "params": {
        "spec": SPEC, "solvers": ["exhaustive", "simulated_annealing"],
        "qaoa": {"p": 1, "restarts": 1, "maxiter": 30},
        "hardware": {"provider": "qiskit_aer", "backend": "aer_ideal", "shots": 500}}}).json()
    assert j["status"] == "done", j.get("error")
    kinds = {r["execution_kind"] for r in j["result"]["results"]}
    assert kinds == {"classical", "shot_simulator"} and j["is_real_hardware"] is False


def test_hardware_cannot_bypass_approval(admin_client):
    api = admin_client
    r = api.post("/api/jobs", json={"kind": "hybrid", "params": {"spec": SPEC, "solvers": ["exhaustive"],
                                                                 "hardware": {"provider": "ibm_quantum",
                                                                              "backend": "ibm_x"}}}).json()
    assert r["status"] == "error" and "approval workflow" in r["error"]
    assert api.post("/api/jobs", json={"kind": "hardware", "params": {}}).status_code == 422


def test_approval_flow_refuses_unavailable_provider(admin_client):
    api = admin_client
    exp = api.post("/api/experiments", json={"name": "k", "spec": SPEC}).json()
    a = api.post("/api/approvals", json={"experiment_id": exp["id"], "provider": "ibm_quantum",
                                         "backend": "ibm_brisbane", "shots": 100}).json()
    assert a["status"] == "pending"
    r = api.post(f"/api/approvals/{a['id']}/approve", json={"note": "ok"})
    assert r.status_code == 409 and "unavailable" in r.json()["detail"]
    assert api.post(f"/api/approvals/{a['id']}/reject", json={"note": "no creds"}).json()["status"] == "rejected"
    audit = api.get("/api/admin/audit").json()
    assert {"approval_requested", "approval_rejected"} <= {e["action"] for e in audit}


def test_api_key_auth_and_revocation(admin_client):
    api = admin_client
    k = api.post("/api/apikeys", json={"name": "ci"}).json()
    h = {"X-API-Key": k["key"]}
    assert api.get("/api/auth/me", headers={**h, "Authorization": ""}).status_code == 200
    api.delete(f"/api/apikeys/{k['id']}")
    assert api.get("/api/auth/me", headers={**h, "Authorization": ""}).status_code == 401
    assert all("key" not in row for row in api.get("/api/apikeys").json())   # never shown again


def test_datasets_samples_upload_validation(admin_client):
    api = admin_client
    ds = api.get("/api/datasets").json()
    assert len([d for d in ds if d["is_sample"]]) == 6 and all("SAMPLE" in d["name"] for d in ds if d["is_sample"])
    bad = api.post("/api/datasets", json={"name": "bad", "problem_key": "finance.portfolio", "content": {"x": 1}})
    assert bad.status_code == 422
    r = api.post("/api/datasets/upload", files={"file": ("d.exe", b"MZ", "application/octet-stream")},
                 data={"name": "x"})
    assert r.status_code == 415
    r = api.post("/api/datasets/upload", files={"file": ("d.csv", b"a,b\n1,2\n", "text/csv")}, data={"name": "csv"})
    assert r.status_code == 200


def test_research_library_upload_and_search(admin_client):
    api = admin_client
    text = ("The Quantum Approximate Optimization Algorithm alternates cost and mixer unitaries. "
            "Penalty methods encode constraints in QUBO models. ") * 5
    assert api.post("/api/research/upload", files={"file": ("qaoa.md", text.encode(), "text/markdown")},
                    data={"title": "QAOA notes"}).status_code == 200
    res = api.get("/api/research/search", params={"q": "mixer unitaries"}).json()["results"]
    assert res and res[0]["title"] == "QAOA notes"
    assert api.post("/api/research/upload", files={"file": ("x.pdf", b"not a pdf", "application/pdf")}
                    ).status_code == 415


def test_agents_report_unavailable_without_key(admin_client):
    api = admin_client
    info = api.get("/api/agents").json()
    assert len(info["agents"]) == 10 and info["credentials"]["api_credentials_in_env"] is False
    r = api.post("/api/agents/problem_understanding/run", json={"message": "optimise"})
    assert r.status_code == 503 and "unavailable" in r.json()["detail"]


def test_benchmark_job_and_dashboard(admin_client):
    api = admin_client
    j = api.post("/api/jobs", json={"kind": "benchmark", "params": {
        "problems": ["maxcut_gnp"], "sizes": [5], "seeds": 2, "solvers": ["simulated_annealing", "milp"],
        "qaoa_depths": [1], "qaoa_maxiter": 30, "qaoa_shots": 256}}).json()
    assert j["status"] == "done", j.get("error")
    rows = j["result"]["rows"]
    assert {r["solver"] for r in rows} == {"simulated_annealing", "milp", "qaoa_p1"}
    assert next(r for r in rows if r["solver"] == "milp")["optimum_hit_rate"] == 1.0
    ov = api.get("/api/dashboard/overview").json()
    assert ov["jobs_by_status"]["done"] >= 1 and ov["data_source"] == "live application database"
    u = api.get("/api/usage/summary").json()
    assert u["totals"]["compute_s"] > 0


def test_circuit_landscape_and_state_endpoints(admin_client):
    api = admin_client
    c = api.post("/api/qaoa/circuit", json={"spec": SPEC, "p": 1, "gammas": [0.3], "betas": [0.2]}).json()
    assert c["summary"]["num_qubits"] == 6 and "OPENQASM 3" in c["qasm3"] and c["gates"]
    st = api.post("/api/simulator/state", json={"spec": SPEC, "gammas": [0.3], "betas": [0.2]}).json()
    assert abs(sum(s["probability"] for s in st["top_states"]) - 1) < 1e-6 or len(st["top_states"]) == 32
    ls = api.post("/api/qaoa/landscape", json={"spec": SPEC, "resolution": 6}).json()
    assert len(ls["energies"]) == 6 and len(ls["energies"][0]) == 6


def test_input_validation_errors(admin_client):
    api = admin_client
    assert api.post("/api/qubo/compile", json={}).status_code == 422
    assert api.post("/api/qubo/evaluate", json={"spec": SPEC, "bitstring": "10x"}).status_code == 422
    assert api.post("/api/industries/finance.portfolio/formulate", json={"data": {"assets": ["a"]}}).status_code == 422
    assert api.get("/api/docs-content/..%2F..%2Fetc").status_code in (400, 404)
