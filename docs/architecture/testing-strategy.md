# Testing Strategy - Personal CRM & Journal System

This document provides comprehensive testing patterns and strategies for the Personal CRM & Journal System with its Isolated Worker Architecture.

## Testing Strategy for Isolated Worker Architecture

The system's Isolated Worker Architecture requires a specialized testing approach that accounts for the distributed nature of integrations.

### Three-Tier Testing Strategy

#### 1. Worker Unit Tests
**Scope**: Individual integration worker logic in isolation
**Location**: `integration_workers/{integration_name}/tests/`
**Execution**: `cd integration_workers/google && pytest`

**Characteristics**:
- Test worker's internal logic and business rules
- Mock external API clients (Google, Strava, etc.)
- Mock `core_shared` database functions
- No Docker, Redis, or real database required
- Fast execution for rapid development feedback

**Example**:
```python
# integration_workers/google/tests/test_sync_service.py
@pytest.fixture
def mock_google_client():
    return Mock(spec=GoogleClient)

@pytest.fixture
def mock_db_session():
    return Mock(spec=Session)

def test_sync_contact_creates_new_contact(mock_google_client, mock_db_session):
    # Test sync logic without external dependencies
    pass
```

**Shared ARQ lifecycle factory in worker tests (ITER14-002)**

Each worker's ARQ `WorkerSettings` is built from the shared `core_shared` toolkit
(`SharedARQWorkerSettings` defaults, `build_worker_lifecycle`, `generate_cron_jobs`,
`redis_settings_from_url`). Because arq's `get_kwargs` reads only the *leaf* class's
attributes (inherited shared defaults are invisible to arq and fall back to arq's own
constructor defaults), worker settings tests assert against `arq.worker.get_kwargs(...)`
rather than raw class attributes — this surfaces what arq actually consumes (e.g. a
`health_check_interval` that must be redeclared on the leaf to take effect).

- **Settings unit tests** verify the migrated `WorkerSettings` exposes the expected
  `functions`, `queue_name`, redis settings, and documented overrides, and that lifecycle
  hooks delegate to `build_worker_lifecycle` (asserted by patching
  `core_shared.build_worker_lifecycle` and checking the `close_session_factory` /
  `log_consumer_errors` options and the consumer factory wiring). They also assert the
  duplicated `_parse_redis_url`/`_generate_cron_jobs`/`startup`/`shutdown` helpers are gone.
- **Lifecycle integration tests** (`tests/integration/test_worker_lifecycle_integration.py`)
  exercise the factory's `on_startup`/`on_shutdown` against real Redis + Postgres: startup
  builds the session factory and launches the stream-consumer task, a trivial ARQ job runs
  against the database, and shutdown cancels/reaps the consumer task with no leaked
  background task.

**Shared worker test fixtures — `core_shared.testing` (ITER14-005)**

The common unit-test scaffolding every worker used to hand-roll lives once in
`core_shared/core_shared/testing/`, exposed as a **pytest plugin**. A worker test suite
opts in by adding one line to its top-level `conftest.py`:

```python
# integration_workers/<worker>/tests/conftest.py
pytest_plugins = ["core_shared.testing"]
```

After that, these fixtures are available as test arguments (the matching `make_*` factory
helpers are importable from `core_shared.testing` for tests that need several instances or
deeper overrides):

| Fixture | Helper | Provides |
|---------|--------|----------|
| `mock_redis` | `make_mock_redis()` | An `AsyncMock` `redis.asyncio.Redis` double with every stream op the `StreamClient`/`StreamConsumer` use pre-seeded — scalar ops (`xadd`, `xack`, `xgroup_create`, `ping`, `xlen`) and the list-returning reads (`xreadgroup`, `xpending_range`, `xclaim`, `xinfo_groups` → `[]`) so a full consumer loop, including the retry-pending path, runs without extra setup. |
| `worker_settings` | `make_worker_settings(settings_cls=..., **overrides)` | A real, deterministic `BaseWorkerSettings` (or a worker subclass) with a valid `SecretStr` database URL and `_env_file=None` so no ambient `.env` leaks in. |
| `session_factory_mock` | `make_session_factory_mock()` | A mock async session factory: `async with factory() as session` yields an `AsyncMock` session, and `factory.close` is an awaitable matching what `build_worker_lifecycle` closes on shutdown. |
| `arq_ctx` | `make_arq_ctx(**overrides)` | An ARQ `ctx` dict primed with the lifecycle keys (`session_factory`, `settings`); merge in overrides or a `stream_consumer_task`. |

