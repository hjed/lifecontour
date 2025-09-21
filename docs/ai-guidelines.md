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

- **Backend**: Python 3.11+ with FastAPI, PostgreSQL database, Dishka for dependency injection
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
4. **Domain-Driven Architecture**: Core domains with isolated integration workers
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
6. **Linting & Type Checking** - Ensure no linting or type errors
7. **Deploy and Validate** - Confirm feature works in real environment

### Feature-Complete Iterations

- Each iteration delivers working, testable functionality end-to-end
- **Tests drive the design** - write tests to define interfaces and behavior first
- Test each layer independently and together during development
- Run linting, type checking, and all tests before considering any change complete
- Isolated integration workers developed separately from core domains
- Architecture can evolve - check technology choices with user before acting

### AI Context Management for Integration Workers

When working on integration workers, provide focused context to avoid confusion:

**For Integration Worker Tasks:**
- Provide the full contents of the specific worker directory (e.g., `integration_workers/strava/`)
- Include relevant models from `core_shared/` package
- Include `docs/architecture/integration-architecture.md` for patterns
- **Do NOT** include other integration workers or core application code

**Example Context for Strava Integration:**
```
Files to include:
- integration_workers/strava/ (complete directory)
- core_shared/models/ (relevant models only)
- docs/architecture/integration-architecture.md
```

This provides complete, isolated context without noise from other integrations.

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

### ⚠️ CRITICAL: Test Data Setup Requirements

**NEVER write tests that accept multiple outcomes or skip based on data state.**

#### ❌ FORBIDDEN Test Patterns

```typescript
// NEVER accept multiple outcomes
expect(hasContacts || hasEmptyState).toBe(true); // Meaningless test

// NEVER skip based on data state
if (contactCount === 0) {
  test.skip('No contacts found');
}

// NEVER use try-catch to suppress test failures
try {
  await testFeature();
} catch {
  console.log('Test skipped - data not available');
}

// NEVER write conditional test logic
if (tagCount > 0) {
  // Test with tags
} else {
  // Test without tags - this makes tests non-deterministic
}
```

#### ✅ REQUIRED Test Patterns

```typescript
// ALWAYS set up exact test data needed
test('should display contacts when they exist', async ({ page }) => {
  const { testData } = createTestHelpers(page);

  // Set up exactly what this test needs
  await testData.setupAuthenticatedUser();
  await testData.createTestContacts([
    { firstName: 'John', lastName: 'Doe' },
    { firstName: 'Jane', lastName: 'Smith' },
  ]);

  // Test expects exactly 2 contacts
  const contacts = await page.locator('[data-testid="contact-card"]');
  expect(await contacts.count()).toBe(2);
});

// ALWAYS have separate tests for different scenarios
test('should display empty state when no contacts exist', async ({ page }) => {
  const { testData } = createTestHelpers(page);

  // Set up empty state
  await testData.setupAuthenticatedUser();
  // Don't create any contacts

  // Test expects empty state
  const emptyState = page.locator('text=/no contacts/i');
  await expect(emptyState).toBeVisible();
});
```

#### Test Data Setup Rules

1. **Each test creates its own data** - Use `testData.createTestContacts()`, `testData.createTestTags()`, etc.
2. **Tests are deterministic** - Each test knows exactly what data exists
3. **No conditional logic** - Tests must not have if/else based on data state
4. **No skipping** - Tests must not skip based on what data they find
5. **Separate scenarios** - Different tests for empty vs populated states
6. **Clean authentication** - Use `testData.setupAuthenticatedUser()` for auth setup

## Language Rules

### Python

- **Formatting**: ruff-format
- **Linting**: ruff with comprehensive rule set
- **Type Hints**: Required for all functions and methods (mypy enforced)
- **Import Organization**: ruff handles import sorting
- **Naming**: snake_case for variables/functions, PascalCase for classes
- **No Inline Imports**: No `from module import specific_thing` allowed inside functions or classes

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
- **Accessibility**: ARIA attributes, keyboard navigation, screen reader support
- **Clear Separation**: Independent test suites for backend and frontend

