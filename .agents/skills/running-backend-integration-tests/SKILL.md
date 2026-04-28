---
name: running-backend-integration-tests
description: How to run Python backend integration tests locally against Docker PostgreSQL, Redis, and MeiliSearch with workspace-isolated ports.
---

# Running Backend Integration Tests Locally

Backend integration tests (`backend/tests/integration/`) run against real PostgreSQL, Redis, and MeiliSearch instances via Docker. The test infrastructure automatically handles Docker lifecycle and port resolution using `scripts/workspace_env.py`.

## How It Works (Automatic Mode)

The backend `tests/integration/conftest.py` is **self-contained** — it will:

1. Call `scripts/workspace_env.py` at import time to derive workspace-specific ports
2. Check if the `test-backend` Docker profile is already running
3. Start Docker containers if needed (using `docker compose --profile test-backend`)
4. Wait for PostgreSQL to be healthy
5. Reset and re-migrate the test database (`personal_management_test`)
6. Stop containers after the test session (unless they were already running)

### Just Run the Tests

```bash
# From the project root
cd backend
uv run pytest tests/integration/ -v
```

That's it. The conftest handles everything.

### Running Specific Tests

```bash
cd backend
uv run pytest tests/integration/contacts/ -v
uv run pytest tests/integration/contacts/test_contact_service_integration.py -v -k "test_name"
```

## Pre-Starting Docker (Optional)

If you want to keep Docker containers running across multiple test runs (faster iteration), start them manually:

```bash
# From the project root
eval "$(python3 scripts/workspace_env.py export)"
docker compose --profile test-backend --env-file .env.test up -d
```

When containers are already running, the conftest will detect them and skip the startup/teardown steps. It will still reset and re-migrate the test database each session to ensure a clean state.

### Verifying Containers Are Running

```bash
docker ps --filter "name=$(python3 scripts/workspace_env.py CONTAINER_PREFIX)" --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
```

## Port Resolution

The conftest resolves ports in this priority order:

1. **Environment variables** (`TEST_DB_PORT`, `REDIS_URL`, `MEILISEARCH_URL`) — if explicitly set
2. **`workspace_env.py`** output (`DB_TEST_PORT`, `REDIS_TEST_PORT`, `MEILI_TEST_PORT`) — the default
3. **Hardcoded fallbacks** (`5433`, `6380`, `7701`) — last resort

You should **never need to set ports manually** in normal development. The `workspace_env.py` script hashes the workspace absolute path to derive a unique port offset, so multiple workspace checkouts will not conflict.

## Docker Profiles

| Profile | Services | Use Case |
|---------|----------|----------|
| `test-backend` | PostgreSQL, Redis, MeiliSearch | Backend integration tests only (lightweight) |
| `test` | All of `test-backend` + Backend API, OAuth, Google Worker | E2E tests (full stack) |

The backend integration tests use `test-backend` which is faster to start since it only runs the infrastructure services.

## Stopping Docker Services

```bash
# From the project root
eval "$(python3 scripts/workspace_env.py export)"
docker compose --profile test-backend --env-file .env.test down -v
```

> **Note:** The `-v` flag removes volumes. Omit it if you want to preserve data between runs (e.g. to avoid re-running migrations).

## Common Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `OperationalError: could not connect` | Docker not running | The conftest should auto-start. If it fails, run `docker compose --profile test-backend --env-file .env.test up -d` manually with workspace env exported. |
| `DuplicateTable` during migrations | Partially-migrated DB from a crashed session | The conftest resets the DB each session. If still occurring, manually drop: `docker exec <prefix>-postgres dropdb -U postgres personal_management_test` |
| Tests use wrong port | Stale environment variable overriding `workspace_env.py` | Unset `DATABASE_URL`, `TEST_DB_PORT`, `REDIS_URL` from your shell |
| `psycopg2` import error | Missing dev dependency | Run `uv sync` in `backend/` |
| Container name conflict | Dev profile containers using same names | The workspace prefix (`pms_test_XX`) should prevent this. If not, stop dev containers first: `docker compose --profile dev down` |
