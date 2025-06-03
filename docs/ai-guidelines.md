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
- **Authentication**: Session-based authentication with Starlette SessionMiddleware
- **Search**: MeiliSearch with event-driven indexing via transactional outbox pattern
- **Testing**: pytest (backend), React Testing Library (frontend), Playwright (e2e)
- **Integrations**: Google Calendar/Contacts, Immich photos
- **Deployment**: Docker with nginx proxy support

### Core Principles

1. **Test-First Development**: Write tests before implementation - no exceptions
2. **Clear Language Separation**: Python backend, TypeScript frontend
3. **AI-Optimized**: Design for AI assistant understanding over performance
4. **Domain-Driven Architecture**: Core domains with separate integration sub-domains
5. **Agile Development**: Feature-complete iterations delivering incremental value
6. **Simple Dependencies**: Standard libraries over complex abstractions

## Test-First Development Approach

### Mandatory Test-First Workflow

**EVERY feature must follow this exact sequence - no exceptions:**

1. **Write Tests First** - Define expected behavior through tests before any implementation
2. **Run Tests** - Verify they fail (red phase of TDD)
3. **Implement Minimum Code** - Write just enough code to make tests pass (green phase)
4. **Refactor** - Improve code while keeping tests passing (refactor phase)
5. **Integration** - Ensure all layers work together
6. **Deploy and Validate** - Confirm feature works in real environment

### Feature-Complete Iterations

- Each iteration delivers working, testable functionality end-to-end
- **Tests drive the design** - write tests to define interfaces and behavior first
- Test each layer independently and together during development
- Run linting, type checking, and all tests before considering any change complete
- Integration sub-domains developed separately from core domains
- Architecture can evolve - check technology choices with user before acting

### Test-Driven Development Sequence

1. **Documentation** - Document planned changes and confirm design decisions
2. **Write Tests** - Unit tests for domain logic, integration tests for database operations
3. **Backend Domain Logic** - Python business logic guided by failing tests
4. **Database Operations** - SQL queries with SQLAlchemy Core, tested with real PostgreSQL
5. **API Endpoints** - FastAPI controllers with JSON API compliance, API tests included
6. **Frontend UI** - Next.js interface using shadcn/ui, component tests included
7. **MCP Tools** - AI integration via Model Context Protocol, integration tests included
8. **End-to-End Tests** - Full user workflows with Playwright
9. **Deploy and Validate** - Ensure feature works in real environment

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
|   |   |   |── search/          # MeiliSearch integration
|   |   |   |── events/          # Outbox pattern implementation
|   |   |   |── auth/            # Session management
│   │   ├── api/                 # FastAPI route handlers
│   │   |   ├── auth/            # Authentication endpoints
│   │   |   ├── contacts/        # Contact CRUD endpoints
│   │   |   ├── search/          # Search endpoints
│   │   |   ├── dependencies.py  # Service factories and DI
│   │   |   └── schemas/         # Pydantic request/response models
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

#### Core Development Patterns

- **Test-Driven**: Write tests first, then implement to make them pass
- **Explicit SQL**: Use SQLAlchemy Core with raw SQL queries for readability
- **Simple Components**: Clear business logic without complex abstractions
- **Type Safety**: Strong type hints, mypy compliance, Pydantic models for validation
- **Clear Separation**: Keep domain logic separate from API and database concerns
- **Python Enums**: Use enums for domain values (e.g., `MethodType.EMAIL`) for type safety

#### Database & Error Handling

- **Database Operations**: Explicit SQL with SQLAlchemy text(), parameterized queries for security
- **Transaction Management**: Handle at domain/business layer, pass connections to repositories
- **Constraint Validation**: Use database constraints, catch `IntegrityError` and convert to domain exceptions
- **Error Handling**: Custom exceptions with HTTP status codes, exception chaining with `from e`
- **Integration Testing**: Test real database operations with Docker PostgreSQL

#### Type Checking & Validation

- **Function Signatures**: Always include return type annotations for all parameters
- **Generic Types**: Use `Union[T, U]` for multiple types, `Optional[T]` for nullable
- **Type Ignores**: Use `# type: ignore[specific-error]` sparingly with specific error codes
- **Pydantic Models**: Use for input validation, `str` instead of `PostgresDsn` for database URLs
- **Mypy Compliance**: All code must pass mypy type checking without any errors after every change

_See [Domain Architecture](./examples/domain-architecture.md) for detailed patterns._

### Dependency Injection

- **Pattern**: Constructor injection with typed interfaces
- **Framework**: Use FastAPI's built-in `Depends` system for service injection
- **Service Factories**: Create service factory functions for clean dependency management
- **Repositories**: Receive database connections as constructor parameters
- **Services**: Receive repository interfaces as constructor parameters
- **Simple Container**: Use basic factory pattern, avoid complex DI frameworks
- **Type Safety**: All dependencies typed with interfaces for clarity

### API Design

- **JSON API Compliance**: Follow JSON API specification for REST endpoints
- **Authentication**: Session-based authentication with Starlette SessionMiddleware
- **Input Validation**: Use Pydantic models for all request validation
- **Error Responses**: Return structured JSON API error format
- **Pagination**: Implement simple pagination for large datasets
- **Search Endpoints**: Domain-specific search endpoints (e.g., `/api/contacts/search`)
- **Global Search**: Cross-domain search endpoint (`/api/search`) designed for future expansion

### Search and Event Processing

- **Search Engine**: MeiliSearch with event-driven indexing
- **Outbox Pattern**: Transactional outbox for reliable event publishing
- **Background Processing**: FastAPI background tasks every 10 seconds
- **Performance Target**: <50ms search response times
- **Event Flow**: Domain Service → OutboxEventPublisher → Outbox Table → Background Task → MeiliSearch
- **Search Features**: Typo tolerance, highlighting, faceted search, pagination
- **Error Handling**: MeiliSearch failures cause search endpoints to fail (no graceful degradation)

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

## Test-First Quality Assurance

### Mandatory Pre-Implementation Workflow

**BEFORE writing any implementation code:**

1. **Write Tests First** - Define expected behavior through tests
2. **Run Tests** - Verify they fail appropriately (red phase)
3. **Write Minimum Implementation** - Make tests pass (green phase)
4. **Refactor** - Improve code while keeping tests passing
5. **Run All Quality Checks** - Ensure no regressions

### Mandatory Quality Checks

**Run these checks after every code change - no failures acceptable:**

```bash
# Backend
cd backend
mypy .
ruff check .
ruff format --check .
python scripts/run_integration_tests.py

# Frontend
cd frontend
pnpm type-check
pnpm lint
```

### CI/CD Compliance

- **All tests must pass** before considering any change complete
- **Type errors are blocking** - all mypy and TypeScript errors must be resolved
- **Fix linting errors immediately** - no suppressions without justification
- **Integration tests required** for database schema or API changes

## Essential Reminders

1. **Tests First** - Write tests before implementation, always
2. **Check with user** before making technology or architectural changes
3. **Start simple** - implement core functionality before optimizations
4. **Document decisions** - update architecture docs when patterns evolve
5. **Quality checks mandatory** - run linting, type checking, and tests for every change
