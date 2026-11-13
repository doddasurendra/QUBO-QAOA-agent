"""Quantum provider abstraction.

Honesty rules enforced here:
* ``execution_kind`` / ``is_real_hardware`` on every result come from the backend object
  (e.g. Qiskit ``backend.simulator`` / Braket device type), never from caller input.
* Gate-model providers run QAOA circuits; annealing providers (D-Wave) sample the QUBO
  directly and are labelled ``qpu_annealer`` — they are not QAOA.
* Real-hardware submissions require an explicit ``approval_id`` (checked by the caller,
  see qopt.services.approvals) — providers refuse otherwise.
"""
from __future__ import annotations

import importlib.util
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ProviderUnavailable(RuntimeError):
    """SDK missing, credentials missing or backend offline. Message explains which."""


class ApprovalRequired(PermissionError):
    pass


@dataclass
class BackendInfo:
    name: str
    provider: str
    technology: str            # 'gate' | 'annealer'
    is_simulator: bool
    num_qubits: Optional[int]
    status: str = "unknown"
    pending_jobs: Optional[int] = None
    basis_gates: List[str] = field(default_factory=list)
    connectivity: Optional[str] = None
    error_rates: Dict[str, float] = field(default_factory=dict)
    cost_note: str = "unknown — consult provider pricing"

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["execution_kind"] = ("shot_simulator" if self.is_simulator else
                               "qpu_annealer" if self.technology == "annealer" else "qpu_gate")
        return d


@dataclass
class ProviderJobResult:
    provider: str
    backend: str
    job_id: str
    status: str                       # QUEUED | RUNNING | DONE | ERROR | CANCELLED
    execution_kind: str
    is_real_hardware: bool
    counts: Dict[str, int] = field(default_factory=dict)   # assignment strings, variable order
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["bit_order"] = "variable 0 first"
        return d


def sdk_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


class Provider(ABC):
    name: str
    technology: str = "gate"
    sdk_module: Optional[str] = None
    credential_env: List[str] = []
    docs_url: str = ""

    def status(self) -> dict:
        sdk = sdk_installed(self.sdk_module) if self.sdk_module else True
        missing = [e for e in self.credential_env if not os.environ.get(e)]
        return {
            "name": self.name, "technology": self.technology, "sdk_module": self.sdk_module,
            "sdk_installed": sdk, "credentials_configured": not missing,
            "missing_credentials": missing, "available": sdk and not missing,
            "docs": self.docs_url,
        }

    def require_available(self):
        st = self.status()
        if not st["sdk_installed"]:
            raise ProviderUnavailable(f"{self.name}: Python SDK '{self.sdk_module}' is not installed "
                                      f"(pip install the '{self.name}' extra)")
        if not st["credentials_configured"]:
            raise ProviderUnavailable(f"{self.name}: missing credentials: {', '.join(st['missing_credentials'])}")

    @abstractmethod
    def list_backends(self) -> List[BackendInfo]: ...

    def submit_circuit(self, circuit, backend: str, shots: int, approval_id: Optional[str] = None) -> str:
        raise NotImplementedError(f"{self.name} does not run gate-model circuits")

    def submit_qubo(self, qubo, backend: str, num_reads: int, approval_id: Optional[str] = None) -> str:
        raise NotImplementedError(f"{self.name} does not sample QUBOs directly")

    @abstractmethod
    def job_result(self, job_id: str, num_qubits: int, wait: bool = True,
                   timeout: Optional[float] = None) -> ProviderJobResult: ...

    def cancel(self, job_id: str) -> bool:
        return False

    @staticmethod
    def _check_approval(is_real: bool, approval_id: Optional[str]):
        if is_real and not approval_id:
            raise ApprovalRequired("real quantum hardware submission requires an approved "
                                   "hardware-job approval (admin approval workflow)")
