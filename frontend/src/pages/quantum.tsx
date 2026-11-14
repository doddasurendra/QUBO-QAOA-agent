import { useEffect, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, saveBlob, type ModelRef } from "../api";
import { can, useAuth } from "../auth";
import { HistoryChart, JobHeader, SamplesTable, DomainView, useJob } from "../components/jobs";
import { RequireModel } from "../components/model";
import { CircuitView, Landscape } from "../components/viz";
import { Card, ErrorBox, Field, FOCUS, fmt, Json, KindBadge, Note, Page, StatusBadge, useAction, useLoad } from "../components/ui";

const OPTIMIZERS = ["COBYLA", "L-BFGS-B", "Nelder-Mead", "Powell", "SPSA", "ADAM", "BFGS", "SLSQP"];

export function CircuitPage() {
  const [p, setP] = useState(1);
  const [mixer, setMixer] = useState("x");
  const [g, setG] = useState("0.5");
  const [b, setB] = useState("0.4");
  const [r, setR] = useState<any>();
  const { busy, error, run } = useAction();
  const go = (ref: ModelRef, withParams: boolean) => run(async () => {
    const parse = (s: string) => s.split(",").map((x) => Number(x.trim()));
    const body: any = { ...ref, p, mixer };
    if (withParams) {
      body.gammas = parse(g); body.betas = parse(b);
      if (body.gammas.length !== p || body.betas.length !== p || [...body.gammas, ...body.betas].some((x: number) => !Number.isFinite(x))) throw new Error(`enter ${p} comma-separated numbers for γ and for β`);
    }
    const out = await api.post("/qaoa/circuit", body);
    setR(out);
    if (withParams && out.qasm3) saveBlob(new Blob([out.qasm3], { type: "text/plain" }), "qaoa.qasm");
  });
  return (
    <Page title="QAOA Circuit Designer" subtitle="U_C(γ) = exp(−iγ H_C/s) as RZ/RZZ gates, mixer U_M(β) = exp(−iβ H_M).">
      <RequireModel>{(ref) => (
        <Card>
          <div className="grid gap-3 md:grid-cols-5">
            <Field label="Depth p"><input className="input" type="number" min={1} max={10} value={p} onChange={(e) => setP(Math.max(1, Math.min(10, Number(e.target.value))))} /></Field>
            <Field label="Mixer"><select className="input" value={mixer} onChange={(e) => setMixer(e.target.value)}><option value="x">X (transverse field)</option><option value="xy_ring">XY ring (one-hot preserving)</option></select></Field>
            <Field label="γ values"><input className="input" value={g} onChange={(e) => setG(e.target.value)} /></Field>
            <Field label="β values"><input className="input" value={b} onChange={(e) => setB(e.target.value)} /></Field>
            <div className="flex items-end gap-2"><button className="btn" disabled={busy} onClick={() => go(ref, false)}>Build</button><button className="btn-secondary" disabled={busy} onClick={() => go(ref, true)}>QASM 3</button></div>
          </div>
        </Card>)}</RequireModel>
      <ErrorBox error={error} />
      {r && <>
        <div className="grid gap-3 sm:grid-cols-4">
          <Card><div className="label">qubits</div><div className="text-2xl font-bold">{r.summary.num_qubits}</div></Card>
          <Card><div className="label">depth</div><div className="text-2xl font-bold">{r.summary.depth}</div></Card>
          <Card><div className="label">two-qubit gates</div><div className="text-2xl font-bold">{r.summary.two_qubit_gates}</div></Card>
          <Card><div className="label">H_C scale s</div><div className="text-2xl font-bold">{fmt(r.hamiltonian_scale)}</div></Card>
        </div>
        <Card title="Circuit"><CircuitView gates={r.gates} numQubits={r.num_qubits} labels={r.variables} /></Card>
        <Card title="Gate counts & conventions"><Json value={{ ops: r.summary.ops, conventions: r.conventions }} /></Card>
        {r.text_diagram && <Card title="Qiskit text diagram"><pre tabIndex={0} role="region" aria-label="Qiskit text diagram" className={`overflow-auto text-xs ${FOCUS}`}>{r.text_diagram}</pre></Card>}
      </>}
    </Page>
  );
}

