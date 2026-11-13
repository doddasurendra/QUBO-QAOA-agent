import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBox, Field, fmt, KindBadge, Note, Page, Stat, StatusBadge, useAction, useLoad } from "../components/ui";

export function LoginPage() {
  const { login } = useAuth();
  const [status, setStatus] = useState<{ bootstrap_required: boolean; registration_open: boolean }>();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();
  useEffect(() => { api.get("/auth/status").then(setStatus).catch(() => {}); }, []);
  const boot = status?.bootstrap_required;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const r = await api.post(boot ? "/auth/bootstrap" : "/auth/login", boot ? { email, password, name } : { email, password });
      login(r.access_token, r.user);
    });
  };
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-3">
        <div>
          <h1 className="text-xl font-bold">qopt</h1>
          <p className="text-sm text-slate-500">QUBO / QAOA hybrid optimisation platform</p>
        </div>
        {boot && <Note tone="warn">No users exist yet. Create the first <b>administrator</b> account.</Note>}
        {boot && <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>}
        <Field label="Email"><input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></Field>
        <Field label="Password" hint={boot ? "At least 10 characters." : undefined}>
          <input className="input" type="password" required minLength={boot ? 10 : 1} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={boot ? "new-password" : "current-password"} />
        </Field>
        <ErrorBox error={error} />
        <button className="btn w-full justify-center" disabled={busy}>{boot ? "Create administrator" : "Sign in"}</button>
      </form>
    </div>
  );
}

export function OverviewPage() {
  const [ov, err, reload] = useLoad(() => api.get("/dashboard/overview"));
  const [providers] = useLoad(() => api.get("/providers"));
  const jobsByKind = ov ? Object.entries(ov.jobs_by_kind as Record<string, number>).map(([k, v]) => ({ k, v })) : [];
  return (
    <Page title="Overview" subtitle="Live figures from this installation's database." actions={<button className="btn-secondary" onClick={reload}>Refresh</button>}>
      <ErrorBox error={err} />
      {ov && <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Experiments" value={ov.experiments} />
          <Stat label="Jobs completed" value={ov.jobs_by_status.done ?? 0} hint={`${ov.jobs_by_status.error ?? 0} failed · ${(ov.jobs_by_status.running ?? 0) + (ov.jobs_by_status.queued ?? 0)} active`} />
          <Stat label="Real-QPU jobs" value={ov.real_hardware_jobs} hint="Only counted when the provider reports real hardware" />
          <Stat label="Pending approvals" value={ov.pending_approvals} />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Jobs by kind" className="lg:col-span-1">
            {jobsByKind.length ? <div className="h-48"><ResponsiveContainer><BarChart data={jobsByKind}><XAxis dataKey="k" fontSize={11} /><YAxis allowDecimals={false} fontSize={11} /><Tooltip /><Bar dataKey="v" fill="#6366f1" /></BarChart></ResponsiveContainer></div>
              : <p className="text-sm text-slate-500">No jobs yet. Try <Link className="text-indigo-600 underline" to="/industry">Industry Solutions</Link>.</p>}
          </Card>
          <Card title="Execution environment" className="lg:col-span-2">
            <ul className="space-y-1 text-sm">
              <li>AI agents: {ov.agents_available ? <span className="text-emerald-600">available</span> : <span className="text-amber-600">unavailable — no Anthropic API credentials on the server</span>}</li>
              <li>Quantum execution available: {ov.providers_available.join(", ")}</li>
              {providers && <li>Real hardware providers configured: {(providers.providers as any[]).filter((p) => p.available && !["local_statevector", "qiskit_aer"].includes(p.name)).map((p) => p.name).join(", ") || <span className="text-amber-600">none (SIMULATOR mode)</span>}</li>}
            </ul>
          </Card>
        </div>
        <Card title="Recent jobs">
          {ov.recent_jobs.length === 0 ? <p className="text-sm text-slate-500">No jobs yet.</p> : (
            <table className="table"><thead><tr><th>id</th><th>kind</th><th>solver/agent</th><th>status</th><th>execution</th><th>runtime</th><th>created</th></tr></thead>
              <tbody>{ov.recent_jobs.map((j: any) => (
                <tr key={j.id}><td><Link className="text-indigo-600 underline" to={`/results?job=${j.id}`}>#{j.id}</Link></td><td>{j.kind}</td><td>{j.solver ?? "—"}</td><td><StatusBadge status={j.status} /></td>
                  <td><KindBadge kind={j.execution_kind} real={j.is_real_hardware} /></td><td>{fmt(j.runtime_s, 2)} s</td><td className="text-xs">{new Date(j.created_at).toLocaleString()}</td></tr>))}</tbody></table>)}
        </Card>
      </>}
    </Page>
  );
}
