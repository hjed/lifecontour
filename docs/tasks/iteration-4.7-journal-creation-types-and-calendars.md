# Iteration 4.7 – Journal Creation, Types & Calendar Management

**Status:** 🔵 IN PROGRESS
**Dependencies:** Iteration 4 (Journal Core & Base Types), Iteration 4.5 (Fitness & Activity Types), Iteration 4.6 (Filtering, Hierarchy & E2E Coverage); prepares groundwork for Iteration 7 (Google Calendar Integration)
**Goal:** Make journal creation and editing robust and spec-compliant for types and calendars, with clear UI flows, full test coverage, and MCP parity.

## 1. Background & Motivation
- Create Journal flow sometimes fails to attach selected types and their dependent types correctly, especially for complex activity types where required data is missing.
- Inline editing components used on the journal detail page are more robust but not reused in the creation flow, leading to duplicated and inconsistent logic.
- Users cannot add/remove journal types after creation from the UI, despite backend support via `update_journal_entry` and type-specific data endpoints.
- Calendar configuration exists in the domain (calendars table, EVENT calendar_info) but there is no first-class UI for adding/removing calendars or configuring sync-related metadata.
- This iteration focuses on closing these gaps without implementing Google Calendar sync itself (covered by Iteration 7).

## 2. Scope
### 2.1 In Scope
- Refactor Create Journal UI to reuse inline editors and reliably attach types and type_data (including dependent types).
- Add UI to add/remove types on existing journals, with inline editing of type-specific data.
- Add UI and minimal backend surface needed to add, edit, and remove calendars (name, description, color, sync configuration flags) in a way that is forward-compatible with Google Calendar sync.
- For all touched behaviour, ensure unit, integration, and Playwright E2E tests are written first and extended as needed.
- Keep MCP journal tools (`create_journal_entry`, `update_journal_entry`, calendar-related query tools) in sync with any API changes.

### 2.2 Out of Scope / Non‑Goals
- Implementing Google Calendar API calls, sync workers, or webhook handling (covered by Iteration 7).
- Replacing existing calendar views or building new calendar UI such as month/week/day views (Iteration 7).
- New journal types or changes to type dependency rules beyond what is required to fix bugs in type attachment.

## 3. Tasks