export function QaoaPage() {
  const [cfg, setCfg] = useState({ p: 1, optimizer: "COBYLA", maxiter: 150, restarts: 3, init: "linear_ramp", mixer: "x", shots: 2048, seed: 7 });
  const { job, error, busy, submit } = useJob();
  const set = (k: string, v: any) => setCfg({ ...cfg, [k]: v });
  const r = job?.result;
  return (
    <Page title="QAOA Execution" subtitle="Optimise γ, β on the exact statevector simulator, then sample measurement shots. Results are SIMULATION.">
      <RequireModel>{(ref) => (
        <Card>
          <div className="grid gap-3 md:grid-cols-4">
            <Field label="Depth p"><input className="input" type="number" min={1} max={12} value={cfg.p} onChange={(e) => set("p", Number(e.target.value))} /></Field>
            <Field label="Optimizer"><select className="input" value={cfg.optimizer} onChange={(e) => set("optimizer", e.target.value)}>{OPTIMIZERS.map((o) => <option key={o}>{o}</option>)}</select></Field>
            <Field label="Initialisation"><select className="input" value={cfg.init} onChange={(e) => set("init", e.target.value)}><option value="linear_ramp">linear ramp (+random restarts)</option><option value="interp">INTERP (p → p+1)</option><option value="random">random</option></select></Field>
            <Field label="Mixer"><select className="input" value={cfg.mixer} onChange={(e) => set("mixer", e.target.value)}><option value="x">X</option><option value="xy_ring">XY ring</option></select></Field>
            <Field label="Max iterations"><input className="input" type="number" min={1} max={2000} value={cfg.maxiter} onChange={(e) => set("maxiter", Number(e.target.value))} /></Field>
            <Field label="Restarts"><input className="input" type="number" min={1} max={20} value={cfg.restarts} onChange={(e) => set("restarts", Number(e.target.value))} /></Field>
            <Field label="Shots"><input className="input" type="number" min={0} max={200000} value={cfg.shots} onChange={(e) => set("shots", Number(e.target.value))} /></Field>
            <Field label="Seed"><input className="input" type="number" value={cfg.seed} onChange={(e) => set("seed", Number(e.target.value))} /></Field>
          </div>
          <button className="btn mt-3" disabled={busy} onClick={() => submit({ kind: "qaoa", params: { ...ref, config: cfg } })}>Run QAOA</button>
        </Card>)}</RequireModel>
      <ErrorBox error={error} />
      <JobHeader job={job} />
      {r && <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Card><div className="label">⟨H⟩ optimised</div><div className="text-xl font-bold tabular-nums">{fmt(r.expected_energy)}</div><div className="text-xs text-slate-600 dark:text-slate-400">E_min {fmt(r.e_min)} · E_max {fmt(r.e_max)}</div></Card>
          <Card><div className="label">approximation ratio</div><div className="text-xl font-bold">{fmt(r.approximation_ratio, 3)}</div></Card>
          <Card><div className="label">P(ground state)</div><div className="text-xl font-bold">{fmt(r.ground_state_probability, 3)}</div></Card>
          <Card><div className="label">circuit evaluations</div><div className="text-xl font-bold">{r.nfev}</div><div className="text-xs text-slate-600 dark:text-slate-400">{r.num_qubits} qubits · depth {r.circuit?.depth}</div></Card>
        </div>
        {r.warnings?.map((w: string) => <Note key={w} tone="warn">{w}</Note>)}
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="Convergence (best restart)"><HistoryChart history={r.history} /></Card>
          <Card title="Restarts"><table className="table"><thead><tr><th>#</th><th>⟨H⟩</th><th>evaluations</th><th>γ / β</th></tr></thead>
            <tbody>{r.restarts.map((x: any) => <tr key={x.restart}><td>{x.restart}</td><td className="tabular-nums">{fmt(x.expected_energy)}</td><td>{x.evaluations}</td><td className="font-mono text-xs">{x.params.map((v: number) => v.toFixed(3)).join(", ")}</td></tr>)}</tbody></table>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">γ = [{r.gammas.map((v: number) => v.toFixed(4)).join(", ")}], β = [{r.betas.map((v: number) => v.toFixed(4)).join(", ")}] ({r.angle_convention})</p></Card>
        </div>
        <Card title={`Measured samples (${r.config.shots} shots, ranked: feasible first, then energy)`}><SamplesTable rows={r.ranked_samples} /></Card>
        <DomainView domain={r.domain} />
      </>}
    </Page>
  );
}

