# Architecture

## 1. Layering (dependency order)

```
                 ┌──────────────────────────────────────────────────────┐
 frontend/       │ React + TypeScript + Tailwind dashboard (24 pages)    │
                 └──────────────────────────┬───────────────────────────┘
                                            │ HTTPS / JSON (JWT or API key)
                 ┌──────────────────────────▼───────────────────────────┐
 qopt/api        │ FastAPI routers · auth · RBAC · rate limit · audit    │
                 └───┬──────────────┬──────────────┬──────────────┬─────┘
 qopt/agents     ┌───▼───────┐ ┌────▼──────┐ ┌─────▼─────┐ ┌──────▼─────┐
                 │ Claude    │ │ hybrid    │ │ industries│ │ jobs / db  │
                 │ agents +  │ │ engine +  │ │ (finance, │ │ SQLAlchemy │
                 │ orchestr. │ │ selector  │ │ health…)  │ │ + Alembic  │
                 └───┬───────┘ └────┬──────┘ └─────┬─────┘ └────────────┘
                     │ tools        │              │
                 ┌───▼──────────────▼──────────────▼─────────────────────┐
 qopt/quantum    │ QAOA engine · statevector sim · Qiskit circuits ·      │
 qopt/providers  │ provider registry (Aer, IBM Runtime, Braket, D-Wave)  │
                 ├────────────────────────────────────────────────────────┤
 qopt/solvers    │ brute force · simulated annealing · tabu · greedy ·    │
                 │ MILP (SciPy/HiGHS)                                    │
                 ├────────────────────────────────────────────────────────┤
 qopt/core       │ Expr/Model builder · QUBO · Ising · penalties ·        │
                 │ preprocessing · exhaustive validation                 │
                 └────────────────────────────────────────────────────────┘
```

Lower layers never import upper layers. `qopt.core` depends only on NumPy/SciPy.

## 2. Mathematical conventions (single source of truth)

These conventions are enforced by tests in `backend/tests/`.

* **QUBO energy**: `E(x) = offset + Σ_i a_i x_i + Σ_{i<j} b_ij x_i x_j`, `x ∈ {0,1}^n`.
* **Matrix form**: upper-triangular `Q` with `Q_ii = a_i`, `Q_ij = b_ij (i<j)`, so `E(x) = xᵀQx + offset`
  (uses `x_i² = x_i`). The symmetric form `(Q+Qᵀ)/2` with the same diagonal gives the identical energy;
  both are exported and import accepts either (`convention` field).
* **Spin mapping**: `x_i = (1 − z_i)/2`, `z_i ∈ {+1, −1}`. Bit 0 ↔ `z=+1` ↔ qubit `|0⟩`
  (eigenvalue of Pauli Z), which is the convention of Qiskit and of every gate-based backend.
* **Ising Hamiltonian**: `H = c + Σ h_i Z_i + Σ_{i<j} J_ij Z_i Z_j`, with
  `h_i = −a_i/2 − Σ_j b_ij/4`, `J_ij = b_ij/4`, `c = offset + Σ a_i/2 + Σ b_ij/4`.
  Annealers (D-Wave) use `s_i = −z_i`-free conventions; the D-Wave adapter converts
  explicitly (`x = (1+s)/2`) — see `providers/dwave.py`.
* **Bit / qubit ordering**: variable `i` ↔ qubit `i`. Basis-state index `k` has
  `x_i = (k >> i) & 1` (little-endian, identical to Qiskit). Qiskit count keys are
  big-endian strings (`key[-1-i]` is qubit `i`); `quantum/bitstrings.py` is the only
  place where this is converted. The platform's public "assignment string" is written in
  **variable order** (`x0 x1 … x_{n-1}`), and every API response states this.
* **QAOA**: `|ψ(γ,β)⟩ = Π_l e^{−iβ_l H_M} e^{−iγ_l H_C} |s⟩`, minimising `⟨H_C⟩`.
  Gates: `RZ(2γh_i)`, `RZZ(2γJ_ij)`, `RX(2β)` for the X mixer.

## 3. Constraint handling

* Equality `Σ c_i x_i = r` → `P (Σ c_i x_i − r)²`.
* Inequality `Σ c_i x_i ≤ r` with integer coefficients → slack `s ∈ [0, r − min LHS]`
  encoded with bounded binary expansion (coefficients 1,2,4,…,remainder) so every slack
  value is representable and no value outside the range is; then equality penalty.
  Non-integer inequality coefficients are rejected unless an explicit `resolution` is
  given (they are then scaled and rounded — the rounding error is reported, never hidden).
* **Automatic penalty**: `P = (Σ|objective coefficients|) + 1`. For integer-coefficient
  constraints any violation contributes `≥ P > max f − min f`, so every infeasible
  assignment has higher energy than every feasible one. Penalties are always recorded
  in the compiled model and constraints are always re-checked on the original variables.

## 4. Execution kinds (honest labelling)

| kind                      | meaning                                     | real hardware |
|---------------------------|---------------------------------------------|---------------|
| `classical`               | classical algorithm on CPU                  | no            |
| `statevector_simulator`   | exact NumPy / Qiskit statevector            | no            |
| `shot_simulator`          | sampled simulator (Aer)                     | no            |
| `qpu_gate`                | gate-model QPU (IBM, IonQ, Rigetti, …)      | yes           |
| `qpu_annealer`            | quantum annealer (D-Wave) — **not QAOA**    | yes           |

`is_real_hardware` is set only from provider backend metadata, never from user input.

## 5. Agents

`qopt/agents` implements a Claude tool-use loop over a tool registry. Each agent has a
role prompt and an allow-list of tools (permissions). The orchestrator enforces
max-iteration, token and cost budgets, logs every call, and turns any tool marked
`requires_approval` (QPU submission) into an approval request instead of executing it.
Without `ANTHROPIC_API_KEY` the agents report themselves unavailable; the underlying
tools stay callable directly via the API.

## 6. Persistence & jobs

SQLAlchemy 2 models, SQLite by default, PostgreSQL via `QOPT_DATABASE_URL`.
Alembic migrations in `backend/alembic`. Long jobs run on a bounded thread pool with
timeouts and status stored in the `jobs` table (Redis is optional — see DEPLOYMENT.md).
