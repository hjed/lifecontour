# Strava Integration Worker
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy and install core_shared package first (for caching)
COPY ./core_shared/ /core_shared/
RUN pip install -e /core_shared/

# Copy worker pyproject.toml and install dependencies
COPY ./integration_workers/strava/pyproject.toml .
RUN pip install --no-cache-dir .

# Copy worker code
COPY ./integration_workers/strava/ .

# Create non-root user
RUN useradd --create-home --shell /bin/bash worker

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import redis; r=redis.Redis.from_url('${REDIS_URL}'); r.ping()" || exit 1

# Switch to non-root user
USER worker

# Run the worker (placeholder — Phase 3 adds the ARQ worker entrypoint)
CMD ["python", "-c", "print('Strava worker ready — waiting for Phase 3 worker.py')"]
