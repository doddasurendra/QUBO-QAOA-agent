// Thin typed client for the qopt backend. The JWT lives in sessionStorage (cleared when the tab closes).
// No secrets other than the user's own session token are ever handled in the browser.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const TOKEN_KEY = "qopt.token";

export const auth = {
  get token(): string | null {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set(token: string | null) {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch { /* storage unavailable */ }
  },
};

async function request<T = any>(method: string, path: string, body?: unknown, form?: FormData,
                                extra: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { ...extra };
  if (auth.token) headers["Authorization"] = `Bearer ${auth.token}`;
  if (body !== undefined && !form) headers["Content-Type"] = "application/json";
  const res = await fetch(`/api${path}`, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    if (res.status === 401 && path !== "/auth/login") { auth.set(null); window.dispatchEvent(new Event("qopt-logout")); }
    let msg: string;
    if (typeof data === "string") msg = data;
    else if (Array.isArray(data?.detail)) msg = data.detail.map((d: any) => `${(d.loc || []).join(".")}: ${d.msg}`).join("; ");
    else msg = data?.detail ?? res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  get: <T = any>(p: string) => request<T>("GET", p),
  post: <T = any>(p: string, b?: unknown, headers?: Record<string, string>) => request<T>("POST", p, b ?? {}, undefined, headers),
  patch: <T = any>(p: string, b?: unknown) => request<T>("PATCH", p, b ?? {}),
  del: <T = any>(p: string) => request<T>("DELETE", p),
  upload: <T = any>(p: string, form: FormData) => request<T>("POST", p, undefined, form),
  async download(p: string, filename: string) {
    const res = await fetch(`/api${p}`, { headers: auth.token ? { Authorization: `Bearer ${auth.token}` } : {} });
    if (!res.ok) throw new ApiError(res.status, await res.text());
    const blob = await res.blob();
    saveBlob(blob, filename);
  },
};

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function saveJson(obj: unknown, filename: string) {
  saveBlob(new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" }), filename);
}

/** Poll a job until it reaches a terminal state. */
export async function waitForJob(id: number, onUpdate?: (j: any) => void, intervalMs = 1000): Promise<any> {
  for (;;) {
    const j = await api.get(`/jobs/${id}`);
    onUpdate?.(j);
    if (!["queued", "running"].includes(j.status)) return j;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/** Model reference accepted by every optimisation endpoint. */
export type ModelRef =
  | { spec: any } | { qubo: any } | { industry: { key: string; data: any } } | { experiment_id: number };
