"""Local Qiskit Aer simulator provider (always SIMULATOR)."""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from ..quantum.bitstrings import counts_from_qiskit
from .base import BackendInfo, Provider, ProviderJobResult


class AerProvider(Provider):
    name = "qiskit_aer"
    sdk_module = "qiskit_aer"
    docs_url = "https://qiskit.github.io/qiskit-aer/"

    BACKENDS = {
        "aer_ideal": "ideal shot-based simulator",
        "aer_noisy_depolarizing": "synthetic depolarizing noise model (1q=1e-3, 2q=1e-2, readout=2e-2) "
                                  "— illustrative, NOT calibrated to any device",
    }

    def __init__(self):
        self._jobs: Dict[str, ProviderJobResult] = {}

    def list_backends(self) -> List[BackendInfo]:
        return [BackendInfo(name=k, provider=self.name, technology="gate", is_simulator=True,
                            num_qubits=None, status="online", basis_gates=["rz", "sx", "x", "cx"],
                            connectivity="all-to-all", cost_note="free (local CPU) — " + v)
                for k, v in self.BACKENDS.items()]

    def _backend(self, name: str, seed: Optional[int] = None):
        from qiskit_aer import AerSimulator
        if name == "aer_ideal":
            return AerSimulator(seed_simulator=seed)
        if name == "aer_noisy_depolarizing":
            from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error
            nm = NoiseModel()
            nm.add_all_qubit_quantum_error(depolarizing_error(1e-3, 1), ["rz", "sx", "x", "rx", "h"])
            nm.add_all_qubit_quantum_error(depolarizing_error(1e-2, 2), ["cx", "rzz"])
            nm.add_all_qubit_readout_error(ReadoutError([[0.98, 0.02], [0.02, 0.98]]))
            return AerSimulator(noise_model=nm, seed_simulator=seed)
        raise ValueError(f"unknown Aer backend {name!r}")

    def submit_circuit(self, circuit, backend: str, shots: int, approval_id: Optional[str] = None,
                       seed: Optional[int] = None) -> str:
        from qiskit import transpile
        be = self._backend(backend, seed)
        tc = transpile(circuit, be, optimization_level=1, seed_transpiler=seed)
        raw = be.run(tc, shots=shots).result().get_counts()
        jid = f"aer-{uuid.uuid4().hex[:12]}"
        self._jobs[jid] = ProviderJobResult(
            self.name, backend, jid, "DONE", "shot_simulator", False,
            counts_from_qiskit(raw, circuit.num_qubits),
            {"shots": shots, "transpiled_depth": tc.depth(), "transpiled_ops": dict(tc.count_ops()),
             "noise": backend != "aer_ideal"})
        return jid

    def job_result(self, job_id: str, num_qubits: int, wait: bool = True, timeout=None) -> ProviderJobResult:
        if job_id not in self._jobs:
            raise KeyError(f"unknown job {job_id}")
        return self._jobs[job_id]
