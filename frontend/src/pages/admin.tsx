import DOMPurify from "dompurify";
import { marked } from "marked";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBox, fmt, Json, Note, Page, Stat, StatusBadge, useAction, useLoad } from "../components/ui";

export function ApiPage() {
  const [keys, err, reload] = useLoad(() => api.get("/apikeys"));
  const [name, setName] = useState("");
  const [created, setCreated] = useState<any>();
  const { busy, error, run } = useAction();
  const origin = window.location.origin;
  return (
    <Page title="API Management" subtitle="Personal API keys for scripts and CI. Keys inherit your role.">
      <ErrorBox error={err || error} />
      <Card title="Create key">
        <div className="flex gap-2"><input className="input" placeholder="key name (e.g. notebook)" value={name} onChange={(e) => setName(e.target.value)} /><button className="btn" disabled={busy || !name} onClick={() => run(async () => { setCreated(await api.post("/apikeys", { name })); setName(""); reload(); })}>Create</button></div>
        {created && <Note tone="ok"><div>Copy this key now — it will not be shown again:</div><code className="mt-1 block break-all">{created.key}</code><button className="btn-secondary mt-2" onClick={() => navigator.clipboard?.writeText(created.key)}>Copy</button></Note>}
      </Card>
      <Card title="Your keys">
        <table className="table"><thead><tr><th>name</th><th>prefix</th><th>created</th><th>last used</th><th>status</th><th /></tr></thead>
          <tbody>{keys?.map((k: any) => <tr key={k.id}><td>{k.name}</td><td className="font-mono text-xs">{k.prefix}…</td><td className="text-xs">{new Date(k.created_at).toLocaleString()}</td><td className="text-xs">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
            <td>{k.revoked ? <span className="text-rose-600">revoked</span> : "active"}</td><td>{!k.revoked && <button className="btn-secondary" onClick={() => { if (window.confirm(`Revoke key "${k.name}"? Scripts using it will stop working.`)) run(async () => { await api.del(`/apikeys/${k.id}`); reload(); }); }}>Revoke</button>}</td></tr>)}</tbody></table>
      </Card>
      <Card title="Usage">
        <p className="text-sm">Interactive OpenAPI documentation: <a className="text-indigo-600 underline" href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a></p>
        <pre className="mt-2 overflow-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{`curl -X POST ${origin}/api/jobs \\
  -H "X-API-Key: $QOPT_KEY" -H "Content-Type: application/json" \\
  -d '{"kind":"classical","params":{"qubo":{"variables":["a","b"],"linear":{"0":1},"quadratic":[[0,1,-2]]},"solver":"exhaustive"}}'`}</pre>
      </Card>
    </Page>
  );
}

export function UsersPage() {
  const { user: me } = useAuth();
  const [users, err, reload] = useLoad(() => api.get("/users"));
  const [form, setForm] = useState({ email: "", name: "", password: "", role: "researcher" });
  const { busy, error, run } = useAction();
  return (
    <Page title="User and Role Management" subtitle="admin: everything · researcher: build models, run jobs and agents, request hardware · viewer: read-only.">
      <ErrorBox error={err || error} />
      <Card title="Create user">
        <div className="grid gap-2 md:grid-cols-5">
          <input className="input" placeholder="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="input" placeholder="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className="input" type="password" placeholder="initial password (≥10)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option>researcher</option><option>viewer</option><option>admin</option></select>
          <button className="btn" disabled={busy || !form.email || form.password.length < 10} onClick={() => run(async () => { await api.post("/users", form); setForm({ email: "", name: "", password: "", role: "researcher" }); reload(); })}>Create</button>
        </div>
      </Card>
      <Card title="Users">
        <table className="table"><thead><tr><th>email</th><th>name</th><th>role</th><th>active</th><th>created</th></tr></thead>
          <tbody>{users?.map((u: any) => <tr key={u.id}><td>{u.email}</td><td>{u.name}</td>
            <td><select className="input" value={u.role} disabled={u.id === me?.id} onChange={(e) => run(async () => { await api.patch(`/users/${u.id}`, { role: e.target.value }); reload(); })}><option>admin</option><option>researcher</option><option>viewer</option></select></td>
            <td><input type="checkbox" checked={u.is_active} disabled={u.id === me?.id} onChange={(e) => run(async () => { await api.patch(`/users/${u.id}`, { is_active: e.target.checked }); reload(); })} /></td>
            <td className="text-xs">{new Date(u.created_at).toLocaleDateString()}</td></tr>)}</tbody></table>
      </Card>
    </Page>
  );
}

export function AdminPage() {
  const [cfg, cerr] = useLoad(() => api.get("/admin/config"));
  const [approvals, aerr, reloadA] = useLoad(() => api.get("/approvals"));
  const [action, setAction] = useState("");
  const [audit, auerr, reloadAudit] = useLoad(() => api.get(`/admin/audit?limit=200${action ? `&action=${action}` : ""}`), [action]);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const { busy, error, run } = useAction();
  return (
    <Page title="Administration" subtitle="Configuration (no secrets are ever returned), hardware approvals and the audit log.">
      <ErrorBox error={cerr || aerr || auerr || error} />
      <Card title="Hardware job approvals">
        {approvals?.length === 0 && <p className="text-sm text-slate-500">No requests.</p>}
        <table className="table"><tbody>{approvals?.map((a: any) => (
          <tr key={a.id}><td>#{a.id}</td><td className="text-xs">user {a.requester_id}</td><td className="text-xs"><b>{a.payload.provider}</b> · {a.payload.backend} · {a.payload.shots} shots · p={a.payload.p ?? 1}<div className="text-slate-500">{a.payload.justification}</div></td><td><StatusBadge status={a.status} /></td>
            <td>{a.status === "pending" ? <div className="flex gap-1"><input className="input w-40" placeholder="note" value={notes[a.id] ?? ""} onChange={(e) => setNotes({ ...notes, [a.id]: e.target.value })} />
              <button className="btn" disabled={busy} onClick={() => { if (window.confirm("Approve? This will submit a job to the provider and may incur charges.")) run(async () => { await api.post(`/approvals/${a.id}/approve`, { note: notes[a.id] ?? "" }); reloadA(); }); }}>Approve</button>
              <button className="btn-danger" disabled={busy} onClick={() => run(async () => { await api.post(`/approvals/${a.id}/reject`, { note: notes[a.id] ?? "" }); reloadA(); })}>Reject</button></div> : <span className="text-xs">{a.review_note}{a.job_id ? ` · job #${a.job_id}` : ""}</span>}</td></tr>))}</tbody></table>
      </Card>
      <Card title="Audit log" actions={<div className="flex gap-2"><input className="input w-48" placeholder="filter action (e.g. login)" value={action} onChange={(e) => setAction(e.target.value)} /><button className="btn-secondary" onClick={reloadAudit}>Refresh</button></div>}>
        <div className="max-h-96 overflow-auto"><table className="table"><thead><tr><th>time</th><th>user</th><th>action</th><th>resource</th><th>ok</th><th>ip</th></tr></thead>
          <tbody>{audit?.map((e: any) => <tr key={e.id}><td className="text-xs">{new Date(e.ts).toLocaleString()}</td><td>{e.user_id ?? "—"}</td><td>{e.action}</td><td className="text-xs">{e.resource}</td><td>{e.success ? "✓" : <span className="text-rose-600">✗</span>}</td><td className="text-xs">{e.ip}</td></tr>)}</tbody></table></div>
      </Card>
      {cfg && <Card title="Configuration">
        {!cfg.jwt_secret_configured && <Note tone="warn">QOPT_JWT_SECRET is not set — an ephemeral secret is in use (development only).</Note>}
        <Json value={cfg} />
      </Card>}
    </Page>
  );
}

