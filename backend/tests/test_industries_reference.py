"""Independent reference solvers for the industry modules.

Each reference enumerates the *domain* decisions directly from the raw example data (no Model, no QUBO)
and computes the optimum from the problem definition. It must equal the optimum of the compiled QUBO
(proven by exhaustive enumeration / MILP). This catches modelling errors, not only compilation errors.
"""
import itertools
import math

import numpy as np
import pytest

from qopt.core import validate_compiled
from qopt.industries import get_problem
from qopt.industries.energy_ext import battery_cost, uc_cost
from qopt.industries.logistics_ext import best_tour
from qopt.industries.supply_chain import facility_cost, production_cost, supplier_cost
from qopt.solvers import exhaustive

INF = math.inf


def qubo_optimum(key):
    p = get_problem(key)
    data, cm = p.compile(p.example())
    rep = validate_compiled(cm)          # exhaustive over all decision assignments ⇒ proven optimum
    assert rep.passed, rep.issues
    ev = cm.evaluate(np.array([int(c) for c in rep.best_feasible[0]]))
    assert ev.feasible and ev.objective == pytest.approx(rep.best_feasible_objective)
    if cm.qubo.num_variables <= 16:       # cross-check with an independent solver path where cheap
        assert cm.evaluate(exhaustive(cm.qubo).best_x).objective == pytest.approx(ev.objective)
    return p, data, ev, p.interpret(data, ev.assignment)


# ------------------------------------------------------------------ finance
def test_investment_allocation_reference():
    p, d, ev, out = qubo_optimum("finance.investment_allocation")
    C, mu, U = np.array(d.covariance), np.array(d.expected_returns), d.total_units
    best = INF
    for w in itertools.product(range(U + 1), repeat=len(d.assets)):
        if sum(w) == U:
            f = np.array(w) / U
            best = min(best, d.risk_aversion * f @ C @ f - mu @ f)
    assert ev.objective == pytest.approx(best)
    assert sum(out["units"].values()) == U


def test_fraud_feature_selection_reference():
    p, d, ev, out = qubo_optimum("finance.fraud_feature_selection")
    X, y = np.array(d.samples), np.array(d.labels)
    n = X.shape[1]
    rel = [abs(np.corrcoef(X[:, i], y)[0, 1]) for i in range(n)]
    red = np.abs(np.corrcoef(X.T))
    best = min(-sum(rel[i] for i in S) + d.redundancy_weight * sum(red[i, j] for i, j in itertools.combinations(S, 2))
               for S in itertools.combinations(range(n), d.num_features))
    assert ev.objective == pytest.approx(best, abs=1e-9)
    # the near-duplicate of the strongest feature must not be picked together with it
    assert not {"amount_zscore", "amount_zscore_dup"} <= set(out["selected_features"])


def test_transaction_scheduling_reference():
    p, d, ev, out = qubo_optimum("finance.transaction_scheduling")
    best = INF
    for choice in itertools.product(*[d.allowed(t) for t in range(len(d.transactions))]):
        load = [0] * len(d.windows)
        for t, w in enumerate(choice):
            load[w] += d.amounts[t]
        if all(l <= c for l, c in zip(load, d.window_capacity)):
            best = min(best, sum(d.cost[t][w] for t, w in enumerate(choice)))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])


# ------------------------------------------------------------------ healthcare
def test_clinical_trial_reference():
    p, d, ev, out = qubo_optimum("healthcare.clinical_trial_sites")
    best = INF
    for bits in itertools.product([0, 1], repeat=len(d.sites)):
        S = [i for i, b in enumerate(bits) if b]
        if (sum(d.expected_enrollment[i] for i in S) >= d.target_enrollment
                and set(d.required_regions) <= {d.region[i] for i in S}
                and (d.max_sites is None or len(S) <= d.max_sites)):
            best = min(best, sum(d.cost[i] for i in S))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])


def test_compound_selection_reference():
    p, d, ev, out = qubo_optimum("healthcare.compound_selection")
    S = np.array(d.similarity)
    best = min(-sum(d.activity[i] for i in c) + d.diversity_weight * sum(S[i, j] for i, j in itertools.combinations(c, 2))
               for c in itertools.combinations(range(len(d.compounds)), d.num_select))
    assert ev.objective == pytest.approx(best)
    assert out["max_pairwise_similarity"] < 0.85   # picks from different clusters


