# Personal CRM & Journal System - Task Overview

## Project Overview
A comprehensive personal management system with Python FastAPI backend, Next.js frontend, and AI integration via MCP protocol. Integrates personal data from multiple sources (Google Calendar/Contacts, Immich photos, Strava activities, financial data) with both web interface and AI assistant capabilities.

## Technology Stack
- **Backend:** Python 3.11+ with FastAPI, PostgreSQL, Dishka dependency injection
- **Frontend:** Next.js with React, shadcn/ui components, Tailwind CSS
- **AI Integration:** MCP (Model Context Protocol) with FastMCP v2 framework
- **Search:** MeiliSearch with event-driven indexing
- **Background Processing:** ARQ task queue with Redis
- **Testing:** pytest (backend), Jest/React Testing Library (frontend), Playwright (e2e)
- **Deployment:** Docker with nginx proxy support

## Development Principles
- **Test-First Development:** Write tests before implementation - no exceptions
- **Reviewable PRs:** Each task creates PRs with max 10 files changed
- **Quality Gates:** All tests, linting, and type checking must pass
- **Architecture Consistency:** Follow established patterns (Dishka DI, ARQ workers, etc.)
- **AI-Optimized:** Design for AI assistant understanding and integration

The [architecture document](./architecture.md) provides a high-level overview of the system architecture and navigation.

The [AI guidelines](./ai-guidelines.md) provide essential information for AI assistants working on the project. The AI Guidelines MUST be followed at all times. NO EXCEPTIONS.

Integrations MUST follow the integration architecture specified in the [integration architecture document](./architecture/integration-architecture.md). Including using the event based architecture.

## Task Organization
Tasks are organized into **feature iterations** that deliver end-to-end value incrementally. Each iteration is documented in detail in separate files for better organization and navigation.

## Product Specifications

Read these first when working on the active product-alignment streams:

- **[Contacts Product Specification](./product-specifications/contacts-product-specification.md)** - target product behaviour for the contacts improvement stream
- **[Journals Product Specification](./product-specifications/journals-product-specification.md)** - target product behaviour for the journals improvement stream
- **[Outdoor Logbook Product Specification](./product-specifications/outdoor-logbook-product-specification.md)** - target product behaviour for the outdoor logbook expansion
- **[Integration Architecture & Strava Product Specification](./product-specifications/integration-architecture-and-strava-product-specification.md)** - event bus migration and Strava integration
- **[Activity History Product Specification](./product-specifications/activity-history-product-specification.md)** - unified, event-driven activity history across contacts and journals

---

## Iterations Overview

### [Iteration 1: Basic Contact Management (MVP)](./tasks/iteration-1-basic-contact-management.md)
**Status:** ✅ COMPLETED
**Goal:** Establish core contact management functionality with search capabilities and MCP integration

**Key Deliverables:**
- Python FastAPI backend with PostgreSQL database
- Next.js frontend with shadcn/ui components
- MeiliSearch-powered search capabilities
- MCP (Model Context Protocol) integration for AI assistants
- Comprehensive testing suite (pytest, Jest, Playwright)
- Docker-based development environment

**Architecture Established:**
- SQLAlchemy Core with explicit SQL queries
- Simple dependency injection (later upgraded to Dishka)
- Event-driven MeiliSearch indexing via transactional outbox pattern
- OAuth2 authentication with configurable providers

### [Iteration 1.5: Enhanced Layout & Navigation (MVP Usability)](./tasks/iteration-1.5-enhanced-layout-navigation.md)
**Status:** ✅ COMPLETED
**Goal:** Improve user experience with modern navigation patterns and contact filtering

**Key Deliverables:**
- Redesigned header with prominent search functionality
- Hierarchical sidebar navigation with collapsible sections
- Contact filtering and favourites functionality
- Tag-based grouping and organization
- Responsive design for mobile and desktop
- 295 tests passing with 100% success rate

**Quality Improvements:**
- Extracted reusable components (`ContactCard`, `ContactList`) and hooks (`useDisplayContacts`)
- Fixed Playwright e2e tests with proper `waitForSelector` calls
- Improved code quality and maintainability

### [Iteration 2: Integration Architecture Foundation](./tasks/iteration-2-integration-architecture.md)
**Status:** 🟡 IN PROGRESS (60% complete)
**Goal:** Establish robust integration architecture with Google Contacts sync

**Key Deliverables:**
- Dishka dependency injection framework migration
- ARQ task queue with Redis for background processing
- Google Contacts bidirectional synchronization (60% complete)
- Isolated worker architecture for scalability
- Production resilience patterns (idempotency, retry logic, monitoring)