The fixtures are synchronous-construction (they return ready-made objects), so they work
under pytest-asyncio's STRICT mode without `@pytest_asyncio.fixture`. They are self-tested in
`core_shared/tests/unit/test_testing_fixtures.py`, with a worker-shaped example driving
`build_worker_lifecycle` purely on these fixtures in
`core_shared/tests/unit/test_sample_worker_style.py`. Per-worker `conftest.py` keeps only its
integration-specific fixtures.

A worker registers the unit plugin in its **top-level** `tests/conftest.py` (this is required —
`pytest_plugins` is only honoured in the top-level conftest, never a nested one):

```python
# integration_workers/<worker>/tests/conftest.py
pytest_plugins = ["core_shared.testing"]
```

**Shared worker *integration* fixtures — `core_shared.testing.integration` (ITER14-005)**

The database scaffolding every worker hand-rolled in its
`tests/integration/conftest.py` — a per-test `async_engine`, a session-scoped autouse
`apply_migrations` (`alembic upgrade head`), a savepoint-wrapped `async_connection`, and a
savepoint `db_session` — lives once in `core_shared/core_shared/testing/integration.py`, together
with the `get_workspace_env` / `get_async_database_url` / `get_repo_root` helpers that derive the
workspace-isolated test database.

These are consumed **by import, not via `pytest_plugins`**. A worker's
`tests/integration/conftest.py` imports the fixtures it needs (and re-exports them via `__all__`
so the linter sees them as used):

```python
# integration_workers/<worker>/tests/integration/conftest.py
from core_shared.testing.integration import (
    apply_migrations,
    async_connection,
    async_engine,
    db_session,
)

__all__ = ["apply_migrations", "async_connection", "async_engine", "db_session"]
```

Importing (rather than registering a plugin) is deliberate: `apply_migrations` is
`autouse=True, scope="session"`, and importing it into the integration conftest keeps it scoped
to the **integration subtree** only — a `pytest_plugins` registration would be global and force
every unit-test session to run `alembic upgrade head`. Each worker keeps only its
worker-specific environment preamble (e.g. `ENCRYPTION_KEY`, client credentials) in that
conftest. Test modules needing the helpers import them from `core_shared.testing.integration`
directly. The pure helpers are unit-tested in `core_shared/tests/unit/test_testing_integration.py`;
the DB fixtures are validated by every worker's integration suite.

#### 2. Core Application Tests
**Scope**: Core FastAPI application without integration workers
**Location**: `backend/tests/`
**Execution**: Standard pytest in backend directory

**Characteristics**:
- Mock ARQ task queue client (`arq.enqueue_job`)
- Test that correct tasks are enqueued with correct parameters
- Do NOT test worker execution - only task scheduling
- Use existing unit/integration test patterns

**Example**:
```python
# backend/tests/integration/api/test_sync_endpoints.py
@pytest.fixture
def mock_arq_client():
    return Mock(spec=ArqRedis)

async def test_trigger_google_sync_enqueues_task(client, mock_arq_client):
    response = await client.post("/api/integrations/google/sync")
    assert response.status_code == 202
    mock_arq_client.enqueue_job.assert_called_once_with(
        'sync_google_contacts',
        user_id=123
    )
```

#### 3. End-to-End (E2E) Integration Tests
**Scope**: Full system including core app + workers + infrastructure
**Location**: `tests/e2e/`
**Execution**: Dedicated E2E test environment

**Characteristics**:
- Uses `docker-compose.e2e.yml` with all services
- Tests complete data flow from API call to database changes
- Polls database to verify worker execution results
- Tests real integration between all components
- Slower execution but comprehensive validation

