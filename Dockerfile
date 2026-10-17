# FamilyLog in a container - see docs/CONTAINER.md.
#
#   bash update.sh compose up -d --build     (first start)
#   bash update.sh                           (updates: backup + automatic undo)
#
# One volume, /data, holds everything that is yours: app.db, settings.json,
# FamilyMap photos and the logs. The image holds only the code.

# ---- the frontend ---------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- the app --------------------------------------------------------------------
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DATA_DIR=/data \
    TZ=Europe/Copenhagen

# curl: the health check (and update.sh's check inside the container).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY VERSION ./
COPY docs/ docs/
COPY backend/app backend/app
COPY --from=web /src/frontend/dist backend/static

# Not root. A host folder mounted at /data must be owned by uid 1000.
RUN useradd --uid 1000 --create-home app \
 && mkdir -p /data \
 && chown -R app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/auth/status > /dev/null || exit 1
WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
