# Snipe-IT Integration Worker
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

# Copy worker pyproject.toml for dependency caching
COPY ./integration_workers/snipeit/pyproject.toml .

# Copy worker source code before install so the package is complete
COPY ./integration_workers/snipeit/ .
RUN pip install --no-cache-dir .

# Create non-root user
RUN useradd --create-home --shell /bin/bash worker

# Health check — uses shell form so $REDIS_URL is expanded at runtime
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import redis, os; r=redis.Redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# Switch to non-root user
USER worker

# Run the ARQ worker
CMD ["python", "worker.py"]
