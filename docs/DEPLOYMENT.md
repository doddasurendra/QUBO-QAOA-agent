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
- **Verified:** the `Dockerfile` builds and runs. It is the image deployed on Fly.io (built by Fly's remote builder,
  149 MB), healthy, serving HTTPS, migrations applied to the volume, app process non-root.
- **Verified in CI:** the backend suite on **PostgreSQL 16** (job `backend-postgres`: every API test gets its own
  freshly created and migrated database; `tests/test_database_backend.py` asserts the dialect really is PostgreSQL).
  Run it locally against any server with `QOPT_TEST_POSTGRES_URL=postgresql+psycopg://user:pw@host:5432/postgres`
  (the user needs `CREATE DATABASE`) after `pip install -e ".[dev,postgres]"`.
- **Not verified:** `docker compose up` (with PostgreSQL) on a local Docker host. Docker is not installed on the
  development machine. On a Docker host, run the commands above; then check `docker compose ps` shows `healthy`.

### Fly.io (live deployment)

The app runs at **https://qopt-quantum-c4da.fly.dev** (region `sin`, Singapore: Fly offers no Indian region).
`fly.toml` builds the repository `Dockerfile` on Fly's remote builders, so no local Docker is needed:

```powershell
flyctl auth login                                   # once, in the browser
flyctl secrets import --stage -a qopt-quantum-c4da < secrets.env   # QOPT_JWT_SECRET, QOPT_BOOTSTRAP_TOKEN
flyctl deploy --remote-only                         # rebuild + roll out after code changes
flyctl logs -a qopt-quantum-c4da                    # live logs
```

- One always-on `shared-cpu-1x` machine with 2 GB RAM; SQLite on a 1 GB volume `qopt_data` mounted at `/app/data`
  (survives restarts and redeploys). Jobs run in-process, so keep a single machine.
- `docker-entrypoint.sh` starts as root only to make the root-owned volume writable, then drops to the `qopt` user.
- `FORWARDED_ALLOW_IPS="*"` lets per-IP rate limits see real client addresses behind Fly's proxy.
- **First admin:** open the URL and enter the setup token (`QOPT_BOOTSTRAP_TOKEN`). The generated values for this
  deployment are in the git-ignored `.run/fly-secrets.env` on the machine that deployed it.
- Use `flyctl` from a Windows PowerShell pipe with care: it prepends a UTF-8 BOM to piped input; use `cmd /c "... < file"`.

