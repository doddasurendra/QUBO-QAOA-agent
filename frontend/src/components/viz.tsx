import { useMemo, useState } from "react";
import { FOCUS } from "./ui";

/** Diverging heatmap for a QUBO matrix (blue negative, red positive). */
export function MatrixHeatmap({ matrix, labels }: { matrix: number[][]; labels: string[] }) {
  const n = matrix.length;
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  const max = useMemo(() => Math.max(1e-12, ...matrix.flat().map(Math.abs)), [matrix]);
  const cell = Math.max(6, Math.min(28, Math.floor(560 / Math.max(n, 1))));
  const color = (v: number) => {
    if (v === 0) return "var(--zero, #f1f5f9)";
    const t = Math.min(1, Math.abs(v) / max);
    const a = 0.15 + 0.85 * t;
    return v < 0 ? `rgba(37, 99, 235, ${a})` : `rgba(220, 38, 38, ${a})`;
  };
  const showLabels = n <= 24;
  const pad = showLabels ? 70 : 4;
  return (
    <div role="region" aria-label="QUBO matrix (scrollable)" tabIndex={0} className={`overflow-auto ${FOCUS}`}>
      <svg width={pad + n * cell + 4} height={pad + n * cell + 4} role="img" aria-label="QUBO matrix heatmap">
        {showLabels && labels.map((l, k) => (
          <g key={k}>
            <text x={pad - 4} y={pad + k * cell + cell / 2 + 3} textAnchor="end" fontSize={9} className="fill-slate-500">{l.slice(0, 12)}</text>
            <text transform={`translate(${pad + k * cell + cell / 2 + 3}, ${pad - 4}) rotate(-60)`} fontSize={9} className="fill-slate-500">{l.slice(0, 12)}</text>
          </g>
        ))}
        {matrix.map((row, i) => row.map((v, j) => (
          <rect key={`${i}-${j}`} x={pad + j * cell} y={pad + i * cell} width={cell - 1} height={cell - 1} fill={color(v)}
            stroke={hover && hover.i === i && hover.j === j ? "#111" : "none"}
            onMouseEnter={() => setHover({ i, j })} onMouseLeave={() => setHover(null)} />
        )))}
      </svg>
      <div className="mt-2 h-5 text-xs text-slate-600 dark:text-slate-400">
        {hover ? <>Q[{labels[hover.i]}, {labels[hover.j]}] = <b className="tabular-nums">{matrix[hover.i][hover.j]}</b></> : <>Hover a cell. Blue = negative, red = positive, scale ±{max.toPrecision(3)}.</>}
      </div>
    </div>
  );
}

type Gate = { gate: string; qubits: number[]; params: (number | string)[] };

