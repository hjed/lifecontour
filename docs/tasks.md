# Personal CRM & Journal System - Task List

## Project Overview
A Python FastAPI backend with Next.js frontend personal CRM and journal system with MCP protocol support, web interface, and integrations with Google Calendar, Google Contacts, and Immich for photos. Uses PostgreSQL as the database, JSON API standard for REST endpoints, and pytest/React Testing Library for testing. Features include contact tags with Google sync, album integration with journal entries and events, name-based person matching, and nginx proxy support.

## Prerequisites
- Python 3.11+ with UV for dependency management
- Node.js 18+ with pnpm for frontend dependencies
- Google Cloud Console account for API access
- Immich instance running
- PostgreSQL database
- Docker and Docker Compose
- Nginx reverse proxy (for production)
- Basic understanding of Python, FastAPI, PostgreSQL, and REST APIs

## Agile Development Approach
Tasks are organized by **feature iterations** that deliver end-to-end value incrementally. Each iteration includes domain logic, API endpoints, basic UI, and integration where applicable.

**Complexity Scale:**
- 🟢 Simple (1-2 hours)
- 🟡 Medium (3-6 hours)
- 🔴 Complex (1-2 days)
- 🟣 Epic (3+ days)

**Development Principles:**
- Each iteration delivers working, testable functionality
- Features are built end-to-end (domain → API → UI)
- Integration sub-domains are developed separately from core domains
- Continuous integration and deployment from iteration 1

---

## Iteration 1: Basic Contact Management (MVP)

### ITER1-001: Project Foundation 🟡 ✅ COMPLETED
**Description:** Set up project foundation with clear backend/frontend separation
**Dependencies:** None
**Acceptance Criteria:**
- [x] Initialize Python backend with UV and pyproject.toml
- [x] Set up FastAPI with Python 3.11+ and type hints
- [x] Configure PostgreSQL database with Docker Compose
- [x] Set up Python linting (ruff), formatting (black), type checking (mypy)
- [x] Initialize Next.js frontend with TypeScript and pnpm
- [x] Configure separate ESLint/Prettier for frontend
- [x] Create clear project structure (backend/, frontend/, docker-compose.yml)
- [x] Set up SQLAlchemy Core with explicit SQL queries
- [x] Configure Alembic for database migrations
- [x] Set up Python standard library logging
- [x] Configure nginx proxy support
- [x] Set up Tailwind CSS and shadcn/ui for frontend
- [x] Configure Australian English localisation (en-AU)
- [x] Set up pytest for backend testing
- [x] Configure React Testing Library for frontend testing
- [x] Set up Playwright for end-to-end testing
- [x] Create Docker containers for backend, frontend, database
- [x] Add development scripts and documentation
- [x] Fix all mypy type checking errors (17 errors resolved)
- [x] Fix ESLint configuration issues
- [x] Fix Jest configuration warnings
- [x] Update .gitignore with comprehensive patterns
- [x] Update AI guidelines with mypy compliance requirements

**Final Status:** All tests passing, all linting passing, all type checking passing. Project foundation is complete and ready for ITER1-002.

### ITER1-002: Contacts Domain Core 🟡 ✅ COMPLETED
**Description:** Build contacts domain with structured tags and contact methods support (Python backend)
**Dependencies:** ITER1-001
**Acceptance Criteria:**
- [x] Create PostgreSQL schema (contacts, contact_methods, contact_addresses, contact_notes, tags, contact_tags, contact_history tables)
- [x] Write explicit SQL queries using SQLAlchemy Core text() with proper joins
- [x] Implement Contact, Tag, ContactMethod, ContactAddress, ContactNote Pydantic models for validation
- [x] Create domain entities with business logic (Contact, Tag, ContactMethod, ContactAddress, ContactNote)
- [x] Implement repository interfaces with connection injection (ContactRepository, TagRepository, ContactHistoryRepository)
- [x] Create ContactService with dependency injection and transaction management
- [x] Implement simple dependency injection container with constructor injection pattern
- [x] Add comprehensive error handling with custom exceptions and HTTP status codes
- [x] Implement business rule validation (email uniqueness, tag limits, primary methods)
- [x] Set up contact history tracking for all changes
- [x] Create domain events (ContactCreated, ContactUpdated, TagAssigned, etc.)
- [x] Set up Alembic database migrations (single migration for all tables)
- [x] Write pytest unit tests for domain logic (no database dependencies)
- [x] Add database seed data for development and e2e testing (separate datasets)
- [x] **BONUS**: Implement comprehensive integration tests with real PostgreSQL database
- [x] **BONUS**: Convert ContactMethod.method_type to Python enum for type safety
- [x] **BONUS**: Add Docker PostgreSQL test infrastructure with transaction isolation

