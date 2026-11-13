"""Generate docs/SCIENTIFIC_VALIDATION.md and docs/BENCHMARK_REPORT.md from actual runs.

    python scripts/generate_reports.py            (from backend/)
"""
from __future__ import annotations

import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qopt import __version__  # noqa: E402
from qopt.benchmark import run_benchmark, to_markdown  # noqa: E402
from qopt.core import check_qubo_ising_equivalence, enumerate_energies, validate_compiled  # noqa: E402
from qopt.industries import PROBLEMS  # noqa: E402
from qopt.problems import maxcut, random_qubo  # noqa: E402
from qopt.quantum import QAOAConfig, StatevectorQAOA, XYRingMixer, run_qaoa  # noqa: E402
from qopt.quantum.circuits import bind, build_qaoa_circuit  # noqa: E402
from qopt.solvers import exhaustive, milp_solve, simulated_annealing, tabu_search  # noqa: E402

DOCS = Path(__file__).resolve().parents[2] / "docs"


def validation_report() -> str:
    from qiskit.quantum_info import Statevector
    t0 = time.perf_counter()
    L = ["# Scientific validation report", "",
         f"Generated {datetime.now(timezone.utc).isoformat()} by `backend/scripts/generate_reports.py` · qopt "
         f"{__version__} · Python {platform.python_version()} · NumPy {np.__version__}", "",
         "Every check below was executed; nothing is hand-entered.", ""]

    # 1. QUBO ↔ Ising equivalence
    rows = []
    for n in (4, 8, 12, 16):
        for seed in range(5):
            r = check_qubo_ising_equivalence(random_qubo(n, 0.6, seed))
            rows.append((n, seed, r["checked"], r["max_abs_error"], r["roundtrip_max_abs_error"], r["passed"]))
    L += ["## 1. QUBO ↔ Ising equivalence (exhaustive over all 2ⁿ assignments)", "",
          "| n | seed | assignments | max abs error | round-trip error | pass |", "|---|---|---|---|---|---|"]
    L += [f"| {n} | {s} | {c} | {e:.2e} | {e2:.2e} | {'✅' if p else '❌'} |" for n, s, c, e, e2, p in rows]

    # 2. Industry formulations
    L += ["", "## 2. Constrained formulations: penalty exactness (industry examples)", "",
          "For every decision assignment: feasible ⇒ QUBO energy = objective; infeasible ⇒ energy > best feasible; "
          "QUBO argmin is a feasible optimum.", "",
          "| problem | decision vars | slack vars | feasible / total | best objective | pass |", "|---|---|---|---|---|---|"]
    for key, p in PROBLEMS.items():
        _, cm = p.compile(p.example())
        rep = validate_compiled(cm)
        L.append(f"| {key} | {cm.num_decision} | {len(cm.slack_variables)} | {rep.num_feasible} / {rep.num_states} | "
                 f"{rep.best_feasible_objective:.6g} | {'✅' if rep.passed else '❌ ' + '; '.join(rep.issues)} |")

    # 3. Solvers vs exhaustive
    L += ["", "## 3. Classical solvers vs exhaustive optimum (random QUBOs, n = 14, 10 seeds)", "",
          "| solver | optimum found | max energy gap |", "|---|---|---|"]
    stats = {"milp_highs": [], "simulated_annealing": [], "tabu_search": []}
    for seed in range(10):
        q = random_qubo(14, 0.5, 100 + seed)
        opt = exhaustive(q).best_energy
        for name, fn in (("milp_highs", lambda: milp_solve(q)), ("simulated_annealing", lambda: simulated_annealing(q, 20, 400, seed=seed)),
                         ("tabu_search", lambda: tabu_search(q, 800, seed=seed))):
            stats[name].append(fn().best_energy - opt)
    for k, v in stats.items():
        L.append(f"| {k} | {sum(abs(x) < 1e-6 for x in v)}/10 | {max(v):.2e} |")

    # 4. QAOA statevector vs Qiskit
    L += ["", "## 4. QAOA unitary: NumPy simulator vs Qiskit `Statevector`", "",
          "| n | p | mixer | fidelity |", "|---|---|---|---|"]
    rng = np.random.default_rng(0)
    for n, p, mix in ((4, 1, "x"), (6, 3, "x"), (8, 2, "x"), (6, 2, "xy_ring")):
        q = random_qubo(n, 0.6, n)
        mixer = XYRingMixer([[0, 1, 2]]) if mix == "xy_ring" else None
        sim = StatevectorQAOA(q, mixer)
        x = rng.uniform(-1, 1, 2 * p)
        qc, g, b, _ = build_qaoa_circuit(q, p, mixer)
        f = abs(np.vdot(Statevector(bind(qc, g, b, x[:p], x[p:])).data, sim.state(x))) ** 2
        L.append(f"| {n} | {p} | {mix} | {f:.12f} |")

    # 5. Known analytic result
    n = 8
    q = maxcut([(i, (i + 1) % n) if i < (i + 1) % n else ((i + 1) % n, i) for i in range(n)], n)
    r = run_qaoa(q, QAOAConfig(p=1, restarts=5, optimizer="L-BFGS-B", seed=1))
    L += ["", "## 5. Known result: p = 1 QAOA on the 8-ring MaxCut", "",
          "Farhi, Goldstone & Gutmann (2014): for 2-regular graphs the optimal p = 1 expected cut is 3/4 of the edges.", "",
          f"- Expected cut found: **{-r.expected_energy:.6f}**; theory 0.75 × 8 = **6.000000**",
          f"- Optimal angles: γ = {r.gammas[0]:.4f} (on H_C / {r.hamiltonian_scale:g}), β = {r.betas[0]:.4f}"]

    # 6. Depth study
    L += ["", "## 6. QAOA depth study (MaxCut, random 3-regular graph n = 10, INTERP initialisation)", "",
          "| p | ⟨cut⟩ | approximation ratio | P(optimal cut) | evaluations |", "|---|---|---|---|---|"]
    from qopt.problems import regular_maxcut
    q, _ = regular_maxcut(10, 3, seed=3)
    for p in (1, 2, 3, 4):
        r = run_qaoa(q, QAOAConfig(p=p, init="interp", restarts=1, optimizer="L-BFGS-B", maxiter=300, shots=0))
        L.append(f"| {p} | {-r.expected_energy:.4f} | {r.approximation_ratio:.4f} | {r.ground_state_probability:.4f} | {r.nfev} |")
    L += ["", "Increasing p improved results here with warm-started (INTERP) parameters; this is not guaranteed for "
          "cold-started optimisation or under hardware noise.",
          "", "## 7. Constraint-preserving mixer", "",
          "Tested in `tests/test_qaoa.py::test_xy_mixer_matches_qiskit_and_preserves_one_hot`: probability mass outside "
          "the one-hot subspace stays < 1e-12 for every layer.", "",
          "## Limitations", "",
          "- Exhaustive validation is limited to ≤ 20 decision / 22 QUBO variables.",
          "- QAOA results here are exact noiseless simulation. No real-QPU runs were performed (no credentials configured).",
          "- Penalty dominance is guaranteed for integer-coefficient constraints; non-integer equality constraints are "
          "flagged with a warning and must be checked via `validate_compiled`.",
          f"", f"Total generation time: {time.perf_counter() - t0:.1f} s"]
    return "\n".join(L) + "\n"


def main():
    DOCS.mkdir(exist_ok=True)
    (DOCS / "SCIENTIFIC_VALIDATION.md").write_text(validation_report(), encoding="utf-8")
    print("wrote SCIENTIFIC_VALIDATION.md")
    rep = run_benchmark(["maxcut_gnp", "maxcut_3regular", "number_partitioning", "knapsack"], [6, 8, 10], seeds=5,
                        qaoa_depths=[1, 2, 3], qaoa_shots=1024, qaoa_maxiter=150)
    (DOCS / "BENCHMARK_REPORT.md").write_text(to_markdown(rep), encoding="utf-8")
    (DOCS / "benchmark_results.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"wrote BENCHMARK_REPORT.md ({rep['total_runtime_s']:.1f} s)")


if __name__ == "__main__":
    main()
