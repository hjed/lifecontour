# Domain Architecture Guidelines

## Python Backend Domain Patterns

### Domain Layer Guidelines (Ports & Adapters)
- **Domain Entities**: Pure Python classes with business logic, no framework dependencies
- **Domain Components**: Business logic that doesn't belong to a single entity
- **Adapters**: Classes supply the domains infrastructure needs such as sql repositories
- **Value Objects**: Immutable objects representing domain concepts
- **Domain Events**: Pure Python classes representing business events
- **No Framework Dependencies**: Domain layer must be framework-agnostic

### Application Layer Guidelines
- **Use Cases**: Orchestrate domain operations, no business logic
- **Application Services**: Coordinate between domain and infrastructure
- **Command/Query Objects**: Simple data structures for input/output
- **Dependency Injection**: Inject ports (interfaces), not concrete implementations
- **Transaction Management**: Handle database transactions at this layer

### Infrastructure Layer Guidelines (Adapters)
- **Repository Adapters**: Implement domain-defined repository ports
- **API Adapters**: Implement external service ports (Google, Immich)
- **Database Adapters**: Use SQLAlchemy Core, implement repository interfaces
- **Framework Integration**: Pydantic models for FastAPI, not domain
- **Dependency Direction**: Infrastructure depends on domain ports, never reverse
- **Error Translation**: Convert infrastructure errors to domain exceptions

### Validation Strategy (Layered)
- **Domain Layer**: Business rule validation in entities/domain services
- **Application Layer**: Use case validation and authorization
- **Infrastructure Layer**: Pydantic models for API input/output validation
- **Database Layer**: Database constraints as final safety net

### External Integration Guidelines
- Create separate modules for each external service
- Use standard HTTP libraries (requests) for API calls
- Implement proper error handling and retries
- Use environment variables for API credentials
- Add logging for debugging integration issues
- Map external data to internal models
- Handle rate limiting and API quotas gracefully

### Application Service Guidelines
- Keep application services focused on orchestration
- Validate input using Pydantic models
- Implement business rule validation
- Use database transactions for consistency
- Add comprehensive logging for operations
- Handle errors gracefully with meaningful messages
- Keep services stateless and testable

### Error Handling Guidelines
- Create custom exception classes for domain errors
- Use meaningful error messages for debugging
- Include context information in error messages
- Log errors with appropriate severity levels
- Handle exceptions at appropriate boundaries
- Return user-friendly error responses from APIs
- Use standard HTTP status codes for API errors

### Logging Guidelines
- Use Python standard library logging
- Include structured logging with context
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Include correlation IDs for request tracing
- Log business operations for audit trails
- Avoid logging sensitive information
- Use consistent log message formats