# AI Development Guidelines - Personal CRM & Journal System

## Project Context

This document provides essential guidelines for AI assistants working on the
Personal CRM & Journal System. The system uses a Python FastAPI backend with
PostgreSQL database and TypeScript/React frontend, integrating personal data
from multiple sources with both MCP (Model Context Protocol) and web interfaces.

Refer to the [architecture document](./architecture.md) for a high-level
overview of the system architecture and navigation.

Tasks can be found in the [tasks document](./tasks.md).

### Key Technologies

- **Backend**: Python 3.11+ with FastAPI, PostgreSQL database
- **Frontend**: Next.js with React, shadcn/ui components, Tailwind CSS
- **APIs**: JSON API standard for REST endpoints, MCP for AI integration
- **Testing**: pytest (backend), React Testing Library (frontend), Playwright (e2e)
- **Integrations**: Google Calendar/Contacts, Immich photos
- **Deployment**: Docker with nginx proxy support

### Core Principles

1. **Clear Language Separation**: Python backend, TypeScript frontend
2. **AI-Optimized**: Design for AI assistant understanding over performance
3. **Domain-Driven Architecture**: Core domains with separate integration sub-domains
4. **Agile Development**: Feature-complete iterations delivering incremental value
5. **Explicit Patterns**: No magic, everything readable and understandable
6. **Simple Dependencies**: Standard libraries over complex abstractions

## Agile Development Approach

### Feature-Complete Iterations

- Each iteration delivers working, testable functionality end-to-end
- Build domain logic → database queries → API endpoints → basic UI
- Deploy and test after each iteration
- Integration sub-domains developed separately from core domains
- Architecture can evolve - check technology choices with user before acting

### Development Sequence

1. **Documentation** - document any planned changes, confirm design decisions
2. **Backend domain logic** - Python business logic with clear, simple patterns. Use test driven development.
3. **Database operations** - Explicit SQL queries with SQLAlchemy Core in Repository adapters.
4. **API endpoints** - FastAPI controllers with JSON API compliance
5. **Frontend UI** - Next.js interface using shadcn/ui
6. **Tests** - pytest (backend), React Testing Library (frontend), Playwright (e2e)
7. **Deploy and validate** - ensure feature works in real environment

## Testing Strategy

### Multi-Language Testing Approach

1. **Backend Tests (pytest)** - Domain logic, database operations, API endpoints
   - **Unit Tests**: Fast, isolated tests for business logic
   - **Integration Tests**: Real database operations with Docker PostgreSQL
2. **Frontend Tests (React Testing Library)** - Components with shadcn/ui integration
3. **End-to-End Tests (Playwright)** - Full user workflows and Australian localization

### Testing Requirements

- **Coverage**: Focus on critical business logic rather than arbitrary percentages
- **Test-Driven Development**: Write tests first, then implement functionality
- **Real Database Testing**: Use Docker PostgreSQL for integration tests
- **Australian Localization**: Test date formats (DD/MM/YYYY)
- **Accessibility**: ARIA attributes, keyboard navigation, screen reader support
- **Clear Separation**: Independent test suites for backend and frontend

### Integration Testing Patterns

- **Docker PostgreSQL**: Use `docker-compose.test.yml` for real database testing
- **Transaction Isolation**: Each test runs in isolated transaction with rollback
- **Schema Recreation**: Fresh database schema for each test session
- **Real Constraints**: Test actual database constraints and SQL behavior
- **Performance Validation**: Verify query performance with real data

_See [Testing Patterns](./examples/testing-patterns.md) for detailed examples._

## Frontend Development Standards

### shadcn/ui Component Guidelines

- Use shadcn/ui components with proper TypeScript interfaces
- Implement proper accessibility with ARIA attributes and screen reader support
- Follow responsive design patterns with mobile-first approach
- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`

### Key Patterns

- **Cards**: Use `Card`, `CardHeader`, `CardContent` for consistent layouts
- **Forms**: Integrate with react-hook-form and Zod validation
- **Dropdowns**: Include keyboard navigation and proper ARIA attributes
- **Badges**: Use for tags with custom colors via style prop

_See [Component Patterns](./examples/component-patterns.md) for detailed
shadcn/ui implementation examples._

### Tailwind CSS Guidelines

- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`
- Follow mobile-first responsive design with `sm:`, `lg:`, `xl:` prefixes
- Leverage shadcn/ui's CSS custom properties for theming

