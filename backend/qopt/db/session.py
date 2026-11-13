from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings

_engine = None
_SessionLocal = None
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"     # qopt/migrations


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            path = url.split("///", 1)[-1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _fk(dbapi_conn, _):  # enforce foreign keys on SQLite
                dbapi_conn.execute("PRAGMA foreign_keys=ON")
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = _SessionLocal = None


def SessionLocal() -> Session:
    engine()
    return _SessionLocal()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate():
    """Apply Alembic migrations up to head (used at startup and by tests)."""
    from alembic import command
    from alembic.config import Config
    # Migrations ship inside the package (qopt/migrations), so this works from a source checkout
    # and from a regular (non-editable) install such as the Docker image. No alembic.ini needed.
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    cfg.attributes["url_set_by_caller"] = True
    command.upgrade(cfg, "head")
