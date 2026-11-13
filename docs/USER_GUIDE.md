# User guide

## Signing in

The first visit to a fresh installation asks you to create the **administrator** account. Afterwards
administrators create users under *Users & Roles*:

| role | can |
|---|---|
| viewer | browse everything, inspect models, read results |
| researcher | + build models, run solvers / QAOA / agents, upload data, request hardware jobs |
| admin | + manage users, approve or reject hardware jobs, read the audit log and configuration |

## The active model

Analysis pages (Matrix Explorer, Validation, Ising, Circuit Designer, QAOA, Simulator, Classical,
Hybrid) work on the **active model** shown at the top of each page. Choose a saved experiment, an
industry template with your data, a custom JSON spec, or a raw QUBO. The choice is kept for the
browser tab.

## Typical workflow

1. **Formulate** — *Industry Solutions* (pick a template, replace the SAMPLE data with yours) or
   *Model Builder* (variables, objective, constraints). Save as an experiment.
2. **Validate** — *QUBO Validation* proves on small models that the penalty QUBO has exactly the
   same optimum as your constrained problem.
3. **Baseline** — *Classical Solvers*: exhaustive or MILP give proven optima; heuristics scale further.
4. **QAOA** — *Circuit Designer* to inspect the circuit, *QAOA Execution* to optimise angles and
   sample, *Quantum Simulator* to explore the state and the p = 1 landscape.
5. **Compare** — *Hybrid Optimization* runs several solvers and ranks them against the best (proven
   when an exact solver ran).
6. **Report** — every job page has *Report (.md)* and *Raw (.json)* downloads; *Results & Reports*
   lists all jobs.

## Simulation vs hardware — how to tell

Every result carries an execution badge:

- `classical` — CPU algorithm
- `SIMULATOR · statevector_simulator` — exact NumPy simulation
- `SIMULATOR · shot_simulator` — Qiskit Aer (optionally with a *synthetic* noise model)
- `REAL QPU · qpu_gate` / `REAL QPU · qpu_annealer` — only when the provider reports real hardware

Real hardware requires (1) the provider SDK on the server, (2) credentials on the server, and (3) an
administrator approving the specific request (*Hardware Providers → Request*, then *Administration*).
D-Wave is a quantum annealer; it samples the QUBO directly and is **not** QAOA.

## AI assistant

*AI Quantum Assistant* accepts problems in plain language, e.g. "Schedule 100 electric vehicles for
charging without overloading the grid". The agent:

- picks a template or builds a custom model, **asking you for missing numbers instead of inventing them**;
- validates the formulation, runs solvers, and explains the result;
- shows every tool call it made (expand *Tool calls*), token usage and estimated cost.

Agents need `ANTHROPIC_API_KEY` on the server (Anthropic API usage is billed per token, separately from
any Claude subscription). Without it the page says so; every tool remains usable from the other pages.
Agents can never submit hardware jobs: they can only create an approval request.

## Data

- *Datasets*: SAMPLE datasets are synthetic and labelled. Upload `.json` / `.csv` (≤ 5 MB). Datasets tied
  to a template are validated against its schema.
- *Research Library*: upload `.txt`, `.md`, `.tex` (and `.pdf` if `pypdf` is installed on the server);
  search is BM25 over passages. The Research Assistant agent searches it.

## API access

*API Management* creates personal keys (shown once). Send them as `X-API-Key`. The interactive API
reference is at `/api/docs`.
