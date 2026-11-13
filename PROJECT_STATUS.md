# PROJECT_STATUS

_Last updated: 2026-11-13 · version 0.1.0_

## Summary

Built from an empty repository: mathematical (QUBO/Ising) engine, QAOA engine, classical solvers, hybrid
engine, quantum-provider framework, 10 Claude agents, **27 industry modules**, persistence, a REST API with
security controls, a 24-page React dashboard, and a deployment setup verified from an installed package.
**Everything runs in SIMULATOR mode**: no quantum-hardware credentials and no Anthropic API key were available,
so no real-QPU job and no live Claude API call has been made.

## Milestones

| # | milestone | status | commit |
|---|---|---|---|
| 1 | Core QUBO/Ising engine, classical solvers, QAOA, providers, hybrid engine, first 6 industry modules | done | `70bbd1d` |
| 2 | Claude agent orchestrator, persistence, FastAPI with auth/RBAC/approvals/jobs | done | `8852b8c` |
| 3 | Frontend (24 pages), reports, docs, deployment config | done | `894cfea` |
| 4 | 14 more industry modules + independent reference tests | done | `a9b96a5` |
| 5 | Production planning, facility location, supplier selection | done | `ba60972` |
| 6 | Renewable allocation, demand response | done | `09642b0` |
| 7 | Multi-echelon supply chain (two-echelon network design, multi-echelon replenishment) | done | `3f29e69` |
| 8 | Installed-package deployment fix (migrations packaged, configurable paths, Docker/env hardening) | done | `9c885a2` |
| 9 | Browser E2E tests (Playwright, 32 tests, all 24 pages, CI job) + the bugs they found | done | see `git log` |

## Completed (implemented + tested)

| area | what | evidence |
|---|---|---|
| QUBO engine | Expr/Model builder, linear/quadratic terms, equality & inequality (exact bounded binary slack), auto penalty with proof bound, upper/symmetric/sparse matrices, JSON serialisation, matrix import (any convention), normalisation, safe variable fixing, infeasibility detection, vectorised exhaustive validation | `tests/test_core_qubo.py` (34) |
| Quadratic logical constraints | `x·y == 0` conflicts and implications such as `x·(1−z) == 0` (exact P·lhs penalty, no slack); non-negativity proved by exact enumeration of the constraint's variables (≤ 16); unsatisfiable ones rejected at compile time | `tests/test_industries_hybrid.py` |
| Ising | QUBO→Ising, Ising→QUBO, spin/bit maps, Qiskit-ordered Pauli terms | exhaustive equivalence, errors ≤ 2e-14 (`docs/SCIENTIFIC_VALIDATION.md` §1) |
| Classical solvers | exhaustive, MILP (HiGHS, sign-aware Fortet), simulated annealing (vectorised), tabu, greedy | `tests/test_solvers.py` (13); 10/10 optimal vs exhaustive (§3) |
| QAOA | statevector simulator, X and ring-XY mixers, custom `Mixer` interface, adjoint gradients, COBYLA / Nelder-Mead / Powell / L-BFGS-B / BFGS / SLSQP / SPSA / Adam, linear-ramp / random / INTERP init, restarts, history, sampling, feasibility ranking, approximation ratio, P(ground) | fidelity 1.0 vs Qiskit (§4); 8-ring MaxCut p=1 = 6.000000 vs theory 6 (§5); `tests/test_qaoa.py` (23) |
| Circuits | Qiskit circuit, gate list for the UI, OpenQASM 3, text diagram; Aer bit order verified | `tests/test_qaoa.py` |
| Providers | Aer (ideal + synthetic noise), IBM Runtime (SamplerV2), Amazon Braket (IonQ/Rigetti/IQM via ARNs), D-Wave annealer (labelled `qpu_annealer`); honest availability status; approval enforced | mocked IBM backend refused without approval; missing SDK/credentials → explicit errors |
| Hybrid engine | transparent recommendations with reasons, execution, ranking against the proven/best optimum, no-advantage note | `tests/test_industries_hybrid.py` |
| Industries (27) | **Finance:** portfolio selection, discrete investment allocation, fraud-detection feature selection, transaction settlement scheduling · **Healthcare:** staff scheduling, operating-room scheduling, clinical-trial site selection, drug-discovery compound selection · **Telecom:** base-station assignment, spectrum allocation, network routing · **Energy:** EV charging, unit commitment, battery arbitrage, renewable portfolio allocation, demand response · **Logistics:** delivery TSP, capacitated vehicle routing, cargo loading, warehouse dock scheduling · **Manufacturing:** machine load balancing, job-shop scheduling, production planning · **Supply chain:** facility location, supplier selection, two-echelon network design, multi-echelon replenishment. Each has a schema, formulation, limitations, interpretation with domain checks, SAMPLE data and API | every example validated exhaustively (§2, 27/27 ✅) **and**, for the 21 later modules, checked against an independent brute-force solver written from the problem definition (`tests/test_industries_reference.py`, 22 tests) |
| Agents | 10 roles, tool allow-lists, manual Claude tool-use loop (official SDK, `claude-opus-5-5`, explicit effort, server-side refusal fallback), delegation with depth limit, iteration/token/USD budgets, needs-input halt, approval-only hardware tool, usage & cost tracking | `tests/test_agents.py` (11), scripted fake client + real tools |
| Persistence | SQLAlchemy 2 models (9 tables), Alembic migration `0001` **shipped inside the package** (`qopt/migrations`), SQLite default / PostgreSQL URL | migrations run in every API test and from an installed package |
| API & security | JWT + hashed API keys, RBAC admin/researcher/viewer, bootstrap-once admin, login throttling, per-user & per-IP rate limits, upload limits, schema validation, job quotas & timeouts, approval workflow, audit log with secret redaction, security headers, structured JSON logs; production refuses missing or weak JWT secrets | `tests/test_api.py` (16), `tests/test_deployment.py` (6) |
| Frontend | 24 pages wired to real endpoints, industry templates grouped by sector, execution-kind badges, SAMPLE data labelled, form labels linked with `htmlFor`/`id` | `tsc` clean, `vite build` OK; **32 Playwright browser E2E tests** against the real backend (below) |
| Browser E2E | Playwright + Chromium against the real backend and production build: admin bootstrap via the UI, all 24 pages via the sidebar, every optimisation workflow (builder → validation → matrix/CSV → Ising → circuit/QASM → QAOA → simulator → classical → hybrid → industry → benchmark → report download → experiment history), RBAC for admin/researcher/viewer, API keys, datasets, research upload/search, agents-unavailable state, hardware approval reject + refused approve, admin config/audit, docs, sign-out, mobile layout. Any console error, uncaught exception, 5xx or unexpected 4xx fails a test | `frontend/e2e/`, 32/32 passed in two consecutive runs; CI job `e2e` |
| Deployment | Dockerfile (installs the package, runs from `/app`, non-root, healthcheck), `.dockerignore`, docker-compose with PostgreSQL, `.env.example` covering every setting, GitHub Actions CI | installed-package runtime verified live, 12/12 checks (below); `docker build` not run here |

