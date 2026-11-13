"""D-Wave quantum ANNEALING provider (NOT gate-based QAOA).

Requires ``pip install dwave-ocean-sdk`` and ``DWAVE_API_TOKEN``. The QUBO is submitted in
its native {0,1} form (``sample_qubo``), so no spin-convention conversion is needed here;
returned samples are re-evaluated with the platform's own QUBO energy function.
Results are labelled ``qpu_annealer``.
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from ..core.qubo import QUBO
from .base import BackendInfo, Provider, ProviderJobResult


def qubo_to_dwave_dict(q: QUBO) -> Dict[tuple, float]:
    d = {(q.variables[i], q.variables[i]): c for i, c in q.linear.items()}
    d.update({(q.variables[i], q.variables[j]): c for (i, j), c in q.quadratic.items()})
    return d


class DWaveProvider(Provider):
    name = "dwave"
    technology = "annealer"
    sdk_module = "dwave.system"
    credential_env = ["DWAVE_API_TOKEN"]
    docs_url = "https://docs.dwavequantum.com/"

    def __init__(self):
        self._results: Dict[str, ProviderJobResult] = {}

    def status(self) -> dict:
        try:
            return super().status()
        except ModuleNotFoundError:  # parent package 'dwave' missing
            st = {"name": self.name, "technology": self.technology, "sdk_module": self.sdk_module,
                  "sdk_installed": False, "credentials_configured": False,
                  "missing_credentials": self.credential_env, "available": False, "docs": self.docs_url}
            return st

    def require_available(self):
        st = self.status()
        from .base import ProviderUnavailable
        if not st["available"]:
            raise ProviderUnavailable(f"dwave: sdk_installed={st['sdk_installed']}, "
                                      f"missing credentials={st['missing_credentials']}")

    def list_backends(self) -> List[BackendInfo]:
        self.require_available()
        from dwave.cloud import Client
        out = []
        with Client.from_config() as client:
            for s in client.get_solvers(qpu=True):
                out.append(BackendInfo(name=s.name, provider=self.name, technology="annealer",
                                       is_simulator=False, num_qubits=len(s.nodes), status="online",
                                       connectivity=str(s.properties.get("topology", {}).get("type")),
                                       cost_note="QPU access time billed per D-Wave Leap plan"))
        return out

    def submit_qubo(self, qubo: QUBO, backend: str, num_reads: int, approval_id: Optional[str] = None) -> str:
        self.require_available()
        self._check_approval(True, approval_id)
        from dwave.system import DWaveSampler, EmbeddingComposite
        sampler = EmbeddingComposite(DWaveSampler(solver=backend) if backend else DWaveSampler())
        ss = sampler.sample_qubo(qubo_to_dwave_dict(qubo), num_reads=num_reads)
        counts: Dict[str, int] = {}
        for rec in ss.data(["sample", "num_occurrences"]):
            s = "".join(str(int(rec.sample[v])) for v in qubo.variables)
            counts[s] = counts.get(s, 0) + int(rec.num_occurrences)
        jid = f"dwave-{uuid.uuid4().hex[:12]}"
        self._results[jid] = ProviderJobResult(self.name, backend or "default", jid, "DONE", "qpu_annealer", True,
                                               counts, {"timing": dict(ss.info.get("timing", {}))})
        return jid

    def job_result(self, job_id: str, num_qubits: int, wait: bool = True, timeout=None) -> ProviderJobResult:
        return self._results[job_id]
