# Developer guide

## Layout

```
backend/
  qopt/core        Expr/Model builder, QUBO, Ising, penalties, preprocessing, exhaustive validation
  qopt/solvers     exhaustive, simulated annealing, tabu, greedy, MILP (SciPy/HiGHS)
  qopt/quantum     statevector QAOA (adjoint gradients), mixers, Qiskit circuits, bit-order helpers
  qopt/providers   Aer, IBM Runtime, Amazon Braket, D-Wave (annealer) + registry
  qopt/hybrid      solver recommendation + hybrid execution + ranking
  qopt/industries  25 industry templates (schema, formulation, interpretation, sample data);
                   *_ext.py, energy_flex.py and supply_chain.py hold the later modules
  qopt/agents      Claude tool-use orchestrator, 10 agent roles, tool registry
  qopt/services    jobs, audit, security, research search, reports, agent persistence bridge
  qopt/api         FastAPI app and routers
  qopt/db          SQLAlchemy models, session, migrations entry point
  alembic/         migrations
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
  `alembic -c alembic.ini revision --autogenerate -m "..."` (set `QOPT_DATABASE_URL` to a scratch DB).

## Agents and the Anthropic API

`AgentRuntime` uses the official `anthropic` SDK with a manual tool-use loop so that it can enforce
per-agent tool allow-lists, iteration / token / USD budgets, delegation depth, approval gating, and audit
logging on every call. Default model `claude-opus-5-5` (override with `QOPT_CLAUDE_MODEL`), explicit
`output_config.effort` per agent, and server-side refusal fallbacks (`fallbacks="default"`, beta
`server-side-fallback-2026-07-01`; disable with `QOPT_CLAUDE_FALLBACKS=0`). Tests use a scripted fake
client: the model is mocked, the tools are real.
