# Iteration 2: Integration Architecture Foundation

**Status:** 🟡 IN PROGRESS (core steel thread complete; resilience & observability from the Integration Architecture doc still outstanding)
**Dependencies:** Iteration 1.5
**Goal:** Establish robust integration architecture with Google Contacts sync using modern patterns

## Overview

This iteration implements a production-ready integration architecture and lays the groundwork for the full design in `docs/architecture/integration-architecture.md`:
- ✅ Dishka dependency injection framework migration (COMPLETED)
- ✅ ARQ task queue with Redis for background processing (COMPLETED)
- ✅ Google Contacts bidirectional synchronization (COMPLETED - Core functionality with outbox pattern)
- ✅ Isolated worker architecture for scalability (COMPLETED)
- 🟡 Production resilience patterns - Phase 1 critical issues resolved (idempotency, security, error handling); Phase 2 retry strategy with exponential backoff implemented and tested; advanced observability patterns are tracked as remaining work below
- ✅ FastMCP v2 integration for AI assistant capabilities (COMPLETED)
- ✅ Worker test infrastructure matching backend patterns (COMPLETED - tests/unit/ and tests/integration/ with CI integration)

## Tasks

### ITER2-001: Integration Architecture Foundation 🟡 ✅ COMPLETED
**Description:** Implement isolated worker architecture with ARQ task queue and shared code strategy
**PR Size:** ~12 files (Core shared package, Redis setup, integration domain, tests)

**Acceptance Criteria:**
- [x] Create `core_shared` Python package with SQLAlchemy models and database utilities
- [x] Set up Redis container for ARQ task queue
- [x] Create integration domain structure (app/core/integrations/)
- [x] Implement shared integration models (SyncMetadata, ExternalReference) in core_shared
- [x] Create base integration service interface and patterns
- [x] Set up ARQ task queue with Redis backend and DLQ configuration
- [x] Implement session-per-task database connection pattern
- [x] Create integration-specific exception handling
- [x] Add integration domain to dependency injection container
- [x] Write unit tests for integration foundation
- [x] Update Docker Compose with Redis service and volume mounts for core_shared
- [x] Add integration health check endpoint (`/api/health/integrations`)
- [x] Create comprehensive verification script for steel thread validation
- [x] Database migrations for integration tables (SyncMetadata, ExternalReference)

**Final Status:** All integration foundation components implemented and verified. Steel thread complete with Redis task queue, core shared models, integration domain, dependency injection, and comprehensive testing.

### ITER2-002: Google Contacts Integration ✅ COMPLETED
**Description:** Implement Google Contacts integration using isolated worker architecture
**Strategy:** Break into 5 manageable slices for reviewable PRs

#### Slice 1: Foundational API Client & Credential Management ✅ COMPLETED
**PR Size:** ~6 files (Auth models, encryption service, API client, tests)

**Acceptance Criteria:**
- [x] Add Google API `client_id` and `client_secret` to worker secrets management
- [x] Create `UserGoogleAuth` DB model (user_id, access_token, refresh_token encrypted, expires_at)
- [x] Implement `GoogleAuthService` for CRUD operations on UserGoogleAuth tokens with encryption
- [x] Implement `GoogleAPIClient` using official `google-api-python-client` library
- [x] Add automatic token refresh logic handling 401 responses via GoogleAuthService
- [x] Write integration test confirming successful token refresh on 401 response

**Implementation Details:**
- **UserGoogleAuth Model:** Database model with encrypted OAuth token storage supporting multiple Google accounts per user
- **EncryptionService:** Fernet-based symmetric encryption for secure token storage with proper key management
- **GoogleAuthService:** CRUD operations with SELECT FOR UPDATE for concurrency safety and automatic token refresh
- **GoogleAPIClient:** httpx.Auth subclass with automatic token refresh on 401 responses
- **Database Migration:** Migration 0005 with proper indexes and constraints
- **Testing:** 13 comprehensive integration tests covering all functionality including token refresh verification

#### Slice 2: Data Modeling & Read-Only Full Sync 🟢 ✅ COMPLETED
**PR Size:** ~8 files (API models, transformer, service, tests)

**Acceptance Criteria:**
- [x] Create `integrations/google` package structure
- [x] Define Pydantic models for Google Contact API response structure
- [x] Create data transformer mapping Google Contact models to core_shared contact models
- [x] Create `UserGoogleIntegration` DB model to store user_id and sync_token
- [x] Implement `GoogleService.full_sync(user_id)` returning (List[Contact], next_sync_token)
- [x] Write unit tests for full_sync mocking API client and verifying pagination/token extraction

**Implementation Details:**
- **Package Structure:** Complete `app/core/integrations/google/` package with proper module organization
- **API Models:** Comprehensive Pydantic models for Google People API responses with proper field aliases and validation
- **Data Transformer:** `GoogleContactTransformer` with robust data mapping, sanitization, and error handling
- **Database Model:** `UserGoogleIntegration` model with sync token storage and database migration (0006)
- **Contacts Service:** `GoogleService.full_sync()` with pagination support, error handling, and sync state management
- **Testing:** 24 comprehensive unit tests covering all functionality including edge cases and error scenarios