### Australian English Localisation

#### Key Requirements

- **Date Format**: DD/MM/YYYY (not MM/DD/YYYY) for user display. Use ISO format
  for machine-to-machine communication.
- **Currency**: AUD formatting with Intl.NumberFormat('en-AU')
- **Locale**: Use 'en-AU' for react-intl and date-fns

## Development Standards

### TypeScript Configuration

- Always define interfaces for API objects, database entities, configuration,
  and MCP tools
- Use exact optional property types for better type safety

### Code Organization

#### Project Structure (Clear Language Separation)

```
personal-management-system/
├── backend/                      # Python FastAPI application
│   ├── app/
|   |   |── core/                 # Core Domain Logic
|   |   |   |── contacts/        # Contact Domain Logic
|   |   |   |   |── adapters/    # Interfaces with apis, sql, events, etc
|   |   |   |   |   |── api/     # External API clients
|   |   |   |   |   |── sql/     # Database repositories
|   |   |   |   |   |── events/  # Event publishing and receiving adapters
|   |   |   |   |── models/      # Domain models
|   |   |   |── calendar/        # Calendar Domain Logic
|   |   |   |── journal/         # Journal Domain Logic
|   |   |── infrastructure/      # Common code for Database, Events, etc.
│   │   ├── api/                 # FastAPI route handlers
│   │   |   ├── dtos/            # Pydantic models
│   │   ├── migrations/          # SQL queries and migrations
│   │   └── integrations/        # External Sub-Domains
│   │       ├── google/          # Google Integration Sub-Domain
│   │       └── immich/          # Immich Integration Sub-Domain
│   ├── tests/                    # pytest test suite
│   |   ├── unit/                 # Unit tests
│   │   ├── integration/          # Integration tests
│   │   └── e2e/                  # End-to-end tests
│   └── pyproject.toml            # UV dependencies
├── frontend/                     # Next.js TypeScript application
│   ├── src/
│   │   ├── app/                  # Next.js app router
│   │   ├── components/           # React components
│   │   ├── lib/                  # Utilities and API clients
│   │   └── types/                # TypeScript interfaces
│   ├── tests/                    # React Testing Library tests
│   └── package.json              # pnpm dependencies
|── docker-compose.yml            # Multi-container setup
|── docs/                         # All documentation
|   ├── architecture/             # Architecture documentation
|   ├── examples/                 # Code examples and patterns
|   ├── ai-guidelines.md          # AI assistant guidelines
|   ├── tasks.md                  # Task tracking and agile development
|   └── ...                       # Other documentation
```

#### Naming Conventions

- **Python Files**: snake_case (`fetch_contacts.py`)
- **TypeScript Files**: kebab-case (`contact-service.ts`)
- **Classes**: PascalCase (`FetchContactComponent`)
- **Functions/Variables**: camelCase (TS), snake_case (Python)
- **Constants**: UPPER_SNAKE_CASE

### Backend Development (Python)

#### Key Patterns

- **Explicit SQL**: Use SQLAlchemy Core with raw SQL queries
- **Simple Components**: Clear business logic without complex abstractions
- **Pydantic Models**: Type-safe request/response validation
- **Standard Libraries**: Prefer built-in libraries over external dependencies
- **Clear Separation**: Keep domain logic separate from API and database concerns
- **Use Type Hints**: Always use type hints for better code understanding
- **Mypy Compliance**: All code must pass mypy type checking without errors
- **Python Enums**: Use enums for domain values (e.g., `MethodType.EMAIL`) for type safety
- **Enum Conversion**: Convert between enums and strings at repository boundaries

#### Type Checking Guidelines

- **Function Signatures**: Always include return type annotations
- **Parameter Types**: Use proper type hints for all function parameters
- **Generic Types**: Use `Union[T, U]` for multiple types, `Optional[T]` for nullable
- **Unused Parameters**: Prefix with underscore (`_param`) to indicate intentionally unused
- **Type Ignores**: Use `# type: ignore[specific-error]` sparingly with specific error codes
- **Pydantic Models**: Use `str` instead of `PostgresDsn` for database URLs to avoid validation complexity

#### Enum Usage Patterns

