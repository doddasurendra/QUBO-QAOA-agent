"""The ONLY place where hardware/Qiskit bit ordering is converted.

Qiskit count keys are big-endian strings: ``key[-1 - i]`` is the bit of qubit/clbit ``i``.
Platform assignment strings are in variable order: ``s[i]`` is variable ``i``.
"""
from __future__ import annotations

from typing import Dict

import numpy as np


def qiskit_key_to_assignment(key: str, n: int) -> str:
    key = key.replace(" ", "")
    if len(key) != n:
        raise ValueError(f"count key {key!r} does not have {n} bits")
    return key[::-1]


def index_to_assignment(k: int, n: int) -> str:
    return "".join(str((k >> i) & 1) for i in range(n))


def assignment_to_index(s: str) -> int:
    return int(s[::-1], 2) if s else 0


def assignment_to_array(s: str) -> np.ndarray:
    return np.array([int(c) for c in s], dtype=int)


def counts_from_qiskit(counts: Dict[str, int], n: int) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for k, v in counts.items():
        a = qiskit_key_to_assignment(k, n)
        out[a] = out.get(a, 0) + int(v)
    return out
