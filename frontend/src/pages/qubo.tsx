import { useState } from "react";
import { api, saveBlob, saveJson, type ModelRef } from "../api";
import { useActiveModel, RequireModel } from "../components/model";
import { MatrixHeatmap } from "../components/viz";
import { Card, ErrorBox, Field, fmt, Json, Note, Page, useAction } from "../components/ui";

type Cons = { label: string; coefs: Record<string, string>; sense: "==" | "<=" | ">="; rhs: string; one_hot: boolean };

export function BuilderPage() {
  const { setActive } = useActiveModel();
  const [name, setName] = useState("my-model");
  const [vars, setVars] = useState<string[]>(["x0", "x1", "x2"]);
  const [sense, setSense] = useState<"min" | "max">("min");
  const [lin, setLin] = useState<Record<string, string>>({ x0: "1", x1: "-2", x2: "3" });
  const [quad, setQuad] = useState<{ u: string; v: string; c: string }[]>([{ u: "x0", v: "x1", c: "2" }]);
  const [cons, setCons] = useState<Cons[]>([{ label: "pick_two", coefs: { x0: "1", x1: "1", x2: "1" }, sense: "==", rhs: "2", one_hot: false }]);
  const [newVar, setNewVar] = useState("");
  const [result, setResult] = useState<any>();
  const [saved, setSaved] = useState<any>();
  const { busy, error, run, setError } = useAction();

  const num = (s: string, where: string) => {
    if (s.trim() === "") return 0;
    const v = Number(s);
    if (!Number.isFinite(v)) throw new Error(`"${s}" in ${where} is not a number`);
    return v;
  };
  const buildSpec = () => {
    if (!vars.length) throw new Error("add at least one variable");
    const linear: Record<string, number> = {};
    vars.forEach((v) => { const c = num(lin[v] ?? "", `objective coefficient of ${v}`); if (c) linear[v] = c; });
    return {
      name, variables: vars, sense,
      objective: { linear, quadratic: quad.filter((q) => q.u && q.v && q.c).map((q) => {
        if (q.u === q.v) throw new Error(`quadratic term ${q.u}·${q.v}: use the linear coefficient for x·x (binary)`);
        return [q.u, q.v, num(q.c, "quadratic term")]; }) },
      constraints: cons.map((c, i) => {
        const l: Record<string, number> = {};
        vars.forEach((v) => { const k = num(c.coefs[v] ?? "", `constraint ${c.label || i}`); if (k) l[v] = k; });
        if (!Object.keys(l).length) throw new Error(`constraint ${c.label || i} has no non-zero coefficients`);
        return { label: c.label || `c${i}`, lhs: { linear: l }, sense: c.sense, rhs: num(c.rhs, `rhs of ${c.label}`), ...(c.one_hot ? { kind: "one_hot" } : {}) };
      }),
    };
  };
  const compile = () => run(async () => { setSaved(undefined); setResult(await api.post("/qubo/compile", { spec: buildSpec(), include_matrix: true })); });
  const save = () => run(async () => {
    const e = await api.post("/experiments", { name, spec: buildSpec(), description: "Built in the QUBO Model Builder" });
    setSaved(e); setActive({ ref: { experiment_id: e.id }, label: `Experiment #${e.id} ${e.name}` });
  });
  const addVar = () => {
    const v = newVar.trim();
    if (!/^[A-Za-z_][\w]*$/.test(v)) return setError(new Error("variable names: letters, digits, underscore; must not start with a digit"));
    if (vars.includes(v)) return setError(new Error(`${v} already exists`));
    setVars([...vars, v]); setNewVar(""); setError(undefined);
  };

  return (
    <Page title="QUBO Model Builder" subtitle="Define binary variables, an objective and constraints. Constraints are converted to exact penalty terms (inequalities get bounded slack variables).">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="1 · Variables & objective">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Model name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Sense"><select className="input" value={sense} onChange={(e) => setSense(e.target.value as any)}><option value="min">minimise</option><option value="max">maximise</option></select></Field>
          </div>
          <table className="table mt-3"><thead><tr><th>variable (binary)</th><th>linear coefficient</th><th /></tr></thead>
            <tbody>{vars.map((v) => (
              <tr key={v}><td className="font-mono">{v}</td><td><input className="input" value={lin[v] ?? ""} onChange={(e) => setLin({ ...lin, [v]: e.target.value })} /></td>
                <td><button className="btn-secondary" onClick={() => { setVars(vars.filter((x) => x !== v)); setQuad(quad.filter((q) => q.u !== v && q.v !== v)); }}>✕</button></td></tr>))}</tbody></table>
          <div className="mt-2 flex gap-2"><input className="input" placeholder="new variable name" value={newVar} onChange={(e) => setNewVar(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addVar()} /><button className="btn-secondary" onClick={addVar}>Add</button></div>
          <div className="label mt-4">Quadratic terms c · u · v</div>
          {quad.map((q, i) => (
            <div key={i} className="mb-1 flex gap-1">
              {(["u", "v"] as const).map((k) => <select key={k} className="input" value={q[k]} onChange={(e) => setQuad(quad.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))}><option value="">—</option>{vars.map((v) => <option key={v}>{v}</option>)}</select>)}
              <input className="input w-24" value={q.c} onChange={(e) => setQuad(quad.map((x, j) => (j === i ? { ...x, c: e.target.value } : x)))} />
              <button className="btn-secondary" onClick={() => setQuad(quad.filter((_, j) => j !== i))}>✕</button>
            </div>))}
          <button className="btn-secondary" onClick={() => setQuad([...quad, { u: "", v: "", c: "1" }])}>+ quadratic term</button>
        </Card>
        <Card title="2 · Constraints">
          {cons.map((c, i) => (
            <div key={i} className="mb-3 rounded-lg border border-slate-200 p-2 dark:border-slate-800">
              <div className="mb-2 flex gap-2">
                <input className="input" value={c.label} onChange={(e) => setCons(cons.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} placeholder="label" />
                <label className="flex items-center gap-1 whitespace-nowrap text-xs"><input type="checkbox" checked={c.one_hot} onChange={(e) => setCons(cons.map((x, j) => (j === i ? { ...x, one_hot: e.target.checked } : x)))} />one-hot (XY mixer)</label>
                <button className="btn-secondary" onClick={() => setCons(cons.filter((_, j) => j !== i))}>✕</button>
              </div>
              <div className="flex flex-wrap items-center gap-1 text-sm">
                {vars.map((v, k) => <span key={v} className="flex items-center gap-1">{k > 0 && "+"}<input className="input w-14" value={c.coefs[v] ?? ""} onChange={(e) => setCons(cons.map((x, j) => (j === i ? { ...x, coefs: { ...x.coefs, [v]: e.target.value } } : x)))} /><span className="font-mono">{v}</span></span>)}
                <select className="input w-16" value={c.sense} onChange={(e) => setCons(cons.map((x, j) => (j === i ? { ...x, sense: e.target.value as any } : x)))}><option>==</option><option>{"<="}</option><option>{">="}</option></select>
                <input className="input w-16" value={c.rhs} onChange={(e) => setCons(cons.map((x, j) => (j === i ? { ...x, rhs: e.target.value } : x)))} />
              </div>
            </div>))}
          <button className="btn-secondary" onClick={() => setCons([...cons, { label: `c${cons.length}`, coefs: {}, sense: "<=", rhs: "1", one_hot: false }])}>+ constraint</button>
          <Note>Inequalities need integer coefficients (slack is binary-encoded exactly). Penalty weight defaults to Σ|objective coefficients| + 1, which provably makes every infeasible assignment worse than every feasible one.</Note>
        </Card>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn" disabled={busy} onClick={compile}>Compile to QUBO</button>
        <button className="btn-secondary" disabled={busy} onClick={save}>Save as experiment & make active</button>
        <button className="btn-secondary" onClick={() => { try { saveJson(buildSpec(), `${name}.spec.json`); } catch (e) { setError(e); } }}>Export spec JSON</button>
      </div>
      <ErrorBox error={error} />
      {saved && <Note tone="ok">Saved as experiment #{saved.id} and set as the active model for the analysis pages.</Note>}
      {result && <CompileResult r={result} />}
    </Page>
  );
}

function CompileResult({ r }: { r: any }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Compiled QUBO">
        <ul className="text-sm">
          <li>Decision variables: {r.summary?.num_decision_variables ?? r.stats.num_variables}; slack variables: {r.summary?.num_slack_variables ?? 0}</li>
          <li>Quadratic terms: {r.stats.num_quadratic_terms}; density {fmt(r.stats.density, 3)}</li>
          {r.summary && <li>Penalties: {Object.entries(r.summary.penalties).map(([k, v]) => `${k}=${fmt(v)}`).join(", ") || "none"}</li>}
        </ul>
        {r.summary?.warnings?.map((w: string) => <Note key={w} tone="warn">{w}</Note>)}
        {r.formulation && <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-100 p-2 font-mono text-xs dark:bg-slate-800">{r.formulation}</pre>}
        {r.matrix_upper && <div className="mt-3"><MatrixHeatmap matrix={r.matrix_upper} labels={r.qubo.variables} /></div>}
      </Card>
      <Card title="Ising form & checks">
        <p className="mb-2 text-sm">QUBO ↔ Ising equivalence: {r.structural_validation.ising_equivalence ? (r.structural_validation.ising_equivalence.passed ? <b className="text-emerald-600">verified on all {r.structural_validation.ising_equivalence.checked} assignments</b> : <b className="text-rose-600">FAILED</b>) : "not checked (> 16 variables)"}</p>
        <Json value={r.ising} max={120} />
      </Card>
    </div>
  );
}

export function MatrixPage() {
  const [r, setR] = useState<any>();
  const [red, setRed] = useState<any>();
  const [conv, setConv] = useState<"upper" | "symmetric">("upper");
  const [paste, setPaste] = useState("[[1, -2], [0, 3]]");
  const { busy, error, run } = useAction();
  const load = (ref: ModelRef) => run(async () => { setRed(undefined); setR(await api.post("/qubo/compile", { ...ref, include_matrix: true })); });
  const toCsv = (m: number[][], labels: string[]) => [["", ...labels].join(","), ...m.map((row, i) => [labels[i], ...row].join(","))].join("\n");
  return (
    <Page title="QUBO Matrix Explorer" subtitle="Inspect, reduce and export QUBO matrices.">
      <RequireModel>{(ref) => (
        <div className="flex flex-wrap gap-2">
          <button className="btn" disabled={busy} onClick={() => load(ref)}>Load matrix of active model</button>
          <button className="btn-secondary" disabled={busy} onClick={() => run(async () => setRed(await api.post("/qubo/reduce", ref)))}>Run safe variable reduction</button>
        </div>)}</RequireModel>
      <Card title="…or paste a matrix (E = xᵀQx)">
        <textarea className="input h-24 font-mono text-xs" value={paste} onChange={(e) => setPaste(e.target.value)} />
        <button className="btn-secondary mt-2" disabled={busy} onClick={() => run(async () => setR(await api.post("/qubo/from-matrix", { matrix: JSON.parse(paste) })))}>Import matrix</button>
      </Card>
      <ErrorBox error={error} />
      {red && <Card title="Variable reduction"><p className="text-sm">{red.rule}</p><p className="mt-1 text-sm">{Object.keys(red.fixed_variables).length} of {red.original_variables} variables fixed; {red.remaining_variables} remain.</p><Json value={red.fixed_variables} /></Card>}
      {r && (
        <Card title={`Q (${r.qubo.variables.length}×${r.qubo.variables.length}), offset ${fmt(r.qubo.offset)}`} actions={
          <div className="flex gap-2">
            <select className="input" value={conv} onChange={(e) => setConv(e.target.value as any)}><option value="upper">upper-triangular</option><option value="symmetric">symmetric</option></select>
            <button className="btn-secondary" onClick={() => saveJson(r.qubo, "qubo.json")}>JSON</button>
            {r.matrix_upper && <button className="btn-secondary" onClick={() => saveBlob(new Blob([toCsv(conv === "upper" ? r.matrix_upper : r.matrix_symmetric, r.qubo.variables)], { type: "text/csv" }), `qubo-${conv}.csv`)}>CSV</button>}
          </div>}>
          {r.matrix_upper ? <MatrixHeatmap matrix={conv === "upper" ? r.matrix_upper : r.matrix_symmetric} labels={r.qubo.variables} /> : <Note>Matrix too large to render (&gt;120 variables); export JSON instead.</Note>}
          <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
            <div>Linear terms: {r.stats.num_linear_terms}</div><div>Quadratic terms: {r.stats.num_quadratic_terms}</div><div>Max |coef|: {fmt(r.stats.max_abs_coefficient)}</div>
            <div>Dynamic range: {fmt(r.structural_validation.dynamic_range, 1)}</div><div>Unused variables: {r.structural_validation.unused_variables.join(", ") || "none"}</div>
          </div>
          {r.structural_validation.issues.map((i: string) => <Note key={i} tone="warn">{i}</Note>)}
        </Card>)}
    </Page>
  );
}

export function ValidationPage() {
  const [r, setR] = useState<any>();
  const { busy, error, run } = useAction();
  return (
    <Page title="QUBO Validation" subtitle="Independent checks: QUBO ↔ Ising equivalence, penalty dominance, and that the QUBO optimum is the true constrained optimum (exhaustive for ≤ 20 decision variables).">
      <RequireModel>{(ref) => <button className="btn" disabled={busy} onClick={() => run(async () => setR(await api.post("/qubo/validate", ref)))}>Run validation</button>}</RequireModel>
      <ErrorBox error={error} />
      {r && <>
        {r.exhaustive?.passed !== undefined && <Note tone={r.exhaustive.passed ? "ok" : "warn"}>{r.exhaustive.passed ? "All exhaustive checks passed." : `Validation found issues: ${r.exhaustive.issues.join("; ")}`}</Note>}
        {r.exhaustive?.skipped && <Note tone="warn">{r.exhaustive.skipped}</Note>}
        {r.exhaustive?.checks && (
          <Card title={`Exhaustive checks over ${r.exhaustive.num_states} decision assignments`}>
            <table className="table"><thead><tr><th>check</th><th>result</th><th>details</th></tr></thead>
              <tbody>{Object.entries(r.exhaustive.checks).map(([k, v]: [string, any]) => (
                <tr key={k}><td>{k.replace(/_/g, " ")}</td><td>{v.passed ? <span className="text-emerald-600">pass</span> : <span className="text-rose-600">FAIL</span>}</td>
                  <td className="font-mono text-xs">{JSON.stringify(Object.fromEntries(Object.entries(v).filter(([kk]) => kk !== "passed")))}</td></tr>))}</tbody></table>
            <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
              <div>Feasible assignments: <b>{r.exhaustive.num_feasible}</b></div>
              <div>Best feasible objective: <b>{fmt(r.exhaustive.best_feasible_objective)}</b></div>
              <div>Optimal assignment(s): <span className="font-mono">{r.exhaustive.best_feasible.slice(0, 4).join(", ")}</span></div>
            </div>
          </Card>)}
        <Card title="Structural checks"><Json value={r.structural} /></Card>
      </>}
    </Page>
  );
}

export function IsingPage() {
  const [r, setR] = useState<any>();
  const [bits, setBits] = useState("");
  const [ev, setEv] = useState<any>();
  const { busy, error, run } = useAction();
  const [ref, setRef] = useState<ModelRef>();
  return (
    <Page title="Ising Model Explorer" subtitle="H(z) = c + Σ hᵢ zᵢ + Σ Jᵢⱼ zᵢ zⱼ with xᵢ = (1 − zᵢ)/2 (bit 0 ↔ spin +1 ↔ |0⟩).">
      <RequireModel>{(m) => <button className="btn" disabled={busy} onClick={() => run(async () => { setRef(m); setR(await api.post("/qubo/compile", { ...m, include_matrix: false })); })}>Load Ising form</button>}</RequireModel>
      <ErrorBox error={error} />
      {r && <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Fields h (offset c = ${fmt(r.ising.offset)})`}>
          <table className="table"><thead><tr><th>spin</th><th>variable</th><th>h</th></tr></thead>
            <tbody>{Object.entries(r.ising.h).map(([i, h]: [string, any]) => <tr key={i}><td>z{i}</td><td className="font-mono">{r.ising.variables[Number(i)]}</td><td className="tabular-nums">{fmt(h)}</td></tr>)}</tbody></table>
        </Card>
        <Card title={`Couplings J (${r.ising.J.length})`}>
          <div className="max-h-80 overflow-auto"><table className="table"><thead><tr><th>i</th><th>j</th><th>J</th></tr></thead>
            <tbody>{r.ising.J.slice(0, 300).map(([i, j, c]: number[]) => <tr key={`${i}-${j}`}><td>{r.ising.variables[i]}</td><td>{r.ising.variables[j]}</td><td className="tabular-nums">{fmt(c)}</td></tr>)}</tbody></table></div>
        </Card>
        <Card title="Evaluate an assignment in both forms">
          <Field label={`Bitstring (x0 first, ${r.qubo.variables.length} QUBO bits or decision bits only)`}><input className="input font-mono" value={bits} onChange={(e) => setBits(e.target.value.replace(/[^01]/g, ""))} /></Field>
          <button className="btn mt-2" disabled={!bits || busy} onClick={() => run(async () => setEv(await api.post("/qubo/evaluate", { ...ref, bitstring: bits })))}>Evaluate</button>
          {ev && <Json value={ev} />}
        </Card>
      </div>}
    </Page>
  );
}