### Code Quality Checks

**Always run quality checks before completing any task:**

```bash
# Frontend quality checks (run from frontend/)
pnpm quality:check    # Check formatting, linting, and types
pnpm quality:fix      # Auto-fix formatting and linting issues

# Individual checks
pnpm format:check     # Prettier formatting check
pnpm format           # Auto-format code
pnpm lint             # ESLint check
pnpm lint:fix         # Auto-fix ESLint issues
pnpm type-check       # TypeScript type checking
```

**Quality check failures must be fixed before task completion.**

### Pre-commit Hook Setup and Troubleshooting

**NEVER use `git commit --no-verify` to bypass pre-commit hooks.**

All commits must pass the full verification pipeline. If pre-commit hooks fail, fix the underlying issues rather than bypassing them.

#### Pre-commit Hook Installation and Fixes

If pre-commit hooks are failing with Python environment issues:

```bash
# Install pre-commit using uv (fixes Python version issues)
uv tool install pre-commit --force

# Install hooks in the repository
pre-commit install

# Test all hooks
pre-commit run --all-files
```

**Common Issue**: If you see `/usr/bin/env: 'python': No such file or found` or similar Python path errors, it means pre-commit was installed with an incompatible Python version (e.g., Python 2). The solution is to reinstall pre-commit using uv as shown above.

**Verification Process**:
- All backend Python code must pass: `ruff format`, `ruff check`, `mypy`
- All frontend code must pass: `prettier`, `eslint`, `typescript check`
- All general checks must pass: trailing whitespace, YAML/JSON/TOML validation, merge conflict detection

### Integration Testing Patterns

- **Docker PostgreSQL**: Use `docker-compose.test.yml` for real database testing
- **Transaction Isolation**: Each test runs in isolated transaction with rollback
- **Schema Recreation**: Fresh database schema for each test session
- **Real Constraints**: Test actual database constraints and SQL behavior
- **Performance Validation**: Verify query performance with real data
- **Reuse Fixtures**: Reuse test fixtures across tests as much as possible for simplicity

### Test Organization and Fixture Usage

**CRITICAL: Always use the correct test fixtures for the test type:**

- **Unit Tests** (`tests/unit/`): Use `tests/conftest.py` fixtures for fast, isolated testing
  - Uses mock databases
  - Fast execution, no external dependencies
  - Suitable for business logic and API schema validation

- **Integration Tests** (`tests/integration/`): Use `tests/integration/conftest.py` fixtures for real database testing
  - Uses Docker PostgreSQL on port 5433 via `docker-compose.test.yml`
  - Real database constraints and SQL behavior
  - Suitable for repository operations, service layer testing, and API endpoints that need database

**Common Mistake to Avoid:**
- ❌ **Never** create custom fixtures in integration test files that duplicate conftest.py functionality
- ❌ **Never** put integration tests that need real database in `tests/integration/**` without using proper fixtures
- ✅ **Always** use the existing `async_connection` and `clean_database` fixtures from `tests/integration/conftest.py`
- ✅ **Always** place API integration tests in the correct directory structure to inherit proper fixtures

**Example Correct Structure:**
(In the backend folder)
```
tests/
├── conftest.py                           # Unit test fixtures (fast, mocked)
├── unit/
│   ├── api/test_contact_schemas.py       # Uses unit test fixtures
│   └── contacts/test_contact_service.py  # Uses mocked dependencies
└── integration/
    ├── conftest.py                       # Integration fixtures (Docker DB)
    ├── contacts/test_contact_service_integration.py  # Uses real DB
    └── api/test_contact_endpoints.py     # Uses real DB via integration fixtures
```

_See [Testing Strategy](./architecture/testing-strategy.md) for detailed testing patterns and examples._

## Frontend Development Standards

### shadcn/ui Component Guidelines

