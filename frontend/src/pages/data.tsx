import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { can, useAuth } from "../auth";
import { JobHeader, RankingTable } from "../components/jobs";
import { useActiveModel } from "../components/model";
import { Card, ErrorBox, Field, FOCUS, fmt, Json, KindBadge, Note, Page, StatusBadge, useAction, useLoad } from "../components/ui";

export function ExperimentsPage() {
  const { setActive } = useActiveModel();
  const { user } = useAuth();
  const [list, err, reload] = useLoad(() => api.get("/experiments"));
  const [sel, setSel] = useState<any>();
  const { busy, error, run } = useAction();
  return (
    <Page title="Experiment Management" subtitle="Saved models with their full job history." actions={<button className="btn-secondary" onClick={reload}>Refresh</button>}>
      <ErrorBox error={err || error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Experiments (${list?.length ?? 0})`}>
          {list?.length === 0 && <p className="text-sm text-slate-600 dark:text-slate-400">None yet. Create one in the Model Builder or Industry Solutions.</p>}
          <table className="table"><tbody>{list?.map((e: any) => (
            <tr key={e.id} className={sel?.id === e.id ? "bg-indigo-50 dark:bg-indigo-950" : ""}>
              <td><button className="text-left text-indigo-600 underline" onClick={() => run(async () => setSel(await api.get(`/experiments/${e.id}`)))}>#{e.id} {e.name}</button><div className="text-xs text-slate-600 dark:text-slate-400">{e.source} · {new Date(e.created_at).toLocaleString()}</div></td>
              <td className="text-xs">{e.summary?.num_decision_variables ?? e.summary?.num_variables} vars</td>
              <td><button className="btn-secondary" onClick={() => setActive({ ref: { experiment_id: e.id }, label: `Experiment #${e.id} ${e.name}` })}>Use</button></td>
            </tr>))}</tbody></table>
        </Card>
        {sel && <Card title={`#${sel.id} ${sel.name}`} actions={can(user, "researcher") && <button className="btn-danger" disabled={busy} onClick={() => { if (window.confirm(`Delete experiment #${sel.id}? Jobs are kept but unlinked.`)) run(async () => { await api.del(`/experiments/${sel.id}`); setSel(undefined); reload(); }); }}>Delete</button>}>
          <p className="text-sm">{sel.description}</p>
          <div className="label mt-3">Jobs</div>
          {sel.jobs.length === 0 ? <p className="text-sm text-slate-600 dark:text-slate-400">No jobs yet.</p> : <table className="table"><tbody>{sel.jobs.map((j: any) => <tr key={j.id}><td>#{j.id}</td><td>{j.kind}</td><td><StatusBadge status={j.status} /></td><td><KindBadge kind={j.execution_kind} real={j.is_real_hardware} /></td><td>{fmt(j.runtime_s, 2)} s</td></tr>)}</tbody></table>}
          <details className="mt-3"><summary className="cursor-pointer text-sm">Model</summary><Json value={{ summary: sel.summary, spec: sel.model_spec, input: sel.input_data }} /></details>
        </Card>}
      </div>
    </Page>
  );
}

export function DatasetsPage() {
  const { user } = useAuth();
  const [list, err, reload] = useLoad(() => api.get("/datasets"));
  const [probs] = useLoad(() => api.get("/industries"));
  const [view, setView] = useState<any>();
  const [form, setForm] = useState({ name: "", problem_key: "", content: "{}" });
  const [file, setFile] = useState<File | null>(null);
  const { busy, error, run } = useAction();
  return (
    <Page title="Dataset Management" subtitle="Inputs for industry templates. SAMPLE datasets are synthetic and clearly labelled." actions={<button className="btn-secondary" onClick={reload}>Refresh</button>}>
      <ErrorBox error={err || error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Datasets">
          <table className="table"><thead><tr><th>name</th><th>template</th><th /></tr></thead><tbody>{list?.map((d: any) => (
            <tr key={d.id}><td>{d.is_sample && <span className="badge mr-1 bg-amber-100 text-amber-800">SAMPLE</span>}{d.name}</td><td className="text-xs">{d.problem_key ?? "—"}</td>
              <td className="whitespace-nowrap"><button className="btn-secondary" onClick={() => run(async () => setView(await api.get(`/datasets/${d.id}`)))}>View</button>
                {can(user, "researcher") && (!d.is_sample || can(user, "admin")) && <button className="btn-secondary ml-1" onClick={() => { if (window.confirm(`Delete dataset "${d.name}"?`)) run(async () => { await api.del(`/datasets/${d.id}`); reload(); }); }}>Delete</button>}</td></tr>))}</tbody></table>
        </Card>
        {can(user, "researcher") && <Card title="Add dataset">
          <div className="grid gap-2 md:grid-cols-2">
            <Field label="Name"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Template (validates content)"><select className="input" value={form.problem_key} onChange={(e) => setForm({ ...form, problem_key: e.target.value })}><option value="">none</option>{probs?.map((p: any) => <option key={p.key} value={p.key}>{p.key}</option>)}</select></Field>
          </div>
          <Field label="Content (JSON)"><textarea className="input h-40 font-mono text-xs" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} /></Field>
          <button className="btn mt-2" disabled={busy || !form.name} onClick={() => run(async () => { await api.post("/datasets", { name: form.name, problem_key: form.problem_key || null, content: JSON.parse(form.content) }); reload(); })}>Save</button>
          <div className="mt-4 border-t pt-3 dark:border-slate-800">
            <div className="label">or upload .json / .csv (≤ 5 MB)</div>
            <input type="file" aria-label="Dataset file (.json or .csv)" accept=".json,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="text-sm" />
            <button className="btn-secondary mt-2" disabled={busy || !file || !form.name} onClick={() => run(async () => { const f = new FormData(); f.append("file", file!); f.append("name", form.name); f.append("problem_key", form.problem_key); await api.upload("/datasets/upload", f); reload(); })}>Upload</button>
          </div>
        </Card>}
      </div>
      {view && <Card title={view.name}>{view.is_sample && <Note tone="warn">{view.description}</Note>}<Json value={view.content} /></Card>}
    </Page>
  );
}

export function ResearchPage() {
  const { user } = useAuth();
  const [list, err, reload] = useLoad(() => api.get("/research"));
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any>();
  const [doc, setDoc] = useState<any>();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const { busy, error, run } = useAction();
  return (
    <Page title="Quantum Research Library" subtitle="Upload papers and notes (.txt, .md, .tex; .pdf when pypdf is installed on the server). The Research Assistant agent searches this library.">
      <ErrorBox error={err || error} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Search">
          <div className="flex gap-2"><input className="input" type="search" aria-label="Search the research library" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q.length > 1 && run(async () => setHits(await api.get(`/research/search?q=${encodeURIComponent(q)}`)))} placeholder="e.g. constraint-preserving mixer" />
            <button className="btn" disabled={busy || q.length < 2} onClick={() => run(async () => setHits(await api.get(`/research/search?q=${encodeURIComponent(q)}`)))}>Search</button></div>
          {hits && <div className="mt-3 space-y-2">{hits.results.length === 0 ? <p className="text-sm text-slate-600 dark:text-slate-400">No matches.</p> : hits.results.map((h: any, i: number) => (
            <div key={i} className="rounded border border-slate-200 p-2 text-sm dark:border-slate-800"><div className="font-medium">{h.title} <span className="text-xs text-slate-600 dark:text-slate-400">score {h.score}</span></div><p className="mt-1 text-xs">{h.passage.slice(0, 400)}…</p></div>))}
            <p className="text-xs text-slate-600 dark:text-slate-400">{hits.method}</p></div>}
        </Card>
        {can(user, "researcher") && <Card title="Upload">
          <Field label="Title"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <input type="file" aria-label="Document file (.txt, .md, .tex or .pdf)" accept=".txt,.md,.tex,.pdf" className="mt-2 text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <button className="btn mt-2" disabled={busy || !file} onClick={() => run(async () => { const f = new FormData(); f.append("file", file!); f.append("title", title); await api.upload("/research/upload", f); setTitle(""); reload(); })}>Upload</button>
        </Card>}
      </div>
      <Card title={`Documents (${list?.length ?? 0})`}>
        <table className="table"><tbody>{list?.map((d: any) => <tr key={d.id}><td><button className="text-indigo-600 underline" onClick={() => run(async () => setDoc(await api.get(`/research/${d.id}`)))}>{d.title}</button><div className="text-xs text-slate-600 dark:text-slate-400">{d.filename} · {(d.size_bytes / 1024).toFixed(1)} KB</div></td>
          <td>{can(user, "researcher") && <button className="btn-secondary" onClick={() => { if (window.confirm(`Delete "${d.title}"?`)) run(async () => { await api.del(`/research/${d.id}`); reload(); }); }}>Delete</button>}</td></tr>)}</tbody></table>
      </Card>
      {doc && <Card title={doc.title}><pre tabIndex={0} role="region" aria-label={`Text of ${doc.title}`} className={`max-h-96 overflow-auto whitespace-pre-wrap text-xs ${FOCUS}`}>{doc.content}</pre></Card>}
    </Page>
  );
}