**Final Status:** All domain logic implemented with 112 unit tests and 53 integration tests passing. ContactMethod.method_type converted to type-safe enum. Real database testing infrastructure established. All linting errors resolved (ruff passing).

### ITER1-003: Contacts REST API with Search 🟡 ✅ COMPLETED
**Description:** Create JSON API compliant FastAPI endpoints with MeiliSearch integration using event-driven architecture
**Dependencies:** ITER1-002
**Acceptance Criteria:**
- [x] Set up MeiliSearch Docker container and Python SDK integration
- [x] Implement transactional outbox pattern for reliable event publishing
- [x] Create OutboxEventPublisher implementing existing ContactEventPublisher interface
- [x] Set up FastAPI background task for outbox processing (every 10 seconds)
- [x] Implement OAuth2 authentication using Authlib with configurable providers
- [x] Create OAuth endpoints (authorize/callback/logout) and session validation dependency
- [x] Configure OAuth providers (GitHub, Microsoft, Discord, generic OAuth2) via config file
- [x] Create FastAPI ContactController with automatic OpenAPI docs
- [x] Implement CRUD operations (GET, POST, PUT, DELETE) with proper error handling
- [x] Add contact search endpoints using MeiliSearch (/api/contacts/search)
- [x] Add global search endpoint for contacts (/api/search) - designed for future expansion
- [x] Add tag management endpoints (assign/remove tags)
- [x] Implement comprehensive input validation using Pydantic models
- [x] Configure CORS for frontend integration
- [x] Implement event-driven MeiliSearch indexing via outbox pattern
- [x] Add search features: typo tolerance, highlighting, faceted search, pagination
- [x] Add comprehensive pytest integration tests for all endpoints including search
- [x] Generate automatic Swagger documentation
- [x] Add MeiliSearch health checks to system health endpoint
- [x] Create service factory functions for clean dependency injection

**Final Status:** All REST API endpoints implemented with comprehensive search capabilities, OAuth2 authentication, event-driven MeiliSearch indexing, and full test coverage. Ready for ITER1-004.

### ITER1-004: Contact UI with Search �
**Description:** Create Next.js frontend for contact management with search capabilities
**Dependencies:** ITER1-003
**Acceptance Criteria:**
- [X] Set up Next.js with TypeScript, Tailwind CSS, and shadcn/ui
- [X] Configure API client for FastAPI backend communication
- [X] Implement Australian English interface (en-AU locale, DD/MM/YYYY dates)
- [X] Create contact list view with search and filtering capabilities
- [X] Implement contact creation and editing forms with validation
- [X] Implement responsive design with mobile-first approach
- [X] Add error handling and loading states
- [X] Write React Testing Library tests for components (69 Jest tests passing)
- [X] Add comprehensive end-to-end tests with Playwright
- [ ] Add global search component for searching across all entities
- [ ] Add tag management UI with colour coding (deferred)
- [ ] Implement search result highlighting and typo tolerance display 
- [ ] Add search filters (by tags, date ranges, entity types) 
- [ ] Deploy working MVP with Docker Compose including MeiliSearch

**Current Status:** Contact management UI complete with comprehensive testing. Implemented contact list, detail/edit, and creation pages with form validation, responsive design, and Australian English formatting. Jest tests: 69/69 passing (includes 22 new contact tests). Playwright e2e tests implemented for core contact workflows. 

