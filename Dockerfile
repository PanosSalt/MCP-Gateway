# ── Frontend build stage ──────────────────────────────────────────────────────
FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

# ── API stage ─────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Create a non-root user to run the application
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend-builder /app/static/ app/static/

# Ensure the app user owns all files
RUN chown -R appuser:appgroup /app

EXPOSE 8000
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1

USER appuser
ENTRYPOINT ["./entrypoint.sh"]
