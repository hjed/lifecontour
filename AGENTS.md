# AI Development Guidelines - Lifecontour

## Project Context

Lifecontour is a self-hosted personal CRM and journal: your journal, people and adventures —
self-hosted. The product name lives in one constant per stack (`APP_NAME` in
`frontend/src/lib/constants.ts`, `PRODUCT_NAME` in `core_shared/core_shared/product.py`); read it
from there rather than writing the name as a literal.


Refer to the [architecture document](docs/architecture.md) for a high-level overview of the system architecture and navigation.

Tasks can be found in the [tasks document](docs/tasks.md).

### Key Technologies

- **Backend**: Python 3.14+ (using uv) with FastAPI, PostgreSQL database, Dishka for dependency injection
- **Frontend**: Next.js with React, shadcn/ui components, Tailwind CSS
- **APIs**: JSON API standard for REST endpoints, MCP for AI integration
- **Authentication**: Session-based authentication with Starlette SessionMiddleware
- **Search**: MeiliSearch with event-driven indexing via transactional outbox pattern
- **Testing**: pytest (backend), React Testing Library (frontend), Playwright (e2e)

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
- **Debugging**: E2E tests should not pollute standard output. Use standard `console.debug()` for detailed logging during local debugging instead of console.log.
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

- **Docker PostgreSQL**: Use `docker-compose.yml` for real database testing with the correct profile, and prefer the runtime-backed helpers so local ports and `COMPOSE_PROJECT_NAME` are derived from the current workspace while CI stays fixed/deterministic.
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
  - Uses Docker PostgreSQL via `docker-compose.yml` with the correct profile and current-worktree-derived runtime values for local development
  - Real database constraints and SQL behavior
  - Suitable for repository operations, service layer testing, and API endpoints that need database

**Common Mistake to Avoid:**
- ❌ **Never** create custom fixtures in integration test files that duplicate conftest.py functionality
- ❌ **Never** use `DatabaseProvider(test_settings)` in test clients — this creates independent connections that bypass the savepoint and **commit data to the database**, causing state to leak between tests
- ✅ **Always** use the existing `async_connection` and `clean_database` fixtures from `tests/integration/conftest.py`
- ✅ **Always** place API integration tests in the correct directory structure to inherit proper fixtures
- ✅ **Always** inject `async_connection` into API test clients via a `TestDatabaseProvider` (see `authenticated_client` fixture in `tests/integration/conftest.py` for the correct pattern)

## Frontend Development Standards

### shadcn/ui Component Guidelines

- Use shadcn/ui components with proper TypeScript interfaces
- Minimize the use of `'use client'`, `useEffect`, and `setState`; favor React Server Components (RSC) and Next.js SSR features.
- Implement proper accessibility with ARIA attributes and screen reader support
- Use semantic color classes for dark mode support: `bg-background`,
  `text-foreground`, `border-border`
- Leverage shadcn/ui's CSS custom properties for theming

### Design System Sync (`frontend/.design-sync/`)

`frontend/.design-sync/` holds the inputs that publish this app's UI kit to
**Claude Design** (claude.ai/design), so the design agent builds screens from our
real components instead of generic ones. It is tooling configuration, **not
application code** — nothing under it is imported by the app at runtime.

Scope is the design-system surface: `components/ui/` plus the shared app chrome
(`layout/`, `navigation/`, `auth/UserMenu`, `history/`, `shared/`). Feature
components under `journals/`, `contacts/`, `integrations/`, `settings/` and
`search/` are deliberately excluded.

| Path | Purpose |
|---|---|
| `config.json` | Component list, groups, card viewports, target project |
| `ds-entry.ts` | Barrel re-exporting the real components (no `dist/` exists — this is the bundle entry) |
| `previews/<Name>.tsx` | Hand-authored preview cards, one named export per card cell |
| `preview-providers.tsx` | Mock Next-router / auth / query context so app chrome renders outside Next |
| `process-shim.ts` | Browser `process` shim — **must stay the first import** in the two entries |
| `preview.css` | Tailwind entry + `@source inline(...)` safelist |
| `prepare.mjs` | Generates the compiled CSS and the `.d.ts` tree (`cfg.buildCmd`) |
| `conventions.md` | Prepended to the generated README; tells the design agent how to build with the kit |
| `docs/<Name>.md` | Group-assignment stubs |
| `NOTES.md` | **Read this first** — repo-specific gotchas and re-sync risks |

**To re-sync**, run `/design-sync` from the repo — it is incremental and reuses
everything above. Do not hand-edit `ds-bundle/`; it is generated output.

**When adding a design-system component**, add it in three places or it stays
invisible to the sync: `ds-entry.ts`, `componentSrcMap` in `config.json`, and a
`docs/<Name>.md` group stub. Then author `previews/<Name>.tsx`.

Two constraints that bite if forgotten (both explained in `NOTES.md`):

- Run `node .design-sync/prepare.mjs` **before** each build, and again after
  editing previews — Tailwind only emits utilities it can see.
- Keep `.design-sync/` Prettier-clean, and format **before** grading previews:
  reformatting a preview changes its source hash and clears its verification.

Generated and gitignored: `ds-bundle/`, `.ds-sync/`, `types/`, `index.d.ts`,
`.design-sync/.cache/`.

## Development Standards

### TypeScript Configuration

