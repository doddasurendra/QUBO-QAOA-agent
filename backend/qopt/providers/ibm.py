"""IBM Quantum via qiskit-ibm-runtime (SamplerV2).

Requires ``pip install qiskit-ibm-runtime`` and env ``QISKIT_IBM_TOKEN`` (optionally
``QISKIT_IBM_INSTANCE``, ``QISKIT_IBM_CHANNEL`` default 'ibm_quantum_platform').
Real-hardware status is read from ``backend.simulator`` / configuration.
"""
from __future__ import annotations

import os
from typing import List, Optional

from ..quantum.bitstrings import counts_from_qiskit
from .base import BackendInfo, Provider, ProviderJobResult, ProviderUnavailable


class IBMRuntimeProvider(Provider):
    name = "ibm_quantum"
    sdk_module = "qiskit_ibm_runtime"
    credential_env = ["QISKIT_IBM_TOKEN"]
    docs_url = "https://quantum.cloud.ibm.com/docs/en/guides"

    def __init__(self, service=None):
        self._service = service   # injectable for tests

    def service(self):
        if self._service is None:
            self.require_available()
            from qiskit_ibm_runtime import QiskitRuntimeService
            kwargs = {"channel": os.environ.get("QISKIT_IBM_CHANNEL", "ibm_quantum_platform"),
                      "token": os.environ["QISKIT_IBM_TOKEN"]}
            if os.environ.get("QISKIT_IBM_INSTANCE"):
                kwargs["instance"] = os.environ["QISKIT_IBM_INSTANCE"]
            self._service = QiskitRuntimeService(**kwargs)
        return self._service

    def status(self) -> dict:
        st = super().status()
        if self._service is not None:
            st.update(available=True, credentials_configured=True, sdk_installed=True, missing_credentials=[])
        return st

    @staticmethod
    def _is_sim(backend) -> bool:
        sim = getattr(backend, "simulator", None)
        if sim is None:
            cfg = backend.configuration() if hasattr(backend, "configuration") else None
            sim = bool(getattr(cfg, "simulator", False))
        return bool(sim)

    def list_backends(self) -> List[BackendInfo]:
        out = []
        for b in self.service().backends():
            try:
                st = b.status()
                status, pending = ("online" if st.operational else "offline"), st.pending_jobs
            except Exception:  # noqa: BLE001 — status endpoint can be unavailable
                status, pending = "unknown", None
            out.append(BackendInfo(name=b.name, provider=self.name, technology="gate",
                                   is_simulator=self._is_sim(b), num_qubits=getattr(b, "num_qubits", None),
                                   status=status, pending_jobs=pending,
                                   basis_gates=list(getattr(getattr(b, "target", None), "operation_names", []) or []),
                                   connectivity="heavy-hex coupling map"))
        return out

    def submit_circuit(self, circuit, backend: str, shots: int, approval_id: Optional[str] = None) -> str:
        b = self.service().backend(backend)          # raises ProviderUnavailable first if not configured
        self._check_approval(not self._is_sim(b), approval_id)
        from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
        from qiskit_ibm_runtime import SamplerV2
        isa = generate_preset_pass_manager(optimization_level=2, backend=b).run(circuit)
        job = SamplerV2(mode=b).run([isa], shots=shots)
        return job.job_id()

    def job_result(self, job_id: str, num_qubits: int, wait: bool = True, timeout=None) -> ProviderJobResult:
        job = self.service().job(job_id)
        backend = job.backend()
        is_real = not self._is_sim(backend)
        status = str(job.status()).split(".")[-1].upper()
        res = ProviderJobResult(self.name, backend.name, job_id, status,
                                "qpu_gate" if is_real else "shot_simulator", is_real)
        if status in ("DONE",) or wait:
            try:
                pub = job.result(timeout=timeout)[0]
                raw = pub.data.meas.get_counts()
                res.counts = counts_from_qiskit(raw, num_qubits)
                res.status = "DONE"
                res.metadata = {"usage": getattr(job, "usage", lambda: None)()}
            except Exception as exc:  # noqa: BLE001 — surface provider errors verbatim
                res.status, res.error = "ERROR", f"{type(exc).__name__}: {exc}"
        return res

    def cancel(self, job_id: str) -> bool:
        self.service().job(job_id).cancel()
        return True
