# Google Contacts Integration Worker
# Extends the shared python-base image which provides:
#   - Python 3.14, system deps, uv, core_shared, and the appuser account

FROM pms-python-base

# Copy worker pyproject.toml and install dependencies
COPY ./integration_workers/google/pyproject.toml .
RUN uv pip install --system --no-cache-dir --no-sources .

# Copy worker code
COPY ./integration_workers/google/ .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import redis; r=redis.Redis.from_url('${REDIS_URL}'); r.ping()" || exit 1

# Switch to non-root user
USER appuser

# Run the worker
CMD ["python", "worker.py"]
