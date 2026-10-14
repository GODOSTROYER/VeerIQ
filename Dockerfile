FROM node:22-alpine AS frontend-build
WORKDIR /src
COPY frontend/package*.json ./frontend/
RUN npm --prefix frontend ci
COPY frontend ./frontend
RUN npm --prefix frontend run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system --gid 10001 veeriq && useradd --system --uid 10001 --gid veeriq --home-dir /app veeriq
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN python -m pip install --upgrade pip && python -m pip install 'uv==0.9.*' \
    && uv sync --project backend --locked --no-dev --no-install-project
COPY backend/rewindsafe ./backend/rewindsafe
COPY backend/migrations ./backend/migrations
COPY backend/samples ./backend/samples
COPY --from=frontend-build /src/frontend/dist ./frontend/dist
RUN mkdir -p /app/.data && chown -R veeriq:veeriq /app
ENV PATH="/app/backend/.venv/bin:${PATH}"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=2)"
CMD ["uvicorn", "rewindsafe.api.app:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
