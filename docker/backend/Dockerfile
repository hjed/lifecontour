# Backend Dockerfile - Python FastAPI
FROM python:3.11-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install UV for dependency management
RUN pip install uv

# Set working directory
WORKDIR /app

# Copy dependency files
COPY backend/pyproject.toml ./
COPY backend/README.md ./

# Install dependencies
RUN uv pip install --system -e .[dev]

# Copy source code
COPY backend/app ./app
COPY backend/alembic.ini ./

# Production stage
FROM python:3.11-slim AS production

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies, UV, and create app user
RUN apt-get update && apt-get install -y \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv \
    && groupadd -r appuser && useradd -r -g appuser appuser

# Set working directory
WORKDIR /app

# Copy dependency files
COPY backend/pyproject.toml ./
COPY backend/README.md ./

# Install production dependencies only
RUN uv pip install --system .

# Copy scripts and set permissions as root
COPY docker/backend/start.sh /start.sh
COPY docker/backend/healthcheck.sh /healthcheck.sh
RUN chmod +x /start.sh /healthcheck.sh

# Copy application code
COPY --chown=appuser:appuser backend/app ./app
COPY --chown=appuser:appuser backend/alembic.ini ./

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["/healthcheck.sh"]
CMD ["/start.sh"]
