"""Supply chain: production planning (lot sizing), capacitated facility location, risk-aware supplier selection."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from ..core.expr import Expr, quicksum
from ..core.model import Model, _binary_expansion_weights
from .base import IndustryProblem


# ----------------------------------------------------------------------------- production planning
class ProductionInput(BaseModel):
    products: List[str] = Field(min_length=1, max_length=3)
    periods: List[str] = Field(min_length=1, max_length=4)
    demand: List[List[int]] = Field(description="product×period demand (units)")
    max_production: List[int] = Field(description="max units per product per period (≤ 7)")
    capacity: List[int] = Field(description="shared production capacity per period (units)")
    unit_cost: List[float]
    setup_cost: List[float] = Field(description="fixed cost whenever a product is produced in a period")
    holding_cost: List[float] = Field(description="cost per unit of end-of-period inventory")
    initial_inventory: List[int]
    storage_cap: Optional[List[int]] = Field(default=None, description="max end-of-period inventory per product")

    @model_validator(mode="after")
    def _check(self):
        P, T = len(self.products), len(self.periods)
        if len(self.demand) != P or any(len(r) != T for r in self.demand) or min(min(r) for r in self.demand) < 0:
            raise ValueError("demand must be a non-negative products×periods matrix")
        for name in ("max_production", "unit_cost", "setup_cost", "holding_cost", "initial_inventory"):
            v = getattr(self, name)
            if len(v) != P or min(v) < 0:
                raise ValueError(f"{name}: one non-negative value per product")
        if any(m > 7 for m in self.max_production):
            raise ValueError("max_production is limited to 7 units per period (3 bits) to keep the QUBO small")
        if len(self.capacity) != T or min(self.capacity) < 0:
            raise ValueError("one non-negative capacity per period")
        if self.storage_cap is not None and (len(self.storage_cap) != P or min(self.storage_cap) < 0):
            raise ValueError("storage_cap: one non-negative value per product")
        for p in range(P):     # necessary condition: cumulative demand reachable
            for t in range(T):
                if sum(self.demand[p][: t + 1]) > self.initial_inventory[p] + (t + 1) * self.max_production[p]:
                    raise ValueError(f"{self.products[p]}: demand up to {self.periods[t]} cannot be met — infeasible")
        return self


def production_cost(d: ProductionInput, q) -> Optional[float]:
    """Domain cost of a production plan q[p][t]; None if infeasible."""
    P, T = len(d.products), len(d.periods)
    cost = 0.0
    for t in range(T):
        if sum(q[p][t] for p in range(P)) > d.capacity[t]:
            return None
    for p in range(P):
        inv = d.initial_inventory[p]
        for t in range(T):
            if q[p][t] > d.max_production[p]:
                return None
            inv += q[p][t] - d.demand[p][t]
            if inv < 0 or (d.storage_cap is not None and inv > d.storage_cap[p]):
                return None
            cost += d.unit_cost[p] * q[p][t] + (d.setup_cost[p] if q[p][t] > 0 else 0) + d.holding_cost[p] * inv
    return cost


class ProductionPlanning(IndustryProblem):
    key = "manufacturing.production_planning"
    industry = "manufacturing"
    title = "Production planning (multi-product lot sizing)"
    description = ("Decide how many units of each product to make in each period, meeting demand from production and "
                   "inventory, within shared capacity, minimising production, setup and holding costs.")
    formulation = ("q_pt = Σ_k c_k b_ptk (bounded binary expansion), z_pt = setup flag, I_pt = I_p0 + Σ_{s≤t} (q_ps − d_ps)\n"
                   "min  Σ_pt (u_p q_pt + s_p z_pt + h_p I_pt)\n"
                   "s.t. I_pt ≥ 0 (no backlog) ;  Σ_p q_pt ≤ C_t ;  b_ptk (1 − z_pt) = 0  (production ⇒ setup) ;\n"
                   "     I_pt ≤ S_p (optional storage cap)")
    limitations = ("Integer units with ≤ 7 per product-period; no backlogging, lead times or multi-level bills of "
                   "materials. Slack bits for the inventory constraints make examples larger than the statevector limit.")
    Input = ProductionInput

    def _bits(self, d: ProductionInput):
        return [_binary_expansion_weights(m) for m in d.max_production]

    def build_model(self, d: ProductionInput) -> Model:
        m = Model("production_planning")
        P, T = len(d.products), len(d.periods)
        bits = self._bits(d)
        Q = [[None] * T for _ in range(P)]
        B, Z = {}, {}
        for p in range(P):
            for t in range(T):
                for k, c in enumerate(bits[p]):
                    B[(p, t, k)] = m.binary(f"q_{p}_{t}_{k}")
                Q[p][t] = quicksum(c * B[(p, t, k)] for k, c in enumerate(bits[p]))
                Z[(p, t)] = m.binary(f"z_{p}_{t}")
        obj = []
        for p in range(P):
            inv: Expr = Expr(d.initial_inventory[p])
            for t in range(T):
                inv = inv + Q[p][t] - d.demand[p][t]
                obj += [d.unit_cost[p] * Q[p][t], d.setup_cost[p] * Z[(p, t)], d.holding_cost[p] * inv]
                if inv.bounds()[0] < 0:
                    m.add_constraint(inv >= 0, f"no_backlog_{p}_{t}")
                if d.storage_cap is not None and inv.bounds()[1] > d.storage_cap[p]:
                    m.add_constraint(inv <= d.storage_cap[p], f"storage_{p}_{t}")
                for k in range(len(bits[p])):
                    m.add_constraint(B[(p, t, k)] * (1 - Z[(p, t)]) == 0, f"setup_{p}_{t}_{k}")
        for t in range(T):
            if sum(d.max_production) > d.capacity[t]:
                m.add_constraint(quicksum(Q[p][t] for p in range(P)) <= d.capacity[t], f"capacity_{t}")
        m.minimize(quicksum(obj))
        return m

    def interpret(self, d: ProductionInput, a):
        P, T = len(d.products), len(d.periods)
        bits = self._bits(d)
        q = [[int(sum(c * a[f"q_{p}_{t}_{k}"] for k, c in enumerate(bits[p]))) for t in range(T)] for p in range(P)]
        inv_rows = {}
        for p in range(P):
            inv, row = d.initial_inventory[p], []
            for t in range(T):
                inv += q[p][t] - d.demand[p][t]
                row.append(inv)
            inv_rows[d.products[p]] = row
        cost = production_cost(d, q)
        return {"production": {d.products[p]: dict(zip(d.periods, q[p])) for p in range(P)},
                "end_inventory": inv_rows, "total_cost": cost,
                "demand_met_ok": all(v >= 0 for r in inv_rows.values() for v in r),
                "capacity_ok": all(sum(q[p][t] for p in range(P)) <= d.capacity[t] for t in range(T)),
                "plan_feasible_ok": cost is not None}

    def example(self):
        return {"products": ["widget", "gadget"], "periods": ["wk1", "wk2", "wk3"],
                "demand": [[2, 3, 1], [1, 2, 3]], "max_production": [3, 3], "capacity": [4, 4, 4],
                "unit_cost": [1.0, 1.5], "setup_cost": [5.0, 4.0], "holding_cost": [1.0, 1.0],
                "initial_inventory": [1, 0]}


# ----------------------------------------------------------------------------- facility location
class FacilityInput(BaseModel):
    facilities: List[str] = Field(min_length=2, max_length=4)
    customers: List[str] = Field(min_length=1, max_length=6)
    fixed_cost: List[float] = Field(description="cost of opening each facility")
    capacity: List[int] = Field(description="throughput capacity per facility (units)")
    demand: List[int] = Field(description="units required by each customer")
    transport_cost: List[List[float]] = Field(description="customer×facility cost per unit shipped")

    @model_validator(mode="after")
    def _check(self):
        F, C = len(self.facilities), len(self.customers)
        if len(self.fixed_cost) != F or len(self.capacity) != F or min(self.fixed_cost) < 0 or min(self.capacity) < 0:
            raise ValueError("fixed_cost and capacity: one non-negative value per facility")
        if len(self.demand) != C or min(self.demand) < 0:
            raise ValueError("one non-negative demand per customer")
        if len(self.transport_cost) != C or any(len(r) != F for r in self.transport_cost):
            raise ValueError("transport_cost must be customers×facilities")
        if max(self.demand) > max(self.capacity) or sum(self.demand) > sum(self.capacity):
            raise ValueError("demand cannot be served within facility capacities — infeasible")
        return self


def facility_cost(d: FacilityInput, assign: List[int]) -> Optional[float]:
    F = len(d.facilities)
    load = [0] * F
    for c, f in enumerate(assign):
        load[f] += d.demand[c]
    if any(load[f] > d.capacity[f] for f in range(F)):
        return None
    opened = set(assign)
    return sum(d.fixed_cost[f] for f in opened) + sum(d.demand[c] * d.transport_cost[c][f] for c, f in enumerate(assign))


class FacilityLocation(IndustryProblem):
    key = "supply_chain.facility_location"
    industry = "supply chain"
    title = "Supply-chain network design (capacitated facility location)"
    description = ("Choose which warehouses / plants to open and which customers each one serves, minimising "
                   "opening plus transport cost within facility capacities (single sourcing).")
    formulation = ("y_f = open facility f, x_cf = customer c served by f\n"
                   "min  Σ_f F_f y_f + Σ_cf d_c t_cf x_cf\n"
                   "s.t. Σ_f x_cf = 1 ∀c ;  Σ_c d_c x_cf ≤ K_f y_f  (binding capacity, slack-encoded) ;\n"
                   "     x_cf (1 − y_f) = 0  where capacity is never binding")
    limitations = "Single sourcing, one echelon, deterministic demand."
    Input = FacilityInput

    def build_model(self, d: FacilityInput) -> Model:
        m = Model("facility_location")
        F, C = len(d.facilities), len(d.customers)
        Y = [m.binary(f"open_{f}") for f in range(F)]
        X = [[m.binary(f"serve_{c}_{f}") for f in range(F)] for c in range(C)]
        m.minimize(quicksum(d.fixed_cost[f] * Y[f] for f in range(F))
                   + quicksum(d.demand[c] * d.transport_cost[c][f] * X[c][f] for c in range(C) for f in range(F)))
        for c in range(C):
            m.add_one_hot([f"serve_{c}_{f}" for f in range(F)], f"customer_{c}")
        for f in range(F):
            if sum(d.demand) > d.capacity[f]:
                m.add_constraint(quicksum(d.demand[c] * X[c][f] for c in range(C)) - d.capacity[f] * Y[f] <= 0,
                                 f"capacity_{f}")
            else:
                for c in range(C):
                    m.add_constraint(X[c][f] * (1 - Y[f]) == 0, f"open_{c}_{f}")
        return m

    def interpret(self, d: FacilityInput, a):
        F, C = len(d.facilities), len(d.customers)
        served = [[f for f in range(F) if a[f"serve_{c}_{f}"]] for c in range(C)]
        opened = [f for f in range(F) if a[f"open_{f}"]]
        single = all(len(s) == 1 for s in served)
        assign = [s[0] for s in served] if single else None
        cost = facility_cost(d, assign) if assign else None
        load = {d.facilities[f]: sum(d.demand[c] for c in range(C) if f in served[c]) for f in range(F)}
        return {"open_facilities": [d.facilities[f] for f in opened],
                "assignment": {d.customers[c]: [d.facilities[f] for f in served[c]] for c in range(C)},
                "facility_load": load, "total_cost": cost, "single_sourcing_ok": single,
                "served_by_open_facility_ok": single and all(assign[c] in opened for c in range(C)),
                "capacity_ok": all(load[d.facilities[f]] <= d.capacity[f] for f in range(F))}

    def example(self):
        return {"facilities": ["DC-Pune", "DC-Nagpur", "DC-Hyderabad"],
                "customers": ["Mumbai", "Nashik", "Indore", "Raipur", "Vizag"],
                "fixed_cost": [40, 30, 35], "capacity": [6, 5, 6], "demand": [3, 1, 2, 2, 2],
                "transport_cost": [[1, 4, 5], [1, 3, 5], [4, 2, 5], [5, 1, 3], [6, 3, 2]]}


# ----------------------------------------------------------------------------- supplier selection
class SupplierInput(BaseModel):
    suppliers: List[str] = Field(min_length=2, max_length=14)
    cost: List[float] = Field(description="cost of contracting each supplier")
    components: List[str] = Field(min_length=1, max_length=6)
    supplies: List[List[int]] = Field(description="per supplier: indices of components it can provide")
    min_sources: List[int] = Field(description="per component: number of independent suppliers required")
    region: List[str]
    concentration_penalty: float = Field(default=0.0, ge=0,
                                         description="cost per pair of selected suppliers in the same region")

    @model_validator(mode="after")
    def _check(self):
        S, C = len(self.suppliers), len(self.components)
        if len(self.cost) != S or len(self.supplies) != S or len(self.region) != S or min(self.cost) < 0:
            raise ValueError("cost, supplies and region: one entry per supplier (costs non-negative)")
        if any(not 0 <= c < C for s in self.supplies for c in s):
            raise ValueError("supplies contains an invalid component index")
        if len(self.min_sources) != C or min(self.min_sources) < 1:
            raise ValueError("min_sources: one positive value per component")
        for c in range(C):
            if sum(1 for s in self.supplies if c in s) < self.min_sources[c]:
                raise ValueError(f"not enough suppliers for {self.components[c]} — infeasible")
        return self


def supplier_cost(d: SupplierInput, chosen: List[int]) -> Optional[float]:
    for c in range(len(d.components)):
        if sum(1 for s in chosen if c in d.supplies[s]) < d.min_sources[c]:
            return None
    pairs = sum(1 for i, s in enumerate(chosen) for t in chosen[i + 1:] if d.region[s] == d.region[t])
    return sum(d.cost[s] for s in chosen) + d.concentration_penalty * pairs


class SupplierSelection(IndustryProblem):
    key = "supply_chain.supplier_selection"
    industry = "supply chain"
    title = "Risk-aware supplier selection (multi-sourcing)"
    description = ("Contract a set of suppliers so every component has the required number of sources, minimising "
                   "cost plus a penalty for concentrating suppliers in the same region (correlated disruption risk).")
    formulation = ("min  Σ_s c_s x_s + ρ Σ_{s<s', region(s)=region(s')} x_s x_s'\n"
                   "s.t. Σ_{s supplies k} x_s ≥ m_k   ∀ components k  (slack-encoded)")
    limitations = "Regional concentration is a simple pairwise proxy for disruption risk; no probabilistic model."
    Input = SupplierInput

    def build_model(self, d: SupplierInput) -> Model:
        m = Model("supplier_selection")
        S = len(d.suppliers)
        X = m.binaries([f"sup_{s}" for s in range(S)])
        pen = [d.concentration_penalty * X[i] * X[j] for i in range(S) for j in range(i + 1, S)
               if d.region[i] == d.region[j]] if d.concentration_penalty else []
        m.minimize(quicksum(d.cost[s] * X[s] for s in range(S)) + quicksum(pen))
        for c in range(len(d.components)):
            m.add_constraint(quicksum(X[s] for s in range(S) if c in d.supplies[s]) >= d.min_sources[c], f"source_{c}")
        return m

    def interpret(self, d: SupplierInput, a):
        chosen = [s for s in range(len(d.suppliers)) if a[f"sup_{s}"]]
        cover = {d.components[c]: [d.suppliers[s] for s in chosen if c in d.supplies[s]] for c in range(len(d.components))}
        regions = {}
        for s in chosen:
            regions[d.region[s]] = regions.get(d.region[s], 0) + 1
        return {"selected_suppliers": [d.suppliers[s] for s in chosen], "sources_per_component": cover,
                "suppliers_per_region": regions, "total_cost": supplier_cost(d, chosen),
                "coverage_ok": all(len(cover[d.components[c]]) >= d.min_sources[c] for c in range(len(d.components)))}

    def example(self):
        return {"suppliers": ["S1-Shenzhen", "S2-Shenzhen", "S3-Penang", "S4-Pune", "S5-Pune", "S6-Monterrey",
                              "S7-Penang"],
                "cost": [10, 9, 12, 11, 13, 15, 8],
                "components": ["chips", "displays", "batteries"],
                "supplies": [[0, 1], [0, 2], [0], [1, 2], [2], [0, 1, 2], [1]],
                "min_sources": [2, 2, 1],
                "region": ["CN", "CN", "MY", "IN", "IN", "MX", "MY"], "concentration_penalty": 6.0}
