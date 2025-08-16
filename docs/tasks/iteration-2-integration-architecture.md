# Iteration 2: Integration Architecture Foundation

**Status:** 🟡 IN PROGRESS (75% complete)
**Dependencies:** Iteration 1.5
**Goal:** Establish robust integration architecture with Google Contacts sync using modern patterns

## Overview

This iteration implements a production-ready integration architecture:
- Dishka dependency injection framework migration
- ARQ task queue with Redis for background processing
- Google Contacts bidirectional synchronization
- Isolated worker architecture for scalability
- Production resilience patterns (idempotency, retry logic, monitoring)
- FastMCP v2 integration for AI assistant capabilities

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

### ITER2-002: Google Contacts Integration 🟡 IN PROGRESS (60% complete)
**Description:** Implement Google Contacts integration using isolated worker architecture
**Strategy:** Break into 5 manageable slices for reviewable PRs

#### Slice 1: Foundational API Client & Credential Management ✅ COMPLETED
**PR Size:** ~6 files (Auth models, encryption service, API client, tests)

**Acceptance Criteria:**
- [x] Add Google API `client_id` and `client_secret` to worker secrets management
- [x] Create `UserGoogleAuth` DB model (user_id, access_token, refresh_token encrypted, expires_at)
- [x] Implement `GoogleAuthService` for CRUD operations on UserGoogleAuth tokens with encryption
- [x] Implement `GoogleContactsAPIClient` using official `google-api-python-client` library
- [x] Add automatic token refresh logic handling 401 responses via GoogleAuthService
- [x] Write integration test confirming successful token refresh on 401 response

**Implementation Details:**
- **UserGoogleAuth Model:** Database model with encrypted OAuth token storage supporting multiple Google accounts per user
- **EncryptionService:** Fernet-based symmetric encryption for secure token storage with proper key management
- **GoogleAuthService:** CRUD operations with SELECT FOR UPDATE for concurrency safety and automatic token refresh
- **GoogleContactsAPIClient:** httpx.Auth subclass with automatic token refresh on 401 responses
- **Database Migration:** Migration 0005 with proper indexes and constraints
- **Testing:** 13 comprehensive integration tests covering all functionality including token refresh verification

#### Slice 2: Data Modeling & Read-Only Full Sync 🟢 ✅ COMPLETED
**PR Size:** ~8 files (API models, transformer, service, tests)

**Acceptance Criteria:**
- [x] Create `integrations/google_contacts` package structure
- [x] Define Pydantic models for Google Contact API response structure
- [x] Create data transformer mapping Google Contact models to core_shared contact models
- [x] Create `UserGoogleIntegration` DB model to store user_id and sync_token
- [x] Implement `GoogleContactsService.full_sync(user_id)` returning (List[Contact], next_sync_token)
- [x] Write unit tests for full_sync mocking API client and verifying pagination/token extraction

**Implementation Details:**
- **Package Structure:** Complete `app/core/integrations/google_contacts/` package with proper module organization
- **API Models:** Comprehensive Pydantic models for Google People API responses with proper field aliases and validation
- **Data Transformer:** `GoogleContactTransformer` with robust data mapping, sanitization, and error handling
- **Database Model:** `UserGoogleIntegration` model with sync token storage and database migration (0006)
- **Contacts Service:** `GoogleContactsService.full_sync()` with pagination support, error handling, and sync state management
- **Testing:** 24 comprehensive unit tests covering all functionality including edge cases and error scenarios

#### Slice 3: Idempotent Persistence & Incremental Sync Logic 🟡 ✅ COMPLETED
**PR Size:** ~5 files (Persistence logic, incremental sync, tests)

**Acceptance Criteria:**
- [x] Use existing `SyncMetadata` DB model from core_shared (item_id, external_id, version_hash as ETag, last_synced_at)
- [x] Implement persistence logic to save contacts and SyncMetadata from full_sync results with idempotent operations
- [x] Implement `GoogleContactsService.incremental_sync(user_id, sync_token)` for efficient updates using Google's sync tokens
- [x] Add logic to handle created, updated, and soft-deleted contacts in incremental_sync with automatic fallback to full sync
- [x] Write comprehensive unit tests for incremental_sync covering create, update, delete, and error scenarios

