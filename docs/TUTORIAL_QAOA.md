# Tutorial: from a constrained problem to QAOA, in Python

All code below runs against the `qopt` package (`backend/`), e.g. `python -i` from `backend/`.

## 1. Build a constrained model

```python
from qopt.core import Model, quicksum, validate_compiled

m = Model("knapsack")
x = m.binaries(["a", "b", "c", "d"])
m.maximize(6*x[0] + 5*x[1] + 4*x[2] + 3*x[3])
m.add_constraint(4*x[0] + 3*x[1] + 2*x[2] + 1*x[3] <= 6, "capacity")
cm = m.compile()
print(cm.summary()["penalties"], cm.slack_variables)
```

The inequality becomes `4a + 3b + 2c + d + s = 6` with slack `s ∈ {0..6}` encoded by bits with weights
1, 2, 3 (every value representable, none outside the range), then penalised as `P(·)²` with
`P = Σ|objective coefficients| + 1 = 19`.

## 2. Prove the formulation is exact

```python
rep = validate_compiled(cm)
rep.passed, rep.best_feasible_objective, rep.best_feasible
```

This enumerates every decision assignment, evaluates the original objective and constraints directly,
and checks that (a) feasible energies equal the objective, (b) every infeasible energy is higher than the
best feasible one, (c) the QUBO minimum is feasible-optimal, (d) QUBO ↔ Ising equivalence.

## 3. QUBO → Ising

```python
ising = cm.qubo.to_ising()      # x_i = (1 - z_i)/2 ; bit 0 ↔ z=+1 ↔ |0>
ising.h, ising.J, ising.offset
```

## 4. QAOA

```python
from qopt.quantum import QAOAConfig, run_qaoa
r = run_qaoa(cm.qubo, QAOAConfig(p=2, optimizer="L-BFGS-B", restarts=3, shots=4096), compiled=cm)
r.expected_energy, r.approximation_ratio, r.ground_state_probability
r.best_sample          # feasible-first ranking, objective in the original sense
```

The cost unitary is `exp(-iγ H_C / s)` with `s = max |Ising coefficient|` so typical good angles lie in
`γ ∈ [0, π]` regardless of problem units; gradients are exact (adjoint method).

## 5. The same circuit in Qiskit

```python
from qopt.quantum.circuits import build_qaoa_circuit, bind
qc, g, b, scale = build_qaoa_circuit(cm.qubo, p=2, measure=True)
bound = bind(qc, g, b, r.gammas, r.betas)
```

Qiskit count keys are big-endian; convert with `qopt.quantum.counts_from_qiskit(counts, n)` to get
variable-order assignment strings.

## 6. Classical baselines

```python
from qopt.solvers import exhaustive, milp_solve, simulated_annealing
exhaustive(cm.qubo).best_energy, milp_solve(cm.qubo).optimal
```
