# Frontend Dockerfile - Next.js
FROM node:24-alpine AS base

# Install pnpm
RUN npm install -g pnpm@9.12.0

# Set working directory
WORKDIR /app

# Copy package files for dependency installation
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source code
COPY frontend/ .

# Build application
RUN pnpm build

# Production stage
FROM node:24-alpine AS production

# Install curl, pnpm, and create app user
RUN apk add --no-cache curl \
    && npm install -g pnpm@9.12.0 \
    && addgroup -g 1001 -S nodejs \
    && adduser -S frontend -u 1001

# Set working directory
WORKDIR /app

# Copy package files
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# Install production dependencies only
RUN pnpm install --frozen-lockfile --prod

# Copy scripts and set permissions as root
COPY docker/frontend/start.sh /start.sh
COPY docker/frontend/healthcheck.sh /healthcheck.sh
RUN chmod +x /start.sh /healthcheck.sh

# Copy built application (standalone mode in Docker/Linux)
COPY --from=base --chown=frontend:nodejs /app/.next/standalone ./
COPY --from=base --chown=frontend:nodejs /app/.next/static ./.next/static
COPY --from=base --chown=frontend:nodejs /app/public ./public

# Switch to non-root user
USER frontend

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["/healthcheck.sh"]
CMD ["/start.sh"]