### ITER1-005: Contact MCP Tools 🟡 ✅ COMPLETED
**Description:** Implement MCP (Model Context Protocol) server foundation and contact tools for AI integration
**Dependencies:** ITER1-004
**Acceptance Criteria:**
- [X] Set up MCP server framework and protocol implementation
- [X] Implement basic MCP message handling and connection management
- [X] Add authentication and security for MCP connections
- [X] Create MCP tool registration system
- [X] Implement contact search, creation, and management tools using MeiliSearch
- [ ] Add OpenTelemetry instrumentation for MCP operations
- [X] Document MCP server setup and configuration
- [X] Implement health checks for MCP server
- [X] Create MCP client test suite for contact tools
- [X] Add comprehensive MCP tool documentation

**Final Status:** MCP server foundation complete with comprehensive contact tools including search, creation, and management. Tools implemented: get_contact, search_contacts, global_search, create_contact, list_contacts. All tools return AI-friendly JSON responses with contextual summaries. Unit tests passing for core functionality.

---

## Iteration 2: Integration Architecture Foundation

### ITER2-001: Integration Architecture Foundation 🟡
**Description:** Implement the isolated worker architecture with ARQ task queue and shared code strategy
**Dependencies:** ITER1-005
**Acceptance Criteria:**
- [ ] Create `core_shared` Python package with SQLAlchemy models and database utilities
- [ ] Set up Redis container for ARQ task queue
- [ ] Create integration domain structure (app/core/integrations/)
- [ ] Implement shared integration models (SyncMetadata, ExternalReference) in core_shared
- [ ] Create base integration service interface and patterns
- [ ] Set up ARQ task queue with Redis backend and DLQ configuration
- [ ] Implement session-per-task database connection pattern
- [ ] Create integration-specific exception handling
- [ ] Add integration domain to dependency injection container
- [ ] Write unit tests for integration foundation
- [ ] Update Docker Compose with Redis service and volume mounts for core_shared

### ITER2-002: Google Contacts Integration 🔴
**Description:** Implement Google Contacts integration using the isolated worker architecture
**Dependencies:** ITER2-001
**Acceptance Criteria:**
- [ ] Create Google Contacts integration package using core_shared models
- [ ] Implement Google API client with OAuth2 authentication
- [ ] Create Google Contacts service with sync logic
- [ ] Implement two-way sync with conflict resolution using SyncMetadata
- [ ] Add mandatory idempotency patterns with version hashing
- [ ] Create ARQ background tasks with DLQ configuration
- [ ] Implement session-per-task database connection pattern
- [ ] Add worker-specific configuration and secrets management
- [ ] Implement credential management and token refresh
- [ ] Add comprehensive error handling and retry logic with DLQ
- [ ] Create integration tests for Google sync
- [ ] Add monitoring and logging for sync operations

### ITER2-003: Integration Worker Architecture 🟡
**Description:** Set up background worker processes for integration isolation
**Dependencies:** ITER2-002
**Acceptance Criteria:**
- [ ] Create integration_workers directory structure
- [ ] Implement Google Contacts worker process
- [ ] Set up isolated dependencies per worker
- [ ] Create worker Dockerfiles for container isolation
- [ ] Implement worker health checks and monitoring
- [ ] Add worker process management and restart logic
- [ ] Create worker-specific logging and error handling
- [ ] Test worker isolation and dependency separation
- [ ] Document worker deployment and scaling patterns
- [ ] Update Docker Compose with worker services

### ITER2-004: Production Resilience Patterns 🔴
**Description:** Implement production-grade resilience and observability patterns
**Dependencies:** ITER2-003
**Acceptance Criteria:**
- [ ] Implement mandatory idempotency patterns with SyncMetadata locking
- [ ] Add transactional outbox pattern for atomic database/event operations
- [ ] Configure ARQ retry strategy with exponential backoff and jitter
- [ ] Implement Dead Letter Queue monitoring and alerting
- [ ] Add structured logging with correlation IDs and context propagation
- [ ] Implement Prometheus metrics collection (golden signals)
- [ ] Add graceful shutdown handling for workers
- [ ] Implement secure configuration and secrets management
- [ ] Add long-running job progress tracking and cancellation support
- [ ] Create comprehensive error handling and recovery procedures
- [ ] Write production readiness tests and monitoring

