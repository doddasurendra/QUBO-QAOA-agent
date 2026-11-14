import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type ModelRef } from "../api";
import { Card, ErrorBox, Field } from "./ui";

export const EXAMPLE_SPEC = {
  name: "knapsack-demo",
  variables: ["item_a", "item_b", "item_c", "item_d"],
  sense: "max",
  objective: { linear: { item_a: 6, item_b: 5, item_c: 4, item_d: 3 }, quadratic: [["item_a", "item_b", -2]] },
  constraints: [
    { label: "capacity", lhs: { linear: { item_a: 4, item_b: 3, item_c: 2, item_d: 1 } }, sense: "<=", rhs: 6 },
  ],
};

type Active = { ref: ModelRef; label: string } | null;
const Ctx = createContext<{ active: Active; setActive: (a: Active) => void }>({ active: null, setActive: () => {} });
const KEY = "qopt.activeModel";

export function ModelProvider({ children }: { children: ReactNode }) {
  const [active, setA] = useState<Active>(() => {
    try { const s = sessionStorage.getItem(KEY); return s ? JSON.parse(s) : null; } catch { return null; }
  });
  const setActive = (a: Active) => {
    setA(a);
    try { a ? sessionStorage.setItem(KEY, JSON.stringify(a)) : sessionStorage.removeItem(KEY); } catch { /* ignore */ }
  };
  return <Ctx.Provider value={{ active, setActive }}>{children}</Ctx.Provider>;
}
export const useActiveModel = () => useContext(Ctx);

/** Select the model used by analysis pages: saved experiment, industry template + dataset, custom spec, or raw QUBO. */
export function ModelPicker({ compact = false }: { compact?: boolean }) {
  const { active, setActive } = useActiveModel();
  const [mode, setMode] = useState<"experiment" | "industry" | "spec" | "qubo">("experiment");
  const [exps, setExps] = useState<any[]>([]);
  const [probs, setProbs] = useState<any[]>([]);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [text, setText] = useState(JSON.stringify(EXAMPLE_SPEC, null, 2));
  const [ikey, setIkey] = useState("");
  const [err, setErr] = useState<unknown>();
  const [open, setOpen] = useState(!active || !compact);

  useEffect(() => {
    api.get("/experiments").then(setExps).catch(setErr);
    api.get("/industries").then((p) => { setProbs(p); setIkey(p[0]?.key ?? ""); }).catch(setErr);
    api.get("/datasets").then(setDatasets).catch(() => {});
  }, []);

  const useJson = (kind: "spec" | "qubo") => {
    setErr(undefined);
    try {
      const v = JSON.parse(text);
      setActive({ ref: kind === "spec" ? { spec: v } : { qubo: v }, label: `${kind === "spec" ? "Custom model" : "QUBO"}: ${v.name ?? `${(v.variables || []).length} variables`}` });
      setOpen(false);
    } catch (e) { setErr(new Error(`Invalid JSON: ${(e as Error).message}`)); }
  };

  const loadDataset = async (id: number) => {
    const d = await api.get(`/datasets/${id}`);
    setText(JSON.stringify(d.content, null, 2));
  };

  return (
    <Card title="Active model" actions={compact && <button className="btn-secondary" onClick={() => setOpen(!open)}>{open ? "Hide" : "Change"}</button>}>
      <div className="mb-2 text-sm">{active ? <span>Using <b>{active.label}</b></span> : <span className="text-warn">No model selected — choose one below.</span>}</div>
      {open && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1">
            {(["experiment", "industry", "spec", "qubo"] as const).map((m) => (
              <button key={m} className={mode === m ? "btn" : "btn-secondary"} onClick={() => {
                setMode(m);
                if (m === "spec") setText(JSON.stringify(EXAMPLE_SPEC, null, 2));
                if (m === "industry") { const p = probs.find((x) => x.key === ikey); if (p) api.get(`/industries/${p.key}`).then((d) => setText(JSON.stringify(d.example, null, 2))); }
              }}>{{ experiment: "Saved experiment", industry: "Industry template", spec: "Custom spec (JSON)", qubo: "Raw QUBO (JSON)" }[m]}</button>
            ))}
          </div>
          {mode === "experiment" && (
            <Field label="Experiment">
              <select className="input" defaultValue="" onChange={(e) => {
                const ex = exps.find((x) => String(x.id) === e.target.value);
                if (ex) { setActive({ ref: { experiment_id: ex.id }, label: `Experiment #${ex.id} ${ex.name}` }); setOpen(false); }
              }}>
                <option value="" disabled>{exps.length ? "Select…" : "No experiments yet — create one in Experiments / Model Builder"}</option>
                {exps.map((x) => <option key={x.id} value={x.id}>#{x.id} {x.name} ({x.source})</option>)}
              </select>
            </Field>
          )}
          {mode === "industry" && (
            <>
              <div className="grid gap-2 md:grid-cols-2">
                <Field label="Template">
                  <select className="input" value={ikey} onChange={async (e) => {
                    setIkey(e.target.value);
                    const d = await api.get(`/industries/${e.target.value}`);
                    setText(JSON.stringify(d.example, null, 2));
                  }}>{probs.map((p) => <option key={p.key} value={p.key}>{p.title}</option>)}</select>
                </Field>
                <Field label="Load dataset">
                  <select className="input" defaultValue="" onChange={(e) => e.target.value && loadDataset(Number(e.target.value))}>
                    <option value="">—</option>
                    {datasets.filter((d) => d.problem_key === ikey).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </Field>
              </div>
              <textarea className="input h-56 font-mono text-xs" aria-label="Template input data (JSON)" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
              <button className="btn" onClick={() => {
                try { const data = JSON.parse(text); setActive({ ref: { industry: { key: ikey, data } }, label: `${probs.find((p) => p.key === ikey)?.title}` }); setOpen(false); }
                catch (e) { setErr(new Error(`Invalid JSON: ${(e as Error).message}`)); }
              }}>Use this data</button>
            </>
          )}
          {(mode === "spec" || mode === "qubo") && (
            <>
              <textarea className="input h-56 font-mono text-xs" aria-label={mode === "spec" ? "Model specification (JSON)" : "QUBO (JSON)"} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
              <button className="btn" onClick={() => useJson(mode)}>Use this {mode === "spec" ? "model" : "QUBO"}</button>
            </>
          )}
          <ErrorBox error={err} />
        </div>
      )}
    </Card>
  );
}

export function RequireModel({ children }: { children: (ref: ModelRef) => ReactNode }) {
  const { active } = useActiveModel();
  return <>{<ModelPicker compact />}{active ? children(active.ref) : null}</>;
}
