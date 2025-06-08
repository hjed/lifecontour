# Testing Strategy - Personal CRM & Journal System

This document provides comprehensive testing patterns and strategies for the Personal CRM & Journal System.

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
