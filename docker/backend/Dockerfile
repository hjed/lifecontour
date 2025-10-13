# Unified Backend Dockerfile - Python FastAPI
# Supports both development and production builds via build args

FROM python:3.14.0-slim AS base

# Build arguments
ARG BUILD_ENV=production
ARG INSTALL_DEV_DEPS=false

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install UV for dependency management
RUN pip install uv

# Create app user (for security)
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Copy dependency files
COPY backend/pyproject.toml backend/README.md ./
COPY core_shared/ /core_shared/

# Install core_shared first
RUN echo "Installing core_shared..." && \
    uv pip install --system -e /core_shared

# Install dependencies based on build environment
RUN if [ "$INSTALL_DEV_DEPS" = "true" ]; then \
        echo "Installing development dependencies..." && \
        uv pip install --system -e .[dev] && \
        uv pip install --system \
            watchdog \
            opentelemetry-exporter-otlp \
            opentelemetry-exporter-jaeger; \
    else \
        echo "Installing production dependencies..." && \
        uv pip install --system .; \
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
