"""Deployment regressions: the app must work from an installed package, not only from the source tree."""
import fnmatch
import tomllib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def test_every_migration_file_is_declared_package_data():
    """Startup runs migrations; if they are not packaged, an installed (Docker) deployment crashes."""
    cfg = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    globs = cfg["tool"]["setuptools"]["package-data"]["qopt"]
    pkg = BACKEND / "qopt"
    files = [p.relative_to(pkg).as_posix() for p in (pkg / "migrations").rglob("*")
             if p.is_file() and "__pycache__" not in p.parts]
    assert any(f.startswith("migrations/versions/") for f in files), "no migration revisions found"
    missing = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in globs)]
    assert not missing, f"migration files not shipped with the package: {missing}"


def test_migrations_do_not_depend_on_alembic_ini(tmp_path, monkeypatch):
    """migrate() must work with an arbitrary working directory and no alembic.ini nearby."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("QOPT_DATABASE_URL", f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    from qopt.config import get_settings
    from qopt.db import migrate, reset_engine
    get_settings.cache_clear(); reset_engine()
    try:
        migrate()
        import sqlite3
        tables = {r[0] for r in sqlite3.connect(tmp_path / "m.db").execute(
            "select name from sqlite_master where type='table'")}
        assert {"users", "jobs", "experiments", "approval_requests", "audit_log"} <= tables
    finally:
        reset_engine(); get_settings.cache_clear()


def test_frontend_and_docs_locations_are_configurable(tmp_path, monkeypatch):
    (tmp_path / "GUIDE.md").write_text("# Guide from custom dir\n", encoding="utf-8")
    monkeypatch.setenv("QOPT_DOCS_DIR", str(tmp_path))
    monkeypatch.setenv("QOPT_FRONTEND_DIST", str(tmp_path / "no-dist"))
    from qopt.config import get_settings
    get_settings.cache_clear()
    try:
        s = get_settings()
        assert s.docs_path() == tmp_path and s.frontend_dist_path() == tmp_path / "no-dist"
        from qopt.api.routes_admin import docs_dir
        assert (docs_dir() / "GUIDE.md").is_file()
    finally:
        get_settings.cache_clear()


def test_production_rejects_missing_or_weak_jwt_secret(monkeypatch):
    from qopt.config import Settings
    with pytest.raises(RuntimeError, match="must be set"):
        Settings(environment="production", jwt_secret="").effective_jwt_secret()
    with pytest.raises(RuntimeError, match="too weak"):
        Settings(environment="production", jwt_secret="generate-with: python -c ...").effective_jwt_secret()
    ok = "a" * 48
    assert Settings(environment="production", jwt_secret=ok).effective_jwt_secret() == ok


def test_env_example_lists_every_setting():
    from qopt.config import Settings
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    missing = [f"QOPT_{name.upper()}" for name in Settings.model_fields if f"QOPT_{name.upper()}" not in text]
    assert not missing, f".env.example does not mention: {missing}"
    for var in ("POSTGRES_PASSWORD", "ANTHROPIC_API_KEY", "QISKIT_IBM_TOKEN", "QOPT_BRAKET_S3_BUCKET",
                "DWAVE_API_TOKEN", "QOPT_CLAUDE_MODEL"):
        assert var in text
    # the JWT secret must not ship with a non-empty placeholder value
    line = next(l for l in text.splitlines() if l.startswith("QOPT_JWT_SECRET="))
    assert line == "QOPT_JWT_SECRET="


def test_dockerfile_matches_repository_layout():
    df = (REPO / "Dockerfile").read_text(encoding="utf-8")
    for line in df.splitlines():
        if line.startswith("COPY ") and "--from" not in line:
            src = line.split()[1]
            assert (REPO / src).exists(), f"Dockerfile copies missing path {src}"
    assert "QOPT_FRONTEND_DIST" in df and "QOPT_DOCS_DIR" in df
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8")
    assert "node_modules" in ignore and ".venv" in ignore
