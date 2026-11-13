"""Healthcare: clinical-trial site selection, compound subset selection (drug discovery), operating-room scheduling."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


# ----------------------------------------------------------------------------- clinical trial sites
class TrialInput(BaseModel):
    sites: List[str] = Field(min_length=2, max_length=16)
    cost: List[float] = Field(description="activation + running cost per site")
    expected_enrollment: List[int] = Field(description="patients each site is expected to enrol")
    region: List[str]
    target_enrollment: int = Field(gt=0)
    required_regions: List[str] = []
    max_sites: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self):
        n = len(self.sites)
        if len(self.cost) != n or len(self.expected_enrollment) != n or len(self.region) != n:
            raise ValueError("cost, expected_enrollment and region need one entry per site")
        if any(c < 0 for c in self.cost) or any(e < 0 for e in self.expected_enrollment):
            raise ValueError("costs and enrolments must be non-negative")
        if sum(self.expected_enrollment) < self.target_enrollment:
            raise ValueError("all sites together cannot reach the enrolment target — infeasible")
        missing = set(self.required_regions) - set(self.region)
        if missing:
            raise ValueError(f"no site in required region(s) {sorted(missing)}")
        return self


class ClinicalTrialSites(IndustryProblem):
    key = "healthcare.clinical_trial_sites"
    industry = "healthcare"
    title = "Clinical-trial site selection"
    description = ("Choose trial sites that reach the enrolment target at minimum cost while covering every required "
                   "region, optionally capping the number of sites.")
    formulation = ("min  Σ_i c_i x_i\n"
                   "s.t. Σ_i e_i x_i ≥ N            (enrolment, slack-encoded)\n"
                   "     Σ_{i∈r} x_i ≥ 1            ∀ required regions r\n"
                   "     Σ_i x_i ≤ S_max            (optional)")
    limitations = "Expected enrolment is treated as deterministic; enrolment uncertainty is not modelled."
    Input = TrialInput

    def build_model(self, d: TrialInput) -> Model:
        m = Model("clinical_trial_sites")
        xs = m.binaries([f"site_{i}" for i in range(len(d.sites))])
        m.minimize(quicksum(c * x for c, x in zip(d.cost, xs)))
        m.add_constraint(quicksum(e * x for e, x in zip(d.expected_enrollment, xs)) >= d.target_enrollment,
                         "enrolment")
        for r in sorted(set(d.required_regions)):
            m.add_constraint(quicksum(x for x, rg in zip(xs, d.region) if rg == r) >= 1, f"region_{r}")
        if d.max_sites is not None and d.max_sites < len(xs):
            m.add_constraint(quicksum(xs) <= d.max_sites, "max_sites")
        return m

    def interpret(self, d: TrialInput, a):
        sel = [i for i in range(len(d.sites)) if a[f"site_{i}"]]
        enrol = sum(d.expected_enrollment[i] for i in sel)
        covered = {d.region[i] for i in sel}
        return {"selected_sites": [d.sites[i] for i in sel], "total_cost": float(sum(d.cost[i] for i in sel)),
                "expected_enrollment": enrol, "target": d.target_enrollment, "enrollment_ok": enrol >= d.target_enrollment,
                "regions_covered": sorted(covered), "regions_ok": set(d.required_regions) <= covered,
                "site_cap_ok": d.max_sites is None or len(sel) <= d.max_sites}

    def example(self):
        return {"sites": ["Delhi-1", "Delhi-2", "Chennai-1", "Chennai-2", "Kolkata-1", "Kolkata-2", "Mumbai-1", "Mumbai-2"],
                "cost": [120, 95, 150, 80, 110, 70, 130, 90],
                "expected_enrollment": [40, 30, 55, 20, 35, 15, 50, 25],
                "region": ["north", "north", "south", "south", "east", "east", "west", "west"],
                "target_enrollment": 120, "required_regions": ["north", "south", "east"], "max_sites": 4}


# ----------------------------------------------------------------------------- compound selection
class CompoundInput(BaseModel):
    compounds: List[str] = Field(min_length=2, max_length=20)
    activity: List[float] = Field(description="predicted activity / docking score (higher is better)")
    similarity: List[List[float]] = Field(description="pairwise structural similarity in [0,1] (e.g. Tanimoto)")
    num_select: int = Field(ge=1)
    diversity_weight: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def _check(self):
        n = len(self.compounds)
        if len(self.activity) != n:
            raise ValueError("one activity score per compound")
        S = np.asarray(self.similarity, float)
        if S.shape != (n, n) or not np.allclose(S, S.T) or S.min() < 0 or S.max() > 1:
            raise ValueError("similarity must be a symmetric n×n matrix with entries in [0, 1]")
        if self.num_select > n:
            raise ValueError("num_select exceeds the number of compounds")
        return self


class CompoundSelection(IndustryProblem):
    key = "healthcare.compound_selection"
    industry = "healthcare"
    title = "Drug-discovery screening subset (active + diverse)"
    description = ("Pick K candidate compounds for the next assay round that have high predicted activity and low "
                   "mutual structural similarity (research-stage use).")
    formulation = ("min  −Σ_i a_i x_i + λ Σ_{i<j} s_ij x_i x_j\n"
                   "s.t. Σ_i x_i = K")
    limitations = ("Selection only: activity scores and similarities must come from your own models / "
                   "cheminformatics pipeline. No molecular simulation or docking is performed.")
    Input = CompoundInput

    def build_model(self, d: CompoundInput) -> Model:
        m = Model("compound_selection")
        xs = m.binaries([f"c_{i}" for i in range(len(d.compounds))])
        n = len(xs)
        m.minimize(-quicksum(d.activity[i] * xs[i] for i in range(n))
                   + d.diversity_weight * quicksum(d.similarity[i][j] * xs[i] * xs[j]
                                                   for i in range(n) for j in range(i + 1, n)))
        m.add_constraint(quicksum(xs) == d.num_select, "select_k")
        return m

    def interpret(self, d: CompoundInput, a):
        sel = [i for i in range(len(d.compounds)) if a[f"c_{i}"]]
        pairs = [d.similarity[i][j] for k, i in enumerate(sel) for j in sel[k + 1:]]
        return {"selected": [d.compounds[i] for i in sel], "total_activity": float(sum(d.activity[i] for i in sel)),
                "max_pairwise_similarity": float(max(pairs)) if pairs else 0.0,
                "count_ok": len(sel) == d.num_select}

    def example(self):
        cluster = [0, 0, 1, 2, 1, 3, 2, 3]
        sim = [[1.0 if i == j else (0.85 if cluster[i] == cluster[j] else 0.2) for j in range(8)] for i in range(8)]
        return {"compounds": [f"CMPD-{k:03d}" for k in range(1, 9)],
                "activity": [0.82, 0.79, 0.65, 0.91, 0.55, 0.70, 0.88, 0.60],
                "similarity": sim, "num_select": 3, "diversity_weight": 1.0}


# ----------------------------------------------------------------------------- operating rooms
class ORSlot(BaseModel):
    room: str
    day: str


class ORInput(BaseModel):
    surgeries: List[str] = Field(min_length=1, max_length=8)
    duration_blocks: List[int] = Field(description="duration in schedule blocks (e.g. 1 block = 1 hour)")
    surgeon: List[str]
    slots: List[ORSlot] = Field(min_length=1, max_length=8)
    slot_capacity_blocks: int = Field(ge=1)
    surgeon_daily_max_blocks: int = Field(ge=1)
    preference_cost: Optional[List[List[float]]] = Field(default=None, description="surgery×slot cost")

    @model_validator(mode="after")
    def _check(self):
        n, s = len(self.surgeries), len(self.slots)
        if len(self.duration_blocks) != n or len(self.surgeon) != n:
            raise ValueError("duration_blocks and surgeon need one entry per surgery")
        if any(not 1 <= b <= min(self.slot_capacity_blocks, self.surgeon_daily_max_blocks) for b in self.duration_blocks):
            raise ValueError("every surgery must fit within one slot and the surgeon daily limit")
        if self.preference_cost is not None and (len(self.preference_cost) != n or any(len(r) != s for r in self.preference_cost)):
            raise ValueError("preference_cost must be surgeries×slots")
        if sum(self.duration_blocks) > s * self.slot_capacity_blocks:
            raise ValueError("total surgery time exceeds total room capacity — infeasible")
        return self


class OperatingRoomScheduling(IndustryProblem):
    key = "healthcare.operating_room_scheduling"
    industry = "healthcare"
    title = "Operating-room (hospital resource) scheduling"
    description = "Assign surgeries to room-day slots within room capacity and per-surgeon daily workload limits."
    formulation = ("min  Σ_sk c_sk x_sk\n"
                   "s.t. Σ_k x_sk = 1                          ∀ surgeries\n"
                   "     Σ_s d_s x_sk ≤ C                      ∀ room-day slots\n"
                   "     Σ_{s∈surgeon} Σ_{k∈day} d_s x_sk ≤ M  ∀ surgeon, day")
    limitations = "Sequencing within a slot, anaesthesia/staff and equipment constraints are not modelled."
    Input = ORInput

    def build_model(self, d: ORInput) -> Model:
        m = Model("operating_room_scheduling")
        S, K = len(d.surgeries), len(d.slots)
        X = {(s, k): m.binary(f"or_{s}_{k}") for s in range(S) for k in range(K)}
        pc = d.preference_cost
        m.minimize(quicksum((pc[s][k] if pc else 0.0) * x for (s, k), x in X.items()))
        for s in range(S):
            m.add_one_hot([f"or_{s}_{k}" for k in range(K)], f"surgery_{s}")
        for k in range(K):
            if sum(d.duration_blocks) > d.slot_capacity_blocks:
                m.add_constraint(quicksum(d.duration_blocks[s] * X[(s, k)] for s in range(S)) <= d.slot_capacity_blocks,
                                 f"room_{k}")
        days = sorted({sl.day for sl in d.slots})
        for doc in sorted(set(d.surgeon)):
            mine = [s for s in range(S) if d.surgeon[s] == doc]
            if sum(d.duration_blocks[s] for s in mine) <= d.surgeon_daily_max_blocks:
                continue
            for di, day in enumerate(days):
                terms = [d.duration_blocks[s] * X[(s, k)] for s in mine for k in range(K) if d.slots[k].day == day]
                m.add_constraint(quicksum(terms) <= d.surgeon_daily_max_blocks, f"surgeon_{doc}_{di}".replace(" ", "_"))
        return m

    def interpret(self, d: ORInput, a):
        plan: Dict[str, List[str]] = {f"{sl.room}/{sl.day}": [] for sl in d.slots}
        per_doc_day: Dict[tuple, int] = {}
        cost, assigned = 0.0, {}
        for s in range(len(d.surgeries)):
            for k, sl in enumerate(d.slots):
                if a.get(f"or_{s}_{k}"):
                    plan[f"{sl.room}/{sl.day}"].append(d.surgeries[s])
                    per_doc_day[(d.surgeon[s], sl.day)] = per_doc_day.get((d.surgeon[s], sl.day), 0) + d.duration_blocks[s]
                    cost += d.preference_cost[s][k] if d.preference_cost else 0.0
                    assigned[s] = assigned.get(s, 0) + 1
        load = {key: sum(d.duration_blocks[d.surgeries.index(x)] for x in v) for key, v in plan.items()}
        return {"plan": plan, "slot_load_blocks": load, "preference_cost": cost,
                "capacity_ok": all(v <= d.slot_capacity_blocks for v in load.values()),
                "surgeon_ok": all(v <= d.surgeon_daily_max_blocks for v in per_doc_day.values()),
                "each_scheduled_once_ok": all(assigned.get(s) == 1 for s in range(len(d.surgeries)))}

    def example(self):
        return {"surgeries": ["hip-replacement", "knee-arthroscopy", "appendectomy", "cataract"],
                "duration_blocks": [3, 2, 2, 1], "surgeon": ["Dr A", "Dr A", "Dr B", "Dr B"],
                "slots": [{"room": "OR1", "day": "Mon"}, {"room": "OR2", "day": "Mon"},
                          {"room": "OR1", "day": "Tue"}, {"room": "OR2", "day": "Tue"}],
                "slot_capacity_blocks": 4, "surgeon_daily_max_blocks": 3,
                "preference_cost": [[0, 1, 2, 3], [1, 0, 3, 2], [0, 0, 1, 1], [2, 1, 0, 0]]}
