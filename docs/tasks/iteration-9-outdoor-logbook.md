# Iteration 9: Outdoor Logbook

**Status:** 🟡 IN PROGRESS
**Dependencies:** Iteration 7 (complete — journal hierarchy, calendar sync, merge, MCP parity), Iteration 4.5 (complete — fitness and activity types foundation)
**Goal:** Expand the outdoor activity journal system into a comprehensive outdoor logbook with structured abseil pitches, activity templates, new activity and supporting types, gear maintenance tracking, and PDF logbook export.

## Overview

This iteration delivers the approved [Outdoor Logbook Product Specification](../product-specifications/outdoor-logbook-product-specification.md) in incremental, shippable slices. Each task delivers end-to-end functionality across backend, frontend, and MCP before the next task begins.

The work builds on the existing outdoor activity type hierarchy established in [Iteration 4.5](./iteration-4.5-fitness-activity-types.md) and the journal hierarchy, merge, and MCP patterns established in [Iteration 7](./iteration-7-calendar-integration.md).

**Key changes from the current system:**

- The free-text `activity_type` field on OUTDOOR_ACTIVITY is removed — subtypes now fully define the activity
- Abseil pitches become a structured inline data model, replacing the never-implemented child journal approach
- Reusable activity templates (canyon, cave, climb) pre-populate pitch data
- Five new outdoor activity types: CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING
- Three new supporting types: OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE
- Gear items as a supporting entity (future SnipeIT sync compatible)
- PDF logbook export with yearly summaries and participant index

## Reference Documents

- **[Outdoor Logbook Product Specification](../product-specifications/outdoor-logbook-product-specification.md)** — approved product behaviour for this iteration
- **[Journal System Specification](../journal-system-specification.md)** — journal domain model, type system, and data models
- **[Journals Product Specification](../product-specifications/journals-product-specification.md)** — broader journal product direction (hierarchy, merge, MCP parity)
- **[Iteration 4.5: Fitness & Activity Types](./iteration-4.5-fitness-activity-types.md)** — foundation this iteration extends
- **[Domain Architecture](../architecture/domain-architecture.md)** — domain patterns and service layer conventions
- **[API Design](../architecture/api-design.md)** — REST and MCP API patterns
- **[Frontend Design](../architecture/frontend-design.md)** — Next.js, shadcn/ui, and form guidelines
- **[Database Design](../architecture/database-design.md)** — schema and migration conventions
- **[Testing Strategy](../architecture/testing-strategy.md)** — test-first workflow and coverage requirements

## Delivery Rules

These rules apply to every task:

1. **Tests first:** write failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks pass.
3. **Reviewable PRs:** keep each PR to roughly ≤ 10 files where practical; split further if needed.
4. **MCP parity:** if a capability is meaningful in the UI, expose the same capability through MCP in the same task. New types use the existing generic `create_journal_entry` / `update_journal_entry` MCP pattern — no per-type tools.
5. **Full vertical slice:** each task delivers backend (domain, repository, migration, API), frontend (types, editor, display), and MCP integration together.
6. **Every task is shippable:** no task may rely on a later task to restore broken behaviour.

## Sequencing Strategy

The sequence reflects both product priority and technical dependency:

1. **Foundation first:** abseil pitches and templates are the most architecturally significant changes and are required by modified types (CLIMBING) and new types (CAVING).
2. **Modified types before new types:** CLIMBING and KAYAKING changes build on the pitch foundation and are simpler to validate against existing data.
3. **New outdoor types together:** CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING follow the established type pattern and can be delivered as a batch.
4. **Supporting types next:** OUTDOOR_TRAINING, OUTDOOR_PLANNING, and GEAR_MAINTENANCE are functionally independent from the outdoor activity types but share the activity subtype enum.
5. **PDF export last:** the export aggregates data from all types and needs them to exist first.

## Dependency and Parallelisation Notes

- **Task 1** must land before **Tasks 2, 3, and 4** (pitch model and templates are prerequisites).
- **Task 2** can begin immediately after **Task 1** (modifies existing types using new pitch infrastructure).
- **Task 3** depends on **Task 1** (CAVING needs pitches and templates) but is otherwise independent.
- **Task 4** depends on **Task 3** completing the activity subtype enum (OUTDOOR_TRAINING and OUTDOOR_PLANNING reference the full list of subtypes).
- **Task 5** depends on **Tasks 3 and 4** (exports data from all types).
- **Tasks 2 and 3** can run in parallel after **Task 1** if capacity allows.

---

## Task Breakdown

