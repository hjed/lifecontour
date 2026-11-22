# Unified Backend Dockerfile - Python FastAPI
# Extends the shared python-base image which provides:
#   - Python 3.14, system deps, uv, core_shared, and the appuser account
# Supports both development and production builds via build args

FROM pms-python-base AS base

# Build arguments
ARG BUILD_ENV=production
ARG INSTALL_DEV_DEPS=false

# Copy dependency files. The lock's `../core_shared` path source resolves to
# the /core_shared copy the base image installed.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./

# Install dependencies from uv.lock. `uv export --locked` fails the build when
# the lock is stale against pyproject.toml; the exported hashes are verified on
# install. Every install passes --no-deps: the export is the complete locked
# closure, and re-resolving it would drop the lock's overrides. core_shared is
# already installed (editable) by the base image. Production leaves out the dev
# dependency group; development adds the `dev` extra.
RUN if [ "$INSTALL_DEV_DEPS" = "true" ]; then \
        echo "Installing development dependencies..." && \
        uv export -q --locked --extra dev --no-emit-project --no-emit-package core_shared \
            -o /tmp/requirements.txt && \
        uv pip install --system --no-cache --no-deps -r /tmp/requirements.txt && \
        uv pip install --system --no-deps -e .; \
    else \
        echo "Installing production dependencies..." && \
        uv export -q --locked --no-dev --no-emit-project --no-emit-package core_shared \
            -o /tmp/requirements.txt && \
        uv pip install --system --no-cache --no-deps -r /tmp/requirements.txt && \
        uv pip install --system --no-deps .; \
    fi

# Copy application code
COPY backend/app ./app
COPY backend/alembic.ini ./

# Copy startup scripts based on build environment
RUN if [ "$BUILD_ENV" = "development" ]; then \
        echo "Setting up development environment..." && \
        mkdir -p .cache logs; \
    fi

# Copy and set up scripts
COPY docker/backend/start.sh /start.sh
COPY docker/backend/start-dev.sh /start-dev.sh
COPY docker/backend/healthcheck.sh /healthcheck.sh
# Convert Windows line endings to Unix line endings and make executable
RUN sed -i 's/\r$//' /start.sh /start-dev.sh /healthcheck.sh && \
    chmod +x /start.sh /start-dev.sh /healthcheck.sh

# Set proper permissions
RUN chown -R appuser:appuser /app && \
    chmod -R 755 ./app && \
    chmod 644 ./alembic.ini && \
    chown appuser:appuser /start.sh /start-dev.sh /healthcheck.sh

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["/healthcheck.sh"]

# Default command (can be overridden in docker-compose)
CMD ["/start.sh"]
