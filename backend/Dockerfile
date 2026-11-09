FROM python:3.12.8-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install -e ".[dev]"

FROM base AS prod
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app
COPY . .
RUN useradd -r -u 1001 app && chown -R app /app
USER app
EXPOSE 8000
# Готовность: 200 (ok/degraded) — здоров, 503 (БД/миграции не готовы) — нет.
HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=30s CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header", "--proxy-headers"]

FROM deps AS dev
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--no-server-header"]
