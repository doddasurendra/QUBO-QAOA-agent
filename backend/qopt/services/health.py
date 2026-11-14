"""Deep health check for uptime monitors.

``/api/health`` stays a cheap liveness probe (used by Fly's routing checks). ``/api/health/deep`` runs real checks
and is what external monitors should poll:

* database   — a query round-trip (fail if it errors)
* migrations — the schema revision equals the newest packaged migration (fail otherwise)
* backups    — SQLite only: newest backup younger than 1.5 × the interval (degraded if older; "pending" during
               the first interval after startup; n/a for PostgreSQL or when disabled)
* disk       — free space on the database volume (degraded below 15 % or 100 MB, fail below 2 % or 10 MB)

Overall status = worst component: ok < degraded < fail. HTTP 503 only for "fail". Only statuses, ages and
percentages are returned — no paths, hostnames or data.
"""
from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

from sqlalchemy import text

from .. import __version__
from ..config import get_settings
from ..db import engine

RANK = {"ok": 0, "pending": 0, "n/a": 0, "degraded": 1, "fail": 2}
STARTED = time.monotonic()


def _db() -> Tuple[str, dict]:
    t0 = time.perf_counter()
    try:
        with engine().connect() as c:
            c.execute(text("SELECT 1")).scalar_one()
        return "ok", {"latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        return "fail", {"error": type(exc).__name__}


def _migrations() -> Tuple[str, dict]:
    try:
        from alembic.script import ScriptDirectory
        from alembic.config import Config
        from ..db.session import MIGRATIONS_DIR
        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        with engine().connect() as c:
            current = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return ("ok" if current == head else "fail"), {"current": current, "head": head}
    except Exception as exc:  # noqa: BLE001
        return "fail", {"error": type(exc).__name__}


def _backups() -> Tuple[str, dict]:
    from . import backup
    s = get_settings()
    if s.backup_interval_hours <= 0:
        return "n/a", {"reason": "disabled"}
    try:
        items = backup.list_backups()
    except backup.BackupUnavailable:
        return "n/a", {"reason": "not SQLite"}
    limit_h = 1.5 * s.backup_interval_hours
    if not items:
        uptime_h = (time.monotonic() - STARTED) / 3600
        grace_h = s.backup_first_delay_s / 3600 + 0.25
        return ("pending" if uptime_h < grace_h else "degraded"), {"count": 0}
    newest = datetime.fromisoformat(items[0]["created_at"])
    age_h = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
    return ("ok" if age_h <= limit_h else "degraded"), {"count": len(items), "newest_age_h": round(age_h, 2),
                                                         "max_age_h": limit_h}


def _disk() -> Tuple[str, dict]:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        return "n/a", {"reason": "not SQLite"}
    path = Path(url[len("sqlite:///"):]).resolve().parent
    try:
        u = shutil.disk_usage(path)
    except OSError as exc:
        return "fail", {"error": type(exc).__name__}
    free_pct = 100 * u.free / u.total if u.total else 0.0
    free_mb = u.free / 2**20
    status = "fail" if (free_pct < 2 or free_mb < 10) else "degraded" if (free_pct < 15 or free_mb < 100) else "ok"
    return status, {"free_pct": round(free_pct, 1), "free_mb": round(free_mb)}


def deep_health() -> Tuple[dict, int]:
    checks: Dict[str, dict] = {}
    for name, fn in (("database", _db), ("migrations", _migrations), ("backups", _backups), ("disk", _disk)):
        status, detail = fn()
        checks[name] = {"status": status, **detail}
    worst = max((c["status"] for c in checks.values()), key=lambda s: RANK[s])
    overall = {"pending": "ok", "n/a": "ok"}.get(worst, worst)
    body = {"status": overall, "version": __version__, "checked_at": datetime.now(timezone.utc).isoformat(),
            "uptime_s": round(time.monotonic() - STARTED), "checks": checks}
    return body, (503 if overall == "fail" else 200)
