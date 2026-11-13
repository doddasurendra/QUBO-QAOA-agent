# Benchmark report

Generated 2026-11-13T08:28:11.099291+00:00 · qopt 0.1.0 · Python 3.12.0 · NumPy 2.5.4

> Small instances, exact optima by enumeration. QAOA is simulated exactly (no noise). These results do not demonstrate quantum advantage.

| problem | n | solver | kind | hit rate | norm. gap (mean±std) | runtime s (mean) | approx. ratio | P(ground) |
|---|---|---|---|---|---|---|---|---|
| maxcut_gnp | 6 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2043 |  |  |
| maxcut_gnp | 6 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.1950 |  |  |
| maxcut_gnp | 6 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0004 |  |  |
| maxcut_gnp | 6 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0182 |  |  |
| maxcut_gnp | 6 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0200 | 0.780 | 0.217 |
| maxcut_gnp | 6 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0369 | 0.868 | 0.350 |
| maxcut_gnp | 6 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1162 | 0.898 | 0.476 |
| maxcut_gnp | 8 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2673 |  |  |
| maxcut_gnp | 8 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2417 |  |  |
| maxcut_gnp | 8 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0004 |  |  |
| maxcut_gnp | 8 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0468 |  |  |
| maxcut_gnp | 8 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0323 | 0.742 | 0.144 |
| maxcut_gnp | 8 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0717 | 0.886 | 0.463 |
| maxcut_gnp | 8 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1918 | 0.903 | 0.514 |
| maxcut_gnp | 10 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.3604 |  |  |
| maxcut_gnp | 10 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2549 |  |  |
| maxcut_gnp | 10 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0006 |  |  |
| maxcut_gnp | 10 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0862 |  |  |
| maxcut_gnp | 10 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0572 | 0.757 | 0.030 |
| maxcut_gnp | 10 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1880 | 0.858 | 0.143 |
| maxcut_gnp | 10 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.3464 | 0.860 | 0.143 |
| maxcut_3regular | 6 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2293 |  |  |
| maxcut_3regular | 6 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2322 |  |  |
| maxcut_3regular | 6 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0004 |  |  |
| maxcut_3regular | 6 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0178 |  |  |
| maxcut_3regular | 6 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0200 | 0.817 | 0.387 |
| maxcut_3regular | 6 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0409 | 0.933 | 0.729 |
| maxcut_3regular | 6 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1242 | 0.943 | 0.733 |
| maxcut_3regular | 8 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2510 |  |  |
| maxcut_3regular | 8 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2048 |  |  |
| maxcut_3regular | 8 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0004 |  |  |
| maxcut_3regular | 8 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0769 |  |  |
| maxcut_3regular | 8 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0278 | 0.804 | 0.161 |
| maxcut_3regular | 8 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0665 | 0.882 | 0.356 |
| maxcut_3regular | 8 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.2619 | 0.923 | 0.537 |
| maxcut_3regular | 10 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.3142 |  |  |
| maxcut_3regular | 10 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.1946 |  |  |
| maxcut_3regular | 10 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0005 |  |  |
| maxcut_3regular | 10 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0174 |  |  |
| maxcut_3regular | 10 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0480 | 0.791 | 0.085 |
| maxcut_3regular | 10 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1169 | 0.871 | 0.238 |
| maxcut_3regular | 10 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.4100 | 0.908 | 0.372 |
| number_partitioning | 6 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.1818 |  |  |
| number_partitioning | 6 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2009 |  |  |
| number_partitioning | 6 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0005 |  |  |
| number_partitioning | 6 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0424 |  |  |
| number_partitioning | 6 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0185 | 0.937 | 0.124 |
| number_partitioning | 6 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0511 | 0.945 | 0.135 |
| number_partitioning | 6 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1482 | 0.964 | 0.149 |
| number_partitioning | 8 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2386 |  |  |
| number_partitioning | 8 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2233 |  |  |
| number_partitioning | 8 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0004 |  |  |
| number_partitioning | 8 | milp | classical | 1.00 | 0.0000±0.0000 | 0.0746 |  |  |
| number_partitioning | 8 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0366 | 0.952 | 0.060 |
| number_partitioning | 8 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0809 | 0.934 | 0.068 |
| number_partitioning | 8 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.2042 | 0.953 | 0.074 |
| number_partitioning | 10 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2810 |  |  |
| number_partitioning | 10 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2029 |  |  |
| number_partitioning | 10 | greedy_descent | classical | 1.00 | 0.0000±0.0000 | 0.0007 |  |  |
| number_partitioning | 10 | milp | classical | 1.00 | 0.0000±0.0000 | 0.1593 |  |  |
| number_partitioning | 10 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0759 | 0.963 | 0.066 |
| number_partitioning | 10 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.2111 | 0.959 | 0.079 |
| number_partitioning | 10 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.3128 | 0.905 | 0.070 |
| knapsack | 6 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.2890 |  |  |
| knapsack | 6 | tabu_search | classical | 1.00 | 0.0000±0.0000 | 0.2092 |  |  |
| knapsack | 6 | greedy_descent | classical | 0.80 | 0.0000±0.0000 | 0.0004 |  |  |
| knapsack | 6 | milp | classical | 1.00 | 0.0000±0.0000 | 0.1442 |  |  |
| knapsack | 6 | qaoa_p1 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.0826 | 0.969 | 0.003 |
| knapsack | 6 | qaoa_p2 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.1844 | 0.981 | 0.004 |
| knapsack | 6 | qaoa_p3 | statevector_simulator | 1.00 | 0.0000±0.0000 | 0.4261 | 0.988 | 0.006 |
| knapsack | 8 | simulated_annealing | classical | 1.00 | 0.0000±0.0000 | 0.3718 |  |  |
| knapsack | 8 | tabu_search | classical | 0.20 | 0.0000±0.0001 | 0.2052 |  |  |
| knapsack | 8 | greedy_descent | classical | 0.00 | 0.0001±0.0001 | 0.0005 |  |  |
| knapsack | 8 | milp | classical | 1.00 | 0.0000±0.0000 | 0.3143 |  |  |
| knapsack | 8 | qaoa_p1 | statevector_simulator | 0.60 | 0.0000±0.0000 | 0.1967 | 0.977 | 0.001 |
| knapsack | 8 | qaoa_p2 | statevector_simulator | 0.80 | 0.0000±0.0000 | 0.5103 | 0.986 | 0.001 |
| knapsack | 8 | qaoa_p3 | statevector_simulator | 0.80 | 0.0000±0.0000 | 1.2854 | 0.992 | 0.001 |
| knapsack | 10 | simulated_annealing | classical | 0.80 | 0.0000±0.0000 | 0.5176 |  |  |
| knapsack | 10 | tabu_search | classical | 0.00 | 0.0001±0.0000 | 0.2464 |  |  |
| knapsack | 10 | greedy_descent | classical | 0.00 | 0.0001±0.0000 | 0.0006 |  |  |
| knapsack | 10 | milp | classical | 1.00 | 0.0000±0.0000 | 1.2406 |  |  |
| knapsack | 10 | qaoa_p1 | statevector_simulator | 0.40 | 0.0000±0.0000 | 0.8533 | 0.981 | 0.000 |
| knapsack | 10 | qaoa_p2 | statevector_simulator | 0.00 | 0.0000±0.0000 | 3.4196 | 0.990 | 0.000 |
| knapsack | 10 | qaoa_p3 | statevector_simulator | 0.20 | 0.0000±0.0000 | 6.8153 | 0.993 | 0.000 |

