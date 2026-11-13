import { useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, waitForJob } from "../api";
import { Card, ErrorBox, fmt, KindBadge, Note, Spinner, StatusBadge } from "./ui";

/** Submit a job and follow it to completion. */
export function useJob() {
  const [job, setJob] = useState<any>();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const submit = async (body: { kind: string; params: any; experiment_id?: number }) => {
    setBusy(true); setError(undefined); setJob(undefined);
    try {
      const j = await api.post("/jobs", body);
      setJob(j);
      const done = ["queued", "running"].includes(j.status) ? await waitForJob(j.id, setJob) : j;
      setJob(done);
      return done;
    } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const follow = async (id: number) => { setBusy(true); try { setJob(await waitForJob(id, setJob)); } catch (e) { setError(e); } finally { setBusy(false); } };
  return { job, error, busy, submit, follow, setJob };
}

export function JobHeader({ job }: { job: any }) {
  if (!job) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span>Job <Link className="text-indigo-600 underline" to={`/results?job=${job.id}`}>#{job.id}</Link></span>
      <StatusBadge status={job.status} />
      <KindBadge kind={job.execution_kind} real={job.is_real_hardware} />
      {job.runtime_s != null && <span className="text-slate-500">{fmt(job.runtime_s, 2)} s</span>}
      {["queued", "running"].includes(job.status) && <Spinner label={job.status} />}
      {job.status === "done" && <>
        <button className="btn-secondary" onClick={() => api.download(`/reports/jobs/${job.id}?format=md`, `job-${job.id}-report.md`)}>Report (.md)</button>
        <button className="btn-secondary" onClick={() => api.download(`/reports/jobs/${job.id}?format=json`, `job-${job.id}.json`)}>Raw (.json)</button>
      </>}
      {job.error && <span className="text-rose-600">{job.error}</span>}
    </div>
  );
}

export function HistoryChart({ history, label = "⟨H⟩ per evaluation" }: { history: number[]; label?: string }) {
  if (!history?.length) return null;
  const data = history.map((v, i) => ({ i, v }));
  return (
    <div className="h-56">
      <div className="label">{label}</div>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={data} margin={{ left: 8, right: 8, top: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="i" fontSize={10} />
          <YAxis fontSize={10} domain={["auto", "auto"]} />
          <Tooltip formatter={(v: number) => v.toFixed(5)} />
          <Line type="monotone" dataKey="v" stroke="#6366f1" dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SamplesTable({ rows, max = 15 }: { rows: any[]; max?: number }) {
  if (!rows?.length) return <p className="text-sm text-slate-500">No samples.</p>;
  const hasFeas = rows.some((r) => "feasible" in r);
  return (
    <div className="overflow-auto">
      <table className="table">
        <thead><tr><th>assignment (x0…)</th><th>count</th><th>freq</th><th>QUBO energy</th>{hasFeas && <><th>feasible</th><th>objective</th></>}</tr></thead>
        <tbody>{rows.slice(0, max).map((r, k) => (
          <tr key={k}><td className="font-mono text-xs">{r.decision_bitstring ?? r.bitstring}</td><td>{r.count}</td><td>{fmt(r.frequency, 3)}</td>
            <td className="tabular-nums">{fmt(r.qubo_energy)}</td>
            {hasFeas && <><td>{r.feasible ? "✓" : <span className="text-rose-600">✗</span>}</td><td className="tabular-nums">{fmt(r.objective)}</td></>}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function RankingTable({ ranking }: { ranking: any[] }) {
  if (!ranking?.length) return null;
  return (
    <div className="overflow-auto">
      <table className="table">
        <thead><tr><th>#</th><th>solver</th><th>execution</th><th>QUBO energy</th><th>objective</th><th>feasible</th><th>gap to best</th></tr></thead>
        <tbody>{ranking.map((r) => (
          <tr key={r.solver}><td>{r.rank}</td><td className="font-medium">{r.solver}</td><td><KindBadge kind={r.execution_kind} real={r.is_real_hardware} /></td>
            <td className="tabular-nums">{fmt(r.qubo_energy)}</td><td className="tabular-nums">{fmt(r.objective)}</td><td>{r.feasible === false ? <span className="text-rose-600">✗</span> : r.feasible ? "✓" : "—"}</td>
            <td className="tabular-nums">{fmt(r.gap_to_best)}</td></tr>
        ))}</tbody>
      </table>
      <p className="mt-1 text-xs text-slate-500">Reference: {ranking[0].reference}.</p>
    </div>
  );
}

export function DomainView({ domain }: { domain: any }) {
  if (!domain) return null;
  const it = domain.interpretation ?? {};
  return (
    <Card title="What this means for your problem">
      {domain.evaluation && <Note tone={domain.evaluation.feasible ? "ok" : "warn"}>
        {domain.evaluation.feasible ? "The solution satisfies every original constraint." : `The solution violates: ${Object.keys(domain.evaluation.violations).join(", ")}.`}
        {" "}Objective value: <b>{fmt(domain.evaluation.objective)}</b>.</Note>}
      <dl className="mt-3 grid gap-2 text-sm md:grid-cols-2">
        {Object.entries(it).map(([k, v]) => (
          <div key={k}><dt className="label">{k.replace(/_/g, " ")}</dt><dd className="break-words">{typeof v === "object" ? <pre className="whitespace-pre-wrap text-xs">{JSON.stringify(v, null, 1)}</pre> : typeof v === "boolean" ? (v ? "yes" : "no") : fmt(v)}</dd></div>
        ))}
      </dl>
    </Card>
  );
}

export function JobError({ error }: { error: unknown }) { return <ErrorBox error={error} />; }
