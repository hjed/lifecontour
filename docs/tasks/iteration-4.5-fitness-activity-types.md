# Iteration 4.5: Journal System - Fitness & Activity Types

**Status:** 🟢 COMPLETE (7/7 tasks complete; activity analytics, MCP tools, UI, and routes are delivered)
**Dependencies:** Iteration 4 (Journal Core & Base Types)
**Goal:** Add comprehensive fitness and outdoor activity tracking with specialized activity types

## Overview

This iteration extends the journal system with fitness and outdoor activity types following the [journal system specification](../journal-system-specification.md):

**Core Features:**
- Routes domain for reusable route/track names
- FITNESS base type with GPX tracks, heart rate, elevation data
- OUTDOOR_ACTIVITY type with weather, role, leadership tracking
- Specialized activity types with Australian and French grading systems
- GPX track display using interactive map components
- Activity statistics and analytics
- Preparation for Strava integration (Iteration 5)

**Activity Types Implemented:**
- **FITNESS:** Base type for all fitness activities (heart rate, distance, elevation, GPX, Strava preparation)
- **OUTDOOR_ACTIVITY:** Outdoor-specific data (weather, role, leadership)
- **BUSHWALKING:** Australian Track Grading System
- **ABSEILING_TRIP:** Abseiling/rappelling with anchor details
- **CANYONING:** French grading system, water gauge data
- **CLIMBING:** Rock climbing with grades
- **KAYAKING:** Water type tracking
- **CROSS_COUNTRY_SKIING:** Snow conditions
- **JOGGING:** Running/jogging with pace tracking

## Prerequisites

- Iteration 4 completed (Journal core with type system)
- Type dependency resolution implemented
- Journal UI with type-specific forms
- MeiliSearch indexing for journals

## Tasks

### ITER4.5-001: Routes Domain ✅ COMPLETE
**Description:** Create routes table for reusable route/track names
**Strategy:** Single task for routes infrastructure
**Specification Reference:** Multiple activity types reference routes table

**PR Size:** ~10 files (domain, repository, service, API, tests)

**Acceptance Criteria:**
- [x] Create `routes` table in database:
  - `id` (UUID), `user_id` (FK to users)
  - `name` (string, required)
  - `description` (text, nullable)
  - `created_at`, `updated_at`
  - `gpx_data` (text, nullable, GPX XML format)
  - Indexes on: `user_id`, `name`, `created_at`
  - Migration: `0016_create_routes_table.py`
- [x] Create `Route` entity in `core_shared/models/`:
  - Dataclass with validation in `__post_init__`
  - GPX data validated as XML with `<gpx>` root element
  - Field length validation (user_id max 50, name max 200)
- [x] Create `RouteRepository` interface and `SqlRouteRepository` implementation:
  - Interface: `RouteRepository` ABC in `backend/app/core/journal/models/repositories.py`
  - Implementation: `SqlRouteRepository` in `backend/app/core/journal/adapters/sql/route_repository.py`
  - Methods: `find_by_id`, `save`, `delete`, `get_all`, `get_count`, `check_usage_in_journals`
  - Uses SQLAlchemy Core with `text()` for raw SQL
  - 12 integration tests passing ✅
- [x] Create `RouteService` with Dishka DI:
  - Service: `RouteService` in `backend/app/core/journal/services/route_service.py`
  - Domain events: `RouteCreated`, `RouteUpdated`, `RouteDeleted`
  - Domain exceptions: `RouteNotFoundError`, `RouteInUseError`, `RouteValidationError`
  - Methods: `create_route`, `update_route`, `delete_route`, `get_route`, `get_routes_for_user`, `get_route_count`
  - Registered in `JournalProvider` with REQUEST scope
  - 11 unit tests passing ✅
- [x] Implement routes API endpoints:
  - `GET /api/routes` - List routes with pagination and filtering
  - `POST /api/routes` - Create route
  - `GET /api/routes/{id}` - Get route
  - `PUT /api/routes/{id}` - Update route
  - `DELETE /api/routes/{id}` - Delete route (check for usage in journals)
  - All endpoints require authentication
  - User ownership verification for all operations
  - Proper error handling with domain exceptions
- [x] Add database migration with proper indexes:
  - Migration `0016_create_routes_table.py` applied successfully
  - Indexes on `user_id`, `name`, `created_at`
