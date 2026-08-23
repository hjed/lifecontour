---
name: running-worker-integration-tests
description: How to configure and run integration worker (e.g. Google) integration tests locally against the correct Docker containers and ports.
---

# Running Integration Worker Integration Tests Locally

When working on integration workers (e.g., `integration_workers/google`), integration tests run against a real PostgreSQL database. The `conftest.py` in each worker already calls `scripts/workspace_env.py` to derive workspace-specific ports, so **no manual port discovery is needed**.

## How Port Resolution Works

Each worker's `tests/integration/conftest.py` calls `scripts/workspace_env.py` at import time to get workspace-specific ports (e.g. `DB_TEST_PORT`). The conftest builds a database URL from these values and falls back to environment variable overrides (`DATABASE_URL`) if set.

## 1. Start Docker Services (if not already running)

The worker integration tests need only PostgreSQL and Redis. Use the `test-backend` profile with workspace-derived environment variables:

```bash
# From the project root
eval "$(python3 scripts/workspace_env.py export)"
docker compose --profile test-backend --env-file .env.test up -d
```

This starts containers with workspace-specific port bindings (e.g. `pms_test_48-postgres` on port `5913`) that won't conflict with other workspace checkouts.

If the containers are already running from a previous test run or from running backend integration tests, you can skip this step. Verify with:

```bash
docker ps --filter "name=$(python3 scripts/workspace_env.py CONTAINER_PREFIX)-postgres" --format "{{.Names}}"
```

## 2. Run the Tests

Execute the tests from the worker directory using `uv run pytest`:

```bash
# From the project root
cd integration_workers/google
uv run pytest tests/integration/ -v
```

The `conftest.py` will:
1. Resolve the correct DB port via `workspace_env.py`
2. Run Alembic migrations against the test database automatically
3. Use savepoint-based isolation so each test rolls back its changes

### Running a Single Test

```bash
cd integration_workers/google
uv run pytest tests/integration/test_sync_calendar_events_integration.py -v -k "test_name"
```

## 3. Stopping Docker Services

If you started the containers specifically for these tests and want to clean up:

```bash
# From the project root — tears down every profile for this worktree
python3 scripts/teardown_workspace.py
```

`teardown_workspace.py` resolves this worktree's `pms_test_<N>` compose project,
brings it down across all profiles and sweeps anything left over. Pass
`--keep-volumes` to preserve data, or `--dry-run` to preview.

> **Note:** If the `test` or `test-backend` profile containers were started by another test suite (e.g. backend integration tests), they share the same Docker containers. Only stop them when you're finished with all testing.

The equivalent raw command, if you need it:

```bash
eval "$(python3 scripts/workspace_env.py export)"
docker compose --profile test-backend --env-file .env.test down -v
```

## Common Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `OperationalError: could not connect to server` | Docker containers not running | Run step 1 |
| `InFailedSQLTransactionError` | Stale/partially-migrated test DB | Drop and recreate: `docker exec <container> dropdb -U postgres personal_management_test && docker exec <container> createdb -U postgres personal_management_test` |
| `UndefinedColumnError` | Migration/schema mismatch | Run `uv run alembic upgrade head` from `backend/` with correct `DATABASE_URL` |
| Port conflict with another workspace | Two checkouts using same ports | This shouldn't happen — `workspace_env.py` hashes the workspace path to derive unique ports. If it does, check both workspaces' `python3 scripts/workspace_env.py json` output. |

