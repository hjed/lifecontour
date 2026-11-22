# Snipe-IT Integration Worker
# Extends the shared python-base image which provides:
#   - Python 3.14, system deps, uv, core_shared, and the appuser account

FROM pms-python-base

# Install dependencies from uv.lock, before the source so code edits keep this
# layer cached. The manifest and lock go to the repo-shaped path because the
# lock's `../../core_shared` path source can't be resolved from /app; from here
# it resolves to the /core_shared copy the base image installed.
# `uv export --locked` fails the build when the lock is stale against
# pyproject.toml, and the exported hashes are verified on install. --no-deps:
# the export is the complete locked closure, and re-resolving it would drop the
# lock's `override-dependencies` (redis>=8 over arq's redis<6 pin).
COPY ./integration_workers/snipeit/pyproject.toml ./integration_workers/snipeit/uv.lock /integration_workers/snipeit/
RUN uv export -q --locked --no-dev --no-emit-project --no-emit-package core_shared \
        --project /integration_workers/snipeit -o /tmp/requirements.txt \
 && uv pip install --system --no-cache --no-deps -r /tmp/requirements.txt

# Copy the worker source and install the worker itself (dependencies above)
COPY ./integration_workers/snipeit/ .
RUN uv pip install --system --no-cache-dir --no-deps --no-sources .

# Health check — Python reads REDIS_URL from the environment at runtime
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import redis, os; r=redis.Redis.from_url(os.environ['REDIS_URL']); r.ping()" || exit 1

# Switch to non-root user
USER appuser

# Run the ARQ worker
CMD ["python", "worker.py"]