### ITER2-005: Integration Management UI 🟡
**Description:** Create UI for managing integrations and sync status
**Dependencies:** ITER2-004
**Acceptance Criteria:**
- [ ] Create integration management dashboard
- [ ] Add Google OAuth authentication flow
- [ ] Implement sync status monitoring and controls
- [ ] Create sync history and error log views
- [ ] Add manual sync trigger functionality
- [ ] Implement integration health monitoring with metrics
- [ ] Create conflict resolution UI
- [ ] Add integration configuration management
- [ ] Display job progress and cancellation controls
- [ ] Test integration management workflows
- [ ] Add integration documentation and help

---

## Iteration 3: Extended Integrations

### ITER3-001: Immich Integration 🟡
**Description:** Implement Immich photo service integration
**Dependencies:** ITER2-005
**Acceptance Criteria:**
- [ ] Create Immich integration package
- [ ] Implement Immich API client
- [ ] Create photo and album sync service
- [ ] Add face recognition data integration
- [ ] Implement external reference pattern for photos
- [ ] Create Immich background worker
- [ ] Add person-to-contact matching logic
- [ ] Implement album linking to events/journal
- [ ] Create integration tests for Immich sync
- [ ] Add Immich worker to deployment

### ITER3-002: Strava Integration 🟡
**Description:** Implement Strava activity integration
**Dependencies:** ITER3-001
**Acceptance Criteria:**
- [ ] Create Strava integration package
- [ ] Implement Strava API client with OAuth
- [ ] Create activity sync service
- [ ] Transform activities to journal entries
- [ ] Add activity linking to events and photos
- [ ] Create Strava background worker
- [ ] Implement activity deduplication logic
- [ ] Add activity metadata and statistics
- [ ] Create integration tests for Strava sync
- [ ] Add Strava worker to deployment

### ITER3-003: Firefly III Integration 🟡
**Description:** Implement Firefly III financial integration
**Dependencies:** ITER3-002
**Acceptance Criteria:**
- [ ] Create Firefly III integration package
- [ ] Implement Firefly III API client
- [ ] Create transaction sync service
- [ ] Link transactions to contacts and events
- [ ] Add transaction history tracking
- [ ] Create Firefly III background worker
- [ ] Implement transaction categorization
- [ ] Add financial insights and analytics
- [ ] Create integration tests for Firefly sync
- [ ] Add Firefly worker to deployment

### ITER3-004: Integration MCP Tools 🟡
**Description:** Add integration management tools to MCP interface
**Dependencies:** ITER3-003
**Acceptance Criteria:**
- [ ] Implement integration status monitoring tools
- [ ] Add sync management and control tools
- [ ] Create integration health check tools
- [ ] Add conflict resolution tools via MCP
- [ ] Implement cross-integration search tools
- [ ] Add integration analytics and insights
- [ ] Create integration configuration tools
- [ ] Add bulk sync and management operations
- [ ] Test integration MCP tools with AI assistants
- [ ] Document integration MCP capabilities

---

## Iteration 4: Journal System

### ITER2-001: Google Integration Sub-Domain 🟡
**Description:** Create Google integration sub-domain with standardized interfaces
**Dependencies:** ITER1-004
**Acceptance Criteria:**
- [ ] Create google-integration sub-domain structure
- [ ] Set up Google OAuth 2.0 authentication with token refresh
- [ ] Implement GoogleSyncState entity for tracking sync metadata
- [ ] Create GoogleSyncStateRepository using Drizzle ORM
- [ ] Set up official `googleapis` library with TypeScript support
- [ ] Implement GoogleContactsClient using People API v1
- [ ] Add comprehensive error handling and rate limiting
- [ ] Create sync state database tables
- [ ] Add OpenTelemetry instrumentation for Google API calls

