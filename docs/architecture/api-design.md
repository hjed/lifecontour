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

## MCP (Model Context Protocol) Guidelines

### FastMCP v2 Implementation

- **Framework**: Use FastMCP v2 (jlowin/fastmcp) instead of official MCP SDK
- **Documentation**: Reference https://gofastmcp.com/llms.txt for AI-optimized patterns
- **Integration**: Follow https://gofastmcp.com/deployment/asgi.md for FastAPI integration

### Tool Structure

- Use `@mcp.tool` decorator on async functions
- Define clear function names and docstrings
- Use Pydantic `Field` with `Annotated` for parameter descriptions
- Return JSON strings for structured data
- Include comprehensive error handling with try/catch blocks
- Provide AI-friendly responses with context and summaries

### Domain-Based Organization

- Organize tools by domain: `app/mcp/domains/{domain}/tools.py`
- Separate schemas: `app/mcp/domains/{domain}/schemas.py`
- Register domain tools in main server: `register_{domain}_tools(mcp)`
- Allow future domain expansion (journal, calendar, photos)

### Response Format

- Return JSON strings with structured, AI-friendly data
- Include contextual summaries for AI understanding
- Provide clear error messages with helpful context
- Use consistent field naming across all tools
- Add metadata like IDs, tags, and relationship information

### Authentication Integration

- Share OAuth session authentication with REST API
- Use `SessionAuthMiddleware` for MCP endpoint protection
- Validate session data: `id`, `email`, `name`, `provider`
- Provide user context to tools via request state

### Server Configuration

- Mount MCP server as sub-application in FastAPI
- Use configurable mount path (default: `/mcp-server`)
- Enable/disable via `MCP_ENABLED` environment variable
- Include in application health checks
- Use Streamable HTTP transport for web compatibility

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

## Incomplete Outdoor Activities Review Endpoints

The incomplete outdoor activities review (outdoor logbook) is exposed as a
journal sub-resource projection keyed by journal id:

| Verb + path | Purpose | Status |
|---|---|---|
| `GET /api/journals/incomplete-outdoor-activities` | List flagged journals with per-entry `reasons` (`no_attributes`, `missing_template`, `no_participants`), `subtypes`, and `event_date_range` | 200 |
| `POST /api/journals/incomplete-outdoor-activities/{journal_id}/dismiss` | Dismiss a journal from the review (provenance recorded as `ui`) | 200; 404 unknown/not-owned |
| `POST /api/journals/incomplete-outdoor-activities/{journal_id}/undismiss` | Restore a journal to the review | 200 (idempotent no-op with `was_dismissed: false` when never dismissed); 404 unknown/not-owned |

Conventions this surface pins down:

- **Action-verb POSTs** mirror the existing `POST /review-items/{id}/dismiss`
  precedent rather than introducing a second style (e.g. `DELETE .../dismissal`).
- **Idempotent undismiss:** 404 is reserved for "journal doesn't exist or isn't
  yours" (checked before the write, so unknown ids never surface as FK errors);
  un-dismissing a never-dismissed journal is a 200 no-op, observable via the
  `was_dismissed` attribute.
- **Unpaginated by design:** the review is a bounded advisory list computed by
  rule evaluation over a single facts query; repo-level limit/offset does not
  apply. The Pagination Guidelines above apply to stored collections, not this
  projection.
- **Transactions:** the controllers pass the request-scoped `AsyncConnection`
  into the `@transactional` dismissal service, which owns the commit —
  controllers never open transactions.

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
