import { useState } from "react";
import { api, waitForJob } from "../api";
import { can, useAuth } from "../auth";
import { useActiveModel } from "../components/model";
import { Card, ErrorBox, Field, fmt, Json, Note, Page, Spinner, StatusBadge, useLoad } from "../components/ui";

type Turn = { role: "user" | "agent"; text: string; job?: any };

const EXAMPLES = [
  "Optimise my investment portfolio with a maximum budget of ₹10 lakh and reduce risk.",
  "Distribute 5G traffic across network towers while minimizing congestion.",
  "Schedule 100 electric vehicles for charging without overloading the grid.",
];

function Transcript({ steps }: { steps: any[] }) {
  return (
    <ol className="space-y-1 text-xs">
      {steps.map((s, i) => s.type === "tool" ? (
        <li key={i} className="rounded border border-slate-200 p-1.5 dark:border-slate-800">
          <span className="font-mono font-semibold">🔧 {s.tool}</span> <span className="text-slate-500">{fmt(s.duration_s, 2)}s</span>
          {s.error && <span className="ml-2 text-rose-600">{s.error}</span>}
          {s.questions && <span className="ml-2 text-amber-600">asked the user {s.questions.length} question(s)</span>}
          <details><summary className="cursor-pointer text-slate-500">input / output</summary><Json value={{ input: s.input, output: s.output_preview?.slice(0, 1500) }} max={60} /></details>
          {s.delegated_steps && <div className="ml-3 mt-1 border-l pl-2"><Transcript steps={s.delegated_steps} /></div>}
        </li>
      ) : s.text ? <li key={i} className="text-slate-600 dark:text-slate-300">💬 {s.text.slice(0, 300)}{s.text.length > 300 ? "…" : ""}</li> : null)}
    </ol>
  );
}

