from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.qubo import QUBO


@dataclass
class Sample:
    x: np.ndarray
    energy: float
    count: int = 1

    def bitstring(self) -> str:
        return "".join(str(int(b)) for b in self.x)


@dataclass
class SolverResult:
    solver: str
    execution_kind: str            # see docs/ARCHITECTURE.md §4
    is_real_hardware: bool
    best_x: np.ndarray
    best_energy: float
    samples: List[Sample]
    runtime_s: float
    optimal: Optional[bool] = None  # True only when the solver *proves* optimality
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, max_samples: int = 20) -> dict:
        return {
            "solver": self.solver,
            "execution_kind": self.execution_kind,
            "is_real_hardware": self.is_real_hardware,
            "best_bitstring": "".join(str(int(b)) for b in self.best_x),
            "bit_order": "QUBO variable order (index 0 first)",
            "best_energy": self.best_energy,
            "proven_optimal": self.optimal,
            "runtime_s": self.runtime_s,
            "num_unique_samples": len(self.samples),
            "samples": [{"bitstring": s.bitstring(), "energy": s.energy, "count": s.count}
                        for s in self.samples[:max_samples]],
            "metadata": self.metadata,
        }


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.elapsed = time.perf_counter() - self.t0


def aggregate(qubo: QUBO, X: np.ndarray) -> List[Sample]:
    """Unique samples with counts, sorted by energy (energies recomputed from the QUBO)."""
    X = np.asarray(X, dtype=np.int8)
    uniq, counts = np.unique(X, axis=0, return_counts=True)
    E = qubo.energies(uniq)
    order = np.argsort(E, kind="stable")
    return [Sample(uniq[k].astype(int), float(E[k]), int(counts[k])) for k in order]


def dense_parts(qubo: QUBO):
    """Return (a, W) with W symmetric zero-diagonal so E = offset + a·x + ½ xᵀWx."""
    a = qubo.linear_vector()
    B = qubo.strict_upper()
    W = B + B.T
    return a, W
