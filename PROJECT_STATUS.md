# PROJECT_STATUS

_Last updated: 2026-11-13 · version 0.1.0_

## Summary

Built from an empty repository. The mathematical engine, QAOA engine, classical solvers, hybrid engine,
provider framework, 10 Claude agents, 6 industry modules, persistence, REST API with security controls,
and a 24-page React dashboard are implemented and tested. **Everything runs in SIMULATOR mode**: no quantum
hardware credentials and no Anthropic API key were available, so no real-QPU job and no live Claude call
has been made.

## Completed (implemented + tested)

| area | what | evidence |
|---|---|---|
| QUBO engine | Expr/Model builder, linear/quadratic terms, equality & inequality (exact bounded binary slack), quadratic `x·y == 0` constraints, auto penalty with proof bound, upper/symmetric/sparse matrices, JSON serialization, matrix import (any convention), normalization, safe variable fixing, infeasibility detection | `tests/test_core_qubo.py` (33) |
| Ising | QUBO→Ising, Ising→QUBO, spin/bit maps, Qiskit-ordered Pauli terms | exhaustive equivalence, errors ≤ 2e-14 (`docs/SCIENTIFIC_VALIDATION.md` §1) |
| Validation framework | exhaustive: feasible energy = objective, penalty dominance, argmin feasibility, Ising equivalence | all 6 industry examples pass (§2) |
| Classical solvers | exhaustive, MILP (HiGHS, sign-aware Fortet), simulated annealing (vectorised), tabu, greedy | `tests/test_solvers.py`; 10/10 optimal vs exhaustive (§3) |
| QAOA | statevector simulator, X and ring-XY mixers, custom `Mixer` interface, adjoint gradients, COBYLA/Nelder-Mead/Powell/L-BFGS-B/BFGS/SLSQP/SPSA/Adam, linear-ramp/random/INTERP init, restarts, history, sampling, feasibility ranking, approximation ratio, P(ground) | fidelity 1.0 vs Qiskit (§4); 8-ring MaxCut p=1 = 6.000000 vs theory 6 (§5); `tests/test_qaoa.py` (23) |
| Circuits | Qiskit circuit, gate list for UI, OpenQASM 3, text diagram; Aer bit-order verified | `tests/test_qaoa.py` |
| Providers | Aer (ideal + synthetic noise), IBM Runtime (SamplerV2), Amazon Braket (native circuit; IonQ/Rigetti/IQM via ARNs), D-Wave annealer (labelled `qpu_annealer`); honest status; approval enforced | mocked IBM backend refused without approval; missing SDK/creds → explicit errors |
| Hybrid engine | transparent recommendations with reasons, execution, ranking vs proven/best optimum, no-advantage note | `tests/test_industries_hybrid.py` |
| Industries (23 modules) | **Supply chain:** capacitated facility location (network design), risk-aware supplier selection · **Manufacturing (added):** multi-product production planning (lot sizing with inventory, setups, shared capacity) · **Finance:** portfolio selection, discrete investment allocation (multi-bit weights), fraud-detection feature selection, transaction settlement scheduling · **Healthcare:** staff scheduling, operating-room scheduling, clinical-trial site selection, drug-discovery compound subset selection · **Telecom:** base-station assignment, spectrum allocation, capacity-aware network routing · **Energy:** EV charging, unit commitment, battery arbitrage · **Logistics:** delivery TSP, capacitated vehicle routing (cluster-first), cargo loading (multiple knapsack), warehouse dock scheduling · **Manufacturing:** machine load balancing, time-indexed job-shop — each with schema, formulation, limitations, interpretation with domain checks, SAMPLE data, API | exhaustive validation of every example (`SCIENTIFIC_VALIDATION.md` §2) **and** an independent brute-force solver per new module written from the problem definition (`tests/test_industries_reference.py`, 17 tests) |
| Quadratic logical constraints | `x·y == 0` and implication constraints such as `x·(1−z) == 0` (exact P·lhs penalty, no slack); non-negativity proved by exact enumeration of the constraint's variables (≤ 16), unsatisfiable ones rejected at compile time | `tests/test_industries_hybrid.py::test_quadratic_equality_conflict_constraint` |
| Agents | 10 roles, tool allow-lists, manual Claude tool-use loop (official SDK, `claude-opus-5-5`, explicit effort, server-side refusal fallback), delegation with depth limit, iteration/token/USD budgets, needs-input halt, approval-only hardware tool, usage & cost tracking, persistence of agent-created models | `tests/test_agents.py` (11) with scripted fake client and real tools |
| Persistence | SQLAlchemy 2 models (9 tables), Alembic migration `0001`, SQLite default / PostgreSQL URL | migrations run in every API test |
| API & security | FastAPI: JWT + API keys (hashed), RBAC admin/researcher/viewer, bootstrap-once admin, login throttling, per-user & per-IP rate limits, upload type/size limits, schema validation, job quotas & timeouts, approval workflow, audit log with secret redaction, security headers, structured JSON logs | `tests/test_api.py` (15); live HTTP smoke test 27/27 |
| Frontend | 24 pages, all wired to real endpoints; execution-kind badges on every result; SAMPLE data labelled | `tsc` clean, `vite build` OK; every page's API call exercised by the live smoke test |
| Reports | Markdown/JSON job reports; generated validation & benchmark reports | `docs/SCIENTIFIC_VALIDATION.md`, `docs/BENCHMARK_REPORT.md` |
| Deployment | Dockerfile (non-root, SPA + API), docker-compose with PostgreSQL, `.env.example`, GitHub Actions CI (tests, pip-audit, npm audit, docker build) | written, **not executed here** (see below) |

