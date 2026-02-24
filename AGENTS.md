# AI Development Guidelines - Personal CRM & Journal System

## Project Context

This document provides essential guidelines for AI assistants working on the Personal CRM & Journal System. The system uses a Python FastAPI backend with PostgreSQL database and TypeScript/React frontend, integrating personal data from multiple sources with both MCP (Model Context Protocol) and web interfaces.

Refer to the [architecture document](docs/architecture.md) for a high-level overview of the system architecture and navigation.

Tasks can be found in the [tasks document](docs/tasks.md).

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
## Code Quality Checks

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

### Integration Testing Patterns

- **Docker PostgreSQL**: Use `docker-compose.yml` for real database testing (with the correct profile e.g. "test")
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

## Frontend Development Standards

### shadcn/ui Component Guidelines

- Use shadcn/ui components with proper TypeScript interfaces
- Minimize the use of `'use client'`, `useEffect`, and `setState`; favor React Server Components (RSC) and Next.js SSR features.
- Implement proper accessibility with ARIA attributes and screen reader support
- Follow responsive design patterns with mobile-first approach
- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`
- Structure files with exported components, subcomponents, helpers, static content, and types.

- Leverage shadcn/ui's CSS custom properties for theming

## Development Standards

### TypeScript Configuration

- Always define interfaces for API objects, database entities, and configuration
- Use exact optional property types for better type safety
- Keep http client usage issolated to dedicated components and resources (adapter pattern)
- Never use `any` type or disable type checking. Always fix the underlying issue.

### Code Organization

#### Project Structure (Clear Language Separation)

```text
personal-management-system/
├── backend/                      # Python FastAPI application
│   ├── app/
|   |   |── core/                 # Core Domain Logic
|   |   |── infrastructure/       # Common code for Database, Events, etc.
│   │   ├── api/                  # FastAPI route handlers
│   │   ├── migrations/           # SQL queries and migrations
│   │   └── mcp/                  # MCP server implementation
│   ├── core_shared/              # Shared models, schemas, db logic (private package)
│   ├── integration_workers/      # Isolated workers for each integration
│   ├── tests/                    # pytest test suite
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
```

### Backend Development (Python)

#### Core Development Patterns

- **Test-Driven**: Write tests first, then implement to make them pass
- **Explicit SQL**: Use SQLAlchemy Core with raw SQL queries for readability
- **Simple Components**: Clear business logic without complex abstractions
- **Type Safety**: Strong type hints, mypy compliance, Pydantic models for validation
- **Clear Separation**: Keep domain logic separate from API and database concerns
- **Python Enums**: Use enums for domain values (e.g., `MethodType.EMAIL`) for type safety

#### Business Logic Patterns

- **Changed Fields Calculation**: Always calculate within service layer transactions for accuracy. Use tuple format `(old_value, new_value)` for history service compatibility.
- **Service Method Signatures**: Keep business logic parameters minimal. E.g., `update_contact(contact, transaction)` where the service calculates changes internally.

#### Dependency Injection with Dishka

- **Framework**: Use Dishka DI framework
- **Pattern**: Constructor injection with typed interfaces and automatic resolution
- **Scopes**: Use APP scope for singletons, REQUEST scope for per-request objects
- **FastAPI Integration**: Use `FromDishka[Type]` for dependency injection in endpoints

#### MCP Implementation

- **FastMCP v2**: Use FastMCP v2 (jlowin/fastmcp) for MCP server implementation instead of official MCP SDK
- **Dishka Integration**: Use Dishka dependency injection in MCP tools (`FromDishka[Type]`) for consistency with REST API

### Frontend Standards

- **React Server Components**: Minimize the use of `'use client'`, `useEffect`, and `setState`; favor React Server Components (RSC) and Next.js SSR features.
- **Forms**: Always use `Form`, `FormField`, `FormControl`, `FormLabel`, `FormMessage` components for forms with react-hook-form and Zod validation, guaranteeing proper accessibility linking automatically.

## Detailed Architecture & Development Guidelines

To avoid repetition, detailed guidelines are maintained in specialized documents in the `docs/` directory. **You must refer to these documents for specific implementation details, patterns, and rules.**

### Testing & Quality Assurance
- **[Testing Strategy](docs/architecture/testing-strategy.md)**: Comprehensive guidelines for Worker Unit Tests, Backend Tests, Frontend Tests, Testing Organization (conftest usage), E2E fixtures, and Database Integration.
- **[Code Quality Standards](docs/code-quality-standards.md)**: Strict rules for linting, formatting, type checking, Python Language Rules (ruff, mypy requirements) and pre-commit hooks. *Quality check failures must be fixed before task completion.*

### Architecture & Design
- **[Domain Architecture](docs/architecture/domain-architecture.md)**: Domain-driven design patterns, Domain Enum Patterns, Ports & Adapters implementation, business logic validation, and component structure.
- **[API Design](docs/architecture/api-design.md)**: REST and FastMCP API patterns, JSON API compliance, validation, and error handling.
- **[Integration Architecture](docs/architecture/integration-architecture.md)**: Patterns for isolated integration workers (e.g. Google, Strava).
- **[Frontend Design](docs/architecture/frontend-design.md)**: Next.js, shadcn/ui, Tailwind CSS patterns, forms, and responsive design guidelines.
- **[Database Design](docs/architecture/database-design.md)**: Database schema definitions and data layer standards.
- **[Technology Stack](docs/architecture/technology-stack.md)**: Technology choices and configuration.
- **[Deployment Guide](docs/architecture/deployment-guide.md)**: Docker and deployment configuration.

### CI/CD & Operations
- **[CI/CD Setup](docs/ci-cd-setup.md)**: Continuous integration and deployment configuration.
- **[MCP Setup](docs/mcp-setup.md)**: Model Context Protocol integration guide.

### Troubleshooting
- **[Docker Development](docs/troubleshooting/docker-development.md)**
- **[Docker Fixes](docs/troubleshooting/docker-fixes.md)**
- **[CI Integration Tests](docs/troubleshooting/ci-integration-tests-fix.md)**
- **[Frontend CI Fixes](docs/troubleshooting/frontend-ci-fixes.md)**

## Essential Reminders

1. **Tests First** - Write tests before implementation, always
2. **Check with user** before making technology or architectural changes
3. **Start simple** - implement core functionality before optimizations
4. **Document decisions** - update architecture docs when patterns evolve
5. **Quality checks mandatory** - run linting, type checking, and tests for every change

## Library Documentation

Your knowledge of the current versions of libraries may be out of date - refer to their documentation for best practises. Use context 7 where possible.

### Python Backend

- **FastAPI**: https://fastapi.tiangolo.com/ - context 7 library fastapi/fastapi
- **SQLAlchemy**: https://docs.sqlalchemy.org/en/20/
- **Dishka**: https://dishka.readthedocs.io/en/stable/_sources/index.rst.txt
- **pytest**: https://docs.pytest.org/en/7.4.x/
- **FastMCP**: https://gofastmcp.com/llms.txt - context 7 library id websites/gofastmcp
- **Alembic**: https://alembic.sqlalchemy.org/en/latest/ - context7 library id sqlalchemy/alembic

### TypeScript Frontend

- **Next.js**: https://raw.githubusercontent.com/nextjsargentina/next.js-docs/refs/heads/main/src/docs/index.mdx
- **shadcn/ui**: https://ui.shadcn.com/docs - context 7 websites/ui_shadcn
- **Tailwind CSS**: https://tailwindcss.com/docs - context 7 library websites/tailwindcss
- **Jest**: https://jestjs.io/docs/getting-started
- **React Testing Library**: https://testing-library.com/docs/react-testing-library/intro
- **Playwright**: https://playwright.dev/docs/intro
