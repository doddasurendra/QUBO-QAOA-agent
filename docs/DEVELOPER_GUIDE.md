# Developer guide

## Layout

```
backend/
  qopt/core        Expr/Model builder, QUBO, Ising, penalties, preprocessing, exhaustive validation
  qopt/solvers     exhaustive, simulated annealing, tabu, greedy, MILP (SciPy/HiGHS)
  qopt/quantum     statevector QAOA (adjoint gradients), mixers, Qiskit circuits, bit-order helpers
  qopt/providers   Aer, IBM Runtime, Amazon Braket, D-Wave (annealer) + registry
  qopt/hybrid      solver recommendation + hybrid execution + ranking
  qopt/industries  27 industry templates (schema, formulation, interpretation, sample data);
                   *_ext.py, energy_flex.py, supply_chain*.py hold the later modules
  qopt/agents      Claude tool-use orchestrator, 10 agent roles, tool registry
  qopt/services    jobs, audit, security, research search, reports, agent persistence bridge
  qopt/api         FastAPI app and routers
  qopt/db          SQLAlchemy models, session, migrations entry point
  qopt/migrations  Alembic migrations (package data: shipped with every install)
  tests/           pytest suite
  scripts/         report generators
frontend/          Vite + React + TypeScript + Tailwind SPA (24 pages)
docs/              architecture, guides, generated reports
```

## Local development

```powershell
python -m venv .venv; .\.venv\Scripts\pip install -e "backend[dev]"
cd backend; ..\.venv\Scripts\python -m pytest            # full suite
..\.venv\Scripts\uvicorn qopt.api.app:app --reload       # API on :8000, /api/docs
cd ..\frontend; npm install; npm run dev                 # UI on :5173 (proxies /api)
```

`npm run build` produces `frontend/dist`, which the backend serves automatically (single process).

## Browser end-to-end tests (Playwright)

```powershell
cd frontend
npx playwright install chromium firefox webkit   # once: Playwright's pinned browser builds
npm run e2e                         # build the SPA, start the real backend on :8790, run all 3 browsers (94 tests)
npm run e2e:only -- --project=firefox            # one browser, no rebuild (setup always runs in chromium)
npx playwright show-report e2e\.report
```

The suite runs in **Chromium, Firefox and WebKit** (Safari's engine): one setup test plus 31 tests per browser.
Locally the browsers run one after another against one server and database, so every spec tags the data it creates
with `tag()` (the project name), e.g. `my-model-firefox`, `e2e-viewer-webkit@example.com`. Keep doing this for new
tests, and scope locators to a section when another browser's data may be on the page. In CI each browser is a
separate matrix job with its own fresh backend.

`e2e/start-server.mjs` starts uvicorn from `backend/` with a throw-away SQLite DB (`e2e/.work`), real job threads,
the production SPA build, and agents forced unavailable. `auth.setup.ts` bootstraps the admin **through the UI** and
saves tokens; specs inject them into `sessionStorage`. The `problems` fixture fails any test on a browser console
error, an uncaught exception, any 5xx, or a 4xx that the test did not explicitly allow. Specs:
`01-navigation` (all 24 pages via the sidebar, deep links, overview), `02-workflows` (builder → validation → matrix →
Ising → circuit + QASM → QAOA → simulator → classical → hybrid → industry → benchmark → reports → experiment history),
`03-platform` (users/RBAC incl. viewer, API keys, datasets, research upload + search, agents unavailable, hardware
approval reject + refused approve, admin config/audit, usage, docs, sign-out, mobile menu + no horizontal scroll).
The active model is per browser tab, so each test selects it (`useExperiment`). Set `QOPT_PYTHON` if the venv is not
at `<repo>/.venv`, and `PW_CHANNEL=msedge|chrome` to run the chromium project in an installed browser (Edge crashed
after downloads here).

## Conventions you must not break

See `docs/ARCHITECTURE.md §2`. Tests enforce: matrix conventions, the `x = (1 − z)/2` spin map,
little-endian qubit order, Qiskit big-endian key conversion (only in `quantum/bitstrings.py`),
QAOA unitary equality with Qiskit, adjoint gradient = finite differences.

## Adding things

- **Industry problem**: subclass `IndustryProblem` (pydantic `Input`, `build_model`, `interpret`,
  `example`), register in `industries/__init__.py`. `tests/test_industries_hybrid.py` automatically
  validates its example exhaustively — keep examples ≤ 18 decision variables. `interpret` must return at
  least one `*_ok` domain check. Add an independent brute-force reference in
  `tests/test_industries_reference.py` that enumerates domain decisions without using `Model`.
  Prefer slack-free encodings (one-hot state variables, pairwise `x·y == 0` conflicts) where possible:
  they keep qubit counts within simulator range and are compatible with the XY mixer.
- **Mixer**: subclass `quantum.mixers.Mixer` (initial state, components with generators, Qiskit gates).
  Add a fidelity test against Qiskit and a gradient test.
- **Provider**: subclass `providers.base.Provider`; derive `is_real_hardware` from backend metadata only;
  call `_check_approval` before any real submission; register in `providers/registry.py`.
- **Agent tool**: add a `Tool` in `agents/tools.py` (real platform code only) and grant it to agents in
  `agents/definitions.py`. Sensitive actions must be `requires_approval=True` and create approval requests.
- **Migration**: edit `db/models.py`, then
  `alembic -c alembic.ini revision --autogenerate -m "..."` from `backend/` (set `QOPT_DATABASE_URL` to a
  scratch DB). Revisions land in `qopt/migrations/versions/` and are packaged automatically.
- **Never locate files with `Path(__file__).parents[...]` outside the package**: installed deployments have no
  source tree. Ship data as package data, or make the location a setting (see `QOPT_FRONTEND_DIST`,
  `QOPT_DOCS_DIR`). `tests/test_deployment.py` enforces the current guarantees.

## Agents and the Anthropic API

`AgentRuntime` uses the official `anthropic` SDK with a manual tool-use loop so that it can enforce
per-agent tool allow-lists, iteration / token / USD budgets, delegation depth, approval gating, and audit
logging on every call. Default model `claude-opus-5-5` (override with `QOPT_CLAUDE_MODEL`), explicit
`output_config.effort` per agent, and server-side refusal fallbacks (`fallbacks="default"`, beta
`server-side-fallback-2026-07-01`; disable with `QOPT_CLAUDE_FALLBACKS=0`). Tests use a scripted fake
client: the model is mocked, the tools are real.