**Example**:
```python
# tests/e2e/test_google_sync.py
async def test_google_full_sync():
    # 1. Trigger sync via API
    response = await api_client.post("/api/integrations/google/sync")
    assert response.status_code == 202

    # 2. Wait for worker to process
    await asyncio.sleep(5)

    # 3. Verify database changes
    contacts = await db.execute("SELECT * FROM contacts WHERE source = 'google'")
    assert len(contacts) > 0

    # 4. Verify sync metadata
    sync_data = await db.execute("SELECT * FROM sync_metadata WHERE integration_source = 'google'")
    assert len(sync_data) > 0
```

### Testing Workflow

1. **Worker Unit Tests**: Fast feedback during worker development
2. **Core App Tests**: Verify task scheduling and API contracts
3. **E2E Tests**: Validate complete system integration
4. **Run All**: Comprehensive validation before deployment

### Test Execution Concurrency

To support multi-worktree local development without port or container name clashes, the testing environments (E2E and Backend Integration) dynamically allocate Docker resources:

- **Dynamic Ports & Container Names**: A Python script (`scripts/workspace_env.py`) deterministically hashes the absolute workspace path to generate a unique integer offset.
- **Isolation**: Container names are prefixed with `pms_test_{offset}-` and host ports are shifted by `{offset} * 10`. For example, `DB_PORT` becomes `5433 + (offset * 10)`.
- **CI Compatibility**: In environments where `CI=true` or `GITHUB_ACTIONS=true` is set, the offset always evaluates to `0`, ensuring CI workflows run reliably on the standard default ports.

**Execution:**
Simply run `pnpm test:e2e` in `frontend/` or `python scripts/run_integration_tests.py` in `backend/` from any concurrent worktrees. The testing frameworks and `docker-compose.yml` automatically ingest these derived parameters to avoid collisions.


## Backend Testing with pytest

### pytest Configuration Guidelines

- Use `pyproject.toml` for pytest configuration with UV dependency management
- Focus on critical business logic rather than arbitrary coverage percentages
- Organize tests with clear markers (unit, integration, e2e)
- Use descriptive test file naming patterns
- Configure coverage reporting for CI/CD pipeline integration

### Unit Testing Patterns

- Use `@pytest.fixture` for test dependencies and setup
- Mock external dependencies with `pytest-mock` and `AsyncMock`
- Follow Arrange-Act-Assert pattern for clear test structure
- Group related tests together into test classes and suites
- Group tests by scenario aspect together as well
- Use descriptive test method names that explain the scenario
- Test both success and error scenarios comprehensively
- Use `@pytest.mark.asyncio` for async tests with pytest-asyncio

### API Integration Testing Guidelines

- Use `TestClient` for FastAPI endpoint testing
- Create fixtures for test database and client setup
- Test both success and error response scenarios
- Verify JSON API response format compliance
- Assert correct HTTP status codes
- Test validation error handling
- Use realistic test data

### MCP Integration Testing Guidelines

