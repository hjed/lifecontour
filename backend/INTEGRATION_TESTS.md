# Integration Tests

This document describes how to run integration tests for the Personal Management System backend.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.14+ with dependencies installed (`uv pip install -e .[dev]`)

## Running Integration Tests

### Option 1: Using the Test Runner Script (Recommended)

The easiest way to run integration tests is using the provided script:

```bash
python scripts/run_integration_tests.py
```

This script will:
1. Check that Docker is available
2. Start a PostgreSQL test database container using the unified docker-compose
3. Run all integration tests
4. Stop the test database container

### Option 2: Using Unified Docker Compose (test-backend profile)

Start the minimal test environment with the unified docker-compose:

```bash
# Start test services
docker compose --profile test-backend --env-file .env.test up -d

# Wait for database to be ready
docker compose exec database pg_isready -U postgres

# Run integration tests
python -m pytest tests/integration/ -v

# Stop and clean up
docker compose --profile test-backend down -v
```

### Option 3: Manual Setup (Legacy)

If you prefer to manage the database manually:

1. **Start the test database:**
   ```bash
   docker compose --profile test-backend --env-file .env.test up -d
   ```

2. **Wait for database to be ready:**
   ```bash
   docker compose exec database pg_isready -U postgres
   ```

3. **Run integration tests:**
   ```bash
   python -m pytest tests/integration/ -v
   ```

4. **Stop the test database:**
   ```bash
   docker compose --profile test-backend down -v
   ```

## Test Structure

### Repository Integration Tests

- `test_contact_repository_integration.py` - Tests for ContactRepository SQL implementation
- `test_tag_repository_integration.py` - Tests for TagRepository SQL implementation
- `test_field_history_repository_integration.py` - Tests for ContactFieldHistoryRepository SQL implementation
- `test_event_repository_integration.py` - Tests for ContactEditEventRepository SQL implementation

### Service Integration Tests

- `test_contact_service_integration.py` - End-to-end tests for ContactService with real database

## Database Setup

The integration tests use a separate PostgreSQL database running in Docker via the unified docker-compose setup:

**Configuration (.env.test):**
- **Host:** localhost
- **Port:** 5433 (to avoid conflicts with local PostgreSQL)
- **Database:** personal_management_test
- **User:** postgres
- **Password:** postgres

**Connection string:**
```
postgresql://postgres:postgres@localhost:5433/personal_management_test
```

Each test runs in a transaction that is rolled back after the test completes, ensuring test isolation.

## Test Database Schema

The test database schema is created automatically for each test and includes:

- `contacts` - Main contact table
- `contact_methods` - Email, phone, etc.
- `contact_addresses` - Physical addresses
- `contact_notes` - Notes about contacts
- `tags` - Hierarchical tags
- `contact_tags` - Many-to-many relationship
- `contact_field_history` - Audit trail for field changes
- `contact_edit_event` - Domain events for business logic

## Troubleshooting

### Docker Issues

If you get Docker-related errors:

1. Make sure Docker is running
2. Check that port 5433 is not in use
3. Try stopping any existing containers:
   ```bash
   docker-compose -f docker-compose.yml down -v
   ```

### Database Connection Issues

If tests fail with connection errors:

1. Wait longer for the database to start (it can take 10-30 seconds)
2. Check container logs:
   ```bash
   docker logs backend-postgres-test-1
   ```

### Test Failures

If specific tests fail:

1. Run tests with more verbose output:
   ```bash
   python -m pytest tests/integration/ -v --tb=long
   ```

2. Run a specific test file:
   ```bash
   python -m pytest tests/integration/contacts/test_contact_repository_integration.py -v
   ```

3. Run a specific test:
   ```bash
   python -m pytest tests/integration/contacts/test_contact_repository_integration.py::TestContactRepositoryIntegration::test_save_new_contact -v
   ```

## Performance

Integration tests are slower than unit tests because they:
- Start/stop Docker containers
- Create/drop database schemas
- Perform real database operations

Typical run times:
- Repository tests: ~30-60 seconds
- Service tests: ~60-120 seconds
- Full integration suite: ~2-5 minutes

## CI/CD Integration

For continuous integration, you can run integration tests in CI pipelines:

```yaml
# Example GitHub Actions step
- name: Run Integration Tests
  run: |
    python scripts/run_integration_tests.py
```

The test runner script handles all setup and teardown automatically.
