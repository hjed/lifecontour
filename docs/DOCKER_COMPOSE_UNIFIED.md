# Unified Docker Compose Setup

This document describes the unified Docker Compose configuration for Lifecontour, which consolidates all environment setups (development, testing, production) into a single `docker-compose.yml` file using Docker Compose profiles.

## Overview

The unified setup uses **Docker Compose profiles** to manage different service configurations:

- **dev** (default): Full development environment with hot reload and observability
- **test**: Complete testing environment with OAuth and all services
- **test-backend**: Minimal backend integration testing setup
- **prod**: Production deployment with nginx reverse proxy

## Quick Start

### Development (Default)

```bash
# Start development environment
docker compose up

# Or explicitly with dev profile
docker compose --profile dev up

# Stop services
docker compose down
```

**Services started:**
- PostgreSQL database
- Redis cache
- MeiliSearch
- Jaeger (observability)
- OAuth provider + UI
- Backend (with hot reload)
- Frontend (with hot reload)
- Google Contacts worker

**Access points:**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/api/docs
- OAuth Provider: http://localhost:4444
- OAuth UI: http://localhost:3001
- Jaeger UI: http://localhost:16686
- MeiliSearch: http://localhost:7700

### Testing

```bash
# Start test environment
docker compose --profile test --env-file .env.test up

# Run tests
cd frontend && pnpm test:e2e
cd backend && pytest tests/integration/

# Stop and clean up
docker compose --profile test down -v
```

**Services started:**
- PostgreSQL (port 5433)
- Redis (port 6380)
- MeiliSearch (port 7701)
- OAuth provider + UI (ports 4446, 4447, 3002)
- Backend (port 8001)

**Note:** The frontend dev server is managed by Playwright's `webServer` configuration during E2E tests, not by Docker Compose.

### Backend Integration Tests Only

```bash
# Start minimal test environment
docker compose --profile test-backend up

# Run backend integration tests
cd backend && python scripts/run_integration_tests.py

# Stop services
docker compose --profile test-backend down -v
```

**Services started:**
- PostgreSQL (port 5433)
- Redis (port 6380)
- MeiliSearch (port 7701)

### Production

```bash
# Start production environment
docker compose --profile prod --env-file .env.prod up -d

# Access via nginx
# Frontend: http://localhost
# Backend API: http://localhost/api
```

The compose `frontend` service always builds the Dockerfile's `development` stage: the dev
server over the bind-mounted source. For a production frontend, run the released
`ghcr.io/hjed/lifecontour-frontend` image with `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` set; see
[Deployment Guide → Frontend Image](architecture/deployment-guide.md#frontend-image).

**Services started:**
- PostgreSQL
- Redis
- MeiliSearch
- OAuth provider
- Backend (production build)
- Frontend (production build)
- Google Contacts worker
- Nginx reverse proxy

## Environment Configuration

Each profile uses environment variables from `.env` files:

### .env.dev (Development)
- Database: personal_management_dev (port 5432)
- Redis: port 6380
- MeiliSearch: port 7700
- OAuth: ports 4444, 4445, 3001
- Backend: port 8000
- Frontend: port 3000

### .env.test (Testing)
- Database: personal_management_test (port 5433)
- Redis: port 6380
- MeiliSearch: port 7701
- OAuth: ports 4446, 4447, 3002
- Backend: port 8001
- Frontend: port 3000 (managed by Playwright, not Docker Compose)

### .env.prod (Production)
- Database: personal_management (port 5432)
- Redis: port 6379
- MeiliSearch: port 7700
- OAuth: ports 4444, 4445
- Backend: port 8000 (internal)
- Frontend: port 3000 (internal)
- Nginx: ports 80, 443

## Service Profiles

### Core Services (All Profiles)
- **database**: PostgreSQL 15
- **redis**: Redis 7
- **meilisearch**: MeiliSearch v1.2

### Development Profile
- All core services
- **jaeger**: OpenTelemetry tracing
- **oauth-provider**: Hydra OAuth2/OIDC
- **oauth-login-consent**: OAuth UI
- **oauth-init**: OAuth client initialization
- **backend**: FastAPI (development mode)
- **frontend**: Next.js (development mode)
- **google-worker**: Integration worker

### Test Profile
- All core services
- **oauth-provider**: Hydra OAuth2/OIDC
- **oauth-login-consent**: OAuth UI
- **oauth-init**: OAuth client initialization
- **backend**: FastAPI (test mode)

**Note:** The frontend is not included in the test profile. For E2E tests, Playwright manages the frontend dev server via its `webServer` configuration.

### Test-Backend Profile
- Core services only (minimal setup)

### Production Profile
- All core services
- **oauth-provider**: Hydra OAuth2/OIDC
- **backend**: FastAPI (production build)
- **frontend**: Next.js (production build)
- **google-worker**: Integration worker
- **nginx**: Reverse proxy

## Volume Management

Volumes are automatically created and managed by Docker Compose:

```bash
# List volumes
docker volume ls | grep pms

# Remove all volumes (WARNING: deletes data)
docker compose down -v

# Backup database
docker compose exec database pg_dump -U postgres personal_management > backup.sql

# Restore database
docker compose exec -T database psql -U postgres personal_management < backup.sql
```

## Network Configuration

All services communicate via the `personal-management` bridge network:

```bash
# View network
docker network inspect personal-management

# Services can reference each other by name:
# - database:5432
# - redis:6379
# - meilisearch:7700
# - oauth-provider:4444
# - backend:8000
# - frontend:3000
```

## Troubleshooting

### Port Conflicts
```bash
# Check what's using a port
lsof -i :8000  # Backend
lsof -i :3000  # Frontend
lsof -i :5432  # Database

# Change port in .env file and restart
```

### Service Health Issues
```bash
# Check service logs
docker compose logs backend
docker compose logs database

# Restart a service
docker compose restart backend

# Rebuild a service
docker compose build --no-cache backend
docker compose up backend
```

### Database Issues
```bash
# Reset database (WARNING: deletes all data)
docker compose down -v
docker compose up database

# Check database connection
docker compose exec database psql -U postgres -d personal_management -c "SELECT 1"
```

## Migration from Old Setup

The old setup used separate files:
- `docker-compose.yml` (production)
- `docker-compose.dev.yml` (development)
- `docker-compose.test.yml` (testing)
- `backend/docker-compose.test.yml` (backend tests)

These are now consolidated into a single `docker-compose.yml` with profiles. The old files are deprecated but can be removed after verifying the new setup works.

## Best Practices

1. **Always use profiles**: Explicitly specify profiles to avoid starting unnecessary services
2. **Use environment files**: Keep configuration in `.env.dev`, `.env.test`, `.env.prod`
3. **Check health**: Wait for healthchecks before running tests
4. **Clean up**: Use `docker compose down -v` to remove volumes when switching profiles
5. **Rebuild when needed**: Rebuild images after dependency changes

