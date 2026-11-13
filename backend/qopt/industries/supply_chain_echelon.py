"""Multi-echelon supply chain: two-echelon network design and time-phased multi-echelon replenishment."""
from __future__ import annotations

import itertools
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from ..core.expr import Expr, quicksum
from ..core.model import Model, _binary_expansion_weights
from .base import IndustryProblem


# ----------------------------------------------------------------------------- two-echelon network design
class EchelonNetworkInput(BaseModel):
    plants: List[str] = Field(min_length=1, max_length=3)
    dcs: List[str] = Field(min_length=1, max_length=3, description="distribution centres (second echelon)")
    customers: List[str] = Field(min_length=1, max_length=6)
    demand: List[int]
    plant_capacity: List[int]
    dc_capacity: List[int]
    dc_fixed_cost: List[float]
    inbound_cost: List[List[float]] = Field(description="DC×plant cost per unit (plant → DC)")
    outbound_cost: List[List[float]] = Field(description="customer×DC cost per unit (DC → customer)")
    single_source_dcs: bool = Field(default=True, description="each DC is replenished by exactly one plant")

    @model_validator(mode="after")
    def _check(self):
        P, J, C = len(self.plants), len(self.dcs), len(self.customers)
        if len(self.demand) != C or min(self.demand) < 0:
            raise ValueError("one non-negative demand per customer")
        if len(self.plant_capacity) != P or min(self.plant_capacity) < 0:
            raise ValueError("one non-negative capacity per plant")
        if len(self.dc_capacity) != J or len(self.dc_fixed_cost) != J or min(self.dc_capacity) < 0 \
                or min(self.dc_fixed_cost) < 0:
            raise ValueError("dc_capacity and dc_fixed_cost: one non-negative value per DC")
        if len(self.inbound_cost) != J or any(len(r) != P for r in self.inbound_cost):
            raise ValueError("inbound_cost must be DCs×plants")
        if len(self.outbound_cost) != C or any(len(r) != J for r in self.outbound_cost):
            raise ValueError("outbound_cost must be customers×DCs")
        tot = sum(self.demand)
        if tot > sum(self.plant_capacity) or tot > sum(self.dc_capacity) or \
                max(self.demand) > min(max(self.dc_capacity), max(self.plant_capacity)):
            raise ValueError("demand cannot be served within plant / DC capacities — infeasible")
        return self

    def paths(self) -> List[Tuple[int, int]]:
        return [(j, p) for j in range(len(self.dcs)) for p in range(len(self.plants))]


def echelon_network_cost(d: EchelonNetworkInput, choice: List[Tuple[int, int]]) -> Optional[float]:
    """Domain cost of assigning customer c to route (dc j, plant p); None if infeasible."""
    J, P = len(d.dcs), len(d.plants)
    dc_load, pl_load, src = [0] * J, [0] * P, {}
    for c, (j, p) in enumerate(choice):
        dc_load[j] += d.demand[c]
        pl_load[p] += d.demand[c]
        if d.single_source_dcs and src.setdefault(j, p) != p:
            return None
    if any(dc_load[j] > d.dc_capacity[j] for j in range(J)) or any(pl_load[p] > d.plant_capacity[p] for p in range(P)):
        return None
    opened = {j for j, _ in choice}
    return sum(d.dc_fixed_cost[j] for j in opened) + \
        sum(d.demand[c] * (d.outbound_cost[c][j] + d.inbound_cost[j][p]) for c, (j, p) in enumerate(choice))