- Use shadcn/ui components with proper TypeScript interfaces
- Minimize the use of `'use client'`, `useEffect`, and `setState`; favor React Server Components (RSC) and Next.js SSR features.
- Implement proper accessibility with ARIA attributes and screen reader support
- Follow responsive design patterns with mobile-first approach
- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`
- Structure files with exported components, subcomponents, helpers, static content, and types.

### Key Patterns

- **Cards**: Use `Card`, `CardHeader`, `CardContent` for consistent layouts
- **Forms**: Use `Form`, `FormField`, `FormControl`, `FormLabel`, `FormMessage` with react-hook-form and Zod validation for proper accessibility
- **Dropdowns**: Include keyboard navigation and proper ARIA attributes
- **Badges**: Use for tags with custom colors via style prop

### Form Accessibility Guidelines

- **Use Form system for validation**: Use `Form`, `FormField`, `FormControl`, `FormLabel`, `FormMessage` components for forms with validation and error handling
- **Use standalone Input/Textarea for simple cases**: Use standalone `Input`/`Textarea` components for search fields, filters, and non-validated inputs
- **Automatic ARIA attributes**: Form system automatically provides `aria-describedby`, `aria-invalid`, and proper ID linking
- **Error message accessibility**: `FormMessage` components automatically have proper IDs and are linked to form controls
- **Screen reader support**: Error messages are announced immediately when validation fails

### Component Usage Patterns

- **Forms with validation**: Always use the Form system (`FormField` + `FormControl` + `Input`)
- **Search inputs**: Use standalone `Input` component
- **Filter inputs**: Use standalone `Input` component
- **Simple inputs without validation**: Use standalone `Input`/`Textarea` components

_See [Frontend Design](./architecture/frontend-design.md) for detailed
shadcn/ui implementation patterns._

### Tailwind CSS Guidelines

- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`
- Follow mobile-first responsive design with `sm:`, `lg:`, `xl:` prefixes
- Leverage shadcn/ui's CSS custom properties for theming

## Development Standards

### TypeScript Configuration

- Always define interfaces for API objects, database entities, and configuration
- Use exact optional property types for better type safety
- Keep http client usage issolated to dedicated components and resources (adapter pattern)
- Never use `any` type or disable type checking. Always fix the underlying issue.

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
│   │   └── mcp/                 # MCP server implementation
│   ├── core_shared/             # Shared models, schemas, db logic (private package)
│   │   ├── pyproject.toml
│   │   └── core_shared/
│   │       ├── models/          # SQLAlchemy models
│   │       ├── database/        # Database session management
│   │       └── exceptions/      # Shared exception classes
│   ├── integration_workers/     # Isolated workers for each integration
│   │   ├── google_contacts/
│   │   │   ├── Dockerfile
│   │   │   ├── requirements.txt
│   │   │   ├── worker.py
│   │   │   └── .env.example
│   │   ├── immich/
│   │   │   ├── Dockerfile
│   │   │   ├── requirements.txt
│   │   │   ├── worker.py
│   │   │   └── .env.example
│   │   └── strava/
│   │       ├── Dockerfile
│   │       ├── requirements.txt
│   │       ├── worker.py
│   │       └── .env.example
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
|   ├── architecture/             # Detailed architecture documentation
|   |   ├── domain-architecture.md    # Domain patterns and implementation
|   |   ├── testing-strategy.md       # Testing patterns and guidelines
|   |   ├── api-design.md             # REST and MCP API patterns
|   |   ├── frontend-design.md        # Component and UI patterns
|   |   └── ...                       # Other architecture docs
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

#### Business Logic Patterns

- **Changed Fields Calculation**: Always calculate within service layer transactions for accuracy
  - ❌ **Wrong**: Calculate in controllers outside transaction
  - ✅ **Correct**: Service fetches current state and calculates changes within transaction
  - Use tuple format `(old_value, new_value)` for history service compatibility
  - Handle None values properly: `(field or "", updated_field or "")` for optional fields

