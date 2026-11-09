FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install -e ".[dev]"

FROM base AS prod
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app
COPY . .
RUN useradd -r -u 1001 app && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers"]

FROM deps AS dev
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--no-server-header"]
