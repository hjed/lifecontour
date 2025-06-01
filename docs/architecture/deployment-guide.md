# Deployment Guide - Personal CRM & Journal System

This document covers deployment architecture, infrastructure setup, containerization, and operational considerations for the Python FastAPI backend with Next.js frontend.

## Deployment Architecture Overview

### Development Environment
- PostgreSQL database in Docker container
- MeiliSearch search engine in Docker container
- Python backend with UV dependency management
- Next.js frontend with pnpm
- Environment-based configuration
- Hot reloading for both backend and frontend
- Mock external services for testing
- Docker Compose for consistent development setup

### Production Environment
- **Reverse Proxy**: Nginx proxy handling SSL termination and load balancing
- **Multi-Container Deployment**: Separate containers for backend, frontend, database, search
- **Orchestration**: Docker Compose or Kubernetes
- **Database**: PostgreSQL with persistent volume mounts and backups
- **Search Engine**: MeiliSearch with persistent volume mounts
- **Configuration**: Environment variables and secrets management
- **Health Checks**: Built-in health endpoints for all services
- **Monitoring**: Prometheus metrics and log aggregation
- **Backup**: Automated PostgreSQL backup to external storage
- **CI/CD**: GitHub Actions with separate backend/frontend pipelines

## Docker Configuration

### Backend Dockerfile (Python FastAPI)

```dockerfile
# Backend Dockerfile
FROM python:3.11-slim AS backend

WORKDIR /app

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen

# Copy application code
COPY app/ ./app/

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Start application
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Frontend Dockerfile (Next.js)

```dockerfile
# Frontend Dockerfile
FROM node:18-alpine AS frontend

WORKDIR /app

# Copy package files
COPY package.json pnpm-lock.yaml ./

# Install pnpm and dependencies
RUN npm install -g pnpm && pnpm install --frozen-lockfile

# Copy source code
COPY . .

# Build application
RUN pnpm build

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001

USER nextjs

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

# Expose port
EXPOSE 3000

# Start application
CMD ["pnpm", "start"]
```

### Docker Compose Configuration

#### Development (docker-compose.yml)
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: personal_crm_dev
      POSTGRES_USER: dev_user
      POSTGRES_PASSWORD: dev_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_dev_data:/var/lib/postgresql/data

  meilisearch:
    image: getmeili/meilisearch:v1.2
    environment:
      MEILI_MASTER_KEY: dev_master_key
      MEILI_ENV: development
    ports:
      - "7700:7700"
    volumes:
      - meilisearch_dev_data:/meili_data

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
    environment:
      - DATABASE_URL=postgresql://dev_user:dev_password@postgres:5432/personal_crm_dev
      - MEILISEARCH_URL=http://meilisearch:7700
      - MEILISEARCH_MASTER_KEY=dev_master_key
      - ENVIRONMENT=development
    depends_on:
      - postgres
      - meilisearch
    command: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    depends_on:
      - backend
    command: pnpm dev

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/dev.conf:/etc/nginx/nginx.conf
    depends_on:
      - backend
      - frontend

volumes:
  postgres_dev_data:
  meilisearch_dev_data:
```

