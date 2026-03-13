# Testing Strategy - Personal CRM & Journal System

This document provides comprehensive testing patterns and strategies for the Personal CRM & Journal System with its Isolated Worker Architecture.

## Testing Strategy for Isolated Worker Architecture

The system's Isolated Worker Architecture requires a specialized testing approach that accounts for the distributed nature of integrations.

### Three-Tier Testing Strategy

#### 1. Worker Unit Tests
**Scope**: Individual integration worker logic in isolation
**Location**: `integration_workers/{integration_name}/tests/`
**Execution**: `cd integration_workers/google && pytest`

**Characteristics**:
- Test worker's internal logic and business rules
- Mock external API clients (Google, Strava, etc.)
- Mock `core_shared` database functions
- No Docker, Redis, or real database required
- Fast execution for rapid development feedback

**Example**:
```python
# integration_workers/google/tests/test_sync_service.py
@pytest.fixture
def mock_google_client():
    return Mock(spec=GoogleClient)

@pytest.fixture
def mock_db_session():
    return Mock(spec=Session)

def test_sync_contact_creates_new_contact(mock_google_client, mock_db_session):
    # Test sync logic without external dependencies
    pass
```

#### 2. Core Application Tests
**Scope**: Core FastAPI application without integration workers
**Location**: `backend/tests/`
**Execution**: Standard pytest in backend directory

**Characteristics**:
- Mock ARQ task queue client (`arq.enqueue_job`)
- Test that correct tasks are enqueued with correct parameters
- Do NOT test worker execution - only task scheduling
- Use existing unit/integration test patterns

**Example**:
```python
# backend/tests/integration/api/test_sync_endpoints.py
@pytest.fixture
def mock_arq_client():
    return Mock(spec=ArqRedis)

async def test_trigger_google_sync_enqueues_task(client, mock_arq_client):
    response = await client.post("/api/integrations/google/sync")
    assert response.status_code == 202
    mock_arq_client.enqueue_job.assert_called_once_with(
        'sync_google_contacts',
        user_id=123
    )
```

#### 3. End-to-End (E2E) Integration Tests
**Scope**: Full system including core app + workers + infrastructure
**Location**: `tests/e2e/`
**Execution**: Dedicated E2E test environment

**Characteristics**:
- Uses `docker-compose.e2e.yml` with all services
- Tests complete data flow from API call to database changes
- Polls database to verify worker execution results
- Tests real integration between all components
- Slower execution but comprehensive validation

**Example**:
```python
# tests/e2e/test_google_sync.py
async def test_google_full_sync():
    # 1. Trigger sync via API
    response = await api_client.post("/api/integrations/google/sync")
    assert response.status_code == 202

    # 2. Wait for worker to process
    await asyncio.sleep(5)

    # 3. Verify database changes
    contacts = await db.execute("SELECT * FROM contacts WHERE source = 'google'")
    assert len(contacts) > 0

    # 4. Verify sync metadata
    sync_data = await db.execute("SELECT * FROM sync_metadata WHERE integration_source = 'google'")
    assert len(sync_data) > 0
```

### Testing Workflow

1. **Worker Unit Tests**: Fast feedback during worker development
2. **Core App Tests**: Verify task scheduling and API contracts
3. **E2E Tests**: Validate complete system integration
4. **Run All**: Comprehensive validation before deployment

### Test Execution Concurrency

To support multi-worktree local development without port or container name clashes, the testing environments (E2E and Backend Integration) dynamically allocate Docker resources:

- **Dynamic Ports & Container Names**: A Python script (`scripts/workspace_env.py`) deterministically hashes the absolute workspace path to generate a unique integer offset.
- **Isolation**: Container names are prefixed with `pms_test_{offset}-` and host ports are shifted by `{offset} * 10`. For example, `DB_PORT` becomes `5433 + (offset * 10)`.
- **CI Compatibility**: In environments where `CI=true` or `GITHUB_ACTIONS=true` is set, the offset always evaluates to `0`, ensuring CI workflows run reliably on the standard default ports.

