# Testing Strategy - Personal CRM & Journal System

This document provides comprehensive testing patterns and strategies for the Personal CRM & Journal System with its Isolated Worker Architecture.

## Testing Strategy for Isolated Worker Architecture

The system's Isolated Worker Architecture requires a specialized testing approach that accounts for the distributed nature of integrations.

### Three-Tier Testing Strategy

#### 1. Worker Unit Tests
**Scope**: Individual integration worker logic in isolation
**Location**: `integration_workers/{integration_name}/tests/`
**Execution**: `cd integration_workers/google_contacts && pytest`

**Characteristics**:
- Test worker's internal logic and business rules
- Mock external API clients (Google, Strava, etc.)
- Mock `core_shared` database functions
- No Docker, Redis, or real database required
- Fast execution for rapid development feedback

**Example**:
```python
# integration_workers/google_contacts/tests/test_sync_service.py
@pytest.fixture
def mock_google_client():
    return Mock(spec=GoogleContactsClient)

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
# tests/e2e/test_google_contacts_sync.py
async def test_google_contacts_full_sync():
    # 1. Trigger sync via API
    response = await api_client.post("/api/integrations/google/sync")
    assert response.status_code == 202

    # 2. Wait for worker to process
    await asyncio.sleep(5)

    # 3. Verify database changes
    contacts = await db.execute("SELECT * FROM contacts WHERE source = 'google'")
    assert len(contacts) > 0

    # 4. Verify sync metadata
    sync_data = await db.execute("SELECT * FROM sync_metadata WHERE integration_source = 'google_contacts'")
    assert len(sync_data) > 0
```

### Testing Workflow

1. **Worker Unit Tests**: Fast feedback during worker development
2. **Core App Tests**: Verify task scheduling and API contracts
3. **E2E Tests**: Validate complete system integration
4. **Run All**: Comprehensive validation before deployment

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

### E2E Testing Guidelines

- Test complete user workflows from start to finish
- Use `data-testid` attributes for reliable element selection
- Test Australian localization (DD/MM/YYYY dates)
- Mock external API calls for consistent testing
- Verify error handling and user feedback
- Test responsive design across different screen sizes
- Include accessibility testing in E2E flows

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

- Use `docker-compose.test.yml` for test database container
- Separate test database from development database
- Automated container lifecycle management in test fixtures
- Health checks to ensure database readiness before tests

#### Test Isolation Patterns

- **Transaction Rollback**: Each test runs in isolated transaction
- **Schema Recreation**: Fresh database schema for each test session
- **Data Cleanup**: Automatic cleanup between tests
- **Connection Management**: Proper connection pooling and cleanup

#### Integration Test Structure

```python
@pytest.fixture(scope="session")
async def test_database():
    """Start test database container and create schema."""
    # Start Docker container
    # Wait for database readiness
    # Create schema
    yield connection
    # Cleanup and stop container

@pytest.fixture
async def clean_database(test_database):
    """Provide clean database for each test."""
    async with test_database.begin() as transaction:
        yield transaction
        await transaction.rollback()
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