## Definitions

- **normalized_gap**: (E_found − E_opt) / (E_max − E_min); 0 = optimal
- **optimum_hit_rate**: fraction of seeds where the proven optimum was found
- **approximation_ratio**: (E_max − ⟨H⟩) / (E_max − E_min) of the QAOA state
- **ground_state_probability**: Σ |⟨z|ψ⟩|² over optimal z

## How to read these numbers

- **QAOA hit rate is not evidence of quantum performance at these sizes.** With 1024 shots and n ≤ 10 (≤ 1024 basis states) sampling covers a large fraction of the whole state space, so even a uniform distribution would often hit the optimum. Use *P(ground)* and the *approximation ratio*, which describe the QAOA state itself.
- **Normalised gap for constrained problems (knapsack)** is divided by the full QUBO energy range, which includes penalty energies; a gap that rounds to 0.0000 can still be a sub-optimal (or infeasible) answer. The hit rate is the meaningful metric there.
- **Deeper is not automatically better.** Where the approximation ratio falls as p grows, the classical parameter optimiser (L-BFGS-B, 2 restarts) did not find better angles for the larger p — the best achievable value is non-decreasing in p, a found value is not.
- Runtimes are wall-clock on the machine listed above and include Python overhead; they are not comparable to optimised C/C++ solvers or to QPU wall-clock times.
- Exact classical methods (exhaustive, MILP) solve every instance here; these instances are far too small to say anything about quantum advantage.