### ITER4.7-001: Journal Creation Flow & Type Attachment Reliability ✅ COMPLETE
**Description:** Make the Create Journal flow spec-compliant for types by reusing inline editors and ensuring type dependencies and type_data are created correctly.
**Strategy:** Single PR focused on creation flow plus small backend bug fixes, forming a complete vertical slice.
**Specification Reference:** [Journal Types](../journal-system-specification.md#journal-types), [Type Dependency Rules](../journal-system-specification.md#type-dependency-rules), [API & MCP Tools](../journal-system-specification.md#api-and-mcp-tools)

**PR Size:** ~10–14 files (frontend Create Journal components/tests, small backend fixes/tests, Playwright E2E).

**Acceptance Criteria:**
- [x] Audit existing Create Journal UI and inline editors (e.g. journal detail type editors) and document current gaps in a short section in this file.
- [x] Refactor Create Journal UI to compose the same inline editing components used on the detail page for each supported type (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM, FITNESS/OUTDOOR_ACTIVITY and activity subtypes as appropriate).
- [x] Ensure type dependency rules are enforced on creation (for example, creating CANYONING also creates required OUTDOOR_ACTIVITY, FITNESS, and other dependent types) and that empty type_data rows are created for dependent types as per the spec.
- [x] Fix any backend/service/repository bugs that cause missing or partially-attached types when required type_data is absent; cover this with targeted unit and integration tests.
- [x] For every journal type that appears in the Create Journal UI, add a deterministic Playwright E2E test that (a) creates the journal via the UI, (b) asserts the expected set of types is attached (including dependencies), and (c) verifies key type-specific fields are persisted.
- [x] Ensure tests are written first (or extended) before implementation changes (`pytest` unit plus integration, Playwright E2E).
- [x] Run and fix all quality gates for the PR: `uv run pytest` (backend), `pnpm quality:check` (frontend), plus any pre-commit hooks.
- [x] If `POST /api/journals` or the journals MCP `create_journal_entry` interface is changed (fields, required/optional semantics, or type handling), update MCP schemas, docs, and tests in lockstep.

### ITER4.7-002: Journal Type Management UI (Add/Remove Types with Inline Editing)
**Description:** Allow users to add and remove types from an existing journal in the UI, editing type-specific data inline while respecting dependency rules.
**Strategy:** Single PR centred on a type-management component wired to existing update endpoints, plus backend tests and E2E coverage.
**Specification Reference:** [Journal Types](../journal-system-specification.md#journal-types), [Type Dependency Rules](../journal-system-specification.md#type-dependency-rules), [API & MCP Tools](../journal-system-specification.md#api-and-mcp-tools)

**PR Size:** ~10–15 files (frontend type management components/tests, backend tests and minor API adjustments if needed, Playwright E2E).

**Acceptance Criteria:**
- [x] Implement a dedicated UI component on the journal detail page to manage types: list current types, add new types, and remove existing types.
- [x] When adding a type, enforce dependency rules and automatically attach required dependent types; when removing a type, enforce safe behaviour (for example, preventing removal that would violate dependency consistency).
- [x] Reuse type-specific inline editors for editing type_data when adding a new type or updating an existing type’s data; avoid duplicating form logic.
- [x] Wire the UI to backend update capabilities (for example, `update_journal_entry` and/or type-specific data endpoints) with clear JSON API contracts.
- [x] Add backend unit and integration tests that cover adding/removing types via the API, including complex activity-type dependency scenarios and error cases.
- [x] Add focused Playwright E2E tests that (a) start from an existing journal, (b) add at least one additional type and verify persistence, and (c) remove a type where allowed and verify database state and UI update.
- [x] Ensure tests are written or extended before implementation (`pytest` unit plus integration, Playwright E2E).
- [ ] Run and fix all quality gates for the PR (same as above).
- [ ] If `PATCH/PUT /api/journals/{id}` or related MCP tools (`update_journal_entry`, search filters by type) change in shape or semantics, update MCP tools, schemas, and tests accordingly.

### ITER4.7-003: Calendar Management UI & Metadata (Future‑Proofed for Google Sync)
**Description:** Expose calendar management in the UI (create/update/delete calendars and basic sync metadata) so EVENT journals can reliably reference calendars, without yet implementing Google sync.
**Strategy:** Single PR that introduces a simple calendar settings UI and any missing backend endpoints, designed to align with Iteration 7 expectations.
**Specification Reference:** [Calendars](../journal-system-specification.md#calendars), [Google Calendar Integration](../journal-system-specification.md#google-calendar-integration), [Iteration 7 – Google Calendar Integration](./iteration-7-calendar-integration.md)

**PR Size:** ~10–14 files (backend calendar API plus tests, frontend calendar management UI plus tests, Playwright E2E).

**Acceptance Criteria:**
- [ ] Confirm or introduce a `calendars` table and domain model consistent with the spec (`id`, `user_id`, `name`, `description`, `color`, `is_synced_to_google`, `google_calendar_id`, timestamps).
- [ ] Implement JSON API-compliant endpoints for listing, creating, updating, and soft-deleting calendars, with appropriate validation and authorization.
- [ ] Add backend unit and integration tests for these calendar endpoints, including constraints relevant to EVENT journals (for example, preventing deletion of a calendar that still has EVENT journals unless a clear migration path is implemented).
- [ ] Implement a Calendar Settings UI (for example, under journal or global settings) that allows adding/removing calendars, editing name and color, and toggling sync-related flags without triggering actual Google sync.
- [ ] Ensure the EVENT journal type UI (creation and inline editors) consumes the calendar list from these APIs and handles calendar deletion or renaming gracefully.
- [ ] Add Playwright E2E tests that cover (a) creating a new calendar and using it when creating an EVENT journal, and (b) editing/removing calendars with expected constraints and error handling.
- [ ] Ensure tests are written or extended before implementation (`pytest` unit plus integration, Playwright E2E).
- [ ] Run and fix all quality gates for the PR (same as above).
- [ ] If calendar-related REST endpoints or MCP tools (for example, journal search filters by `calendar_id` or any future calendar MCP tools) are introduced or changed, update their MCP definitions and tests in the same PR.

## 4. Testing & Quality Expectations for Iteration 4.7
- All tasks follow strict test‑first development: write or extend unit, integration, and E2E tests before implementing behaviour.
- Tests must use the existing fixtures and deterministic test data patterns (no conditional logic or data-dependent skipping).
- Each PR must run and pass:
  - `uv run pytest` for backend unit and integration tests.
  - `pnpm quality:check` (format, lint, type-check) for frontend.
  - Relevant Playwright E2E test suite portion for journals and calendars.
- No MCP tool or REST API change is allowed to merge without corresponding schema, test, and documentation updates.