#### Slice 3: Idempotent Persistence & Incremental Sync Logic 🟡 ✅ COMPLETED
**PR Size:** ~5 files (Persistence logic, incremental sync, tests)

**Acceptance Criteria:**
- [x] Use existing `SyncMetadata` DB model from core_shared (item_id, external_id, version_hash as ETag, last_synced_at)
- [x] Implement persistence logic to save contacts and SyncMetadata from full_sync results with idempotent operations
- [x] Implement `GoogleService.incremental_sync(user_id, sync_token)` for efficient updates using Google's sync tokens
- [x] Add logic to handle created, updated, and soft-deleted contacts in incremental_sync with automatic fallback to full sync
- [x] Write comprehensive unit tests for incremental_sync covering create, update, delete, and error scenarios

**Implementation Details:**
- **Idempotent Persistence:** `save_contacts_with_metadata()` method with version hash-based conflict detection using ETags
- **Incremental Sync:** `incremental_sync()` method leveraging Google's sync tokens (29-day validity) for efficient updates
- **Smart Fallback:** Automatic fallback to full sync when sync token expires (HTTP 410 response)
- **Atomic Operations:** Transaction-based persistence for contacts and sync metadata with proper rollback handling
- **Comprehensive Testing:** 17 new unit tests + 13 integration tests covering all scenarios including edge cases

#### Slice 4: Integration Management UI ✅ COMPLETED
**PR Size:** ~15 files (Frontend integration UI, API client, tests)

**Acceptance Criteria:**
- [x] Create integration management page (`/integrations`)
- [x] Implement integration API client with TypeScript types
- [x] Add Google Contacts integration status display
- [x] Implement sync trigger controls (smart sync, full sync)
- [x] Add job status tracking and progress monitoring
- [x] Implement sync history display with pagination
- [x] Add health monitoring dashboard
- [x] Include navigation integration
- [x] Add comprehensive test coverage (unit + integration tests)
- [x] Re-enable previously skipped e2e tests
- [x] **Fix CI failures (e2e tests, SonarQube analysis)**
- [x] **Address GitHub Copilot feedback (5 rounds completed)**
- [x] **Final CI validation and quality assurance**

**Implementation Details:**
- **Integration Page:** Complete `/integrations` page with status display, sync controls, and history
- **API Client:** TypeScript integration API client with React Query hooks for caching and real-time updates
- **Type Safety:** Comprehensive TypeScript types for all integration API responses
- **UI Components:** Reusable integration components with proper loading states and error handling
- **Testing:** 100% test coverage including unit tests for API client and integration tests for UI components
- **Navigation:** Added integrations section to sidebar navigation with proper routing

**Status:** ✅ IMPLEMENTATION COMPLETE - Production Ready

**Final Achievements:**
- **E2E Tests:** Added Docker fallback mechanism for CI reliability
- **Code Quality:** Implemented all GitHub Copilot suggestions (5 rounds completed)
  - Polling optimization with progressive backoff
  - Enhanced error handling with validation
  - Date validation to prevent crashes
  - Type-only React imports
  - Extracted magic numbers to constants
  - OAuth redirect error handling for SSR/testing
  - Date formatting helper function to eliminate duplication
- **Quality Gates:** All passing (ESLint, Prettier, TypeScript, Tests)
- **Production Ready:** Ready for merge and deployment

## ✅ IMPLEMENTATION COMPLETE

The integration architecture foundation and core Google Contacts sync functionality is now complete.

### ITER2-004: Google Contacts Sync Implementation ✅ COMPLETED
**Description:** Implement actual Google Contacts synchronization logic in the worker
**Dependencies:** Integration infrastructure (✅ COMPLETED)
**Target:** Complete functional Google Contacts sync

**Final State:** ✅ Complete implementation with outbox pattern. Google Contacts integration migrated from core to worker. Architecture compliance achieved - worker uses message-based communication via outbox events. Critical security issues resolved.

#### Phase 1: Worker Sync Logic Implementation ✅ COMPLETED
**Status:** Worker now implements actual Google People API sync using outbox pattern

**Completed:**
- [x] Implemented actual Google People API calls in worker
- [x] Migrated Google Contacts integration from core to worker (resolved code duplication)
- [x] Added outbox pattern for message-based architecture compliance
- [x] Implemented full sync and incremental sync with smart sync strategy
- [x] Added comprehensive error handling and structured logging
- [x] Fixed timezone consistency issues (UTC throughout)

#### Phase 2: Outbox Event Processing & API Integration ✅ COMPLETED
**PR Size:** ~24 files (Outbox processor, API endpoints, core cleanup, tests, security fixes)
**Actual Effort:** 3 days

