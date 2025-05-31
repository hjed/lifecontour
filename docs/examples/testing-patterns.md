# Testing Patterns - Guidelines

## Backend Testing with pytest

### pytest Configuration Guidelines
- Use `pyproject.toml` for pytest configuration
- Set coverage thresholds for quality gates
- Organize tests with clear markers (unit, integration, e2e)
- Use descriptive test file naming patterns
- Configure coverage reporting for CI/CD

### Unit Testing Patterns
- Use `@pytest.fixture` for test dependencies
- Mock external dependencies with `AsyncMock`
- Follow Arrange-Act-Assert pattern
- Group related tests together into suites
- Group tests by scenario aspect together as well
- Use descriptive test method names
- Test both success and error scenarios
- Use `@pytest.mark.asyncio` for async tests

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
