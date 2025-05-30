# Deployment Guide - Personal CRM & Journal System

This document covers deployment architecture, infrastructure setup, containerization, and operational considerations for the Personal CRM & Journal System.

## Deployment Architecture Overview

### Development Environment
- Local SQLite database
- Environment-based configuration
- Hot reloading for development
- Mock external services for testing
- Docker Compose for consistent development setup

### Production Environment
- **Reverse Proxy**: Nginx proxy handling SSL termination and load balancing
- **Containerized Deployment**: Docker containers with multi-stage builds
- **Orchestration**: Docker Compose or Kubernetes
- **Database**: SQLite with persistent volume mounts
- **Configuration**: Environment variables and secrets management
- **Health Checks**: Built-in health endpoints accessible through proxy
- **Monitoring**: Prometheus metrics and log aggregation
- **Backup**: Automated SQLite backup to external storage
- **CI/CD**: GitHub Actions or similar for automated deployment

## Docker Configuration

### Multi-Stage Dockerfile

```dockerfile
# Build stage
FROM node:24-alpine AS builder
WORKDIR /app

# Copy package files
COPY package*.json ./
COPY tsconfig.json ./

# Install dependencies
RUN npm ci --only=production && npm cache clean --force

# Copy source code
COPY src/ ./src/
COPY public/ ./public/

# Build application
RUN npm run build

# Runtime stage
FROM node:24-alpine AS runtime
WORKDIR /app

# Create non-root user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S nextjs -u 1001

# Copy built application
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

# Create data directory for SQLite
RUN mkdir -p /app/data && chown -R nextjs:nodejs /app/data

# Switch to non-root user
USER nextjs

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

# Expose port
EXPOSE 3000

# Start application
CMD ["npm", "start"]
```

### Docker Compose Configuration

#### Development (docker-compose.yml)
```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      target: builder
    ports:
      - "3000:3000"
    volumes:
      - .:/app
      - /app/node_modules
      - ./data:/app/data
    environment:
      - NODE_ENV=development
      - DATABASE_PATH=/app/data/dev.db
    command: npm run dev

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/dev.conf:/etc/nginx/nginx.conf
    depends_on:
      - app
```

#### Production (docker-compose.prod.yml)
```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      target: runtime
    restart: unless-stopped
    environment:
      - NODE_ENV=production
      - DATABASE_PATH=/app/data/production.db
      - PORT=3000
      - MCP_PORT=3001
      - MCP_HOST=0.0.0.0
    volumes:
      - app-data:/app/data
      - app-logs:/app/logs
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

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
      - app
    restart: unless-stopped

  backup:
    image: alpine:latest
    volumes:
      - app-data:/data
      - backup-storage:/backup
    command: |
      sh -c "
        while true; do
          cp /data/production.db /backup/backup-$(date +%Y%m%d-%H%M%S).db
          find /backup -name '*.db' -mtime +7 -delete
          sleep 86400
        done
      "
    restart: unless-stopped

volumes:
  app-data:
  app-logs:
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
    upstream app {
        server app:3000;
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

        # API routes with rate limiting
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://app;
        }

        # Authentication routes with stricter rate limiting
        location /api/auth/ {
            limit_req zone=auth burst=5 nodelay;
            proxy_pass http://app;
        }

        # MCP server endpoint (if exposed via proxy)
        location /mcp/ {
            limit_req zone=api burst=10 nodelay;
            proxy_pass http://app:3001/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_cache_bypass $http_upgrade;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://app;
            access_log off;
        }

        # Static files (if served by nginx)
        location /static/ {
            alias /app/public/;
            expires 1y;
            add_header Cache-Control "public, immutable";
        }

        # Main application
        location / {
            proxy_pass http://app;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection 'upgrade';
            proxy_cache_bypass $http_upgrade;
        }
    }
}
```

## Observability and Monitoring

### OpenTelemetry Integration

#### Tracing Configuration
```typescript
// src/observability/tracing.ts
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { JaegerExporter } from '@opentelemetry/exporter-jaeger';

const sdk = new NodeSDK({
  traceExporter: new JaegerExporter({
    endpoint: process.env.JAEGER_ENDPOINT || 'http://localhost:14268/api/traces',
  }),
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();
```

#### Custom Metrics
```typescript
// src/observability/metrics.ts
import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('personal-crm', '1.0.0');

export const contactsCreated = meter.createCounter('contacts_created_total', {
  description: 'Total number of contacts created',
});

export const syncOperations = meter.createHistogram('sync_operation_duration', {
  description: 'Duration of sync operations',
  unit: 'ms',
});

export const mcpToolCalls = meter.createCounter('mcp_tool_calls_total', {
  description: 'Total number of MCP tool calls',
});

export const mcpToolDuration = meter.createHistogram('mcp_tool_duration', {
  description: 'Duration of MCP tool executions',
  unit: 'ms',
});
```

