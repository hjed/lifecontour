#!/bin/bash

# Development startup script for Personal Management System Backend
# Includes database migrations, OpenTelemetry setup, and hot reload

set -e

echo "🚀 Starting Personal Management System Backend (Development Mode)"

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
while ! pg_isready -h postgres-dev -p 5432 -U dev_user -d personal_management_dev; do
    echo "Database not ready, waiting..."
    sleep 2
done
echo "✅ Database is ready!"

# Wait for MeiliSearch to be ready
echo "⏳ Waiting for MeiliSearch to be ready..."
while ! curl -f http://meilisearch-dev:7700/health > /dev/null 2>&1; do
    echo "MeiliSearch not ready, waiting..."
    sleep 2
done
echo "✅ MeiliSearch is ready!"

# Run database migrations
echo "🔄 Running database migrations..."
alembic upgrade head
echo "✅ Database migrations completed!"

# Setup OpenTelemetry if enabled
if [ "${ENABLE_TELEMETRY}" = "true" ]; then
    echo "📊 OpenTelemetry enabled - traces will be sent to Jaeger"
    export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces"
    export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/metrics"
    export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/logs"
fi

# Start the development server with hot reload
echo "🔥 Starting FastAPI development server with hot reload..."
echo "📍 Backend will be available at: http://localhost:8000"
echo "📖 API Documentation: http://localhost:8000/api/docs"
echo "🔍 Health Check: http://localhost:8000/api/health"

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir /app/app \
    --log-level debug \
    --access-log
