# Deployment

## Single container + PostgreSQL (recommended)

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, QOPT_JWT_SECRET, optionally ANTHROPIC_API_KEY / provider creds
docker compose up -d --build
open http://localhost:8000  # first visit creates the administrator
```

The image builds the SPA, installs the backend, runs Alembic migrations at startup and serves API + UI
on port 8000 as a non-root user. Provider SDKs are opt-in: build with `--build-arg EXTRAS="[ibm,braket,dwave]"`.

> Not verified in this environment: Docker is not installed on the development machine used to build this
> release, so the image and compose file have not been built or run here. CI (`.github/workflows/ci.yml`)
> builds the image.

## Configuration (environment variables)

| variable | default | notes |
|---|---|---|
| `QOPT_ENVIRONMENT` | development | `production` refuses to start without `QOPT_JWT_SECRET` |
| `QOPT_DATABASE_URL` | `sqlite:///./data/qopt.db` | `postgresql+psycopg://user:pw@host/db` in production |
| `QOPT_JWT_SECRET` | ephemeral (dev) | ≥ 32 random bytes |
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