/** Render a gate list as a circuit diagram (columns are packed greedily, barriers start a new column). */
export function CircuitView({ gates, numQubits, labels }: { gates: Gate[]; numQubits: number; labels?: string[] }) {
  const cols: { g: Gate; col: number }[] = [];
  const level = new Array(numQubits).fill(0);
  for (const g of gates) {
    if (g.gate === "barrier") { const m = Math.max(...level); level.fill(m); continue; }
    const qs = g.qubits;
    const lo = Math.min(...qs), hi = Math.max(...qs);
    let c = 0;
    for (let q = lo; q <= hi; q++) c = Math.max(c, level[q]);
    for (let q = lo; q <= hi; q++) level[q] = c + 1;
    cols.push({ g, col: c });
  }
  const ncol = Math.max(1, ...level);
  if (ncol > 400) return <p className="text-sm text-slate-600 dark:text-slate-400">Circuit has {ncol} layers — too deep to draw; see gate counts and QASM.</p>;
  const W = 46, H = 34, L = 64;
  const color: Record<string, string> = { h: "#6366f1", rz: "#0ea5e9", rx: "#f59e0b", rzz: "#10b981", xx_plus_yy: "#ec4899", state_preparation: "#8b5cf6" };
  const fmtp = (p: number | string) => (typeof p === "number" ? p.toFixed(2) : p.replace(/\*\*/g, "^").slice(0, 14));
  return (
    <div role="region" aria-label="QAOA circuit (scrollable)" tabIndex={0} className={`overflow-auto ${FOCUS}`}>
      <svg width={L + ncol * W + 20} height={numQubits * H + 20} role="img" aria-label="QAOA circuit">
        {Array.from({ length: numQubits }, (_, q) => (
          <g key={q}>
            <text x={4} y={q * H + H / 2 + 14} fontSize={10} className="fill-slate-500">q{q}{labels?.[q] ? ` ${labels[q].slice(0, 7)}` : ""}</text>
            <line x1={L} x2={L + ncol * W} y1={q * H + H / 2 + 10} y2={q * H + H / 2 + 10} stroke="#94a3b8" />
          </g>
        ))}
        {cols.map(({ g, col }, k) => {
          const x = L + col * W + 4;
          const ys = g.qubits.map((q) => q * H + H / 2 + 10);
          const c = color[g.gate] ?? "#64748b";
          const title = `${g.gate}(${g.params.map(fmtp).join(", ")}) on q${g.qubits.join(",q")}`;
          if (g.qubits.length === 2) {
            return (
              <g key={k}><title>{title}</title>
                <line x1={x + 19} x2={x + 19} y1={Math.min(...ys)} y2={Math.max(...ys)} stroke={c} strokeWidth={2} />
                {ys.map((y, i) => <circle key={i} cx={x + 19} cy={y} r={6} fill={c} />)}
                <text x={x + 26} y={(ys[0] + ys[1]) / 2 + 3} fontSize={8} fill={c}>{g.gate === "rzz" ? "ZZ" : "XY"}</text>
              </g>
            );
          }
          return (
            <g key={k}><title>{title}</title>
              {ys.map((y, i) => <g key={i}><rect x={x} y={y - 11} width={38} height={22} rx={4} fill={c} />
                <text x={x + 19} y={y + 4} fontSize={10} textAnchor="middle" fill="white">{g.gate === "state_preparation" ? "W" : g.gate.toUpperCase()}</text></g>)}
            </g>
          );
        })}
      </svg>
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">Hover a gate for its parameters. Qubit i encodes variable i.</p>
    </div>
  );
}

/** Small SVG heatmap for the p=1 energy landscape. */
export function Landscape({ gammas, betas, energies }: { gammas: number[]; betas: number[]; energies: number[][] }) {
  const flat = energies.flat();
  const lo = Math.min(...flat), hi = Math.max(...flat);
  const cw = 14, ch = 14;
  const col = (v: number) => { const t = hi > lo ? (v - lo) / (hi - lo) : 0; return `hsl(${240 - 240 * t}, 70%, ${40 + 20 * t}%)`; };
  let best = { i: 0, j: 0 };
  energies.forEach((r, i) => r.forEach((v, j) => { if (v < energies[best.i][best.j]) best = { i, j }; }));
  return (
    <div role="region" aria-label="Energy landscape (scrollable)" tabIndex={0} className={`overflow-auto ${FOCUS}`}>
      <svg width={gammas.length * cw + 60} role="img" aria-label="p = 1 energy landscape heatmap" height={betas.length * ch + 40}>
        {energies.map((r, i) => r.map((v, j) => <rect key={`${i}${j}`} x={50 + j * cw} y={i * ch} width={cw} height={ch} fill={col(v)}><title>γ={gammas[j].toFixed(3)} β={betas[i].toFixed(3)} ⟨H⟩={v.toFixed(4)}</title></rect>))}
        <rect x={50 + best.j * cw} y={best.i * ch} width={cw} height={ch} fill="none" stroke="white" strokeWidth={2} />
        <text x={50} y={betas.length * ch + 14} fontSize={10} className="fill-slate-500">γ: 0 → π</text>
        <text x={0} y={10} fontSize={10} className="fill-slate-500">β ↓</text>
      </svg>
      <p className="text-xs text-slate-600 dark:text-slate-400">Blue = lower energy. Minimum on the grid: ⟨H⟩ = {energies[best.i][best.j].toFixed(4)} at γ = {gammas[best.j].toFixed(3)}, β = {betas[best.i].toFixed(3)}.</p>
    </div>
  );
}
