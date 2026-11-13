# Deployment

## Single container + PostgreSQL (recommended)

```bash
cp .env.example .env        # REQUIRED: POSTGRES_PASSWORD and QOPT_JWT_SECRET (≥ 32 random chars)
                            # optional: ANTHROPIC_API_KEY, provider credentials
docker compose up -d --build
curl http://localhost:8000/api/health      # → {"status":"ok",...}
open http://localhost:8000                 # first visit creates the administrator
```

The image builds the SPA, installs the backend **as a regular package**, runs Alembic migrations at startup
(they ship inside the package, `qopt/migrations`) and serves API + UI on port 8000 as a non-root user, from
`/app` (outside any source tree). Provider SDKs are opt-in: build with `--build-arg EXTRAS="[ibm,braket,dwave]"`.
Production mode refuses to start without a strong `QOPT_JWT_SECRET`.

### What has and has not been verified

- **Verified:** the exact runtime the image uses. A non-editable install of the package, started with
  uvicorn from outside the source tree in production mode, with `QOPT_FRONTEND_DIST` / `QOPT_DOCS_DIR` set as in the
  Dockerfile, passed 12/12 live HTTP checks (health, OpenAPI, SPA + assets, migrations, login, docs, all
  industry modules, a background job, secret not leaked). `tests/test_deployment.py` guards the packaging,
  migration, path and `.env.example` requirements in CI.
- **Not verified here:** `docker build` / `docker compose up` themselves, and PostgreSQL. Docker, WSL2 and
  PostgreSQL are not installed on the development machine (installing Docker Desktop requires enabling
  WSL2/Hyper-V with admin rights and a reboot). CI (`.github/workflows/ci.yml`) builds the image. On a Docker
  host, run the commands above; then check `docker compose ps` shows the app as `healthy`.

### Without Docker (single host)

```bash
python -m venv .venv && .venv/bin/pip install ./backend "psycopg[binary]" pypdf
(cd frontend && npm ci && npm run build)
export QOPT_ENVIRONMENT=production QOPT_JWT_SECRET=... QOPT_DATABASE_URL=postgresql+psycopg://...
export QOPT_FRONTEND_DIST=$PWD/frontend/dist QOPT_DOCS_DIR=$PWD/docs
.venv/bin/uvicorn qopt.api.app:app --host 0.0.0.0 --port 8000
```

## Configuration (environment variables)

| variable | default | notes |
|---|---|---|
| `QOPT_ENVIRONMENT` | development | `production` refuses to start without a strong `QOPT_JWT_SECRET` |
| `QOPT_DATABASE_URL` | `sqlite:///./data/qopt.db` | `postgresql+psycopg://user:pw@host/db` in production |
| `QOPT_JWT_SECRET` | ephemeral (dev) | ≥ 32 random characters, no spaces (enforced in production) |
| `QOPT_FRONTEND_DIST` | `<repo>/frontend/dist` | built SPA; the image sets `/app/frontend/dist`. API-only if missing (logged) |
| `QOPT_DOCS_DIR` | `<repo>/docs` | markdown docs served in the UI; the image sets `/app/docs` |
| `QOPT_AGENT_RATE_LIMIT_PER_MINUTE` | 10 | agent runs per user |
| `QOPT_MAX_UPLOAD_BYTES` | 5242880 | dataset / research uploads |
| `QOPT_JWT_EXPIRY_MINUTES` | 120 | |
| `QOPT_ALLOW_REGISTRATION` | false | self-service researcher accounts |
| `QOPT_CORS_ORIGINS` | localhost:5173 | JSON list |
| `QOPT_RATE_LIMIT_PER_MINUTE` | 240 | per user (2× per IP) |
| `QOPT_WORKER_THREADS` | 4 | background job threads (0 = inline) |
| `QOPT_JOB_TIMEOUT_S` | 900 | |
| `QOPT_MAX_CONCURRENT_JOBS_PER_USER` | 4 | quota |
| `QOPT_MAX_STATEVECTOR_QUBITS` | 22 | memory = 16·2ⁿ bytes |
| `QOPT_AGENT_RUN_BUDGET_USD` / `QOPT_AGENT_DAILY_BUDGET_USD` | 2 / 10 | estimated from token usage |
| `ANTHROPIC_API_KEY` | — | enables agents (server-side only) |
| `QOPT_CLAUDE_MODEL` | claude-opus-5-5 | |
| `QISKIT_IBM_TOKEN` (+`QISKIT_IBM_INSTANCE`) | — | IBM Quantum, needs `[ibm]` extra |
| `AWS_*`, `QOPT_BRAKET_S3_BUCKET` | — | Amazon Braket, needs `[braket]` extra |
| `DWAVE_API_TOKEN` | — | D-Wave Leap, needs `[dwave]` extra |

Secrets are read only from the environment; they are never stored in the database, returned by the API
(`/api/admin/config` reports only *whether* something is configured) or sent to the browser. The audit
logger redacts credential-like strings.

## Scaling notes / known limits

- Jobs run on an in-process thread pool; run **one** API process per database, or move jobs to a
  dedicated worker. Rate limiting is in-process too. For multiple replicas, put both behind Redis
  (`QOPT_REDIS_URL` is reserved; not implemented in this release).
- Python threads cannot be killed: a job over `QOPT_JOB_TIMEOUT_S` is marked `timeout`, its late result
  is stored as `late=true`.
- Monitoring: structured JSON logs on stdout (request id, user, latency), `/api/health` for liveness.
  Ship stdout to your log stack; no metrics exporter is bundled.
