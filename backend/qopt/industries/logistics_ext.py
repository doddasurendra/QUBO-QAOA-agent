"""Logistics: capacitated vehicle routing (cluster-first), cargo loading (multiple knapsack), warehouse dock scheduling."""
from __future__ import annotations

import itertools
import math
from typing import List

from pydantic import BaseModel, Field, model_validator

from ..core.expr import quicksum
from ..core.model import Model
from .base import IndustryProblem


def best_tour(dist, stops: List[int]):
    """Exact shortest closed tour depot → stops → depot by enumeration (stops ≤ 8)."""
    if not stops:
        return [0, 0], 0.0
    best = None
    for perm in itertools.permutations(stops):
        route = [0, *perm, 0]
        L = sum(dist[route[k]][route[k + 1]] for k in range(len(route) - 1))
        if best is None or L < best[1] - 1e-12:
            best = (route, L)
    return best


# ----------------------------------------------------------------------------- CVRP
class VRPInput(BaseModel):
    locations: List[str] = Field(min_length=3, max_length=9, description="index 0 is the depot")
    distance: List[List[float]]
    demand: List[int] = Field(description="per location; depot must be 0")
    num_vehicles: int = Field(ge=2, le=3)
    vehicle_capacity: int = Field(ge=1)

    @model_validator(mode="after")
    def _check(self):
        n = len(self.locations)
        if len(self.distance) != n or any(len(r) != n for r in self.distance) or any(v < 0 for r in self.distance for v in r):
            raise ValueError("distance must be a non-negative n×n matrix")
        if len(self.demand) != n or self.demand[0] != 0 or any(q < 0 for q in self.demand):
            raise ValueError("demand: one non-negative value per location, 0 for the depot")
        if max(self.demand) > self.vehicle_capacity:
            raise ValueError("a customer's demand exceeds the vehicle capacity")
        if sum(self.demand) > self.num_vehicles * self.vehicle_capacity:
            raise ValueError("total demand exceeds fleet capacity — infeasible")
        return self


class VehicleRouting(IndustryProblem):
    key = "logistics.vehicle_routing"
    industry = "logistics"
    title = "Capacitated vehicle routing (cluster-first, route-second)"
    description = ("Assign customers to vehicles within capacity using a QUBO clustering objective, then compute the "
                   "exact shortest route for each vehicle.")
    formulation = ("Stage 1 (QUBO): x_cv = customer c on vehicle v\n"
                   "min  Σ_v Σ_{c<c'} d_cc' x_cv x_c'v + Σ_cv ½(d_0c + d_c0) x_cv\n"
                   "s.t. Σ_v x_cv = 1 ∀c ;  Σ_c q_c x_cv ≤ Q ∀v ;  customer 1 fixed to vehicle 1 (symmetry breaking)\n"
                   "Stage 2 (exact): shortest depot tour per vehicle by enumeration")
    limitations = ("Decomposition heuristic: the QUBO minimises a clustering proxy, so the combined routes are not "
                   "guaranteed to be the optimal CVRP solution. ≤ 8 customers.")
    Input = VRPInput

    def _vars(self, d: VRPInput):
        return {(c, v): f"veh_{c}_{v}" for c in range(1, len(d.locations))
                for v in range(d.num_vehicles) if c != 1 or v == 0}

    def build_model(self, d: VRPInput) -> Model:
        m = Model("vehicle_routing")
        V = self._vars(d)
        X = {k: m.binary(n) for k, n in V.items()}
        D = d.distance
        cust = range(1, len(d.locations))
        obj = quicksum(D[c][c2] * X[(c, v)] * X[(c2, v)] for v in range(d.num_vehicles)
                       for c in cust for c2 in cust if c < c2 and (c, v) in X and (c2, v) in X)
        obj = obj + quicksum(0.5 * (D[0][c] + D[c][0]) * x for (c, v), x in X.items())
        m.minimize(obj)
        for c in cust:
            names = [V[(c, v)] for v in range(d.num_vehicles) if (c, v) in V]
            if len(names) == 1:
                m.add_constraint(m.var(names[0]) == 1, f"cust_{c}")
            else:
                m.add_one_hot(names, f"cust_{c}")
        for v in range(d.num_vehicles):
            on = [(c, X[(c, v)]) for c in cust if (c, v) in X]
            if sum(d.demand[c] for c, _ in on) > d.vehicle_capacity:
                m.add_constraint(quicksum(d.demand[c] * x for c, x in on) <= d.vehicle_capacity, f"cap_{v}")
        return m

    def interpret(self, d: VRPInput, a):
        V = self._vars(d)
        groups = [[c for c in range(1, len(d.locations)) if a.get(V.get((c, v), ""), 0)] for v in range(d.num_vehicles)]
        each = all(sum(c in g for g in groups) == 1 for c in range(1, len(d.locations)))
        routes, total = {}, 0.0
        for v, g in enumerate(groups):
            route, L = best_tour(d.distance, g)
            routes[f"vehicle {v + 1}"] = {"route": [d.locations[i] for i in route], "length": round(L, 3),
                                          "load": sum(d.demand[c] for c in g)}
            total += L
        return {"routes": routes, "total_distance": round(total, 3), "each_customer_once_ok": each,
                "capacity_ok": all(r["load"] <= d.vehicle_capacity for r in routes.values())}

    def example(self):
        pts = [(0, 0), (2, 1), (3, 3), (1, 4), (-2, 2), (-3, -1), (-1, -3)]
        dist = [[round(math.dist(p, q), 2) for q in pts] for p in pts]
        return {"locations": ["Depot", "C1", "C2", "C3", "C4", "C5", "C6"], "distance": dist,
                "demand": [0, 2, 3, 1, 2, 2, 1], "num_vehicles": 2, "vehicle_capacity": 6}