- [x] Write unit tests for route service:
  - 11 unit tests in `backend/tests/unit/routes/test_route_service.py`
  - All tests passing ✅
- [x] Write integration tests for route repository:
  - 12 integration tests in `backend/tests/integration/routes/test_route_repository_integration.py`
  - All tests passing ✅
- [x] Write integration tests for route API:
  - 23 integration tests in `backend/tests/integration/api/test_route_endpoints.py`
  - Tests cover CRUD operations, pagination, error handling, authentication
  - All tests passing ✅
- [x] Document routes domain in code comments:
  - Comprehensive docstrings in all route-related files

**Implementation Details:**
- **Database Migration:** `backend/app/migrations/versions/0016_create_routes_table.py` (revision 0016, revises 0015)
- **Domain Entity:** `core_shared/core_shared/models/route.py` with validation
- **Repository Interface:** `backend/app/core/journal/models/repositories.py` (lines 813-900)
- **Repository Implementation:** `backend/app/core/journal/adapters/sql/route_repository.py` (SQLAlchemy Core)
- **Service Layer:** `backend/app/core/journal/services/route_service.py` with event publishing
- **Domain Events:** `backend/app/core/journal/models/events.py` (RouteCreated, RouteUpdated, RouteDeleted)
- **Domain Exceptions:** `backend/app/core/journal/models/exceptions.py` (RouteNotFoundError, RouteInUseError, RouteValidationError)
- **Dependency Injection:** Registered in `backend/app/infrastructure/di/journal.py` (JournalProvider)
- **API Layer:**
  - **Schemas:** `backend/app/api/routes/schemas.py` (Pydantic models for JSON API)
  - **Converters:** `backend/app/api/routes/converters.py` (Domain ↔ API transformations with error handling)
  - **Controllers:** `backend/app/api/routes/controllers.py` (FastAPI endpoints with authentication)
  - **Error Handlers:** Updated `backend/app/api/error_handlers.py` to include route exceptions
- **Unit Tests:** `backend/tests/unit/routes/test_route_service.py` (11 tests, all passing ✅)
- **Integration Tests:**
  - Repository: `backend/tests/integration/routes/test_route_repository_integration.py` (12 tests, all passing ✅)
  - API: `backend/tests/integration/api/test_route_endpoints.py` (23 tests, all passing ✅)

**Progress:** 100% complete ✅
- ✅ Database migration
- ✅ Domain entity with validation
- ✅ Repository interface and SQL implementation
- ✅ Service layer with business logic and event publishing
- ✅ Dependency injection setup
- ✅ API endpoints (5 endpoints: list, get, create, update, delete)
- ✅ Unit tests (11/11 passing)
- ✅ Integration tests for repository (12/12 passing)
- ✅ Integration tests for API (23/23 passing)
- ✅ All quality gates passing (ruff, mypy, pytest)

**Note:** Routes are referenced by BUSHWALKING, CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, and JOGGING types.