class EchelonNetworkDesign(IndustryProblem):
    key = "supply_chain.two_echelon_network"
    industry = "supply chain"
    title = "Two-echelon network design (plants → DCs → customers)"
    description = ("Decide which distribution centres to open, which DC serves each customer and which plant "
                   "replenishes each DC, within plant and DC capacities, minimising DC fixed costs plus inbound and "
                   "outbound transport.")
    formulation = ("v_{c,j,p} = customer c served via DC j replenished from plant p (one route per customer), y_j = open DC\n"
                   "min  Σ_j F_j y_j + Σ_{c,j,p} d_c (t_cj + u_jp) v_cjp\n"
                   "s.t. Σ_{j,p} v_cjp = 1 ∀c ;  Σ_{c,p} d_c v_cjp ≤ K_j y_j (or v_cjp(1−y_j)=0 if non-binding) ;\n"
                   "     Σ_{c,j} d_c v_cjp ≤ Cap_p ;  v_cjp v_c'jp' = 0 for p ≠ p' (single-sourced DCs)")
    limitations = ("Route-based encoding: C·J·P qubits. Single-period, deterministic demand, unsplittable "
                   "customer flows; plants are always available (no plant opening decision).")
    Input = EchelonNetworkInput

    def build_model(self, d: EchelonNetworkInput) -> Model:
        m = Model("two_echelon_network")
        C, J, P = len(d.customers), len(d.dcs), len(d.plants)
        Y = [m.binary(f"dc_{j}") for j in range(J)]
        V = {(c, j, p): m.binary(f"route_{c}_{j}_{p}") for c in range(C) for (j, p) in d.paths()}
        m.minimize(quicksum(d.dc_fixed_cost[j] * Y[j] for j in range(J)) +
                   quicksum(d.demand[c] * (d.outbound_cost[c][j] + d.inbound_cost[j][p]) * v
                            for (c, j, p), v in V.items()))
        for c in range(C):
            m.add_one_hot([f"route_{c}_{j}_{p}" for (j, p) in d.paths()], f"customer_{c}")
        tot = sum(d.demand)
        for j in range(J):
            flow = quicksum(d.demand[c] * V[(c, j, p)] for c in range(C) for p in range(P))
            if tot > d.dc_capacity[j]:
                m.add_constraint(flow - d.dc_capacity[j] * Y[j] <= 0, f"dc_capacity_{j}")
            else:
                for c in range(C):
                    for p in range(P):
                        m.add_constraint(V[(c, j, p)] * (1 - Y[j]) == 0, f"dc_open_{c}_{j}_{p}")
            if d.single_source_dcs and P > 1:
                for c, c2 in itertools.combinations(range(C), 2):
                    for p in range(P):
                        for p2 in range(P):
                            if p != p2:
                                m.add_constraint(V[(c, j, p)] * V[(c2, j, p2)] == 0, f"ss_{j}_{c}{p}_{c2}{p2}")
        for p in range(P):
            if tot > d.plant_capacity[p]:
                m.add_constraint(quicksum(d.demand[c] * V[(c, j, p)] for c in range(C) for j in range(J))
                                 <= d.plant_capacity[p], f"plant_capacity_{p}")
        return m

    def interpret(self, d: EchelonNetworkInput, a):
        C = len(d.customers)
        routes = [[(j, p) for (j, p) in d.paths() if a[f"route_{c}_{j}_{p}"]] for c in range(C)]
        one = all(len(r) == 1 for r in routes)
        opened = [j for j in range(len(d.dcs)) if a[f"dc_{j}"]]
        out = {"open_dcs": [d.dcs[j] for j in opened], "one_route_per_customer_ok": one}
        if not one:
            return out
        choice = [r[0] for r in routes]
        cost = echelon_network_cost(d, choice)
        dc_src = {}
        for j, p in choice:
            dc_src.setdefault(d.dcs[j], set()).add(d.plants[p])
        out.update({
            "routes": {d.customers[c]: f"{d.plants[p]} → {d.dcs[j]} → {d.customers[c]}" for c, (j, p) in enumerate(choice)},
            "dc_supplier": {k: sorted(v) for k, v in dc_src.items()},
            "dc_load": {d.dcs[j]: sum(d.demand[c] for c, (jj, _) in enumerate(choice) if jj == j) for j in range(len(d.dcs))},
            "plant_load": {d.plants[p]: sum(d.demand[c] for c, (_, pp) in enumerate(choice) if pp == p)
                           for p in range(len(d.plants))},
            "total_cost": cost, "network_feasible_ok": cost is not None,
            "served_by_open_dc_ok": all(j in opened for j, _ in choice)})
        return out

    def example(self):
        return {"plants": ["Plant-Chennai", "Plant-Ahmedabad"], "dcs": ["DC-Bengaluru", "DC-Nagpur"],
                "customers": ["Hyderabad", "Kochi", "Bhopal", "Indore"], "demand": [2, 2, 1, 2],
                "plant_capacity": [5, 4], "dc_capacity": [5, 5], "dc_fixed_cost": [20, 18],
                "inbound_cost": [[1, 4], [3, 2]], "outbound_cost": [[2, 3], [1, 6], [5, 1], [6, 2]],
                "single_source_dcs": True}


