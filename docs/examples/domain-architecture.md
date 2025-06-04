# Domain Architecture Guidelines

## Python Backend Domain Patterns

### Domain Layer Guidelines (Ports & Adapters)
- **Domain Entities**: Pure Python classes with business logic, no framework dependencies
- **Domain Components**: Business logic that doesn't belong to a single entity
- **Adapters**: Classes supply the domains infrastructure needs such as sql repositories
- **Value Objects**: Immutable objects representing domain concepts
- **Domain Events**: Pure Python classes representing business events
- **Domain Enums**: Python enums for fixed domain values with type safety
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

### Domain Enum Patterns

#### Enum Definition Guidelines
- **String Values**: Use string values for database compatibility
- **Descriptive Names**: Use clear, descriptive enum member names
- **String Conversion**: Implement `__str__()` method to return enum value
- **Domain Location**: Define enums in the same module as related entities

#### Example Enum Implementation
```python
from enum import Enum

class MethodType(Enum):
    """Enumeration for contact method types."""

    EMAIL = "email"
    PHONE = "phone"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
```

#### Repository Conversion Patterns
- **Writing to Database**: Convert enum to string using `.value` property
- **Reading from Database**: Convert string to enum using `EnumType(string_value)`
- **Error Handling**: Handle invalid enum values gracefully

#### Entity Validation Patterns
```python
def __post_init__(self) -> None:
    """Validate entity with enum."""
    if not isinstance(self.method_type, MethodType):
        raise ValueError(f"Invalid method type: {self.method_type}")

    # Type-safe business logic
    if self.method_type == MethodType.EMAIL:
        Email(self.value)  # Validate email format
    elif self.method_type == MethodType.PHONE:
        PhoneNumber(self.value)  # Validate phone format
```

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