#### Production (docker-compose.prod.yml)
```yaml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: personal_crm_prod
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_prod_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d personal_crm_prod"]
      interval: 30s
      timeout: 10s
      retries: 3

  meilisearch:
    image: getmeili/meilisearch:v1.2
    restart: unless-stopped
    environment:
      MEILI_MASTER_KEY: ${MEILISEARCH_MASTER_KEY}
      MEILI_ENV: production
    volumes:
      - meilisearch_prod_data:/meili_data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7700/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/personal_crm_prod
      - MEILISEARCH_URL=http://meilisearch:7700
      - MEILISEARCH_MASTER_KEY=${MEILISEARCH_MASTER_KEY}
      - ENVIRONMENT=production
      - MCP_PORT=3001
      - MCP_HOST=0.0.0.0
    volumes:
      - backend-logs:/app/logs
    depends_on:
      - postgres
      - meilisearch
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - NEXT_PUBLIC_API_URL=https://your-domain.com/api
    depends_on:
      - backend
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/prod.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
      - nginx-logs:/var/log/nginx
    depends_on:
      - backend
      - frontend
    restart: unless-stopped

  backup:
    image: postgres:15-alpine
    volumes:
      - postgres_prod_data:/var/lib/postgresql/data
      - backup-storage:/backup
    environment:
      - PGPASSWORD=${DB_PASSWORD}
    command: |
      sh -c "
        while true; do
          pg_dump -h postgres -U ${DB_USER} personal_crm_prod > /backup/backup-$(date +%Y%m%d-%H%M%S).sql
          find /backup -name '*.sql' -mtime +7 -delete
          sleep 86400
        done
      "
    depends_on:
      - postgres
    restart: unless-stopped

volumes:
  postgres_prod_data:
  meilisearch_prod_data:
  backend-logs:
  nginx-logs:
  backup-storage:
```

## Nginx Proxy Configuration

### Production Nginx Configuration
```nginx
events {
    worker_connections 1024;
}

http {
    upstream backend {
        server backend:8000;
    }

    upstream frontend {
        server frontend:3000;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/s;

    # SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;

    server {
        listen 80;
        server_name your-domain.com;
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        ssl_certificate /etc/nginx/ssl/cert.pem;
        ssl_certificate_key /etc/nginx/ssl/key.pem;

        # Security headers
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains";

        # Proxy settings
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Backend API routes with rate limiting
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://backend/;
        }

        # Authentication routes with stricter rate limiting
        location /api/auth/ {
            limit_req zone=auth burst=5 nodelay;
            proxy_pass http://backend/api/auth/;
        }

        # MCP server endpoint (if exposed via proxy)
        location /mcp/ {
            limit_req zone=api burst=10 nodelay;
            proxy_pass http://backend:3001/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_cache_bypass $http_upgrade;
        }

        # Backend health check endpoint
        location /api/health {
            proxy_pass http://backend/health;
            access_log off;
        }

        # Frontend health check endpoint
        location /health {
            proxy_pass http://frontend/health;
            access_log off;
        }

        # Static files (served by Next.js)
        location /_next/static/ {
            proxy_pass http://frontend;
            expires 1y;
            add_header Cache-Control "public, immutable";
        }

        # Main frontend application
        location / {
            proxy_pass http://frontend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_cache_bypass $http_upgrade;
        }
    }
}
```

## Observability and Monitoring

### Python Backend Observability

#### Logging Configuration
```python
# app/observability/logging.py
import logging
import sys
from typing import Dict, Any

def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/app/logs/app.log')
        ]
    )

def log_business_event(event_name: str, context: Dict[str, Any]) -> None:
    """Log business events with structured context."""
    logger = logging.getLogger("business_events")
    logger.info(f"Business Event: {event_name}", extra=context)
```

#### Health Checks
```python
# app/api/health.py
from fastapi import APIRouter
from sqlalchemy import text
from app.database import get_db_connection
import psutil
import time

router = APIRouter()

@router.get("/health")
async def health_check():
    """Comprehensive health check for all services."""
    start_time = time.time()

    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "checks": {
            "database": await check_database(),
            "memory": check_memory(),
            "disk": check_disk_space(),
            "uptime": time.time() - start_time
        }
    }

    is_healthy = all(
        check.get("status") == "healthy"
        for check in health_status["checks"].values()
        if isinstance(check, dict)
    )

    return health_status

async def check_database():
    """Check database connectivity."""
    try:
        async with get_db_connection() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

def check_memory():
    """Check memory usage."""
    memory = psutil.virtual_memory()
    return {
        "status": "healthy" if memory.percent < 80 else "warning",
        "usage_percent": memory.percent,
        "available_mb": memory.available // 1024 // 1024
    }
```