export function SimulatorPage() {
  const [p, setP] = useState(1);
  const [gam, setGam] = useState<number[]>([0.5]);
  const [bet, setBet] = useState<number[]>([0.4]);
  const [mixer, setMixer] = useState("x");
  const [st, setSt] = useState<any>();
  const [ls, setLs] = useState<any>();
  const { busy, error, run } = useAction();
  useEffect(() => { setGam((g) => Array.from({ length: p }, (_, i) => g[i] ?? 0.5)); setBet((b) => Array.from({ length: p }, (_, i) => b[i] ?? 0.4)); }, [p]);
  return (
    <Page title="Quantum Simulator" subtitle="Exact statevector of the QAOA state for chosen angles (≤ 18 qubits), plus the p = 1 energy landscape (≤ 14 qubits).">
      <RequireModel>{(ref) => (
        <Card>
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Layers p"><input className="input" type="number" min={1} max={6} value={p} onChange={(e) => setP(Math.max(1, Math.min(6, Number(e.target.value))))} /></Field>
            <Field label="Mixer"><select className="input" value={mixer} onChange={(e) => setMixer(e.target.value)}><option value="x">X</option><option value="xy_ring">XY ring</option></select></Field>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {gam.map((g, i) => <Field key={`g${i}`} label={`γ${i + 1} = ${g.toFixed(3)}`}><input type="range" min={0} max={Math.PI} step={0.01} value={g} onChange={(e) => setGam(gam.map((x, j) => (j === i ? Number(e.target.value) : x)))} className="w-full" /></Field>)}
            {bet.map((b, i) => <Field key={`b${i}`} label={`β${i + 1} = ${b.toFixed(3)}`}><input type="range" min={0} max={Math.PI / 2} step={0.01} value={b} onChange={(e) => setBet(bet.map((x, j) => (j === i ? Number(e.target.value) : x)))} className="w-full" /></Field>)}
          </div>
          <div className="mt-3 flex gap-2">
            <button className="btn" disabled={busy} onClick={() => run(async () => setSt(await api.post("/simulator/state", { ...ref, gammas: gam, betas: bet, mixer })))}>Simulate state</button>
            <button className="btn-secondary" disabled={busy} onClick={() => run(async () => setLs(await api.post("/qaoa/landscape", { ...ref, resolution: 30, mixer })))}>Scan p=1 landscape</button>
          </div>
        </Card>)}</RequireModel>
      <ErrorBox error={error} />
      {st && <Card title="Most probable basis states" actions={<KindBadge kind={st.execution_kind} />}>
        <p className="mb-2 text-sm">⟨H⟩ = <b>{fmt(st.expected_energy)}</b> (range {fmt(st.e_min)} … {fmt(st.e_max)}), P(ground) = <b>{fmt(st.ground_state_probability, 4)}</b></p>
        <div className="h-64"><ResponsiveContainer><BarChart data={st.top_states}><XAxis dataKey="bitstring" fontSize={9} angle={-45} textAnchor="end" height={60} /><YAxis fontSize={10} /><Tooltip formatter={(v: number) => v.toFixed(4)} /><Bar dataKey="probability" fill="#0ea5e9" /></BarChart></ResponsiveContainer></div>
        <p className="text-xs text-slate-600 dark:text-slate-400">Bitstrings are in variable order (x0 first).</p>
      </Card>}
      {ls && <Card title="p = 1 landscape ⟨H⟩(γ, β)"><Landscape gammas={ls.gammas} betas={ls.betas} energies={ls.energies} /></Card>}
    </Page>
  );
}