**Execution:**
Simply run `pnpm test:e2e` in `frontend/` or `python scripts/run_integration_tests.py` in `backend/` from any concurrent worktrees. The testing frameworks and `docker-compose.yml` automatically ingest these derived parameters to avoid collisions.


## Backend Testing with pytest

### pytest Configuration Guidelines

- Use `pyproject.toml` for pytest configuration with UV dependency management
- Focus on critical business logic rather than arbitrary coverage percentages
- Organize tests with clear markers (unit, integration, e2e)
- Use descriptive test file naming patterns
- Configure coverage reporting for CI/CD pipeline integration

### Unit Testing Patterns

- Use `@pytest.fixture` for test dependencies and setup
- Mock external dependencies with `pytest-mock` and `AsyncMock`
- Follow Arrange-Act-Assert pattern for clear test structure
- Group related tests together into test classes and suites
- Group tests by scenario aspect together as well
- Use descriptive test method names that explain the scenario
- Test both success and error scenarios comprehensively
- Use `@pytest.mark.asyncio` for async tests with pytest-asyncio

### API Integration Testing Guidelines

- Use `TestClient` for FastAPI endpoint testing
- Create fixtures for test database and client setup
- Test both success and error response scenarios
- Verify JSON API response format compliance
- Assert correct HTTP status codes
- Test validation error handling
- Use realistic test data

## Frontend Testing with React Testing Library

### Component Testing Guidelines

- Use `render` and `screen` for component testing
- Test component rendering with realistic props
- Verify user interactions with `fireEvent`
- Use `getByRole` and `getByText` for element queries
- Mock callback functions with `jest.fn()`
- Test accessibility with proper role attributes
- Focus on user behavior rather than implementation details

## End-to-End Testing with Playwright

### Advanced Fixture-Based Testing System

**🎯 MAJOR MILESTONE**: Complete fixture-based testing system with real OAuth authentication and deterministic data management.

> 📚 **Complete Documentation**: See [`frontend/tests/e2e/FIXTURE_SYSTEM_GUIDE.md`](../../frontend/tests/e2e/FIXTURE_SYSTEM_GUIDE.md) for comprehensive documentation, examples, and best practices.

#### Key Features

- ✅ **Real OAuth Authentication**: Authentic OAuth flows with Hydra provider
- ✅ **Worker-Scoped Performance**: OAuth once per worker, not per test
- ✅ **Deterministic Data**: Advanced fixture system eliminates conditional logic
- ✅ **Automatic Cleanup**: Zero test pollution with dependency tracking
- ✅ **Scalable Datasets**: From 5 contacts (smoke tests) to 500 contacts (performance tests)
- ✅ **Data Factories**: Realistic test data generation with customization

#### Available Fixtures

**Authentication Fixtures:**
- `authenticatedPage`: Real OAuth-authenticated page
- `unauthenticatedPage`: Clean unauthenticated state

**Dataset Fixtures:**
- `smallDataSet`: 5 contacts, 3 tags - quick smoke tests
- `mediumDataSet`: 20 contacts, 8 tags - comprehensive testing
- `largeDataSet`: 100 contacts, 15 tags - performance testing
- `searchTestData`: Optimized for search functionality testing
- `favouritesTestData`: Mix of favourite/regular contacts
- `performanceTestData`: 500 contacts, 50 tags - stress testing

**Specialized Fixtures:**
- `favouriteContacts`: Only favourite contacts
- `contactsWithoutTags`: Guaranteed untagged contacts
- `dataFactory`: Access to all data generation factories

### E2E Testing Guidelines

- Test complete user workflows from start to finish
- Use `data-testid` attributes for reliable element selection
- Test Australian localization (DD/MM/YYYY dates)
- Use fixture-based testing for deterministic scenarios
- Verify error handling and user feedback
- Test responsive design across different screen sizes
- Include accessibility testing in E2E flows

### ⚠️ LEGACY PATTERN - Replaced by Fixture System

**The conditional logic patterns below have been replaced by the advanced fixture-based testing system.**

