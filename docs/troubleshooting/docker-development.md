# Docker Development Environment

This guide explains how to set up and use the complete Docker-based development environment for the Personal Management System.

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose installed
- Git (to clone the repository)

### Start the Complete Environment

```bash
# Clone the repository (if you haven't already)
git clone https://github.com/hjed/lifecontour.git
cd lifecontour

# Start all services
./scripts/dev.sh docker-start
```

That's it! All services will be started automatically with proper dependencies and networking.

## 🌐 Service URLs

Once started, you can access:

- **Frontend**: http://localhost:3000 (Next.js development server)
- **Backend API**: http://localhost:8000 (FastAPI with auto-reload)
- **API Documentation**: http://localhost:8000/api/docs (Swagger UI)
- **Database**: localhost:5432 (PostgreSQL)
- **Search**: http://localhost:7700 (MeiliSearch)
- **OAuth Provider**: http://localhost:4444 (Hydra)
- **OAuth UI**: http://localhost:4445 (Hydra Admin UI)
- **Jaeger Tracing**: http://localhost:16686 (OpenTelemetry traces)

## 🐳 Docker Services

The development environment includes these services:

### Core Application Services

- **`frontend-dev`**: Next.js development server with hot reload
- **`backend-dev`**: FastAPI server with auto-reload and debug mode
- **`database`**: PostgreSQL 16 with development data
- **`search`**: MeiliSearch for full-text search capabilities

### Supporting Services

- **`oauth-provider`**: Hydra OAuth2/OIDC provider for authentication
- **`oauth-ui`**: Hydra admin UI for OAuth management
- **`jaeger`**: OpenTelemetry tracing for observability

## 🛠️ Development Commands

### Service Management (Unified Docker Compose)

```bash
# Start all services (dev profile - default)
docker compose up

# Stop all services
docker compose down

# Restart specific service
docker compose restart frontend

# View service status
docker compose ps

# View logs for all services
docker compose logs -f

# View logs for specific service
docker compose logs -f backend
```

### Legacy Commands (Still Supported)

```bash
# Start all services
./scripts/dev.sh docker-start

# Stop all services
./scripts/dev.sh docker-stop

# Restart specific service
./scripts/dev.sh docker-restart backend-dev

# View service status
./scripts/dev.sh docker-status
```

### Logs and Debugging (Unified Docker Compose)

```bash
# View logs for all services
docker compose logs

# View logs for specific service
docker compose logs backend

# Follow logs in real-time
docker compose logs -f backend

# View last 50 lines
docker compose logs --tail 50 frontend

# View logs with timestamps
docker compose logs --timestamps backend
```

### Database Operations (Unified Docker Compose)

```bash
# Run database migrations
docker compose exec backend alembic upgrade head

# Create new migration
docker compose exec backend alembic revision --autogenerate -m "Description"

# Access database shell
docker compose exec database psql -U postgres -d personal_management

# Reset database (WARNING: destroys all data)
docker compose down -v
docker compose up database
```

### Legacy Database Commands

```bash
# Run database migrations (old)
./scripts/dev.sh docker-exec backend-dev alembic upgrade head

# Create new migration (old)
./scripts/dev.sh docker-exec backend-dev alembic revision --autogenerate -m "Description"

# Access database shell (old)
./scripts/dev.sh docker-exec database psql -U dev_user -d personal_management_dev
```

### Code Quality and Testing (Unified Docker Compose)

```bash
# Run linting and type checking
docker compose exec backend uv run ruff check .
docker compose exec backend uv run mypy .
docker compose exec frontend pnpm lint

# Run tests
docker compose exec backend uv run pytest
docker compose exec frontend pnpm test

# Run tests with coverage
docker compose exec backend uv run pytest --cov=app
docker compose exec frontend pnpm test:coverage

# Run e2e tests
docker compose --profile test --env-file .env.test up
cd frontend && pnpm test:e2e
docker compose --profile test down -v
```

## 🔧 Configuration

### Environment Variables (Unified Docker Compose)

The unified Docker Compose setup uses these configuration files:

- **`docker-compose.yml`**: Unified configuration with profiles
- **`.env.dev`**: Development environment variables (default)
- **`.env.test`**: Testing environment variables
- **`.env.prod`**: Production environment variables

### Key Environment Variables