> **Fly trial accounts stop machines after 5 minutes** ("Trial machine stopping. To run for longer than 5m0s, add a
> credit card"). The proxy restarts the machine on the next request (cold start of several seconds), but scheduled
> in-app backups and long jobs cannot run until a card is added at https://fly.io/trial.

### Monitoring and alerting

- **Health endpoints:** `/api/health` is a cheap liveness probe (Fly's routing check). `/api/health/deep` checks the
  database round-trip, that the schema is at the newest migration, backup freshness (newest backup ≤ 1.5 × the
  interval; "pending" during the first interval after startup) and free disk space. Overall status is the worst
  component: `ok` / `degraded` (HTTP 200) / `fail` (HTTP 503). It returns statuses, ages and percentages only.
- **GitHub Actions monitor** (`.github/workflows/uptime.yml`): runs `scripts/uptime_check.py` about every 10
  minutes (GitHub schedules are best-effort and pause in public repos after 60 days without commits). Three attempts
  20 s apart before declaring "down". It opens **one** issue labelled `uptime-alert` per outage (GitHub emails the
  repository's watchers, i.e. you), comments when the state changes, and comments + closes it on recovery. Test it with
  *Actions → uptime → Run workflow* and a URL override such as `https://<app>.fly.dev/api/alert-test` (should open
  an issue), then run it without an override (should close it). Override the URL with the repository variable
  `QOPT_HEALTH_URL`.
- **External monitor (second, independent channel):** create a free account at e.g. UptimeRobot or Better Stack and
  add a monitor:

  | setting | value |
  |---|---|
  | type | HTTP(s) **keyword** monitor |
  | URL | `https://qopt-quantum-c4da.fly.dev/api/health/deep` |
  | keyword | `"status":"ok"` (alert when the keyword is **missing**) |
  | interval | 5 minutes |
  | timeout | 30 seconds (allows for a cold start) |
  | alert contacts | your email and/or phone |

  A keyword check also alerts on `degraded` (e.g. backups not running). Use a plain HTTP-status check instead if
  you only want alerts for full outages.

### Custom domain (when you have one)

```powershell
flyctl certs add qopt.example.com -a qopt-quantum-c4da       # prints the DNS records to create
flyctl ips list -a qopt-quantum-c4da                         # shared IPv4 + IPv6 of the app
```

At your DNS provider create either a **CNAME** `qopt.example.com → qopt-quantum-c4da.fly.dev` (subdomains), or for
an apex/root domain an **A** record to the app's IPv4 and an **AAAA** record to its IPv6. Fly issues a free Let's
Encrypt certificate automatically; `flyctl certs check qopt.example.com -a qopt-quantum-c4da` shows progress. Then:
`flyctl secrets set QOPT_CORS_ORIGINS='["https://qopt.example.com"]'` (or edit `[env]` in `fly.toml` and deploy), and
point the monitors at the new hostname.

### Backups and restore (SQLite on Fly)

Three layers, no extra Fly product needed:

| layer | what | where | retention |
|---|---|---|---|
| Volume snapshots | Fly's daily snapshot of the whole volume | Fly | 30 days (`snapshot_retention = 30`; first 10 GB free) |
| In-app backups | consistent SQLite copy (online backup API), `PRAGMA integrity_check` before it is kept | `/app/data/backups` on the volume | daily, newest 14 (`QOPT_BACKUP_INTERVAL_HOURS`, `QOPT_BACKUP_KEEP`) |
| Off-site copy | `scripts\download-backup.ps1` creates a fresh backup and downloads it, then re-checks integrity | `backups-offsite\` on your PC (git-ignored) | your choice; weekly via the scheduled task below |

**Weekly off-site copy, automatically:** `powershell -ExecutionPolicy Bypass -File scripts\register-backup-task.ps1`
registers a Windows scheduled task (Sundays 10:00 by default; `-Day`, `-At` to change; `-RunNow` for an immediate
test run; `-Unregister` to remove it). It runs as you, only while you are logged on (flyctl uses your login), catches
up if the PC was off, and appends to `backups-offsite\backup-task.log` (a failure is logged as `FAILED: <reason>`
and the task's last result is non-zero; check with `Get-ScheduledTaskInfo -TaskName 'qopt off-site backup'`).

Administrators see the backups and a **Back up now** button under *Administration → Database backups*. There is
deliberately no web download (backups contain password hashes); off-site copies go through your `flyctl` login.

**Restore an in-app backup** (the current database is copied to a `pre-restore` backup first):

```powershell
flyctl ssh console -a qopt-quantum-c4da -u qopt -C "python -m qopt.services.backup list"
flyctl ssh console -a qopt-quantum-c4da -u qopt -C "python -m qopt.services.backup restore /app/data/backups/<file>"
flyctl machine restart -a qopt-quantum-c4da          # start clean on the restored data
```

Run it while nobody is working in the app: writes made during the restore are overwritten.

**Restore an off-site copy:** upload it, then restore as above:
`flyctl ssh sftp shell -a qopt-quantum-c4da` → `put backups-offsite\<file> /app/data/backups/<file>`.

**Restore a volume snapshot** (whole-disk rollback): `flyctl volumes snapshots list <volume id>`, then
`flyctl volumes create qopt_data --snapshot-id <id> -r sin -a qopt-quantum-c4da`, and move the machine to the new
volume (`flyctl machine update <machine id> --mount ...`, or destroy the old machine/volume and `flyctl deploy`).

PostgreSQL (`docker-compose.yml`, or Fly Managed Postgres if chosen later) uses the database provider's backups; the
in-app backup service reports itself as not applicable there.

### Without Docker on Windows (one command)

`powershell -ExecutionPolicy Bypass -File scripts\run-production.ps1` serves the app at http://localhost:8080 in
production mode: it creates `.env` with random secrets if missing, installs the backend package into `.run/site`,
uses `.run/qopt.db` (SQLite) and the built SPA. Binds to 127.0.0.1 only; put a reverse proxy with TLS in front
before exposing it to a network.

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
