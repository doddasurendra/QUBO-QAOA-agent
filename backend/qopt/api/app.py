from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .. import __version__
from ..config import get_settings
from ..db import Dataset, SessionLocal, migrate
from ..industries import PROBLEMS
from ..services.security import rate_limiter
from . import routes_admin, routes_auth, routes_data, routes_opt


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        return json.dumps({"ts": self.formatTime(r), "level": r.levelname, "logger": r.name, "msg": r.getMessage(),
                           **({"exc": self.formatException(r.exc_info)} if r.exc_info else {})})


def configure_logging():
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    root = logging.getLogger("qopt")
    if not root.handlers:
        root.addHandler(h)
        root.setLevel(logging.INFO)
        root.propagate = False


def seed_samples():
    """Industry example inputs, stored as clearly-flagged SAMPLE datasets."""
    with SessionLocal() as db:
        existing = {d.problem_key for d in db.scalars(select(Dataset).where(Dataset.is_sample.is_(True))).all()}
        for key, p in PROBLEMS.items():
            if key not in existing:
                db.add(Dataset(owner_id=None, name=f"SAMPLE — {p.title}", problem_key=key, content=p.example(),
                               description="Synthetic sample data shipped with qopt for demonstration and testing. "
                                           "Not real business data.", is_sample=True))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    get_settings().effective_jwt_secret()   # fail fast in production without a secret
    migrate()
    seed_samples()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="qopt — QUBO/QAOA Optimisation Platform", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type",
                                                                                        "X-API-Key", "X-Bootstrap-Token"])
    log = logging.getLogger("qopt.http")

    @app.middleware("http")
    async def middleware(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        ip = request.client.host if request.client else "?"
        if request.url.path.startswith("/api/"):
            ok, retry = rate_limiter.allow(f"ip:{ip}", s.rate_limit_per_minute * 2)
            if not ok:
                return JSONResponse({"detail": "rate limit exceeded"}, 429, {"Retry-After": str(int(retry) + 1)})
            cl = request.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > s.max_upload_bytes + 64 * 1024:
                return JSONResponse({"detail": "request body too large"}, 413)
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error rid=%s path=%s", rid, request.url.path)
            return JSONResponse({"detail": "internal server error", "request_id": rid}, 500)
        resp.headers["X-Request-ID"] = rid
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            log.info("%s %s %s %.1fms rid=%s user=%s", request.method, request.url.path, resp.status_code,
                     (time.perf_counter() - t0) * 1000, rid, getattr(request.state, "user_id", None))
        return resp

    for r in (routes_auth.router, routes_opt.router, routes_data.router, routes_admin.router):
        app.include_router(r, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    # Serve the built frontend if present (single-container deployment)
    dist = s.frontend_dist_path().resolve()
    if not (dist / "index.html").is_file():
        logging.getLogger("qopt").warning("frontend build not found at %s: serving the API only "
                                          "(set QOPT_FRONTEND_DIST)", dist)
    if (dist / "index.html").is_file() and (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, 404)   # never answer API paths with the SPA
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
