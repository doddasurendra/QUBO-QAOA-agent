"""Regression: Qiskit >= 2.5 segfaulted on Linux when circuits were built in successive short-lived event-loop
threads (each TestClient / server lifespan runs in one) unless Qiskit was first used in the main thread.
qopt.api.app warms Qiskit up in the main thread at import; these tests run the crashing pattern in a subprocess
so a regression shows up as a failed test, not as a dead test run."""
import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    import os, tempfile
    from fastapi.testclient import TestClient
    import qopt.api.app as appmod
    from qopt.config import get_settings
    from qopt.db import reset_engine
    assert appmod._warmed_up, "import-time warm-up did not run"
    tmp = tempfile.mkdtemp()
    os.environ.update(QOPT_WORKER_THREADS="0", QOPT_BACKUP_INTERVAL_HOURS="0", QOPT_JWT_SECRET="t" * 48)
    for i in range(3):                       # the second start used to crash
        os.environ["QOPT_DATABASE_URL"] = f"sqlite:///{tmp}/r{i}.db".replace(os.sep, "/")
        get_settings.cache_clear(); reset_engine()
        with TestClient(appmod.create_app()) as c:
            assert c.get("/api/health").status_code == 200
            from qiskit import QuantumCircuit
            from qiskit.circuit import ParameterVector
            QuantumCircuit(2).rx(ParameterVector("g", 1)[0], 0)
    print("ok")
""")


def test_repeated_app_lifespans_with_qiskit_do_not_crash():
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", SCRIPT], cwd=BACKEND, capture_output=True,
                       text=True, timeout=300)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), (r.returncode, r.stdout[-2000:], r.stderr[-4000:])