### Logging Configuration
```typescript
// src/observability/logger.ts
import winston from 'winston';

export const logger = winston.createLogger({
  level: process.env.LOG_LEVEL || 'info',
  format: winston.format.combine(
    winston.format.timestamp(),
    winston.format.errors({ stack: true }),
    winston.format.json()
  ),
  defaultMeta: { service: 'personal-crm' },
  transports: [
    new winston.transports.File({ filename: 'logs/error.log', level: 'error' }),
    new winston.transports.File({ filename: 'logs/combined.log' }),
    new winston.transports.Console({
      format: winston.format.simple()
    })
  ],
});
```

### Health Checks
```typescript
// src/api/health.ts
import { Request, Response } from 'express';
import { database } from '../database';

export async function healthCheck(req: Request, res: Response) {
  const health = {
    status: 'healthy',
    timestamp: new Date().toISOString(),
    checks: {
      database: await checkDatabase(),
      memory: checkMemory(),
      uptime: process.uptime(),
    }
  };

  const isHealthy = Object.values(health.checks).every(check =>
    typeof check === 'object' ? check.status === 'healthy' : true
  );

  res.status(isHealthy ? 200 : 503).json(health);
}

async function checkDatabase() {
  try {
    await database.raw('SELECT 1');
    return { status: 'healthy' };
  } catch (error) {
    return { status: 'unhealthy', error: error.message };
  }
}

function checkMemory() {
  const usage = process.memoryUsage();
  return {
    status: usage.heapUsed < 500 * 1024 * 1024 ? 'healthy' : 'warning',
    heapUsed: usage.heapUsed,
    heapTotal: usage.heapTotal,
  };
}
```

## Environment Configuration

### Environment Variables
```bash
# Application
NODE_ENV=production
PORT=3000
DATABASE_PATH=/app/data/production.db

# Authentication
JWT_SECRET=your-jwt-secret
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# External Services
IMMICH_API_URL=https://your-immich-instance.com
IMMICH_API_KEY=your-immich-api-key

# MCP Server
MCP_PORT=3001
MCP_HOST=localhost

# Observability
LOG_LEVEL=info
JAEGER_ENDPOINT=http://jaeger:14268/api/traces
PROMETHEUS_ENDPOINT=http://prometheus:9090

# Security
CORS_ORIGIN=https://your-domain.com
RATE_LIMIT_WINDOW_MS=900000
RATE_LIMIT_MAX_REQUESTS=100
```

### Configuration Management
```typescript
// src/config/index.ts
import { z } from 'zod';

const configSchema = z.object({
  nodeEnv: z.enum(['development', 'test', 'production']),
  port: z.coerce.number().default(3000),
  databasePath: z.string(),
  jwtSecret: z.string(),
  google: z.object({
    clientId: z.string(),
    clientSecret: z.string(),
  }),
  immich: z.object({
    apiUrl: z.string().url(),
    apiKey: z.string(),
  }),
  mcp: z.object({
    port: z.coerce.number().default(3001),
    host: z.string().default('localhost'),
  }),
});

export const config = configSchema.parse({
  nodeEnv: process.env.NODE_ENV,
  port: process.env.PORT,
  databasePath: process.env.DATABASE_PATH,
  jwtSecret: process.env.JWT_SECRET,
  google: {
    clientId: process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CLIENT_SECRET,
  },
  immich: {
    apiUrl: process.env.IMMICH_API_URL,
    apiKey: process.env.IMMICH_API_KEY,
  },
  mcp: {
    port: process.env.MCP_PORT,
    host: process.env.MCP_HOST,
  },
});
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
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '24'
          cache: 'npm'

      - run: npm ci
      - run: npm run lint
      - run: npm run test
      - run: npm run build

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'

    steps:
      - uses: actions/checkout@v4

      - name: Deploy to production
        run: |
          # Deploy using your preferred method
          # Docker, SSH, or cloud provider CLI
```

## Backup and Recovery

### Database Backup Strategy
```bash
#!/bin/bash
# scripts/backup.sh

BACKUP_DIR="/backup"
DB_PATH="/app/data/production.db"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup-$TIMESTAMP.db"

# Create backup
cp "$DB_PATH" "$BACKUP_FILE"

# Compress backup
gzip "$BACKUP_FILE"

# Clean old backups (keep 30 days)
find "$BACKUP_DIR" -name "*.db.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE.gz"
```

### Recovery Procedures
1. **Database Recovery**: Restore from latest backup
2. **Configuration Recovery**: Restore environment variables
3. **Container Recovery**: Restart containers with health checks
4. **Data Validation**: Verify data integrity after recovery

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - Application architecture being deployed
- [Technology Stack](./technology-stack.md) - Technologies used in deployment
- [Security & Performance](./security-performance.md) - Security and performance in production
