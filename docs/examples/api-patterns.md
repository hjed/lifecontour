# API Patterns - FastAPI and MCP Guidelines

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

## Database Query Guidelines

### SQLAlchemy Core Patterns
- Use `text()` for explicit SQL queries
- Define queries as constants for reusability
- Use parameterized queries to prevent SQL injection
- Keep queries simple and readable
- Group related queries in dedicated modules
- Return dictionaries from query functions

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
- Use official Python MCP SDK
- Initialize server with clear name and version
- Register tools in a centralized list
- Implement `list_tools` and `call_tool` handlers
- Use HTTPTransport for web compatibility
- Configure host and port from environment variables
- Add proper error handling and logging
- Return structured responses with content array

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