### ITER4.5-002: Fitness Base Type ✅ COMPLETE
**Description:** Implement FITNESS base type with GPX tracks and Strava preparation
**Strategy:** Single task for fitness foundation
**Specification Reference:** [Fitness Data](../journal-system-specification.md#fitness-data-fitness-type)

**PR Size:** ~10 files (domain, repository, migration, type system, DI, tests)

**Acceptance Criteria:**
- [x] Create `journal_fitness_data` table:
  - `journal_id` (PK, FK to journals)
  - `heart_rate_avg` (integer bpm, nullable)
  - `heart_rate_max` (integer bpm, nullable)
  - `distance` (integer meters, nullable)
  - `elevation_gain` (integer meters, nullable)
  - `elevation_loss` (integer meters, nullable)
  - `duration` (integer seconds, nullable)
  - `calories` (integer, nullable)
  - `gpx_track_data` (text, nullable, GPX XML format)
  - `strava_activity_id` (string, nullable, external reference)
  - `created_at`, `updated_at`
  - Check constraints for non-negative values (>= 0) on all numeric fields
  - Migration: `0017_create_fitness_data_table.py`
- [x] Implement FITNESS type in type system (no dependencies)
- [x] Add GPX validation (XML format with `<gpx>` root element check)
- [x] Implement GPX storage and retrieval
- [x] Add Strava preparation (`strava_activity_id` field for Iteration 5)
- [x] Add database migration with proper constraints
- [x] Write unit tests for FITNESS type validation (19 tests passing ✅)
- [x] Write integration tests for FITNESS data persistence (9 tests passing ✅)
- [x] Document GPX storage format and Strava preparation in code comments

**Implementation Details:**
- **Database Migration:** `backend/app/migrations/versions/0017_create_fitness_data_table.py` (revision 0017, revises 0016)
- **Domain Entity:** `backend/app/core/journal/models/fitness_data.py` with validation
  - FitnessData dataclass with all fields
  - Complete validation in `__post_init__` method
  - GPX XML validation using `xml.etree.ElementTree`
  - Exception chaining for proper error context
- **Repository Interface:** `backend/app/core/journal/models/repositories.py` (FitnessDataRepository, lines 395-441)
- **Repository Implementation:** `backend/app/core/journal/adapters/sql/fitness_data_repository.py` (SQLAlchemy Core)
  - Methods: `find_by_journal_id`, `save` (insert/update), `delete`
  - 9 integration tests passing ✅
- **Type System Integration:**
  - Uncommented `FITNESS = "fitness"` in `JournalType` enum
  - Added FITNESS to dependencies mapping (no dependencies - base type)
  - Updated `_JOURNAL_TYPE_TABLE_MAP` in `journal_repository.py`
  - Added FITNESS JOIN clauses in query methods
- **Dependency Injection:** Registered in `backend/app/infrastructure/di/journal.py` (JournalProvider)
  - `SqlFitnessDataRepository` registered with REQUEST scope
- **Unit Tests:** `backend/tests/unit/journal/test_fitness_data_entity.py` (19 tests, all passing ✅)
  - Tests for minimal creation, all fields, and validation errors
- **Integration Tests:** `backend/tests/integration/journal/test_fitness_data_repository_integration.py` (9 tests, all passing ✅)
  - Tests for save (insert/update), find, delete, GPX data, and Strava activity ID

**Progress:** 100% complete ✅
- ✅ Database migration with check constraints
- ✅ Domain entity with full validation
- ✅ Repository interface and SQL implementation
- ✅ Type system integration (enum, dependencies, table mapping)
- ✅ Dependency injection setup
- ✅ Unit tests (19/19 passing)
- ✅ Integration tests (9/9 passing)
- ✅ All quality gates passing (ruff, mypy, pytest)
- ✅ Updated journal type count test for FITNESS

**GPX Storage:**
- Stored as TEXT column in `journal_fitness_data` table
- Validated as XML with `<gpx>` root element requirement
- Ready for future enhancement: extract metrics, compression, download endpoint

### ITER4.5-003: Outdoor Activity Types - Part 1 (OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING) ✅ COMPLETE
**Description:** Implement outdoor activity base type and first specialized types
**Strategy:** Single task for three related types
**Specification Reference:** [Outdoor Activity Data](../journal-system-specification.md#outdoor-activity-data-outdoor_activity-type), [Bushwalking Data](../journal-system-specification.md#bushwalking-data-bushwalking-type), [Jogging Data](../journal-system-specification.md#jogging-data-jogging-type)

**PR Size:** ~12 files (3 type tables, dependency logic, API schemas/converters/controllers, tests, migrations)

**Acceptance Criteria:**
- [x] Create `journal_outdoor_activity_data` table:
  - `journal_id` (PK, FK to journals)
  - `activity_type` (string, e.g., "hiking", "climbing", "kayaking")
  - `weather_conditions` (text, nullable)
  - `role` (string, nullable, e.g., "leader", "participant", "spectator")
  - `in_leadership_role` (boolean, nullable)
  - `participant_notes` (text, nullable)
  - `created_at`, `updated_at`
  - Migration: `0018_create_outdoor_activity_data_table.py`
- [x] Implement OUTDOOR_ACTIVITY type (requires FITNESS, automatically added)
- [x] Create `journal_bushwalking_data` table:
  - `journal_id` (PK, FK to journals)
  - `route_id` (FK to routes, nullable)
  - `track_grading` (string, nullable, Australian Track Grading System: Grade 1-5)
  - `created_at`, `updated_at`
  - Migration: `0019_create_bushwalking_data_table.py`
- [x] Implement BUSHWALKING type (requires OUTDOOR_ACTIVITY, FITNESS)
- [x] Create `journal_jogging_data` table:
  - `journal_id` (PK, FK to journals)
  - `route_id` (FK to routes, nullable)
  - `pace` (integer seconds per km, nullable)
  - `created_at`, `updated_at`
  - Migration: `0020_create_jogging_data_table.py`
- [x] Implement JOGGING type (requires FITNESS, not OUTDOOR_ACTIVITY)
- [x] Update type dependency resolution to handle these types
- [x] Add database migrations with proper foreign key constraints
- [x] **Add API schemas, converters, and controller integration:**
  - [x] Add `OutdoorActivityDataSchema`, `BushwalkingDataSchema`, `JoggingDataSchema` to `backend/app/api/journals/schemas.py`
  - [x] Add converter functions in `backend/app/api/journals/converters.py`
  - [x] Update `_enrich_journal_data()` and `_create_type_specific_data()` in `backend/app/api/journals/controllers.py`
  - [x] Add repository parameters to all journal endpoints
  - [x] Update `backend/app/api/contacts/controllers.py` (`get_contact_journals` endpoint)
- [x] Write unit tests for type-specific validation and dependencies
  - `backend/tests/unit/journal/test_outdoor_activity_data_entity.py` (entity validation)
  - `backend/tests/unit/journal/test_bushwalking_data_entity.py` (entity validation)
  - `backend/tests/unit/journal/test_jogging_data_entity.py` (entity validation)
  - `backend/tests/unit/journal/test_journal_types.py` (updated for new types and dependencies)
  - 789 unit tests total passing ✅
- [x] Write integration tests for type data persistence
  - 7 tests in `backend/tests/integration/journal/test_outdoor_activity_data_repository_integration.py` ✅
  - 9 tests in `backend/tests/integration/journal/test_bushwalking_data_repository_integration.py` ✅
  - 9 tests in `backend/tests/integration/journal/test_jogging_data_repository_integration.py` ✅
- [x] **Write API integration tests for type creation and updates**
  - `test_update_outdoor_activity_type_data`, `test_update_bushwalking_type_data`, `test_update_jogging_type_data` in `backend/tests/integration/api/test_journal_endpoints.py` ✅
- [x] Document Australian Track Grading System in code comments

**Implementation Details:**
- **Database Migrations:**
  - `backend/app/migrations/versions/0018_create_outdoor_activity_data_table.py`
  - `backend/app/migrations/versions/0019_create_bushwalking_data_table.py`
  - `backend/app/migrations/versions/0020_create_jogging_data_table.py`
- **Domain Constants:** `backend/app/core/journal/models/constants.py` — added `MAX_ACTIVITY_TYPE_LENGTH`, `MAX_WEATHER_CONDITIONS_LENGTH`, `MAX_ROLE_LENGTH`, `MAX_PARTICIPANT_NOTES_LENGTH`, `VALID_TRACK_GRADES`
- **Domain Exceptions:** `backend/app/core/journal/models/exceptions.py` — added `OutdoorActivityDataValidationError`, `BushwalkingDataValidationError`, `JoggingDataValidationError`
- **Domain Entities:**
  - `backend/app/core/journal/models/outdoor_activity_data.py` — `OutdoorActivityData` dataclass
  - `backend/app/core/journal/models/bushwalking_data.py` — `BushwalkingData` dataclass
  - `backend/app/core/journal/models/jogging_data.py` — `JoggingData` dataclass
- **Repository Interfaces:** `backend/app/core/journal/models/repositories.py` — added `OutdoorActivityDataRepository`, `BushwalkingDataRepository`, `JoggingDataRepository`
- **SQL Repositories:**
  - `backend/app/core/journal/adapters/sql/outdoor_activity_data_repository.py`
  - `backend/app/core/journal/adapters/sql/bushwalking_data_repository.py`
  - `backend/app/core/journal/adapters/sql/jogging_data_repository.py`
- **Type System:** `backend/app/core/journal/models/journal_types.py` — uncommented OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING; updated dependency map
- **Journal Repository:** `backend/app/core/journal/adapters/sql/journal_repository.py` — updated `_JOURNAL_TYPE_TABLE_MAP`, NOTE detection JOINs, and `_get_type_table_join`
- **API Schemas:** `backend/app/api/journals/schemas.py` — added `OutdoorActivityDataSchema`, `BushwalkingDataSchema`, `JoggingDataSchema`
- **API Converters:** `backend/app/api/journals/converters.py` — added three converter methods
- **API Controllers:** `backend/app/api/journals/controllers.py` — updated `_enrich_journal_data` (type narrowing assert + `journal_id` local var), `_create_type_specific_data`, `_process_journal_types`, `list_journals`, all CRUD endpoints, and three new `update_*_data` functions
- **Contacts Controller:** `backend/app/api/contacts/controllers.py` — added three new repo imports and params to `get_contact_journals`
- **Dependency Injection:** `backend/app/infrastructure/di/journal.py` — added providers for all three new repositories
- **Frontend:**
  - `frontend/src/types/journals.ts` — added FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING to `JournalType` enum
  - `frontend/src/types/__tests__/journals.test.ts` — updated expectations for new types
  - `frontend/src/components/journals/JournalTypeSection.tsx` — added labels for new types
  - `frontend/src/components/journals/JournalFilters.tsx` — added labels for new types
  - `frontend/src/components/journals/JournalCreateForm.tsx` — added new types to `typeOptions`
  - `frontend/src/components/journals/JournalListItem.tsx` — added icons for new types

**Progress:** 100% complete ✅
- ✅ Database migrations (0018, 0019, 0020)
- ✅ Domain entities with validation
- ✅ Repository interfaces and SQL implementations
- ✅ Type system integration (enum, dependencies, table mapping, NOTE detection)
- ✅ Dependency injection setup
- ✅ API layer (schemas, converters, controllers — all endpoints updated)
- ✅ Unit tests (789 total passing, includes new entity and type dependency tests)
- ✅ Frontend type enum and most component updates
- ✅ Integration tests for repositories (25/25 passing)
- ✅ API integration tests for type creation and updates (3/3 passing)
- ✅ All quality gates passing (ruff check, ruff format, mypy, pytest)

**Australian Track Grading System:**
- Grade 1: Well-formed track, suitable for wheelchairs
- Grade 2: Well-formed track, suitable for most ages and fitness
- Grade 3: Formed track, some steep sections
- Grade 4: Rough track, very steep sections
- Grade 5: Route only, very rough, very steep

### ITER4.5-004: Outdoor Activity Types - Part 2 (ABSEILING_TRIP, CANYONING, CLIMBING) ✅ COMPLETE
**Description:** Implement abseiling, canyoning, and climbing types
**Strategy:** Single task for three complex types
**Specification Reference:** [Abseiling Data](../journal-system-specification.md#abseiling-data-abseiling_trip-type), [Canyoning Data](../journal-system-specification.md#canyoning-data-canyoning-type), [Climbing Data](../journal-system-specification.md#climbing-data-climbing-type)

**PR Size:** ~12 files (3 type tables, dependency logic, API schemas/converters/controllers, tests, migrations)

**Acceptance Criteria:**
- [x] Create `journal_abseiling_data` table:
  - `journal_id` (PK, FK to journals)
  - `number_of_abseils` (integer, nullable)
  - `total_length` (integer meters, nullable)
  - `created_at`, `updated_at`
  - **Note:** Individual abseils are child journals with their own abseiling data
- [x] Implement ABSEILING_TRIP type (requires OUTDOOR_ACTIVITY, FITNESS)
- [x] Create `journal_canyoning_data` table:
  - `journal_id` (PK, FK to journals)
  - `route_id` (FK to routes, nullable)
  - `french_grade` (string, nullable, e.g., "v3a2IV**")
  - `water_guage_name` (string, nullable)
  - `water_guage_level` (integer, nullable)
  - `is_vertical` (boolean, nullable)
  - `is_night_canyon` (boolean, nullable)
  - `is_white_water` (boolean, nullable)
  - `created_at`, `updated_at`
- [x] Implement CANYONING type (requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS)
- [x] Create `journal_climbing_data` table:
  - `journal_id` (PK, FK to journals)
  - `route_id` (FK to routes, nullable)
  - `climbing_type` (enum: "sport", "trad", "bouldering", nullable)
  - `grade` (integer, nullable)
  - `length` (integer meters, nullable)
  - `created_at`, `updated_at`
- [x] Implement CLIMBING type (requires OUTDOOR_ACTIVITY, FITNESS)
- [x] Update type dependency resolution for complex dependencies (CANYONING)
- [x] Add database migrations with proper constraints
- [x] **Add API schemas, converters, and controller integration:**
  - [x] Add `AbseilingDataSchema`, `CanyoningDataSchema`, `ClimbingDataSchema` to `backend/app/api/journals/schemas.py`
  - [x] Add converter functions in `backend/app/api/journals/converters.py`
  - [x] Update `_enrich_journal_data()` and `_create_type_specific_data()` in `backend/app/api/journals/controllers.py`
  - [x] Add repository parameters to all journal endpoints
  - [x] Update `backend/app/api/contacts/controllers.py` if it uses `_enrich_journal_data()`
- [x] Write unit tests for type-specific validation and complex dependencies
- [x] Write integration tests for type data persistence (26/26 passing)
- [x] **Write API integration tests for type creation and updates**
  - 3 tests in `TestJournalTypeManagement` (update data for each new type) ✅
  - 3 tests in `TestJournalTypeDependencyDataCreation` (dependency auto-creation) ✅
  - 6 tests in `TestJournalTypeDataValidation` (validation errors return 400) ✅
- [x] Document French grading system for canyoning in code comments
- [x] **Write MCP scheme updates and integration tests for new types**

**French Canyoning Grading System:**
- Format: v[vertical]a[aquatic][engagement][duration][stars]
- Example: v3a2IV** = vertical grade 3, aquatic grade 2, engagement IV, 2 stars
- Vertical: 1-7 (difficulty of abseils)
- Aquatic: 1-7 (difficulty of water sections)
- Engagement: I-VI (commitment level)
- Stars: * to *** (quality/beauty)

### ITER4.5-005: Outdoor Activity Types - Part 3 (KAYAKING, CROSS_COUNTRY_SKIING) ✅ COMPLETED
**Description:** Implement remaining outdoor activity types
**Strategy:** Single task for two types
**Specification Reference:** [Kayaking Data](../journal-system-specification.md#kayaking-data-kayaking-type), [Cross-Country Skiing Data](../journal-system-specification.md#cross-country-skiing-data-cross_country_skiing-type)
**Completed:** 2026-02-24

**PR Size:** ~10 files (2 type tables, dependency logic, API schemas/converters/controllers, mcp tool and schema updates, tests, migrations)

**Acceptance Criteria:**
- [x] Create `journal_kayaking_data` table:
  - `journal_id` (PK, FK to journals)
  - `route_id` (FK to routes, nullable)
  - `water_type` (string, nullable, e.g., "river", "sea", "lake")
  - `created_at`, `updated_at`
- [x] Implement KAYAKING type (requires OUTDOOR_ACTIVITY, FITNESS)
- [x] Create `journal_skiing_data` table:
  - `journal_id` (PK, FK to journals)
  - `route_id` (FK to routes, nullable)
  - `snow_conditions` (text, nullable)
  - `created_at`, `updated_at`
- [x] Implement CROSS_COUNTRY_SKIING type (requires BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS)
- [x] Update type dependency resolution for these types
- [x] Add database migrations with proper constraints (migration 0024)
- [x] **Add API schemas, converters, and controller integration:**
  - [x] Add `KayakingDataSchema`, `CrossCountrySkiingDataSchema` to `backend/app/api/journals/schemas.py`
  - [x] Add converter functions in `backend/app/api/journals/converters.py`
  - [x] Update `_enrich_journal_data()` and `_create_type_specific_data()` in `backend/app/api/journals/controllers.py`
  - [x] Add repository parameters to all journal endpoints
  - [x] Update `backend/app/api/contacts/controllers.py` with new repos in `_enrich_journal_data()` call
- [x] Write unit tests for type-specific validation and dependencies
- [x] Write integration tests for type data persistence
- [x] **Write API integration tests for type creation, updates, removal and validation**
- [x] Update frontend TypeScript types (`frontend/src/types/journals.ts`)
- [x] **Write MCP schema updates and integration tests for new types** (completed in ITER4.5-007)

**Implementation Notes:**
- KAYAKING: `journal_kayaking_data` table with `route_id` (UUID FK) and `water_type` (string)
- CROSS_COUNTRY_SKIING: `journal_skiing_data` table with `route_id` (UUID FK) and `snow_conditions` (text)
- Both types validated via `__post_init__` with `KayakingDataValidationError` / `CrossCountrySkiingDataValidationError`
- All quality gates passed: ruff, mypy, 1402 backend tests, 842 frontend tests

### ITER4.5-006: Activity UI Components ✅ COMPLETED
**Description:** Build UI components for activity display and GPX visualization
**Strategy:** Single task for activity-specific UI
**Specification Reference:** [Frontend Components](../journal-system-specification.md#frontend-components)

**Progress:** PRs 1-5 delivered the route selector, GPX map display, activity statistics, all planned type editors, the final visual polish pass for the complex activity UI, and Playwright E2E coverage for the remaining complex activity flows. The E2E pass also uncovered and fixed a backend create-time type_data persistence gap for the newer complex activity types.

**PR Size:** ~7 files (GPX component, stats component, forms, tests, e2e tests)

**Acceptance Criteria:**
- [x] Create `GPXTrackDisplay` component using `react-leaflet`/`shadcn-map`:
  - Display GPX track on map
  - Display track statistics (distance, elevation gain/loss)
  - Interactive map with zoom and pan
  - Marker for start/end points
- [x] Create `ActivityStats` component:
  - Display fitness metrics (heart rate, distance, elevation, duration, calories)
  - Show activity-specific data (grading, weather, role, etc.)
  - Format metrics appropriately (pace, duration, etc.)
  - Responsive design for mobile
- [x] Create type-specific editor components:
  - `FitnessTypeEditor` (heart rate, distance, elevation, duration, calories, GPX upload)
  - `OutdoorActivityTypeEditor` (activity type, weather, role, leadership, participant notes)
  - `BushwalkingTypeEditor` (route selector, track grading dropdown)
  - `AbseilingTripTypeEditor` (number of abseils, total length)
  - `CanyoningTypeEditor` (route, French grade, water gauge, flags)
  - `ClimbingTypeEditor` (route, climbing type, grade, length)
  - `KayakingTypeEditor` (route, water type)
  - `CrossCountrySkiingTypeEditor` (route, snow conditions)
  - `JoggingTypeEditor` (route, pace)
- [x] Integrate interactive map rendering and GPX file upload/validation in the journal UI
- [x] Write Jest unit tests for components
- [x] Write React Testing Library tests for user interactions
- [x] Playwright E2E coverage for the remaining complex activity flows

**Map Integration:**
- Use `react-leaflet` via `shadcn-map`
- Display GPX track as polyline
- Add markers for start/end points
- Support zoom and pan interactions

### ITER4.5-007: Activity MCP Tools & Analytics ✅ COMPLETED
**Description:** Add activity-specific MCP tools and analytics
**Strategy:** Single task for MCP and analytics
**Specification Reference:** [MCP Tools](../journal-system-specification.md#mcp-tools)
**Completed:** 2026-03-11

**PR Size:** ~5 files (MCP tools, analytics, tests)

**Acceptance Criteria:**
- [x] Create activity-specific MCP tools in `backend/app/mcp/domains/journals/`:
  - `get_activity_stats()` - Statistics for fitness activities (total distance, elevation, duration by type)
  - `search_activities()` - Search activities with type filtering
  - `analyze_activity_trends()` - Activity pattern analysis
  - `get_route_history()` - History of activities on specific route
- [x] Implement activity analytics:
  - Total distance, elevation, duration by activity type
  - Activity frequency over time
  - Personal records (longest distance, highest elevation, etc.)
  - Route usage statistics
- [x] Add activity filtering to existing search tools
- [x] Write MCP integration tests
- [x] Document activity MCP tools in `docs/mcp-tools.md`

**Implementation Details:**
- Added MCP response schemas for activity totals, per-type stats, personal records, trend buckets, and route history in `backend/app/mcp/domains/journals/schemas.py`
- Extended journal MCP tool repository wiring to include kayaking, cross-country skiing, and route repositories in `backend/app/mcp/domains/journals/tools.py`
- Implemented `search_journals()` query + type filtering so combined text/type searches work for activity journals and general journals
- Added `search_activities()`, `get_activity_stats()`, `analyze_activity_trends()`, and `get_route_history()` to the journal MCP domain and registered them with the MCP server
- Added mounted MCP integration coverage for journal/activity filtering, aggregated stats, monthly trend bucketing, and route history usage
- Updated MCP response serialization to emit JSON-safe values for datetime fields

**Quality Gates:**
- ✅ Targeted MCP test slice passing: `uv run pytest tests/unit/mcp/domains/journals/test_tools.py tests/integration/mcp/test_journal_tools_integration.py`
- ✅ Backend lint and type checks passing for touched files

**Known Limitations / Deferred Follow-up:**
- Period-over-period comparison analytics are still future work; the current MCP analytics expose bucketed trend data but do not yet calculate delta comparisons versus previous periods
- Multi-type journal search currently reuses repository filtering for single-type queries and performs type-aware refinement in MCP for comma-separated multi-type queries; if search volume grows, move that refinement into repository SQL
- Route usage analytics currently query route-aware activity tables directly because `SqlRouteRepository.check_usage_in_journals()` remains a stub; consider consolidating route usage detection in the route repository during a future iteration

**Follow-up Work for Future Iterations:**
- Add period-over-period delta summaries and rolling averages to activity analytics
- Add repository-level support for multi-type journal filtering so MCP search scales without post-query refinement
- Reuse route history aggregation in the routes domain/service layer so route analytics and route deletion checks share the same source of truth

**Analytics Features:**
- Activity type breakdown (pie chart data)
- Timeline chart data (activities over time)
- Personal records tracking
- Route popularity statistics
- Comparison to previous periods

## Architecture Notes

**Type Dependency System:**
- FITNESS: No dependencies (base type for all fitness activities)
- OUTDOOR_ACTIVITY: Requires FITNESS (automatically added)
- BUSHWALKING: Requires OUTDOOR_ACTIVITY, FITNESS
- ABSEILING_TRIP: Requires OUTDOOR_ACTIVITY, FITNESS
- CANYONING: Requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS (most complex)
- CLIMBING: Requires OUTDOOR_ACTIVITY, FITNESS
- KAYAKING: Requires OUTDOOR_ACTIVITY, FITNESS
- CROSS_COUNTRY_SKIING: Requires BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS
- JOGGING: Requires FITNESS only (not OUTDOOR_ACTIVITY)

**Routes Domain:**
- Shared across multiple activity types
- User-specific (each user has their own routes)
- Reusable for tracking favorite routes
- Optional (activities can exist without route reference)

**GPX Storage:**
- Store as TEXT in PostgreSQL (XML format)
- Validate XML structure on import
- Extract metrics for indexing (distance, elevation)
- Consider compression for large files
- Provide download endpoint for export

**Strava Preparation:**
- `strava_activity_id` field in FITNESS type
- Ready for automatic journal creation (Iteration 5)
- Merge logic foundation for duplicate detection

## Testing Strategy

**Unit Tests:**
- Type dependency resolution (especially CANYONING)
- GPX validation and parsing
- Activity-specific validation rules
- Grading system validation (Australian, French)

**Integration Tests:**
- Type data persistence with dependencies
- Routes CRUD operations
- GPX storage and retrieval
- Activity analytics queries

**E2E Tests (Playwright):**
- Create activity journal with GPX upload
- View GPX track on map
- Add activity with route selection
- Type dependency visualization in form
- Activity statistics display

## Success Criteria

- ✅ Routes domain implemented and tested
- ✅ FITNESS base type with GPX support
- ✅ All 8 specialized activity types implemented
- ✅ Type dependency resolution working for complex types (CANYONING)
- ✅ GPX track display with interactive map rendering
- ✅ Activity-specific UI forms/editors for all types
- ✅ Activity statistics UI complete and backed by MCP analytics
- ✅ MCP tools for activity management and analytics implemented
- ✅ All implemented tests passing (unit, integration, frontend)
- ✅ System in working state after each PR
- ✅ Ready for Strava integration (Iteration 5)

## Next Steps

**Immediate:** Start Iteration 5 (Strava Integration)
- Strava OAuth and API client
- Activity data synchronization
- Automatic FITNESS journal creation from Strava
- GPX track import from Strava
- Merge logic for duplicate detection

**Follow-up backlog from Iteration 4.5:**
- Period-over-period analytics deltas for MCP activity summaries
- Repository-level multi-type journal filtering for MCP search performance
- Shared route usage aggregation between route repository and MCP analytics

**Then:** Iteration 6 (Immich Integration)
- Photo display in activity journals
- Album linking to outdoor activities

**Then:** Iteration 7 (Google Calendar Integration)
- Calendar sync for planned activities
- Event-based activity scheduling

