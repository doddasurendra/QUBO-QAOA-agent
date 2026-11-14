"""Deep health endpoint and the uptime probe used by the GitHub Actions monitor."""
import importlib.util
import os
import shutil
import sqlite3
import time
from collections import namedtuple
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load_probe():
    spec = importlib.util.spec_from_file_location("uptime_check", REPO / "scripts" / "uptime_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ /api/health/deep
def test_deep_health_ok_and_reveals_no_paths(api):
    r = api.get("/api/health/deep")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["migrations"]["status"] == "ok"
    assert body["checks"]["backups"]["status"] == "n/a"          # disabled in tests (interval 0)
    assert body["checks"]["disk"]["status"] in ("ok", "degraded")
    assert r.headers["cache-control"] == "no-store"
    from qopt.services import health
    assert health.STARTED < time.monotonic()      # clock started at import (app startup), not on first request
    text = r.text
    assert "test.db" not in text and ":\\" not in text and "/tmp" not in text   # no filesystem paths leak


def test_deep_health_fails_with_503_on_schema_mismatch(api, tmp_path):
    db = tmp_path / "test.db"
    con = sqlite3.connect(db); con.execute("update alembic_version set version_num='bogus'"); con.commit(); con.close()
    r = api.get("/api/health/deep")
    assert r.status_code == 503 and r.json()["status"] == "fail"
    assert r.json()["checks"]["migrations"]["status"] == "fail"


def test_deep_health_disk_thresholds(api, monkeypatch):
    U = namedtuple("U", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(1000 * 2**20, 900 * 2**20, 100 * 2**20 - 1))
    assert api.get("/api/health/deep").json()["checks"]["disk"]["status"] == "degraded"
    monkeypatch.setattr(shutil, "disk_usage", lambda p: U(1000 * 2**20, 995 * 2**20, 5 * 2**20))
    r = api.get("/api/health/deep")
    assert r.status_code == 503 and r.json()["checks"]["disk"]["status"] == "fail"


def test_deep_health_backup_freshness(tmp_path, monkeypatch):
    monkeypatch.setenv("QOPT_DATABASE_URL", f"sqlite:///{(tmp_path / 'h.db').as_posix()}")
    monkeypatch.setenv("QOPT_BACKUP_INTERVAL_HOURS", "24")
    from qopt.config import get_settings
    from qopt.db import migrate, reset_engine
    from qopt.services import backup, health
    get_settings.cache_clear(); reset_engine(); migrate()
    try:
        assert health._backups()[0] == "pending"                  # just started, no backup yet
        info = backup.create_backup()
        assert health._backups()[0] == "ok"
        old = time.time() - 40 * 3600                             # older than 1.5 × 24 h
        os.utime(tmp_path / "backups" / info["name"], (old, old))
        status, detail = health._backups()
        assert status == "degraded" and detail["newest_age_h"] > 36
        body, code = health.deep_health()
        assert body["status"] == "degraded" and code == 200       # degraded is not an outage
    finally:
        reset_engine(); get_settings.cache_clear()


# ------------------------------------------------------------------ scripts/uptime_check.py
def test_probe_classification():
    p = load_probe()
    assert p.classify(200, {"status": "ok", "checks": {}}, None)[0] == p.UP
    v, why = p.classify(200, {"status": "degraded", "checks": {"backups": {"status": "degraded"}, "db": {"status": "ok"}}}, None)
    assert v == p.DEGRADED and "backups=degraded" in why and "db" not in why
    assert p.classify(503, {"status": "fail"}, None) == (p.DOWN, "HTTP 503, status=fail")
    assert p.classify(None, None, "URLError: timed out")[0] == p.DOWN
    assert p.classify(200, None, "response is not JSON")[0] == p.DOWN


def test_probe_retries_before_declaring_down_and_recovers():
    p = load_probe()
    sleeps = []
    seq = iter([(None, None, "timeout"), (503, {"status": "fail"}, None), (200, {"status": "ok"}, None)])
    r = p.check("u", attempts=3, delay=1, prober=lambda u: next(seq), sleep=sleeps.append)
    assert r["verdict"] == "up" and r["attempts"] == 3 and sleeps == [1, 1]     # a blip does not alert
    r = p.check("u", attempts=3, delay=1, prober=lambda u: (None, None, "refused"), sleep=lambda s: None)
    assert r["verdict"] == "down" and r["code"] == 1 and r["attempts"] == 3
    r = p.check("u", attempts=3, delay=1, prober=lambda u: (200, {"status": "degraded", "checks": {}}, None),
                sleep=lambda s: pytest.fail("degraded must not be retried"))
    assert r["verdict"] == "degraded" and r["attempts"] == 1


def test_probe_against_live_test_server(api):
    """Real HTTP round trip through the probe's classification of a real deep-health body."""
    p = load_probe()
    r = api.get("/api/health/deep")
    assert p.classify(r.status_code, r.json(), None)[0] == p.UP
