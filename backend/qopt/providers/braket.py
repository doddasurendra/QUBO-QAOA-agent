"""Amazon Braket (gives access to IonQ, Rigetti, IQM and others, subject to region/availability).

Requires ``pip install amazon-braket-sdk`` and standard AWS credentials (env
``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY`` or a profile) plus ``QOPT_BRAKET_S3_BUCKET``
for results. The QAOA circuit is built natively with Braket gates from the Ising model, using
the same conventions as qopt.quantum.circuits (verified in tests on the local simulator when
the SDK is installed).

Braket measurement strings list qubit 0 first, i.e. they are already in variable order.
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence

from ..core.qubo import QUBO
from .base import BackendInfo, Provider, ProviderJobResult


def build_braket_qaoa(qubo: QUBO, gammas: Sequence[float], betas: Sequence[float], scale: float):
    from braket.circuits import Circuit
    ising = qubo.to_ising()
    n = qubo.num_variables
    c = Circuit()
    for q in range(n):
        c.h(q)
    for g, b in zip(gammas, betas):
        for i, h in sorted(ising.h.items()):
            c.rz(i, 2 * g * h / scale)
        for (i, j), J in sorted(ising.J.items()):
            c.zz(i, j, 2 * g * J / scale)     # ZZ(θ) = exp(-iθ/2 Z⊗Z)
        for q in range(n):
            c.rx(q, 2 * b)
    return c


class BraketProvider(Provider):
    name = "aws_braket"
    sdk_module = "braket"
    credential_env = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "QOPT_BRAKET_S3_BUCKET"]
    docs_url = "https://docs.aws.amazon.com/braket/"

    def status(self) -> dict:
        st = super().status()
        if os.environ.get("AWS_PROFILE") and os.environ.get("QOPT_BRAKET_S3_BUCKET"):
            st.update(credentials_configured=True, missing_credentials=[], available=st["sdk_installed"])
        return st

    def list_backends(self) -> List[BackendInfo]:
        self.require_available()
        from braket.aws import AwsDevice
        out = []
        for d in AwsDevice.get_devices(statuses=["ONLINE", "RETIRED", "OFFLINE"]):
            is_sim = str(d.type).endswith("SIMULATOR")
            tech = "annealer" if "annealing" in str(getattr(d, "provider_name", "")).lower() else "gate"
            out.append(BackendInfo(name=d.arn, provider=self.name, technology=tech, is_simulator=is_sim,
                                   num_qubits=getattr(getattr(d, "properties", None), "paradigm", None) and
                                   getattr(d.properties.paradigm, "qubitCount", None),
                                   status=str(d.status).lower(),
                                   cost_note="per-task + per-shot pricing, see aws.amazon.com/braket/pricing"))
        return out

    def submit_circuit(self, circuit, backend: str, shots: int, approval_id: Optional[str] = None) -> str:
        self.require_available()
        from braket.aws import AwsDevice
        dev = AwsDevice(backend)
        is_real = not str(dev.type).endswith("SIMULATOR")
        self._check_approval(is_real, approval_id)
        bucket = os.environ["QOPT_BRAKET_S3_BUCKET"]
        task = dev.run(circuit, (bucket, "qopt-results"), shots=shots)
        return task.id

    def job_result(self, job_id: str, num_qubits: int, wait: bool = True, timeout=None) -> ProviderJobResult:
        from braket.aws import AwsDevice, AwsQuantumTask
        task = AwsQuantumTask(job_id)
        dev = AwsDevice(task.metadata()["deviceArn"])
        is_real = not str(dev.type).endswith("SIMULATOR")
        state = task.state()
        res = ProviderJobResult(self.name, dev.arn, job_id, {"COMPLETED": "DONE", "FAILED": "ERROR"}.get(state, state),
                                "qpu_gate" if is_real else "shot_simulator", is_real)
        if state == "COMPLETED" or wait:
            r = task.result()
            res.counts = {k: int(v) for k, v in r.measurement_counts.items()}  # qubit 0 first
            res.status = "DONE"
        return res