# ----------------------------------------------------------------------------- cargo loading
class CargoInput(BaseModel):
    items: List[str] = Field(min_length=1, max_length=10)
    weight: List[int]
    value: List[float]
    containers: List[str] = Field(min_length=1, max_length=3)
    capacity: List[int]

    @model_validator(mode="after")
    def _check(self):
        if len(self.weight) != len(self.items) or len(self.value) != len(self.items):
            raise ValueError("weight and value per item")
        if any(w <= 0 for w in self.weight) or any(v < 0 for v in self.value):
            raise ValueError("weights must be positive, values non-negative")
        if len(self.capacity) != len(self.containers) or any(c < 0 for c in self.capacity):
            raise ValueError("one non-negative capacity per container")
        return self


class CargoLoading(IndustryProblem):
    key = "logistics.cargo_loading"
    industry = "logistics"
    title = "Cargo allocation to containers (multiple knapsack)"
    description = "Load items into containers to maximise shipped value without exceeding any container's capacity."
    formulation = ("max  Σ_ik v_i x_ik\n"
                   "s.t. x_ik x_ik' = 0  (k ≠ k': an item goes in at most one container)\n"
                   "     Σ_i w_i x_ik ≤ C_k  ∀ containers (slack-encoded)")
    Input = CargoInput

    def build_model(self, d: CargoInput) -> Model:
        m = Model("cargo_loading")
        I, K = len(d.items), len(d.containers)
        X = [[m.binary(f"load_{i}_{k}") for k in range(K)] for i in range(I)]
        m.maximize(quicksum(d.value[i] * X[i][k] for i in range(I) for k in range(K)))
        for i in range(I):
            for k in range(K):
                for k2 in range(k + 1, K):
                    m.add_constraint(X[i][k] * X[i][k2] == 0, f"once_{i}_{k}_{k2}")
        for k in range(K):
            if sum(d.weight) > d.capacity[k]:
                m.add_constraint(quicksum(d.weight[i] * X[i][k] for i in range(I)) <= d.capacity[k], f"cap_{k}")
        return m

    def interpret(self, d: CargoInput, a):
        I, K = len(d.items), len(d.containers)
        plan = {d.containers[k]: [d.items[i] for i in range(I) if a[f"load_{i}_{k}"]] for k in range(K)}
        w = {c: sum(d.weight[d.items.index(x)] for x in v) for c, v in plan.items()}
        loaded = [x for v in plan.values() for x in v]
        return {"plan": plan, "container_weight": w,
                "shipped_value": float(sum(d.value[d.items.index(x)] for x in loaded)),
                "left_behind": [x for x in d.items if x not in loaded],
                "capacity_ok": all(w[d.containers[k]] <= d.capacity[k] for k in range(K)),
                "at_most_once_ok": len(loaded) == len(set(loaded))}

    def example(self):
        return {"items": ["pallet-A", "pallet-B", "crate-C", "crate-D", "box-E"], "weight": [4, 3, 2, 5, 1],
                "value": [10, 7, 4, 12, 2], "containers": ["truck-1", "truck-2"], "capacity": [7, 6]}