### ITER2-002: Contact Tags and Google Sync �
**Description:** Implement bidirectional contact and tag synchronization with Google
**Dependencies:** ITER2-001
**Acceptance Criteria:**
- [ ] Implement GoogleContactsAdapter with bidirectional sync
- [ ] Map Google contact groups to local tags
- [ ] Handle tag creation, updates, and deletions
- [ ] Implement conflict resolution for contacts and tags
- [ ] Add sync scheduling and manual sync triggers
- [ ] Create sync status monitoring and reporting
- [ ] Handle Google API rate limiting and quotas
- [ ] Add comprehensive logging for sync operations
- [ ] Implement incremental sync with etags
- [ ] Add sync health checks and error recovery

### ITER2-003: Google Sync UI 🟡
**Description:** Add Google sync management to contact UI
**Dependencies:** ITER2-002
**Acceptance Criteria:**
- [ ] Add Google authentication flow to UI
- [ ] Create sync status dashboard
- [ ] Implement manual sync triggers
- [ ] Add conflict resolution UI for contacts and tags
- [ ] Show sync history and error logs
- [ ] Add Google account management
- [ ] Implement sync progress indicators
- [ ] Add tag mapping configuration UI

### ITER2-004: Google Sync MCP Tools 🟡
**Description:** Extend MCP tools with Google sync capabilities and global search
**Dependencies:** ITER2-003
**Acceptance Criteria:**
- [ ] Add Google sync management tools to MCP interface
- [ ] Implement global search tool across all entities (contacts, journal, calendar, photos)
- [ ] Add advanced search tools with filters, facets, and typo tolerance
- [ ] Create sync status monitoring and control tools via MCP
- [ ] Add conflict resolution tools for Google sync via MCP
- [ ] Implement data export and import tools via MCP
- [ ] Add Google authentication management via MCP
- [ ] Create comprehensive search capabilities documentation
- [ ] Test MCP integration with AI assistants for sync operations

---

## Iteration 3: Basic Journal System

### ITER3-001: Journal Domain Core 🟡
**Description:** Build journal domain with album linking support and event publishing
**Dependencies:** ITER2-003
**Acceptance Criteria:**
- [ ] Create journal database schema (journal_entries table with album references)
- [ ] Implement JournalEntry domain entity with business logic
- [ ] Create JournalRepository adapter using SQLAlchemy Core
- [ ] Implement JournalApplicationService with use cases (create, update, link albums)
- [ ] Add mood tracking and sentiment analysis
- [ ] Create domain events using existing DomainEvent base class (JournalEntryCreated, JournalEntryUpdated, JournalEntryDeleted, AlbumLinked)
- [ ] Integrate with shared outbox event publisher for MeiliSearch synchronization
- [ ] Add OpenTelemetry instrumentation for journal operations
- [ ] Write unit tests for journal domain logic

### ITER3-002: Journal REST API with Search 🟡
**Description:** Create JSON API endpoints for journal management with search capabilities
**Dependencies:** ITER3-001
**Acceptance Criteria:**
- [ ] Create JournalController with JSON API compliant endpoints
- [ ] Implement CRUD operations for journal entries
- [ ] Add mood tracking endpoints
- [ ] Implement MeiliSearch-powered search and filtering capabilities (/api/journal/search)
- [ ] Add journal entries to global search index
- [ ] Add album linking endpoints
- [ ] Generate OpenAPI documentation for journal endpoints
- [ ] Add integration tests for journal API including search functionality

### ITER3-003: Journal UI with Search 🔴
**Description:** Build journal management interface with search capabilities
**Dependencies:** ITER3-002
**Acceptance Criteria:**
- [ ] Create journal entry list view with MeiliSearch-powered search and filtering
- [ ] Implement rich text journal entry editor
- [ ] Add mood tracking interface
- [ ] Create journal entry detail view
- [ ] Add search result highlighting for journal content
- [ ] Add mood-based filtering and search
- [ ] Add album linking UI (when albums are available)
- [ ] Implement journal analytics dashboard
- [ ] Add export functionality for journal entries

