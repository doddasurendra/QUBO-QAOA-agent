"""Reproducible benchmarking of classical solvers and QAOA (simulation) on standard instances.

Statistics are reported over seeds; "optimum" is the exhaustive (proven) optimum, so success
rates are exact. No claims of quantum advantage are made or implied.
"""
from __future__ import annotations

import platform
import statistics
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from . import __version__
from .core.validation import enumerate_energies
from .problems import GENERATORS
from .quantum.qaoa import QAOAConfig, run_qaoa
from .solvers.classical import SOLVERS


def _stats(xs: List[float]) -> dict:
    return {"mean": statistics.fmean(xs), "std": statistics.pstdev(xs) if len(xs) > 1 else 0.0,
            "min": min(xs), "max": max(xs)}


def run_benchmark(problems: List[str], sizes: List[int], seeds: int = 3,
                  solvers: Optional[List[str]] = None, qaoa_depths: Optional[List[int]] = None,
                  qaoa_shots: int = 1024, qaoa_maxiter: int = 100, progress=None) -> dict:
    solvers = solvers or ["simulated_annealing", "tabu_search", "greedy_descent", "milp"]
    qaoa_depths = qaoa_depths or []
    rows: List[dict] = []
    t0 = time.perf_counter()
    for prob in problems:
        if prob not in GENERATORS:
            raise ValueError(f"unknown benchmark problem {prob!r}; choose from {sorted(GENERATORS)}")
        for n in sizes:
            per: Dict[str, Dict[str, list]] = {}
            for seed in range(seeds):
                q = GENERATORS[prob](n, seed=seed)
                if q.num_variables > 22:
                    raise ValueError(f"{prob} n={n} has {q.num_variables} QUBO variables; benchmarks use exact "
                                     "optima and are limited to 22")
                E = enumerate_energies(q)
                opt, worst = float(E.min()), float(E.max())
                span = worst - opt if worst > opt else 1.0
                for s in solvers:
                    kw = {"seed": seed} if s in ("simulated_annealing", "tabu_search", "greedy_descent") else {}
                    r = SOLVERS[s](q, **kw)
                    d = per.setdefault(s, {"gap": [], "time": [], "hit": []})
                    d["gap"].append((r.best_energy - opt) / span)
                    d["time"].append(r.runtime_s)
                    d["hit"].append(abs(r.best_energy - opt) < 1e-6)
                for p in qaoa_depths:
                    r = run_qaoa(q, QAOAConfig(p=p, restarts=2, maxiter=qaoa_maxiter, shots=qaoa_shots, seed=seed,
                                               optimizer="L-BFGS-B"))
                    d = per.setdefault(f"qaoa_p{p}", {"gap": [], "time": [], "hit": [], "ratio": [], "gs_prob": [],
                                                      "nfev": []})
                    best = r.best_sample["qubo_energy"] if r.best_sample else worst
                    d["gap"].append((best - opt) / span)
                    d["time"].append(r.runtime_s)
                    d["hit"].append(abs(best - opt) < 1e-6)
                    d["ratio"].append(r.approximation_ratio)
                    d["gs_prob"].append(r.ground_state_probability)
                    d["nfev"].append(r.nfev)
                if progress:
                    progress({"problem": prob, "n": n, "seed": seed})
            for s, d in per.items():
                row = {"problem": prob, "n": n, "qubo_variables": q.num_variables, "solver": s, "seeds": seeds,
                       "normalized_gap": _stats(d["gap"]), "runtime_s": _stats(d["time"]),
                       "optimum_hit_rate": sum(d["hit"]) / len(d["hit"])}
                if "ratio" in d:
                    row.update({"approximation_ratio": _stats(d["ratio"]),
                                "ground_state_probability": _stats(d["gs_prob"]),
                                "circuit_evaluations": _stats(d["nfev"]), "shots": qaoa_shots,
                                "execution_kind": "statevector_simulator"})
                else:
                    row["execution_kind"] = "classical"
                rows.append(row)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "qopt_version": __version__, "python": platform.python_version(), "platform": platform.platform(),
        "numpy": np.__version__, "config": {"problems": problems, "sizes": sizes, "seeds": seeds,
                                            "solvers": solvers, "qaoa_depths": qaoa_depths, "qaoa_shots": qaoa_shots},
        "definitions": {
            "normalized_gap": "(E_found − E_opt) / (E_max − E_min); 0 = optimal",
            "optimum_hit_rate": "fraction of seeds where the proven optimum was found",
            "approximation_ratio": "(E_max − ⟨H⟩) / (E_max − E_min) of the QAOA state",
            "ground_state_probability": "Σ |⟨z|ψ⟩|² over optimal z"},
        "disclaimer": "Small instances, exact optima by enumeration. QAOA is simulated exactly (no noise). "
                      "These results do not demonstrate quantum advantage.",
        "rows": rows, "total_runtime_s": time.perf_counter() - t0}


def to_markdown(rep: dict) -> str:
    lines = [f"# Benchmark report", "", f"Generated {rep['generated_at']} · qopt {rep['qopt_version']} · "
             f"Python {rep['python']} · NumPy {rep['numpy']}", "", f"> {rep['disclaimer']}", "",
             "| problem | n | solver | kind | hit rate | norm. gap (mean±std) | runtime s (mean) | approx. ratio | P(ground) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        g = r["normalized_gap"]
        ar = r.get("approximation_ratio"); gp = r.get("ground_state_probability")
        lines.append(f"| {r['problem']} | {r['n']} | {r['solver']} | {r['execution_kind']} | "
                     f"{r['optimum_hit_rate']:.2f} | {g['mean']:.4f}±{g['std']:.4f} | {r['runtime_s']['mean']:.4f} | "
                     f"{'' if ar is None else f'{ar['mean']:.3f}'} | {'' if gp is None else f'{gp['mean']:.3f}'} |")
    lines += ["", "## Definitions", ""] + [f"- **{k}**: {v}" for k, v in rep["definitions"].items()]
    return "\n".join(lines) + "\n"
