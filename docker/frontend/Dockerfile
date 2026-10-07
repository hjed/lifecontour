# Frontend Dockerfile - Next.js
#
# Stages:
#   development - full source and dependencies, runs `pnpm dev` (docker-compose)
#   runner      - the default (last) stage, published by release.yml: Next.js
#                 standalone output only. It ships no .next/cache (which holds
#                 copies of the build-generated keys), no dev dependencies and
#                 no pnpm store.

FROM node:26-alpine AS base

# Node 26 no longer bundles corepack, so pnpm is installed directly via npm.
# Keep this version in sync with the "packageManager" field in
# frontend/package.json.
RUN apk add --no-cache curl && \
    npm install -g --ignore-scripts pnpm@11.7.0

RUN addgroup -g 1001 -S nodejs && \
    adduser -S frontend -u 1001

WORKDIR /app

# ---------------------------------------------------------------------------
FROM base AS deps

COPY frontend/package.json frontend/pnpm-lock.yaml* frontend/pnpm-workspace.yaml* ./

# Dev dependencies are needed to build; they never reach the runner stage.
RUN pnpm install --frozen-lockfile

# ---------------------------------------------------------------------------
FROM deps AS development

ENV NODE_ENV=development

COPY frontend/ .
COPY docker/frontend/healthcheck.sh /healthcheck.sh
RUN mkdir -p .next && chown -R frontend:nodejs /app && chmod +x /healthcheck.sh

USER frontend
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["/healthcheck.sh"]
CMD ["pnpm", "dev"]

# ---------------------------------------------------------------------------
FROM deps AS builder

ENV NODE_ENV=production

COPY frontend/ .
# prebuild writes public/third-party-notices.txt; next.config.mjs selects
# `output: "standalone"`.
RUN pnpm build

# ---------------------------------------------------------------------------
FROM node:26-alpine AS runner

# Docker sets HOSTNAME to the container ID, and server.js binds to HOSTNAME.
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apk add --no-cache curl && \
    addgroup -g 1001 -S nodejs && \
    adduser -S frontend -u 1001

WORKDIR /app

COPY --from=builder --chown=frontend:nodejs /app/public ./public
COPY --from=builder --chown=frontend:nodejs /app/.next/standalone ./
COPY --from=builder --chown=frontend:nodejs /app/.next/static ./.next/static

COPY docker/frontend/start.sh /start.sh
COPY docker/frontend/healthcheck.sh /healthcheck.sh
RUN chmod +x /start.sh /healthcheck.sh

USER frontend
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD ["/healthcheck.sh"]

CMD ["/start.sh"]
