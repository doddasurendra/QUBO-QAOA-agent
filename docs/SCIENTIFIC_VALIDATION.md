# Scientific validation report

Generated 2026-11-13T10:15:47.912598+00:00 by `backend/scripts/generate_reports.py` · qopt 0.1.0 · Python 3.12.0 · NumPy 2.5.4

Every check below was executed; nothing is hand-entered.

## 1. QUBO ↔ Ising equivalence (exhaustive over all 2ⁿ assignments)

| n | seed | assignments | max abs error | round-trip error | pass |
|---|---|---|---|---|---|
| 4 | 0 | 16 | 2.22e-16 | 0.00e+00 | ✅ |
| 4 | 1 | 16 | 2.22e-16 | 2.22e-16 | ✅ |
| 4 | 2 | 16 | 8.88e-16 | 8.88e-16 | ✅ |
| 4 | 3 | 16 | 4.44e-16 | 4.44e-16 | ✅ |
| 4 | 4 | 16 | 4.44e-16 | 2.22e-16 | ✅ |
| 8 | 0 | 256 | 2.66e-15 | 8.88e-16 | ✅ |
| 8 | 1 | 256 | 1.33e-15 | 8.88e-16 | ✅ |
| 8 | 2 | 256 | 3.55e-15 | 1.78e-15 | ✅ |
| 8 | 3 | 256 | 1.78e-15 | 1.78e-15 | ✅ |
| 8 | 4 | 256 | 1.78e-15 | 8.88e-16 | ✅ |
| 12 | 0 | 4096 | 7.11e-15 | 1.78e-15 | ✅ |
| 12 | 1 | 4096 | 4.88e-15 | 1.78e-15 | ✅ |
| 12 | 2 | 4096 | 7.99e-15 | 1.78e-15 | ✅ |
| 12 | 3 | 4096 | 1.07e-14 | 3.55e-15 | ✅ |
| 12 | 4 | 4096 | 7.11e-15 | 3.55e-15 | ✅ |
| 16 | 0 | 65536 | 1.42e-14 | 3.55e-15 | ✅ |
| 16 | 1 | 65536 | 9.77e-15 | 1.78e-15 | ✅ |
| 16 | 2 | 65536 | 8.88e-15 | 3.55e-15 | ✅ |
| 16 | 3 | 65536 | 1.78e-14 | 3.55e-15 | ✅ |
| 16 | 4 | 65536 | 1.95e-14 | 3.55e-15 | ✅ |

## 2. Constrained formulations: penalty exactness (industry examples)

For every decision assignment: feasible ⇒ QUBO energy = objective; infeasible ⇒ energy > best feasible; QUBO argmin is a feasible optimum.

