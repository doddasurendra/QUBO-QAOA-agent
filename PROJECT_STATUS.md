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
| 9 | Browser E2E tests (Playwright, all 24 pages, CI job) + the bugs they found | done | `3be2f9c`, `cdba55b` |
| 10 | E2E in Firefox and WebKit as well as Chromium (94 tests), CI browser matrix | done | `f26a147` |
| 11 | axe-core WCAG 2.1 A/AA audit of every page + all violations fixed | done | `99372bc` |
| 12 | Regression after a11y fixes (93 functional tests, per-browser runs) + one-command production launcher, app running locally | done | `011dd3d` |
| 13 | Setup token for first admin; public cloud deployment on Fly.io (https://qopt-quantum-c4da.fly.dev) | done | `efec4d3`, `81b5f7c` |
| 14 | Automated backups on Fly (owner chose SQLite + backups over Managed Postgres at ≥ $38/month): 30-day volume snapshots, daily integrity-checked in-app backups, off-site download script, tested restore | done | `52e56f6` |
| 15 | Deep health check, GitHub Actions uptime monitor (alert + recovery verified live), external-monitor and custom-domain guides (owner has no domain yet); first CI runs fixed (frontend dependency vulnerabilities, Linux worker-thread crash) | done | `1496999` + see `git log` |

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
| Backups | SQLite online-backup copies with `PRAGMA integrity_check`, scheduler (daily, keep 14), pruning, restore with automatic pre-restore copy, CLI (`python -m qopt.services.backup`), admin API + UI card, off-site download script; Fly volume snapshots kept 30 days | `tests/test_backup.py` (7, incl. restore round-trip and corrupt-file refusal) |
| API & security | JWT + hashed API keys, RBAC admin/researcher/viewer, bootstrap-once admin, login throttling, per-user & per-IP rate limits, upload limits, schema validation, job quotas & timeouts, approval workflow, audit log with secret redaction, security headers, structured JSON logs; production refuses missing or weak JWT secrets | `tests/test_api.py` (16), `tests/test_deployment.py` (6) |
| Frontend | 24 pages wired to real endpoints, industry templates grouped by sector, execution-kind badges, SAMPLE data labelled, form labels linked with `htmlFor`/`id` | `tsc` clean, `vite build` OK; **94 Playwright browser E2E tests** in Chromium, Firefox and WebKit against the real backend (below) |
| Accessibility | axe-core 4.10 with WCAG 2.0/2.1 A + AA rules on the login screen, all 24 pages, result views (compiled QUBO, validation, circuit, industry formulation), hovered buttons and the mobile menu: **0 violations**. Fixed to get there: contrast of sidebar labels, status text, secondary text on tinted rows/bubbles and button hover states; names for every unlabelled input/select/textarea/checkbox and icon-only button; keyboard access + focus ring for every scroll region; screen-reader text for ✓/✗ | `frontend/e2e/04-accessibility.spec.ts` (28 checks, chromium) |
| Browser E2E | Playwright in **Chromium 131, Firefox 132 and WebKit 18.2** against the real backend and production build: admin bootstrap via the UI, all 24 pages via the sidebar, every optimisation workflow (builder → validation → matrix/CSV → Ising → circuit/QASM → QAOA → simulator → classical → hybrid → industry → benchmark → report download → experiment history), RBAC for admin/researcher/viewer, API keys, datasets, research upload/search, agents-unavailable state, hardware approval reject + refused approve, admin config/audit, docs, sign-out, mobile layout. Any console error, uncaught exception, 5xx or unexpected 4xx fails a test | `frontend/e2e/`: 1 setup + 31 tests × 3 browsers = 94, all passed in two consecutive full runs; after the accessibility changes re-run per browser (exactly as the CI matrix jobs run): chromium 32/32, firefox 32/32, webkit 32/32; CI matrix job `e2e (chromium / firefox / webkit)` |
| Deployment | Dockerfile (installs the package, runs from `/app`, non-root, healthcheck), `.dockerignore`, docker-compose with PostgreSQL, `.env.example` covering every setting, GitHub Actions CI | installed-package runtime verified live, 12/12 checks (below); `docker build` not run here |

## Tests

- **Passed:** backend `pytest` **178 / 178** (core 34, solvers 13, QAOA 23, industries/hybrid 36, industry
  reference solvers 22, agents 11, API 18, deployment 6, backups 7, health/monitor 7, native-thread regression 1).
  **GitHub CI fully green** (run 43572749019: backend, frontend, e2e chromium/firefox/webkit, docker). After the dependency upgrades
  (Playwright 1.65), the full chromium E2E + accessibility suite passed locally (60 tests; one browser crash at
  0.1 GB free memory, passed on re-run); firefox/webkit run in the CI matrix. **Browser E2E 94 / 94** (Playwright: Chromium,
  Firefox, WebKit; two consecutive clean full runs). Frontend `tsc` + `vite build` clean. Two live
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
- **Browser coverage:** E2E runs Playwright's builds of Chromium, Firefox and WebKit. WebKit approximates Safari but is
  not the shipping Safari on macOS/iOS, and none of the runs was on a real phone (mobile is an emulated viewport).
  Tests check behaviour, not visual appearance (no screenshot comparison). The installed Microsoft Edge crashed under
  automation after file downloads, so local runs use Playwright's pinned Chromium.
- **Accessibility limits:** axe finds roughly a third to a half of WCAG issues; it cannot judge keyboard flow, focus
  order, screen-reader announcements of live updates (e.g. job progress), or whether labels are meaningful. No manual
  screen-reader (NVDA/VoiceOver) or keyboard-only walkthrough has been done. The audit runs in light mode only (dark
  mode colours were chosen to pass but are not audited), and agent-chat result bubbles cannot be audited without an
  API key. Charts (Recharts, SVG heatmaps) expose a label but no tabular alternative of their data.
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
- **CI history:** the first CI runs on GitHub (after the code was pushed) all failed and went unnoticed for four
  pushes. Causes, both fixed: (1) `npm audit` high-severity advisories in DOMPurify 3.2.4 and React Router 6.28.0,
  which shipped on the live site (upgraded to 3.4.17 / 6.30.6); (2) a segfault in Qiskit (`CircuitData()`) on GitHub's Linux
  runner. Root cause, isolated by bisecting on the runner: with **Qiskit ≥ 2.5** (2.5.2, 2.6.1, 2.6.2 crash; 2.4.2
  does not), building circuits in a short-lived asyncio event-loop thread, letting it exit, then building circuits in
  a second one crashes, unless Qiskit was first used in the main thread. Minimal repro: a bare FastAPI app with a
  circuit in its lifespan, started twice under TestClient. Not our code, not the OS image (same on ubuntu-24.04),
  not thread stack size or faulthandler (both tested and ruled out). Fix: `qopt.api.app` warms Qiskit up in the
  main thread at import (uvicorn and pytest import it there); the earlier stack-size workaround was removed;
  `tests/test_native_threads.py` runs the crashing pattern in a subprocess. Not reported upstream yet. Dev tooling upgraded: Vite 5.4.21, PostCSS 8.5.33, Playwright 1.65.1.
- **Accepted dependency risks (documented, not fixed):** React Router 6 has two moderate advisories (open redirect via
  backslash URLs in `<Link>`/`useNavigate`; SSR error deserialisation). The app passes only fixed paths and numeric
  ids to `<Link>`, never calls `navigate()` with user input, and does not use SSR; the fix is React Router 7 (major).
  Vite 5 has advisories affecting only its **dev server**, which is never used in production or CI (`vite build`
  only); the fix is Vite 8 (major).
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
- **Production on this machine (no Docker):** `powershell -ExecutionPolicy Bypass -File scripts\run-production.ps1`
  → **http://localhost:8080**. It creates `.env` with random secrets if missing, installs the backend as a package into
  `.run/` (same layout as the Docker image), serves API + UI in production mode with a persistent SQLite DB
  (`.run/qopt.db`). Started and verified on 2026-11-14 (health, UI, OpenAPI, migrations).
- Docker: `docker compose up -d --build` (uses the same `.env`), then `curl http://localhost:8000/api/health`.

## Live deployment

**https://qopt-quantum-c4da.fly.dev** — Fly.io, region Singapore, deployed 2026-11-14 from commit `efec4d3` + the
Fly configuration. Verified live: `/api/health` ok, SPA over HTTPS (HTTP redirects to HTTPS), security headers,
OpenAPI, unknown API paths 404, admin bootstrap **refused without the setup token** (403), migrations applied to the
1 GB volume, database owned by the unprivileged `qopt` user, machine started with its health check passing.
Simulator mode only (no quantum-hardware or Anthropic credentials set on Fly).

The administrator account has **not** been created yet: the owner creates it on first visit with the setup token
from `.run/fly-secrets.env` (git-ignored, on the deploying machine).

**The Fly account is on a free trial:** Fly stops the machine every 5 minutes ("Trial machine stopping … add a credit
card"); the proxy restarts it on the next request (cold start of several seconds). Until the owner adds a card at
https://fly.io/trial, scheduled in-app backups (first one due 10 min after start) and jobs running at the 5-minute
mark cannot complete. Daily volume snapshots are unaffected. The earlier "always on" description was wrong for a trial
account.

**Monitoring:** `/api/health/deep` (database, migrations, backup freshness, disk) is polled every ~10 min by the
GitHub Actions `uptime` workflow, which opens an `uptime-alert` issue on failure and closes it on recovery. Both
paths were exercised against the live site (issue #1 opened by a deliberately failing URL, then closed by a healthy
run). An external monitor (UptimeRobot / Better Stack) is documented in `docs/DEPLOYMENT.md` but needs the owner's
account. Custom domain: none yet; one-command setup documented.

## Docker status

The `Dockerfile` is verified: built by Fly's remote builder and running in production (above). `docker compose up`
with PostgreSQL has **not** been run: Docker Desktop is not installed on this machine (it needs WSL2 / Virtual
Machine Platform enabled by the owner, admin rights, a reboot and ≈ 2–4 GB free RAM).

## Next implementation tasks

0. Owner: add a card at https://fly.io/trial (machine stops every 5 min on the trial), create the admin account, set up
   the external monitor, and add a custom domain when one is available.
1. Production hardening on Fly: schedule `scripts\download-backup.ps1`
   (e.g. Windows Task Scheduler, weekly); PostgreSQL (Fly Managed Postgres, ≥ $38/month) if high availability or
   multiple app machines are needed, plus a CI job running the suite against PostgreSQL.
2. With credentials: a real IBM job end-to-end through the approval flow; Braket/D-Wave integration tests.
3. With an API key: agent evaluations on the three natural-language example prompts; tune prompts and effort.
4. Manual screen-reader + keyboard-only review; audit dark mode; live-region announcements for job progress; data-table
   alternatives for charts; visual regression; real Safari / mobile devices; code-split the bundle.
5. Redis-backed job queue and rate limiting for multi-replica deployments; cooperative cancellation.
6. Slack-free encodings for the slack-heavy modules so they fit simulator limits; lead times and plant capacity
   in multi-echelon replenishment; scenario-based (stochastic) renewable planning.
7. Hardware-aware compilation analysis (routing overhead, estimated fidelity) in the solver selector.
