#!/usr/bin/env bash
# Each case runs in a fresh process: do something first, then build a Qiskit circuit. Prints OK / CRASH per case.
# Used to find which earlier activity in the test process makes Qiskit segfault on GitHub's Linux runner.
cd "$(dirname "$0")/../../backend" || exit 1
run() {
  local name="$1"; shift
  if timeout 300 python -X faulthandler -c "$1" >/tmp/case.log 2>&1; then echo "OK     $name"; else echo "CRASH  $name (exit $?)"; tail -n 4 /tmp/case.log | sed 's/^/         /'; fi
}
QC='from qiskit import QuantumCircuit; from qiskit.circuit import ParameterVector; QuantumCircuit(2).rx(ParameterVector("g",1)[0],0)'
run "baseline (qiskit only)"            "$QC"
run "after import scipy.optimize"       "import scipy.optimize; $QC"
run "after scipy milp (HiGHS)"          "from qopt.solvers import milp_solve; from qopt.problems import random_qubo; milp_solve(random_qubo(8)); $QC"
run "after exhaustive solver"           "from qopt.solvers import exhaustive; from qopt.problems import random_qubo; exhaustive(random_qubo(8)); $QC"
run "after statevector QAOA"            "from qopt.quantum import run_qaoa, QAOAConfig; from qopt.problems import random_qubo; run_qaoa(random_qubo(5), QAOAConfig(p=1,restarts=1,maxiter=10)); $QC"
run "after import anthropic"            "import anthropic; $QC"
run "after import qopt.agents"          "import qopt.agents; $QC"
run "after import fastapi app"          "import qopt.api.app; $QC"
run "pytest test_api only"              "import pytest,sys; sys.exit(pytest.main(['-q','-x','tests/test_api.py']))"
run "pytest test_agents then test_api"  "import pytest,sys; sys.exit(pytest.main(['-q','-x','tests/test_agents.py','tests/test_api.py']))"
exit 0