export function ResultsPage() {
  const [params, setParams] = useSearchParams();
  const [kind, setKind] = useState("");
  const [list, err, reload] = useLoad(() => api.get(`/jobs${kind ? `?kind=${kind}` : ""}`), [kind]);
  const jid = params.get("job");
  const [job, jerr] = useLoad(() => (jid ? api.get(`/jobs/${jid}`) : Promise.resolve(undefined)), [jid]);
  const { error, run } = useAction();
  return (
    <Page title="Results and Reports" subtitle="Every job with its raw result; download Markdown reports or JSON." actions={<button className="btn-secondary" onClick={reload}>Refresh</button>}>
      <ErrorBox error={err || jerr || error} />
      <div className="flex gap-2">{["", "classical", "qaoa", "hybrid", "hardware", "benchmark", "agent"].map((k) => <button key={k} className={kind === k ? "btn" : "btn-secondary"} onClick={() => setKind(k)}>{k || "all"}</button>)}</div>
      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Jobs" className="lg:col-span-2">
          <div role="region" aria-label="Job list" tabIndex={0} className={`max-h-[36rem] overflow-auto ${FOCUS}`}><table className="table"><tbody>{list?.map((j: any) => (
            <tr key={j.id} className={String(j.id) === jid ? "bg-indigo-50 dark:bg-indigo-950" : ""}><td><button className="text-indigo-600 underline" onClick={() => setParams({ job: String(j.id) })}>#{j.id}</button></td><td>{j.kind}</td><td className="text-xs">{j.solver ?? ""}</td><td><StatusBadge status={j.status} /></td><td><KindBadge kind={j.execution_kind} real={j.is_real_hardware} /></td>
              <td>{["queued", "running"].includes(j.status) && <button className="btn-secondary" onClick={() => run(async () => { await api.post(`/jobs/${j.id}/cancel`); reload(); })}>Cancel</button>}</td></tr>))}</tbody></table></div>
        </Card>
        <div className="space-y-3 lg:col-span-3">
          {job ? <>
            <Card title={`Job #${job.id}`}><JobHeader job={job} />{job.result?.ranking && <div className="mt-3"><RankingTable ranking={job.result.ranking} /></div>}</Card>
            {job.kind === "agent" && job.result && <Card title="Agent answer"><p className="whitespace-pre-wrap text-sm">{job.result.final_text}</p></Card>}
            <Card title="Parameters"><Json value={job.params} max={120} /></Card>
            <Card title="Result"><Json value={job.result} /></Card>
          </> : <Note>Select a job to inspect it.</Note>}
        </div>
      </div>
    </Page>
  );
}
