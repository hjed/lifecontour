---
name: running-e2e-tests
description: How to run Playwright E2E tests locally with workspace-isolated Docker services and ports.
---

# Running Playwright E2E Tests Locally

E2E tests (`frontend/tests/e2e/`) use Playwright to test the full stack: Frontend (Next.js) → Backend (FastAPI) → PostgreSQL, Redis, MeiliSearch, and OAuth (Hydra). The test infrastructure uses `scripts/workspace_env.py` to derive workspace-specific ports so multiple checkouts don't conflict.

## How It Works (Automatic Mode)

Playwright's `globalSetup` (`frontend/tests/global-setup.ts`) is **self-contained** — it will:

1. Load workspace-specific ports from `scripts/workspace_env.py` via `frontend/tests/e2e/utils/frontend-test-config.ts`
2. Check if the full `test` Docker profile is already running with correct config
3. Start/restart Docker containers if needed (including Backend, OAuth, Workers)
4. Wait for all services to be healthy (Backend API, OAuth, MeiliSearch)
5. Playwright then starts its own frontend dev server on the workspace-specific port

### Just Run the Tests

```bash
# From the frontend directory
cd frontend
pnpm exec playwright test
```

That's it. The global setup handles Docker orchestration automatically.

### Running Specific Tests

```bash
cd frontend

# Run a specific test file
pnpm exec playwright test tests/e2e/contacts.spec.ts

# Run a specific test by name
pnpm exec playwright test -g "should create a new contact"

# Run a specific browser only (projects: firefox, "Mobile Chrome")
pnpm exec playwright test --project=firefox

# Run with UI mode for debugging
pnpm exec playwright test --ui

# Run with headed browser
pnpm exec playwright test --headed
```

### Repeating Tests (Flakiness Detection)

```bash
cd frontend
pnpm exec playwright test --repeat-each 5 tests/e2e/contacts.spec.ts
```

## Pre-Starting Docker (Optional, Faster Iteration)

If you want to keep Docker containers running across multiple test runs:

```bash
# From the project root
eval "$(python3 scripts/workspace_env.py export)"

# Build the workspace-specific docker environment
export OAUTH_CONSENT_URL="http://localhost:${OAUTH_UI_TEST_PORT:-3002}/consent"
export OAUTH_LOGIN_URL="http://localhost:${OAUTH_UI_TEST_PORT:-3002}/login"
export OAUTH_AUTHORIZATION_URL="http://localhost:${OAUTH_PUBLIC_TEST_PORT:-4446}/oauth2/auth"
export OAUTH_ISSUER="http://localhost:${OAUTH_PUBLIC_TEST_PORT:-4446}"
export FRONTEND_URL="http://localhost:${FRONTEND_TEST_PORT:-3100}"
export CORS_ORIGINS="http://localhost:${FRONTEND_TEST_PORT:-3100},http://127.0.0.1:${FRONTEND_TEST_PORT:-3100},http://frontend:3000"

docker compose --profile test --env-file .env.test up -d --build
```

When services are already running with the correct configuration, the global setup will detect them and skip startup (much faster).

### Reusing an Already-Running Frontend

If you already have a frontend dev server running on the test port:

```bash
PLAYWRIGHT_REUSE_EXISTING_SERVER=true pnpm exec playwright test
```

## Port Resolution

All ports are derived from `scripts/workspace_env.py` and loaded by `frontend/tests/e2e/utils/frontend-test-config.ts`:

| Variable | Default (offset 0) | Description |
|----------|-------------------|-------------|
| `FRONTEND_TEST_PORT` | 3100 | Next.js dev server |
| `BACKEND_TEST_PORT` | 8001 | FastAPI backend |
| `DB_TEST_PORT` | 5433 | PostgreSQL |
| `MEILI_TEST_PORT` | 7701 | MeiliSearch |
| `REDIS_TEST_PORT` | 6380 | Redis |
| `OAUTH_PUBLIC_TEST_PORT` | 4446 | Hydra public |
| `OAUTH_ADMIN_TEST_PORT` | 4447 | Hydra admin |
| `OAUTH_UI_TEST_PORT` | 3002 | OAuth login/consent UI |

Each workspace adds a unique offset (derived from the workspace path hash × 10) to all ports.

## Docker Profile: `test`

The E2E tests use the `test` profile which starts **all** services:

- PostgreSQL, Redis, MeiliSearch (infrastructure)
- Backend API (FastAPI in Docker)
- OAuth provider (Hydra) + login/consent UI + init
- Google worker

This is heavier than the `test-backend` profile used by backend integration tests.

## Stopping Docker Services

```bash
# From the project root — tears down every profile for this worktree
python3 scripts/teardown_workspace.py
```

`teardown_workspace.py` resolves this worktree's `pms_test_<N>` project itself,
runs `docker compose down --volumes --remove-orphans` across all profiles, then
sweeps any container, volume or network still labelled with that project. It
never touches the shared `personal-management` network or another worktree's
containers. Add `--keep-volumes` to preserve data between runs, or `--dry-run`
to see what it would remove.

Use it on **worktree cleanup** too — it takes the worktree path as an argument
and works after that directory has been deleted:

```bash
python3 /path/to/any/checkout/scripts/teardown_workspace.py /path/to/removed/worktree

# or sweep every workspace project whose worktree no longer exists
python3 scripts/teardown_workspace.py --prune-stale
```

The equivalent raw command, if you need it:

```bash
eval "$(python3 scripts/workspace_env.py export)"
docker compose --profile test --env-file .env.test down -v
```

## Key Files

| File | Purpose |
|------|---------|
| `scripts/workspace_env.py` | Derives workspace-specific ports and container prefix |
| `frontend/tests/e2e/utils/frontend-test-config.ts` | Loads workspace env and exports port constants |
| `frontend/tests/global-setup.ts` | Orchestrates Docker startup and health checks |
| `frontend/tests/global-teardown.ts` | Cleanup after tests |
| `frontend/playwright.config.ts` | Playwright configuration, web server, browser projects |
| `.env.test` | Base environment variables for Docker test profile |

## Common Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Service failed to start after 120 attempts` | Docker services didn't become healthy in time | Check `docker compose --profile test logs --tail=50` for errors. Common cause: port conflict. |
| `ECONNREFUSED` on backend port | Backend container not running or unhealthy | Check `docker ps` and `docker logs <prefix>-backend` |
| OAuth redirect mismatch | Frontend URL changed but OAuth client wasn't re-initialized | The global setup detects this and restarts services. If stuck, run `docker compose --profile test down -v` and re-run. |
| `Port already in use` | Another process (e.g. dev server) on the same port | The workspace offset should prevent this across checkouts. Kill conflicting processes or stop other Docker profiles. |
| Tests timeout on CI | GitHub Actions services are separate | In CI, set `CI=true` — the global setup skips Docker management and just verifies health. |
| Frontend dev server fails to start | Missing dependencies | Run `pnpm install` in `frontend/` first |
| Stale containers from wrong profile | Switching between dev/test profiles | Run `eval "$(python3 scripts/workspace_env.py export)" && docker compose --profile test down --remove-orphans -v` |