## Tests

- **Passed:** backend `pytest` **146 / 146** (core 34, solvers 13, QAOA 23, industries/hybrid 32,
  industry reference solvers 17, agents 11, API 16); live HTTP smoke test against a running server **27 / 27**; frontend `tsc` + `vite build` clean.
- **Failed:** none outstanding. During development the tests caught and I fixed: IBM provider importing
  its SDK before the availability check; a delegation permission check that ran after the sub-agent; the
  SPA fallback answering unknown `/api/*` paths with `index.html` (now JSON 404). Two wrong
  hand-computed test expectations were also corrected (the engine was right).

## Not verified / known limitations

- **No real quantum hardware run.** IBM is tested against a mocked service only; the Braket and D-Wave
  submission code is untested against live services.
- **No live Claude API call.** Agent behaviour with the real model is untested; orchestration is tested with a scripted client.
- **Docker / docker-compose / PostgreSQL not run** (Docker is not installed on this machine; tests use SQLite).
- **UI not clicked through in a browser** (the Chrome extension was not connected). Every endpoint each page uses was exercised over HTTP against the live server, and the UI compiles, but layout and interaction bugs may remain. There are no automated UI tests.
- Jobs run on an in-process thread pool; rate limits are in-process; Redis is not implemented → run a single API process.
- Running jobs cannot be interrupted (timeout marks status; late results are stored with `late=true`).
- Statevector QAOA ≤ 22 qubits; exhaustive validation ≤ 20 decision variables. Hardware QAOA for larger
  problems falls back to un-optimised linear-ramp angles (flagged in the result).
- Industry modelling simplifications (each is stated in its module's `limitations`): machine scheduling
  minimises Σ load² (a makespan proxy); job-shop minimises total weighted completion time (not makespan);
  unit commitment ignores economic dispatch, ramp rates and min up/down times; the battery model has no
  efficiency losses; vehicle routing is a cluster-first/route-second heuristic (it matched the exact CVRP
  optimum on the example, which is not guaranteed in general); fraud selection uses Pearson correlation and
  does not train a classifier; compound selection needs upstream activity and similarity scores.
- Production planning: integer units (≤ 7 per product-period), no backlogging, lead times or multi-level bills
  of materials. Facility location: single echelon, single sourcing, deterministic demand. Supplier risk:
  pairwise same-region penalty, not a probabilistic disruption model.
- Production planning (40 qubits) and facility location (27 qubits) exceed the statevector limit; MILP
  proves their optima in about 15–25 s. **Heuristics can miss:** tabu search found the production-planning optimum
  (39) but returned 123 against the true optimum of 90 on the facility-location example.
- Still not built: renewable allocation and demand response as separate modules; multi-echelon supply chains.
- Operating-room scheduling (32 qubits) and other slack-heavy examples exceed the 22-qubit statevector
  limit, so they are classical-only unless hardware is configured. The hybrid engine skips simulated QAOA for them automatically.
- MILP (HiGHS) is slow on QUBOs dominated by squared-penalty terms (about 30 s for the 22-variable
  clinical-trial example on a loaded machine); exhaustive search or tabu is often faster at that size.
- PennyLane, Cirq and OpenFermion are not used; Qiskit plus an independent NumPy simulator cross-check each other. Quantinuum and Azure Quantum are not integrated.
- PDF ingestion needs `pypdf` on the server (installed in the Docker image, not in the dev venv).
- Frontend bundle is ~726 kB (not code-split).
- Benchmarks: small instances only; **no quantum advantage is claimed or demonstrated**.

## Required credentials (all server-side env vars; see `.env.example`)

| capability | needs |
|---|---|
| AI agents | `ANTHROPIC_API_KEY` (Anthropic API billing; separate from a Claude subscription) |
| IBM Quantum | `pip install qiskit-ibm-runtime` + `QISKIT_IBM_TOKEN` (+ `QISKIT_IBM_INSTANCE`) |
| Amazon Braket (IonQ, Rigetti, IQM) | `pip install amazon-braket-sdk` + AWS credentials + `QOPT_BRAKET_S3_BUCKET` |
| D-Wave (annealing) | `pip install dwave-ocean-sdk` + `DWAVE_API_TOKEN` |

## Hardware access status

**None configured — SIMULATOR mode.** Available: local NumPy statevector, Qiskit Aer (ideal + synthetic noise).

## Next implementation tasks

1. With credentials: run a real IBM job end-to-end through the approval flow; add Braket/D-Wave integration tests.
2. With an API key: run agent evaluations on the three NL example prompts; tune prompts and effort.
3. Browser E2E tests (Playwright) for the 24 pages; code-split the bundle.
4. `docker compose up` on a Docker host; run the suite against PostgreSQL.
5. Redis-backed job queue and rate limiting for multi-replica deployments; cooperative cancellation.
6. Multi-echelon supply chain and demand-response modules; slack-free encodings for the slack-heavy modules
   (production planning, operating rooms, facility location) so they fit within simulator limits.
7. Hardware-aware compilation analysis (routing overhead, estimated fidelity) in the solver selector.