MCP tools are tested through the mounted app (`authenticated_lifespan_client`),
speaking the **sessionless `2026-07-28` protocol** that current clients
negotiate — see [MCP Setup → Protocol Versions](../mcp-setup.md#protocol-versions).
There is no `initialize` handshake and no `mcp-session-id`; use the helpers in
`backend/tests/integration/mcp/http_helpers.py`:

- `call_mcp_tool(client, tool_name, arguments)` — call a tool and return its
  JSON payload. Prefer it for ordinary tool tests.
- `sessionless_mcp_request(method, params)` with
  `sessionless_mcp_headers(method, name)` — build a raw request when the test
  needs the HTTP response itself (status code, headers, an `isError` body).
  The headers must name the same method and tool as the body, or the server
  rejects the request.
- `extract_mcp_json_payload(response.text)` — unwrap the tool's payload from a
  raw response.

Handshake-era (session-based) requests appear only in
`tests/integration/mcp/test_mcp_protocol_eras.py`, which pins that older
clients keep working; don't add session handling to other tests.

## Frontend Testing with React Testing Library

### Component Testing Guidelines

- Use `render` and `screen` for component testing
- Test component rendering with realistic props
- Verify user interactions with `fireEvent`
- Use `getByRole` and `getByText` for element queries
- Mock callback functions with `jest.fn()`
- Test accessibility with proper role attributes
- Focus on user behavior rather than implementation details

## End-to-End Testing with Playwright

### Advanced Fixture-Based Testing System

**🎯 MAJOR MILESTONE**: Complete fixture-based testing system with real OAuth authentication and deterministic data management.

> 📚 **Complete Documentation**: See [`frontend/tests/e2e/FIXTURE_SYSTEM_GUIDE.md`](../../frontend/tests/e2e/FIXTURE_SYSTEM_GUIDE.md) for comprehensive documentation, examples, and best practices.

#### Key Features

- ✅ **Real OAuth Authentication**: Authentic OAuth flows with Hydra provider
- ✅ **Worker-Scoped Performance**: OAuth once per worker, not per test
- ✅ **Deterministic Data**: Advanced fixture system eliminates conditional logic
- ✅ **Automatic Cleanup**: Zero test pollution with dependency tracking
- ✅ **Scalable Datasets**: From 5 contacts (smoke tests) to 500 contacts (performance tests)
- ✅ **Data Factories**: Realistic test data generation with customization

#### Available Fixtures

**Authentication Fixtures:**
- `authenticatedPage`: Real OAuth-authenticated page
- `unauthenticatedPage`: Clean unauthenticated state

**Dataset Fixtures:**
- `smallDataSet`: 5 contacts, 3 tags - quick smoke tests
- `mediumDataSet`: 20 contacts, 8 tags - comprehensive testing
- `largeDataSet`: 100 contacts, 15 tags - performance testing
- `searchTestData`: Optimized for search functionality testing
- `favouritesTestData`: Mix of favourite/regular contacts
- `performanceTestData`: 500 contacts, 50 tags - stress testing

**Specialized Fixtures:**
- `favouriteContacts`: Only favourite contacts
- `contactsWithoutTags`: Guaranteed untagged contacts
- `dataFactory`: Access to all data generation factories

### E2E Testing Guidelines

- Test complete user workflows from start to finish
- Use `data-testid` attributes for reliable element selection
- Test Australian localization (DD/MM/YYYY dates)
- Use fixture-based testing for deterministic scenarios
- Verify error handling and user feedback
- Test responsive design across different screen sizes
- Include accessibility testing in E2E flows

### The AI Daily Summary in E2E

The e2e stack has no Gemini key. It sets `ENABLE_TEST_DAILY_SUMMARY_STUB=true` (`.env.test`,
passed through `docker-compose.yml`), which makes `DailySummaryService` answer with the fixed
sentence `DAILY_SUMMARY_STUB_TEXT` (`backend/app/infrastructure/di/journal.py`) instead of calling a
model — so a *generated* summary can be created from fixtures. The flag reaches daily summaries only:
contact summaries and similarity assessment still see an unconfigured AI. It defaults to `false` and
must never be set outside test/CI.

Four rules follow from a summary being **one row per user per day**, shared by the whole run:

- **Establish the summary state a test asserts; never inherit it.** Press Regenerate until the
  regeneration's own response says `generated` — a journal or task seeded moments before invalidates
  the day asynchronously, and an invalidation landing mid-generation makes the persist guard keep the
  row pending, so a single press is not deterministic.
- **Read the server's summary state from `GET /api/home-dashboard`**, which never writes. The
  daily-summary `GET` regenerates what it reads, so polling it changes the thing being observed.
- **Before a load that must not be overtaken, wait for every invalidation to land, not the first.**
  The outbox relay publishes on a poll, so a test's writes reach the summary-invalidation consumer
  as one burst, and "today reads stale" is already true after the burst's first invalidation. The
  rest then overtake the page's generating read. `waitForDomainEventsSettled(page,
  SUMMARY_INVALIDATION_GROUP)` (`tests/e2e/utils/domain-events.ts`) waits until
  `GET /api/health/outbox-backlog` reports nothing unrelayed and, after that,
  `GET /api/health/consumer-lag` reports no `lag` or `pending` for the group. After it returns,
  assert the stale state once rather than polling for it.
- **Clear the day before asserting its journal count.** The summary counts every journal on the day,
  and specs that create journals through the UI leave today's behind, so a full run always holds
  some. `TestDataManager.clearJournalsOn(day)` deletes them — destructively, which `workers: 1` makes
  safe, as it does for `clearFutureJournals()`.

"AI unconfigured" cannot be created on a stack with the stub on; serve the unconfigured wire answer
(an unavailable summary section, `data: null` from the summary endpoints) at the route level, over a
real page, and pin the backend branch with unit and integration tests.

### Cross-Browser Reliability Patterns

The E2E suite runs across Firefox and Mobile Chrome. Firefox is notably more sensitive to timing — it processes click events, DOM state changes, and navigations slightly slower than the chromium engine. The following patterns prevent Firefox-specific flakes.

#### Use `expect.toPass()` for Action + Assertion Sequences

When a test clicks an element and immediately asserts a state change, Firefox may not register the click in time. Wrap the **action + assertion** together inside `expect.toPass()` so the entire sequence retries as a unit:

```typescript
// ✅ CORRECT: Retryable click + assertion
await expect(async () => {
  await button.click();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
}).toPass({ timeout: 15000 });

