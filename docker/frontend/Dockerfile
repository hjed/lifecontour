# Unified Frontend Dockerfile - Next.js
# Supports both development and production builds via build args

FROM node:24-alpine AS base

# Build arguments
ARG BUILD_ENV=production
ARG NODE_ENV=production

# Install curl and pnpm
RUN apk add --no-cache curl && \
    npm install -g pnpm

# Create app user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S frontend -u 1001

# Set working directory
WORKDIR /app

# Copy package files for dependency installation
COPY frontend/package.json frontend/pnpm-lock.yaml* ./

# Install dependencies - always install all dependencies for build process
# Temporarily unset NODE_ENV to ensure dev dependencies are installed
RUN unset NODE_ENV && \
    echo "Installing all dependencies..." && \
    pnpm install --frozen-lockfile

# Copy application code
COPY frontend/ .

# Build application for production (skip in development)
RUN if [ "$BUILD_ENV" = "production" ]; then \
        echo "Building application for production..." && \
        pnpm build; \
    else \
        echo "Skipping build for development mode..." && \
        mkdir -p .next; \
    fi

# Copy startup scripts
COPY docker/frontend/start.sh /start.sh
COPY docker/frontend/healthcheck.sh /healthcheck.sh
RUN chmod +x /start.sh /healthcheck.sh

# Set proper permissions
RUN chown -R frontend:nodejs /app

# Switch to non-root user
USER frontend

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["/healthcheck.sh"]

# Default command (can be overridden in docker-compose)
CMD if [ "$NODE_ENV" = "development" ]; then \
        pnpm dev; \
    else \
        /start.sh; \
    fi