### ITER3-004: Journal MCP Tools 🟡
**Description:** Add journal management and search tools to MCP interface
**Dependencies:** ITER3-003
**Acceptance Criteria:**
- [ ] Implement journal entry creation and management tools via MCP
- [ ] Add journal search tools with mood tracking and content search
- [ ] Create mood analysis and sentiment tracking tools
- [ ] Add journal entry linking tools for albums and events
- [ ] Implement journal analytics and insights tools
- [ ] Add journal export and import capabilities via MCP
- [ ] Create journal search with date range and mood filtering
- [ ] Add journal entry summarization tools for AI assistants
- [ ] Test journal MCP tools with AI assistant workflows

---

## Iteration 4: Calendar Integration

### ITER4-001: Calendar Domain Core 🟡
**Description:** Build calendar domain with Google Calendar integration and event publishing
**Dependencies:** ITER3-003
**Acceptance Criteria:**
- [ ] Create calendar database schema (events table with album references)
- [ ] Implement Event domain entity with business logic
- [ ] Create EventRepository adapter using SQLAlchemy Core
- [ ] Implement CalendarApplicationService with use cases
- [ ] Add recurring event support and time zone handling
- [ ] Create domain events using existing DomainEvent base class (EventCreated, EventUpdated, EventDeleted, AlbumLinked)
- [ ] Integrate with shared outbox event publisher for MeiliSearch synchronization
- [ ] Add OpenTelemetry instrumentation for calendar operations
- [ ] Write unit tests for calendar domain logic

### ITER4-002: Google Calendar Integration 🔴
**Description:** Extend Google integration sub-domain for calendar sync
**Dependencies:** ITER4-001
**Acceptance Criteria:**
- [ ] Implement GoogleCalendarClient using Calendar API v3
- [ ] Add calendar sync to GoogleIntegrationService
- [ ] Handle recurring events and time zones
- [ ] Implement bidirectional calendar sync
- [ ] Add conflict resolution for calendar events
- [ ] Support multiple Google calendars
- [ ] Add webhook support for real-time sync
- [ ] Implement calendar-specific sync state management

### ITER4-003: Calendar API and UI with Search 🔴
**Description:** Build calendar REST API and user interface with search capabilities
**Dependencies:** ITER4-002
**Acceptance Criteria:**
- [ ] Create CalendarController with JSON API endpoints
- [ ] Add MeiliSearch-powered calendar event search (/api/calendar/search)
- [ ] Add calendar events to global search index
- [ ] Implement calendar view components (month, week, day)
- [ ] Add event creation and editing interface
- [ ] Implement Google Calendar sync UI
- [ ] Add meeting preparation features with search integration
- [ ] Create calendar analytics views
- [ ] Add album linking for events
- [ ] Implement calendar export functionality
- [ ] Add search and filtering within calendar views

### ITER4-004: Calendar MCP Tools 🟡
**Description:** Add calendar management and search tools to MCP interface
**Dependencies:** ITER4-003
**Acceptance Criteria:**
- [ ] Implement calendar event creation and management tools via MCP
- [ ] Add calendar event search with date range and content filtering
- [ ] Create meeting preparation tools with search integration
- [ ] Add Google Calendar sync management via MCP
- [ ] Implement calendar analytics and scheduling insights tools
- [ ] Add calendar event linking tools for albums and contacts
- [ ] Create recurring event management tools
- [ ] Add calendar export and import capabilities via MCP
- [ ] Test calendar MCP tools with AI assistant scheduling workflows

---

## Iteration 5: Photo Albums and Immich Integration

### ITER5-001: Immich Integration Sub-Domain 🟡
**Description:** Create Immich integration sub-domain for album and person management
**Dependencies:** ITER4-003
**Acceptance Criteria:**
- [ ] Create immich-integration sub-domain structure
- [ ] Set up Immich API client with authentication
- [ ] Implement ImmichSyncState entity for tracking sync metadata
- [ ] Create ImmichSyncStateRepository using Drizzle ORM
- [ ] Implement album and person data fetching from Immich
- [ ] Add comprehensive error handling and rate limiting
- [ ] Create sync state database tables for Immich
- [ ] Add OpenTelemetry instrumentation for Immich API calls

