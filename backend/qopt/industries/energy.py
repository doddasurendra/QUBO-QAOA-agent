from __future__ import annotations

from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class EVInput(BaseModel):
    vehicles: List[str] = Field(min_length=1, max_length=20)
    slots: List[str] = Field(min_length=1, max_length=24)
    required_slots: List[int] = Field(description="charging slots each vehicle needs")
    availability: Optional[List[Tuple[int, int]]] = Field(default=None,
                                                           description="per vehicle [first_slot, last_slot] inclusive")
    price: List[float] = Field(description="energy price per slot")
    grid_limit: List[int] = Field(description="max vehicles charging simultaneously per slot")
    peak_weight: float = Field(default=0.0, ge=0, description="weight on Σ_t (load_t)² to flatten peaks")

    @model_validator(mode="after")
    def _check(self):
        V, T = len(self.vehicles), len(self.slots)
        if len(self.required_slots) != V or len(self.price) != T or len(self.grid_limit) != T:
            raise ValueError("required_slots per vehicle; price and grid_limit per slot")
        if self.availability is not None:
            if len(self.availability) != V:
                raise ValueError("availability per vehicle")
            for v, (a, b) in enumerate(self.availability):
                if not (0 <= a <= b < T):
                    raise ValueError(f"bad availability window for vehicle {v}")
                if b - a + 1 < self.required_slots[v]:
                    raise ValueError(f"vehicle {self.vehicles[v]} window too short for its requirement")
        if sum(self.required_slots) > sum(self.grid_limit):
            raise ValueError("total charging requirement exceeds total grid capacity — infeasible")
        return self


class EVCharging(IndustryProblem):
    key = "energy.ev_charging"
    industry = "energy"
    title = "EV charging scheduling under grid limits"
    description = "Schedule vehicle charging slots minimising energy cost and peak load without exceeding grid limits."
    formulation = ("min  Σ_vt p_t x_vt + λ Σ_t (Σ_v x_vt)²\n"
                   "s.t. Σ_t x_vt = r_v       ∀ vehicles (within availability window)\n"
                   "     Σ_v x_vt ≤ G_t       ∀ slots (slack-encoded)")
    limitations = "Each slot is unit power per vehicle; multi-level charging rates need additional bits."
    Input = EVInput

    def _window(self, d, v):
        return range(d.availability[v][0], d.availability[v][1] + 1) if d.availability else range(len(d.slots))

    def build_model(self, d: EVInput) -> Model:
        m = Model("ev_charging")
        V, T = len(d.vehicles), len(d.slots)
        X = {(v, t): m.binary(f"c_{v}_{t}") for v in range(V) for t in self._window(d, v)}
        loads = [quicksum(X[(v, t)] for v in range(V) if (v, t) in X) for t in range(T)]
        m.minimize(quicksum(d.price[t] * x for (v, t), x in X.items()) + d.peak_weight * quicksum(l * l for l in loads))
        for v in range(V):
            m.add_constraint(quicksum(X[(v, t)] for t in self._window(d, v)) == d.required_slots[v], f"need_{v}")
        for t in range(T):
            nv = sum(1 for v in range(V) if (v, t) in X)
            if nv > d.grid_limit[t]:
                m.add_constraint(loads[t] <= d.grid_limit[t], f"grid_{t}")
        return m

    def interpret(self, d, a):
        V, T = len(d.vehicles), len(d.slots)
        sched = {d.vehicles[v]: [d.slots[t] for t in self._window(d, v) if a.get(f"c_{v}_{t}")] for v in range(V)}
        load = [sum(1 for v in range(V) if a.get(f"c_{v}_{t}")) for t in range(T)]
        cost = sum(d.price[t] * load[t] for t in range(T))
        return {"schedule": sched, "load_per_slot": dict(zip(d.slots, load)), "energy_cost": cost,
                "grid_ok": all(load[t] <= d.grid_limit[t] for t in range(T)),
                "requirements_met": all(len(sched[d.vehicles[v]]) == d.required_slots[v] for v in range(V))}

    def example(self):
        return {"vehicles": ["EV1", "EV2", "EV3"], "slots": ["18:00", "19:00", "20:00", "21:00"],
                "required_slots": [2, 1, 2], "availability": [[0, 3], [0, 1], [1, 3]],
                "price": [8.0, 9.5, 6.0, 4.5], "grid_limit": [1, 2, 2, 2], "peak_weight": 0.5}
