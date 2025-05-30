# Frontend Dockerfile
FROM node:24-alpine AS base

# Install pnpm
RUN npm install -g pnpm@9.12.0

# Set working directory
WORKDIR /app

# Copy package files for dependency installation
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/shared/package.json ./packages/shared/
COPY apps/frontend/package.json ./apps/frontend/

# Install dependencies
RUN pnpm install --frozen-lockfile --prod=false

# Copy source code
COPY packages/shared ./packages/shared
COPY apps/frontend ./apps/frontend
COPY tsconfig.json ./

# Build shared package first
RUN pnpm --filter @personal-management/shared build

# Build frontend
RUN pnpm --filter @personal-management/frontend build

# Production stage
FROM node:24-alpine AS production

# Install curl for healthcheck
RUN apk add --no-cache curl

# Create app user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S frontend -u 1001

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json pnpm-workspace.yaml ./
COPY apps/frontend/package.json ./apps/frontend/

# Install production dependencies only
RUN npm install -g pnpm@9.12.0 && \
    pnpm install --frozen-lockfile --prod

# Copy built application
COPY --from=base --chown=frontend:nodejs /app/apps/frontend/.next/standalone ./
COPY --from=base --chown=frontend:nodejs /app/apps/frontend/.next/static ./.next/static
COPY --from=base --chown=frontend:nodejs /app/apps/frontend/public ./public

# Switch to non-root user
USER frontend

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:3000/api/health || exit 1

# Start the application
CMD ["node", "server.js"]