**Acceptance Criteria:**
- [x] Create outbox event processor in core to handle contact creation/updates
- [x] Remove Google Contacts integration from core (keep only outbox processing)
- [x] Connect API endpoints to real ARQ task queue instead of mock responses
- [x] Implement real job status tracking using ARQ job IDs
- [x] Connect health endpoints to actual Redis and worker status
- [x] Add critical security fixes (idempotency, user-job ownership, error sanitization)
- [x] Comprehensive test coverage (76 passing unit tests)

**Implementation Completed:**
1. **Outbox Event Processor** ✅
   - Created `OutboxEventProcessor` service in core to process contact sync events (created/updated/completed)
   - Uses existing `ContactService` to create/update contacts from outbox events
   - Implemented idempotency checks to prevent duplicate contact creation
   - Added comprehensive error handling with proper exception chaining

2. **Core Integration Cleanup** ✅
   - Removed Google Contacts services from core (GoogleService, GoogleAuthService, etc.)
   - Kept only transformer and API models needed for outbox processing
   - Updated dependency injection to remove Google Contacts providers
   - Added new integration services (TaskQueueService, HealthService, OutboxEventProcessor)

3. **API Endpoint Integration** ✅
   - Connected `/api/integrations/google/contacts/sync` to real ARQ task queue
   - Implemented real job status tracking using ARQ job IDs with user-job ownership security
   - Connected health endpoints to actual Redis and worker status monitoring
   - Added proper error handling and sanitized error messages

4. **Security & Testing** ✅
   - Added user-job ownership verification to prevent unauthorized access
   - Implemented comprehensive test coverage (76 passing unit tests)
   - Added integration tests for API controllers
   - Fixed critical security vulnerabilities identified in code review

#### Phase 3: OAuth Integration & UI Flow 🟡 IN PROGRESS (PR #237)
**PR Size:** ~16 files (OAuth endpoints, frontend integration, tests)
**Estimated Effort:** 2-3 days

**Acceptance Criteria:**
- [x] Add OAuth2 endpoints for Google account linking in main API
- [x] Implement frontend OAuth flow for Google account connection
- [x] Add user-facing sync controls and status display
- [x] Implement sync job monitoring and progress tracking
- [x] Add comprehensive end-to-end testing with OAuth flow

**Implementation Details:**
- **OAuth Endpoints:** `POST /api/integrations/google/contacts/oauth/authorize`, `POST /api/integrations/google/contacts/oauth/callback`, `DELETE /api/integrations/google/contacts/oauth/disconnect`
- **Status Endpoint:** `GET /api/integrations/google/contacts/status` returns JSON API format with connection status
- **Frontend:** Enhanced integrations page with Connect/Disconnect buttons, OAuth callback handling
- **Security:** CSRF protection with state parameter, PKCE flow, secure state encoding
- **Testing:** 6 unit tests, integration tests, E2E tests for OAuth UI flow

**Bug Fix (2025-12-10):**
- Fixed backend response format mismatch: Updated `/api/integrations/google/contacts/status` to return JSON API format (`data.attributes.connected`) instead of simple object format

#### Slice 5: Two-Way Sync & Conflict Resolution ✅ COMPLETED
**PR Size:** ~6 files (Push logic, conflict resolution, API client updates, tests)

**Acceptance Criteria:**
- [x] Add logic to detect locally created/updated contacts since last sync
- [x] Add `create_contact` and `update_contact` methods to GoogleAPIClient
- [x] Implement push logic using ETag from SyncMetadata in If-Match header for updates
- [x] Handle `412 Precondition Failed` errors by logging conflicts and skipping updates
- [x] Update SyncMetadata with new ETag from Google API response after successful push
- [x] Create comprehensive integration tests mocking API for two-way sync, conflicts, token expiration

**Implementation Details (2026-01-04):**
- Added `create_contact()` and `update_contact()` methods to GoogleAPIClient with ETag support
- Implemented `find_contacts_to_push()` to detect locally created/updated contacts
- Added `push_contacts_to_google()` with conflict resolution handling 412/400 errors
- Created `push_local_contacts_to_google()` ARQ task for bidirectional sync
- Added comprehensive test suite: 17 tests covering sync, API client, local changes detection, and push logic
- All tests passing with proper mocking and error handling
- Code quality: All linting issues resolved, Pydantic v2 migration complete

### ITER2-003: Dishka Migration & Architecture Modernization ✅ COMPLETED
**Description:** Migrate entire application to use Dishka dependency injection framework
**Status:** All phases completed successfully

#### Phase 1: Core Domain Migration ✅ COMPLETED
**PR Size:** ~8 files (Domain providers, service updates, tests)

**Acceptance Criteria:**
- [x] Create domain-specific Dishka providers (ContactProvider, TagProvider, etc.)
- [x] Migrate ContactService and related services to use Dishka injection
- [x] Update repository interfaces to use Dishka patterns
- [x] Implement proper scope management (APP for singletons, REQUEST for per-request)
- [x] Update unit tests to use Dishka testing utilities
- [x] Ensure all existing functionality continues to work

