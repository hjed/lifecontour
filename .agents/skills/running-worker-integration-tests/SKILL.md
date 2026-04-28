---
name: running-worker-integration-tests
description: How to configure and run Python backend integration tests locally against the correct Docker containers and ports.
---

# Running Python Worker Integration Tests Locally

When working on integration workers (e.g., `integration_workers/google`), you must run integration tests against a real PostgreSQL database and Redis instance to guarantee correctness.

However, default configurations in test files like `tests/conftest.py` often override connection strings to default ports (e.g., `5432` for Postgres, `6379` for Redis), which may not match your local Docker environment's dynamic port mappings (e.g., due to different profiles running simultaneously).

Follow these exact steps to run integration tests successfully without `OperationalError` or `ConnectionError`.

## 1. Identify Running Containers and Ports

First, find the ports mapped for your active test backend profile using Docker.

```bash
docker ps | grep pms_test
```

Look for containers like:
- `pms_test_XX-postgres` (Identify the host port mapped to `5432/tcp`)
- `pms_test_XX-redis` (Identify the host port mapped to `6379/tcp`)

*Example Output:*
```text
32e33ee9e6c2   postgres:18-alpine   ...   0.0.0.0:5913->5432/tcp   pms_test_48-postgres
122494b3d906   redis:8-alpine       ...   0.0.0.0:6860->6379/tcp   pms_test_48-redis
```
*In this example, Postgres is on port `5913` and Redis is on port `6860`.*

## 2. Ensure the Test Database Exists

The tests typically run against the `personal_management_test` database. If it is corrupted or missing, create (or drop and recreate) it inside your specific Postgres container.

```bash
# Drop the database if recreating from a corrupted state (optional)
docker exec pms_test_XX-postgres dropdb -U postgres personal_management_test || true

# Create the test database
docker exec pms_test_XX-postgres createdb -U postgres personal_management_test
```

*Note: If you want to use a totally fresh database without conflicting with existing test states, you can create a custom database name like `personal_management_test2` and use it in Step 3.*

## 3. Export Environment Variables

Because some `conftest.py` files use `os.environ.setdefault(...)`, you **MUST** export the variables in your shell *before* invoking `pytest` so they are not overwritten by the defaults.

Using the ports discovered in Step 1:

```bash
# Replace <PG_PORT> with your Postgres port and <REDIS_PORT> with your Redis port
# Replace the database name if using a custom one (e.g. personal_management_test2)

export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:<PG_PORT>/personal_management_test"
export DB_TEST_PORT="<PG_PORT>"

export REDIS_URL="redis://localhost:<REDIS_PORT>"
export REDIS_PORT="<REDIS_PORT>"
```

## 4. Run the Tests

Execute the tests from the worker directory using `uv run pytest`.

```bash
cd integration_workers/<worker-name>
uv run pytest tests/integration/
```

### Common Troubleshooting

- **`InFailedSQLTransactionError`**: Ensure your test database schema is cleanly generated. If you encounter missing tables/columns, your database migrations might be out of sync. Drop the DB and run Alembic `upgrade head`, or let the tests handle migrations on a fresh test DB.
- **`UndefinedColumnError`**: An SQL query manually referencing a column that doesn't exist (or no longer exists) in the schema migrations. Review the query and the migrations to ensure alignment.
- **`redis connection error localhost:6379`**: You did not correctly export `REDIS_URL` and `REDIS_PORT`. Ensure both are exported before running the tests.
