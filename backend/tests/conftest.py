import os

import pytest


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """FastAPI TestClient on a fresh migrated SQLite DB with inline (synchronous) jobs."""
    monkeypatch.setenv("QOPT_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("QOPT_WORKER_THREADS", "0")
    monkeypatch.setenv("QOPT_JWT_SECRET", "test-secret-" + "x" * 40)
    monkeypatch.setenv("QOPT_RATE_LIMIT_PER_MINUTE", "10000")
    monkeypatch.setenv("QOPT_BACKUP_INTERVAL_HOURS", "0")      # no background backup thread in API tests
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    from qopt.config import get_settings
    from qopt.db import reset_engine
    from qopt.services.security import rate_limiter
    get_settings.cache_clear()
    reset_engine()
    rate_limiter.reset()
    from fastapi.testclient import TestClient
    from qopt.api.app import create_app
    with TestClient(create_app()) as c:
        yield c
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture()
def admin_client(api):
    r = api.post("/api/auth/bootstrap", json={"email": "admin@example.com", "password": "correct-horse-1",
                                              "name": "Admin"})
    assert r.status_code == 200, r.text
    api.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return api