**Implementation Details:**
- **Domain Providers:** ContactProvider, AuthProvider, IntegrationProvider, DatabaseProvider all implemented
- **Service Migration:** All services use constructor injection with typed interfaces
- **Scope Management:** Proper APP/REQUEST scope separation implemented
- **Type Safety:** All dependencies use `FromDishka[Type]` annotations

#### Phase 2: API Layer Migration ✅ COMPLETED
**PR Size:** ~6 files (API controllers, middleware, tests)

**Acceptance Criteria:**
- [x] Update FastAPI controllers to use `FromDishka[Type]` annotations
- [x] Set up Dishka with `setup_dishka(container, app)` in app factory
- [x] Implement proper lifespan management for container cleanup
- [x] Update API integration tests to work with Dishka
- [x] Ensure all endpoints continue to function correctly

**Implementation Details:**
- **Controller Migration:** All API controllers use `FromDishka[Type]` for dependency injection
- **Container Setup:** Dishka integrated with FastAPI using `setup_dishka(container, app)`
- **Lifespan Management:** Proper container cleanup in application lifespan
- **Testing Integration:** All tests work with Dishka container

#### Phase 3: MCP Server Migration ✅ COMPLETED
**PR Size:** ~4 files (MCP tools, FastMCP v2 setup, tests)

**Acceptance Criteria:**
- [x] Migrate MCP server to FastMCP v2 framework
- [x] Update MCP tools to use Dishka dependency injection
- [x] Share Dishka container between REST API and MCP server
- [x] Implement proper cleanup of resources after tool execution
- [x] Update MCP integration tests

**Implementation Details:**
- **FastMCP v2:** MCP server uses FastMCP v2 framework with domain-based tools
- **Dishka Integration:** MCP tools use `FromDishka[Type]` for dependency injection
- **Shared Container:** Same Dishka container used by both REST API and MCP server
- **Resource Management:** Proper cleanup of database connections and resources

### ITER2-005: Production Resilience Patterns 🟡 IN PROGRESS
**Description:** Implement production-grade resilience and observability patterns
**PR Size:** Split into 4 sub-tasks for comprehensive coverage

#### Phase 1: Idempotency & Transactional Patterns ✅ COMPLETED
**PR Size:** ~15 files (Repository, outbox processor integration, utils, tests, documentation)

**Acceptance Criteria:**
- [x] Implement mandatory idempotency patterns with SyncMetadata locking
- [x] Add transactional outbox pattern for atomic database/event operations (already existed)
- [x] Implement SELECT FOR UPDATE locking for concurrent sync operations
- [x] Add comprehensive integration tests for concurrent scenarios
- [x] Document idempotency patterns and usage guidelines
- [x] Integrate OutboxEventProcessor into OutboxProcessor for contact sync events

**Implementation Details:**
- **SyncMetadataRepository** (`backend/app/core/integrations/adapters/sql/sync_metadata_repository.py`):
  - `find_and_lock()`: Acquires exclusive lock using SELECT FOR UPDATE
  - `find_by_external_id()`: Read-only query without locking
  - `upsert()`: Atomic insert/update with ON CONFLICT handling
  - `should_sync()`: Version hash-based idempotency check
- **Version Hash Utilities** (`backend/app/core/integrations/utils/version_hash.py`):
  - `calculate_version_hash()`: Generic SHA-256 hash calculation
  - `calculate_contact_version_hash()`: Contact-specific hash (excludes metadata timestamps)
- **OutboxEventProcessor** (`backend/app/core/integrations/outbox_event_processor.py`):
  - Updated `_process_contact_updated()` to use SELECT FOR UPDATE locking
  - Added version hash checking for idempotency (skip if unchanged)
  - Atomic sync metadata updates in same transaction as contact updates
  - Updated `_process_contact_created()` to create initial sync metadata
- **OutboxProcessor Integration** (`backend/app/infrastructure/events/outbox_processor.py`):
  - Added event routing logic to distinguish contact sync events (`contact.*`) from other events
  - Contact sync events routed to `OutboxEventProcessor` for proper locking and idempotency
  - Other events continue to be processed by `SearchIndexer` (MeiliSearch)
  - Added `_process_contact_event()` method that creates all necessary dependencies
  - Maintains transactional integrity using same database connection
- **Integration Tests** (`backend/tests/integration/core/integrations/test_concurrent_sync.py`):
  - `test_concurrent_sync_with_locking`: Verifies SELECT FOR UPDATE prevents race conditions
  - `test_concurrent_sync_different_contacts`: Verifies row-level locking (not table-level)
  - Tests use real PostgreSQL database via Docker