| problem | decision vars | slack vars | feasible / total | best objective | pass |
|---|---|---|---|---|---|
| finance.portfolio | 6 | 4 | 52 / 64 | -0.3275 | ✅ |
| finance.investment_allocation | 9 | 0 | 43 / 512 | -0.0562222 | ✅ |
| finance.fraud_feature_selection | 8 | 0 | 56 / 256 | -0.996815 | ✅ |
| finance.transaction_scheduling | 11 | 10 | 18 / 2048 | 6 | ✅ |
| healthcare.staff_scheduling | 11 | 7 | 36 / 2048 | 5 | ✅ |
| healthcare.operating_room_scheduling | 16 | 16 | 88 / 65536 | 2 | ✅ |
| healthcare.clinical_trial_sites | 8 | 14 | 23 / 256 | 355 | ✅ |
| healthcare.compound_selection | 8 | 0 | 56 / 256 | -1.83 | ✅ |
| telecom.base_station_assignment | 12 | 6 | 26 / 4096 | 7 | ✅ |
| telecom.spectrum_allocation | 15 | 0 | 243 / 32768 | 0.54 | ✅ |
| telecom.network_routing | 7 | 6 | 4 / 128 | 12.3333 | ✅ |
| energy.ev_charging | 9 | 3 | 21 / 512 | 33.5 | ✅ |
| energy.unit_commitment | 12 | 9 | 75 / 4096 | 335 | ✅ |
| energy.battery_scheduling | 14 | 0 | 70 / 16384 | -72 | ✅ |
| energy.renewable_allocation | 6 | 5 | 47 / 64 | 3.5 | ✅ |
| energy.demand_response | 18 | 4 | 124 / 262144 | 102.5 | ✅ |
| logistics.delivery_routing | 9 | 0 | 6 / 512 | 14 | ✅ |
| logistics.vehicle_routing | 11 | 6 | 10 / 2048 | 38.48 | ✅ |
| logistics.cargo_loading | 10 | 6 | 108 / 1024 | 31 | ✅ |
| logistics.dock_scheduling | 16 | 0 | 36 / 65536 | 4 | ✅ |
| manufacturing.machine_scheduling | 8 | 0 | 8 / 256 | 72 | ✅ |
| manufacturing.job_shop | 12 | 0 | 26 / 4096 | 6 | ✅ |
| manufacturing.production_planning | 18 | 22 | 21 / 262144 | 39 | ✅ |
| supply_chain.facility_location | 18 | 9 | 192 / 262144 | 90 | ✅ |
| supply_chain.supplier_selection | 7 | 6 | 69 / 128 | 25 | ✅ |

Each module's optimum is additionally checked against an independent brute-force solver written directly from the problem definition (no Model / QUBO): `tests/test_industries_reference.py`.

## 3. Classical solvers vs exhaustive optimum (random QUBOs, n = 14, 10 seeds)

| solver | optimum found | max energy gap |
|---|---|---|
| milp_highs | 10/10 | 3.55e-15 |
| simulated_annealing | 10/10 | 8.88e-16 |
| tabu_search | 10/10 | 8.88e-16 |

## 4. QAOA unitary: NumPy simulator vs Qiskit `Statevector`

| n | p | mixer | fidelity |
|---|---|---|---|
| 4 | 1 | x | 1.000000000000 |
| 6 | 3 | x | 1.000000000000 |
| 8 | 2 | x | 1.000000000000 |
| 6 | 2 | xy_ring | 1.000000000000 |

## 5. Known result: p = 1 QAOA on the 8-ring MaxCut

Farhi, Goldstone & Gutmann (2014): for 2-regular graphs the optimal p = 1 expected cut is 3/4 of the edges.

- Expected cut found: **6.000000**; theory 0.75 × 8 = **6.000000**
- Optimal angles: γ = 1.9635 (on H_C / 0.5), β = 1.1781

## 6. QAOA depth study (MaxCut, random 3-regular graph n = 10, INTERP initialisation)

| p | ⟨cut⟩ | approximation ratio | P(optimal cut) | evaluations |
|---|---|---|---|---|
| 1 | 10.2264 | 0.7866 | 0.1257 | 24 |
| 2 | 11.2999 | 0.8692 | 0.2960 | 72 |
| 3 | 12.0573 | 0.9275 | 0.4859 | 139 |
| 4 | 12.3109 | 0.9470 | 0.5982 | 210 |

Increasing p improved results here with warm-started (INTERP) parameters; this is not guaranteed for cold-started optimisation or under hardware noise.

## 7. Constraint-preserving mixer

Tested in `tests/test_qaoa.py::test_xy_mixer_matches_qiskit_and_preserves_one_hot`: probability mass outside the one-hot subspace stays < 1e-12 for every layer.

## Limitations

- Exhaustive validation is limited to ≤ 20 decision / 22 QUBO variables.
- QAOA results here are exact noiseless simulation. No real-QPU runs were performed (no credentials configured).
- Penalty dominance is guaranteed for integer-coefficient constraints; non-integer equality constraints are flagged with a warning and must be checked via `validate_compiled`.

Total generation time: 41.7 s
