import os
import uuid
from contextlib import contextmanager

import pytest

# Set (e.g. in CI) to run every API-fixture test against PostgreSQL instead of SQLite. It must point at a server
# where the user may CREATE DATABASE, e.g. postgresql+psycopg://postgres:postgres@localhost:5432/postgres.
# Each test gets its own freshly created (and afterwards dropped) database, migrated from scratch.
TEST_POSTGRES_URL = os.environ.get("QOPT_TEST_POSTGRES_URL", "")


@contextmanager
def _test_database(tmp_path):
    if not TEST_POSTGRES_URL:
        yield f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
        return
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    name = f"qopt_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(TEST_POSTGRES_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(TEST_POSTGRES_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture()
def database_url(tmp_path):
    with _test_database(tmp_path) as url:
        yield url


@pytest.fixture()
def api(database_url, monkeypatch):
    """FastAPI TestClient on a fresh migrated database (SQLite, or PostgreSQL if QOPT_TEST_POSTGRES_URL is set)
    with inline (synchronous) jobs."""
    monkeypatch.setenv("QOPT_DATABASE_URL", database_url)
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
