import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { DomainView, JobHeader, RankingTable, SamplesTable, useJob } from "../components/jobs";
import { RequireModel, useActiveModel } from "../components/model";
import { Card, ErrorBox, Field, FOCUS, fmt, Json, KindBadge, Note, Page, useAction, useLoad } from "../components/ui";

const CLASSICAL = {
  exhaustive: {}, milp: { time_limit: 60 }, simulated_annealing: { num_reads: 20, num_sweeps: 1000, seed: 7 },
  tabu_search: { max_iter: 2000, restarts: 5, seed: 7 }, greedy_descent: { restarts: 10, seed: 7 },
} as Record<string, Record<string, number>>;

export function ClassicalPage() {
  const [solver, setSolver] = useState("simulated_annealing");
  const [opts, setOpts] = useState<Record<string, number>>(CLASSICAL.simulated_annealing);
  const { job, error, busy, submit } = useJob();
  const r = job?.result;
  return (
    <Page title="Classical Solvers" subtitle="Exact (exhaustive, MILP/HiGHS) and heuristic (simulated annealing, tabu, greedy) baselines.">
      <RequireModel>{(ref) => (
        <Card>
          <div className="grid gap-3 md:grid-cols-4">
            <Field label="Solver"><select className="input" value={solver} onChange={(e) => { setSolver(e.target.value); setOpts(CLASSICAL[e.target.value]); }}>{Object.keys(CLASSICAL).map((s) => <option key={s}>{s}</option>)}</select></Field>
            {Object.entries(opts).map(([k, v]) => <Field key={k} label={k}><input className="input" type="number" value={v} onChange={(e) => setOpts({ ...opts, [k]: Number(e.target.value) })} /></Field>)}
          </div>
          <button className="btn mt-3" disabled={busy} onClick={() => submit({ kind: "classical", params: { ...ref, solver, options: opts } })}>Solve</button>
        </Card>)}</RequireModel>
      <ErrorBox error={error} />
      <JobHeader job={job} />
      {r && <>
        <div className="grid gap-3 sm:grid-cols-4">
          <Card><div className="label">best QUBO energy</div><div className="text-xl font-bold tabular-nums">{fmt(r.best_energy)}</div></Card>
          <Card><div className="label">proven optimal</div><div className="text-xl font-bold">{r.proven_optimal === true ? "yes" : r.proven_optimal === false ? "no (time limit)" : "not proven (heuristic)"}</div></Card>
          <Card><div className="label">feasible</div><div className="text-xl font-bold">{r.evaluation ? (r.evaluation.feasible ? "yes" : "no") : "n/a"}</div></Card>
          <Card><div className="label">objective</div><div className="text-xl font-bold tabular-nums">{fmt(r.evaluation?.objective)}</div></Card>
        </div>
        <Card title="Best assignment"><p className="font-mono text-sm">{r.evaluation?.bitstring ?? r.best_bitstring}</p><p className="text-xs text-slate-600 dark:text-slate-400">{r.evaluation?.bit_order ?? r.bit_order}</p></Card>
        <Card title="Samples"><SamplesTable rows={r.samples.map((s: any) => ({ ...s, qubo_energy: s.energy }))} /></Card>
        <DomainView domain={r.domain} />
        <Card title="Solver metadata"><Json value={r.metadata} /></Card>
      </>}
    </Page>
  );
}

