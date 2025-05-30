# Backend Dockerfile
FROM node:24-alpine AS base

# Install pnpm
RUN npm install -g pnpm@9.12.0

# Set working directory
WORKDIR /app

# Copy package files for dependency installation
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/shared/package.json ./packages/shared/
COPY packages/database/package.json ./packages/database/
COPY apps/backend/package.json ./apps/backend/

# Install dependencies
RUN pnpm install --frozen-lockfile --prod=false

# Copy source code
COPY packages/shared ./packages/shared
COPY packages/database ./packages/database
COPY apps/backend ./apps/backend
COPY tsconfig.json ./

# Build shared packages first
RUN pnpm --filter @personal-management/shared build
RUN pnpm --filter @personal-management/database build

# Build backend
RUN pnpm --filter @personal-management/backend build

# Production stage
FROM node:24-alpine AS production

# Install pnpm and curl for healthcheck
RUN npm install -g pnpm@9.12.0 && \
    apk add --no-cache curl

# Create app user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S backend -u 1001

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json pnpm-workspace.yaml ./
COPY packages/shared/package.json ./packages/shared/
COPY packages/database/package.json ./packages/database/
COPY apps/backend/package.json ./apps/backend/

# Install production dependencies only
RUN pnpm install --frozen-lockfile --prod

# Copy built application
COPY --from=base --chown=backend:nodejs /app/packages/shared/dist ./packages/shared/dist
COPY --from=base --chown=backend:nodejs /app/packages/database/dist ./packages/database/dist
COPY --from=base --chown=backend:nodejs /app/apps/backend/dist ./apps/backend/dist

# Create data directory for SQLite database
RUN mkdir -p /data && chown backend:nodejs /data

# Switch to non-root user
USER backend

# Expose port
EXPOSE 3001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:3001/health || exit 1

# Start the application
CMD ["node", "apps/backend/dist/index.js"]
