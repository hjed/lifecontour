# Docker Image Rebuild Guide

This guide explains how to rebuild Docker images for the Personal Management System, especially useful during development when dependencies or configurations change.

## Why Rebuild Docker Images?

Docker images should be rebuilt when:

- **Dependencies change**: After modifying `pyproject.toml`, `package.json`, or `uv.lock`/`pnpm-lock.yaml`
- **Dockerfile changes**: When Docker configuration files are modified
- **Base image updates**: To get security updates from base images
- **Cache issues**: When experiencing problems with stale cached layers
- **Development issues**: When containers behave unexpectedly

## Quick Commands

### Linux/macOS (Bash)

```bash
# Rebuild all development images
./scripts/dev.sh docker-rebuild

# Rebuild all production images
./scripts/dev.sh docker-rebuild-prod

# Rebuild specific service
./scripts/dev.sh docker-rebuild-service backend-dev

# View available commands
./scripts/dev.sh help
```

### Windows (PowerShell)

```powershell
# Rebuild all development images
.\scripts\dev.ps1 docker-rebuild

# Rebuild all production images
.\scripts\dev.ps1 docker-rebuild-prod

# Rebuild specific service
.\scripts\dev.ps1 docker-rebuild-service backend-dev

# View available commands
.\scripts\dev.ps1 help
```

### Windows (Batch - Simplified)

```cmd
# Rebuild all development images
scripts\rebuild-docker.bat dev

# Rebuild all production images
scripts\rebuild-docker.bat prod

# Rebuild specific service
scripts\rebuild-docker.bat service backend-dev

# View available commands
scripts\rebuild-docker.bat help
```

## Available Services

### Development Services
- `backend-dev`: Python FastAPI backend with development dependencies
- `frontend-dev`: Next.js frontend with hot reload

### Production Services
- `backend`: Python FastAPI backend (production build)
- `frontend`: Next.js frontend (production build)
- `nginx`: Nginx reverse proxy

## Detailed Process

When you run a rebuild command, the following happens:

1. **Stop Services**: Existing containers are stopped to avoid conflicts
2. **Clear Cache**: Images are rebuilt with `--no-cache` flag to ensure fresh builds
3. **Rebuild**: Docker builds new images from scratch
4. **Restart**: Services are restarted with new images (for single service rebuilds)

## Common Scenarios

### After Dependency Changes

```bash
# Backend dependency changes (pyproject.toml)
./scripts/dev.sh docker-rebuild-service backend-dev

# Frontend dependency changes (package.json)
./scripts/dev.sh docker-rebuild-service frontend-dev

# Both changed
./scripts/dev.sh docker-rebuild
```

### After Git Pull

```bash
# Check what changed
git diff HEAD~1 --name-only

# If Docker files or dependencies changed
./scripts/dev.sh docker-rebuild
```

### Production Deployment

```bash
# Rebuild production images
./scripts/dev.sh docker-rebuild-prod

# Start production environment
docker-compose up -d
```

## Troubleshooting

### Build Failures

If rebuild fails:

1. **Check Docker space**: `docker system df`
2. **Clean up**: `docker system prune -a`
3. **Check logs**: Look at the build output for specific errors
4. **Verify files**: Ensure Dockerfiles and dependency files are valid

### Performance Issues

- **Use specific service rebuilds** instead of full rebuilds when possible
- **Clean Docker cache** periodically: `docker builder prune`
- **Monitor disk space**: Docker images can consume significant space

### Windows-Specific Issues

- **PowerShell execution policy**: Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- **Docker Desktop**: Ensure Docker Desktop is running
- **WSL2**: For better performance, consider using WSL2 backend

## Integration with Development Workflow

### Recommended Workflow

1. **Pull changes**: `git pull`
2. **Check for Docker changes**: Look for modified Dockerfiles or dependency files
3. **Rebuild if needed**: Use appropriate rebuild command
4. **Start development**: `./scripts/dev.sh docker-start`
5. **Develop and test**: Make your changes
6. **Test before commit**: Ensure everything works with fresh images

### CI/CD Integration

The rebuild commands are designed for local development. In CI/CD:

- Images are always built fresh (no cache reuse between builds)
- Use `docker-compose build --no-cache` directly
- Consider using multi-stage builds for optimization

## Best Practices

1. **Rebuild after dependency changes**: Always rebuild when `pyproject.toml` or `package.json` change
2. **Use specific service rebuilds**: Faster than rebuilding everything
3. **Clean up regularly**: Use `docker system prune` to free space
4. **Monitor build times**: If builds are slow, consider optimizing Dockerfiles
5. **Test after rebuilds**: Ensure functionality works with new images

## Related Documentation

- [Docker Development Guide](troubleshooting/docker-development.md)
- [Docker Fixes](troubleshooting/docker-fixes.md)
- [Development Script Guide](../scripts/dev.sh) (run with `help` argument)
