# Docker Troubleshooting and Fixes

This document contains solutions to common Docker-related issues encountered during development and CI/CD.

## Frontend Docker Build Issues

### Problem: Frontend Container Startup Failure

**Error:**
```
Error: Cannot find module '/app/server.js'
```

**Root Cause:**
The frontend Docker container was trying to run `node server.js` instead of Next.js commands.

**Solution:**
Updated `docker/frontend/start.sh` to use Next.js commands:

```bash
#!/bin/sh
set -e

# Start the Next.js application in production mode
exec pnpm start
```

### Problem: Frontend Build Failing in Docker

**Error:**
```
Error: Cannot find module '@tailwindcss/postcss'
Failed to compile.
```

**Root Cause:**
The Dockerfile was installing only production dependencies (`pnpm install --prod`) but the build process requires dev dependencies like Tailwind CSS.

**Solution:**
Updated `docker/frontend/Dockerfile` to install all dependencies for builds:

```dockerfile
# Install dependencies - always install all dependencies for build process
# Temporarily unset NODE_ENV to ensure dev dependencies are installed
RUN unset NODE_ENV && \
    echo "Installing all dependencies..." && \
    pnpm install --frozen-lockfile
```

### Problem: Development vs Production Mode Issues

**Root Cause:**
The Dockerfile's CMD instruction was using `BUILD_ENV` (build-time argument) to make runtime decisions, but `BUILD_ENV` is not available at container runtime.

**Solution:**
Updated the CMD to use `NODE_ENV` (runtime environment variable):

```dockerfile
CMD if [ "$NODE_ENV" = "development" ]; then \
        pnpm dev; \
    else \
        /start.sh; \
    fi
```

## CI/CD Docker Issues

### Problem: Docker Build Test Failures in CI

**Error:**
CI workflows failing on Docker build steps in both `build-test` and `docker-security` jobs.

**Root Cause:**
Frontend Docker builds were failing due to missing dev dependencies during the build process.

**Solution:**
Applied the frontend Docker fixes above, which resolved:
- ✅ Backend Docker Build: `Successfully built cf4cc23b58b3`
- ✅ Frontend Docker Build: `Successfully built ed7e28ec665c`
- ✅ CI Build Test Commands: Both docker build commands now work
- ✅ CI Security Test Commands: Docker images build successfully for Trivy scanning

## Precommit Hook Issues

### Problem: End-of-File Fixer Permission Errors

**Error:**
```
end-of-file-fixer failed: Permission denied writing to docker/oauth-ui/package-lock.json
```

**Root Cause:**
The file was owned by `root:root` (created by Docker container) but the current user didn't have write permissions.

**Solution:**
Excluded the problematic file from the end-of-file-fixer hook:

```yaml
- id: end-of-file-fixer
  exclude: ^docker/oauth-ui/package-lock\.json$
```

## Development Environment Issues

### Problem: Port Conflicts

**Error:**
```
Error starting userland proxy: listen tcp4 0.0.0.0:3000: bind: address already in use
```

**Solution:**
```bash
# Check what's using the ports
lsof -i :3000  # Frontend
lsof -i :8000  # Backend
lsof -i :5432  # Database

# Stop conflicting services or change ports in docker-compose.dev.yml
```

### Problem: Database Connection Issues

**Error:**
```
Connection refused to database
```

**Solution:**
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

### Problem: Volume Mount Issues

**Error:**
Code changes not reflected in containers.

**Solution:**
Ensure proper volume mounts in `docker-compose.dev.yml`:

```yaml
volumes:
  - ./backend:/app
  - ./frontend:/app
  - /app/node_modules  # Exclude node_modules
```

## Performance Issues

### Problem: Slow Docker Builds

**Solution:**
1. Use `.dockerignore` files to exclude unnecessary files
2. Leverage Docker layer caching
3. Use multi-stage builds for production images
4. Consider using Docker BuildKit for faster builds

### Problem: Large Image Sizes

**Solution:**
1. Use Alpine-based images where possible
2. Remove unnecessary packages after installation
3. Use multi-stage builds to exclude build dependencies
4. Clean up package manager caches

## Security Issues

### Problem: Running as Root User

**Solution:**
Both Dockerfiles create non-root users:

```dockerfile
# Backend
RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser

# Frontend
RUN addgroup -g 1001 -S nodejs && adduser -S frontend -u 1001
USER frontend
```

### Problem: Exposed Secrets

**Solution:**
1. Use environment variables for secrets
2. Never include secrets in Dockerfiles
3. Use Docker secrets in production
4. Scan images with Trivy for vulnerabilities

## Best Practices

### Docker Development

1. **Use specific tags** instead of `latest` for base images
2. **Implement health checks** for all services
3. **Use multi-stage builds** for production optimization
4. **Leverage build cache** by ordering Dockerfile instructions properly
5. **Use .dockerignore** to exclude unnecessary files

### CI/CD Integration

1. **Test Docker builds** in CI before deployment
2. **Scan images** for security vulnerabilities
3. **Use consistent environments** between development and production
4. **Cache Docker layers** in CI for faster builds

### Troubleshooting Commands

```bash
# View container logs
docker logs <container_name>

# Execute commands in running container
docker exec -it <container_name> /bin/sh

# Inspect container configuration
docker inspect <container_name>

# View container resource usage
docker stats

# Clean up unused resources
docker system prune -a
```

## Related Documentation

- [Docker Development Environment](docker-development.md) - Complete Docker setup guide
- [CI/CD Setup](../ci-cd-setup.md) - Continuous integration configuration
- [Deployment Guide](../architecture/deployment-guide.md) - Production deployment
- [Code Quality Standards](../code-quality-standards.md) - Development standards