> 🚀 **Migration**: See [`frontend/tests/e2e/MIGRATION_GUIDE.md`](../../frontend/tests/e2e/MIGRATION_GUIDE.md) for migrating from conditional logic to fixtures.

#### ❌ OLD PATTERN - Conditional Logic (Now Replaced)
```typescript
// OLD: Conditional logic based on data state
const { hasContacts, hasEmptyState } = await contacts.checkContactsOrEmptyState();
expect(hasContacts || hasEmptyState).toBe(true); // Meaningless test

// OLD: Skipping based on data state
if (contactCount === 0) {
  test.skip('No contacts found - this test requires contacts');
}
```

#### ✅ NEW PATTERN - Fixture-Based Testing
```typescript
// NEW: Use specific fixtures for guaranteed state
test('should display favourite contacts', async ({ favouriteContacts }) => {
  const { page, contacts } = favouriteContacts;

  await page.goto('/contacts/favourites');

  // Guaranteed: contacts exist and are favourites
  expect(contacts).toHaveLength(3);
  contacts.forEach(contact => {
    expect(contact.isFavourite).toBe(true);
  });
});

// NEW: Separate fixture for empty state
test('should display empty state', async ({ emptyContactsPage }) => {
  await emptyContactsPage.goto('/contacts/favourites');

  // Guaranteed: no contacts exist
  const emptyState = emptyContactsPage.locator('[data-testid="empty-state"]');
  await expect(emptyState).toBeVisible();
});

// NEW: Use data factories for custom scenarios
test('custom scenario', async ({ authenticatedPage, dataFactory, testCleanup }) => {
  const customContacts = dataFactory.contacts.createFavourites(5);
  // Test with exactly 5 favourite contacts
});
```

#### Test Data Setup Principles

1. **Each test creates its own data**: Use `testData.createTestContacts()`, `testData.createTestTags()`, etc.
2. **Tests are deterministic**: Each test knows exactly what data exists and what to expect
3. **No conditional logic**: Tests should not have if/else based on data state
4. **No skipping**: Tests should not skip based on what data they find
5. **Separate scenarios**: Have separate tests for empty states vs populated states
6. **Clean setup**: Use `testData.setupAuthenticatedUser()` and `testData.clearAllTestData()`

#### Required TestDataHelpers Implementation

```typescript
export class TestDataHelpers {
  async setupAuthenticatedUser(): Promise<void> {
    // Set up authentication state for tests
  }

  async createTestContacts(contacts: Array<{
    firstName: string;
    lastName: string;
    email?: string;
    isFavourite?: boolean;
    tags?: string[];
  }>): Promise<void> {
    // Create specific test contacts via backend APIs
  }

  async createTestTags(tags: string[]): Promise<void> {
    // Create specific test tags via backend APIs
  }

  async clearAllTestData(): Promise<void> {
    // Clean up all test data
  }
}
```

## Database Testing Guidelines

### Database Integration Testing

- Use test database separate from development database
- Create fixtures for database connections and cleanup
- Test database operations with realistic data
- Verify data persistence and retrieval
- Test database constraints and relationships
- Use transactions for test isolation

### Real Database Integration Testing with Docker

#### Docker PostgreSQL Setup

- Use `docker-compose.yml` with the test profile for test database container
- Separate test database from development database
- Automated container lifecycle management in test fixtures
- Health checks to ensure database readiness before tests

#### Test Isolation Patterns

- **Transaction Rollback**: Each test runs in an outer transaction with a **nested savepoint**. The savepoint is rolled back after each test, restoring the database to a clean state.
- **Schema Recreation**: Fresh database schema for each test session.
- **Data Cleanup**: Automatic cleanup between tests via savepoint rollback.
- **Connection Management**: Proper connection pooling and cleanup.

> [!IMPORTANT]
> **All database access during a test — including access via API test clients — must use the same `async_connection` savepoint fixture.** If a test client creates its own connection (e.g. via `DatabaseProvider`), data it writes will be committed to the real database and will leak into subsequent tests.

#### Integration Test Structure

