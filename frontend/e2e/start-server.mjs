// Starts the real backend for E2E tests: fresh SQLite DB, real job threads, serving the built SPA.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "..");
const repo = resolve(frontend, "..");
const backend = join(repo, "backend");
const work = join(here, ".work");
const port = process.env.E2E_PORT ?? "8790";

if (!existsSync(join(frontend, "dist", "index.html"))) {
  console.error("frontend/dist is missing: run `npm run build` first (npm run e2e does this)");
  process.exit(1);
}
rmSync(work, { recursive: true, force: true });
mkdirSync(work, { recursive: true });

const python = process.env.QOPT_PYTHON ??
  (process.platform === "win32" ? join(repo, ".venv", "Scripts", "python.exe") : join(repo, ".venv", "bin", "python"));

const env = {
  ...process.env,
  QOPT_ENVIRONMENT: "development",
  QOPT_DATABASE_URL: `sqlite:///${join(work, "e2e.db").replace(/\\/g, "/")}`,
  QOPT_JWT_SECRET: "e2e-only-secret-not-for-production-0123456789",
  QOPT_FRONTEND_DIST: join(frontend, "dist"),
  QOPT_DOCS_DIR: join(repo, "docs"),
  QOPT_RATE_LIMIT_PER_MINUTE: "5000",
  QOPT_WORKER_THREADS: "2",
  // agents must report "unavailable" deterministically in E2E
  ANTHROPIC_API_KEY: "", ANTHROPIC_AUTH_TOKEN: "",
};
const child = spawn(python, ["-m", "uvicorn", "qopt.api.app:app", "--host", "127.0.0.1", "--port", port],
  { cwd: backend, env, stdio: "inherit" });
const stop = () => child.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
child.on("exit", (code) => process.exit(code ?? 0));
