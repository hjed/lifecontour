#!/bin/bash
set -e

echo "Running database migrations..."
# Run Alembic migrations to ensure database schema is up to date
alembic upgrade head

echo "Starting the application..."
# Start the application. --timeout-keep-alive keeps uvicorn from closing pooled
# proxy connections after 5 s idle (#1862); keep it equal to
# UVICORN_TIMEOUT_KEEP_ALIVE_SECONDS in backend/app/main.py.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 65