**Current Progress:**
- ✅ Integration foundation with ARQ and Redis
- ✅ Google API client with automatic token refresh
- ✅ Data modeling and transformation
- ✅ Idempotent persistence and incremental sync logic
- 🟡 ARQ worker implementation with Dishka integration (pending)
- 🟡 Two-way sync and conflict resolution (pending)

### [Iteration 2.5: Interactive Contact Editing](./tasks/iteration-2.5-interactive-contact-editing.md)
**Status:** 🟡 PLANNED
**Goal:** Transform contact view/edit screen into a powerful, interactive interface with inline field editing

**Key Deliverables:**
- Click-to-edit functionality for all contact fields
- Individual field save/cancel with optimistic updates
- Backend PATCH endpoints for partial field updates
- Enhanced user experience with contextual icons and validation
- Comprehensive accessibility and mobile support

**Architecture Benefits:**

- Leverages existing contact domain and API patterns
- Maintains clean separation between UI, API, and domain layers
- Provides foundation for advanced editing features in future iterations

### [Iteration 3: Extended Integrations](./tasks/iteration-3-extended-integrations.md)
**Status:** 🟡 PLANNED
**Goal:** Expand integration capabilities with financial data and unified integration management

**Planned Integrations:**
- **Firefly III Integration:** Financial data with transaction linking
- **Enhanced MCP Tools:** Cross-integration search and management
- **Integration Dashboard:** Unified management interface

**Architecture Benefits:**
- Leverages integration patterns established in Iteration 2
- Unified integration management dashboard
- Cross-integration analytics and insights

**Note:** Strava and Immich integrations moved to Iterations 5 and 6 to align with journal system dependencies.

### [Iteration 4: Journal System - Core & Base Types](./tasks/iteration-4-journal-system.md)
**Status:** 🟡 PLANNED
**Dependencies:** Iteration 2 (Integration Architecture Foundation)
**Goal:** Build comprehensive journal system with hierarchical structure, base types, and integration preparation

**Key Features:**
- Flexible journal domain with hierarchical parent-child relationships
- Base journal types: NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM
- Contact relationships (PARTICIPANT, INVITEE, MENTION, ABOUT)
- Hierarchical tag system for journals
- Calendar support for EVENT type journals
- MeiliSearch-powered search and filtering
- REST API and MCP tools for AI integration
- Preparation for Strava and Immich integrations

**Architecture Established:**
- Type system with automatic dependency resolution
- Event-driven MeiliSearch indexing
- Inline editing UI patterns
- Integration-ready domain models

### [Iteration 4.5: Journal System - Fitness & Activity Types](./tasks/iteration-4.5-fitness-activity-types.md)
**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (Journal Core)
**Goal:** Add comprehensive fitness and outdoor activity tracking with specialized activity types

**Key Features:**
- Routes domain for reusable route/track names
- FITNESS base type with GPX tracks, heart rate, elevation data
- OUTDOOR_ACTIVITY type with weather, role, leadership tracking
- Specialized activity types: BUSHWALKING, ABSEILING_TRIP, CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, JOGGING
- Australian Track Grading System for bushwalking
- French grading system for canyoning
- GPX track display using Google Maps API
- Activity statistics and analytics
- Preparation for Strava integration

### [Iteration 5: Integration Architecture & Strava Integration](./tasks/iteration-5-integration-architecture-and-strava.md)
**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4.5 (Fitness & Activity Types), Iteration 7 (merge/review — partial), Iteration 9 (outdoor logbook activity types — partial)
**Goal:** Replace the hard-coded outbox processor with a Redis Streams event bus, make integrations pluggable, and deliver one-way Strava activity import with merge review

**Key Features:**
- Redis Streams event bus replacing direct-dispatch outbox processor
- Pluggable integration dashboard with dynamic panel rendering
- Strava OAuth 2.0 authentication with webhook-first sync
- Activity data import with GPX track storage and elevation derivation
- Merge review queue integration for duplicate/overlap detection
- Participant detection from Strava athletes with manual mapping
- External system link display on journal/contact detail pages

**Architecture:**
- Redis Streams consumer groups for independent event consumption
- Transactional outbox relay preserving atomicity guarantees
- Pluggable integration registry with dynamic UI rendering
- Follows isolated worker architecture pattern
- See [Integration Architecture & Strava Product Specification](./product-specifications/integration-architecture-and-strava-product-specification.md) for full spec