- **Domain Values**: Use Python enums for fixed domain values (e.g., `MethodType`, `AddressType`)
- **String Values**: Enum values should be strings for database compatibility
- **String Conversion**: Implement `__str__()` method to return enum value
- **Repository Conversion**: Convert enum to string when writing to database, string to enum when reading
- **Type Safety**: Use enum comparisons in business logic (`method.type == MethodType.EMAIL`)
- **Validation**: Validate enum values in entity `__post_init__()` methods

#### Business Rules and Validation

- **Domain-Specific Rules**: See [Domain Architecture](./architecture/domain-architecture.md) for detailed business rules
- **Validation Patterns**: Use Pydantic models for input validation
- **Error Handling**: Custom exceptions with HTTP status codes and AI-friendly messages
- **Transaction Management**: Handle transactions at the domain/business layer
- **History Tracking**: All entity changes recorded with domain events

#### Database Operations

- **Queries**: Explicit SQL with SQLAlchemy text() for readability
- **Migrations**: Alembic with clear, readable SQL migration files
- **Connections**: Simple connection management, no complex pooling
- **Enum Storage**: Store enums as strings in database, convert at repository layer
- **Constraint Handling**: Use database constraints for validation, capture errors in repositories
- **Transaction Management**: Pass transactions to repositories for business-level control
- **Integration Testing**: Test real database operations with Docker PostgreSQL

_See [Domain Architecture](./examples/domain-architecture.md) for detailed patterns._

## Essential Development Practices

### Error Handling

- Create custom error classes with meaningful names and context
- Always handle errors explicitly with try/catch blocks
- Use structured logging for error context
- Return result objects: `{ success: boolean, data?: T, error?: string }`
- Include HTTP status codes in domain exceptions for API layer
- Provide AI-friendly error messages with context
- **Exception Chaining**: Use `raise CustomError(...) from e` to preserve original error context
- **Database Errors**: Catch `IntegrityError` and convert to domain-specific exceptions

_See [Domain Architecture](./architecture/domain-architecture.md) for specific exception patterns._

### Database Operations

- **Explicit Queries**: Use SQLAlchemy Core with text() for readable SQL
- **Connection Management**: Pass connections into repositories for transaction control
- **Transactions**: Manage at domain/business layer, not repository layer
- **Security**: Always use parameterized queries to prevent SQL injection
- **Enum Handling**: Convert enums to strings for database storage, strings to enums when reading
- **Constraint Validation**: Let database constraints validate data, catch and convert errors
- **Integration Testing**: Use real PostgreSQL database for testing actual SQL behavior

### Dependency Injection

- **Pattern**: Constructor injection with typed interfaces
- **Repositories**: Receive database connections as constructor parameters
- **Services**: Receive repository interfaces as constructor parameters
- **Simple Container**: Use basic factory pattern, avoid complex DI frameworks
- **Type Safety**: All dependencies typed with interfaces for clarity

### API Design

- **JSON API Compliance**: Follow JSON API specification for REST endpoints
- **Input Validation**: Use Pydantic models for all request validation
- **Error Responses**: Return structured JSON API error format
- **Pagination**: Implement simple pagination for large datasets

### MCP Implementation

- **Python MCP SDK**: Use official Python MCP SDK for server implementation
- **AI-Friendly Responses**: Provide context and summaries, not raw database data
- **Clear Interfaces**: Structure MCP tools with consistent, simple interfaces

### Security & Performance

- **Logging**: Use Python standard library logging with clear levels
- **Security**: Never log sensitive data, validate inputs, use environment variables
- **Performance**: Focus on readability over optimization
- **Testing**: Focus on critical business logic, mock external integrations

## Reference Documentation

For detailed implementation examples and patterns, see:

- **[Testing Patterns](./examples/testing-patterns.md)** - PyTest, Jest, Storybook, and
  Playwright examples
- **[Component Patterns](./examples/component-patterns.md)** - shadcn/ui
  implementation guides
- **[Domain Architecture](./examples/domain-architecture.md)** - DDD patterns
  and code examples
- **[API Patterns](./examples/api-patterns.md)** - REST and MCP implementation
  guides
- **[Configuration Examples](./examples/configuration/)** - Docker, environment,
  and deployment configs

## Key Reminders

1. **Check with user** before making technology choices or architectural changes
2. **Start simple** - implement core functionality before optimizations
3. **Test thoroughly** - write tests as you build, not after. Ideally before
   implementing.
4. **Document decisions** - update architecture docs when patterns evolve
