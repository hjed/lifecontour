# Frontend Dockerfile - Next.js
FROM node:24-alpine AS base

# Install pnpm
RUN npm install -g pnpm@9.12.0

# Set working directory
WORKDIR /app

# Copy package files for dependency installation
COPY package.json ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source code
COPY . .

# Build application
RUN pnpm build

# Production stage
FROM node:24-alpine AS production

# Install curl for healthcheck
RUN apk add --no-cache curl

# Install pnpm
RUN npm install -g pnpm@9.12.0

# Create app user
RUN addgroup -g 1001 -S nodejs && \
    adduser -S frontend -u 1001

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json ./

# Install production dependencies only
RUN pnpm install --frozen-lockfile --prod

# Copy built application
COPY --from=base --chown=frontend:nodejs /app/.next/standalone ./
COPY --from=base --chown=frontend:nodejs /app/.next/static ./.next/static
COPY --from=base --chown=frontend:nodejs /app/public ./public

# Switch to non-root user
USER frontend

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD curl -f http://localhost:3000 || exit 1

# Start the application
CMD ["node", "server.js"]