**Implementation Details:**
- **Idempotent Persistence:** `save_contacts_with_metadata()` method with version hash-based conflict detection using ETags
- **Incremental Sync:** `incremental_sync()` method leveraging Google's sync tokens (29-day validity) for efficient updates
- **Smart Fallback:** Automatic fallback to full sync when sync token expires (HTTP 410 response)
- **Atomic Operations:** Transaction-based persistence for contacts and sync metadata with proper rollback handling
- **Comprehensive Testing:** 17 new unit tests + 13 integration tests covering all scenarios including edge cases

#### Slice 4: ARQ Worker with Smart Sync Strategy 🟢 ✅ COMPLETED
**PR Size:** ~20 files (ARQ worker, integration APIs, Docker infrastructure, tests)

**Acceptance Criteria:**
- [x] Create isolated Google Contacts worker with ARQ task queue
- [x] Implement Docker container architecture for worker isolation
- [x] Create integration API endpoints for sync management
- [x] Implement core shared package for worker communication
- [x] Add comprehensive test framework for integration flows
- [x] Configure Redis task queue with proper health monitoring
- [x] Add structured logging and health check endpoints

**Implementation Details:**
- **Worker Architecture:** Isolated Docker container with ARQ task processing
- **Integration APIs:** Complete REST API for sync management (`/api/integrations/google/contacts/`)
- **Core Shared Package:** Shared models and database utilities for worker communication
- **Docker Infrastructure:** Production-ready containers with proper dependency management
- **Testing Framework:** Comprehensive E2E test suite with 5/5 tests passing
- **Health Monitoring:** Full health check system for worker and Redis connectivity

## 🚀 IMMEDIATE NEXT STEPS

With the integration worker architecture now complete, the next priority is implementing the actual Google Contacts sync logic. The infrastructure is ready - we need to add the business logic.

### ITER2-004: Google Contacts Sync Implementation 🔴 HIGH PRIORITY
**Description:** Implement actual Google Contacts synchronization logic in the worker
**Dependencies:** Slice 4 (ARQ Worker Architecture) - ✅ COMPLETED
**Target:** Complete functional Google Contacts sync

#### Phase 1: Google API Integration 🟡 NEXT UP
**PR Size:** ~8 files (Google API client, auth service, models, tests)
**Estimated Effort:** 2-3 days

**Acceptance Criteria:**
- [ ] Implement Google People API client with OAuth2 authentication
- [ ] Create Google Contacts data models and transformers
- [ ] Add OAuth flow for Google account linking
- [ ] Implement token refresh and error handling
- [ ] Add comprehensive unit tests for API integration
- [ ] Create integration tests with mock Google API responses

**Implementation Plan:**
1. **Google API Client Setup**
   - Install `google-auth` and `google-api-python-client` dependencies
   - Create `GoogleContactsAPIClient` class with proper authentication
   - Implement rate limiting and retry logic for API calls

2. **OAuth2 Authentication Flow**
   - Add OAuth2 endpoints for Google account linking
   - Implement secure token storage with encryption
   - Add token refresh logic for expired credentials

3. **Data Models & Transformation**
   - Create Pydantic models for Google Contacts API responses
   - Implement data transformer to convert Google contacts to our Contact model
   - Handle field mapping and data validation

#### Phase 2: Sync Logic Implementation 🟡 FOLLOWING
**PR Size:** ~6 files (Sync service, worker tasks, persistence, tests)
**Estimated Effort:** 2-3 days

**Acceptance Criteria:**
- [ ] Implement full sync logic for initial contact import
- [ ] Add incremental sync using Google's sync tokens
- [ ] Implement conflict resolution for bidirectional sync
- [ ] Add sync metadata tracking and status reporting
- [ ] Create comprehensive sync monitoring and logging
- [ ] Add error handling and retry mechanisms