The actual isolation is implemented using SQLAlchemy nested savepoints (`begin_nested`):

```python
@pytest.fixture(scope="session")
async def async_connection(...):
    """Session-scoped outer transaction; never committed."""
    async with engine.connect() as conn:
        await conn.begin()   # outer transaction — never committed
        yield conn
        await conn.rollback()

@pytest.fixture
async def clean_database(async_connection):
    """Per-test savepoint. Rolls back after each test."""
    nested = await async_connection.begin_nested()
    yield async_connection
    await nested.rollback()  # restores pre-test state
```

#### API Test Clients Must Use the Savepoint Connection

When writing API integration tests that use HTTP test clients (e.g. `AsyncClient`), you **must** inject `async_connection` via a custom provider — **do not** use `DatabaseProvider(test_settings)` which creates independent connections outside the savepoint:

```python
# ✅ CORRECT: inject the savepoint connection so writes are rolled back
class TestDatabaseProvider(Provider):
    def __init__(self, connection: AsyncConnection):
        super().__init__()
        self.connection = connection

    @provide(scope=Scope.REQUEST)
    def get_connection(self) -> AsyncConnection:
        return self.connection

@pytest_asyncio.fixture
async def my_api_client(async_connection: AsyncConnection, ...):
    test_container = make_async_container(
        TestDatabaseProvider(async_connection),  # ← savepoint connection
        ContactProvider(),
        ...
    )
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        yield client
    await test_container.close()

# ❌ WRONG: creates fresh connections that bypass the savepoint
test_container = make_async_container(
    DatabaseProvider(test_settings),  # ← commits to real DB — data leaks!
    ...
)
```

#### Real Database Benefits

- **SQL Validation**: Test actual PostgreSQL SQL syntax and behavior
- **Constraint Testing**: Verify database constraints work correctly
- **Performance Insights**: Real query performance characteristics
- **Production Parity**: Closer to actual deployment environment

### Enum Testing Patterns

#### Type-Safe Enum Usage in Tests

- Use enum values instead of string literals in test data
- Test enum validation in entity creation
- Verify enum conversion at repository boundaries
- Test enum comparisons in business logic

#### Example Enum Test Patterns

```python
# ✅ Use enum values in tests
method = ContactMethod(
    method_type=MethodType.EMAIL,  # Not "email"
    value="test@example.com",
    contact_id=1
)

# ✅ Test enum validation
def test_invalid_method_type_raises_error():
    with pytest.raises(ValueError):
        ContactMethod(
            method_type="invalid",  # Should fail validation
            value="test@example.com",
            contact_id=1
        )

# ✅ Test enum comparisons
def test_get_primary_email():
    contact = Contact(first_name="John", last_name="Doe")
    contact.methods.append(ContactMethod(
        method_type=MethodType.EMAIL,
        value="john@example.com",
        contact_id=1,
        is_primary=True
    ))
    assert contact.get_primary_email() == "john@example.com"
```

## Mock Utilities Guidelines

### Service Mocking

- Use `Mock` with `spec` parameter for type safety
- Create `AsyncMock` for async service methods
- Provide factory functions for common mock objects
- Mock external dependencies (database, APIs)
- Use descriptive mock return values
- Reset mocks between tests

## Test Data Factories Guidelines

### Factory Pattern

- Create factory classes for test data generation
- Provide sensible defaults for all fields
- Allow customization of specific fields
- Use realistic test data (Australian phone numbers, etc.)
- Create both request and response objects
- Keep factories simple and focused

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and testing principles
- [AI Guidelines](../ai-guidelines.md) - Test-first development workflow and quality standards
- [Technology Stack](./technology-stack.md) - Testing technology choices and high-level strategy
- [Domain Architecture](./domain-architecture.md) - Domain patterns and validation strategies
- [API Design](./api-design.md) - API testing patterns and validation
- [Frontend Design](./frontend-design.md) - Component testing patterns and accessibility
- [Deployment Guide](./deployment-guide.md) - CI/CD testing pipeline and Docker test setup