# ----------------------------------------------------------------------------- multi-echelon replenishment
class ReplenishmentInput(BaseModel):
    dcs: List[str] = Field(min_length=1, max_length=2)
    stores: List[str] = Field(min_length=1, max_length=4)
    store_dc: List[int] = Field(description="index of the DC that supplies each store")
    periods: List[str] = Field(min_length=1, max_length=3)
    demand: List[List[int]] = Field(description="store×period demand (units)")
    truck_size: int = Field(ge=1, description="units per truckload")
    max_trucks: int = Field(default=1, ge=1, le=3, description="max truckloads per arc per period")
    truck_cost_plant_dc: List[float] = Field(description="cost per truck plant → DC, per DC")
    truck_cost_dc_store: List[float] = Field(description="cost per truck DC → store, per store")
    holding_cost_dc: List[float]
    holding_cost_store: List[float]
    initial_inventory_dc: List[int]
    initial_inventory_store: List[int]

    @model_validator(mode="after")
    def _check(self):
        J, S, T = len(self.dcs), len(self.stores), len(self.periods)
        if len(self.store_dc) != S or any(not 0 <= j < J for j in self.store_dc):
            raise ValueError("store_dc: one valid DC index per store")
        if len(self.demand) != S or any(len(r) != T for r in self.demand) or min(min(r) for r in self.demand) < 0:
            raise ValueError("demand must be a non-negative stores×periods matrix")
        for name, n in (("truck_cost_plant_dc", J), ("holding_cost_dc", J), ("initial_inventory_dc", J),
                        ("truck_cost_dc_store", S), ("holding_cost_store", S), ("initial_inventory_store", S)):
            v = getattr(self, name)
            if len(v) != n or min(v) < 0:
                raise ValueError(f"{name}: {n} non-negative values expected")
        for s in range(S):
            for t in range(T):
                need = sum(self.demand[s][: t + 1]) - self.initial_inventory_store[s]
                if need > (t + 1) * self.max_trucks * self.truck_size:
                    raise ValueError(f"store {self.stores[s]}: demand up to {self.periods[t]} exceeds delivery capacity")
        Q, M = self.truck_size, self.max_trucks
        for j in range(J):
            mine = [s for s in range(S) if self.store_dc[s] == j]
            for t in range(T):
                # each store needs at least ⌈shortfall / Q⌉ full trucks by period t; the DC can only pass on
                # its initial stock plus (t+1)·M inbound truckloads
                trucks_needed = sum(max(0, -(-(sum(self.demand[s][: t + 1]) - self.initial_inventory_store[s]) // Q))
                                    for s in mine)
                if trucks_needed * Q > self.initial_inventory_dc[j] + (t + 1) * M * Q:
                    raise ValueError(f"DC {self.dcs[j]}: its stores need {trucks_needed} truckloads by "
                                     f"{self.periods[t]} but the DC can supply at most "
                                     f"{self.initial_inventory_dc[j] + (t + 1) * M * Q} units — infeasible")
        return self


def replenishment_cost(d: ReplenishmentInput, n_dc, n_st) -> Optional[float]:
    """n_dc[j][t], n_st[s][t] truckloads; None if any inventory goes negative."""
    J, S, T, Q = len(d.dcs), len(d.stores), len(d.periods), d.truck_size
    cost = 0.0
    inv_dc, inv_st = list(d.initial_inventory_dc), list(d.initial_inventory_store)
    for t in range(T):
        for j in range(J):
            inv_dc[j] += Q * n_dc[j][t] - Q * sum(n_st[s][t] for s in range(S) if d.store_dc[s] == j)
            cost += d.truck_cost_plant_dc[j] * n_dc[j][t]
        for s in range(S):
            inv_st[s] += Q * n_st[s][t] - d.demand[s][t]
            cost += d.truck_cost_dc_store[s] * n_st[s][t]
        if min(inv_dc) < 0 or min(inv_st) < 0:
            return None
        cost += sum(h * i for h, i in zip(d.holding_cost_dc, inv_dc)) + sum(h * i for h, i in zip(d.holding_cost_store, inv_st))
    return cost


class MultiEchelonReplenishment(IndustryProblem):
    key = "supply_chain.multi_echelon_replenishment"
    industry = "supply chain"
    title = "Multi-echelon replenishment planning (plant → DCs → stores)"
    description = ("Plan truckload shipments from the plant to each distribution centre and from each DC to its "
                   "stores over several periods, so no echelon runs out of stock, minimising transport and holding "
                   "costs across the whole chain.")
    formulation = ("n_at ∈ {0..M} truckloads on arc a in period t (binary-expanded), Q = truck size\n"
                   "I^DC_jt = I^DC_j0 + Σ_{τ≤t} Q (n_{plant→j,τ} − Σ_{s∈j} n_{j→s,τ}) ≥ 0\n"
                   "I^S_st = I^S_s0 + Σ_{τ≤t} (Q n_{j→s,τ} − D_sτ) ≥ 0\n"
                   "min  Σ_at k_a n_at + Σ_t (Σ_j h_j I^DC_jt + Σ_s h_s I^S_st)")
    limitations = ("Zero transport lead time (shipments arrive in the same period), uncapacitated plant, no "
                   "backorders; inventory constraints need slack bits, so examples exceed the statevector limit.")
    Input = ReplenishmentInput

    def build_model(self, d: ReplenishmentInput) -> Model:
        m = Model("multi_echelon_replenishment")
        J, S, T, Q = len(d.dcs), len(d.stores), len(d.periods), d.truck_size
        w = _binary_expansion_weights(d.max_trucks)

        def trucks(prefix):
            return quicksum(c * m.binary(f"{prefix}_{k}") for k, c in enumerate(w))

        ND = [[trucks(f"pd_{j}_{t}") for t in range(T)] for j in range(J)]
        NS = [[trucks(f"ds_{s}_{t}") for t in range(T)] for s in range(S)]
        obj = []
        inv_dc = [Expr(d.initial_inventory_dc[j]) for j in range(J)]
        inv_st = [Expr(d.initial_inventory_store[s]) for s in range(S)]
        for t in range(T):
            for j in range(J):
                out_j = quicksum(NS[s][t] for s in range(S) if d.store_dc[s] == j)
                inv_dc[j] = inv_dc[j] + Q * ND[j][t] - Q * out_j
                obj += [d.truck_cost_plant_dc[j] * ND[j][t], d.holding_cost_dc[j] * inv_dc[j]]
                if inv_dc[j].bounds()[0] < 0:
                    m.add_constraint(inv_dc[j] >= 0, f"dc_stock_{j}_{t}")
            for s in range(S):
                inv_st[s] = inv_st[s] + Q * NS[s][t] - d.demand[s][t]
                obj += [d.truck_cost_dc_store[s] * NS[s][t], d.holding_cost_store[s] * inv_st[s]]
                if inv_st[s].bounds()[0] < 0:
                    m.add_constraint(inv_st[s] >= 0, f"store_stock_{s}_{t}")
        m.minimize(quicksum(obj))
        return m

    def _trucks(self, d, a, prefix):
        w = _binary_expansion_weights(d.max_trucks)
        return int(sum(c * a[f"{prefix}_{k}"] for k, c in enumerate(w)))

    def interpret(self, d: ReplenishmentInput, a):
        J, S, T = len(d.dcs), len(d.stores), len(d.periods)
        n_dc = [[self._trucks(d, a, f"pd_{j}_{t}") for t in range(T)] for j in range(J)]
        n_st = [[self._trucks(d, a, f"ds_{s}_{t}") for t in range(T)] for s in range(S)]
        cost = replenishment_cost(d, n_dc, n_st)
        return {"plant_to_dc_trucks": {d.dcs[j]: dict(zip(d.periods, n_dc[j])) for j in range(J)},
                "dc_to_store_trucks": {d.stores[s]: dict(zip(d.periods, n_st[s])) for s in range(S)},
                "total_cost": cost, "no_stockout_ok": cost is not None}

    def example(self):
        return {"dcs": ["DC-North", "DC-South"], "stores": ["Store-Delhi", "Store-Jaipur", "Store-Chennai"],
                "store_dc": [0, 0, 1], "periods": ["wk1", "wk2"],
                "demand": [[2, 3], [1, 2], [2, 2]], "truck_size": 3, "max_trucks": 1,
                "truck_cost_plant_dc": [10, 12], "truck_cost_dc_store": [3, 4, 3],
                "holding_cost_dc": [0.5, 0.5], "holding_cost_store": [1.0, 1.0, 1.0],
                "initial_inventory_dc": [4, 1], "initial_inventory_store": [1, 0, 1]}
