from __future__ import annotations

import json

from ..db import Job


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.6g}"
    return "" if v is None else str(v)


def job_report_markdown(j: Job) -> str:
    r = j.result or {}
    L = [f"# Job {j.id} report — {j.kind}", "",
         f"- Status: **{j.status}**", f"- Created: {j.created_at.isoformat()}",
         f"- Runtime: {_fmt(j.runtime_s)} s",
         f"- Execution kind(s): `{j.execution_kind}`",
         f"- Real quantum hardware used: **{'YES' if j.is_real_hardware else 'NO (simulation / classical)'}**", ""]
    if r.get("ranking"):
        L += ["## Solver ranking", "", "| rank | solver | kind | real HW | QUBO energy | objective | feasible | gap |",
              "|---|---|---|---|---|---|---|---|"]
        for row in r["ranking"]:
            L.append(f"| {row['rank']} | {row['solver']} | {row['execution_kind']} | {row['is_real_hardware']} | "
                     f"{_fmt(row['qubo_energy'])} | {_fmt(row.get('objective'))} | {row.get('feasible')} | "
                     f"{_fmt(row['gap_to_best'])} |")
        L += ["", f"Reference: {r['ranking'][0]['reference']}", ""]
    if j.kind == "qaoa":
        L += ["## QAOA", "", f"- p = {r.get('config', {}).get('p')}, optimizer = {r.get('config', {}).get('optimizer')}, "
              f"mixer = {r.get('mixer', {}).get('name')}",
              f"- Expected energy ⟨H⟩ = {_fmt(r.get('expected_energy'))} (E_min = {_fmt(r.get('e_min'))}, "
              f"E_max = {_fmt(r.get('e_max'))})",
              f"- Approximation ratio = {_fmt(r.get('approximation_ratio'))}",
              f"- Ground-state probability = {_fmt(r.get('ground_state_probability'))}",
              f"- Circuit evaluations = {r.get('nfev')}, shots = {r.get('config', {}).get('shots')}",
              f"- γ = {r.get('gammas')}, β = {r.get('betas')}", ""]
        if r.get("best_sample"):
            L += [f"- Best sampled assignment: `{r['best_sample']['bitstring']}` (variable 0 first), "
                  f"energy {_fmt(r['best_sample']['qubo_energy'])}", ""]
    if j.kind == "classical":
        L += ["## Classical solution", "", f"- Solver: {r.get('solver')}", f"- Best energy: {_fmt(r.get('best_energy'))}",
              f"- Proven optimal: {r.get('proven_optimal')}", f"- Assignment: `{r.get('best_bitstring')}`", ""]
        if r.get("evaluation"):
            L += [f"- Feasible: {r['evaluation']['feasible']}, objective: {_fmt(r['evaluation']['objective'])}", ""]
    if j.kind == "benchmark" and r.get("markdown"):
        L += [r["markdown"]]
    if r.get("domain"):
        L += ["## Domain interpretation", "", "```json", json.dumps(r["domain"], indent=2, default=str), "```", ""]
    for note in r.get("notes", []) or []:
        L.append(f"> {note}")
    if r.get("errors"):
        L += ["", "## Errors", ""] + [f"- {e['solver']}: {e['error']}" for e in r["errors"]]
    L += ["", "## Parameters", "", "```json", json.dumps(j.params, indent=2, default=str)[:20000], "```"]
    return "\n".join(L) + "\n"