### ITER9-001: Abseil Pitch Data Model, Activity Templates, and activity_type Removal
**Objective:** Establish the structural foundation that all subsequent tasks depend on: structured abseil pitches, the template entity, and removal of the redundant `activity_type` field.
**Strategy:** Split into 7 phases. Pitches land first (domain → API → UI), then templates follow the same pattern. The `activity_type` removal is small enough to bundle with the first pitch phase.

**Specification Reference:**
- [Remove activity_type from OUTDOOR_ACTIVITY](../product-specifications/outdoor-logbook-product-specification.md#remove-activity_type-from-outdoor_activity)
- [Abseil Pitch Data Model](../product-specifications/outdoor-logbook-product-specification.md#abseil-pitch-data-model)
- [Activity Templates](../product-specifications/outdoor-logbook-product-specification.md#activity-templates)

**Acceptance Criteria (task-level):**
- [ ] `activity_type` column removed from `journal_outdoor_activity_data` without data loss
- [ ] Abseil pitches can be created, edited, and deleted as part of abseiling data
- [ ] Pitch totals auto-calculate from pitches when pitches exist, with manual override
- [ ] Activity templates can be created, searched, listed, updated, and deleted
- [ ] Selecting a template pre-populates editable pitches on the journal
- [ ] All capabilities available through REST API and MCP
- [ ] Unit, integration, and e2e test coverage

#### Phase 1: Remove activity_type and Abseil Pitch Domain Model
**PR Size:** ~5–7 files

Remove the `activity_type` column and establish the abseil pitch domain layer without API or UI changes.

**Acceptance Criteria:**
- [x] Migration drops `activity_type` from `journal_outdoor_activity_data`
- [x] `OutdoorActivityData` entity and API schema no longer reference `activity_type`
- [x] Frontend `OutdoorActivityTypeEditor` no longer renders the activity type field
- [x] Migration creates `abseil_pitches` table (journal_id FK, pitch_number, height, anchor_location, anchor_type, did_rescue, did_setup, timestamps)
- [x] Migration adds `number_of_setups` and `number_of_rescues` to `journal_abseiling_data`
- [x] `AbseilPitch` domain entity with validation (pitch_number required and positive, anchor_location/anchor_type constrained to valid values)
- [x] `AbseilingData` entity updated with new aggregate fields
- [x] `AbseilPitchRepository` interface and `SqlAbseilPitchRepository` implementation (save, find_by_journal_id, delete_by_journal_id)

**Required Test Coverage:**
- **Unit:** ✅ AbseilPitch entity validation (valid/invalid anchor types, location values, pitch_number constraints). AbseilingData entity with new fields. 1326 tests passing.
- **Integration:** ✅ AbseilPitchRepository CRUD with real database. OutdoorActivityData without activity_type. 791 integration tests passing.

#### Phase 2: Abseil Pitch API and Auto-Calculation Logic
**PR Size:** ~5–7 files

Expose pitches through the REST API as nested data within abseiling responses, and implement auto-calculation.

**Acceptance Criteria:**
- [x] `AbseilPitchSchema` added to API schemas (nested within `AbseilingDataSchema`)
- [x] Pitch CRUD handled as part of journal abseiling data create/update endpoints
- [x] Auto-calculation: when pitches present, `number_of_abseils` defaults to pitch count, `total_length` to sum of heights, `number_of_setups` / `number_of_rescues` to filtered counts
- [x] Manual override: user-provided totals take precedence over auto-calculated values
- [x] MCP `create_journal_entry` / `update_journal_entry` handles pitch data within abseiling type data
- [x] API converters handle pitch domain ↔ schema translation

**Required Test Coverage:**
- **Unit:** ✅ auto-calculation logic for all four aggregate fields, manual override precedence.
- **Integration:** ✅ API tests for creating/updating abseiling journals with and without pitches, verifying calculated totals.

### Phase 3: Frontend Editor & Integration [COMPLETED]

**Objective:** Build the UI for pitch editing and integrate it into the abseiling type editor.

- [x] Create `frontend/src/types/journals.ts` interfaces for `AbseilPitch`.
- [x] Build `PitchEditor` React component:
  - [x] Grid-based editing interface for adding/removing pitches.
  - [x] Dropdowns for anchor location and type (using constants).
  - [x] Checkboxes for setup and rescue flags.
- [x] Integrate `PitchEditor` into `AbseilingTripTypeEditor`:
  - [x] Add auto-calculation logic for abseil counts and lengths when pitch data changes.
  - [x] Allow manual override of calculated totals.
- [x] Add unit tests for `PitchEditor` component rendering and state updates.
- [x] Add/update E2E test to include pitch creation and auto-calculation verification.

#### Phase 4: Activity Template Domain Model and Repository
**PR Size:** ~5–7 files

Create the template entity, migration, and repository. No API or UI yet.

**Acceptance Criteria:**
- [x] Migration creates `activity_templates` table (id UUID, user_id, name, template_type enum, region, description, timestamps) with type-specific columns: french_grade, canyon_type, water_gauge_name (canyoning), is_vertical, is_horizontal (caving), climbing_type, grade, length (climbing)
- [x] Migration creates `template_pitches` table (template_id FK, pitch_number, height, anchor_location, anchor_type, did_rescue, did_setup)
- [x] Migration adds `template_id` FK to `journal_canyoning_data`
- [x] `ActivityTemplate` domain entity with validation (name required, template_type constrained)
- [x] `TemplatePitch` domain entity (reuses same field constraints as `AbseilPitch`)
- [x] `ActivityTemplateRepository` interface and SQL implementation (save, find_by_id, find_by_user, search_by_name, delete)

**Required Test Coverage:**
- **Unit:** ✅ ActivityTemplate entity validation (31 tests), TemplatePitch validation (31 tests).
- **Integration:** ✅ ActivityTemplateRepository CRUD with pitches, search by name, template_type filtering (19 tests).

#### Phase 5: Activity Template API and MCP Tools
**PR Size:** ~5–7 files

Expose templates through REST API and MCP. Add `template_id` to canyoning API flow.

**Acceptance Criteria:**
- [x] Template CRUD API endpoints: `GET /api/templates`, `POST /api/templates`, `GET /api/templates/{id}`, `PUT /api/templates/{id}`, `DELETE /api/templates/{id}`
- [x] Template search/filter by name and template_type
- [x] Template responses include nested pitches
- [x] `template_id` field added to `CanyoningDataSchema` and wired through converters/controllers
- [x] MCP tools: `create_template`, `search_templates`, `get_template`, `update_template`
- [x] Template DI registration in provider

**Required Test Coverage:**
- **Unit:** template schema validation, converter logic.
- **Integration:** API endpoint tests for template CRUD, search, and canyoning journal with template_id. MCP tool integration tests.

#### Phase 6: Template Selector UI [COMPLETED]
**PR Size:** ~4–6 files

Build the template selector component and integrate it into `CanyoningTypeEditor`.

**Acceptance Criteria:**
- [x] `TemplateSelector` component: searchable combobox that loads templates filtered by template_type
- [x] Selecting a template copies its standard pitches into the journal's pitch editor as editable defaults
- [x] Template reference stored as `template_id` on the journal type data
- [x] Inline "Create Template" action within the selector (opens a dialog to create and immediately select a new template)
- [x] Integration into `CanyoningTypeEditor` — template selector appears alongside existing canyoning fields

**Required Test Coverage:**
- **Unit:** TemplateSelector rendering, search, selection, pitch pre-population.
- **E2E:** create a template, create a canyoning journal selecting that template, verify pitches pre-populate and are editable.

#### Phase 7: Template Inline Creation and E2E Hardening [COMPLETED]
**PR Size:** ~3–5 files

Polish inline template creation flow, ensure template creation works from within journal forms, and add cross-cutting E2E coverage.

**Acceptance Criteria:**
- [x] Inline template creation dialog: create a template with pitches without leaving the journal form
- [x] Newly created template is immediately selectable and pre-populates pitches
- [x] Template management accessible from a dedicated UI surface (e.g. settings or sidebar link)
- [x] E2E coverage for the full pitch + template workflow end-to-end
- [x] Can copy pitches on the current journal/make a template from the journal

**Required Test Coverage:**
- **E2E:** full workflow: create template → create journal with template → edit pitches → verify totals. Template CRUD from management surface.

---

### ITER9-002: Modified Existing Types — CLIMBING and KAYAKING
**Objective:** Update CLIMBING to gain ABSEILING_TRIP as a dependency (enabling pitch tracking for multi-pitch climbing) and add white water tracking fields to KAYAKING.
**Strategy:** Split into 2 phases. Backend schema/domain changes land first for both types, then frontend editors and E2E follow.

**Specification Reference:**
- [CLIMBING](../product-specifications/outdoor-logbook-product-specification.md#climbing)
- [KAYAKING](../product-specifications/outdoor-logbook-product-specification.md#kayaking)

**Acceptance Criteria (task-level):**
- [x] Creating a CLIMBING journal automatically creates ABSEILING_TRIP data (with null fields)
- [x] Climbing journals can optionally track abseil pitches and link to climbing templates
- [x] Kayaking journals can record white water status and rapids grade
- [x] Existing climbing and kayaking journals are not broken by the migration
- [x] All capabilities available through REST API and MCP
- [x] Unit, integration, and e2e test coverage

#### Phase 1: CLIMBING Dependency Change and KAYAKING Schema Updates
**PR Size:** ~5–7 files

Update type dependencies, schema, and API for both types. No frontend changes yet.

**Acceptance Criteria:**
- [x] CLIMBING type dependency updated: CLIMBING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
- [x] Migration adds `template_id` (UUID FK to activity_templates) to `journal_climbing_data`
- [x] Migration backfills null `journal_abseiling_data` rows for existing climbing journals
- [x] Migration adds `is_white_water` (boolean) and `rapids_grade` (string) to `journal_kayaking_data`
- [x] `ClimbingData` entity updated with `template_id` field
- [x] `KayakingData` entity updated with `is_white_water` and `rapids_grade` fields, rapids_grade validated against International Scale (I–VI)
- [x] API schemas and converters updated for both types
- [x] MCP type data handling updated for both types

**Required Test Coverage:**
- **Unit:** ClimbingData with template_id, KayakingData with white water fields and rapids_grade validation. Type dependency tests updated.
- **Integration:** API tests creating climbing journals (verify ABSEILING_TRIP auto-created), kayaking journals with white water fields. Migration rollback safety.

#### Phase 2: Frontend Editors and E2E Coverage
**PR Size:** ~4–6 files

Update frontend type editors and add E2E tests.

**Acceptance Criteria:**
- [x] `ClimbingTypeEditor` gains template selector (reuses `TemplateSelector` from ITER9-001) and pitch editing via `PitchEditor`
- [x] `KayakingTypeEditor` gains white water toggle and rapids grade dropdown (I–VI)
- [x] Frontend TypeScript types updated for both modified schemas
- [x] Existing climbing and kayaking E2E tests still pass

**Required Test Coverage:**
- **Unit:** ClimbingTypeEditor with template/pitch integration, KayakingTypeEditor with white water fields.
- **E2E:** create climbing journal with pitches and template, create kayaking journal with white water data, verify existing non-white-water kayaking still works.

---

### ITER9-003: New Outdoor Activity Types — CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING
**Objective:** Add five new outdoor activity types following the established pattern from Iteration 4.5.
**Strategy:** Split into 3 phases by complexity. CAVING lands first (compound type with ABSEILING_TRIP dependency and template support). CANOEING follows (simple type with one field). The three minimal types (SNORKELLING, DIVING, DOWNHILL_SKIING) are batched together since they share the same no-field pattern.

**Specification Reference:**
- [CAVING](../product-specifications/outdoor-logbook-product-specification.md#caving)
- [CANOEING](../product-specifications/outdoor-logbook-product-specification.md#canoeing)
- [SNORKELLING](../product-specifications/outdoor-logbook-product-specification.md#snorkelling)
- [DIVING](../product-specifications/outdoor-logbook-product-specification.md#diving)
- [DOWNHILL_SKIING](../product-specifications/outdoor-logbook-product-specification.md#downhill_skiing)
- [Updated Type Dependency Summary](../product-specifications/outdoor-logbook-product-specification.md#updated-type-dependency-summary)

**Acceptance Criteria (task-level):**
- [x] All five types can be created, updated, and queried through REST API and MCP
- [x] CAVING journals automatically gain ABSEILING_TRIP data and can use caving templates
- [x] CANOEING journals capture water type
- [x] SNORKELLING, DIVING, and DOWNHILL_SKIING journals work with minimal type-specific data
- [x] All types inherit OUTDOOR_ACTIVITY fields (weather, role, leadership, participant notes)
- [x] Frontend editors render for each type with appropriate fields
- [x] Unit, integration, and e2e test coverage for all five types

#### Phase 1: CAVING — Full Vertical Slice
**PR Size:** ~8–10 files

Deliver CAVING as a complete vertical slice: domain, migration, repository, API, frontend editor, MCP.

CAVING is the most complex new type — it has ABSEILING_TRIP as a dependency (like CANYONING) and supports templates.

**Acceptance Criteria:**
- [x] Migration creates `journal_caving_data` table (journal_id PK/FK, template_id UUID FK nullable, is_vertical boolean nullable, is_horizontal boolean nullable, timestamps)
- [x] CAVING added to `JournalType` enum with dependencies: CAVING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
- [x] `CavingData` domain entity with validation
- [x] `CavingDataRepository` interface and SQL implementation
- [x] Type system updated: dependency map, table mapping, NOTE detection JOINs
- [x] API schema (`CavingDataSchema`), converter, and controller integration
- [x] MCP handles CAVING type data through existing generic journal tools
- [x] Frontend: CAVING added to `JournalType` enum, `CavingTypeEditor` component with template selector, is_vertical/is_horizontal toggles
- [x] DI provider registration

**Required Test Coverage:**
- **Unit:** CavingData entity validation. Type dependency resolution for CAVING (verify ABSEILING_TRIP auto-created).
- **Integration:** CavingDataRepository CRUD. API test creating caving journal with template, verifying ABSEILING_TRIP data auto-created.
- **E2E:** create a caving journal with template selection, verify it appears in journal list with correct type.

#### Phase 2: CANOEING — Full Vertical Slice
**PR Size:** ~7–9 files

Deliver CANOEING as a complete vertical slice. Simpler than CAVING — one type-specific field, no compound dependencies.

**Acceptance Criteria:**
- [x] Migration creates `journal_canoeing_data` table (journal_id PK/FK, water_type string nullable, timestamps)
- [x] CANOEING added to `JournalType` enum with dependencies: CANOEING → [OUTDOOR_ACTIVITY, FITNESS]
- [x] `CanoeingData` domain entity with validation
- [x] `CanoeingDataRepository` interface and SQL implementation
- [x] Type system updated: dependency map, table mapping, NOTE detection JOINs
- [x] API schema (`CanoeingDataSchema`), converter, and controller integration
- [x] MCP handles CANOEING type data
- [x] Frontend: `CanoeingTypeEditor` with water_type dropdown (river, lake, sea)
- [x] DI provider registration

**Required Test Coverage:**
- **Unit:** CanoeingData entity validation.
- **Integration:** CanoeingDataRepository CRUD. API test creating/updating canoeing journal.
- **E2E:** create a canoeing journal with water type, verify it renders correctly.

#### Phase 3: SNORKELLING, DIVING, DOWNHILL_SKIING — Minimal Types Batch
**PR Size:** ~8–10 files

Deliver three minimal types together. Each has no unique fields beyond journal_id and timestamps, so they follow an identical pattern.

**Acceptance Criteria:**
- [x] Migration creates `journal_snorkelling_data`, `journal_diving_data`, `journal_downhill_skiing_data` tables (journal_id PK/FK, timestamps only)
- [x] All three added to `JournalType` enum with dependencies: each → [OUTDOOR_ACTIVITY, FITNESS]
- [x] Domain entities (`SnorkellingData`, `DivingData`, `DownhillSkiingData`) with journal_id validation
- [x] Repository interfaces and SQL implementations for all three
- [x] Type system updated: dependency map, table mapping, NOTE detection JOINs for all three
- [x] API schemas, converters, and controller integration for all three
- [x] MCP handles all three through existing generic journal tools
- [x] Frontend: type enum updated, minimal editor components for each (placeholder indicating no type-specific fields, inheriting OUTDOOR_ACTIVITY fields)
- [x] DI provider registration for all three
- [x] Outdoor activity subtype enum finalised with all new types (used by OUTDOOR_TRAINING/OUTDOOR_PLANNING in Task 4)
- [x] Any refatoring required to handle common outdoor activity types logic
- [x] Any maintanability refactoring required for adding more journal types easily

**Required Test Coverage:**
- **Unit:** entity validation for all three, journal type count and dependency tests updated.
- **Integration:** repository CRUD and API tests for all three types.
- **E2E:** create one journal of each type, verify they appear in journal list with correct types.

---

### ITER9-004: Supporting Types — OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE, and Gear Items
**Objective:** Add training, planning/meeting, and gear maintenance journal types plus the gear item supporting entity.
**Strategy:** Split into 4 phases. Gear items land first as a standalone entity (required by GEAR_MAINTENANCE). Then each supporting type lands as a vertical slice. OUTDOOR_TRAINING and OUTDOOR_PLANNING land before GEAR_MAINTENANCE since they are simpler.

**Specification Reference:**
- [OUTDOOR_TRAINING](../product-specifications/outdoor-logbook-product-specification.md#outdoor_training)
- [OUTDOOR_PLANNING](../product-specifications/outdoor-logbook-product-specification.md#outdoor_planning)
- [GEAR_MAINTENANCE](../product-specifications/outdoor-logbook-product-specification.md#gear_maintenance)
- [Gear Items](../product-specifications/outdoor-logbook-product-specification.md#gear-items)

**Acceptance Criteria (task-level):**
- [x] OUTDOOR_TRAINING journals can record focus areas from the outdoor activity subtype enum plus custom "other" entries
- [x] OUTDOOR_PLANNING journals extend EVENT with topics and activity type references
- [x] GEAR_MAINTENANCE journals link to a gear item and record maintenance type, related activity types, and optional retirement reason
- [x] Gear items can be created, listed, updated, and searched
- [x] Gear items can be created inline during gear maintenance journal creation/editing
- [x] All capabilities available through REST API and MCP
- [x] Unit, integration, and e2e test coverage

#### Phase 1: Gear Item Entity, API, and MCP Tools
**PR Size:** ~6–8 files

Create the gear item supporting entity with full CRUD. No journal type yet — gear items are standalone.

**Acceptance Criteria:**
- [x] Migration creates `gear_items` table (id UUID, user_id, name string required, model string nullable, serial_number string nullable, purchase_date date nullable, manufacturer string nullable, timestamps)
- [x] `GearItem` domain entity with validation (name required, length constraints)
- [x] `GearItemRepository` interface and SQL implementation (save, find_by_id, find_by_user, search_by_name, delete)
- [x] `GearItemService` with Dishka DI
- [x] API endpoints: `GET /api/gear-items`, `POST /api/gear-items`, `GET /api/gear-items/{id}`, `PUT /api/gear-items/{id}`, `DELETE /api/gear-items/{id}`
- [x] MCP tools: `create_gear_item`, `list_gear_items`, `get_gear_item`, `update_gear_item`
- [x] DI provider registration

**Required Test Coverage:**
- **Unit:** ✅ GearItem entity validation (18 tests).
- **Integration:** ✅ GearItemRepository CRUD (13 tests), API endpoint tests (9 tests).

#### Phase 2: OUTDOOR_TRAINING — Full Vertical Slice
**PR Size:** ~7–9 files

Deliver OUTDOOR_TRAINING as a complete vertical slice.

**Acceptance Criteria:**
- [x] Migration creates `journal_outdoor_training_data` table (journal_id PK/FK, focus_areas JSONB/text[] nullable, timestamps)
- [x] OUTDOOR_TRAINING added to `JournalType` enum with dependencies: OUTDOOR_TRAINING → [OUTDOOR_ACTIVITY, FITNESS]
- [x] `OutdoorTrainingData` domain entity with validation (focus_areas validated against outdoor activity subtype enum + "other" free text)
- [x] `OutdoorTrainingDataRepository` interface and SQL implementation
- [x] Type system updated: dependency map, table mapping, NOTE detection JOINs
- [x] API schema (`OutdoorTrainingDataSchema`), converter, and controller integration
- [x] MCP handles OUTDOOR_TRAINING through existing generic journal tools
- [x] Frontend: `OutdoorTrainingTypeEditor` with multi-select for focus areas (outdoor activity subtypes) plus free-text "other" input
- [x] DI provider registration

**Required Test Coverage:**
- **Unit:** ✅ OutdoorTrainingData entity validation, focus_areas enum + "other" handling.
- **Integration:** ✅ repository CRUD, API test creating/updating training journal with focus areas.
- **E2E:** ✅ create an outdoor training journal with multiple focus areas including "other", verify it renders correctly.

#### Phase 3: OUTDOOR_PLANNING — Full Vertical Slice
**PR Size:** ~7–9 files

Deliver OUTDOOR_PLANNING as a complete vertical slice. This type extends EVENT rather than OUTDOOR_ACTIVITY.

**Acceptance Criteria:**
- [x] Migration creates `journal_outdoor_planning_data` table (journal_id PK/FK, topics text nullable, activity_types JSONB/text[] nullable, timestamps)
- [x] OUTDOOR_PLANNING added to `JournalType` enum with dependencies: OUTDOOR_PLANNING → [EVENT]
- [x] `OutdoorPlanningData` domain entity with validation (activity_types validated against outdoor activity subtype enum)
- [x] `OutdoorPlanningDataRepository` interface and SQL implementation
- [x] Type system updated: dependency map, table mapping, NOTE detection JOINs
- [x] API schema (`OutdoorPlanningDataSchema`), converter, and controller integration
- [x] MCP handles OUTDOOR_PLANNING through existing generic journal tools
- [x] Frontend: `OutdoorPlanningTypeEditor` with free-text topics field and multi-select for activity types
- [x] DI provider registration

**Required Test Coverage:**
- **Unit:** ✅ OutdoorPlanningData entity validation, activity_types enum validation.
- **Integration:** ✅ repository CRUD, API test creating planning journal (verify EVENT data auto-created with time fields).
- **E2E:** ✅ create an outdoor planning journal with topics and activity types, verify EVENT fields (time, location) are usable.

#### Phase 4: GEAR_MAINTENANCE — Full Vertical Slice with Gear Item Selector
**PR Size:** ~7–9 files

Deliver GEAR_MAINTENANCE as a complete vertical slice with inline gear item creation.

**Acceptance Criteria:**
- [x] Migration creates `journal_gear_maintenance_data` table (journal_id PK/FK, gear_item_id UUID FK, maintenance_type string, activity_types JSONB/text[] nullable, retirement_reason string nullable, timestamps)
- [x] GEAR_MAINTENANCE added to `JournalType` enum with no dependencies (standalone type)
- [x] `GearMaintenanceData` domain entity with validation (gear_item_id required, maintenance_type constrained to: "retiring gear", "repairing gear", "routine inspection", "routine maintenance"; retirement_reason required when maintenance_type is "retiring gear")
- [x] `GearMaintenanceDataRepository` interface and SQL implementation
- [x] Type system updated: dependency map, table mapping, NOTE detection JOINs
- [x] API schema (`GearMaintenanceDataSchema`), converter, and controller integration
- [x] MCP handles GEAR_MAINTENANCE through existing generic journal tools
- [x] Frontend: `GearMaintenanceTypeEditor` with gear item selector (searchable combobox with inline "Create Gear Item" dialog), maintenance type dropdown, activity types multi-select, conditional retirement reason field
- [x] DI provider registration

**Required Test Coverage:**
- **Unit:** ✅ GearMaintenanceData entity validation (maintenance_type constraints, retirement_reason conditional requirement).
- **Integration:** ✅ repository CRUD, API test creating gear maintenance journal with gear item reference.
- **E2E:** ✅ create gear item inline from maintenance journal form, select existing gear item, create retirement maintenance with reason.

---

### ITER9-005: PDF Logbook Export
**Objective:** Implement a user-initiated PDF export that produces a comprehensive outdoor logbook with chronological entries, yearly summaries, and participant index.
**Strategy:** Split into 3 phases. Data aggregation and summary calculation land first (pure backend, testable without PDF rendering). PDF rendering and layout follow. Frontend export trigger and E2E complete the feature.

**Specification Reference:**
- [PDF Logbook Export](../product-specifications/outdoor-logbook-product-specification.md#pdf-logbook-export)

**Acceptance Criteria (task-level):**
- [ ] User can initiate a PDF export from the UI with optional date range and activity type filters
- [ ] PDF contains all matching outdoor logbook entries in chronological order with full hierarchy
- [ ] PDF includes per-calendar-year summary pages with all specified statistics
- [ ] PDF includes participant index for contacts with more than three appearances
- [ ] PDF includes fitness data (distance, elevation, heart rate, duration) where available
- [ ] PDF download works reliably for logbooks with up to several hundred entries
- [ ] Unit tests for summary calculation logic and integration tests for PDF generation

#### Phase 1: Logbook Data Aggregation and Summary Calculation Service
**PR Size:** ~5–7 files

Build the backend service that gathers logbook data, orders it hierarchically, and calculates yearly summaries. No PDF rendering yet — this phase establishes the data contracts.

**Acceptance Criteria:**
- [x] `LogbookDataService` gathers all journals matching outdoor logbook export scope (all OUTDOOR_ACTIVITY subtypes, OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE)
- [x] Journals ordered chronologically by topmost parent journal date, full hierarchy preserved
- [x] Per-entry data includes: title, date, content, all type-specific data, fitness data, abseil pitches, template reference names, participant/invitee contacts
- [x] `LogbookSummaryCalculator` produces per-calendar-year summaries: leadership counts per type, total abseiling metres, total abseils, total activities per type, total setups, total rescues
- [x] `ParticipantIndexCalculator` produces index of contacts appearing as PARTICIPANT or INVITEE in more than three entries
- [x] Data service accepts optional filters: date range, activity types
- [x] Data contracts are pure Python dataclasses suitable for any rendering backend

**Required Test Coverage:**
- **Unit:** summary calculation logic (leadership counts, abseiling aggregates, per-type counts). Participant index threshold logic. Hierarchy ordering.
- **Integration:** data service tests with real database journals spanning multiple years, types, and hierarchy levels.

#### Phase 2: PDF Rendering and Layout
**PR Size:** ~4–6 files

Render the aggregated logbook data into a PDF document using a Python PDF library (e.g. reportlab or weasyprint).

**Acceptance Criteria:**
- [x] `LogbookPdfRenderer` takes the data contracts from Phase 1 and produces a PDF byte stream
- [x] PDF layout: cover page, chronological journal entries with hierarchy indentation, type-specific data sections, abseil pitch tables, fitness data blocks
- [x] Summary pages rendered per calendar year with all specified statistics in a readable table format
- [x] Participant index rendered as a sorted table at the end of the PDF
- [x] PDF handles logbooks with up to several hundred entries without excessive memory usage or timeout

**Required Test Coverage:**
- **Unit:** PDF structure assertions (page count, section presence) using deterministic fixture data.
- **Integration:** end-to-end PDF generation from seeded database data, verifying the output is a valid PDF with expected content.

#### Phase 3: Export API Endpoint, Frontend Trigger, and E2E
**PR Size:** ~5–7 files

Wire the export through a REST endpoint and add the frontend UI trigger.

**Acceptance Criteria:**
- [ ] `POST /api/journals/export/outdoor-logbook` endpoint accepts optional date range and activity type filters, returns PDF as a downloadable file response
- [ ] Frontend export trigger: button in the journals UI (e.g. toolbar or settings area) that opens a filter dialog (date range picker, activity type multi-select) and initiates download
- [ ] Loading state shown during PDF generation
- [ ] Error handling for empty exports (no matching journals) and generation failures
- [ ] PDF export is UI-only — not exposed through MCP (per spec)

**Required Test Coverage:**
- **Integration:** API endpoint tests for export with filters, empty export handling, authentication requirement.
- **E2E:** trigger export from UI with filters, verify PDF file downloads successfully.

---

## Architecture Notes

**Type Dependency System (updated):**
```
# Existing (unchanged)
FITNESS → []
OUTDOOR_ACTIVITY → [FITNESS]
BUSHWALKING → [OUTDOOR_ACTIVITY, FITNESS]
ABSEILING_TRIP → [OUTDOOR_ACTIVITY, FITNESS]
CANYONING → [BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
CROSS_COUNTRY_SKIING → [BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS]
JOGGING → [FITNESS]

# Modified
CLIMBING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]  (added ABSEILING_TRIP)

# New outdoor types
CAVING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
CANOEING → [OUTDOOR_ACTIVITY, FITNESS]
SNORKELLING → [OUTDOOR_ACTIVITY, FITNESS]
DIVING → [OUTDOOR_ACTIVITY, FITNESS]
DOWNHILL_SKIING → [OUTDOOR_ACTIVITY, FITNESS]

# New supporting types
OUTDOOR_TRAINING → [OUTDOOR_ACTIVITY, FITNESS]
OUTDOOR_PLANNING → [EVENT]
GEAR_MAINTENANCE → []
```

**Abseil Pitches:**
- Stored as rows in `abseil_pitches` table with FK to `journal_abseiling_data`
- Optimised for the common case of 5–20 pitches (max ~60)
- Auto-calculate totals with manual override

**Activity Templates:**
- User-owned, not shared across users
- Separate from the existing Route entity (Routes track GPS data, templates define pitch characteristics)
- Template pitches are copied to journal on selection (editable, not linked)

**Gear Items:**
- User-owned supporting entity, similar to templates
- Future SnipeIT sync compatible (name, model, serial_number, manufacturer)
- Referenced from GEAR_MAINTENANCE journal type data

## Testing Strategy

**Unit Tests:**
- Domain entity validation for all new types
- Pitch auto-calculation logic
- Template pre-population logic
- PDF summary calculation
- Type dependency resolution for modified and new types

**Integration Tests:**
- Repository CRUD for pitches, templates, gear items, and all new type data
- API endpoint coverage for new types, templates, and gear items
- MCP tool coverage for new capabilities

**E2E Tests (Playwright):**
- Create journals for each new type with appropriate type-specific data
- Pitch editor add/edit/delete workflow
- Template search, selection, and pitch pre-population
- Gear item inline creation from maintenance journal
- PDF export trigger and download

## Success Criteria

- [ ] `activity_type` field removed — subtypes fully define activities
- [ ] Abseil pitches tracked with anchor details and auto-calculated totals
- [ ] Activity templates created and reused for canyoning, caving, and climbing
- [ ] All five new outdoor activity types functional (CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING)
- [ ] All three supporting types functional (OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE)
- [ ] Gear items created and linked to maintenance journals
- [ ] PDF logbook export with hierarchy, yearly summaries, and participant index
- [ ] All new capabilities accessible through MCP using existing generic patterns
- [ ] All tests passing, quality gates green