export function ProvidersPage() {
  const { user } = useAuth();
  const [data, err, reload] = useLoad(() => api.get("/providers"));
  const [exps] = useLoad(() => api.get("/experiments"));
  const [approvals, , reloadA] = useLoad(() => api.get("/approvals"));
  const [backends, setBackends] = useState<Record<string, any>>({});
  const [form, setForm] = useState({ experiment_id: "", provider: "ibm_quantum", backend: "", shots: 1000, p: 1, justification: "" });
  const { busy, error, run } = useAction();
  return (
    <Page title="Quantum Hardware Providers" subtitle="Provider status is detected from installed SDKs and server-side credentials. Nothing here is simulated as hardware." actions={<button className="btn-secondary" onClick={reload}>Refresh</button>}>
      <ErrorBox error={err} />
      <Note>Gate-model QAOA runs on gate-based QPUs (IBM, Braket devices). D-Wave is a quantum <b>annealer</b> and samples the QUBO directly — it is not QAOA. Every real-hardware job needs an administrator's approval.</Note>
      {data && <Card title="Providers">
        <table className="table"><thead><tr><th>provider</th><th>technology</th><th>SDK</th><th>credentials</th><th>available</th><th>notes</th><th /></tr></thead>
          <tbody>{data.providers.map((p: any) => (
            <tr key={p.name}><td className="font-medium">{p.name}</td><td>{p.technology ?? (p.via ? `via ${p.via}` : "—")}</td>
              <td>{p.sdk_installed === undefined ? "—" : p.sdk_installed ? "installed" : <span className="text-warn">missing ({p.sdk_module})</span>}</td>
              <td>{p.missing_credentials?.length ? <span className="text-warn">missing {p.missing_credentials.join(", ")}</span> : p.indirect ? "—" : "configured"}</td>
              <td>{p.available ? <span className="text-ok">yes</span> : "no"}</td><td className="text-xs">{p.note ?? p.docs}</td>
              <td>{!p.indirect && p.name !== "local_statevector" && <button className="btn-secondary" onClick={() => run(async () => setBackends({ ...backends, [p.name]: await api.get(`/providers/${p.name}/backends`) }))}>Backends</button>}</td></tr>))}</tbody></table>
      </Card>}
      {Object.entries(backends).map(([name, b]) => (
        <Card key={name} title={`Backends · ${name}`}>
          {b.unavailable && <Note tone="warn">{b.unavailable}</Note>}{b.error && <ErrorBox error={b.error} />}
          {b.backends.length > 0 && <table className="table"><thead><tr><th>name</th><th>kind</th><th>qubits</th><th>status</th><th>queue</th><th>cost</th></tr></thead>
            <tbody>{b.backends.map((x: any) => <tr key={x.name}><td className="font-mono text-xs">{x.name}</td><td><KindBadge kind={x.execution_kind} real={!x.is_simulator} /></td><td>{x.num_qubits ?? "—"}</td><td>{x.status}</td><td>{x.pending_jobs ?? "—"}</td><td className="text-xs">{x.cost_note}</td></tr>)}</tbody></table>}
        </Card>))}
      {can(user, "researcher") && <Card title="Request a real-hardware job (requires admin approval)">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Experiment"><select className="input" value={form.experiment_id} onChange={(e) => setForm({ ...form, experiment_id: e.target.value })}><option value="">Select…</option>{exps?.map((x: any) => <option key={x.id} value={x.id}>#{x.id} {x.name}</option>)}</select></Field>
          <Field label="Provider"><select className="input" value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>{["ibm_quantum", "aws_braket", "dwave"].map((p) => <option key={p}>{p}</option>)}</select></Field>
          <Field label="Backend / device ARN"><input className="input" value={form.backend} onChange={(e) => setForm({ ...form, backend: e.target.value })} /></Field>
          <Field label="Shots / reads"><input className="input" type="number" min={1} max={100000} value={form.shots} onChange={(e) => setForm({ ...form, shots: Number(e.target.value) })} /></Field>
          <Field label="QAOA p"><input className="input" type="number" min={1} max={10} value={form.p} onChange={(e) => setForm({ ...form, p: Number(e.target.value) })} /></Field>
          <Field label="Justification"><input className="input" value={form.justification} onChange={(e) => setForm({ ...form, justification: e.target.value })} /></Field>
        </div>
        <button className="btn mt-3" disabled={busy || !form.experiment_id || !form.backend} onClick={() => run(async () => { await api.post("/approvals", { ...form, experiment_id: Number(form.experiment_id) }); reloadA(); })}>Submit for approval</button>
        <ErrorBox error={error} />
      </Card>}
      {approvals && approvals.length > 0 && <Card title="Hardware requests">
        <table className="table"><thead><tr><th>id</th><th>provider</th><th>backend</th><th>shots</th><th>status</th><th>job</th><th>note</th></tr></thead>
          <tbody>{approvals.map((a: any) => <tr key={a.id}><td>{a.id}</td><td>{a.payload.provider}</td><td className="font-mono text-xs">{a.payload.backend}</td><td>{a.payload.shots}</td><td><StatusBadge status={a.status} /></td><td>{a.job_id ? `#${a.job_id}` : "—"}</td><td className="text-xs">{a.review_note}</td></tr>)}</tbody></table>
      </Card>}
      {data && <details className="card"><summary className="cursor-pointer text-sm font-medium">Raw status</summary><Json value={data} /></details>}
    </Page>
  );
}