**Implementation Plan:**
1. **Full Sync Implementation**
   - Implement `sync_google_contacts_full(user_id)` ARQ task
   - Add pagination handling for large contact lists
   - Implement batch processing for efficient database operations

2. **Incremental Sync Logic**
   - Implement `sync_google_contacts_incremental(user_id)` ARQ task
   - Use Google's sync tokens for efficient updates
   - Handle created, updated, and deleted contacts

3. **Sync Orchestration**
   - Add sync scheduling and triggering mechanisms
   - Implement sync status tracking and reporting
   - Add user-facing sync controls in the API

#### Phase 3: Production Readiness 🟡 FINAL
**PR Size:** ~4 files (Monitoring, error handling, documentation, tests)
**Estimated Effort:** 1-2 days

**Acceptance Criteria:**
- [ ] Add comprehensive error handling and logging
- [ ] Implement sync monitoring and alerting
- [ ] Add user-facing sync status and controls
- [ ] Create production deployment documentation
- [ ] Add performance monitoring and optimization
- [ ] Complete end-to-end testing with real Google accounts

#### Slice 5: Two-Way Sync & Conflict Resolution 🟡 PENDING
**PR Size:** ~6 files (Push logic, conflict resolution, API client updates, tests)

**Acceptance Criteria:**
- [ ] Add logic to detect locally created/updated contacts since last sync
- [ ] Add `create_contact` and `update_contact` methods to GoogleContactsAPIClient
- [ ] Implement push logic using ETag from SyncMetadata in If-Match header for updates
- [ ] Handle `412 Precondition Failed` errors by logging conflicts and skipping updates
- [ ] Update SyncMetadata with new ETag from Google API response after successful push
- [ ] Create comprehensive integration tests mocking API for two-way sync, conflicts, token expiration

### ITER2-003: Dishka Migration & Architecture Modernization 🟡 PENDING
**Description:** Migrate entire application to use Dishka dependency injection framework
**PR Size:** Split into 3 sub-tasks for manageable changes

#### Phase 1: Core Domain Migration 🟡 PENDING
**PR Size:** ~8 files (Domain providers, service updates, tests)

**Acceptance Criteria:**
- [ ] Create domain-specific Dishka providers (ContactProvider, TagProvider, etc.)
- [ ] Migrate ContactService and related services to use Dishka injection
- [ ] Update repository interfaces to use Dishka patterns
- [ ] Implement proper scope management (APP for singletons, REQUEST for per-request)
- [ ] Update unit tests to use Dishka testing utilities
- [ ] Ensure all existing functionality continues to work

#### Phase 2: API Layer Migration 🟡 PENDING
**PR Size:** ~6 files (API controllers, middleware, tests)

**Acceptance Criteria:**
- [ ] Update FastAPI controllers to use `FromDishka[Type]` annotations
- [ ] Set up Dishka with `setup_dishka(container, app)` in app factory
- [ ] Implement proper lifespan management for container cleanup
- [ ] Update API integration tests to work with Dishka
- [ ] Ensure all endpoints continue to function correctly

#### Phase 3: MCP Server Migration 🟡 PENDING
**PR Size:** ~4 files (MCP tools, FastMCP v2 setup, tests)

**Acceptance Criteria:**
- [ ] Migrate MCP server to FastMCP v2 framework
- [ ] Update MCP tools to use Dishka dependency injection
- [ ] Share Dishka container between REST API and MCP server
- [ ] Implement proper cleanup of resources after tool execution
- [ ] Update MCP integration tests

### ITER2-004: Production Resilience Patterns 🔴 PENDING
**Description:** Implement production-grade resilience and observability patterns
**PR Size:** Split into 4 sub-tasks for comprehensive coverage

#### Phase 1: Idempotency & Transactional Patterns 🟡 PENDING
**PR Size:** ~5 files (Outbox pattern, locking, tests)

**Acceptance Criteria:**
- [ ] Implement mandatory idempotency patterns with SyncMetadata locking
- [ ] Add transactional outbox pattern for atomic database/event operations
- [ ] Implement SELECT FOR UPDATE locking for concurrent sync operations
- [ ] Add comprehensive integration tests for concurrent scenarios
- [ ] Document idempotency patterns and usage guidelines