export function HybridPage() {
  const { active } = useActiveModel();
  const [rec, setRec] = useState<any>();
  const [selected, setSelected] = useState<string[]>([]);
  const [p, setP] = useState(1);
  const [aer, setAer] = useState("");
  const { job, error, busy, submit } = useJob();
  const a = useAction();
  useEffect(() => {
    if (!active) return;
    a.run(async () => {
      const r = await api.post("/hybrid/recommend", { ...active.ref, p });
      setRec(r);
      setSelected(r.recommendations.filter((x: any) => x.recommended && ["classical", "statevector_simulator"].includes(x.execution_kind)).map((x: any) => x.solver));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.label, p]);
  const runnable = new Set(["exhaustive", "milp", "simulated_annealing", "tabu_search", "greedy_descent", "qaoa_statevector"]);
  const r = job?.result;
  return (
    <Page title="Hybrid Optimization" subtitle="Transparent solver selection → classical baselines + QAOA simulation (+ optional Aer shot simulation) → validation → ranking.">
      <RequireModel>{(ref) => (
        <Card title="Solver selection">
          <ErrorBox error={a.error} />
          <div className="mb-2 w-32"><Field label="QAOA depth p"><input className="input" type="number" min={1} max={8} value={p} onChange={(e) => setP(Number(e.target.value))} /></Field></div>
          {rec && <table className="table"><thead><tr><th /><th>solver</th><th>kind</th><th>recommended</th><th>reasons</th></tr></thead>
            <tbody>{rec.recommendations.map((x: any) => (
              <tr key={x.solver}><td>{runnable.has(x.solver) && <input type="checkbox" aria-label={`Run ${x.solver}`} checked={selected.includes(x.solver)} onChange={(e) => setSelected(e.target.checked ? [...selected, x.solver] : selected.filter((s) => s !== x.solver))} />}</td>
                <td className="font-medium">{x.solver}</td><td><KindBadge kind={x.execution_kind} /></td><td>{x.recommended ? "✓" : "—"}</td><td className="text-xs">{x.reasons.join(" · ")}{x.requires_approval ? " · requires admin approval (Hardware Providers page)" : ""}</td></tr>))}</tbody></table>}
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <Field label="Also sample on Aer (simulator)"><select className="input" value={aer} onChange={(e) => setAer(e.target.value)}><option value="">no</option><option value="aer_ideal">aer_ideal</option><option value="aer_noisy_depolarizing">aer_noisy_depolarizing (synthetic noise)</option></select></Field>
            <button className="btn" disabled={busy || !selected.length} onClick={() => submit({ kind: "hybrid", params: { ...ref, solvers: selected, qaoa: { p, restarts: 2, maxiter: 150, shots: 2048 }, ...(aer ? { hardware: { provider: "qiskit_aer", backend: aer, shots: 4096 } } : {}) } })}>Run hybrid workflow</button>
          </div>
        </Card>)}</RequireModel>
      <ErrorBox error={error} />
      <JobHeader job={job} />
      {r && <>
        {r.notes?.map((n: string) => <Note key={n}>{n}</Note>)}
        {r.errors?.length > 0 && <Note tone="warn">{r.errors.map((e: any) => `${e.solver}: ${e.error}`).join(" · ")}</Note>}
        {r.exhaustive_validation && <Note tone={r.exhaustive_validation.passed ? "ok" : "warn"}>Exhaustive formulation validation: {r.exhaustive_validation.passed ? "passed" : r.exhaustive_validation.issues.join("; ")}</Note>}
        <Card title="Ranking"><RankingTable ranking={r.ranking} /></Card>
        <Card title="Per-solver details">
          <table className="table"><thead><tr><th>solver</th><th>runtime s</th><th>assignment</th><th>extra</th></tr></thead>
            <tbody>{r.results.map((x: any) => <tr key={x.solver}><td>{x.solver}</td><td>{fmt(x.runtime_s, 3)}</td><td className="font-mono text-xs">{x.decision_bitstring ?? x.bitstring}</td>
              <td className="text-xs">{x.expected_energy !== undefined ? `⟨H⟩=${fmt(x.expected_energy)} · ratio=${fmt(x.approximation_ratio, 3)} · P(gs)=${fmt(x.ground_state_probability, 3)}` : x.proven_optimal ? "proven optimal" : x.job_id ? `job ${x.job_id}` : ""}</td></tr>)}</tbody></table>
        </Card>
        <DomainView domain={r.domain} />
      </>}
    </Page>
  );
}

export function IndustryPage() {
  const { setActive } = useActiveModel();
  const [probs, err] = useLoad(() => api.get("/industries"));
  const [key, setKey] = useState("");
  const [desc, setDesc] = useState<any>();
  const [text, setText] = useState("");
  const [form, setForm] = useState<any>();
  const [datasets] = useLoad(() => api.get("/datasets"));
  const { job, error, busy, submit } = useJob();
  const a = useAction();
  useEffect(() => { if (probs?.length && !key) setKey(probs[0].key); }, [probs, key]);
  useEffect(() => { if (key) api.get(`/industries/${key}`).then((d) => { setDesc(d); setText(JSON.stringify(d.example, null, 2)); setForm(undefined); }); }, [key]);
  const data = () => { try { return JSON.parse(text); } catch (e) { throw new Error(`Invalid JSON: ${(e as Error).message}`); } };
  return (
    <Page title="Industry Solutions" subtitle="Reusable formulations for finance, healthcare, telecom, energy, logistics and manufacturing.">
      <ErrorBox error={err} />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Array.from(new Set<string>((probs ?? []).map((p: any) => p.industry as string))).map((ind: string) => (
          <Card key={ind} title={ind.charAt(0).toUpperCase() + ind.slice(1)}>
            <div className="flex flex-col gap-1">
              {probs!.filter((p: any) => p.industry === ind).map((p: any) => (
                <button key={p.key} className={`text-left ${key === p.key ? "btn" : "btn-secondary"}`} onClick={() => setKey(p.key)} title={p.description}>{p.title}</button>
              ))}
            </div>
          </Card>
        ))}
      </div>
      {desc && <div className="grid gap-4 lg:grid-cols-2">
        <Card title={desc.title}>
          <p className="text-sm">{desc.description}</p>
          <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-100 p-2 font-mono text-xs dark:bg-slate-800">{desc.formulation}</pre>
          {desc.limitations && <Note tone="warn">Limitation: {desc.limitations}</Note>}
          <details className="mt-2"><summary className="cursor-pointer text-sm">Input schema</summary><Json value={desc.input_schema} /></details>
        </Card>
        <Card title="Input data" actions={<select className="input w-56" aria-label="Load a saved dataset" defaultValue="" onChange={async (e) => { if (e.target.value) setText(JSON.stringify((await api.get(`/datasets/${e.target.value}`)).content, null, 2)); }}>
          <option value="">Load dataset…</option>{datasets?.filter((d: any) => d.problem_key === key).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>}>
          <Note>The pre-filled example is <b>SAMPLE data</b> for demonstration. Replace it with your own figures.</Note>
          <textarea className="input mt-2 h-72 font-mono text-xs" aria-label="Input data (JSON)" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          <div className="mt-2 flex flex-wrap gap-2">
            <button className="btn-secondary" disabled={a.busy} onClick={() => a.run(async () => setForm(await api.post(`/industries/${key}/formulate`, { data: data() })))}>Formulate & inspect</button>
            <button className="btn-secondary" disabled={a.busy} onClick={() => a.run(async () => { const f = await api.post(`/industries/${key}/formulate`, { data: data(), save_as: `${desc.title} ${new Date().toLocaleString()}` }); setForm(f); setActive({ ref: { experiment_id: f.experiment_id }, label: `Experiment #${f.experiment_id} ${desc.title}` }); })}>Save as experiment</button>
            <button className="btn" disabled={busy} onClick={() => { try { submit({ kind: "hybrid", params: { industry: { key, data: data() }, solvers: ["auto"], qaoa: { p: 1, restarts: 2, maxiter: 120 } } }); } catch (e) { a.setError(e); } }}>Solve (auto hybrid)</button>
          </div>
          <ErrorBox error={a.error} />
        </Card>
      </div>}
      {form && <Card title="Formulation"><p className="text-sm">{form.summary.num_decision_variables} decision + {form.summary.num_slack_variables} slack variables = {form.stats.num_variables} qubits, {form.stats.num_quadratic_terms} couplings. Penalties: {Object.entries(form.summary.penalties).map(([k, v]) => `${k}=${fmt(v)}`).slice(0, 8).join(", ")}{Object.keys(form.summary.penalties).length > 8 ? " …" : ""}</p>
        {form.summary.warnings.map((w: string) => <Note key={w} tone="warn">{w}</Note>)}</Card>}
      <ErrorBox error={error} />
      <JobHeader job={job} />
      {job?.result && <>
        <DomainView domain={job.result.domain} />
        <Card title="Solver ranking"><RankingTable ranking={job.result.ranking} /></Card>
        {job.result.errors?.length > 0 && <Note tone="warn">{job.result.errors.map((e: any) => `${e.solver}: ${e.error}`).join(" · ")}</Note>}
        {job.result.results?.find((x: any) => x.solver === "qaoa_statevector") && <Card title="QAOA (simulator) detail">
          <p className="text-sm">{(() => { const q = job.result.results.find((x: any) => x.solver === "qaoa_statevector"); return `⟨H⟩ = ${fmt(q.expected_energy)}, approximation ratio ${fmt(q.approximation_ratio, 3)}, P(ground) ${fmt(q.ground_state_probability, 3)}`; })()}</p></Card>}
      </>}
    </Page>
  );
}

export function BenchmarkPage() {
  const [cfg, setCfg] = useState({ problems: ["maxcut_gnp", "number_partitioning"], sizes: "6,8,10", seeds: 3, solvers: ["simulated_annealing", "tabu_search", "greedy_descent", "milp"], qaoa_depths: "1,2", qaoa_shots: 1024 });
  const { job, error, busy, submit } = useJob();
  const ALL_P = ["maxcut_gnp", "maxcut_3regular", "number_partitioning", "random_qubo", "knapsack"];
  const ALL_S = ["simulated_annealing", "tabu_search", "greedy_descent", "milp", "exhaustive"];
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const nums = (s: string) => s.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0);
  const r = job?.result;
  const chart = r ? Object.values(r.rows.reduce((acc: any, row: any) => { const k = `${row.problem} n=${row.n}`; acc[k] = acc[k] ?? { name: k }; acc[k][row.solver] = row.optimum_hit_rate; return acc; }, {})) : [];
  const solversInChart = r ? Array.from(new Set(r.rows.map((x: any) => x.solver))) as string[] : [];
  const palette = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#64748b"];
  return (
    <Page title="Benchmarking" subtitle="Reproducible comparisons against proven optima (exhaustive enumeration). QAOA is exact, noiseless simulation.">
      <Card>
        <div className="grid gap-3 md:grid-cols-2">
          <div><div className="label">Problems</div><div className="flex flex-wrap gap-2">{ALL_P.map((p) => <label key={p} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={cfg.problems.includes(p)} onChange={() => setCfg({ ...cfg, problems: toggle(cfg.problems, p) })} />{p}</label>)}</div></div>
          <div><div className="label">Classical solvers</div><div className="flex flex-wrap gap-2">{ALL_S.map((p) => <label key={p} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={cfg.solvers.includes(p)} onChange={() => setCfg({ ...cfg, solvers: toggle(cfg.solvers, p) })} />{p}</label>)}</div></div>
          <Field label="Sizes n (comma-separated)" hint="QUBO size must stay ≤ 22 (knapsack adds slack bits)"><input className="input" value={cfg.sizes} onChange={(e) => setCfg({ ...cfg, sizes: e.target.value })} /></Field>
          <Field label="QAOA depths p (empty = none)"><input className="input" value={cfg.qaoa_depths} onChange={(e) => setCfg({ ...cfg, qaoa_depths: e.target.value })} /></Field>
          <Field label="Seeds per instance"><input className="input" type="number" min={1} max={20} value={cfg.seeds} onChange={(e) => setCfg({ ...cfg, seeds: Number(e.target.value) })} /></Field>
          <Field label="QAOA shots"><input className="input" type="number" min={64} max={100000} value={cfg.qaoa_shots} onChange={(e) => setCfg({ ...cfg, qaoa_shots: Number(e.target.value) })} /></Field>
        </div>
        <button className="btn mt-3" disabled={busy || !cfg.problems.length} onClick={() => submit({ kind: "benchmark", params: { problems: cfg.problems, sizes: nums(cfg.sizes), seeds: cfg.seeds, solvers: cfg.solvers, qaoa_depths: nums(cfg.qaoa_depths), qaoa_shots: cfg.qaoa_shots } })}>Run benchmark</button>
      </Card>
      <ErrorBox error={error} />
      <JobHeader job={job} />
      {r && <>
        <Note>{r.disclaimer}</Note>
        <Card title="Optimum hit rate by instance">
          <div className="h-72"><ResponsiveContainer><BarChart data={chart as any[]}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="name" fontSize={10} /><YAxis domain={[0, 1]} fontSize={10} /><Tooltip /><Legend />
            {solversInChart.map((s, i) => <Bar key={s} dataKey={s} fill={palette[i % palette.length]} />)}</BarChart></ResponsiveContainer></div>
        </Card>
        <Card title="Results">
          <div role="region" aria-label="Benchmark results" tabIndex={0} className={`overflow-auto ${FOCUS}`}><table className="table"><thead><tr><th>problem</th><th>n</th><th>qubits</th><th>solver</th><th>kind</th><th>hit rate</th><th>norm. gap</th><th>runtime (s)</th><th>approx. ratio</th><th>P(ground)</th></tr></thead>
            <tbody>{r.rows.map((x: any, i: number) => <tr key={i}><td>{x.problem}</td><td>{x.n}</td><td>{x.qubo_variables}</td><td>{x.solver}</td><td><KindBadge kind={x.execution_kind} /></td><td>{fmt(x.optimum_hit_rate, 2)}</td>
              <td className="tabular-nums">{fmt(x.normalized_gap.mean)} ± {fmt(x.normalized_gap.std)}</td><td className="tabular-nums">{fmt(x.runtime_s.mean, 4)}</td>
              <td>{x.approximation_ratio ? fmt(x.approximation_ratio.mean, 3) : ""}</td><td>{x.ground_state_probability ? fmt(x.ground_state_probability.mean, 3) : ""}</td></tr>)}</tbody></table></div>
          <ul className="mt-2 text-xs text-slate-600 dark:text-slate-400">{Object.entries(r.definitions).map(([k, v]) => <li key={k}><b>{k}</b>: {String(v)}</li>)}</ul>
        </Card>
      </>}
    </Page>
  );
}
