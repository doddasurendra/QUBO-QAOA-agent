from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class MachineInput(BaseModel):
    jobs: List[str] = Field(min_length=1, max_length=20)
    machines: List[str] = Field(min_length=2, max_length=6)
    processing_time: List[float] = Field(description="processing time per job")
    eligible: Optional[List[List[int]]] = Field(default=None, description="per job: list of eligible machine indices")

    @model_validator(mode="after")
    def _check(self):
        if len(self.processing_time) != len(self.jobs):
            raise ValueError("processing_time per job required")
        if any(p <= 0 for p in self.processing_time):
            raise ValueError("processing times must be positive")
        if self.eligible is not None:
            if len(self.eligible) != len(self.jobs):
                raise ValueError("eligible per job required")
            for e in self.eligible:
                if not e or any(not 0 <= k < len(self.machines) for k in e):
                    raise ValueError("each job needs ≥1 valid eligible machine")
        return self


class MachineScheduling(IndustryProblem):
    key = "manufacturing.machine_scheduling"
    industry = "manufacturing"
    title = "Parallel machine load balancing (makespan proxy)"
    description = "Assign jobs to eligible parallel machines so the machine loads are balanced."
    formulation = ("min  Σ_m (Σ_j p_j x_jm)²\n"
                   "s.t. Σ_m x_jm = 1  ∀ jobs (one-hot over eligible machines)\n"
                   "Minimising the sum of squared loads is a standard quadratic proxy for makespan.")
    limitations = ("Sum of squared loads is a proxy: its optimum need not minimise the makespan exactly. "
                   "Sequencing / job-shop precedence needs time-indexed encodings (many more qubits).")
    Input = MachineInput

    def _elig(self, d, j):
        return d.eligible[j] if d.eligible else list(range(len(d.machines)))

    def build_model(self, d: MachineInput) -> Model:
        m = Model("machine_scheduling")
        X = {(j, k): m.binary(f"y_{j}_{k}") for j in range(len(d.jobs)) for k in self._elig(d, j)}
        loads = [quicksum(d.processing_time[j] * x for (j, kk), x in X.items() if kk == k) for k in range(len(d.machines))]
        m.minimize(quicksum(l * l for l in loads))
        for j in range(len(d.jobs)):
            names = [f"y_{j}_{k}" for k in self._elig(d, j)]
            if len(names) == 1:
                m.add_constraint(m.var(names[0]) == 1, f"job_{j}")
            else:
                m.add_one_hot(names, f"job_{j}")
        return m

    def interpret(self, d, a):
        plan = {mc: [] for mc in d.machines}
        for j in range(len(d.jobs)):
            for k in self._elig(d, j):
                if a.get(f"y_{j}_{k}"):
                    plan[d.machines[k]].append(d.jobs[j])
        loads = {mc: sum(d.processing_time[d.jobs.index(job)] for job in js) for mc, js in plan.items()}
        return {"plan": plan, "machine_load": loads, "makespan": max(loads.values()),
                "lower_bound": max(sum(d.processing_time) / len(d.machines), max(d.processing_time)),
                "all_jobs_assigned_once": sum(len(v) for v in plan.values()) == len(d.jobs)}

    def example(self):
        return {"jobs": ["J1", "J2", "J3", "J4", "J5"], "machines": ["CNC-1", "CNC-2"],
                "processing_time": [3, 2, 2, 4, 1], "eligible": [[0, 1], [0, 1], [0], [0, 1], [1]]}
