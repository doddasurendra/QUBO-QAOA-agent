from __future__ import annotations

from typing import List

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class RoutingInput(BaseModel):
    locations: List[str] = Field(min_length=3, max_length=8, description="location 0 is the depot")
    distance: List[List[float]]

    @model_validator(mode="after")
    def _check(self):
        n = len(self.locations)
        D = np.asarray(self.distance, float)
        if D.shape != (n, n):
            raise ValueError("distance must be n×n")
        if np.any(D < 0):
            raise ValueError("distances must be non-negative")
        return self


class DeliveryRouting(IndustryProblem):
    key = "logistics.delivery_routing"
    industry = "logistics"
    title = "Single-vehicle delivery routing (TSP)"
    description = "Find the shortest closed delivery tour from the depot visiting every location once."
    formulation = ("Depot fixed at position 0; x_{i,t}=1 if location i is visited at step t (i,t ≥ 1)\n"
                   "min  Σ_t Σ_ij d_ij x_{i,t} x_{j,t+1} + Σ_i d_0i x_{i,1} + Σ_i d_i0 x_{i,n-1}\n"
                   "s.t. Σ_i x_{i,t} = 1 ∀t (one-hot) ;  Σ_t x_{i,t} = 1 ∀i")
    limitations = ("(n−1)² qubits: practical for ≤ 5 locations on a simulator. Multi-vehicle CVRP needs "
                   "far more qubits; use classical solvers for realistic sizes.")
    Input = RoutingInput

    def build_model(self, d: RoutingInput) -> Model:
        n = len(d.locations)
        D = d.distance
        m = Model("delivery_routing")
        idx = range(1, n)
        X = {(i, t): m.binary(f"v_{i}_{t}") for i in idx for t in idx}
        obj = quicksum(D[0][i] * X[(i, 1)] + D[i][0] * X[(i, n - 1)] for i in idx)
        obj = obj + quicksum(D[i][j] * X[(i, t)] * X[(j, t + 1)]
                             for t in range(1, n - 1) for i in idx for j in idx if i != j)
        m.minimize(obj)
        for t in idx:
            m.add_one_hot([f"v_{i}_{t}" for i in idx], f"step_{t}")
        for i in idx:
            m.add_constraint(quicksum(X[(i, t)] for t in idx) == 1, f"visit_{i}")
        # same location at consecutive steps is excluded by the constraints; no extra terms needed
        return m

    def interpret(self, d, a):
        n = len(d.locations)
        order = [0]
        ok = True
        for t in range(1, n):
            at = [i for i in range(1, n) if a.get(f"v_{i}_{t}")]
            ok &= len(at) == 1
            order.append(at[0] if at else -1)
        valid = ok and sorted(order) == list(range(n))
        length = sum(d.distance[order[k]][order[(k + 1) % n]] for k in range(n)) if valid else None
        return {"tour": [d.locations[i] if i >= 0 else "?" for i in order] + [d.locations[0]],
                "valid_tour": valid, "tour_length": length}

    def example(self):
        return {"locations": ["Depot", "Store-A", "Store-B", "Store-C"],
                "distance": [[0, 4, 9, 5], [4, 0, 3, 7], [9, 3, 0, 2], [5, 7, 2, 0]]}
