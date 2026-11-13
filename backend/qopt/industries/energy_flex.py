"""Energy: renewable portfolio allocation (generation–demand matching) and demand response scheduling."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


# ----------------------------------------------------------------------------- renewable allocation
class RenewableInput(BaseModel):
    projects: List[str] = Field(min_length=1, max_length=14)
    technology: List[str] = Field(description="e.g. solar / wind / hydro (informational)")
    generation: List[List[int]] = Field(description="project×period expected generation (energy units)")
    cost: List[float] = Field(description="build / contract cost per project")
    periods: List[str] = Field(min_length=1, max_length=12)
    demand: List[int] = Field(description="energy demand per period")
    budget: Optional[int] = Field(default=None, ge=0, description="integer budget in cost units")
    period_weight: Optional[List[float]] = Field(default=None, description="importance of matching in each period")
    cost_weight: float = Field(default=0.0, ge=0, description="λ: trade-off between mismatch and cost")

    @model_validator(mode="after")
    def _check(self):
        J, T = len(self.projects), len(self.periods)
        if len(self.technology) != J or len(self.cost) != J or min(self.cost) < 0:
            raise ValueError("technology and cost: one entry per project (costs non-negative)")
        if len(self.generation) != J or any(len(r) != T for r in self.generation) or \
                min(min(r) for r in self.generation) < 0:
            raise ValueError("generation must be a non-negative projects×periods matrix")
        if len(self.demand) != T or min(self.demand) < 0:
            raise ValueError("one non-negative demand per period")
        if self.period_weight is not None and (len(self.period_weight) != T or min(self.period_weight) < 0):
            raise ValueError("period_weight: one non-negative value per period")
        if self.budget is not None and any(abs(c - round(c)) > 1e-9 for c in self.cost):
            raise ValueError("with a budget, project costs must be integers (same units as the budget)")
        return self

    def w(self, t: int) -> float:
        return self.period_weight[t] if self.period_weight else 1.0


def renewable_objective(d: RenewableInput, chosen: List[int]) -> Optional[float]:
    if d.budget is not None and sum(d.cost[j] for j in chosen) > d.budget:
        return None
    mismatch = sum(d.w(t) * (d.demand[t] - sum(d.generation[j][t] for j in chosen)) ** 2 for t in range(len(d.periods)))
    return mismatch + d.cost_weight * sum(d.cost[j] for j in chosen)


class RenewableAllocation(IndustryProblem):
    key = "energy.renewable_allocation"
    industry = "energy"
    title = "Renewable portfolio allocation (generation–demand matching)"
    description = ("Choose which solar, wind and other renewable projects to build or contract so their combined "
                   "hourly/seasonal generation tracks demand as closely as possible, within a budget. Complementary "
                   "profiles (solar by day, wind by night) are rewarded automatically by the quadratic objective.")
    formulation = ("min  Σ_t w_t (D_t − Σ_j g_jt x_j)² + λ Σ_j c_j x_j\n"
                   "s.t. Σ_j c_j x_j ≤ B   (optional, slack-encoded)\n"
                   "The squared term penalises both shortfall (grid import) and surplus (curtailment).")
    limitations = ("Shortfall and curtailment are penalised symmetrically; generation profiles are deterministic "
                   "forecasts you supply; storage is not modelled here (see battery scheduling).")
    Input = RenewableInput

    def build_model(self, d: RenewableInput) -> Model:
        m = Model("renewable_allocation")
        X = m.binaries([f"proj_{j}" for j in range(len(d.projects))])
        J, T = len(X), len(d.periods)
        mismatch = []
        for t in range(T):
            dev = d.demand[t] - quicksum(d.generation[j][t] * X[j] for j in range(J))
            mismatch.append(d.w(t) * (dev * dev))
        m.minimize(quicksum(mismatch) + d.cost_weight * quicksum(d.cost[j] * X[j] for j in range(J)))
        if d.budget is not None and sum(d.cost) > d.budget:
            m.add_constraint(quicksum(int(round(d.cost[j])) * X[j] for j in range(J)) <= d.budget, "budget")
        return m

    def interpret(self, d: RenewableInput, a):
        chosen = [j for j in range(len(d.projects)) if a[f"proj_{j}"]]
        T = len(d.periods)
        supply = [sum(d.generation[j][t] for j in chosen) for t in range(T)]
        matched = sum(min(s, dm) for s, dm in zip(supply, d.demand))
        spend = sum(d.cost[j] for j in chosen)
        return {"selected_projects": [f"{d.projects[j]} ({d.technology[j]})" for j in chosen],
                "supply": dict(zip(d.periods, supply)),
                "shortfall": {p: max(0, dm - s) for p, s, dm in zip(d.periods, supply, d.demand)},
                "curtailment": {p: max(0, s - dm) for p, s, dm in zip(d.periods, supply, d.demand)},
                "renewable_share_of_demand": round(matched / sum(d.demand), 4) if sum(d.demand) else None,
                "total_cost": spend, "budget_ok": d.budget is None or spend <= d.budget}

    def example(self):
        return {"projects": ["Solar-Rajasthan", "Solar-Gujarat", "Solar-Rooftop", "Wind-TamilNadu", "Wind-Gujarat",
                             "Hydro-RoR"],
                "technology": ["solar", "solar", "solar", "wind", "wind", "hydro"],
                "periods": ["morning", "midday", "evening", "night"],
                "generation": [[2, 4, 1, 0], [1, 3, 1, 0], [1, 2, 0, 0], [1, 1, 3, 3], [2, 1, 2, 2], [1, 1, 1, 1]],
                "demand": [4, 6, 7, 5], "cost": [5, 4, 2, 6, 5, 4], "budget": 16, "cost_weight": 0.1}


# ----------------------------------------------------------------------------- demand response
class FlexLoad(BaseModel):
    name: str
    power: int = Field(ge=1, description="power draw while running (units)")
    duration: int = Field(ge=1, description="consecutive slots it must run")
    earliest_start: int = Field(ge=0)
    latest_end: int = Field(ge=1, description="slot index by which it must have finished (exclusive)")
    preferred_start: Optional[int] = None
    discomfort_cost: float = Field(default=0.0, ge=0, description="cost per slot of deviation from preferred start")


class DemandResponseInput(BaseModel):
    slots: List[str] = Field(min_length=2, max_length=12)
    price: List[float] = Field(description="energy price per unit per slot")
    base_load: List[int] = Field(description="inflexible load per slot (units)")
    loads: List[FlexLoad] = Field(min_length=1, max_length=6)
    event_limit: Optional[List[Optional[int]]] = Field(
        default=None, description="per slot: max total load during a demand-response event (null = no limit)")
    peak_weight: float = Field(default=0.0, ge=0, description="λ on Σ_t (total load_t)² to flatten the peak")

    @model_validator(mode="after")
    def _check(self):
        T = len(self.slots)
        if len(self.price) != T or len(self.base_load) != T or min(self.base_load) < 0:
            raise ValueError("price and base_load: one entry per slot (base load non-negative)")
        for l in self.loads:
            if l.latest_end > T or l.earliest_start + l.duration > l.latest_end:
                raise ValueError(f"load {l.name}: its window cannot fit its duration within the horizon")
            if l.preferred_start is not None and not 0 <= l.preferred_start < T:
                raise ValueError(f"load {l.name}: preferred_start outside the horizon")
        if self.event_limit is not None:
            if len(self.event_limit) != T:
                raise ValueError("event_limit: one entry (or null) per slot")
            for t, lim in enumerate(self.event_limit):
                if lim is not None and lim < self.base_load[t]:
                    raise ValueError(f"slot {self.slots[t]}: base load already exceeds the event limit — infeasible")
        return self

    def starts(self, i: int) -> range:
        l = self.loads[i]
        return range(l.earliest_start, l.latest_end - l.duration + 1)


def dr_profile(d: DemandResponseInput, starts: List[int]) -> List[int]:
    load = list(d.base_load)
    for l, s in zip(d.loads, starts):
        for t in range(s, s + l.duration):
            load[t] += l.power
    return load


def dr_cost(d: DemandResponseInput, starts: List[int]) -> Optional[float]:
    load = dr_profile(d, starts)
    if d.event_limit is not None and any(lim is not None and load[t] > lim for t, lim in enumerate(d.event_limit)):
        return None
    energy = sum(d.price[t] * l.power for l, s in zip(d.loads, starts) for t in range(s, s + l.duration))
    disc = sum(l.discomfort_cost * abs(s - l.preferred_start) for l, s in zip(d.loads, starts)
               if l.preferred_start is not None)
    return energy + disc + d.peak_weight * sum(x * x for x in load)


class DemandResponse(IndustryProblem):
    key = "energy.demand_response"
    industry = "energy"
    title = "Demand response: flexible load scheduling"
    description = ("Schedule flexible loads (EV charging, appliances, pre-cooling, pumping) to cut energy cost, "
                   "flatten the peak and stay under the utility's limits during demand-response events, with a "
                   "comfort cost for moving each load away from its preferred time.")
    formulation = ("s_{l,τ} = 1 iff load l starts at τ (one-hot per load; XY mixer compatible)\n"
                   "L_t = B_t + Σ_l Σ_{τ: τ ≤ t < τ+d_l} p_l s_{l,τ}\n"
                   "min  Σ_l Σ_τ (p_l Σ_{t=τ}^{τ+d_l−1} π_t + κ_l |τ − τ*_l|) s_{l,τ} + λ Σ_t L_t²\n"
                   "s.t. L_t ≤ E_t during event slots (slack-encoded)")
    limitations = ("Loads run uninterrupted at constant power once started; no thermal comfort model beyond the "
                   "start-time deviation cost.")
    Input = DemandResponseInput

    def build_model(self, d: DemandResponseInput) -> Model:
        m = Model("demand_response")
        T = len(d.slots)
        S = {(i, s): m.binary(f"start_{i}_{s}") for i in range(len(d.loads)) for s in d.starts(i)}
        running = {t: [] for t in range(T)}
        lin = []
        for (i, s), x in S.items():
            l = d.loads[i]
            c = l.power * sum(d.price[t] for t in range(s, s + l.duration))
            if l.preferred_start is not None:
                c += l.discomfort_cost * abs(s - l.preferred_start)
            lin.append(c * x)
            for t in range(s, s + l.duration):
                running[t].append(l.power * x)
        L = {t: d.base_load[t] + quicksum(running[t]) for t in range(T)}
        m.minimize(quicksum(lin) + d.peak_weight * quicksum(L[t] * L[t] for t in range(T)))
        for i in range(len(d.loads)):
            m.add_one_hot([f"start_{i}_{s}" for s in d.starts(i)], f"load_{i}")
        if d.event_limit is not None:
            for t, lim in enumerate(d.event_limit):
                if lim is not None and L[t].bounds()[1] > lim:
                    m.add_constraint(L[t] <= lim, f"event_{t}")
        return m

    def interpret(self, d: DemandResponseInput, a):
        starts: List[Optional[int]] = []
        for i in range(len(d.loads)):
            ch = [s for s in d.starts(i) if a.get(f"start_{i}_{s}")]
            starts.append(ch[0] if len(ch) == 1 else None)
        if None in starts:
            return {"one_start_per_load_ok": False}
        load = dr_profile(d, starts)
        events_ok = d.event_limit is None or all(lim is None or load[t] <= lim for t, lim in enumerate(d.event_limit))
        sched: Dict[str, dict] = {l.name: {"start": d.slots[s], "end": d.slots[s + l.duration - 1]}
                                  for l, s in zip(d.loads, starts)}
        energy = sum(d.price[t] * l.power for l, s in zip(d.loads, starts) for t in range(s, s + l.duration))
        return {"schedule": sched, "total_load": dict(zip(d.slots, load)), "peak_load": max(load),
                "flexible_energy_cost": energy, "objective": dr_cost(d, starts),
                "one_start_per_load_ok": True, "event_limits_ok": events_ok}

    def example(self):
        return {"slots": ["16:00", "17:00", "18:00", "19:00", "20:00", "21:00"],
                "price": [6, 8, 12, 12, 9, 5], "base_load": [3, 4, 5, 5, 4, 3],
                "loads": [
                    {"name": "EV charger", "power": 2, "duration": 2, "earliest_start": 0, "latest_end": 5,
                     "preferred_start": 2, "discomfort_cost": 1.0},
                    {"name": "dishwasher", "power": 1, "duration": 2, "earliest_start": 1, "latest_end": 6,
                     "preferred_start": 3, "discomfort_cost": 0.5},
                    {"name": "AC pre-cooling", "power": 2, "duration": 1, "earliest_start": 0, "latest_end": 4,
                     "preferred_start": 2, "discomfort_cost": 2.0},
                    {"name": "water heater", "power": 1, "duration": 1, "earliest_start": 0, "latest_end": 6}],
                "event_limit": [None, None, 7, 7, None, None], "peak_weight": 0.2}
