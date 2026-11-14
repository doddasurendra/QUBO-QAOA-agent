import { cloneElement, isValidElement, useEffect, useId, useState, type ReactNode } from "react";
import { ApiError } from "../api";

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Card({ title, children, actions, className = "" }: { title?: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="font-semibold">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof ApiError ? `${error.status}: ${error.message}` : String((error as any)?.message ?? error);
  return <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-800 dark:bg-rose-950 dark:text-rose-200">{msg}</div>;
}

export function Note({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "ok" }) {
  const c = { info: "border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-800 dark:bg-sky-950 dark:text-sky-200",
    warn: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200",
    ok: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" }[tone];
  return <div className={`rounded-lg border p-3 text-sm ${c}`}>{children}</div>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-600 dark:text-slate-400">{hint}</div>}
    </div>
  );
}

export function KindBadge({ kind, real }: { kind?: string | null; real?: boolean }) {
  if (real) return <span className="badge bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-900 dark:text-fuchsia-200">REAL QPU · {kind}</span>;
  if (!kind) return <span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800">—</span>;
  const sim = kind.includes("simulator");
  return <span className={`badge ${sim ? "bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200" : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"}`}>{sim ? "SIMULATOR · " : ""}{kind}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const c: Record<string, string> = { done: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
    running: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200", queued: "bg-slate-100 text-slate-700 dark:bg-slate-800",
    error: "bg-rose-100 text-rose-800 dark:bg-rose-900 dark:text-rose-200", timeout: "bg-amber-100 text-amber-800",
    cancelled: "bg-slate-200 text-slate-700", pending: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
    approved: "bg-emerald-100 text-emerald-800", rejected: "bg-rose-100 text-rose-800" };
  return <span className={`badge ${c[status] ?? "bg-slate-100"}`}>{status}</span>;
}

export function Json({ value, max = 400 }: { value: unknown; max?: number }) {
  const s = JSON.stringify(value, null, 2) ?? "";
  const lines = s.split("\n");
  return <pre tabIndex={0} role="region" aria-label="JSON output" className={`max-h-[28rem] overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-xs text-slate-100 ${FOCUS}`}>{lines.slice(0, max).join("\n")}{lines.length > max ? `\n… ${lines.length - max} more lines` : ""}</pre>;
}

/** Visible keyboard focus ring for focusable non-control elements (WCAG 2.4.7). */
export const FOCUS = "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500";

/** A scrollable box that keyboard users can reach and scroll (WCAG 2.1.1; axe scrollable-region-focusable). */
export function ScrollRegion({ label, className = "", children }: { label: string; className?: string; children: ReactNode }) {
  return <div role="region" aria-label={label} tabIndex={0} className={`overflow-auto ${FOCUS} ${className}`}>{children}</div>;
}

/** Label + control. The label is linked with htmlFor/id rather than wrapping the control, so a control's
 *  accessible name is exactly its label (wrapping a <select> would append every option's text to it). */
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  const autoId = useId();
  let id = autoId;
  let control = children;
  if (isValidElement<{ id?: string }>(children)) {
    id = children.props.id ?? autoId;
    control = cloneElement(children, { id });
  }
  return (
    <div className="block">
      <label className="label" htmlFor={id}>{label}</label>
      {control}
      {hint && <span className="mt-1 block text-xs text-slate-600 dark:text-slate-400">{hint}</span>}
    </div>
  );
}

export function Spinner({ label = "Working…" }: { label?: string }) {
  return <span className="inline-flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400"><span className="h-3 w-3 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />{label}</span>;
}

/** Load data on mount / when deps change; returns [data, error, reload]. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []): [T | undefined, unknown, () => void, boolean] {
  const [data, setData] = useState<T>();
  const [err, setErr] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then((d) => { if (live) { setData(d); setErr(undefined); } }).catch((e) => live && setErr(e)).finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return [data, err, () => setTick((t) => t + 1), loading];
}

/** Wrap an async action with busy + error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const run = async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true); setError(undefined);
    try { return await fn(); } catch (e) { setError(e); return undefined; } finally { setBusy(false); }
  };
  return { busy, error, run, setError };
}

export const fmt = (v: unknown, d = 4) => (typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(d)) : v === null || v === undefined ? "—" : String(v));
