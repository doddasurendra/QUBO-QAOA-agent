from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("qopt")
# <repo>/backend/qopt/config.py → <repo>; only meaningful for a source checkout
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QOPT_", env_file=".env", extra="ignore")

    environment: str = "development"           # development | production
    database_url: str = "sqlite:///./data/qopt.db"
    jwt_secret: str = ""
    jwt_expiry_minutes: int = 120
    allow_registration: bool = False            # self-service researcher accounts
    # One-time token required to create the first administrator in production (so the first visitor of a public
    # deployment cannot claim admin). Empty in production → bootstrap disabled. Not required in development.
    bootstrap_token: str = ""

    def bootstrap_token_required(self) -> bool:
        return self.environment == "production"
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    rate_limit_per_minute: int = 240
    agent_rate_limit_per_minute: int = 10
    max_upload_bytes: int = 5 * 1024 * 1024
    worker_threads: int = 4
    job_timeout_s: int = 900
    max_concurrent_jobs_per_user: int = 4
    max_statevector_qubits: int = 22
    agent_daily_budget_usd: float = 10.0
    agent_run_budget_usd: float = 2.0
    redis_url: str = ""                         # optional; not required for single-node deployments
    # Built-in SQLite backups (ignored for PostgreSQL): consistent copy every N hours, newest K kept.
    backup_interval_hours: float = 24.0         # 0 disables the scheduler
    backup_keep: int = 14
    backup_dir: str = ""                        # default: <database dir>/backups
    backup_first_delay_s: float = 600.0         # first scheduled backup this long after startup
    # Locations of the built SPA and the markdown docs. Empty → the source-checkout defaults
    # (<repo>/frontend/dist, <repo>/docs). Set explicitly for installed deployments (the Docker image does).
    frontend_dist: str = ""
    docs_dir: str = ""

    def frontend_dist_path(self) -> Path:
        return Path(self.frontend_dist) if self.frontend_dist else _REPO_ROOT / "frontend" / "dist"

    def docs_path(self) -> Path:
        return Path(self.docs_dir) if self.docs_dir else _REPO_ROOT / "docs"

    def effective_jwt_secret(self) -> str:
        if self.environment == "production":
            if not self.jwt_secret:
                raise RuntimeError("QOPT_JWT_SECRET must be set in production")
            if len(self.jwt_secret) < 32 or " " in self.jwt_secret:
                raise RuntimeError("QOPT_JWT_SECRET is too weak: use ≥ 32 random characters, e.g. "
                                   "python -c \"import secrets;print(secrets.token_urlsafe(48))\"")
        if self.jwt_secret:
            return self.jwt_secret
        if not hasattr(self, "_dev_secret"):
            object.__setattr__(self, "_dev_secret", secrets.token_urlsafe(48))
            log.warning("QOPT_JWT_SECRET not set: using an ephemeral development secret "
                        "(tokens are invalidated on restart)")
        return self._dev_secret  # type: ignore[attr-defined]


@lru_cache
def get_settings() -> Settings:
    return Settings()
