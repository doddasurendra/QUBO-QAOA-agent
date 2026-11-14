import { useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { can, useAuth } from "./auth";
import { ModelProvider } from "./components/model";
import { Spinner } from "./components/ui";
import { AgentsPage, AssistantPage } from "./pages/ai";
import { AdminPage, ApiPage, DocsPage, UsagePage, UsersPage } from "./pages/admin";
import { DatasetsPage, ExperimentsPage, ResearchPage, ResultsPage } from "./pages/data";
import { LoginPage, OverviewPage } from "./pages/core";
import { CircuitPage, ProvidersPage, QaoaPage, SimulatorPage } from "./pages/quantum";
import { BuilderPage, IsingPage, MatrixPage, ValidationPage } from "./pages/qubo";
import { BenchmarkPage, ClassicalPage, HybridPage, IndustryPage } from "./pages/solve";

const NAV: { group: string; items: { to: string; label: string; role?: "admin" }[] }[] = [
  { group: "Workspace", items: [{ to: "/", label: "Overview" }, { to: "/assistant", label: "AI Quantum Assistant" }, { to: "/agents", label: "AI Agents" }] },
  { group: "QUBO", items: [{ to: "/builder", label: "Model Builder" }, { to: "/matrix", label: "Matrix Explorer" }, { to: "/validation", label: "Validation" }, { to: "/ising", label: "Ising Explorer" }] },
  { group: "Quantum", items: [{ to: "/circuit", label: "QAOA Circuit Designer" }, { to: "/qaoa", label: "QAOA Execution" }, { to: "/simulator", label: "Quantum Simulator" }, { to: "/providers", label: "Hardware Providers" }] },
  { group: "Optimise", items: [{ to: "/classical", label: "Classical Solvers" }, { to: "/hybrid", label: "Hybrid Optimization" }, { to: "/industry", label: "Industry Solutions" }, { to: "/benchmarks", label: "Benchmarking" }] },
  { group: "Data", items: [{ to: "/experiments", label: "Experiments" }, { to: "/datasets", label: "Datasets" }, { to: "/research", label: "Research Library" }, { to: "/results", label: "Results & Reports" }] },
  { group: "Platform", items: [{ to: "/api-keys", label: "API Management" }, { to: "/users", label: "Users & Roles", role: "admin" }, { to: "/admin", label: "Administration", role: "admin" }, { to: "/usage", label: "Usage & Cost" }, { to: "/docs", label: "Docs & Tutorials" }] },
];

export default function App() {
  const { user, loading, logout } = useAuth();
  const [menu, setMenu] = useState(false);
  if (loading) return <div className="p-8"><Spinner label="Loading…" /></div>;
  if (!user) return <LoginPage />;
  return (
    <ModelProvider>
      <div className="flex min-h-screen">
        <aside className={`${menu ? "block" : "hidden"} fixed inset-y-0 z-20 w-64 overflow-y-auto border-r border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900 md:static md:block`}>
          <div className="mb-4 px-2">
            <div className="text-lg font-bold">qopt</div>
            <div className="text-xs text-slate-600 dark:text-slate-400">QUBO · QAOA · Hybrid optimisation</div>
          </div>
          <nav className="space-y-4" onClick={() => setMenu(false)}>
            {NAV.map((g) => (
              <div key={g.group}>
                <div className="px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-600 dark:text-slate-400">{g.group}</div>
                {g.items.filter((i) => !i.role || can(user, i.role)).map((i) => (
                  <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) =>
                    `block rounded-md px-2 py-1 text-sm ${isActive ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300" : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"}`}>{i.label}</NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="mt-6 border-t border-slate-200 px-2 pt-3 text-xs dark:border-slate-800">
            <div className="truncate font-medium">{user.email}</div>
            <div className="text-slate-600 dark:text-slate-400">role: {user.role}</div>
            <button className="btn-secondary mt-2" onClick={logout}>Sign out</button>
          </div>
        </aside>
        <main className="min-w-0 flex-1">
          <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-slate-200 bg-white/80 px-4 py-2 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80 md:hidden">
            <button className="btn-secondary" onClick={() => setMenu(!menu)} aria-label="menu">☰</button><span className="font-semibold">qopt</span>
          </div>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/assistant" element={<AssistantPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/builder" element={<BuilderPage />} />
            <Route path="/matrix" element={<MatrixPage />} />
            <Route path="/validation" element={<ValidationPage />} />
            <Route path="/ising" element={<IsingPage />} />
            <Route path="/circuit" element={<CircuitPage />} />
            <Route path="/qaoa" element={<QaoaPage />} />
            <Route path="/simulator" element={<SimulatorPage />} />
            <Route path="/providers" element={<ProvidersPage />} />
            <Route path="/classical" element={<ClassicalPage />} />
            <Route path="/hybrid" element={<HybridPage />} />
            <Route path="/industry" element={<IndustryPage />} />
            <Route path="/benchmarks" element={<BenchmarkPage />} />
            <Route path="/experiments" element={<ExperimentsPage />} />
            <Route path="/datasets" element={<DatasetsPage />} />
            <Route path="/research" element={<ResearchPage />} />
            <Route path="/results" element={<ResultsPage />} />
            <Route path="/api-keys" element={<ApiPage />} />
            <Route path="/users" element={can(user, "admin") ? <UsersPage /> : <Navigate to="/" />} />
            <Route path="/admin" element={can(user, "admin") ? <AdminPage /> : <Navigate to="/" />} />
            <Route path="/usage" element={<UsagePage />} />
            <Route path="/docs" element={<DocsPage />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </ModelProvider>
  );
}
