# Iteration 4: Journal System - Core & Base Types

**Status:** 🟢 IN PROGRESS
**Dependencies:** Iteration 2 (Integration Architecture Foundation)
**Goal:** Build comprehensive journal system with hierarchical structure, base types, and integration preparation

## Overview

This iteration establishes the journal system foundation following the [journal system specification](../journal-system-specification.md):

**Core Features:**
- Flexible journal domain with hierarchical parent-child relationships (max depth 5)
- Base journal types: NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM
- Type system with automatic dependency resolution
- Contact relationships (PARTICIPANT, INVITEE, MENTION, ABOUT)
- Hierarchical tag system for journals
- Calendar support for EVENT type journals
- MeiliSearch-powered search and filtering
- REST API and MCP tools for AI integration

**Integration Preparation:**
- PHOTO_ALBUM type with `immich_album_id` field (ready for Iteration 6)
- FITNESS type preparation in domain models (implemented in Iteration 4.5)
- Change event tracking with source attribution

## Prerequisites

- Iteration 2 completed (Dishka DI, ARQ workers, integration patterns)
- MeiliSearch indexing infrastructure available
- Contact domain established (for contact relationships)
- Outbox pattern for event-driven indexing

## Tasks

### ITER4-001: Journal Domain Foundation 🟢 IN PROGRESS
**Description:** Establish base journal entity with hierarchical structure and validation
**Strategy:** Single focused task for core domain model
**Specification Reference:** [Domain Model](../journal-system-specification.md#domain-model)
**PR:** [#210](https://github.com/hjed/personal-management-system/pull/210) - Awaiting CI

**PR Size:** ~18 files (domain model, validation, migration, repository, DI, tests)

**Implementation Notes:**
- Used Integer IDs instead of UUID for consistency with contacts domain (better SQL performance)
- Used VARCHAR(50) for user_id to match existing user_google_auth patterns (no users table yet)
- Entity placed in `backend/app/core/journal/models/` following existing domain patterns
- Repository includes hierarchy queries (get_children, get_ancestors, get_depth)

**Acceptance Criteria:**
- [x] Create `Journal` entity in `backend/app/core/journal/models/` with all required fields:
  - `id` (Integer), `user_id`, `title` (max 500 chars), `content` (markdown)
  - `event_date_range` (start_date, end_date as UTC timestamps)
  - `parent_id` (nullable, for hierarchy), `order` (integer)
  - `created_at`, `updated_at`
- [x] Implement hierarchical validation:
  - Maximum nesting depth: 5 levels (constant MAX_HIERARCHY_DEPTH)
  - Repository provides get_depth() for cycle prevention
  - `event_date_range.start` <= `event_date_range.end` (EventDateRange value object)
  - Future dates allowed for planned events
- [x] Create `journals` table migration with proper indexes:
  - Index on `event_date_range` for date queries
  - Index on `parent_id` for hierarchy queries
  - Index on `user_id` for user filtering
  - Foreign key constraints with proper cascading (ON DELETE SET NULL)
- [x] Implement child ordering logic (by event_date_range.start, then order field)
- [x] Write unit tests for domain validation rules (18 tests)
- [x] Write integration tests for database constraints
- [x] Document domain model in code comments

**Files Created:**
- `backend/app/core/journal/models/entities.py` - Journal entity
- `backend/app/core/journal/models/value_objects.py` - EventDateRange
- `backend/app/core/journal/models/constants.py` - MAX_HIERARCHY_DEPTH, MAX_TITLE_LENGTH
- `backend/app/core/journal/models/exceptions.py` - Domain exceptions
- `backend/app/core/journal/models/repositories.py` - JournalRepository interface
- `backend/app/core/journal/adapters/sql/journal_repository.py` - SqlJournalRepository
- `backend/app/infrastructure/di/journal.py` - Dishka DI provider
- `backend/app/migrations/versions/0009_create_journals_table.py` - Migration
- `backend/tests/unit/journal/test_entities.py` - Unit tests
- `backend/tests/integration/journal/test_journal_repository_integration.py` - Integration tests

**Database Schema (Actual):**
```sql
CREATE TABLE journals (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) NOT NULL,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    event_date_range_start TIMESTAMP WITH TIME ZONE NOT NULL,
    event_date_range_end TIMESTAMP WITH TIME ZONE NOT NULL,
    parent_id INTEGER REFERENCES journals(id) ON DELETE SET NULL,
    "order" INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_journals_event_date_range_valid CHECK (event_date_range_start <= event_date_range_end)
);
```

### ITER4-002: Base Journal Types - Part 1 (NOTE, EVENT, MOOD_RATING) ✅ COMPLETE
**Description:** Implement first set of base journal types with calendar support
**Strategy:** Single task for three foundational types
**Specification Reference:** [Journal Types](../journal-system-specification.md#journal-types), [Calendar Info](../journal-system-specification.md#calendar-info-event-type)

**PR Size:** ~7 files (3 type tables, calendars table, type detection, migrations, tests)

**Acceptance Criteria:**
- [x] **NOTE type:** No additional table (uses only base journal fields)
- [x] **EVENT type:** Create `journal_calendar_info` table:
  - `journal_id` (PK, FK to journals)
  - `calendar_id` (FK to calendars, required)
  - `start_time`, `end_time` (nullable for all-day events)
  - `is_all_day` (boolean, default false)
  - `location` (string, nullable)
  - `sync_invitees` (boolean, default based on import source)
  - `created_at`, `updated_at`
- [x] **MOOD_RATING type:** Create `journal_mood_data` table:
  - `journal_id` (PK, FK to journals)
  - `mood_value` (integer 1-10, nullable)
  - `mood_label` (string, nullable)
  - `energy_level` (integer 1-10, nullable)
  - `created_at`, `updated_at`
- [x] Create `calendars` table:
  - `id` (UUID), `user_id`, `name`, `description` (nullable)
  - `color` (hex color), `is_synced_to_google` (boolean)
  - `google_calendar_id` (string, nullable)
  - `created_at`, `updated_at`
- [x] Implement type detection logic (journal has type if row exists in type table)
- [x] Add database migrations with proper foreign key constraints
- [x] Write unit tests for type-specific validation
- [x] Write integration tests for type data persistence
- [x] Document type system architecture in code comments

**Implementation Notes:**
- Type detection is implemented via repository pattern: `CalendarInfoRepository.find_by_journal_id()` returns non-None if journal has EVENT type
- JournalType enum defined with all 15 planned types for future expansion
- Domain entities (Calendar, CalendarInfo, MoodData) are dataclasses with validation
- SQL repositories use raw SQL with SQLAlchemy Core for consistency with existing patterns
- DI providers added for CalendarRepository, CalendarInfoRepository, MoodDataRepository
- Migration 0010 creates all three tables with proper FK constraints and check constraints

**Files Created:**
- `backend/app/core/journal/models/calendar.py` - Calendar domain entity
- `backend/app/core/journal/models/calendar_info.py` - CalendarInfo (EVENT type) entity
- `backend/app/core/journal/models/mood_data.py` - MoodData (MOOD_RATING type) entity
- `backend/app/core/journal/models/journal_types.py` - JournalType enum
- `backend/app/core/journal/adapters/sql/calendar_repository.py` - SqlCalendarRepository
- `backend/app/core/journal/adapters/sql/calendar_info_repository.py` - SqlCalendarInfoRepository
- `backend/app/core/journal/adapters/sql/mood_data_repository.py` - SqlMoodDataRepository
- `backend/app/migrations/versions/0010_create_journal_types_tables.py` - Migration
- `backend/tests/unit/journal/test_calendar_entity.py` - Calendar unit tests
- `backend/tests/unit/journal/test_calendar_info_entity.py` - CalendarInfo unit tests
- `backend/tests/unit/journal/test_mood_data_entity.py` - MoodData unit tests
- `backend/tests/unit/journal/test_journal_types.py` - JournalType enum tests
- `backend/tests/integration/journal/test_calendar_repository_integration.py` - Integration tests
- `backend/tests/integration/journal/test_calendar_info_repository_integration.py` - Integration tests
- `backend/tests/integration/journal/test_mood_data_repository_integration.py` - Integration tests

**Files Modified:**
- `backend/app/core/journal/models/__init__.py` - Export new entities and repositories
- `backend/app/core/journal/models/constants.py` - Add calendar and mood constants
- `backend/app/core/journal/models/exceptions.py` - Add type-specific exceptions
- `backend/app/core/journal/models/repositories.py` - Add repository interfaces
- `backend/app/core/journal/adapters/sql/__init__.py` - Export SQL repositories
- `backend/app/infrastructure/di/journal.py` - Add DI providers
- `backend/tests/integration/conftest.py` - Add test schema for new tables

### ITER4-003: Base Journal Types - Part 2 (PLAN, TRAVEL, PHOTO_ALBUM) ✅ COMPLETED
**Description:** Implement remaining base journal types with Immich preparation
**Strategy:** Single task for three complex types
**Specification Reference:** [Plan Data](../journal-system-specification.md#plan-data-plan-type), [Travel Data](../journal-system-specification.md#travel-data-travel-type), [Photo Album Data](../journal-system-specification.md#photo-album-data-photo_album-type)

**PR Size:** ~15 files (domain models, repositories, migrations, tests)
**Completed:** 2024-12-09

**Acceptance Criteria:**
- [x] **PLAN type:** Create tables:
  - `journal_plan_data` (journal_id PK, created_at, updated_at)
  - `journal_plan_documents` (id, journal_id FK, url, title, description, order, created_at)
- [x] **TRAVEL type:** Create tables:
  - `journal_travel_data` (journal_id PK, created_at, updated_at)
  - `journal_travel_flights` (id, journal_id FK, flight_number, airline, airports, times, booking info, order, created_at)
  - `journal_travel_accommodations` (id, journal_id FK, name, address, check-in/out dates, booking info, order, created_at)
  - `journal_travel_transportation` (id, journal_id FK, type, details, booking_reference, order, created_at)
- [x] **PHOTO_ALBUM type:** Create `journal_photo_album_data` table:
  - `journal_id` (PK, FK to journals)
  - `immich_album_id` (string, Immich album identifier)
  - `created_at`, `updated_at`
  - **Note:** Prepares for Immich integration (Iteration 6)
- [x] Add database migrations with proper constraints and indexes
- [x] Implement order field handling for child items (flights, accommodations, etc.)
- [x] Write unit tests for type-specific validation
- [x] Write integration tests for complex type data persistence
- [x] Document Immich integration preparation in code comments

**Implementation Details:**
- **Domain Models:** 7 new entities (PlanData, PlanDocument, TravelData, TravelFlight, TravelAccommodation, TravelTransportation, PhotoAlbumData)
- **Repository Interfaces:** 3 new interfaces with comprehensive CRUD operations
- **SQL Implementations:** 3 repository implementations with optimized queries
- **Database Migration:** Migration 0011 creates 7 tables with proper constraints
- **Tests:** 32+ unit tests, comprehensive integration tests
- **Validation:** Full entity validation with custom exceptions
- **DI Integration:** All repositories configured in dependency injection

**Bugfixes Applied (2025-12-17):**
- Fixed test schema in `conftest.py` to match migration:
  - Added `confirmation_number` column to `journal_travel_flights` table
  - Changed `check_in`/`check_out` (TIMESTAMP) to `check_in_date`/`check_out_date` (DATE) in `journal_travel_accommodations`
  - Made `address` column nullable in `journal_travel_accommodations` to match spec
  - Added check constraint for valid dates
- Fixed MyPy error in `sample_journal_id` fixture return type

### ITER4-004: Contact Relationships & Tags 🟡 PLANNED
**Description:** Implement journal-contact relationships and hierarchical tag system
**Strategy:** Single task for relationship and tag infrastructure
**Specification Reference:** [Contact Relationships](../journal-system-specification.md#contact-relationships), [Tags](../journal-system-specification.md#tags)

**PR Size:** ~6 files (2 main tables + assignments, migrations, tests)

**Acceptance Criteria:**
- [ ] Create `journal_contact_relationships` table:
  - `journal_id` (FK to journals)
  - `contact_id` (FK to contacts)
  - `relationship_type` (enum: PARTICIPANT, INVITEE, MENTION, ABOUT)
  - `created_at`
  - Primary key: (journal_id, contact_id, relationship_type)
- [ ] Create `journal_tags` table (hierarchical like contact tags):
  - `id` (UUID), `name`, `parent_id` (FK to journal_tags, nullable)
  - `color` (hex color), `created_at`, `updated_at`
- [ ] Create `journal_tag_assignments` table:
  - `journal_id` (FK to journals)
  - `tag_id` (FK to journal_tags)
  - `created_at`
  - Primary key: (journal_id, tag_id)
- [ ] Implement relationship type validation (enum enforcement)
- [ ] Implement tag hierarchy validation (prevent cycles)
- [ ] Add database migrations with proper constraints
- [ ] Write unit tests for relationship and tag validation
- [ ] Write integration tests for relationship and tag persistence
- [ ] Document relationship types and tag hierarchy in code comments

**Relationship Types:**
- **PARTICIPANT:** Contact attended/participated in the event
- **INVITEE:** Contact was invited to the event
- **MENTION:** Contact is mentioned in journal content (manually tagged)
- **ABOUT:** Journal is specifically about this contact

### ITER4-005: Journal Repository & Service Layer 🟡 PLANNED
**Description:** Implement repository and service layer with type dependency resolution
**Strategy:** Single task for data access and business logic
**Specification Reference:** [Type Dependency Rules](../journal-system-specification.md#journal-types)

**PR Size:** ~8 files (repository interface, implementation, service, tests)

**Acceptance Criteria:**
- [ ] Create `JournalRepository` interface in `backend/app/core/journal/adapters/sql/`:
  - CRUD operations (create, get, update, delete)
  - Filtering methods (by date range, types, contacts, tags, calendar, parent)
  - Hierarchy queries (get children, get descendants, get ancestors)
  - Type detection queries (check which types a journal has)
- [ ] Implement `SqlJournalRepository` using SQLAlchemy Core with explicit SQL:
  - Parameterized queries for security
  - Transaction support
  - Proper error handling with IntegrityError conversion
- [ ] Create `JournalService` in `backend/app/core/journal/` using Dishka DI:
  - Journal CRUD with validation
  - Type dependency resolution (automatic type addition)
  - Hierarchy validation (max depth, cycle prevention)
  - Change event publishing via outbox pattern
- [ ] Implement type dependency logic:
  - When type added, automatically add all dependent types
  - Create type data rows with NULL values for optional fields
  - Validate dependencies are transitive (e.g., CANYONING → BUSHWALKING → OUTDOOR_ACTIVITY → FITNESS)
- [ ] Add domain events: JournalCreated, JournalUpdated, JournalDeleted, JournalTypeAdded, JournalTypeRemoved
- [ ] Write unit tests for service business logic (with mocked repository)
- [ ] Write integration tests with real PostgreSQL database
- [ ] Document type dependency resolution algorithm in code comments

**Type Dependency Examples:**
- Adding FITNESS: No dependencies, just create journal_fitness_data row
- Adding OUTDOOR_ACTIVITY: Automatically adds FITNESS
- Adding CANYONING: Automatically adds BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS

### ITER4-006: Journal REST API 🟡 PLANNED
**Description:** Create comprehensive REST API endpoints with JSON API compliance
**Strategy:** Single task for complete API layer
**Specification Reference:** [REST API Endpoints](../journal-system-specification.md#rest-api-endpoints)

**PR Size:** ~9 files (controller, schemas, tests)

**Acceptance Criteria:**
- [ ] Create `JournalController` in `backend/app/api/journals/` with JSON API compliance
- [ ] Implement core CRUD endpoints:
  - `GET /api/journals` - List with filtering (type, date_range, contact_id, tag_id, calendar_id, parent_id, search)
  - `POST /api/journals` - Create with type data and relationships
  - `GET /api/journals/{id}` - Get single journal with all data
  - `PUT /api/journals/{id}` - Full replacement update
  - `PATCH /api/journals/{id}` - Partial update
  - `DELETE /api/journals/{id}` - Delete with cascade/orphan options
- [ ] Implement type management endpoints:
  - `POST /api/journals/{id}/types` - Add type(s) with automatic dependencies
  - `DELETE /api/journals/{id}/types/{type}` - Remove type with validation
  - `PUT /api/journals/{id}/types/{type}/data` - Update type-specific data
- [ ] Implement relationship management endpoints:
  - `POST /api/journals/{id}/contacts` - Add contact relationship
  - `DELETE /api/journals/{id}/contacts/{contact_id}` - Remove relationship(s)
  - `GET /api/contacts/{id}/journals` - Get journals for contact
- [ ] Create Pydantic schemas for request/response validation
- [ ] Implement proper error handling with FastAPI exception handlers
- [ ] Generate OpenAPI documentation
- [ ] Write integration tests for all endpoints
- [ ] Document API patterns in code comments

**Response Format:**
- Embedded type data organized by type
- Embedded relationships (contacts, tags, calendar)
- Child count for parent journals
- Pagination metadata

### ITER4-007: MeiliSearch Integration 🟡 PLANNED
**Description:** Implement event-driven journal indexing and search
**Strategy:** Single task for search infrastructure
**Specification Reference:** [MeiliSearch Integration](../journal-system-specification.md#meilisearch-integration)

**PR Size:** ~5 files (indexing service, search endpoint, tests)

**Acceptance Criteria:**
- [ ] Create `JournalIndexingService` in `backend/app/infrastructure/search/`:
  - Index journals on create/update/delete via outbox events
  - Index type data changes
  - Index relationship changes
- [ ] Configure MeiliSearch index with:
  - Searchable fields: title (high weight), content (medium weight), location
  - Filterable fields: event_date_range, types, contact_ids, tag_ids, calendar_id, parent_id
  - Sortable fields: event_date_range, created_at, title
- [ ] Implement search endpoint `GET /api/journals/search`:
  - Full-text search across title and content
  - Filter by type(s), date range, contacts, tags, calendar, parent
  - Sort by date, relevance, title
  - Pagination support
- [ ] Add journals to global search index (`/api/search`)
- [ ] Implement search result highlighting
- [ ] Write integration tests for indexing and search
- [ ] Document search capabilities in API documentation

**Indexed Fields:**
```json
{
  "id": "uuid",
  "title": "searchable",
  "content": "searchable",
  "event_date_range_start": "filterable, sortable",
  "event_date_range_end": "filterable, sortable",
  "types": ["filterable"],
  "contact_ids": ["filterable"],
  "tag_ids": ["filterable"],
  "calendar_id": "filterable",
  "parent_id": "filterable",
  "location": "searchable"
}
```

### ITER4-008: Journal UI - List & Detail Views 🟡 PLANNED
**Description:** Build journal list and detail views with inline editing
**Strategy:** Single task for core UI components
**Specification Reference:** [Display Requirements](../journal-system-specification.md#display-requirements), [Frontend Components](../journal-system-specification.md#frontend-components)

**PR Size:** ~8 files (list component, detail component, sub-components, tests)

**Acceptance Criteria:**
- [ ] Create `JournalList` component in `frontend/src/components/journals/`:
  - Filterable list with sidebar filters (date range, types, contacts, tags, calendar)
  - Date grouping (day/week/month)
  - Type icons for visual identification
  - Color-coding by calendar (primary) or tag (secondary)
  - Contact chips display
  - Expandable content preview (first 200 chars)
  - Infinite scroll pagination
  - Quick actions (edit, delete, duplicate)
- [ ] Create `JournalDetail` component:
  - Inline editing (similar to contact detail page)
  - Markdown content rendering with live preview
  - Type-specific data sections (collapsible, inline editable)
  - Contact relationship display (grouped by type, inline editable)
  - Tag chips (clickable to filter, inline editable)
  - Calendar badge (color-coded, inline editable)
  - Type icons for visual identification
  - Parent breadcrumb navigation
  - Child journal cards (expandable)
  - Delete confirmation dialog
- [ ] Implement responsive design for mobile and desktop
- [ ] Add accessibility features (ARIA attributes, keyboard navigation)
- [ ] Write Jest unit tests for components
- [ ] Write React Testing Library tests for user interactions
- [ ] Document component patterns in code comments

**UI Patterns:**
- Calendar color bar on left edge of journal cards
- Type icons next to title
- Tag badges with tag colors
- Inline editing for all fields (click to edit)
- Optimistic UI updates

### ITER4-009: Journal UI - Forms & Editing 🟡 PLANNED
**Description:** Build journal creation and editing forms with type management
**Strategy:** Single task for form components
**Specification Reference:** [Journal Form Component](../journal-system-specification.md#journal-form-component)

**PR Size:** ~9 files (form component, type-specific forms, tests)

**Acceptance Criteria:**
- [ ] Create `JournalForm` component in `frontend/src/components/journals/`:
  - Title and content fields (markdown editor with preview)
  - Date range picker with time selection
  - Type selector with dependency handling (show dependent types automatically)
  - Type-specific field forms (conditional rendering based on selected types)
  - Contact relationship builder (add/remove contacts with relationship type)
  - Tag selector (hierarchical tag tree)
  - Calendar selector (with color preview)
  - Parent journal selector (for creating child journals)
  - Validation and error handling
  - Auto-save draft functionality
- [ ] Create type-specific form components:
  - `EventForm` (calendar, times, location, all-day toggle)
  - `MoodRatingForm` (mood value slider, mood label, energy level slider)
  - `PlanForm` (document links with title/description/order)
  - `TravelForm` (flights, accommodations, transportation with order)
  - `PhotoAlbumForm` (Immich album selector - preparation for Iteration 6)
- [ ] Implement form validation with Zod schemas
- [ ] Add error messages with accessibility (FormMessage components)
- [ ] Write Jest unit tests for form components
- [ ] Write React Testing Library tests for form interactions
- [ ] Document form patterns and validation rules in code comments

**Form Features:**
- Real-time validation with error messages
- Type dependency visualization (show which types will be auto-added)
- Markdown editor with toolbar and preview
- Date/time picker with timezone support
- Hierarchical tag selector with search
- Contact autocomplete with relationship type selection

### ITER4-010: Journal MCP Tools 🟡 PLANNED
**Description:** Implement MCP tools for AI-assisted journal management
**Strategy:** Single task for MCP integration
**Specification Reference:** [MCP Tools](../journal-system-specification.md#mcp-tools), [MCP Response Format](../journal-system-specification.md#mcp-response-format)

**PR Size:** ~6 files (MCP tools, response formatting, tests)

**Acceptance Criteria:**
- [ ] Create MCP tools in `backend/app/mcp/journals/`:
  - `create_journal_entry()` - Create with types, type_data, relationships, tags
  - `update_journal_entry()` - Update with partial data
  - `get_journal()` - Get with optional children
  - `search_journals()` - Search with filters (types, date_range, contact_id, tags, calendar_id)
  - `delete_journal()` - Delete with optional children deletion
  - `get_contact_journals()` - Get journals for contact with relationship filtering
  - `link_journal_to_contact()` - Create contact relationship
- [ ] Implement AI-optimized response format:
  - Include `summary` field (AI-friendly summary of journal)
  - Embed related data (contacts, tags, calendar, parent, children)
  - Type data organized by type for clarity
  - Children included as summaries (not full content)
- [ ] Use Dishka DI for service injection (share with REST API)
- [ ] Implement proper error handling with user-friendly messages
- [ ] Write MCP integration tests
- [ ] Document MCP tools in `docs/mcp-tools.md`

**MCP Response Example:**
```python
{
    "id": "uuid",
    "title": "string",
    "content": "markdown",
    "summary": "AI-friendly summary",  # Generated for AI
    "event_date_range": {"start": "datetime", "end": "datetime"},
    "types": ["EVENT", "MOOD_RATING"],
    "type_data": {
        "EVENT": {"calendar_id": "uuid", "location": "string", ...},
        "MOOD_RATING": {"mood_value": 8, "energy_level": 7, ...}
    },
    "contacts": [{"id": "uuid", "name": "string", "relationship_type": "PARTICIPANT"}],
    "tags": ["tag1", "tag2"],
    "calendar": {"id": "uuid", "name": "string"},
    "parent": {"id": "uuid", "title": "string"},
    "children": [{"id": "uuid", "title": "string", "summary": "string"}]
}
```

### ITER4-011: Contact Page Journal Display 🟡 PLANNED
**Description:** Add journal section to contact detail page
**Strategy:** Single task for contact-journal integration
**Specification Reference:** [Contact Page Display](../journal-system-specification.md#contact-page-display)

**PR Size:** ~5 files (component, integration with contact page, tests)

**Acceptance Criteria:**
- [ ] Create `ContactJournals` component in `frontend/src/components/contacts/`:
  - Embedded in contact detail page
  - Show all journals where contact appears (any relationship type)
  - Group by relationship type (sections for Participant, Invitee, About, Mention)
  - Collapsible sections for each relationship type
  - Show parent journals with children grouped underneath
  - Sort by event_date_range (most recent first)
  - Display journal type badges
  - Show excerpt of content (first 200 chars)
  - Link to full journal view
  - Quick add journal button (pre-fills contact as participant)
- [ ] Integrate with existing contact detail page
- [ ] Add API call to fetch contact journals (`GET /api/contacts/{id}/journals`)
- [ ] Implement responsive design for mobile
- [ ] Write Jest unit tests for component
- [ ] Write Playwright e2e tests for complete workflow:
  - View journals on contact page
  - Click to view full journal
  - Create new journal from contact page
  - Verify journal appears on contact page
- [ ] Document integration pattern in code comments

**Display Features:**
- Relationship type badges (color-coded)
- Journal type icons
- Calendar color indicators
- Expandable journal cards
- Quick actions (view, edit)

## Architecture Notes

**Domain-Driven Design:**
- Clear separation: domain entities, repositories, services, API controllers
- Type system with automatic dependency resolution at service layer
- Hierarchical structure with validation (max depth 5, cycle prevention)
- Event-driven indexing via outbox pattern

**Dependency Injection:**
- Full Dishka integration following established patterns
- Shared container between REST API and MCP server
- REQUEST scope for per-request objects
- Proper resource cleanup with yield providers

**Type System Architecture:**
- Type detection by presence of data table row
- Automatic dependency addition (transitive)
- Type-specific data tables with optional fields
- Validation at service layer (not database constraints)

**Search Integration:**
- MeiliSearch with event-driven indexing
- Faceted search (types, dates, contacts, tags, calendar)
- Full-text search across title and content
- Search result highlighting

**UI Patterns:**
- Inline editing (similar to contact detail page)
- Markdown editor with live preview
- Type-specific conditional forms
- Calendar color coding
- Responsive design for mobile and desktop

**Integration Preparation:**
- PHOTO_ALBUM type ready for Immich (Iteration 6)
- FITNESS type preparation in domain models (Iteration 4.5)
- Change event tracking with source attribution
- Merge logic foundation for Strava (Iteration 5)

## Testing Strategy

**Unit Tests:**
- Domain entity validation rules
- Type dependency resolution logic
- Service layer business logic (with mocked repositories)
- Form validation and error handling

**Integration Tests:**
- Repository operations with real PostgreSQL
- API endpoints with full request/response cycle
- MeiliSearch indexing and search
- MCP tools with Dishka DI

**E2E Tests (Playwright):**
- Complete journal creation workflow
- Inline editing on detail page
- Contact-journal integration
- Search and filtering
- Type management with dependencies

## Success Criteria

- ✅ Base journal domain with hierarchical structure (max depth 5)
- ✅ Six base journal types implemented (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM)
- ✅ Contact relationships (4 types) and hierarchical tags
- ✅ Calendar support for EVENT type journals
- ✅ Type system with automatic dependency resolution
- ✅ REST API with JSON API compliance
- ✅ MeiliSearch integration with faceted search
- ✅ Journal UI with inline editing
- ✅ MCP tools for AI integration
- ✅ Contact page journal display
- ✅ All tests passing (unit, integration, e2e)
- ✅ System in working state after each PR

## Next Steps

**Immediate:** Iteration 4.5 (Fitness & Activity Types)
- Routes domain for reusable route names
- FITNESS base type with GPX tracks
- All specialized activity types (BUSHWALKING, CANYONING, etc.)
- Activity UI components with GPX display

**Then:** Iteration 5 (Strava Integration)
- Strava OAuth and API client
- Activity sync with automatic journal creation
- Merge logic for duplicate detection

**Then:** Iteration 6 (Immich Integration)
- Immich API client and album sync
- Photo display in journals
- Album linking to journal entries

**Then:** Iteration 7 (Google Calendar Integration)
- Calendar sync with EVENT journals
- Bidirectional synchronization
- Advanced calendar features
