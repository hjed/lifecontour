#!/bin/bash
set -e

echo "Running database migrations..."
# Run Alembic migrations to ensure database schema is up to date
alembic upgrade head

echo "Starting the application..."
# Start the application
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