## Environment Configuration

### Backend Environment Variables
```bash
# Python Backend (.env)
# Database
DATABASE_URL=postgresql://user:password@postgres:5432/personal_crm_prod

# Application
ENVIRONMENT=production
LOG_LEVEL=INFO
DEBUG=false

# Authentication
JWT_SECRET=your-jwt-secret-key
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Search Engine
MEILISEARCH_URL=http://meilisearch:7700
MEILISEARCH_MASTER_KEY=your-meilisearch-master-key

# External Services
IMMICH_API_URL=https://your-immich-instance.com
IMMICH_API_KEY=your-immich-api-key

# MCP Server
MCP_PORT=3001
MCP_HOST=0.0.0.0

# Security
CORS_ORIGINS=["https://your-domain.com"]
RATE_LIMIT_REQUESTS_PER_MINUTE=60
```

### Frontend Environment Variables
```bash
# Next.js Frontend (.env.local)
NEXT_PUBLIC_API_URL=https://your-domain.com/api
NEXT_PUBLIC_ENVIRONMENT=production

# Authentication (if needed on frontend)
NEXTAUTH_URL=https://your-domain.com
NEXTAUTH_SECRET=your-nextauth-secret
```

### Configuration Management
```python
# app/config.py
from pydantic import BaseSettings, validator
from typing import List

class Settings(BaseSettings):
    # Database
    database_url: str

    # Application
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # Authentication
    jwt_secret: str
    google_client_id: str
    google_client_secret: str

    # External Services
    immich_api_url: str
    immich_api_key: str

    # MCP Server
    mcp_port: int = 3001
    mcp_host: str = "0.0.0.0"

    # Security
    cors_origins: List[str] = ["http://localhost:3000"]
    rate_limit_requests_per_minute: int = 60

    @validator('cors_origins', pre=True)
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(',')]
        return v

    class Config:
        env_file = ".env"

settings = Settings()
```

## CI/CD Pipeline

### GitHub Actions Workflow
```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install UV
        run: pip install uv

      - name: Install dependencies
        run: cd backend && uv sync

      - name: Run backend tests
        run: cd backend && uv run pytest

      - name: Run backend linting
        run: cd backend && uv run ruff check && uv run black --check .

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'pnpm'
          cache-dependency-path: 'frontend/pnpm-lock.yaml'

      - name: Install dependencies
        run: cd frontend && pnpm install --frozen-lockfile

      - name: Run frontend tests
        run: cd frontend && pnpm test

      - name: Run frontend linting
        run: cd frontend && pnpm lint

      - name: Build frontend
        run: cd frontend && pnpm build

  deploy:
    needs: [test-backend, test-frontend]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - uses: actions/checkout@v4

      - name: Deploy to production
        run: |
          # Deploy using Docker Compose
          docker-compose -f docker-compose.prod.yml up -d --build
```

## Backup and Recovery

### PostgreSQL Backup Strategy
```bash
#!/bin/bash
# scripts/backup.sh

BACKUP_DIR="/backup"
DB_HOST="postgres"
DB_NAME="personal_crm_prod"
DB_USER="${DB_USER}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup-$TIMESTAMP.sql"

# Create backup
PGPASSWORD="${DB_PASSWORD}" pg_dump -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" > "$BACKUP_FILE"

# Compress backup
gzip "$BACKUP_FILE"

# Clean old backups (keep 30 days)
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE.gz"
```

### Recovery Procedures
1. **Database Recovery**: Restore from latest PostgreSQL backup using `pg_restore`
2. **Configuration Recovery**: Restore environment variables and secrets
3. **Container Recovery**: Restart containers with health checks
4. **Data Validation**: Verify data integrity and application functionality
5. **Service Verification**: Test all integrations (Google, Immich, MCP)

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - Application architecture being deployed
- [Technology Stack](./technology-stack.md) - Technologies used in deployment
- [Security & Performance](./security-performance.md) - Security and performance in production
