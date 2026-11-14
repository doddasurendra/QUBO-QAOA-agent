"""SQLite backup service: consistency, integrity, pruning, restore round-trip, scheduler, admin API."""
import sqlite3
import time

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("QOPT_DATABASE_URL", f"sqlite:///{(tmp_path / 'live.db').as_posix()}")
    monkeypatch.setenv("QOPT_BACKUP_KEEP", "3")
    monkeypatch.delenv("QOPT_BACKUP_DIR", raising=False)
    from qopt.config import get_settings
    from qopt.db import migrate, reset_engine
    get_settings.cache_clear(); reset_engine()
    migrate()
    yield tmp_path / "live.db"
    from qopt.services import backup
    backup.stop_scheduler()
    reset_engine(); get_settings.cache_clear()


def users(path):
    con = sqlite3.connect(path)
    try:
        return sorted(r[0] for r in con.execute("select email from users"))
    finally:
        con.close()


def add_user(path, email):
    con = sqlite3.connect(path)
    con.execute("insert into users (email, name, password_hash, role, is_active, created_at) "
                "values (?, '', 'x', 'researcher', 1, '2026-01-01')", (email,))
    con.commit(); con.close()


def test_backup_is_consistent_and_integrity_checked(db):
    from qopt.services import backup
    add_user(db, "a@x.co")
    info = backup.create_backup()
    assert info["integrity"] == "ok" and info["size_bytes"] > 0
    copy = db.parent / "backups" / info["name"]
    assert copy.is_file() and users(copy) == ["a@x.co"]
    assert not list((db.parent / "backups").glob("*.partial"))       # no half-written files left


def test_prune_keeps_newest(db):
    from qopt.services import backup
    names = [backup.create_backup()["name"] for _ in range(5)]
    kept = [b["name"] for b in backup.list_backups()]
    assert kept == sorted(names, reverse=True)[:3]                   # QOPT_BACKUP_KEEP=3, newest first


def test_restore_round_trip_brings_data_back(db):
    from qopt.services import backup
    add_user(db, "keep@x.co")
    snap = backup.create_backup()
    con = sqlite3.connect(db); con.execute("delete from users"); con.commit(); con.close()
    add_user(db, "intruder@x.co")
    assert users(db) == ["intruder@x.co"]
    out = backup.restore(db.parent / "backups" / snap["name"])
    assert users(db) == ["keep@x.co"] and out["integrity"] == "ok"
    pre = db.parent / "backups" / out["pre_restore_backup"]           # state before restore is kept too
    assert users(pre) == ["intruder@x.co"]


def test_restore_refuses_corrupt_backup(db):
    from qopt.services import backup
    bad = db.parent / "corrupt.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    with pytest.raises(Exception):
        backup.restore(bad)
    assert "users" in {r[0] for r in sqlite3.connect(db).execute("select name from sqlite_master")}


def test_postgres_url_is_reported_not_applicable(monkeypatch):
    from qopt.config import get_settings
    from qopt.services import backup
    monkeypatch.setenv("QOPT_DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    get_settings.cache_clear()
    try:
        with pytest.raises(backup.BackupUnavailable, match="SQLite only"):
            backup.create_backup()
        assert backup.start_scheduler() is None
    finally:
        get_settings.cache_clear()


def test_scheduler_runs_backups(db):
    from qopt.services import backup
    sch = backup.BackupScheduler(interval_h=0.2 / 3600, first_delay_s=0.05).start()
    try:
        for _ in range(100):
            if sch.runs >= 2:
                break
            time.sleep(0.05)
    finally:
        sch.stop()
    assert sch.runs >= 2 and sch.last_error is None and sch.last["integrity"] == "ok"


def test_admin_backup_api_and_rbac(admin_client):
    api = admin_client
    r = api.post("/api/admin/backups")
    assert r.status_code == 200 and r.json()["integrity"] == "ok"
    listing = api.get("/api/admin/backups").json()
    assert listing["enabled"] and listing["backups"][0]["name"] == r.json()["name"]
    assert any(e["action"] == "backup_create" for e in api.get("/api/admin/audit").json())
    api.post("/api/users", json={"email": "r@x.co", "password": "password123", "role": "researcher"})
    tok = api.post("/api/auth/login", json={"email": "r@x.co", "password": "password123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert api.post("/api/admin/backups", headers=h).status_code == 403
    assert api.get("/api/admin/backups", headers=h).status_code == 403
