from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("qopt")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QOPT_", env_file=".env", extra="ignore")

    environment: str = "development"           # development | production
    database_url: str = "sqlite:///./data/qopt.db"
    jwt_secret: str = ""
    jwt_expiry_minutes: int = 120
    allow_registration: bool = False            # self-service researcher accounts
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

    def effective_jwt_secret(self) -> str:
        if self.jwt_secret:
            return self.jwt_secret
        if self.environment == "production":
            raise RuntimeError("QOPT_JWT_SECRET must be set in production")
        if not hasattr(self, "_dev_secret"):
            object.__setattr__(self, "_dev_secret", secrets.token_urlsafe(48))
            log.warning("QOPT_JWT_SECRET not set: using an ephemeral development secret "
                        "(tokens are invalidated on restart)")
        return self._dev_secret  # type: ignore[attr-defined]


@lru_cache
def get_settings() -> Settings:
    return Settings()