### ITER5-002: Album and Person Matching 🔴
**Description:** Implement album integration and name-based person matching
**Dependencies:** ITER5-001
**Acceptance Criteria:**
- [ ] Create Album and Person domain entities
- [ ] Implement name-based person-to-contact matching (no facial recognition)
- [ ] Add manual person-to-contact linking interface
- [ ] Link albums to journal entries and calendar events automatically
- [ ] Create confidence scoring for name-based matches
- [ ] Implement album sync with Immich
- [ ] Add person matching UI with manual confirmation
- [ ] Create album browsing and linking interface

### ITER5-003: Photo Integration UI 🔴
**Description:** Build photo album interface and contact linking
**Dependencies:** ITER5-002
**Acceptance Criteria:**
- [ ] Create album browsing interface
- [ ] Implement photo viewing with thumbnails
- [ ] Add person-to-contact linking UI
- [ ] Create album linking for journal entries and events
- [ ] Add photo search and filtering
- [ ] Implement album management features
- [ ] Add Immich sync status and controls
- [ ] Create photo-based contact discovery

### ITER5-004: Photo MCP Tools 🟡
**Description:** Add photo album and person linking tools to MCP interface
**Dependencies:** ITER5-003
**Acceptance Criteria:**
- [ ] Implement photo album browsing and search tools via MCP
- [ ] Add person-to-contact linking tools with confidence scoring
- [ ] Create album linking tools for journal entries and calendar events
- [ ] Add photo search and filtering capabilities via MCP
- [ ] Implement Immich sync management tools
- [ ] Add photo-based contact discovery and matching tools
- [ ] Create album analytics and insights tools
- [ ] Add relationship analysis tools using photo data
- [ ] Test photo MCP tools with AI assistant workflows for memory recall

---

## Iteration 6: Advanced Features and Future Protocols

### ITER6-001: Testing and Quality Assurance �
**Description:** Comprehensive three-layer testing suite for all iterations
**Dependencies:** ITER5-004
**Acceptance Criteria:**
- [ ] Enhance Jest testing framework with domain isolation and 80%+ coverage
- [ ] Write comprehensive unit tests for all domain entities and services
- [ ] Create integration tests for all API endpoints and external services
- [ ] Expand Storybook stories for all UI components with interaction testing
- [ ] Implement visual regression testing with Storybook and Chromatic
- [ ] Add accessibility testing with Storybook a11y addon and axe-core
- [ ] Create comprehensive end-to-end tests with Playwright for all user workflows
- [ ] Add cross-browser testing (Chrome, Firefox, Safari) with Playwright
- [ ] Implement performance tests for sync operations and API endpoints
- [ ] Add mobile responsiveness testing with Playwright
- [ ] Create test data factories and fixtures for all domains
- [ ] Set up continuous integration with automated testing pipeline
- [ ] Add security testing and vulnerability scanning
- [ ] Implement load testing for production readiness
- [ ] Create testing documentation and best practices guide

### ITER6-002: Performance and Security 🔴
**Description:** Production readiness with performance optimization and security hardening
**Dependencies:** ITER6-001
**Acceptance Criteria:**
- [ ] Implement comprehensive security measures (input sanitization, SQL injection protection)
- [ ] Add data encryption at rest and in transit
- [ ] Optimize database queries and add caching layers
- [ ] Implement rate limiting and DDoS protection
- [ ] Add comprehensive audit logging
- [ ] Create backup and disaster recovery procedures
- [ ] Set up monitoring and alerting systems
- [ ] Implement GDPR compliance features
- [ ] Add performance monitoring and optimization