// ❌ WRONG: Non-retryable — if the click is missed, the assertion waits forever
await button.click();
await expect(button).toHaveAttribute('aria-expanded', 'true');
```

This pattern applies to:
- **Toggle interactions** (click → `aria-expanded`, `aria-checked`)
- **Navigation after click** (click link → `toHaveURL`)
- **Dynamic UI rendering** (check checkbox → editor `toBeVisible`)
- **Combobox interactions** (fill input → option `toBeVisible`)

#### Never Drive App State With an Interaction That Can No-Op

`scrollIntoViewIfNeeded()` and `hover()`'s implicit scroll do **nothing** when the element is already on screen, and a page with nothing left to scroll fires no `scroll` event however hard it is pushed. Either is fine for *positioning* an element before clicking it — a no-op there means the element was already in place. Neither can be the lever that makes the app do something, because on the runs where it no-ops there is no event for the app to react to, and wrapping it in `toPass()` converts a fast failure into a full-budget deadlock that retries the same no-op.

The journals list only pages into the past once the reader reaches for it, so this bit exactly (issue #1398): a two-journal fixture left the top sentinel already in view with the page at scroll position 0, and the test spun for 30s on `element(s) not found`. Whether the sentinel started in view depended on the settled page height, so it flaked rather than failing outright.

```typescript
// ✅ CORRECT: a gesture that fires regardless of scroll position
await expect(async () => {
  await reachForMoreJournals(page, 'past'); // hover + page.mouse.wheel
  await expect(gapGroup).toBeVisible({ timeout: 3000 });
}).toPass({ timeout: 30000 });

// ❌ WRONG: a no-op on every retry if the sentinel is already visible
await expect(async () => {
  await page.getByTestId('journal-top-sentinel').scrollIntoViewIfNeeded();
  await expect(gapGroup).toBeVisible({ timeout: 5000 });
}).toPass({ timeout: 30000 });
```

Use `frontend/tests/e2e/utils/journal-list-scroll.ts` for the journals list. Sizing fixture data so the target starts *off* screen is not a fix — it makes the test depend on the viewport of whichever project runs it.

#### Use Web-First URL Assertions

Always prefer auto-retrying web-first assertions over snapshot-based checks:

```typescript
// ✅ CORRECT: Web-first, auto-retrying
await expect(page).toHaveURL(/\/journals$/);
await expect(page).not.toHaveURL(/\/journals\/new/);

// ❌ WRONG: Non-retrying — can fail if navigation hasn't completed
expect(page.url()).toContain('/journals');
```

#### Avoid `page.waitForURL()` When Possible

Prefer `await expect(page).toHaveURL(...)` over `page.waitForURL(...)` — the former is a web-first assertion with built-in retry semantics, while the latter has no retry and can timeout on slow browsers.

### ⚠️ LEGACY PATTERN - Replaced by Fixture System

**The conditional logic patterns below have been replaced by the advanced fixture-based testing system.**

> 🚀 **Migration**: See [`frontend/tests/e2e/MIGRATION_GUIDE.md`](../../frontend/tests/e2e/MIGRATION_GUIDE.md) for migrating from conditional logic to fixtures.

#### ❌ OLD PATTERN - Conditional Logic (Now Replaced)
```typescript
// OLD: Conditional logic based on data state
const { hasContacts, hasEmptyState } = await contacts.checkContactsOrEmptyState();
expect(hasContacts || hasEmptyState).toBe(true); // Meaningless test

