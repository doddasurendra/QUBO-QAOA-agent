from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class NurseInput(BaseModel):
    staff: List[str] = Field(min_length=1, max_length=30)
    shifts: List[str] = Field(min_length=1, max_length=30)
    demand: List[int] = Field(description="required staff count per shift")
    max_shifts: List[int] = Field(description="maximum shifts per staff member")
    unavailable: List[Tuple[int, int]] = Field(default_factory=list, description="(staff, shift) pairs not allowed")
    preference_cost: Optional[List[List[float]]] = Field(default=None, description="staff×shift cost (lower=preferred)")
    conflicting_shifts: List[Tuple[int, int]] = Field(default_factory=list,
                                                      description="shift pairs one person may not both work (e.g. night→morning)")

    @model_validator(mode="after")
    def _check(self):
        S, N = len(self.shifts), len(self.staff)
        if len(self.demand) != S or len(self.max_shifts) != N:
            raise ValueError("demand per shift and max_shifts per staff member required")
        if self.preference_cost is not None and (len(self.preference_cost) != N or any(len(r) != S for r in self.preference_cost)):
            raise ValueError("preference_cost must be staff×shift")
        if any(d < 0 for d in self.demand) or any(m < 0 for m in self.max_shifts):
            raise ValueError("demand and max_shifts must be non-negative")
        for n, s in self.unavailable:
            if not (0 <= n < N and 0 <= s < S):
                raise ValueError("unavailable index out of range")
        return self


class NurseScheduling(IndustryProblem):
    key = "healthcare.staff_scheduling"
    industry = "healthcare"
    title = "Doctor / nurse shift scheduling"
    description = "Assign staff to shifts meeting exact coverage, per-person limits, availability and rest rules."
    formulation = ("min  Σ_ns c_ns x_ns\n"
                   "s.t. Σ_n x_ns = d_s           ∀ shifts s (coverage)\n"
                   "     Σ_s x_ns ≤ m_n           ∀ staff n (workload, slack-encoded)\n"
                   "     x_ns · x_nt = 0          ∀ conflicting (s,t)  (rest rule)\n"
                   "     x_ns = 0 (not created)   if unavailable")
    Input = NurseInput

    def _vars(self, d: NurseInput) -> Dict[Tuple[int, int], str]:
        un = {tuple(p) for p in d.unavailable}
        return {(n, s): f"x_{n}_{s}" for n in range(len(d.staff)) for s in range(len(d.shifts)) if (n, s) not in un}

    def build_model(self, d: NurseInput) -> Model:
        m = Model("staff_scheduling")
        V = self._vars(d)
        X = {k: m.binary(v) for k, v in V.items()}
        cost = d.preference_cost
        m.minimize(quicksum((cost[n][s] if cost else 0.0) * x for (n, s), x in X.items()))
        for s in range(len(d.shifts)):
            col = [X[(n, s)] for n in range(len(d.staff)) if (n, s) in X]
            if len(col) < d.demand[s]:
                raise ValueError(f"shift {d.shifts[s]!r} needs {d.demand[s]} staff but only {len(col)} are available")
            m.add_constraint(quicksum(col) == d.demand[s], f"cover_{s}")
        for n in range(len(d.staff)):
            row = [X[(n, s)] for s in range(len(d.shifts)) if (n, s) in X]
            if row and d.max_shifts[n] < len(row):
                m.add_constraint(quicksum(row) <= d.max_shifts[n], f"max_{n}")
            for s, t in d.conflicting_shifts:
                if (n, s) in X and (n, t) in X:
                    m.add_constraint(X[(n, s)] * X[(n, t)] == 0, f"rest_{n}_{s}_{t}")
        return m

    def interpret(self, d: NurseInput, a):
        V = self._vars(d)
        roster = {sh: [] for sh in d.shifts}
        for (n, s), v in V.items():
            if a.get(v):
                roster[d.shifts[s]].append(d.staff[n])
        load = {st: sum(1 for (n, s), v in V.items() if n == i and a.get(v)) for i, st in enumerate(d.staff)}
        return {"roster": roster, "shifts_per_staff": load,
                "coverage_ok": all(len(roster[sh]) == d.demand[i] for i, sh in enumerate(d.shifts)),
                "workload_ok": all(load[st] <= d.max_shifts[i] for i, st in enumerate(d.staff))}

    def example(self):
        return {"staff": ["Asha", "Ben", "Chen", "Divya"], "shifts": ["Mon-Day", "Mon-Night", "Tue-Day"],
                "demand": [2, 1, 2], "max_shifts": [2, 2, 1, 2], "unavailable": [[2, 1]],
                "preference_cost": [[1, 3, 1], [2, 1, 2], [1, 0, 3], [3, 2, 1]],
                "conflicting_shifts": [[1, 2]]}
