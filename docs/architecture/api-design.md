# API Design - Personal CRM & Journal System

This document provides comprehensive API design patterns for both REST and MCP interfaces.

## FastAPI REST API Guidelines (Infrastructure Layer)

### Controller Structure (Adapters)

- **Controllers are Adapters**: Convert HTTP requests to application commands
- **Dependency Injection**: Inject application use cases, not domain entities
- **Pydantic Models**: Use for HTTP input/output validation only
- **Error Translation**: Convert domain exceptions to HTTP responses
- **No Business Logic**: Controllers only handle HTTP concerns
- **JSON API Compliance**: Follow specification for response format

### Proper Layering

- **HTTP Layer**: FastAPI controllers, Pydantic models, HTTP status codes
- **Application Layer**: Use case classes injected into controllers
- **Domain Layer**: Pure Python, no HTTP/FastAPI dependencies
- **Infrastructure Layer**: Database adapters, external API clients

## Input Validation Guidelines

### Pydantic Model Patterns

- Use `BaseModel` for all request/response models
- Add `@validator` decorators for custom validation
- Use `Optional` for nullable fields
- Include clear error messages in validators
- Use `EmailStr` for email validation
- Set sensible defaults for optional fields

## CORS and Proxy Guidelines

### FastAPI CORS Setup

- Use `CORSMiddleware` for cross-origin requests
- Configure allowed origins from environment variables
- Enable credentials for authenticated requests
- Set appropriate headers for nginx proxy compatibility
- Allow common development origins (localhost)

## MCP Tool Guidelines

### Tool Structure

- Inherit from `Tool` base class
- Define clear `name` and `description`
- Specify `input_schema` with required/optional parameters
- Implement `execute` method with proper error handling
- Return AI-friendly responses with context and summaries
- Include search suggestions and metadata for AI assistants

### Response Format

- Provide structured data with clear field names
- Include summary information for AI context
- Add error handling with meaningful error messages
- Return metadata like total counts and search context
- Use consistent field naming across all tools

### MCP Server Guidelines

- Use official Python MCP SDK for standardized implementation
- Initialize server with clear name and version information
- Register tools in a centralized list for maintainability
- Implement `list_tools` and `call_tool` handlers properly
- Use HTTPTransport for web compatibility and AI client integration
- Configure host and port from environment variables
- Add comprehensive error handling and structured logging
- Return structured responses with content array per MCP specification

## Error Handling Guidelines

### JSON API Error Format

- Use `errors` array with structured error objects
- Include `status`, `title`, and `detail` fields
- Add `source` pointer for validation errors
- Map HTTP status codes to appropriate error types
- Log unexpected errors for debugging

### FastAPI Exception Handling

- Create custom exception handlers for common errors
- Use `HTTPException` for API errors
- Return JSON API compliant error responses
- Handle Pydantic validation errors gracefully
- Provide meaningful error messages for users

## Pagination Guidelines

### JSON API Pagination

- Use `page` and `limit` query parameters
- Include `meta` object with total count and page info
- Provide `links` object with navigation URLs
- Calculate `offset` from page and limit
- Handle edge cases (empty results, invalid pages)
- Use generic types for reusable pagination responses

### Implementation Pattern

- Create reusable pagination models with Pydantic
- Build pagination links dynamically from base URL
- Return both data and metadata in responses
- Use consistent parameter names across endpoints
- Validate page and limit parameters

## Authentication Guidelines

### Session-Based Authentication

- Use Starlette SessionMiddleware for session management
- Store session data securely with proper encryption
- Implement session timeout and renewal
- Handle concurrent sessions appropriately
- Provide clear authentication error responses

### Security Considerations

- Use HTTPS in production environments
- Implement proper CSRF protection
- Validate all input parameters
- Log authentication events for audit trails
- Handle rate limiting for authentication endpoints

## API Documentation

### OpenAPI Integration

- Use FastAPI's automatic OpenAPI generation
- Provide clear descriptions for all endpoints
- Include example requests and responses
- Document error responses and status codes
- Use tags to organize endpoints by domain

### Documentation Best Practices

- Write clear, concise endpoint descriptions
- Include parameter validation rules
- Provide realistic example data
- Document authentication requirements
- Keep documentation up-to-date with code changes

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and API principles
- [AI Guidelines](../ai-guidelines.md) - API development standards and guidelines
- [Technology Stack](./technology-stack.md) - API technology choices and frameworks
- [Domain Architecture](./domain-architecture.md) - Domain layer patterns and business logic
- [Testing Strategy](./testing-strategy.md) - API testing patterns and validation
- [Frontend Design](./frontend-design.md) - Frontend API integration patterns
- [Security & Performance](./security-performance.md) - API security considerations
- [Deployment Guide](./deployment-guide.md) - API deployment and configuration
