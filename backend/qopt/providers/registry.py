"""Provider registry. Unsupported-but-requested providers are listed with an honest status."""
from __future__ import annotations

from typing import Dict, List

from .aer import AerProvider
from .base import Provider
from .braket import BraketProvider
from .dwave import DWaveProvider
from .ibm import IBMRuntimeProvider

# Providers reachable through another integration, or not yet integrated.
INDIRECT = [
    {"name": "ionq", "via": "aws_braket", "note": "IonQ QPUs are available as Braket devices (device ARN)."},
    {"name": "rigetti", "via": "aws_braket", "note": "Rigetti QPUs are available as Braket devices."},
    {"name": "iqm", "via": "aws_braket", "note": "IQM QPUs are available as Braket devices (region-dependent)."},
    {"name": "quantinuum", "via": None,
     "note": "Not integrated: requires Azure Quantum (azure-quantum SDK) or Quantinuum's own API access. "
             "Implement a Provider subclass once access is available."},
    {"name": "azure_quantum", "via": None,
     "note": "Not integrated: requires an Azure subscription + workspace and the azure-quantum SDK."},
]


class ProviderRegistry:
    def __init__(self):
        self._providers: Dict[str, Provider] = {}
        for p in (AerProvider(), IBMRuntimeProvider(), BraketProvider(), DWaveProvider()):
            self.register(p)

    def register(self, p: Provider):
        self._providers[p.name] = p

    def get(self, name: str) -> Provider:
        if name not in self._providers:
            raise KeyError(f"unknown provider {name!r}; registered: {sorted(self._providers)}")
        return self._providers[name]

    def names(self) -> List[str]:
        return sorted(self._providers)

    def status(self) -> List[dict]:
        out = [{"name": "local_statevector", "technology": "gate", "sdk_installed": True,
                "credentials_configured": True, "available": True, "missing_credentials": [],
                "note": "built-in exact NumPy statevector simulator (≤22 qubits)"}]
        out += [p.status() for p in self._providers.values()]
        out += [{**i, "available": False, "indirect": True} for i in INDIRECT]
        return out


registry = ProviderRegistry()
