"""Consistent SQLite backups: scheduled, integrity-checked, pruned, restorable.

Uses SQLite's online backup API (``sqlite3.Connection.backup``), which produces a consistent copy while the
application keeps running. Each backup is verified with ``PRAGMA integrity_check`` before it is kept.

CLI (e.g. on the server via ``flyctl ssh console``)::

    python -m qopt.services.backup create
    python -m qopt.services.backup list
    python -m qopt.services.backup verify <file>
    python -m qopt.services.backup restore <file>      # stop traffic first; see docs/DEPLOYMENT.md
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..config import get_settings

log = logging.getLogger("qopt.backup")
PREFIX = "qopt-"
_lock = threading.Lock()


class BackupUnavailable(RuntimeError):
    pass


def sqlite_path(url: Optional[str] = None) -> Path:
    url = url or get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise BackupUnavailable("built-in backups apply to SQLite only; PostgreSQL deployments use the "
                                "database provider's backups")
    p = url[len("sqlite:///"):]
    if not p or p == ":memory:":
        raise BackupUnavailable("in-memory databases cannot be backed up")
    return Path(p)


def backup_dir() -> Path:
    s = get_settings()
    return Path(s.backup_dir) if s.backup_dir else sqlite_path().parent / "backups"


def _integrity(path: Path) -> str:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def _info(p: Path) -> dict:
    st = p.stat()
    return {"name": p.name, "size_bytes": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()}


def list_backups() -> List[dict]:
    d = backup_dir()
    if not d.is_dir():
        return []
    return [_info(p) for p in sorted(d.glob(f"{PREFIX}*.db"), reverse=True)]


def prune(keep: Optional[int] = None) -> List[str]:
    keep = get_settings().backup_keep if keep is None else keep
    files = sorted(backup_dir().glob(f"{PREFIX}*.db"), reverse=True)    # names sort by timestamp
    removed = []
    for p in files[max(keep, 1):]:
        p.unlink(missing_ok=True)
        removed.append(p.name)
    return removed


def create_backup(reason: str = "manual") -> dict:
    """Write a consistent, integrity-checked copy of the live database; prune old copies."""
    src_path = sqlite_path()
    if not src_path.is_file():
        raise BackupUnavailable(f"database file not found: {src_path}")
    d = backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    with _lock:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        final = d / f"{PREFIX}{stamp}.db"
        tmp = final.with_suffix(".db.partial")
        src = sqlite3.connect(src_path.as_posix())
        dst = sqlite3.connect(tmp.as_posix())
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        result = _integrity(tmp)
        if result != "ok":
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"backup failed integrity check: {result}")
        tmp.replace(final)
        removed = prune()
    info = {**_info(final), "integrity": result, "reason": reason, "pruned": removed}
    log.info("backup created %s (%d bytes, reason=%s, pruned=%d)", final.name, info["size_bytes"], reason, len(removed))
    return info


def verify(path: Path) -> str:
    return _integrity(Path(path))


def restore(path: Path) -> dict:
    """Overwrite the live database with a verified backup (page-by-page, via the backup API)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    result = _integrity(path)
    if result != "ok":
        raise RuntimeError(f"refusing to restore: backup failed integrity check: {result}")
    target = sqlite_path()
    safety = create_backup(reason="pre-restore") if target.is_file() else None
    with _lock:
        src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(target.as_posix())
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    log.warning("database restored from %s (pre-restore copy: %s)", path.name, safety and safety["name"])
    return {"restored_from": path.name, "pre_restore_backup": safety and safety["name"],
            "integrity": _integrity(target)}


class BackupScheduler:
    """Daemon thread: first backup after ``first_delay_s``, then every ``interval_h`` hours."""

    def __init__(self, interval_h: float, first_delay_s: float = 600.0):
        self.interval_s = interval_h * 3600.0
        self.first_delay_s = first_delay_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.runs = 0
        self.last: Optional[dict] = None
        self.last_error: Optional[str] = None

    def start(self) -> "BackupScheduler":
        self._thread = threading.Thread(target=self._loop, name="qopt-backup", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        wait = self.first_delay_s
        while not self._stop.wait(wait):
            try:
                self.last = create_backup(reason="scheduled")
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - logged and surfaced in the admin API, never silent
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.error("scheduled backup failed: %s", self.last_error)
            self.runs += 1
            wait = self.interval_s


scheduler: Optional[BackupScheduler] = None


def start_scheduler() -> Optional[BackupScheduler]:
    """Start scheduled backups when the database is SQLite and an interval is configured."""
    global scheduler
    s = get_settings()
    if s.backup_interval_hours <= 0:
        return None
    try:
        sqlite_path()
    except BackupUnavailable:
        return None
    scheduler = BackupScheduler(s.backup_interval_hours, s.backup_first_delay_s).start()
    log.info("scheduled backups every %.1f h, keeping %d, in %s", s.backup_interval_hours, s.backup_keep, backup_dir())
    return scheduler


def stop_scheduler():
    global scheduler
    if scheduler:
        scheduler.stop()
        scheduler = None


def _main(argv: List[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cmd = argv[0] if argv else "list"
    if cmd == "create":
        print(create_backup(reason="cli"))
    elif cmd == "list":
        for b in list_backups():
            print(f"{b['name']}  {b['size_bytes']:>10} bytes  {b['created_at']}")
    elif cmd == "verify" and len(argv) == 2:
        print(verify(Path(argv[1])))
    elif cmd == "restore" and len(argv) == 2:
        print(restore(Path(argv[1])))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