- **Unit Tests**:
  - `test_sync_metadata_repository.py`: 8 tests covering all repository methods
  - `test_outbox_processor.py`: 10 tests including contact event routing
  - `test_outbox_event_processor.py`: 7 tests for contact sync processing
  - Tests for locking, idempotency, and error handling
- **Documentation** (`backend/tests/integration/core/integrations/README.md`):
  - Comprehensive guide to concurrent sync patterns
  - Explains SELECT FOR UPDATE, idempotency checks, and separate connections
  - Running instructions and test infrastructure details

**Test Results:**
- ✅ 107/107 unit tests passing (infrastructure/events + core/integrations)
- ✅ 5/5 integration tests passing (outbox pattern)
- ✅ All quality gates passing (mypy, ruff check, ruff format)

#### Phase 2: Retry & Error Handling 🟡 PENDING
**PR Size:** ~4 files (ARQ configuration, error handling, monitoring)

**Acceptance Criteria:**
- [ ] Configure ARQ retry strategy with exponential backoff and jitter
- [ ] Implement Dead Letter Queue monitoring and alerting
- [ ] Add structured logging with correlation IDs and context propagation
- [ ] Implement graceful shutdown handling for workers
- [ ] Add comprehensive error handling and recovery procedures

#### Phase 3: Observability & Monitoring ✅ COMPLETED
**PR Size:** ~10 files (Metrics endpoint, logging, health checks, cancellation, tests)

**Acceptance Criteria:**
- [x] Implement Prometheus metrics collection (golden signals)
  - Added `/api/metrics` endpoint exposing Prometheus metrics in standard text format
  - Metrics include worker job duration, job totals, queue depth, sync items processed, errors, and conflicts
  - Integrated with existing `core_shared.metrics` module
