import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, auth } from "./api";

export type User = { id: number; email: string; name: string; role: "admin" | "researcher" | "viewer" };
type Ctx = { user: User | null; loading: boolean; login: (token: string, u: User) => void; logout: () => void };

const AuthCtx = createContext<Ctx>({ user: null, loading: true, login: () => {}, logout: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const logout = useCallback(() => { auth.set(null); setUser(null); }, []);
  useEffect(() => {
    const onLogout = () => setUser(null);
    window.addEventListener("qopt-logout", onLogout);
    if (auth.token) api.get<User>("/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
    else setLoading(false);
    return () => window.removeEventListener("qopt-logout", onLogout);
  }, []);
  const login = (token: string, u: User) => { auth.set(token); setUser(u); };
  return <AuthCtx.Provider value={{ user, loading, login, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);
export const can = (u: User | null, role: "viewer" | "researcher" | "admin") =>
  !!u && { viewer: 0, researcher: 1, admin: 2 }[u.role] >= { viewer: 0, researcher: 1, admin: 2 }[role];