### [Iteration 6: Immich Integration](./tasks/iteration-6-immich-integration.md)
**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (Journal Core with PHOTO_ALBUM type)
**Goal:** Integrate Immich photo service with album linking and photo display in journals

**Key Features:**
- Immich API client with authentication
- Album and photo data synchronization
- Photo gallery display in journals
- Album linking to journal entries
- Photo metadata extraction
- ARQ worker for background sync
- Optional: Person-to-contact matching (future enhancement)

**Architecture:**
- Follows isolated worker architecture pattern
- On-demand photo fetching (no local caching)
- Integration with PHOTO_ALBUM journal type

### [Iteration 7: Journals Product Alignment, Calendar Sync & Time Navigation](./tasks/iteration-7-calendar-integration.md)
**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (journal core), Iteration 2 (Google integration and worker foundations), existing journal search/detail foundations
**Goal:** Deliver the journals product specification in reviewable slices covering multi-calendar sync, merge/review workflows, hierarchy, time-oriented journal browsing, calendar views, and AI/MCP parity

**Key Features:**
- Multi-calendar EVENT journal sync with ETag-based conflict handling
- Needs Review queue and journal merge workflow
- Parent-child journal creation and hierarchy visibility
- Current-day-centred bidirectional infinite scroll journal list
- Calendar views (month, week, day, agenda) with sync visibility
- AI daily summaries and day-level stats with MCP parity

**Architecture:**
- Extends the Google integration and isolated worker patterns from Iteration 2
- Keeps journals as the canonical record while linking to external calendar events
- Reuses the contacts-style reviewable PR and full-coverage delivery model
- Preserves parity between UI capabilities and MCP workflows

### [Iteration 8: Advanced Features & Analytics](./tasks/iteration-8-advanced-features.md)
**Status:** 🟡 PLANNED
**Goal:** Deliver advanced analytics, AI insights, and comprehensive personal data intelligence

**Key Features:**
- Advanced analytics across all integrated data sources
- AI-powered life pattern recognition and insights
- Comprehensive testing and quality assurance (80%+ coverage)
- Performance optimization and scalability improvements
- Advanced security and privacy features
- Future protocol support and extensibility

### [Iteration 9: Outdoor Logbook](./tasks/iteration-9-outdoor-logbook.md)
**Status:** 🟡 PLANNED
**Dependencies:** Iteration 7 (journal hierarchy, calendar sync, MCP parity), Iteration 4.5 (fitness and activity types)
**Goal:** Expand outdoor activity journals into a comprehensive outdoor logbook

**Key Features:**
- Structured abseil pitch tracking with anchor details and auto-calculated totals
- Reusable activity templates for canyoning, caving, and climbing
- New activity types: CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING
- Supporting types: OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE
- Gear items entity with future SnipeIT sync compatibility
- PDF logbook export with yearly summaries and participant index
- MCP parity for all new capabilities

### [Iteration 12: Activity History (Journals + Unified Foundation)](./tasks/iteration-12-activity-history.md)
**Status:** 🟡 IN PROGRESS — ITER12-001 (shared foundation) complete
**Dependencies:** Iteration 4 (journal core + events), Iteration 5 (Redis Streams event bus, outbox relay, stream consumers), existing contact activity history
**Goal:** Deliver field-level activity history for journals of all types, displayed at the bottom of the journal UI with full provenance, by generalising contact history into a single shared, event-driven system

**Key Features:**
- Unified, entity-agnostic history model, API shape, and activity-feed component shared by contacts and journals
- Event-driven history projection: a `HistoryProjectionConsumer` derives history from the `pms:domain-events` stream (like the search indexer), replacing the synchronous dual-write
- Journal history for all types — base, fitness, outdoor activity, supporting types, routes, and gear — with provenance (UI, MCP, system, integrations)
- Journal history REST endpoint and MCP `get_journal_history` parity
- Contacts migrated onto the same event-driven foundation (no user-visible change)

**Architecture:**
- History as a read-model projection of domain events (integrity by construction — single publish, no dual-write)
- Idempotent projection (unique `event_id`-scoped key + `ON CONFLICT DO NOTHING`) for at-least-once stream delivery
- Provenance carried in event payloads; row timestamps from `event.occurred_at`
- See [Activity History Product Specification](./product-specifications/activity-history-product-specification.md) for full spec