- **Service Method Signatures**: Keep business logic parameters minimal
  - ❌ **Wrong**: `update_contact(contact, changed_fields, transaction)`
  - ✅ **Correct**: `update_contact(contact, transaction)` - service calculates changes internally

#### Type Checking & Validation

- **Function Signatures**: Always include return type annotations for all parameters
- **Generic Types**: Use `Union[T, U]` for multiple types, `Optional[T]` for nullable
- **Type Ignores**: Use `# type: ignore[specific-error]` sparingly with specific error codes
- **Pydantic Models**: Use for input validation, `str` instead of `PostgresDsn` for database URLs
- **Mypy Compliance**: All code must pass mypy type checking without any errors after every change

_See [Domain Architecture](./architecture/domain-architecture.md) for detailed implementation patterns._

### Dependency Injection with Dishka
 for clean, framework-agnostic dependency injection
- **Framework**: Use Dishka DI framework
- **Pattern**: Constructor injection with typed interfaces and automatic resolution
- **Domain-Based Providers**: Organize providers by domain (ContactProvider, CalendarProvider, etc.)
- **Scopes**: Use APP scope for singletons, REQUEST scope for per-request objects, SESSION for websockets
- **Type Safety**: All dependencies typed with interfaces, use `FromDishka[Type]` for injection
- **Finalization**: Proper cleanup of resources like database connections using `yield` providers
- **Testing**: Use Dishka's testing utilities for dependency overrides in tests

#### Dishka Best Practices

**Provider Organization:**
- Create domain-specific providers: `ContactProvider`, `CalendarProvider`, `JournalProvider`
- Use `Provider(scope=Scope.REQUEST)` for most business logic components
- Use `Provider(scope=Scope.APP)` for configuration, singletons, and stateless services
- Group related dependencies in the same provider class

**Database Connection Management:**
```python
class DatabaseProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def get_connection(self, engine: AsyncEngine) -> AsyncIterable[AsyncConnection]:
        async with engine.begin() as conn:
            yield conn
```

**Service and Repository Providers:**
```python
class ContactProvider(Provider):
    scope = Scope.REQUEST

    def __init__(self):
        self.provide(SqlContactRepository, provides=ContactRepository)
        self.provide(SqlTagRepository, provides=TagRepository)
        self.provide(ContactService)
        self.provide(ContactValidationService)
```

**FastAPI Integration:**
- Use `FromDishka[Type]` for dependency injection in endpoints
- Use `@inject` decorator when auto-injection is not available
- Set up Dishka with `setup_dishka(container, app)` in app factory
- Use proper lifespan management for container cleanup

**Testing with Dishka:**
- Override providers in tests using container's override mechanisms
- Use separate test providers for mock dependencies
- Maintain proper scope isolation in test fixtures

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
- **Event Flow**: Domain Service → OutboxEventPublisher → Outbox Table → Background Task → MeiliSearch

### MCP Implementation

- **FastMCP v2**: Use FastMCP v2 (jlowin/fastmcp) for MCP server implementation instead of official MCP SDK
- **Domain-Based Architecture**: Organize MCP tools by domain (contacts, journal, calendar, photos) to allow future expansion
- **Dishka Integration**: Use Dishka dependency injection in MCP tools for consistency with REST API
- **Session Authentication**: Share OAuth authentication with REST API using session middleware
- **Clear Interfaces**: Structure MCP tools with consistent, simple interfaces

#### MCP with Dishka Patterns

**MCP Tool Dependency Injection:**
```python
@mcp.tool
async def get_contact(
    contact_id: Annotated[int, Field(description="Contact ID")],
    contact_service: FromDishka[ContactService],
) -> str:
    """Get contact details by ID for AI analysis."""
    # Use injected service
```

**MCP Provider Setup:**
- Share the same Dishka container between REST API and MCP server
- Use REQUEST scope for MCP tool dependencies
- Ensure proper cleanup of resources after tool execution

### Security & Performance

- **Logging**: Use Python standard library logging with clear levels
- **Security**: Never log sensitive data, validate inputs, use environment variables
- **Performance**: Focus on readability over optimization
- **Testing**: Focus on critical business logic, mock external integrations