#### Phase 2: Retry & Error Handling 🟡 PENDING
**PR Size:** ~4 files (ARQ configuration, error handling, monitoring)

**Acceptance Criteria:**
- [ ] Configure ARQ retry strategy with exponential backoff and jitter
- [ ] Implement Dead Letter Queue monitoring and alerting
- [ ] Add structured logging with correlation IDs and context propagation
- [ ] Implement graceful shutdown handling for workers
- [ ] Add comprehensive error handling and recovery procedures

#### Phase 3: Observability & Monitoring 🟡 PENDING
**PR Size:** ~6 files (Metrics, logging, health checks, dashboards)

**Acceptance Criteria:**
- [ ] Implement Prometheus metrics collection (golden signals)
- [ ] Add long-running job progress tracking and cancellation support
- [ ] Create comprehensive health checks for all integration components
- [ ] Add integration-specific monitoring dashboards
- [ ] Implement alerting for critical integration failures

#### Phase 4: Security & Configuration 🟡 PENDING
**PR Size:** ~3 files (Secrets management, configuration, security)

**Acceptance Criteria:**
- [ ] Implement secure configuration and secrets management
- [ ] Add encryption at rest for sensitive integration data
- [ ] Implement proper authentication and authorization for workers
- [ ] Add security audit logging for integration operations
- [ ] Create production readiness tests and monitoring

### ITER2-005: Integration Management UI 🟡 PENDING
**Description:** Create UI for managing integrations and sync status
**PR Size:** Split into 3 sub-tasks for focused development

#### Phase 1: Integration Dashboard 🟡 PENDING
**PR Size:** ~5 files (Dashboard components, API endpoints, tests)

**Acceptance Criteria:**
- [ ] Create integration management dashboard
- [ ] Add Google OAuth authentication flow
- [ ] Implement sync status monitoring and controls
- [ ] Create sync history and error log views
- [ ] Add manual sync trigger functionality

#### Phase 2: Monitoring & Health 🟡 PENDING
**PR Size:** ~4 files (Health monitoring, metrics display, alerts)

**Acceptance Criteria:**
- [ ] Implement integration health monitoring with metrics
- [ ] Create conflict resolution UI
- [ ] Add integration configuration management
- [ ] Display job progress and cancellation controls

#### Phase 3: Documentation & Help 🟡 PENDING
**PR Size:** ~3 files (Help system, documentation, user guides)

**Acceptance Criteria:**
- [ ] Test integration management workflows
- [ ] Add integration documentation and help
- [ ] Create user guides for integration setup
- [ ] Add troubleshooting guides and FAQ

## Architecture Notes

- **Dependency Injection:** Migration from simple DI to Dishka framework for better type safety and lifecycle management
- **Task Queue:** ARQ with Redis for reliable background processing
- **Sync Strategy:** Google's sync-token for efficient incremental updates (29-day validity)
- **Conflict Resolution:** Optimistic concurrency control with ETags in If-Match headers
- **Credential Storage:** Encrypted refresh_tokens in database with proper key management
- **Error Handling:** Smart fallback from incremental to full sync on token expiration (HTTP 410)
- **Observability:** Structured logging, metrics collection, and comprehensive health checks

## Current Status

**Completed (60%):**
- ✅ Integration foundation with ARQ and Redis
- ✅ Google API client with automatic token refresh
- ✅ Data modeling and transformation
- ✅ Idempotent persistence and incremental sync logic

**In Progress:**
- 🟡 ARQ worker implementation with Dishka integration
- 🟡 Two-way sync and conflict resolution

**Pending:**
- 🟡 Dishka migration for entire application
- 🟡 Production resilience patterns
- 🟡 Integration management UI

## Next Steps

1. Complete Google Contacts integration (Slices 4-5)
2. Migrate application to Dishka dependency injection
3. Implement production resilience patterns
4. Build integration management UI
5. Prepare for additional integrations (Immich, Calendar)