- [x] Add long-running job progress tracking and cancellation support
  - Implemented `cancel_job()` method in `TaskQueueService` with authorization checks
  - Added `POST /api/integrations/google/contacts/sync/{job_id}/cancel` endpoint
  - Updated Google Contacts worker to check for cancellation between batches
  - Added `_check_job_cancelled()` helper function in worker
  - Proper exception handling for cancelled jobs (doesn't mark as failed)
- [x] Create comprehensive health checks for all integration components
  - Existing health checks already cover database, Redis, and worker components
  - `/api/health/detailed` endpoint provides comprehensive service status
- [x] Add comprehensive test coverage
  - Added unit test for `/api/metrics` endpoint
  - Added 3 unit tests for job cancellation (success, not found, unauthorized)
  - All tests passing (17/17 in health and task queue service tests)
- [ ] Add integration-specific monitoring dashboards (deferred to ITER2-006 Phase 2)
- [ ] Implement alerting for critical integration failures (deferred to future iteration)

#### Phase 4: Security & Configuration 🟡 PENDING
**PR Size:** ~3 files (Secrets management, configuration, security)

**Acceptance Criteria:**
- [ ] Implement secure configuration and secrets management
- [ ] Add encryption at rest for sensitive integration data
- [ ] Implement proper authentication and authorization for workers
- [ ] Add security audit logging for integration operations
- [ ] Create production readiness tests and monitoring

### ITER2-006: Integration Management UI & UX 🟡 IN PROGRESS
**Description:** Refine and extend the UI for managing integrations and sync status
**PR Size:** Split into 4 sub-tasks for focused development

> Note: The initial `/integrations` dashboard, OAuth flow, sync controls, job status display, and basic health views were implemented as part of Google Contacts work (see ITER2-002 Slice 4). This task now focuses on rounding out the UX and aligning it with the broader Integration Architecture (progress, cancellation, richer health/metrics, and documentation).

#### Phase 0: Backend Foundations ✅ COMPLETED
**PR Size:** ~16 files (Database schema, transformers, API/MCP schemas, search integration, tests)

**Acceptance Criteria:**
- [x] Complete company/job_title mapping for Google Contacts integration
  - Added `company` and `job_title` fields to Contact entity (200 chars each)
  - Created database migration `0014_add_company_and_job_title_to_contacts.py`
  - Updated ContactRepository with new fields in all SQL queries
- [x] Implement bidirectional organization sync
  - Implemented `_extract_organization_info` in GoogleContactTransformer (Google → Local)
  - Implemented `_transform_organizations` in worker (Local → Google)
  - Prefers "current" organization, falls back to first organization
  - Handles empty strings as None for clean data
- [x] Update all API and MCP schemas
  - Updated ContactAttributes, ContactResponse, ContactSearchResult
  - Updated ContactCreateRequest, ContactUpdateRequest
  - Enhanced summary generation to include work info: "John Doe is a contact. Senior Developer at TechCorp."
- [x] Integrate with search infrastructure
  - Added company/job_title to MeiliSearch searchable and displayed attributes
  - Updated search service to retrieve and highlight company/job_title
  - Updated search indexer to fetch and index organization data
  - Search results now include work information
- [x] Comprehensive test coverage
  - Added 8 unit tests for GoogleContactTransformer organization extraction
  - Added 6 unit tests for worker organization transformation
  - All 111 backend unit tests passing ✅
  - All 40 worker unit tests passing ✅
  - Type checking (mypy) passing on 160 source files ✅
  - Linting (ruff) passing ✅

**Next Steps:**
- Run database migration: `cd backend && uv run alembic upgrade head`
- Reindex existing contacts to populate search with company/job_title data
- Test end-to-end with actual Google Contacts sync

#### Phase 1: Integration Dashboard ✅ COMPLETED (baseline)
**PR Size:** ~5 files (Dashboard components, API endpoints, tests)

**Acceptance Criteria (baseline implemented):**
- [x] Create integration management dashboard (`/integrations` page)
- [x] Add Google OAuth authentication flow and connection controls
- [x] Implement sync status monitoring and controls (trigger smart/full sync)
- [x] Create sync history and error log views
- [x] Add manual sync trigger functionality wired to real ARQ jobs

#### Phase 2: Monitoring & Health 🟡 IN PROGRESS (enhancements)
**PR Size:** ~9 files (Health monitoring, metrics display, repository methods, tests)

**Acceptance Criteria (enhanced behaviour):**
- [x] Extend integration health monitoring to surface queue depth, recent failures, and worker liveness
  - Added `queue_metrics` to health response with queue depth and job counts
  - Added `job_statistics` with 24h totals for completed, failed, cancelled jobs
  - Added `recent_failures` list showing last 10 failed jobs with details
  - Implemented `SyncJobRepository.get_recent_failures()` for failure tracking
  - Implemented `SyncJobRepository.get_job_statistics()` for job metrics
  - Updated `HealthResponse` schema with new fields
  - Added comprehensive unit tests (4 tests for repository, 3 tests for health service)
  - All tests passing (1020 total tests)
- [ ] Add UI for conflict resolution workflows surfaced by Google Contacts sync
- [ ] Add integration configuration management UI (e.g. per-integration settings & credentials overview)
- [ ] Display long-running job progress and expose cancellation controls backed by real APIs

#### Phase 3: Documentation & Help 🟡 PENDING
**PR Size:** ~3 files (Help system, documentation, user guides)

**Acceptance Criteria:**
- [ ] Test integration management workflows end-to-end (link account → run sync → inspect results & errors)
- [ ] Add integration documentation and in-app help for Google Contacts
- [ ] Create user guides for integration setup and troubleshooting
- [ ] Add troubleshooting guides and FAQ linked from the UI

## Architecture Notes

- **Dependency Injection:** Migration from simple DI to Dishka framework for better type safety and lifecycle management
- **Task Queue:** ARQ with Redis for reliable background processing
- **Sync Strategy:** Google's sync-token for efficient incremental updates (29-day validity)
- **Conflict Resolution:** Optimistic concurrency control with ETags in If-Match headers
- **Credential Storage:** Encrypted refresh_tokens in database with proper key management
- **Error Handling:** Smart fallback from incremental to full sync on token expiration (HTTP 410)
- **Observability:** Structured logging, metrics collection, and comprehensive health checks

## Current Status

**Completed (core steel thread):**
- ✅ Integration foundation with ARQ and Redis
- ✅ Google API client with automatic token refresh
- ✅ Data modeling and transformation
- ✅ Idempotent persistence and incremental sync logic
- ✅ ARQ worker infrastructure and Docker containers
- ✅ Dishka dependency injection migration (all phases)
- ✅ FastMCP v2 integration with Dishka
- ✅ Integration API endpoint structure
- ✅ Google Contacts sync business logic implementation
- ✅ API endpoint connection to real functionality
- ✅ Outbox event processing with message-based architecture
- ✅ Critical security fixes (idempotency, user authorization, error sanitization)
- ✅ Comprehensive test coverage (76 passing unit tests)

**Remaining Work (this iteration):**
- 🟡 Production resilience patterns (DLQ handling, advanced alerting) – see ITER2-005 Phase 4
- 🟡 Integration management UI & UX enhancements (progress display, cancellation UI, monitoring dashboards, docs) – see ITER2-006 Phases 2–3

**Out of Scope for Iteration 2 (separate iterations):**
- 🔜 Additional integrations (Immich, Strava, Firefly III, etc.) – see Iteration 3+/5+/6+ task specs

## Testing Status

### E2E Integration Tests - Ready for Re-enablement ✅
**Status:** Integration e2e tests can now be re-enabled as endpoints are fully functional

**Previous Issue:** The integration e2e tests (`frontend/tests/e2e/integrations.spec.ts`) were testing API endpoints (`/api/integrations/*`) that returned mock responses instead of real functionality.

**Current State:**
- ✅ API endpoints at `/api/integrations/google/contacts/*` and `/api/integrations/health` are fully functional
- ✅ Endpoints connected to real ARQ task queue with job tracking
- ✅ Worker implements actual Google Contacts sync logic with outbox pattern
- ✅ Health endpoints return real Redis and worker status

**Resolution Completed:**
- ✅ API endpoints connected to real ARQ task queue (ITER2-004 Phase 2)
- ✅ Worker implements actual Google Contacts sync logic (ITER2-004 Phase 1)
- ✅ Health endpoints return real Redis and worker status
- ✅ Added comprehensive unit test coverage (76 passing tests)
- ✅ Added integration tests for API controllers

**Re-enablement Status:** Tests can be re-enabled by removing `.skip` from:
- `Integration Management` test suite - Tests for sync triggers and status monitoring
- `Integration UI Components` test suite - Tests for integration UI interactions
- `Integration Error Handling` test suite - Tests for error scenarios

**Files Ready:**
- `frontend/tests/e2e/integrations.spec.ts` - Remove `.skip` to re-enable test suites
- `backend/app/api/integrations/controllers.py` - Endpoints fully functional with real ARQ integration
- `integration_workers/google/worker.py` - Contains complete sync logic with outbox pattern

## Next Steps (Revised Plan Aligned with Integration Architecture)

**Core Integration Steel Thread ✅** – Google Contacts end-to-end sync (including outbox pattern, ARQ worker, API endpoints, and baseline integration UI) is implemented and well covered by unit and integration tests.

The remaining work for Iteration 2 focuses on bringing the implementation in line with `docs/architecture/integration-architecture.md`, with each step independently testable (unit, integration, and e2e):

1. **ITER2-005 Phase 2 – Retry & Error Handling (Google Contacts worker)** 🟡 PARTIALLY COMPLETED
   - ✅ **COMPLETED:** Configure ARQ retry strategy on the Google Contacts worker (`integration_workers/google/worker.py::GoogleWorkerSettings`) using exponential backoff with jitter (as per the architecture doc), replacing the fixed `retry_delay = 60` with a `retry_delay_func` function.
     - Implemented `retry_delay_func()` with exponential backoff: 60s → 120s → 240s → 480s → 900s (capped)
     - Added ±20% jitter to prevent thundering herd problem
     - Configured `max_tries = 5` (1 initial attempt + 4 retries)
     - Created comprehensive unit tests in `integration_workers/google/tests/unit/test_retry_strategy.py` (8 tests, all passing)
     - Created integration tests in `integration_workers/google/tests/integration/test_retry_integration.py` (3 passing tests verifying retry configuration and ARQ job enqueuing)
     - Reorganized worker tests to match backend structure: `tests/unit/` and `tests/integration/`
     - Added CI jobs for worker unit and integration tests in `.github/workflows/ci.yml`
   - 🔲 **TODO:** Introduce clear separation of transient vs permanent failures in `sync_google_contacts` and `push_local_contacts_to_google`.
   - 🔲 **TODO:** Ensure failed jobs surface clear, structured errors (including `job_id`, `user_id`, `integration_source`, and `google_account_email`) in logs and API responses, plumbed through `TaskQueueService.get_job_status` in `backend/app/core/integrations/task_queue_service.py` and the corresponding JSON-API controllers in `backend/app/api/integrations/controllers.py`.
   - ✅ **COMPLETED:** Keep tasks strictly idempotent under retries by relying on `SyncMetadataRepository` in `backend/app/core/integrations/adapters/sql/sync_metadata_repository.py` and the existing locking/idempotency patterns used by the Google Contacts worker and outbox event processor.
   - **Testing:**
     - ✅ Unit tests for custom retry delay logic (8 comprehensive tests covering all retry scenarios).
     - ✅ Integration tests for ARQ retry configuration and job enqueuing (3 tests verifying worker settings, exponential backoff, and job status tracking).
     - ✅ All worker unit tests passing (34/34 tests including sync logic, API client, and contact normalization).
     - 🔲 API integration tests that verify job status and error information via `/api/integrations/google/contacts/jobs/*` endpoints.

2. **ITER2-005 Phase 3 – Observability & Monitoring (shared patterns + Google Contacts)** ✅ COMPLETED
   - ✅ Introduced shared observability helpers (`core_shared.logging` and `core_shared.metrics`) implementing structured logging and Prometheus metrics patterns from the architecture doc
   - ✅ Wired observability into `backend/app/core/integrations/task_queue_service.py`, `backend/app/core/integrations/health_service.py`, and `integration_workers/google/worker.py`
   - ✅ Updated Google Contacts worker and `TaskQueueService` to use shared logging configuration (trace/job/worker IDs) and emit golden-signal metrics (`job_duration`, `job_total`, `queue_depth`)
   - ✅ Added `/api/metrics` endpoint for Prometheus scraping
   - ✅ Implemented job progress tracking and cancellation support:
     - `TaskQueueService.cancel_job()` method with user authorization
     - `POST /api/integrations/google/contacts/sync/{job_id}/cancel` endpoint
     - Worker cancellation checks in `_perform_full_sync()` and `_perform_incremental_sync()`
     - Graceful handling of cancelled jobs without marking as failed
   - ✅ Added comprehensive test coverage (metrics endpoint, job cancellation scenarios)
   - Wire metrics into the main FastAPI app’s `/metrics` endpoint (or equivalent) so they can be scraped in dev/prod, and ensure the integration health endpoints plus `get_google_status` in `backend/app/api/integrations/controllers.py` consume the same underlying status/metrics data.
   - Implement long-running job progress tracking and cancellation using the existing `SyncJob` model (progress field) plus explicit "cancel job" APIs that workers honour between batches (via `TaskQueueService` and the Google Contacts job handlers).
   - **Testing:**
     - Unit tests for logging and metrics helpers (correct labels, safe defaults, no global state leaks).
     - Integration tests that execute a real Google Contacts sync in a test environment and assert metrics and `SyncJob` progress updates.
     - E2E tests exercising job progress display and cancellation from the `/integrations` UI.

3. **ITER2-005 Phase 4 – Security & Configuration (workers)**
   - Harden worker configuration by centralising `WorkerSettings` for the Google Contacts worker in `integration_workers/google/worker.py` (database URL, Redis URL, Google credentials, operational limits) and documenting how it is configured via environment variables and, optionally, secrets managers / Docker secrets.
   - Review and ensure encryption-at-rest for any remaining sensitive integration data beyond the existing token storage (re-using `EncryptionService` and the Google auth service used by the worker), and verify that no secrets are logged by either the worker or API.
   - Add security-focused logging for integration operations (who triggered a job, which resources were touched, and high-level outcome) without leaking sensitive payloads, and ensure `TaskQueueService` user-job ownership checks are consistently applied on all job status and cancellation routes.
   - **Testing:**
     - Unit tests for `WorkerSettings` (validation, required fields, failure modes when misconfigured).
     - Unit/integration tests verifying that encrypted fields are never written or logged in plaintext.
     - Security regression tests for job ownership checks (e.g. job status and cancellation endpoints cannot be used across users).

4. **ITER2-006 Phases 2–3 – Integration Management UI & UX Enhancements**
   - Extend the existing `/integrations` dashboard to surface the new observability data: queue health, recent failures, retry counts, and per-job progress, with the ability to cancel running jobs (backed by `TaskQueueService` APIs and Google Contacts worker status).
   - Replace the TODO-based mock implementation in `backend/app/api/integrations/controllers.py::get_google_status` with real data from `SyncJobRepository` and/or integration health endpoints so the UI shows accurate connection status, last sync time, and sync counts.
   - Add configuration views for Google Contacts (e.g. connected accounts, last sync timestamps) and prepare the layout for future integrations.
   - Add in-app documentation and troubleshooting flows for common integration issues (auth failures, quota errors, schema mismatches).
   - **Testing:**
     - Unit tests for new UI components and hooks (state handling, error states, loading states).
     - Integration tests for the integration management page (React Testing Library or equivalent).
     - E2E tests in `frontend/tests/e2e/integrations.spec.ts` covering connection, sync trigger, progress display, cancellation, and error handling; remove any remaining `.skip` flags as these flows stabilise.

5. **ITER2-006 – Clean up remaining integration TODOs (back-end foundations)** ✅ COMPLETE
   - ✅ Complete the organizations/company/job-title mapping TODO in `backend/app/core/integrations/google/transformer.py::GoogleContactTransformer.transform_person`, and add/extend unit tests to lock in the behaviour.

   **Implementation Summary:**
   - Added `company` and `job_title` fields to Contact entity and database (migration 0014)
   - Implemented `_extract_organization_info` in GoogleContactTransformer for Google → Local sync
   - Implemented `_transform_organizations` in worker for Local → Google bidirectional sync
   - Updated all API and MCP schemas to include company/job_title fields
   - Integrated company/job_title into MeiliSearch indexing and search results
   - Added 14 comprehensive unit tests (8 for transformer, 6 for worker)
   - All quality gates pass: 111 backend tests ✅, 40 worker tests ✅, mypy ✅, ruff ✅
   - Files modified: 16 files across backend, worker, and tests
   - Ready for database migration: `cd backend && uv run alembic upgrade head`

6. **Future Iterations (tracked elsewhere, not part of Iteration 2)**
   - Implement additional integrations (Immich, Strava, Firefly III, etc.) following the patterns established here – see `docs/tasks/iteration-3-extended-integrations.md`, `docs/tasks/iteration-5-integration-architecture-and-strava.md`, and `docs/tasks/iteration-6-immich-integration.md`.
   - Where those iterations introduce new patterns, update the Integration Architecture doc so it remains the single source of truth.

**Production Readiness:** See `ITER2-004-Phase2-Production-Readiness.md` for the historical steel-thread checklist. The items above define the remaining work required for Iteration 2 to fully realise the Integration Architecture patterns in production.
