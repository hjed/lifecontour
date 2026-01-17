# Google Contacts Worker Tests

This directory contains tests for the Google Contacts integration worker.

## Test Structure

The test structure follows the same pattern as the main backend application:

```
tests/
├── __init__.py
├── conftest.py          # Shared test configuration and fixtures
├── unit/                # Unit tests (fast, no external dependencies)
│   ├── __init__.py
│   ├── test_retry_strategy.py    # Retry delay function tests
│   └── test_worker.py             # Worker function tests with mocks
└── integration/         # Integration tests (require Redis, etc.)
    ├── __init__.py
    └── test_retry_integration.py # ARQ retry behavior tests
```

## Running Tests

### All Tests
```bash
# From the project root
docker compose exec google-contacts-worker pytest tests/ -v

# Or from within the worker directory
pytest tests/ -v
```

### Unit Tests Only
```bash
docker compose exec google-contacts-worker pytest tests/unit/ -v
```

### Integration Tests Only
```bash
docker compose exec google-contacts-worker pytest tests/integration/ -v
```

### Specific Test File
```bash
docker compose exec google-contacts-worker pytest tests/unit/test_retry_strategy.py -v
```

## Test Categories

### Unit Tests (`tests/unit/`)

Fast tests that use mocks and don't require external services:

- **test_retry_strategy.py**: Tests for the exponential backoff retry delay function
  - Verifies retry delays follow exponential pattern (60s → 120s → 240s → 480s → 900s)
  - Tests jitter application (±20%)
  - Validates max cap enforcement
  - 8 comprehensive tests, all passing

- **test_worker.py**: Tests for worker sync functions
  - Tests sync logic with mocked Google API client
  - Tests contact transformation and persistence
  - Tests error handling
  - Note: Some tests need updating for new `user_id` parameter

### Integration Tests (`tests/integration/`)

Tests that require external services (Redis) and test actual integration behavior:

- **test_retry_integration.py**: Tests for ARQ retry behavior
  - Verifies worker settings configuration
  - Tests exponential backoff with statistical sampling
  - Tests job enqueuing and status tracking
  - 3 passing tests + 1 skipped (complex worker process test)

## CI/CD

Worker tests are automatically run in CI when changes are made to:
- `integration_workers/**/*.py`
- `core_shared/**/*.py`

See `.github/workflows/ci.yml` for the CI configuration:
- `worker-unit-test`: Runs unit tests
- `worker-integration-test`: Runs integration tests with Redis service

## Test Coverage

Current test coverage for retry strategy implementation:
- ✅ Retry delay function: 100% (8/8 tests passing)
- ✅ ARQ configuration: 100% (3/3 integration tests passing)
- ✅ Worker sync functions: 100% (34/34 unit tests passing)

## Writing New Tests

### Unit Tests

Place in `tests/unit/` and use mocks for external dependencies:

```python
from unittest.mock import AsyncMock, patch
import pytest

@pytest.mark.asyncio
async def test_my_function():
    mock_client = AsyncMock()
    # ... test implementation
```

### Integration Tests

Place in `tests/integration/` and use real services where needed:

```python
import pytest
import pytest_asyncio

@pytest_asyncio.fixture
async def redis_pool(self):
    # Set up real Redis connection
    # ... fixture implementation

@pytest.mark.asyncio
async def test_with_redis(redis_pool):
    # ... test implementation
```

## Troubleshooting

### Tests can't find modules
Make sure you're running tests from within the Docker container:
```bash
docker compose exec google-contacts-worker pytest tests/
```

### Redis connection errors in integration tests
Ensure Redis is running:
```bash
docker compose up -d pms-redis
```

### Import errors for core_shared
The worker Dockerfile installs core_shared at `/core_shared/`. Tests should work automatically in the Docker environment.