## Reference Documentation

For detailed implementation patterns and examples, see:

### Architecture and Design
- **[Testing Strategy](./architecture/testing-strategy.md)** - Comprehensive testing patterns for PyTest, Jest, and Playwright
- **[Frontend Design](./architecture/frontend-design.md)** - shadcn/ui component patterns and responsive design
- **[Domain Architecture](./architecture/domain-architecture.md)** - Domain-driven design patterns and implementation
- **[API Design](./architecture/api-design.md)** - REST and MCP API implementation patterns
- **[Technology Stack](./architecture/technology-stack.md)** - Technology choices and configuration
- **[Deployment Guide](./architecture/deployment-guide.md)** - Docker and deployment configuration

### Development and Operations
- **[Code Quality Standards](./code-quality-standards.md)** - Linting, formatting, and testing standards
- **[CI/CD Setup](./ci-cd-setup.md)** - Continuous integration and deployment configuration
- **[MCP Setup](./mcp-setup.md)** - Model Context Protocol integration guide

### Troubleshooting Guides
- **[Docker Development](./troubleshooting/docker-development.md)** - Complete Docker setup and development environment
- **[Docker Fixes](./troubleshooting/docker-fixes.md)** - Common Docker issues and solutions
- **[CI Integration Tests](./troubleshooting/ci-integration-tests-fix.md)** - Backend CI test configuration fixes
- **[Frontend CI Fixes](./troubleshooting/frontend-ci-fixes.md)** - Frontend CI and testing issue solutions

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

Use `./scripts/dev.sh lint` to run all checks at once.

**Note:** These are the same checks run by CI and the local dev script (`./scripts/dev.sh lint`). Pre-commit hooks auto-fix these issues before commit, while these commands verify the fixes were applied correctly.

### Common Integration Test Pitfalls

**Service Layer Changes:**

- When modifying service method signatures, update ALL calling tests (unit AND integration)

**Type Safety in Tests:**

- Use `# type: ignore` only in test files for intentional validation failures
- Never use `type: ignore` in production code - fix the underlying type issue
- Ensure service method return types match what tests expect

**Database Connection Issues:**
- Integration tests failing with "connection refused" usually means wrong fixtures
- Check that Docker containers are using correct ports (5433 for test DB, not 5432)
- Verify test files are in correct directory structure to inherit proper fixtures

**CI Integration Test Configuration:**
- CI uses GitHub Actions services instead of Docker Compose for databases
- Integration test fixtures detect CI environment via `CI` or `GITHUB_ACTIONS` env vars
- Use environment variables for database connection: `TEST_DB_HOST`, `TEST_DB_PORT`, etc.
- Local development uses Docker Compose, CI uses GitHub Actions services on different ports

### Unit Tests

**Run unit tests after writing tests and before implementation**

Run after every changes

### Integration Testing

**Run integration tests separately after quality checks pass:**

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

## Library Documentation

Your knowledge of the current versions of libraries may be out of date - refer to their documentation for best practises.

### Python Backend

- **FastAPI**: https://fastapi.tiangolo.com/
- **SQLAlchemy**: https://docs.sqlalchemy.org/en/20/
- **Dishka**: https://dishka.readthedocs.io/en/stable/_sources/index.rst.txt
- **pytest**: https://docs.pytest.org/en/7.4.x/
- **FastMCP**: https://gofastmcp.com/llms.txt

### TypeScript Frontend

- **Next.js**: https://raw.githubusercontent.com/nextjsargentina/next.js-docs/refs/heads/main/src/docs/index.mdx
- **shadcn/ui**: https://ui.shadcn.com/docs
- **Tailwind CSS**: https://tailwindcss.com/docs
- **Jest**: https://jestjs.io/docs/getting-started
- **React Testing Library**: https://testing-library.com/docs/react-testing-library/intro
- **Playwright**: https://playwright.dev/docs/intro
