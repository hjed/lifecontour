# Shared Python Base Image
# Provides common system dependencies, uv, core_shared, and a non-root user.
#
# All backend and integration worker Dockerfiles extend this base.
# Build context must be the repository root so that core_shared/ is available.
#
# Build with:
#   docker build -f docker/python-base/Dockerfile -t pms-python-base .

FROM python:3.14.10-slim

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

# Pre-install core_shared package (shared by all Python services).
# Its dependencies come from core_shared/uv.lock: `uv export --locked` fails the
# build when the lock is stale against pyproject.toml, and the exported hashes
# are verified on install. Every install passes --no-deps: the export is the
# complete locked closure, and re-resolving it would drop the lock's overrides.
# The package itself is then installed editable.
# Each backend/worker image re-pins these on top from its own lock.
COPY core_shared/ /core_shared/
RUN uv export -q --locked --no-dev --no-emit-project --project /core_shared \
        -o /tmp/requirements.txt \
 && uv pip install --system --no-cache --no-deps -r /tmp/requirements.txt \
 && uv pip install --system --no-deps -e /core_shared

# Default working directory
WORKDIR /app