// OLD: Skipping based on data state
if (contactCount === 0) {
  test.skip('No contacts found - this test requires contacts');
}
```

#### ✅ NEW PATTERN - Fixture-Based Testing
```typescript
// NEW: Use specific fixtures for guaranteed state
test('should display favourite contacts', async ({ favouriteContacts }) => {
  const { page, contacts } = favouriteContacts;

  await page.goto('/contacts/favourites');

  // Guaranteed: contacts exist and are favourites
  expect(contacts).toHaveLength(3);
  contacts.forEach(contact => {
    expect(contact.isFavourite).toBe(true);
  });
});

// NEW: Separate fixture for empty state
test('should display empty state', async ({ emptyContactsPage }) => {
  await emptyContactsPage.goto('/contacts/favourites');

  // Guaranteed: no contacts exist
  const emptyState = emptyContactsPage.locator('[data-testid="empty-state"]');
  await expect(emptyState).toBeVisible();
});

// NEW: Use data factories for custom scenarios
test('custom scenario', async ({ authenticatedPage, dataFactory, testCleanup }) => {
  const customContacts = dataFactory.contacts.createFavourites(5);
  // Test with exactly 5 favourite contacts
});
```

#### Test Data Setup Principles

1. **Each test creates its own data**: Use `testData.createTestContacts()`, `testData.createTestTags()`, etc.
2. **Tests are deterministic**: Each test knows exactly what data exists and what to expect
3. **No conditional logic**: Tests should not have if/else based on data state
4. **No skipping**: Tests should not skip based on what data they find
5. **Separate scenarios**: Have separate tests for empty states vs populated states
6. **Clean setup**: Use `testData.setupAuthenticatedUser()` and `testData.clearAllTestData()`

#### Required TestDataHelpers Implementation

```typescript
export class TestDataHelpers {
  async setupAuthenticatedUser(): Promise<void> {
    // Set up authentication state for tests
  }

  async createTestContacts(contacts: Array<{
    firstName: string;
    lastName: string;
    email?: string;
    isFavourite?: boolean;
    tags?: string[];
  }>): Promise<void> {
    // Create specific test contacts via backend APIs
  }

  async createTestTags(tags: string[]): Promise<void> {
    // Create specific test tags via backend APIs
  }

  async clearAllTestData(): Promise<void> {
    // Clean up all test data
  }
}
```

## Database Testing Guidelines

### Database Integration Testing

- Use test database separate from development database
- Create fixtures for database connections and cleanup
- Test database operations with realistic data
- Verify data persistence and retrieval
- Test database constraints and relationships
- Use transactions for test isolation

### Real Database Integration Testing with Docker

#### Docker PostgreSQL Setup

- Use `docker-compose.yml` with the test profile for test database container
- Separate test database from development database
- Automated container lifecycle management in test fixtures
- Health checks to ensure database readiness before tests

#### Test Isolation Patterns

- **One outer transaction per test, rolled back at teardown**: Each test runs in a single outer transaction on a shared `async_connection` that is **never committed** — `rollback()` at teardown restores a clean state.
- **Commit seam for commit-as-you-go app code**: Application code commits during the request (see [Database Design → Transaction Management](./database-design.md#transaction-management--commit-timing)). To keep tests isolated, the fixture marks the connection with `EXTERNAL_TRANSACTION_MARKER` (`app/infrastructure/unit_of_work.py`). With the marker set:
  - `unit_of_work` / `savepoint` emulate commit/rollback with **SAVEPOINTs** instead of committing the real (test-owned) transaction, so the outer transaction survives to be rolled back at teardown.
  - Writes still become visible to later reads on the same connection (read-after-write within a test), while the outer `rollback()` discards everything.
- **Schema Recreation**: Fresh database schema for each test session.
- **Connection Management**: Proper connection pooling and cleanup.

> [!IMPORTANT]
> **All database access during a test — including access via API test clients — must use the same `async_connection` fixture.** If a test client creates its own connection (e.g. via `DatabaseProvider`), data it writes will be committed to the real database and will leak into subsequent tests.

#### Integration Test Structure

Isolation is implemented by one outer transaction plus the commit seam marker
(`backend/tests/integration/conftest.py`):

```python
@pytest_asyncio.fixture(scope="function")
async def async_connection(async_engine):
    """Outer transaction + commit seam; never really committed."""
    from app.infrastructure.unit_of_work import EXTERNAL_TRANSACTION_MARKER

    async with async_engine.connect() as conn:
        await conn.begin()                          # outer transaction
        conn.info[EXTERNAL_TRANSACTION_MARKER] = True  # uow/savepoint -> savepoints
        try:
            yield conn
        finally:
            conn.info.pop(EXTERNAL_TRANSACTION_MARKER, None)
            await conn.rollback()                   # discard everything
