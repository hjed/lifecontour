# Unified Docker Architecture

This document explains the unified Docker architecture that eliminates code duplication between development and production environments.

## 🎯 Overview

Instead of maintaining separate `Dockerfile` and `Dockerfile.dev` files, we now use a single unified Dockerfile for each service that supports both development and production builds via build arguments.

## 🏗️ Architecture Benefits

### ✅ Advantages
- **No Code Duplication**: Single source of truth for Docker configuration
- **Consistent Base Images**: Same base image and dependencies across environments
- **Easier Maintenance**: Changes only need to be made in one place
- **Build Argument Flexibility**: Environment-specific behavior via build args
- **Reduced Image Count**: Fewer Docker images to manage

### 🔧 How It Works

Both backend and frontend Dockerfiles use **build arguments** to determine behavior:

```dockerfile
# Build arguments control behavior
ARG BUILD_ENV=production
ARG INSTALL_DEV_DEPS=false

# Conditional logic based on environment
RUN if [ "$BUILD_ENV" = "development" ]; then \
        echo "Installing development dependencies..." && \
        uv pip install --system -e .[dev]; \
    else \
        echo "Installing production dependencies..." && \
        uv pip install --system .; \
    fi
```

## 🐳 Backend Dockerfile (`docker/backend/Dockerfile`)

### Key Features:
- **Base Image**: `python:3.11-slim`
- **PostgreSQL Client**: Includes `postgresql-client` for `pg_isready` command
- **Conditional Dependencies**: Dev dependencies only installed when `INSTALL_DEV_DEPS=true`
- **Multiple Scripts**: Both production (`/start.sh`) and development (`/start-dev.sh`) scripts
- **Security**: Non-root user (`appuser`) for container execution

### Build Arguments:
- `BUILD_ENV`: `development` or `production` (default: `production`)
- `INSTALL_DEV_DEPS`: `true` or `false` (default: `false`)

### Usage Examples:

```yaml
# Development (docker-compose.dev.yml)
backend-dev:
  build:
    context: .
    dockerfile: docker/backend/Dockerfile
    args:
      BUILD_ENV: development
      INSTALL_DEV_DEPS: "true"
  command: ["/start-dev.sh"]

# Production (docker-compose.yml)
backend:
  build:
    context: .
    dockerfile: docker/backend/Dockerfile
    args:
      BUILD_ENV: production
      INSTALL_DEV_DEPS: "false"
  # Uses default CMD: ["/start.sh"]
```

## 🌐 Frontend Dockerfile (`docker/frontend/Dockerfile`)

### Key Features:
- **Base Image**: `node:18-alpine`
- **Package Manager**: pnpm for fast, efficient package management
- **Conditional Build**: Production build only when `BUILD_ENV=production`
- **Development Mode**: Hot reload support with volume mounts
- **Security**: Non-root user (`frontend`) for container execution

### Build Arguments:
- `BUILD_ENV`: `development` or `production` (default: `production`)
- `NODE_ENV`: `development` or `production` (default: `production`)

### Usage Examples:

```yaml
# Development (docker-compose.dev.yml)
frontend-dev:
  build:
    context: .
    dockerfile: docker/frontend/Dockerfile
    args:
      BUILD_ENV: development
      NODE_ENV: development
  # Uses conditional CMD: pnpm dev

# Production (docker-compose.yml)
frontend:
  build:
    context: .
    dockerfile: docker/frontend/Dockerfile
    args:
      BUILD_ENV: production
      NODE_ENV: production
  # Uses conditional CMD: /start.sh
```

## 🔧 Fixed Issues

### 1. Missing `pg_isready` Command
**Problem**: Backend container couldn't check PostgreSQL readiness
**Solution**: Added `postgresql-client` package to backend Dockerfile

```dockerfile
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \  # ← Added this
    && rm -rf /var/lib/apt/lists/*
```

### 2. Code Duplication
**Problem**: Separate Dockerfiles for dev/prod with 80% identical code
**Solution**: Unified Dockerfiles with conditional logic

### 3. Inconsistent Dependencies
**Problem**: Dev and prod images could have different base packages
**Solution**: Same base image with conditional dependency installation

## 📁 File Structure

```
docker/
├── backend/
│   ├── Dockerfile              # ← Unified (dev + prod)
│   ├── start.sh               # Production startup
│   ├── start-dev.sh           # Development startup
│   └── healthcheck.sh         # Health check script
├── frontend/
│   ├── Dockerfile              # ← Unified (dev + prod)
│   ├── start.sh               # Production startup
│   └── healthcheck.sh         # Health check script
└── oauth-ui/                   # OAuth provider UI
    ├── package.json
    ├── server.js
    └── views/
```

## 🚀 Development Workflow

### Building Images:
```bash
# Development images
docker-compose -f docker-compose.dev.yml build

# Production images
docker-compose -f docker-compose.yml build
```

### Starting Services:
```bash
# Development environment
./scripts/dev.sh docker-start

# Production environment
docker-compose up -d
```

## 🔍 Debugging

### Check Build Arguments:
```bash
# Inspect image to see build args
docker inspect personal-management-system_backend-dev:latest

# Check environment variables
docker run --rm personal-management-system_backend-dev:latest env
```

### Test Different Environments:
```bash
# Build with different args
docker build \
  --build-arg BUILD_ENV=development \
  --build-arg INSTALL_DEV_DEPS=true \
  -f docker/backend/Dockerfile \
  -t test-backend-dev .
```

## 📋 Migration Guide

If you have existing separate Dockerfiles:

1. **Backup existing files**:
   ```bash
   cp docker/backend/Dockerfile docker/backend/Dockerfile.prod.backup
   cp docker/backend/Dockerfile.dev docker/backend/Dockerfile.dev.backup
   ```

2. **Update docker-compose files** to use build args:
   ```yaml
   build:
     context: .
     dockerfile: docker/backend/Dockerfile
     args:
       BUILD_ENV: development
       INSTALL_DEV_DEPS: "true"
   ```

3. **Remove old development Dockerfiles**:
   ```bash
   rm docker/backend/Dockerfile.dev
   rm docker/frontend/Dockerfile.dev
   ```

4. **Test both environments**:
   ```bash
   docker-compose -f docker-compose.dev.yml build
   docker-compose -f docker-compose.yml build
   ```

## 🎉 Result

- ✅ **50% fewer Docker files** to maintain
- ✅ **Consistent base images** across environments
- ✅ **Fixed `pg_isready` issue** in development
- ✅ **Easier maintenance** and updates
- ✅ **Same security practices** in both environments