function AgentChat({ agent, title, placeholder }: { agent: string; title: string; placeholder: string }) {
  const { user } = useAuth();
  const { setActive } = useActiveModel();
  const [info] = useLoad(() => api.get("/agents"));
  const [turns, setTurns] = useState<Turn[]>([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>();
  const [last, setLast] = useState<number>();
  const available = info?.credentials?.api_credentials_in_env;

  const send = async (text: string) => {
    if (!text.trim()) return;
    setBusy(true); setErr(undefined);
    setTurns((t) => [...t, { role: "user", text }]);
    setMsg("");
    try {
      const j = await api.post(`/agents/${agent}/run`, { message: text, continue_job_id: last });
      const done = await waitForJob(j.id, undefined, 1500);
      if (done.status !== "done") throw new Error(done.error ?? `job ${done.status}`);
      setLast(done.id);
      setTurns((t) => [...t, { role: "agent", text: done.result.final_text || "(no text)", job: done }]);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4">
      {info && !available && <Note tone="warn">AI agents are <b>unavailable</b>: the server has no Anthropic API credentials (set <code>ANTHROPIC_API_KEY</code> on the backend). The optimisation tools the agents use are all available directly from the other pages. API usage is billed per token and is separate from any Claude subscription.</Note>}
      {!can(user, "researcher") && <Note tone="warn">Viewers cannot run agents.</Note>}
      <Card title={title}>
        <div className="space-y-3">
          {turns.length === 0 && <div className="space-y-1">{EXAMPLES.map((e) => <button key={e} className="btn-secondary block w-full text-left" disabled={!available || busy} onClick={() => send(e)}>{e}</button>)}</div>}
          {turns.map((t, i) => (
            <div key={i} className={`rounded-lg p-3 text-sm ${t.role === "user" ? "ml-10 bg-indigo-50 dark:bg-indigo-950" : "mr-10 bg-slate-100 dark:bg-slate-800"}`}>
              <div className="whitespace-pre-wrap">{t.text}</div>
              {t.job && <div className="mt-2 space-y-2 border-t pt-2 text-xs dark:border-slate-700">
                <div className="flex flex-wrap items-center gap-2"><StatusBadge status={t.job.result.status} /><span>{t.job.result.usage.requests} model calls · {t.job.result.usage.input_tokens + t.job.result.usage.output_tokens} tokens · ≈ ${fmt(t.job.result.usage.cost_usd, 4)}</span>
                  {t.job.result.model_ids.length > 0 && <span>models saved as experiments</span>}
                  {t.job.result.approvals.length > 0 && <span className="text-amber-600">hardware approval requested (#{t.job.result.approvals.join(", ")})</span>}</div>
                {t.job.result.error && <span className="text-rose-600">{t.job.result.error}</span>}
                <details><summary className="cursor-pointer">Tool calls ({t.job.result.steps.filter((s: any) => s.type === "tool").length})</summary><Transcript steps={t.job.result.steps} /></details>
              </div>}
            </div>
          ))}
          {busy && <Spinner label="Agent working (calling tools)…" />}
          <ErrorBox error={err} />
          <div className="flex gap-2">
            <textarea className="input h-20" placeholder={placeholder} value={msg} onChange={(e) => setMsg(e.target.value)} disabled={!available || busy}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(msg); }} />
            <div className="flex flex-col gap-2"><button className="btn" disabled={!available || busy || !msg.trim()} onClick={() => send(msg)}>Send</button>
              <button className="btn-secondary" disabled={busy} onClick={() => { setTurns([]); setLast(undefined); }}>New</button></div>
          </div>
          <p className="text-xs text-slate-500">Ctrl+Enter to send. Follow-ups continue the same conversation. Models the agent creates appear in Experiments — <button className="underline" onClick={() => api.get("/experiments").then((x) => x[0] && setActive({ ref: { experiment_id: x[0].id }, label: `Experiment #${x[0].id} ${x[0].name}` }))}>use the latest as active model</button>.</p>
        </div>
      </Card>
    </div>
  );
}

export function AssistantPage() {
  return (
    <Page title="AI Quantum Assistant" subtitle="Describe an optimisation problem in plain language. The agent formulates it, validates the QUBO, runs solvers and explains the result — every number comes from a tool call.">
      <AgentChat agent="problem_understanding" title="Problem Understanding Agent" placeholder="Describe your optimisation problem, including the numbers you have…" />
    </Page>
  );
}

export function AgentsPage() {
  const [info, err] = useLoad(() => api.get("/agents"));
  const [agent, setAgent] = useState("research_assistant");
  const [jobs] = useLoad(() => api.get("/jobs?kind=agent&limit=20"));
  return (
    <Page title="AI Agent Management" subtitle="Specialised Claude agents, their tool permissions, budgets and recent runs.">
      <ErrorBox error={err} />
      {info && <>
        <Card title="Configuration">
          <ul className="text-sm"><li>Model: <code>{info.credentials.model}</code></li><li>Credentials on server: {info.credentials.api_credentials_in_env ? "yes" : "no"}</li>
            <li>Budget per run: ${info.budgets.per_run_usd} · per user per day: ${info.budgets.per_user_daily_usd}</li><li className="text-xs text-slate-500">{info.credentials.note}</li></ul>
        </Card>
        <div className="grid gap-3 md:grid-cols-2">
          {info.agents.map((a: any) => (
            <Card key={a.name} title={a.title} actions={<button className={agent === a.name ? "btn" : "btn-secondary"} onClick={() => setAgent(a.name)}>Chat</button>}>
              <p className="text-sm">{a.role}</p>
              <div className="mt-2 flex flex-wrap gap-1">{a.tools.map((t: any) => <span key={t.name} className={`badge ${t.requires_approval ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"}`}>{t.name}{t.requires_approval ? " (approval)" : ""}</span>)}</div>
              {a.can_delegate.length > 0 && <p className="mt-2 text-xs text-slate-500">Can delegate to: {a.can_delegate.join(", ")}</p>}
            </Card>))}
        </div>
        <Field label="Selected agent"><div className="font-mono text-sm">{agent}</div></Field>
        <AgentChat key={agent} agent={agent} title={info.agents.find((a: any) => a.name === agent)?.title ?? agent} placeholder="Give the agent a task…" />
      </>}
      {jobs && <Card title="Recent agent runs"><table className="table"><tbody>{jobs.map((j: any) => <tr key={j.id}><td>#{j.id}</td><td>{j.solver}</td><td><StatusBadge status={j.status} /></td><td>{fmt(j.runtime_s, 1)} s</td><td className="text-xs">{new Date(j.created_at).toLocaleString()}</td></tr>)}</tbody></table></Card>}
    </Page>
  );
}
