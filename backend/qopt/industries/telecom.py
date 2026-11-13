from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class BaseStationInput(BaseModel):
    users: List[str] = Field(min_length=1, max_length=25, description="users / traffic clusters")
    stations: List[str] = Field(min_length=1, max_length=10)
    demand: List[int] = Field(description="integer traffic units per user")
    capacity: List[int] = Field(description="integer capacity units per station")
    link_cost: List[List[float]] = Field(description="user×station cost (e.g. path loss / latency)")
    congestion_weight: float = Field(default=0.1, ge=0, description="weight on Σ_s load_s² (congestion)")

    @model_validator(mode="after")
    def _check(self):
        U, S = len(self.users), len(self.stations)
        if len(self.demand) != U or len(self.capacity) != S:
            raise ValueError("demand per user and capacity per station required")
        if len(self.link_cost) != U or any(len(r) != S for r in self.link_cost):
            raise ValueError("link_cost must be users×stations")
        if sum(self.demand) > sum(self.capacity):
            raise ValueError("total demand exceeds total capacity — problem is infeasible")
        return self


class BaseStationAssignment(IndustryProblem):
    key = "telecom.base_station_assignment"
    industry = "telecommunications"
    title = "5G/6G user-to-base-station assignment with congestion control"
    description = "Assign each user (or traffic cluster) to exactly one station, respecting capacity and spreading load."
    formulation = ("min  Σ_us c_us x_us + λ Σ_s (Σ_u w_u x_us)²\n"
                   "s.t. Σ_s x_us = 1        ∀ users (one-hot)\n"
                   "     Σ_u w_u x_us ≤ C_s  ∀ stations (slack-encoded)")
    Input = BaseStationInput

    def build_model(self, d: BaseStationInput) -> Model:
        m = Model("base_station_assignment")
        U, S = len(d.users), len(d.stations)
        X = [[m.binary(f"a_{u}_{s}") for s in range(S)] for u in range(U)]
        link = quicksum(d.link_cost[u][s] * X[u][s] for u in range(U) for s in range(S))
        loads = [quicksum(d.demand[u] * X[u][s] for u in range(U)) for s in range(S)]
        m.minimize(link + d.congestion_weight * quicksum(l * l for l in loads))
        for u in range(U):
            m.add_one_hot([f"a_{u}_{s}" for s in range(S)], f"assign_{u}")
        for s in range(S):
            if sum(d.demand) > d.capacity[s]:
                m.add_constraint(loads[s] <= d.capacity[s], f"cap_{s}")
        return m

    def interpret(self, d, a):
        U, S = len(d.users), len(d.stations)
        assign = {d.users[u]: [d.stations[s] for s in range(S) if a[f"a_{u}_{s}"]] for u in range(U)}
        load = {d.stations[s]: sum(d.demand[u] for u in range(U) if a[f"a_{u}_{s}"]) for s in range(S)}
        return {"assignment": assign, "station_load": load,
                "capacity_ok": all(load[d.stations[s]] <= d.capacity[s] for s in range(S)),
                "each_user_assigned_once": all(len(v) == 1 for v in assign.values()),
                "max_utilisation": max(load[d.stations[s]] / d.capacity[s] for s in range(S) if d.capacity[s])}

    def example(self):
        return {"users": ["cluster-A", "cluster-B", "cluster-C", "cluster-D"],
                "stations": ["gNB-1", "gNB-2", "gNB-3"],
                "demand": [2, 1, 2, 1], "capacity": [3, 3, 2],
                "link_cost": [[1.0, 2.5, 3.0], [2.0, 1.0, 2.0], [1.5, 1.2, 2.5], [3.0, 2.0, 1.0]],
                "congestion_weight": 0.2}
