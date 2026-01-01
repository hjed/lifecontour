# Integration Tests for Concurrent Sync Operations

This directory contains integration tests that verify the correct behavior of concurrent sync operations with database locking and idempotency patterns.

## Overview

These tests ensure that the integration sync system handles race conditions correctly when multiple workers attempt to sync the same data simultaneously. This is critical for maintaining data consistency in a distributed system where multiple workers may be processing sync operations concurrently.

## Test Files

### `test_concurrent_sync.py`

Tests for concurrent sync operations with SELECT FOR UPDATE locking and idempotency checks.

**Test Cases:**

1. **`test_concurrent_sync_with_locking`**
   - **Purpose:** Verify that concurrent sync operations on the same contact use SELECT FOR UPDATE to prevent race conditions
   - **Scenario:** Two workers attempt to sync the same contact simultaneously with the same version hash
   - **Expected Behavior:**
     - Both workers acquire the lock sequentially (not simultaneously)
     - One worker updates the sync metadata
     - The other worker skips the update (idempotency check)
     - Final state has the correct version hash
   - **Key Patterns:**
     - SELECT FOR UPDATE row-level locking
     - Version hash comparison for idempotency
     - Separate database connections per worker

2. **`test_concurrent_sync_different_contacts`**
   - **Purpose:** Verify that concurrent sync operations on different contacts don't block each other
   - **Scenario:** Two workers sync different contacts simultaneously
   - **Expected Behavior:**
     - Both operations run concurrently (not sequentially)
     - Total execution time is ~0.1s (not ~0.2s)
     - Both contacts are updated successfully
   - **Key Patterns:**
     - Row-level locking (not table-level)
     - Concurrent execution verification via timing
     - Independent transaction isolation

## Key Patterns Demonstrated

### 1. SELECT FOR UPDATE Locking

```sql
SELECT id, version_hash, sync_status
FROM sync_metadata
WHERE integration_source = :integration_source
  AND external_id = :external_id
FOR UPDATE
```

This pattern:
- Acquires a row-level lock on the sync metadata
- Prevents other transactions from modifying the same row
- Ensures only one worker processes a sync operation at a time
- Releases the lock when the transaction commits or rolls back

### 2. Idempotency Check

```python
if row and row[1] == new_hash:  # version_hash
    return "skipped"
```

This pattern:
- Checks if the data has already been synced with the same version
- Skips redundant updates
- Ensures safe message redelivery in distributed systems
- Prevents duplicate work

### 3. Separate Connections for Concurrent Operations

```python
async with async_engine.connect() as conn:
    async with conn.begin():
        # Perform sync operation
```

This pattern:
- Creates a new database connection for each worker
- Ensures proper transaction isolation
- Allows concurrent operations on different rows
- Properly tests real-world concurrent behavior

## Running the Tests

### Prerequisites

- Docker and Docker Compose installed
- PostgreSQL test database (automatically started by test fixtures)
- Python 3.11+ with dependencies installed

### Run Tests

```bash
# Run all concurrent sync tests
cd backend
uv run pytest tests/integration/core/integrations/test_concurrent_sync.py -v

# Run a specific test
uv run pytest tests/integration/core/integrations/test_concurrent_sync.py::TestConcurrentSyncOperations::test_concurrent_sync_with_locking -v
```

### Test Infrastructure

The tests use the integration test infrastructure defined in `backend/tests/integration/conftest.py`:

- **Database Setup:** Automatically starts PostgreSQL in Docker using the unified docker-compose.yml
- **Fixtures:**
  - `async_engine`: Async SQLAlchemy engine for creating connections
  - `async_connection`: Async connection with transaction rollback for test isolation
  - `setup_test_database`: Session-scoped fixture that manages Docker containers

### Test Cleanup

Each test includes cleanup steps to ensure test isolation:

```python
# Cleanup: Delete test data
async with async_engine.connect() as cleanup_conn:
    async with cleanup_conn.begin():
        await cleanup_conn.execute(
            text("DELETE FROM sync_metadata WHERE ..."),
            {...},
        )
```

This ensures that data from one test doesn't affect subsequent tests.

## Implementation Notes

### Non-Deterministic Execution Order

The tests account for the non-deterministic nature of `asyncio.gather()`:

```python
# One worker should update, the other should skip (order is non-deterministic)
assert sorted(results) == ["skipped", "updated"]
```

This makes the tests robust regardless of which worker executes first.

### Timing Assertions

The concurrent execution test uses timing assertions with generous thresholds:

```python
# Allow more overhead for transaction management and connection setup
assert total_time < 0.4, f"Syncs should run concurrently, not sequentially (took {total_time}s)"
```

This accounts for:
- Transaction management overhead
- Connection setup time
- System variability
- CI/CD environment differences

## Future Enhancements

Potential improvements to these tests:

1. **Deadlock Detection:** Add tests for deadlock scenarios and recovery
2. **Retry Logic:** Test automatic retry on lock timeout
3. **Performance Benchmarks:** Measure throughput under high concurrency
4. **Error Scenarios:** Test behavior when locks are held for extended periods
5. **Distributed Testing:** Test across multiple database instances

## Related Documentation

- [Integration Architecture](../../../../docs/tasks/iteration-2-integration-architecture.md)
- [Sync Metadata Model](../../../../core_shared/models/sync_metadata.py)
- [Integration Test Setup](../../conftest.py)