def test_operating_room_reference():
    p, d, ev, out = qubo_optimum("healthcare.operating_room_scheduling")
    K = len(d.slots)
    best = INF
    for choice in itertools.product(range(K), repeat=len(d.surgeries)):
        load, doc = [0] * K, {}
        for s, k in enumerate(choice):
            load[k] += d.duration_blocks[s]
            key = (d.surgeon[s], d.slots[k].day)
            doc[key] = doc.get(key, 0) + d.duration_blocks[s]
        if max(load) <= d.slot_capacity_blocks and max(doc.values()) <= d.surgeon_daily_max_blocks:
            best = min(best, sum(d.preference_cost[s][k] for s, k in enumerate(choice)))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["preference_cost"])


# ------------------------------------------------------------------ telecom
def test_spectrum_reference():
    from qopt.industries.telecom_ext import spectrum_interference
    p, d, ev, out = qubo_optimum("telecom.spectrum_allocation")
    best = min(spectrum_interference(d, list(ch))
               for ch in itertools.product(range(len(d.channels)), repeat=len(d.transmitters)))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_interference"])


def test_network_routing_reference():
    p, d, ev, out = qubo_optimum("telecom.network_routing")
    best = INF
    for choice in itertools.product(*[range(len(dm.paths)) for dm in d.demands]):
        load = [0] * len(d.links)
        lat = 0.0
        for dm, pi in zip(d.demands, choice):
            for k in d.path_links(dm.paths[pi]):
                load[k] += dm.volume
                lat += dm.volume * d.latency(k)
        if all(l <= c for l, c in zip(load, d.link_capacity)):
            best = min(best, lat + d.congestion_weight * sum(l * l / c for l, c in zip(load, d.link_capacity)))
    assert ev.objective == pytest.approx(best)
    assert out["capacity_ok"]


# ------------------------------------------------------------------ energy
def test_unit_commitment_reference():
    p, d, ev, out = qubo_optimum("energy.unit_commitment")
    G, T = len(d.generators), len(d.periods)
    best = INF
    for bits in itertools.product([0, 1], repeat=G * T):
        on = [list(bits[g * T:(g + 1) * T]) for g in range(G)]
        if all(sum(d.capacity[g] * on[g][t] for g in range(G)) >= d.demand[t] + d.reserve for t in range(T)):
            best = min(best, uc_cost(d, on))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])


def test_battery_reference():
    p, d, ev, out = qubo_optimum("energy.battery_scheduling")
    best, T = INF, len(d.slots)
    for steps in itertools.product(range(-d.max_rate, d.max_rate + 1), repeat=T):
        soc, s = [], d.initial_soc
        for delta in steps:
            s += delta
            soc.append(s)
        if all(0 <= x <= d.capacity_units for x in soc) and soc[-1] >= d.final_soc_min:
            best = min(best, battery_cost(d, soc))
    assert ev.objective == pytest.approx(best) == pytest.approx(-out["net_profit"])
    # sanity: buying in the cheapest slot and selling in the most expensive one is profitable here
    assert out["net_profit"] > 0


def test_renewable_allocation_reference():
    from qopt.industries.energy_flex import renewable_objective
    p, d, ev, out = qubo_optimum("energy.renewable_allocation")
    vals = [renewable_objective(d, [j for j, b in enumerate(bits) if b])
            for bits in itertools.product([0, 1], repeat=len(d.projects))]
    assert ev.objective == pytest.approx(min(v for v in vals if v is not None))
    assert out["budget_ok"]
    # complementarity: the optimum mixes solar with wind rather than using a single technology
    techs = {s.split("(")[1].rstrip(")") for s in out["selected_projects"]}
    assert {"solar", "wind"} <= techs


def test_demand_response_reference():
    from qopt.industries.energy_flex import dr_cost
    p, d, ev, out = qubo_optimum("energy.demand_response")
    vals = [dr_cost(d, list(st)) for st in itertools.product(*[d.starts(i) for i in range(len(d.loads))])]
    assert ev.objective == pytest.approx(min(v for v in vals if v is not None)) == pytest.approx(out["objective"])
    assert out["event_limits_ok"]