## Tests

- **Passed:** backend `pytest` **162 / 162** (core 34, solvers 13, QAOA 23, industries/hybrid 36, industry
  reference solvers 22, agents 11, API 17, deployment 6). **Browser E2E 32 / 32** (Playwright, Chromium; two
  consecutive clean runs). Frontend `tsc` + `vite build` clean. Two live
  checks: the HTTP smoke test against a source-tree server (27/27), and the **installed-package** server in
  production mode started from outside the source tree, i.e. the Docker runtime layout (12/12: health,
  OpenAPI, SPA + assets, migrations, login, docs, all modules + samples, a background multi-echelon job, no
  secret leakage).
- **Failed:** none outstanding. Bugs found and fixed along the way:
  - the IBM provider imported its SDK before checking availability;
  - a delegation permission check ran after the sub-agent had already executed;
  - the SPA fallback answered unknown `/api/*` paths with `index.html`;
  - a slow per-row slack completion in validation (now vectorised);
  - single-variable one-hot groups were passed to the XY mixer;
  - an infeasible multi-echelon sample example (now caught by a DC-level check);
  - **installed deployments crashed at startup** (migrations and other paths resolved against a source tree that doesn't exist after install);
  - the Dockerfile copied a missing directory and had no `.dockerignore`;
  - `.env.example` shipped a non-empty placeholder JWT secret;
  - found by the browser E2E suite: jobs launched from the UI were never linked to their experiment, so the
    experiment's job history stayed empty;
  - also found by E2E: `experiment_id` inside job params skipped the ownership check, letting a researcher run jobs on
    (and so read) another user's experiment (fixed and covered by an API test);
  - also found by E2E: form controls were nested inside their `<label>`, so a select's accessible name included all
    of its option text (labels are now linked with `htmlFor`/`id`).

## Not verified / known limitations

- **No real quantum hardware run.** IBM is tested against a mocked service only; the Braket and D-Wave submission
  code is untested against live services.
- **No live Claude API call.** Agent behaviour with the real model is untested; orchestration is tested with a
  scripted client.
- **`docker build` / `docker compose up` and PostgreSQL not run.** Docker, WSL2 and PostgreSQL are not installed on
  this machine, and installing Docker Desktop needs WSL2/Hyper-V enabled with admin rights and a reboot. The
  runtime the image uses (installed package, production mode, same paths) is verified; CI builds the image.
- **Browser coverage:** the E2E suite runs Chromium only (no Firefox/WebKit runs) and checks behaviour, not visual
  appearance (no screenshot comparison). Automated accessibility auditing (e.g. axe) is not included. The installed
  Microsoft Edge crashed under automation after file downloads, so the suite uses Playwright's pinned Chromium.
- Jobs run on an in-process thread pool and rate limits are in-process; Redis is not implemented → run a single API
  process. Running jobs cannot be interrupted (a timeout marks the status; late results are stored with `late=true`).
- Statevector QAOA ≤ 22 qubits; exhaustive validation ≤ 20 decision variables. Slack-heavy examples (operating
  rooms 32, production planning 40, multi-echelon replenishment 35, two-echelon network 30, facility location 27
  qubits) are classical-only unless hardware is configured. MILP proves their optima, but is slow on
  penalty-dominated QUBOs (≈ 15–30 s on a loaded machine).
- **Heuristics can miss:** tabu returned 123 against the true optimum of 90 on the facility-location example. QAOA on
  the 22-qubit demand-response example sampled the optimum but with P(ground) ≈ 0.0004.
- Modelling simplifications (each stated in its module's `limitations`):
  - load balancing (Σ load²) and job-shop (weighted completion) use makespan proxies;
  - unit commitment ignores dispatch, ramps and min up/down times; the battery model has no efficiency losses;
  - vehicle routing is cluster-first/route-second;
  - fraud selection uses Pearson correlation and trains no classifier; compound selection needs upstream scores;
  - production planning allows ≤ 7 units per product-period, with no backlog or lead times;
  - multi-echelon replenishment has zero lead time and an uncapacitated plant;
  - two-echelon design is single-period with unsplittable flows;
  - renewable allocation penalises shortfall and curtailment symmetrically, with deterministic forecasts.
- PennyLane, Cirq and OpenFermion are not used; Qiskit and an independent NumPy simulator cross-check each other.
  Quantinuum and Azure Quantum are not integrated.
- PDF ingestion needs `pypdf` (installed in the Docker image, not the dev venv). Frontend bundle ≈ 726 kB (not
  code-split). Benchmarks use small instances only; **no quantum advantage is claimed or demonstrated**.

## Required credentials (server-side env vars; see `.env.example`)

| capability | needs |
|---|---|
| Deployment | `POSTGRES_PASSWORD`, `QOPT_JWT_SECRET` (≥ 32 random characters) |
| AI agents | `ANTHROPIC_API_KEY` (Anthropic API billing; separate from a Claude subscription) |
| IBM Quantum | `EXTRAS="[ibm]"` + `QISKIT_IBM_TOKEN` (+ `QISKIT_IBM_INSTANCE`) |
| Amazon Braket (IonQ, Rigetti, IQM) | `EXTRAS="[braket]"` + AWS credentials + `QOPT_BRAKET_S3_BUCKET` |
| D-Wave (annealing) | `EXTRAS="[dwave]"` + `DWAVE_API_TOKEN` |

## Hardware access status

**None configured — SIMULATOR mode.** Available: local NumPy statevector, Qiskit Aer (ideal + synthetic noise).

## How to run

- Development: see `README.md` → Quick start (`pytest`, `npm run build`, `uvicorn qopt.api.app:app`).
- Deployment: `cp .env.example .env`, set the two required values, then `docker compose up -d --build`, then
  `curl http://localhost:8000/api/health`. A no-Docker recipe is in `docs/DEPLOYMENT.md`.

## Next implementation tasks

1. On a Docker host: `docker compose up --build`, confirm the container is `healthy`, and run the suite against PostgreSQL.
2. With credentials: a real IBM job end-to-end through the approval flow; Braket/D-Wave integration tests.
3. With an API key: agent evaluations on the three natural-language example prompts; tune prompts and effort.
4. Extend E2E to Firefox/WebKit, add axe accessibility checks and visual regression; code-split the bundle.
5. Redis-backed job queue and rate limiting for multi-replica deployments; cooperative cancellation.
6. Slack-free encodings for the slack-heavy modules so they fit simulator limits; lead times and plant capacity
   in multi-echelon replenishment; scenario-based (stochastic) renewable planning.
7. Hardware-aware compilation analysis (routing overhead, estimated fidelity) in the solver selector.
