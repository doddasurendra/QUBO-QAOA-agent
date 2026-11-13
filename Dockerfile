# ---- frontend build ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- backend runtime (serves API + built SPA) ----
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 10001 qopt
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/qopt ./qopt
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
ARG EXTRAS=""
RUN pip install --upgrade pip && pip install ".${EXTRAS}" "psycopg[binary]>=3.1" && pip install pypdf
COPY docs /app/docs
COPY --from=web /web/dist /app/frontend/dist
RUN mkdir -p /app/backend/data && chown -R qopt /app
USER qopt
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "qopt.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "1"]