```

#### API Test Clients Must Use the Savepoint Connection

When writing API integration tests that use HTTP test clients (e.g. `AsyncClient`), you **must** inject `async_connection` via a custom provider — **do not** use `DatabaseProvider(test_settings)` which creates independent connections outside the savepoint:

```python
# ✅ CORRECT: inject the savepoint connection so writes are rolled back
class TestDatabaseProvider(Provider):
    def __init__(self, connection: AsyncConnection):
        super().__init__()
        self.connection = connection

    @provide(scope=Scope.REQUEST)
    def get_connection(self) -> AsyncConnection:
        return self.connection

@pytest_asyncio.fixture
async def my_api_client(async_connection: AsyncConnection, ...):
    test_container = make_async_container(
        TestDatabaseProvider(async_connection),  # ← savepoint connection
        ContactProvider(),
        ...
    )
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        yield client
    await test_container.close()

# ❌ WRONG: creates fresh connections that bypass the savepoint
test_container = make_async_container(
    DatabaseProvider(test_settings),  # ← commits to real DB — data leaks!
    ...
)
```

#### Real Database Benefits

- **SQL Validation**: Test actual PostgreSQL SQL syntax and behavior
- **Constraint Testing**: Verify database constraints work correctly
- **Performance Insights**: Real query performance characteristics
- **Production Parity**: Closer to actual deployment environment

### Enum Testing Patterns

#### Type-Safe Enum Usage in Tests

- Use enum values instead of string literals in test data
- Test enum validation in entity creation
- Verify enum conversion at repository boundaries
- Test enum comparisons in business logic

#### Example Enum Test Patterns

```python
# ✅ Use enum values in tests
method = ContactMethod(
    method_type=MethodType.EMAIL,  # Not "email"
    value="test@example.com",
    contact_id=1
)

# ✅ Test enum validation
def test_invalid_method_type_raises_error():
    with pytest.raises(ValueError):
        ContactMethod(
            method_type="invalid",  # Should fail validation
            value="test@example.com",
            contact_id=1
        )

# ✅ Test enum comparisons
def test_get_primary_email():
    contact = Contact(first_name="John", last_name="Doe")
    contact.methods.append(ContactMethod(
        method_type=MethodType.EMAIL,
        value="john@example.com",
        contact_id=1,
        is_primary=True
    ))
    assert contact.get_primary_email() == "john@example.com"
```

## Mock Utilities Guidelines

### Service Mocking

- Use `Mock` with `spec` parameter for type safety
- Create `AsyncMock` for async service methods
- Provide factory functions for common mock objects
- Mock external dependencies (database, APIs)
- Use descriptive mock return values
- Reset mocks between tests

## Test Data Factories Guidelines

### Factory Pattern

- Create factory classes for test data generation
- Provide sensible defaults for all fields
- Allow customization of specific fields
- Use realistic test data (Australian phone numbers, etc.)
- Create both request and response objects
- Keep factories simple and focused

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and testing principles
- [AI Guidelines](../../AGENTS.md) - Test-first development workflow and quality standards
- [Technology Stack](./technology-stack.md) - Testing technology choices and high-level strategy
- [Domain Architecture](./domain-architecture.md) - Domain patterns and validation strategies
- [API Design](./api-design.md) - API testing patterns and validation
- [Frontend Design](./frontend-design.md) - Component testing patterns and accessibility
- [Deployment Guide](./deployment-guide.md) - CI/CD testing pipeline and Docker test setup
