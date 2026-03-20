#!/bin/sh
set -e
alembic upgrade head
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --timeout-keep-alive 65 \
  --timeout-graceful-shutdown 30