**Development (.env.dev):**
```bash
# Database
DB_NAME=personal_management_dev
DB_USER=dev_user
DB_PASSWORD=dev_password
DB_PORT=5432

# Backend
DEBUG=true
LOG_LEVEL=DEBUG
OAUTH_CLIENT_ID=dev-client-id
OAUTH_CLIENT_SECRET=dev-client-secret

# Frontend
NODE_ENV=development
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Testing (.env.test):**
```bash
# Database
DB_NAME=personal_management_test
DB_USER=postgres
DB_PASSWORD=postgres
DB_PORT=5433

# Backend
DEBUG=true
OAUTH_CLIENT_ID=test-client-id
OAUTH_CLIENT_SECRET=test-client-secret
```

For complete configuration details, see [Docker Compose Unified Setup](../DOCKER_COMPOSE_UNIFIED.md).

## 🚀 Development Features

### Hot Reload and Live Development

- **Hot Reload**: Both frontend and backend automatically reload on code changes
- **Volume Mounts**: Your local code is mounted into containers
- **Debug Mode**: All services run in debug mode with verbose logging
- **Fast Startup**: Services start in parallel with health checks

### Database Access

Connect to the development database:

```bash
# Using psql
psql -h localhost -p 5432 -U dev_user -d personal_management_dev

# Connection details
Host: localhost
Port: 5432
Database: personal_management_dev
Username: dev_user
Password: dev_password
```

### Running Tests

```bash
# Run all tests (uses separate test database)
./scripts/dev.sh test

# Run backend tests only
./scripts/dev.sh docker-exec backend-dev uv run pytest

# Run frontend tests only
./scripts/dev.sh docker-exec frontend-dev pnpm test

# Run integration tests
./scripts/dev.sh docker-exec backend-dev uv run pytest tests/integration/
```

## 🔍 Debugging and Troubleshooting

### Common Issues

#### Port Conflicts
If you get port binding errors:
```bash
# Check what's using the ports
lsof -i :3000  # Frontend
lsof -i :8000  # Backend
lsof -i :5432  # Database

# Stop conflicting services or change ports in docker-compose.dev.yml
```

#### Database Connection Issues
```bash
# Check database is running
./scripts/dev.sh docker-logs database

# Verify database connectivity
./scripts/dev.sh docker-exec backend-dev python -c "
import asyncpg
import asyncio
async def test():
    conn = await asyncpg.connect('postgresql://dev_user:dev_password@database:5432/personal_management_dev')
    print('Database connected successfully')
    await conn.close()
asyncio.run(test())
"
```

#### Service Health Checks
```bash
# Check service health
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View health check logs
./scripts/dev.sh docker-logs backend-dev | grep health
```

### Observability and Monitoring

#### OpenTelemetry Tracing
- Access Jaeger UI at http://localhost:16686
- View API request traces and database queries
- Monitor performance and debug issues

#### Application Logs
```bash
# View structured logs
./scripts/dev.sh docker-logs backend-dev | jq .

# Filter logs by level
./scripts/dev.sh docker-logs backend-dev | grep ERROR

# View OAuth provider logs
./scripts/dev.sh docker-logs oauth-provider
./scripts/dev.sh docker-logs oauth-ui
```

### Resetting the Environment

```bash
# Stop and remove all containers and volumes
./scripts/dev.sh docker-stop
docker-compose -f docker-compose.dev.yml down -v

# Start fresh
./scripts/dev.sh docker-start
```

## 📝 Development Tips

1. **Use Jaeger**: Monitor your API calls and database queries in real-time
2. **Test OAuth Early**: Verify authentication flows work before building features
3. **Check Logs**: Use `docker-logs` to debug issues quickly
4. **Hot Reload**: Code changes are reflected immediately in both frontend and backend
5. **Database Inspection**: Use any PostgreSQL client to inspect data during development

## 🔄 Switching Between Local and Docker

You can switch between local development and Docker:

```bash
# Local development (requires local PostgreSQL/MeiliSearch)
./scripts/dev.sh start

# Docker development (everything in containers)
./scripts/dev.sh docker-start
```

The Docker environment is recommended for:
- Complete integration testing
- OAuth flow testing
- OpenTelemetry/observability development
- Consistent environment across team members

Local development is faster for:
- Quick backend-only changes
- Frontend-only development
- When you already have local services running

## 📚 Related Documentation

- [CI/CD Setup](../ci-cd-setup.md) - Continuous integration configuration
- [Code Quality Standards](../code-quality-standards.md) - Linting and formatting standards
- [Architecture Overview](../architecture.md) - System design and patterns
- [Deployment Guide](../architecture/deployment-guide.md) - Production deployment