export function UsagePage() {
  const [days, setDays] = useState(30);
  const [u, err] = useLoad(() => api.get(`/usage/summary?days=${days}`), [days]);
  return (
    <Page title="Usage and Cost Monitoring" subtitle="Recorded per job and per agent run in this installation's database." actions={<select className="input" value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option></select>}>
      <ErrorBox error={err} />
      {u && <>
        <div className="grid gap-3 sm:grid-cols-4">
          <Stat label="AI agent cost (est.)" value={`$${fmt(u.totals.agent_cost_usd, 4)}`} hint={u.agent_cost_note} />
          <Stat label="Input tokens" value={u.totals.input_tokens.toLocaleString()} />
          <Stat label="Output tokens" value={u.totals.output_tokens.toLocaleString()} />
          <Stat label="Compute time" value={`${fmt(u.totals.compute_s, 1)} s`} />
        </div>
        <Note>{u.hardware_cost_note}</Note>
        <Card title="Per day">
          {u.by_day.length === 0 ? <p className="text-sm text-slate-500">No usage recorded in this window.</p> : <div className="grid gap-4 md:grid-cols-2">
            <div className="h-56"><div className="label">compute seconds</div><ResponsiveContainer height="90%"><BarChart data={u.by_day}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" fontSize={10} /><YAxis fontSize={10} /><Tooltip /><Bar dataKey="compute_s" fill="#0ea5e9" /></BarChart></ResponsiveContainer></div>
            <div className="h-56"><div className="label">agent cost (USD, est.)</div><ResponsiveContainer height="90%"><BarChart data={u.by_day}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" fontSize={10} /><YAxis fontSize={10} /><Tooltip /><Bar dataKey="agent_cost_usd" fill="#6366f1" /></BarChart></ResponsiveContainer></div>
          </div>}
        </Card>
      </>}
    </Page>
  );
}

export function DocsPage() {
  const [list, err] = useLoad(() => api.get("/docs-content"));
  const [slug, setSlug] = useState("USER_GUIDE");
  const [md, setMd] = useState("");
  const [derr, setDerr] = useState<unknown>();
  useEffect(() => { api.get(`/docs-content/${slug}`).then((d) => { setMd(d.markdown); setDerr(undefined); }).catch(setDerr); }, [slug]);
  const html = DOMPurify.sanitize(marked.parse(md, { async: false }) as string);
  return (
    <Page title="Documentation and Tutorials">
      <ErrorBox error={err || derr} />
      <div className="grid gap-4 lg:grid-cols-4">
        <Card title="Documents"><ul className="space-y-1 text-sm">{list?.map((d: any) => <li key={d.slug}><button className={`text-left ${slug === d.slug ? "font-semibold text-indigo-600" : "hover:underline"}`} onClick={() => setSlug(d.slug)}>{d.title}</button></li>)}</ul></Card>
        <Card className="lg:col-span-3"><article className="prose-doc" dangerouslySetInnerHTML={{ __html: html }} /></Card>
      </div>
      <div><div className="label">Interactive API reference</div><a className="text-indigo-600 underline" href="/api/docs" target="_blank" rel="noreferrer">OpenAPI / Swagger UI</a></div>
    </Page>
  );
}