# ------------------------------------------------------------------ logistics
def test_vehicle_routing_reference():
    p, d, ev, out = qubo_optimum("logistics.vehicle_routing")
    D, cust = d.distance, range(1, len(d.locations))
    best, best_routes = INF, INF
    for choice in itertools.product(range(d.num_vehicles), repeat=len(cust)):
        if choice[0] != 0:          # same symmetry breaking as the module (customer 1 on vehicle 1)
            continue
        groups = [[c for c, v in zip(cust, choice) if v == k] for k in range(d.num_vehicles)]
        if any(sum(d.demand[c] for c in g) > d.vehicle_capacity for g in groups):
            continue
        proxy = sum(D[a][b] for g in groups for a, b in itertools.combinations(g, 2)) + \
            sum(0.5 * (D[0][c] + D[c][0]) for c in cust)
        best = min(best, proxy)
        best_routes = min(best_routes, sum(best_tour(D, g)[1] for g in groups))
    assert ev.objective == pytest.approx(best)
    # the decomposition is a heuristic: report, don't hide, its gap to the true best routing
    gap = out["total_distance"] - best_routes
    assert gap >= -1e-6
    print(f"VRP cluster-first total {out['total_distance']} vs exact CVRP {best_routes:.3f} (gap {gap:.3f})")


def test_cargo_loading_reference():
    p, d, ev, out = qubo_optimum("logistics.cargo_loading")
    K = len(d.containers)
    best = -INF
    for choice in itertools.product(range(-1, K), repeat=len(d.items)):   # -1 = left behind
        w = [0] * K
        for i, k in enumerate(choice):
            if k >= 0:
                w[k] += d.weight[i]
        if all(x <= c for x, c in zip(w, d.capacity)):
            best = max(best, sum(d.value[i] for i, k in enumerate(choice) if k >= 0))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["shipped_value"])


def test_dock_scheduling_reference():
    p, d, ev, out = qubo_optimum("logistics.dock_scheduling")
    opts = [[(k, s) for k in range(len(d.doors)) for s in range(d.arrival_slot[t], len(d.slots))]
            for t in range(len(d.trucks))]
    best = INF
    for choice in itertools.product(*opts):
        if len(set(choice)) == len(choice):
            best = min(best, sum(d.handling_cost[t][k] + d.waiting_cost[t] * (s - d.arrival_slot[t])
                                 for t, (k, s) in enumerate(choice)))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])


# ------------------------------------------------------------------ supply chain
def test_production_planning_reference():
    p, d, ev, out = qubo_optimum("manufacturing.production_planning")
    P, T = len(d.products), len(d.periods)
    best = INF
    for flat in itertools.product(*[range(d.max_production[pp] + 1) for pp in range(P) for _ in range(T)]):
        q = [list(flat[pp * T:(pp + 1) * T]) for pp in range(P)]
        c = production_cost(d, q)
        if c is not None:
            best = min(best, c)
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])


def test_facility_location_reference():
    p, d, ev, out = qubo_optimum("supply_chain.facility_location")
    costs = [facility_cost(d, list(a)) for a in itertools.product(range(len(d.facilities)), repeat=len(d.customers))]
    best = min(c for c in costs if c is not None)
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])


def test_supplier_selection_reference():
    p, d, ev, out = qubo_optimum("supply_chain.supplier_selection")
    costs = [supplier_cost(d, [s for s, b in enumerate(bits) if b])
             for bits in itertools.product([0, 1], repeat=len(d.suppliers))]
    best = min(c for c in costs if c is not None)
    assert ev.objective == pytest.approx(best) == pytest.approx(out["total_cost"])
    # the regional-concentration penalty must steer away from picking both Shenzhen suppliers
    assert out["suppliers_per_region"].get("CN", 0) <= 1


# ------------------------------------------------------------------ manufacturing
def test_job_shop_reference():
    from qopt.industries.manufacturing_ext import schedule_ok
    p, d, ev, out = qubo_optimum("manufacturing.job_shop")
    ops = [(j, k) for j in range(len(d.jobs)) for k in range(len(d.jobs[j].operations))]
    best = INF
    for starts in itertools.product(range(d.horizon + 1), repeat=len(ops)):
        st = dict(zip(ops, starts))
        if any(st[(j, k)] + d.jobs[j].operations[k].duration > d.horizon for j, k in ops):
            continue
        prec, over = schedule_ok(d, st)
        if prec and over:
            best = min(best, sum(d.w(j) * (st[(j, len(job.operations) - 1)] + job.operations[-1].duration)
                                 for j, job in enumerate(d.jobs)))
    assert ev.objective == pytest.approx(best) == pytest.approx(out["weighted_completion"])