- Always define interfaces for API objects, database entities, and configuration
- Use exact optional property types for better type safety
- Keep http client usage issolated to dedicated components and resources (adapter pattern)
- Never use `any` type or disable type checking. Always fix the underlying issue.

### Code Organization

#### Project Structure (Clear Language Separation)

```text
lifecontour/
├── backend/                      # Python FastAPI application
├── core_shared/              # Shared python models, schemas, db logic (private package)
├── integration_workers/      # Isolated workers for each integration
├── frontend/                     # Next.js TypeScript application
|── docker-compose.yml            # Multi-container setup
|── docs/                         # All documentation
```

### Backend Development (Python)

#### Core Development Patterns

- **Test-Driven**: Write tests first, then implement to make them pass
- **Simple Components**: Clear business logic without complex abstractions
- **Clear Separation**: Keep domain logic separate from API and database concerns
- **Python Enums**: Use enums for domain values (e.g., `MethodType.EMAIL`) for type safety

#### Business Logic Patterns

- **Changed Fields Calculation**: Always calculate within service layer transactions for accuracy. Use tuple format `(old_value, new_value)` for history service compatibility.
- **Service Method Signatures**: Keep business logic parameters minimal. E.g., `update_contact(contact, transaction)` where the service calculates changes internally.
- **Transactions (commit-as-you-go)**: The request `AsyncConnection` does **not** auto-commit at teardown (that runs after the response is sent — the read-after-write race in #945); the connection provider never commits — on close it rolls back any still-open transaction (typically read-only, but also an uncommitted write if a path forgot its `unit_of_work`). Commit writes **before the response** as an explicit unit of work in the **service layer**: decorate the write method with `@transactional` or wrap it in `async with unit_of_work(connection):` (from `app/infrastructure/unit_of_work.py`). It is re-entrant (only the outermost commits) and uses SAVEPOINTs under the test fixture. Use `savepoint(connection)` for batch loops that skip-and-continue on per-item failure. **Reads** use no transaction helper; **controllers never open transactions**. **MCP tools** are controller-equivalent and must **not** open transactions: call a `@transactional` service that owns the commit. There is **no commit backstop** — a write that forgets its unit of work is discarded at teardown (surfacing the bug), not silently committed. See [Database Design → Transaction Management](docs/architecture/database-design.md#transaction-management--commit-timing).

#### Dependency Injection with Dishka

- **Framework**: Use Dishka DI framework
- **Pattern**: Constructor injection with typed interfaces and automatic resolution
- **Scopes**: Use APP scope for singletons, REQUEST scope for per-request objects
- **FastAPI Integration**: Use `FromDishka[Type]` for dependency injection in endpoints

### Frontend Standards

- **React Server Components**: Minimize the use of `'use client'`, `useEffect`, and `setState`; favor React Server Components (RSC) and Next.js SSR features.
- **Forms**: Always use `Form`, `FormField`, `FormControl`, `FormLabel`, `FormMessage` components for forms with react-hook-form and Zod validation, guaranteeing proper accessibility linking automatically.

## CI for PR Stacks

**Only the bottom layer of a PR stack runs CI. This is deliberate, to save Actions budget. Do not change it.**

GitHub runs workflows for every PR in a native stack as if it targeted `main`, so without a gate each push to any layer ran the full suite (E2E included). The `changes` job in `.github/workflows/ci.yml` therefore runs only for the **lowest unmerged** layer (`github.event.pull_request.stack.base.ref == github.event.pull_request.base.ref`), non-stacked PRs, and pushes. Every other job `needs: changes`, so on upper layers they all show as skipped.

- ❌ **Never** remove or loosen that gate, or add a trigger/job that runs CI for upper layers automatically.
- ❌ **Never** add a job without `needs: changes` (directly or through another job) — it would escape the gate.
- ✅ To run CI on an upper layer, trigger it manually: `gh workflow run ci.yml --ref <branch>`. It tests the branch head and path-filters against `main`, so it covers the layers below too.
- Re-running a skipped PR run does **not** help — a re-run reuses the original event and skips again.
- When the PR below merges, the retarget fires no CI event: the new bottom layer runs CI on its next push (e.g. the `gh stack` rebase), or dispatch it manually.

See [CI/CD Setup → Stacked PRs](docs/ci-cd-setup.md#stacked-prs).

## Detailed Architecture & Development Guidelines

To avoid repetition, detailed guidelines are maintained in specialized documents in the `docs/` directory. **You must refer to these documents for specific implementation details, patterns, and rules.**

### Testing & Quality Assurance
- **[Testing Strategy](docs/architecture/testing-strategy.md)**: Comprehensive guidelines for Worker Unit Tests, Backend Tests, Frontend Tests, Testing Organization (conftest usage), E2E fixtures, and Database Integration.
- **[Code Quality Standards](docs/code-quality-standards.md)**: Strict rules for linting, formatting, type checking, Python Language Rules (ruff, mypy requirements) and pre-commit hooks. *Quality check failures must be fixed before task completion.*
For e2e tests use Playwright best practices: avoid force:true, add typing delays for ProseMirror/contenteditable inputs, and validate on Mobile Chrome when Firefox is unsupported locally. The E2E projects are `firefox` and `Mobile Chrome` — desktop `chromium` was removed to cut CI cost.

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