### [Iteration 15: Integration Link Consolidation (fix contact duplication)](./tasks/iteration-15-integration-link-consolidation.md)
**Status:** 🔴 PLANNED
**Dependencies:** Iteration 11 (Immich), Iteration 13 (Contact Merge), Iteration 14 (Worker Standardisation)
**Goal:** Consolidate the overlapping `external_references` and `sync_metadata` tables onto a single canonical integration-link store to eliminate the Immich→Google→Immich contact duplication loop, and migrate/clean up the duplicates already created

**Key Deliverables:**
- `sync_metadata` becomes the single canonical link store; `external_references` retired
- Contact dedup keyed on the link every worker already writes (fixes the root-cause asymmetry)
- Additive-first migration with backfill + deterministic conflict quarantine
- Data migration to merge existing bug-created duplicate contacts
- Hardening: name-based reconciliation fallback for email-less contacts; local-delete propagation to Google

### [Iteration 16: Outdoor Logbook Improvements](./tasks/iteration-16-outdoor-logbook-improvements.md)
**Status:** 🔵 PLANNED — sub-iterations and PR-sized phases defined (20 phases); ready to implement
**Dependencies:** Iteration 9 (Outdoor Logbook), Iteration 10 (SnipeIT gear checkout), Iteration 11 (Immich album links), Iteration 12 (Activity History provenance)
**Goal:** Add the review, surfacing, and reporting layer on top of the outdoor logbook — find incomplete activities, durable template references, an overview/dashboard page, and a polished PDF — with full UI and MCP parity

**Sub-Iterations:**
- ITER16-001: Durable template reference on abseiling activities (`template_id` consolidated onto `abseiling_data` + `abseiling` template type, preserved on edit, shown in journal/PDF/MCP)
- ITER16-002: Incomplete outdoor activities review (3 rules: no attributes / missing template / no participants) with reversible whole-entry dismiss
- ITER16-003: Outdoor Logbook overview dashboard (upcoming activities, checked-out gear, recent totals by type, abseil templates done)
- ITER16-004: PDF logbook output improvements (summary-first, TOC, linked indexes, type icons, Immich links, GPX track maps, document outline)

**Reference:** [Outdoor Logbook Improvements Product Specification](./product-specifications/outdoor-logbook-improvements-product-specification.md)

### [Iteration 17: Journal Tags Parity](./tasks/iteration-17-journal-tags-parity.md)
**Status:** 🔵 PLANNED — PR-sized phases defined; ready to implement
**Dependencies:** Iteration 4 (journal tag tables and endpoints), Iteration 4.6 (journal tag filtering + detail-view add/remove), Iteration 12 (unified event-driven history), Iteration 2.6 (contact tag management UX — the reference behaviour)
**Goal:** Bring journal tag functionality to exact parity with contact tags across the UI, backend management operations, filtering, history, and MCP

**Sub-Iterations:**
- ITER17-001: Journal tag management backend — `description` column, update endpoint, delete parity (un-assign instead of 409), merge
- ITER17-002: Journal list tag filtering parity — multi-tag `tag_ids`, hierarchical descendant expansion, `/journals?tag=` deep link
- ITER17-003: Journal detail tag editor matching `ContactTagsEditor` (searchable add, inline create with colour, colour-coded badges)
- ITER17-004: Sidebar journal tag tree with context-menu management (create/edit/delete/merge dialogs)
- ITER17-005: Journal tag history events feeding the journal activity feed
- ITER17-006: MCP journal tag parity (list, merge, management operations)

---

## Current Status & Next Steps

**Immediate Priority:** Complete Iteration 2 (Integration Architecture Foundation)
- Finish Google Contacts integration (ARQ worker + two-way sync)
- Complete Dishka migration for entire application
- Implement production resilience patterns
- Build integration management UI

**Next Priority:** Begin Iteration 4 (Journal System - Core & Base Types)
- Establish journal domain with hierarchical structure
- Implement base journal types (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM)
- Build REST API and MCP tools
- Create journal UI with inline editing
- Prepare integration points for Strava and Immich

**Development Guidelines:**
- Each task creates reviewable PRs (~5-10 files changed preferred)
- All tests, linting, and type checking must pass before completion
- Follow established architecture patterns (Dishka DI, ARQ workers, FastMCP v2)
- Maintain comprehensive test coverage across all layers
- Reference [journal system specification](../journal-system-specification.md) for detailed requirements

**Quality Standards:**
- Test-first development approach
- Real database testing with Docker PostgreSQL
- Comprehensive error handling and monitoring
- Security-first design with encrypted credential storage
- All changes must leave system in working state with passing tests

For detailed task breakdowns, acceptance criteria, and implementation notes, see the individual iteration files linked above.
