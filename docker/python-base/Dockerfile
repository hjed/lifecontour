# Shared Python Base Image
# Provides common system dependencies, uv, core_shared, and a non-root user.
#
# All backend and integration worker Dockerfiles extend this base.
# Build context must be the repository root so that core_shared/ is available.
#
# Build with:
#   docker build -f docker/python-base/Dockerfile -t pms-python-base .

FROM python:3.14.5-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies (superset needed by backend + workers).
# fonts-dejavu-core supplies the DejaVu Sans face the outdoor logbook PDF export
# draws its journal-type icon glyphs with — the built-in PDF fonts are
# WinAnsi-encoded and would render those codepoints as empty boxes.
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install UV for dependency management
RUN pip install uv==0.11.15

# Create shared non-root user with home directory
# (FastMCP OAuthProxy needs writable home for token storage)
RUN groupadd -r appuser && useradd -r -m -g appuser appuser

# Pre-install core_shared package (shared by all Python services)
COPY core_shared/ /core_shared/
RUN uv pip install --system -e /core_shared

# Default working directory
WORKDIR /app