### ITER6-003: Future Protocol Extensions 🟣
**Description:** CardDAV, CalDAV, and Home Assistant integration
**Dependencies:** ITER6-002
**Acceptance Criteria:**
- [ ] Implement CardDAV protocol for contact synchronization
- [ ] Add CalDAV protocol for calendar synchronization
- [ ] Create Home Assistant integration for smart home automation
- [ ] Support standard vCard and iCal formats
- [ ] Add protocol discovery mechanisms
- [ ] Test compatibility with standard clients (iOS, Android, Thunderbird)
- [ ] Create comprehensive protocol documentation
- [ ] Implement MQTT support for Home Assistant

---

## Agile Development Guide for AI Assistants

### Development Principles
1. **Feature-Complete Iterations** - Each iteration delivers working, testable functionality
2. **End-to-End Development** - Build domain → API → UI → MCP tools for each feature
3. **AI-First Approach** - MCP integration is part of each iteration, not a separate concern
4. **Integration Sub-Domains** - Keep integrations separate from core business logic
5. **Continuous Deployment** - Deploy and test after each iteration
6. **User Feedback** - Validate features with real usage before moving to next iteration

### Getting Started
1. **Start with Iteration 1** - Basic contact management provides foundation
2. **Check dependencies** - Each iteration builds on previous ones
3. **Follow acceptance criteria** - All criteria must be met before marking complete
4. **Deploy and test** - Each iteration should result in working software
5. **Refer to architecture.md** - For system design decisions and integration patterns
6. **Follow ai-guidelines.md** - For coding standards and domain-driven patterns

### Iteration Tracking

Use this section to track progress:

```
Iteration 1 (Contact MVP): [x] ITER1-001 [x] ITER1-002 [x] ITER1-003 [ ] ITER1-004 [x] ITER1-005
Iteration 2 (Integration Foundation): [ ] ITER2-001 [ ] ITER2-002 [ ] ITER2-003 [ ] ITER2-004
Iteration 3 (Extended Integrations): [ ] ITER3-001 [ ] ITER3-002 [ ] ITER3-003 [ ] ITER3-004
Iteration 4 (Journal): [ ] ITER4-001 [ ] ITER4-002 [ ] ITER4-003 [ ] ITER4-004
Iteration 5 (Calendar): [ ] ITER5-001 [ ] ITER5-002 [ ] ITER5-003 [ ] ITER5-004
Iteration 6 (Photos): [ ] ITER6-001 [ ] ITER6-002 [ ] ITER6-003 [ ] ITER6-004
Iteration 7 (Advanced): [ ] ITER7-001 [ ] ITER7-002 [ ] ITER7-003
Iteration 1 (Contact MVP): [x] ITER1-001 [x] ITER1-002 [x] ITER1-003 [x] ITER1-004 [x] ITER1-005
Iteration 2 (Google Sync): [ ] ITER2-001 [ ] ITER2-002 [ ] ITER2-003 [ ] ITER2-004
Iteration 3 (Journal): [ ] ITER3-001 [ ] ITER3-002 [ ] ITER3-003 [ ] ITER3-004
Iteration 4 (Calendar): [ ] ITER4-001 [ ] ITER4-002 [ ] ITER4-003 [ ] ITER4-004
Iteration 5 (Photos): [ ] ITER5-001 [ ] ITER5-002 [ ] ITER5-003 [ ] ITER5-004
Iteration 6 (Advanced): [ ] ITER6-001 [ ] ITER6-002 [ ] ITER6-003
```

### Value Delivery Timeline
- **Iteration 1**: Working contact management system with global search, transactional events, and MCP foundation
- **Iteration 2**: Integration architecture foundation with Google Contacts sync and worker isolation
- **Iteration 3**: Extended integrations (Immich, Strava, Firefly III) with comprehensive MCP tools
- **Iteration 4**: Journal system with mood tracking, search capabilities, and journal MCP tools
- **Iteration 5**: Calendar integration with Google Calendar sync, search, and calendar MCP tools
- **Iteration 6**: Photo albums with person-contact linking, search, and photo MCP tools
- **Iteration 7**: Production-ready with advanced protocols and comprehensive testing
