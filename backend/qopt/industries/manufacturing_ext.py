"""Manufacturing: time-indexed job-shop scheduling (Venturelli, Marchand & Rojo, 2015 style)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


class Operation(BaseModel):
    machine: int = Field(ge=0)
    duration: int = Field(ge=1)


class Job(BaseModel):
    name: str
    operations: List[Operation] = Field(min_length=1, max_length=4)


class JobShopInput(BaseModel):
    machines: List[str] = Field(min_length=1, max_length=4)
    jobs: List[Job] = Field(min_length=1, max_length=4)
    horizon: int = Field(ge=1, le=16, description="number of discrete time steps")
    weights: Optional[List[float]] = Field(default=None, description="job priority weights")

    @model_validator(mode="after")
    def _check(self):
        for j in self.jobs:
            if any(o.machine >= len(self.machines) for o in j.operations):
                raise ValueError(f"job {j.name}: machine index out of range")
            if sum(o.duration for o in j.operations) > self.horizon:
                raise ValueError(f"job {j.name} cannot finish within the horizon")
        if self.weights is not None and (len(self.weights) != len(self.jobs) or min(self.weights) < 0):
            raise ValueError("one non-negative weight per job")
        nvars = sum(len(self.window(j, k)) for j in range(len(self.jobs)) for k in range(len(self.jobs[j].operations)))
        if nvars > 80:
            raise ValueError(f"{nvars} start-time variables; reduce the horizon or the number of operations")
        return self

    def window(self, j: int, k: int) -> range:
        ops = self.jobs[j].operations
        early = sum(o.duration for o in ops[:k])
        late = self.horizon - sum(o.duration for o in ops[k:])
        return range(early, late + 1)

    def w(self, j: int) -> float:
        return self.weights[j] if self.weights else 1.0


def schedule_ok(d: JobShopInput, start: Dict[Tuple[int, int], int]) -> Tuple[bool, bool]:
    prec = all(start[(j, k + 1)] >= start[(j, k)] + d.jobs[j].operations[k].duration
               for j in range(len(d.jobs)) for k in range(len(d.jobs[j].operations) - 1))
    ops = [(j, k) for j in range(len(d.jobs)) for k in range(len(d.jobs[j].operations))]
    over = True
    for a, (j, k) in enumerate(ops):
        for (j2, k2) in ops[a + 1:]:
            o, o2 = d.jobs[j].operations[k], d.jobs[j2].operations[k2]
            if o.machine == o2.machine:
                s, s2 = start[(j, k)], start[(j2, k2)]
                if s < s2 + o2.duration and s2 < s + o.duration:
                    over = False
    return prec, over


class JobShopScheduling(IndustryProblem):
    key = "manufacturing.job_shop"
    industry = "manufacturing"
    title = "Job-shop scheduling (time-indexed)"
    description = ("Sequence each job's operations on their machines: no two operations overlap on a machine, each "
                   "job's operations run in order, minimising total weighted completion time.")
    formulation = ("x_{o,t} = operation o starts at t (t in its feasible window)\n"
                   "min  Σ_j w_j Σ_t (t + p_last) x_{last(j),t}\n"
                   "s.t. Σ_t x_{o,t} = 1 ∀o ;  x_{o,t} x_{o',t'} = 0 if o,o' share a machine and overlap ;\n"
                   "     x_{o,t} x_{next(o),t'} = 0 if t' < t + p_o  (precedence)")
    limitations = ("Objective is total weighted completion time (not makespan). Qubits grow with operations × "
                   "horizon; practical for small instances only.")
    Input = JobShopInput

    def _ops(self, d):
        return [(j, k) for j in range(len(d.jobs)) for k in range(len(d.jobs[j].operations))]

    def build_model(self, d: JobShopInput) -> Model:
        m = Model("job_shop")
        X = {(j, k, t): m.binary(f"op_{j}_{k}_{t}") for (j, k) in self._ops(d) for t in d.window(j, k)}
        obj = []
        for j, job in enumerate(d.jobs):
            last = len(job.operations) - 1
            p = job.operations[last].duration
            obj += [d.w(j) * (t + p) * X[(j, last, t)] for t in d.window(j, last)]
        m.minimize(quicksum(obj))
        for (j, k) in self._ops(d):
            m.add_one_hot([f"op_{j}_{k}_{t}" for t in d.window(j, k)], f"start_{j}_{k}")
        ops = self._ops(d)
        for a, (j, k) in enumerate(ops):
            o = d.jobs[j].operations[k]
            for (j2, k2) in ops[a + 1:]:
                o2 = d.jobs[j2].operations[k2]
                same_machine = o.machine == o2.machine
                precedes = j == j2 and k2 == k + 1
                if not (same_machine or precedes):
                    continue
                for t in d.window(j, k):
                    for t2 in d.window(j2, k2):
                        bad = (same_machine and t < t2 + o2.duration and t2 < t + o.duration) or \
                              (precedes and t2 < t + o.duration)
                        if bad:
                            m.add_constraint(X[(j, k, t)] * X[(j2, k2, t2)] == 0, f"c_{j}{k}{t}_{j2}{k2}{t2}")
        return m

    def interpret(self, d: JobShopInput, a):
        start, rows = {}, []
        for (j, k) in self._ops(d):
            ts = [t for t in d.window(j, k) if a.get(f"op_{j}_{k}_{t}")]
            if len(ts) != 1:
                return {"one_start_per_operation_ok": False}
            start[(j, k)] = ts[0]
            o = d.jobs[j].operations[k]
            rows.append({"job": d.jobs[j].name, "op": k + 1, "machine": d.machines[o.machine],
                         "start": ts[0], "end": ts[0] + o.duration})
        prec, over = schedule_ok(d, start)
        comp = {d.jobs[j].name: start[(j, len(job.operations) - 1)] + job.operations[-1].duration
                for j, job in enumerate(d.jobs)}
        return {"schedule": sorted(rows, key=lambda r: (r["machine"], r["start"])), "completion": comp,
                "makespan": max(comp.values()),
                "weighted_completion": sum(d.w(j) * comp[job.name] for j, job in enumerate(d.jobs)),
                "one_start_per_operation_ok": True, "precedence_ok": prec, "no_overlap_ok": over}

    def example(self):
        return {"machines": ["lathe", "mill"], "horizon": 5,
                "jobs": [{"name": "shaft", "operations": [{"machine": 0, "duration": 2}, {"machine": 1, "duration": 1}]},
                         {"name": "bracket", "operations": [{"machine": 1, "duration": 2}, {"machine": 0, "duration": 1}]}]}
