"""Energy: unit commitment (power generation) and battery arbitrage scheduling."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


# ----------------------------------------------------------------------------- unit commitment
class UCInput(BaseModel):
    generators: List[str] = Field(min_length=1, max_length=5)
    capacity: List[int] = Field(description="available output when committed (integer MW units)")
    running_cost: List[float] = Field(description="cost per period while committed")
    startup_cost: List[float]
    initially_on: List[bool]
    periods: List[str] = Field(min_length=1, max_length=8)
    demand: List[int] = Field(description="load per period (same units as capacity)")
    reserve: int = Field(default=0, ge=0, description="spinning reserve required on top of demand")

    @model_validator(mode="after")
    def _check(self):
        G, T = len(self.generators), len(self.periods)
        for name, v in (("capacity", self.capacity), ("running_cost", self.running_cost),
                        ("startup_cost", self.startup_cost), ("initially_on", self.initially_on)):
            if len(v) != G:
                raise ValueError(f"{name}: one entry per generator")
        if len(self.demand) != T:
            raise ValueError("one demand value per period")
        if any(c <= 0 for c in self.capacity) or any(x < 0 for x in self.demand):
            raise ValueError("capacities must be positive and demands non-negative")
        if max(self.demand) + self.reserve > sum(self.capacity):
            raise ValueError("peak demand + reserve exceeds total capacity — infeasible")
        return self


def uc_cost(d: UCInput, on) -> float:
    c = 0.0
    for g in range(len(d.generators)):
        prev = d.initially_on[g]
        for t in range(len(d.periods)):
            if on[g][t]:
                c += d.running_cost[g] + (0 if prev else d.startup_cost[g])
            prev = on[g][t]
    return c


class UnitCommitment(IndustryProblem):
    key = "energy.unit_commitment"
    industry = "energy"
    title = "Power generation unit commitment"
    description = ("Decide which generators run in each period so committed capacity covers demand plus reserve, "
                   "minimising running and start-up costs.")
    formulation = ("min  Σ_gt r_g u_gt + Σ_gt s_g u_gt (1 − u_g,t−1)      (u_g,−1 = initial state)\n"
                   "s.t. Σ_g P_g u_gt ≥ D_t + R   ∀ t   (slack-encoded)")
    limitations = ("Commitment only: economic dispatch (continuous output levels), ramp rates and minimum "
                   "up/down times are not modelled; running cost is a per-period figure you supply.")
    Input = UCInput

    def build_model(self, d: UCInput) -> Model:
        m = Model("unit_commitment")
        G, T = len(d.generators), len(d.periods)
        U = [[m.binary(f"u_{g}_{t}") for t in range(T)] for g in range(G)]
        terms = []
        for g in range(G):
            for t in range(T):
                terms.append(d.running_cost[g] * U[g][t])
                if t == 0:
                    if not d.initially_on[g]:
                        terms.append(d.startup_cost[g] * U[g][0])
                else:
                    terms.append(d.startup_cost[g] * (U[g][t] - U[g][t] * U[g][t - 1]))
        m.minimize(quicksum(terms))
        for t in range(T):
            m.add_constraint(quicksum(d.capacity[g] * U[g][t] for g in range(G)) >= d.demand[t] + d.reserve, f"cover_{t}")
        return m

    def interpret(self, d: UCInput, a):
        G, T = len(d.generators), len(d.periods)
        on = [[bool(a[f"u_{g}_{t}"]) for t in range(T)] for g in range(G)]
        cap = [sum(d.capacity[g] for g in range(G) if on[g][t]) for t in range(T)]
        return {"schedule": {d.generators[g]: ["on" if on[g][t] else "off" for t in range(T)] for g in range(G)},
                "committed_capacity": dict(zip(d.periods, cap)), "total_cost": uc_cost(d, on),
                "coverage_ok": all(cap[t] >= d.demand[t] + d.reserve for t in range(T))}

    def example(self):
        return {"generators": ["coal", "gas-ccgt", "gas-peaker"], "capacity": [5, 3, 2],
                "running_cost": [50, 40, 35], "startup_cost": [80, 20, 5], "initially_on": [True, False, False],
                "periods": ["06-10", "10-14", "14-18", "18-22"], "demand": [4, 7, 9, 5], "reserve": 0}


# ----------------------------------------------------------------------------- battery scheduling
class BatteryInput(BaseModel):
    slots: List[str] = Field(min_length=1, max_length=8)
    price: List[float] = Field(description="energy price per unit in each slot")
    capacity_units: int = Field(ge=1, le=6, description="storage capacity in energy units")
    initial_soc: int = Field(ge=0)
    final_soc_min: int = Field(default=0, ge=0)
    max_rate: int = Field(default=1, ge=1, description="max units charged/discharged per slot")
    degradation_cost: float = Field(default=0.0, ge=0, description="cost per unit cycled")

    @model_validator(mode="after")
    def _check(self):
        if len(self.price) != len(self.slots):
            raise ValueError("one price per slot")
        if self.initial_soc > self.capacity_units or self.final_soc_min > self.capacity_units:
            raise ValueError("state of charge values must be within capacity")
        if self.initial_soc + self.max_rate * len(self.slots) < self.final_soc_min:
            raise ValueError("final_soc_min unreachable — infeasible")
        return self

    def levels(self, t: int) -> List[int]:
        """SoC values reachable after slot t (respecting rate limits and the final requirement)."""
        lo, hi = self.initial_soc - self.max_rate * (t + 1), self.initial_soc + self.max_rate * (t + 1)
        T = len(self.slots)
        # must still be able to reach final_soc_min by the end
        lo = max(lo, self.final_soc_min - self.max_rate * (T - 1 - t))
        return [k for k in range(self.capacity_units + 1) if lo <= k <= hi]


def battery_cost(d: BatteryInput, soc: List[int]) -> float:
    c, prev = 0.0, d.initial_soc
    for t, s in enumerate(soc):
        delta = s - prev
        c += d.price[t] * delta + d.degradation_cost * abs(delta)
        prev = s
    return c


class BatteryScheduling(IndustryProblem):
    key = "energy.battery_scheduling"
    industry = "energy"
    title = "Battery arbitrage scheduling"
    description = ("Choose the battery state of charge in each slot to buy energy when cheap and sell when expensive, "
                   "within capacity, rate limits and a final state-of-charge requirement.")
    formulation = ("State encoding: y_{t,k} = 1 iff SoC after slot t is k (one-hot per slot; bounds are built in)\n"
                   "min  Σ_t Σ_{k,k'} (p_t (k'−k) + δ|k'−k|) y_{t−1,k} y_{t,k'}\n"
                   "s.t. Σ_k y_{t,k} = 1 ∀t ;  y_{t−1,k} y_{t,k'} = 0 if |k'−k| > rate ;  k ≥ SoC_min at the end")
    limitations = "Unit-sized energy steps; round-trip efficiency losses are not modelled (use degradation_cost)."
    Input = BatteryInput

    def build_model(self, d: BatteryInput) -> Model:
        m = Model("battery_scheduling")
        T = len(d.slots)
        Y = [{k: m.binary(f"soc_{t}_{k}") for k in d.levels(t)} for t in range(T)]
        terms = []
        for t in range(T):
            prev = {d.initial_soc: None} if t == 0 else Y[t - 1]
            for k, yk in prev.items():
                for k2, y2 in Y[t].items():
                    delta = k2 - k
                    if abs(delta) > d.max_rate:
                        if t > 0:
                            m.add_constraint(yk * y2 == 0, f"rate_{t}_{k}_{k2}")
                        continue
                    c = d.price[t] * delta + d.degradation_cost * abs(delta)
                    if c:   # slot 0 starts from the fixed initial SoC, so its cost term is linear
                        terms.append(c * (y2 if t == 0 else yk * y2))
        m.minimize(quicksum(terms))
        for t in range(T):
            m.add_one_hot([f"soc_{t}_{k}" for k in d.levels(t)], f"slot_{t}")
        return m

    def interpret(self, d: BatteryInput, a):
        soc = []
        for t in range(len(d.slots)):
            ks = [k for k in d.levels(t) if a.get(f"soc_{t}_{k}")]
            soc.append(ks[0] if len(ks) == 1 else None)
        if None in soc:
            return {"state_of_charge": soc, "one_state_per_slot_ok": False}
        prev, actions = d.initial_soc, []
        for s in soc:
            actions.append("charge" if s > prev else "discharge" if s < prev else "idle")
            prev = s
        cost = battery_cost(d, soc)
        return {"state_of_charge": dict(zip(d.slots, soc)), "actions": dict(zip(d.slots, actions)),
                "net_profit": -cost, "one_state_per_slot_ok": True,
                "rate_ok": all(abs(b - a_) <= d.max_rate for a_, b in zip([d.initial_soc] + soc, soc)),
                "final_soc_ok": soc[-1] >= d.final_soc_min}

    def example(self):
        return {"slots": ["00-04", "04-08", "08-12", "12-16", "16-20"], "price": [30, 25, 60, 45, 90],
                "capacity_units": 2, "initial_soc": 1, "final_soc_min": 1, "max_rate": 1, "degradation_cost": 2.0}
