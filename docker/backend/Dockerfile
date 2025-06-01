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
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system -e .[dev]

# Copy source code
COPY app ./app
COPY alembic.ini ./

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
COPY pyproject.toml ./

# Install production dependencies only
RUN uv pip install --system .

# Copy application code
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic.ini ./

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

# Start the application
COPY docker/backend/start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
