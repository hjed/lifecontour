# Strava Integration Worker
# Extends the shared python-base image which provides:
#   - Python 3.14, system deps, uv, core_shared, and the appuser account

FROM pms-python-base

# Copy worker pyproject.toml for dependency caching
COPY ./integration_workers/strava/pyproject.toml .

# Copy worker source code before install so the package is complete
COPY ./integration_workers/strava/ .
RUN uv pip install --system --no-cache-dir --no-sources .

# Health check — uses shell form so $REDIS_URL is expanded at runtime
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import redis, os; r=redis.Redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# Switch to non-root user
USER appuser

# Run the ARQ worker
CMD ["python", "worker.py"]