# ----------------------------------------------------------------------------- dock scheduling
class DockInput(BaseModel):
    trucks: List[str] = Field(min_length=1, max_length=8)
    doors: List[str] = Field(min_length=1, max_length=3)
    slots: List[str] = Field(min_length=1, max_length=6)
    arrival_slot: List[int]
    handling_cost: List[List[float]] = Field(description="truck×door cost (e.g. distance to storage zone)")
    waiting_cost: List[float] = Field(description="cost per slot of waiting, per truck")

    @model_validator(mode="after")
    def _check(self):
        T, D, S = len(self.trucks), len(self.doors), len(self.slots)
        if len(self.arrival_slot) != T or any(not 0 <= s < S for s in self.arrival_slot):
            raise ValueError("arrival_slot: one valid slot index per truck")
        if len(self.handling_cost) != T or any(len(r) != D for r in self.handling_cost):
            raise ValueError("handling_cost must be trucks×doors")
        if len(self.waiting_cost) != T or min(self.waiting_cost) < 0:
            raise ValueError("one non-negative waiting cost per truck")
        # Hall-type feasibility check on suffixes of the horizon
        for s0 in range(S):
            if sum(1 for a in self.arrival_slot if a >= s0) > D * (S - s0):
                raise ValueError("not enough door-slots for the trucks arriving late — infeasible")
        return self


class DockScheduling(IndustryProblem):
    key = "logistics.dock_scheduling"
    industry = "logistics"
    title = "Warehouse dock-door scheduling"
    description = "Assign each arriving truck a dock door and unloading slot (no double-booking), minimising handling and waiting."
    formulation = ("x_tds = truck t at door d in slot s ≥ arrival_t\n"
                   "min  Σ_tds (h_td + w_t (s − a_t)) x_tds\n"
                   "s.t. Σ_ds x_tds = 1 ∀t ;  x_tds x_t'ds = 0 (one truck per door-slot)")
    limitations = "Each truck occupies exactly one slot; multi-slot unloading needs interval constraints."
    Input = DockInput

    def _vars(self, d: DockInput):
        return [(t, k, s) for t in range(len(d.trucks)) for k in range(len(d.doors))
                for s in range(d.arrival_slot[t], len(d.slots))]

    def build_model(self, d: DockInput) -> Model:
        m = Model("dock_scheduling")
        X = {v: m.binary(f"dock_{v[0]}_{v[1]}_{v[2]}") for v in self._vars(d)}
        m.minimize(quicksum((d.handling_cost[t][k] + d.waiting_cost[t] * (s - d.arrival_slot[t])) * x
                            for (t, k, s), x in X.items()))
        for t in range(len(d.trucks)):
            m.add_one_hot([f"dock_{t}_{k}_{s}" for (tt, k, s) in X if tt == t], f"truck_{t}")
        for k in range(len(d.doors)):
            for s in range(len(d.slots)):
                users = [t for t in range(len(d.trucks)) if (t, k, s) in X]
                for i, t in enumerate(users):
                    for t2 in users[i + 1:]:
                        m.add_constraint(X[(t, k, s)] * X[(t2, k, s)] == 0, f"door_{k}_{s}_{t}_{t2}")
        return m

    def interpret(self, d: DockInput, a):
        sched, used, cost, count = {}, {}, 0.0, {}
        for (t, k, s) in self._vars(d):
            if a.get(f"dock_{t}_{k}_{s}"):
                sched.setdefault(d.trucks[t], []).append({"door": d.doors[k], "slot": d.slots[s]})
                used[(k, s)] = used.get((k, s), 0) + 1
                cost += d.handling_cost[t][k] + d.waiting_cost[t] * (s - d.arrival_slot[t])
                count[t] = count.get(t, 0) + 1
        return {"schedule": sched, "total_cost": cost,
                "no_double_booking_ok": all(v <= 1 for v in used.values()),
                "each_truck_once_ok": all(count.get(t) == 1 for t in range(len(d.trucks)))}

    def example(self):
        return {"trucks": ["TRK-1", "TRK-2", "TRK-3", "TRK-4"], "doors": ["door-1", "door-2"],
                "slots": ["08:00", "09:00", "10:00"], "arrival_slot": [0, 1, 1, 2],
                "handling_cost": [[1, 3], [2, 1], [1, 2], [3, 1]], "waiting_cost": [2, 1, 3, 1]}
