#!/usr/bin/env bash
# Each case runs in a fresh process. Prints OK / CRASH per case. Diagnostic only; always exits 0.
# Narrow down which part of the API test fixture makes Qiskit segfault on GitHub's Linux runner.
cd "$(dirname "$0")/../../backend" || exit 1
run() {
  local name="$1"; shift
  if timeout 300 python -X faulthandler -c "$1" >/tmp/case.log 2>&1; then echo "OK     $name"; else echo "CRASH  $name (exit $?)"; grep -m3 'File ' /tmp/case.log | sed 's/^/         /'; fi
}
QK=$(python -c "import qiskit.circuit.quantumcircuit as m; print(m.__file__)")
echo "quantumcircuit.py 1205-1214:"; sed -n '1205,1214p' "$QK" | sed 's/^/    /'
export QOPT_DATABASE_URL="sqlite:////tmp/bisect.db" QOPT_WORKER_THREADS=0 QOPT_JWT_SECRET="test-secret-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" QOPT_BACKUP_INTERVAL_HOURS=0
TC='from fastapi.testclient import TestClient; from qopt.api.app import create_app
with TestClient(create_app()) as c: print(c.get("/api/health").status_code)'
run "create_app only (no lifespan)"            "from qopt.api.app import create_app; create_app()"
run "create_app then qiskit in main"           "from qopt.api.app import create_app; create_app(); from qiskit import QuantumCircuit; QuantumCircuit(2)"
run "create_app then qiskit in a thread"       "from qopt.api.app import create_app; create_app(); import threading; from qiskit import QuantumCircuit; t=threading.Thread(target=lambda: QuantumCircuit(2)); t.start(); t.join()"
run "configure_logging then qiskit"            "from qopt.api.app import configure_logging; configure_logging(); from qiskit import QuantumCircuit; QuantumCircuit(2)"
run "TestClient lifespan"                       "$TC"
run "qiskit in main first, then TestClient"     "from qiskit import QuantumCircuit; QuantumCircuit(2)
$TC"
exit 0
