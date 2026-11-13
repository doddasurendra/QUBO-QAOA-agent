"""Safe QUBO preprocessing: variable fixing by provable first-order dominance.

Rule (exact, never changes the optimum value): for variable i with linear coefficient a_i,
  * if a_i + Σ_j min(0, b_ij) ≥ 0 then x_i = 0 in *some* optimal solution
    (setting x_i=1 can never decrease energy),
  * if a_i + Σ_j max(0, b_ij) ≤ 0 then x_i = 1 in some optimal solution.
Strict inequalities make the fix hold for *every* optimum; we use non-strict (keeps one optimum).
Fixing is iterated until no rule fires. The reduced QUBO plus the fixed values reconstructs
full solutions with identical energy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

from .qubo import QUBO


@dataclass
class Reduction:
    reduced: QUBO
    fixed: Dict[int, int]          # original index -> value
    kept: List[int]                # reduced index k -> original index kept[k]
    original_n: int

    def expand(self, x_reduced) -> np.ndarray:
        x = np.zeros(self.original_n, dtype=int)
        for i, v in self.fixed.items():
            x[i] = v
        for k, i in enumerate(self.kept):
            x[i] = int(x_reduced[k])
        return x

    def to_dict(self) -> dict:
        return {"original_variables": self.original_n, "fixed": {str(k): v for k, v in self.fixed.items()},
                "remaining_variables": len(self.kept)}


def reduce_qubo(q: QUBO, max_rounds: int = 100) -> Reduction:
    n = q.num_variables
    lin = {i: q.linear.get(i, 0.0) for i in range(n)}
    quad = dict(q.quadratic)
    offset = q.offset
    fixed: Dict[int, int] = {}
    for _ in range(max_rounds):
        changed = False
        neg = {i: 0.0 for i in lin}
        pos = {i: 0.0 for i in lin}
        for (i, j), c in quad.items():
            (neg if c < 0 else pos)[i] += c
            (neg if c < 0 else pos)[j] += c
        for i in list(lin):
            val = None
            if lin[i] + neg[i] >= 0:
                val = 0
            elif lin[i] + pos[i] <= 0:
                val = 1
            if val is None:
                continue
            fixed[i] = val
            a = lin.pop(i)
            if val == 1:
                offset += a
            for (u, v) in [k for k in quad if i in k]:
                c = quad.pop((u, v))
                other = v if u == i else u
                if val == 1 and other in lin:
                    lin[other] += c
            changed = True
            break  # recompute neighbourhood sums after each fix
        if not changed:
            break
    kept = sorted(lin)
    remap = {i: k for k, i in enumerate(kept)}
    red = QUBO([q.variables[i] for i in kept],
               {remap[i]: c for i, c in lin.items() if c != 0},
               {(remap[i], remap[j]): c for (i, j), c in quad.items()}, offset)
    return Reduction(red, fixed, kept, n)
