# Iteration 4.6 – Journal Filtering, Hierarchy & E2E Coverage

## 1. Background & Motivation

The core journal system (Iteration 4) is implemented and has solid list/detail/workflow coverage in E2E tests.
However, several spec-defined behaviours are either only partially implemented or not yet covered end-to-end.
This iteration focuses on:
- Bringing backend filtering behaviour in line with the journal specification
- Implementing the contact-page parent/child hierarchy display
- Extending E2E coverage for filtering, search and detail interactions

### Key References
- **Journal spec**: `docs/journal-system-specification.md`
  - Search & filtering: ~lines 592–651
  - `GET /api/journals` endpoint: ~lines 717–719
  - Frontend list filter requirements: ~lines 1045–1060
  - E2E testing requirements: ~lines 1187–1196
- **Iteration 4 task doc**: `docs/tasks/iteration-4-journal-system.md`
  - Contact page limitations & parent/child note: ~lines 1197–1204
  - Phase 6 / testing notes & deferred items: ~lines 750–816


## 2. Current State (Implementation vs Spec)

### 2.1 Backend filtering
- `GET /api/journals` controller in `backend/app/api/journals/controllers.py`:
  - Accepts: `type` (journal_type), `start_date`, `end_date`, `contact_id`, `tag_id`,
    `calendar_id`, `parent_id`, `search`, plus pagination.
  - **Currently only uses `journal_type`** when calling the service & repository.
- `JournalService.get_journals_paginated` (core journal service):
  - Passes only `journal_type` to the repository.
- `JournalRepository.get_all` (SQL adapter):
  - Supports filtering by `journal_type` only.
- **Result**: UI appears to support multiple filters, but backend filtering (other than type)
  is effectively a no-op.

### 2.2 Contact page hierarchy
- Contact detail page currently shows a **flat list** of journals sorted by date.
- Spec requires parent journals with children grouped underneath per contact,
  but Iteration 4 task doc explicitly notes this hierarchy as not yet implemented.
- Backend already supports parent/child relationships; the gap is primarily in the UI
  (and E2E coverage of that UI).

### 2.3 E2E coverage gaps
- Journals list & workflows:
  - Type filtering and basic search are covered.
  - No E2E coverage of date range, contact, tag, calendar or parent filters.
- Journal detail view:
  - Inline editing of title/content/date range is covered.
  - Tags, contacts, calendar and some type-specific interactions are implemented
    in `JournalDetailView.tsx` but lack explicit E2E coverage.
- Search (MeiliSearch):
  - Indexing and search endpoints exist.
  - E2E tests do not yet exercise realistic search flows beyond basic text filter.


## 3. Goals & Non‑Goals

### 3.1 Goals
1. Implement spec-compliant journal filtering in the backend for:
   - Date range (`start_date`/`end_date`)
   - Contact (`contact_id`)
   - Tag (`tag_id` / basic single-tag support)
   - Calendar (`calendar_id`)
   - Parent (`parent_id` including root-only view)
   - Text search (`search`, backed by MeiliSearch where appropriate)
2. Implement parent/child journal hierarchy display on **contact detail** pages.
3. Add focused E2E coverage for:
   - Each of the filter types above on the journals list page
   - Search flows that combine text search with filters
   - Detail-view interactions for tags, contacts, calendar and relevant type sections.

### 3.2 Non‑Goals
- Large UI re-designs of the journal list or contact pages.
- Performance tuning (pagination/infinite scroll, search ranking tweaks) beyond
  what is necessary to meet functional acceptance criteria.
- Implementing new journal types beyond what already exists.


## 4. PR‑Sized Iterations

Each sub‑iteration below is intended to fit in a single PR with its own tests and
clear acceptance criteria.

### 4.1 Iteration A – Backend Filter Implementation

**Status**: ✅ COMPLETE

**Scope**
- Extend repository, service and controller layers so that all supported filter
  parameters affect `GET /api/journals` results.

**Key Tasks**
- ✅ Update `JournalRepository.get_all` interface and implementation to accept:
  - `journal_type`, `start_date`, `end_date`, `contact_id`, `tag_id`,
    `calendar_id`, `parent_id`, `search`.
- ✅ Implement SQL filtering for each parameter, matching the high-level rules
  from the spec (e.g. inclusive date ranges, AND-combining filters).
  - Implemented in `backend/app/core/journal/adapters/sql/journal_repository.py`
  - Uses dynamic query building with parameterized queries for SQL injection protection
  - Supports all filter types with proper JOINs for relationships
  - Date filters use overlap logic: `journal.end >= start_date AND journal.start <= end_date`
  - Date parameters converted from ISO strings to datetime objects for PostgreSQL
- ✅ Update `JournalService.get_journals_paginated` to pass through all filters.
  - Updated in `backend/app/core/journal/services/journal_service.py`
- ✅ Update `JournalService.get_journals_count` to pass through all filters for accurate pagination.
- ✅ Update `list_journals` controller to forward all query params to the service.
  - Updated in `backend/app/api/journals/controllers.py`
- ✅ Add unit/integration tests at the repository/service level to verify filter
  behaviour in isolation from the UI.
  - Added 9 repository filter tests in `test_journal_repository_integration.py`
  - Added 4 service filter tests in `test_journal_service_integration.py`
  - All 113 backend journal tests passing

**Acceptance Criteria**
- ✅ Given backend tests only, each filter parameter demonstrably restricts results
  as expected by the spec.
- ✅ Combining multiple filters (e.g. date + type + contact) works as logical AND.
- ✅ Existing journal list E2E tests continue to pass without modification.

**Implementation Notes**
- Date filters use `event_date_range_start` and `event_date_range_end` columns
- Contact filter joins `journal_contact_relationships` table
- Tag filter joins `journal_tag_assignments` table
- Calendar filter joins `journal_calendar_info` table (or uses existing join for EVENT type)
- Search filter uses ILIKE on title and content (can be enhanced with MeiliSearch later)
- All queries use DISTINCT to handle multiple joins correctly


### 4.2 Iteration A.5 – Backend API Integration Testing & Fixes

**Status:** ✅ COMPLETE

**Prerequisites**
- Iteration A complete and merged.

**Background**
During E2E test development for Iteration B, several gaps were discovered in the backend API implementations:
1. **NOTE type + contact filter combination fails**: When filtering by NOTE type + contact, the backend returns 0 results even though journals exist with both properties
2. **Contact relationships via API**: Unclear if contact relationships are properly created when journals are created via the POST /api/journals endpoint
3. **Calendar creation API**: A minimal POST /api/calendars endpoint was created for E2E testing but lacks proper integration tests
4. **Journal tag creation API**: No POST /api/journals/tags endpoint exists (only GET endpoint)

**Debug Test Findings**
- ✅ NOTE type filtering works correctly when used alone (verified via E2E test)
- ✅ NOTE type + contact filter combination now works correctly (bug fixed)
- ✅ Backend integration test for combined filters PASSES when creating data via SQL
- ✅ E2E test for combined filters now PASSES when creating data via API
- **Root Cause Found**: POST /api/journals endpoint was NOT processing `type_data` field, so EVENT journals with calendar info weren't actually being created as EVENT type

**Scope**
- Add comprehensive backend integration tests for all journal creation APIs
- Fix any bugs discovered in the API implementations
- Ensure all filter combinations work correctly when journals are created via API (not just via SQL)

**Key Tasks**

**Calendar & Event Journal Testing**
- ✅ Add integration tests for POST /api/calendars endpoint
  - ✅ Test calendar creation with all required fields (name, color)
  - ✅ Test calendar creation with minimal fields (name only, color defaults to #3B82F6)
  - ✅ Test validation and error handling (missing name, invalid color format)
  - ✅ Test that created calendars can be retrieved via GET /api/calendars
  - ✅ Added 4 tests in `backend/tests/integration/api/test_calendar_endpoints.py`
- ✅ Add integration tests for EVENT journal creation with calendar info
  - ✅ Test creating event journals with type_data containing calendar_id
  - ✅ Test that event journals have proper calendar info in journal_calendar_info table
  - ✅ Test that event journals are detected as EVENT type (not NOTE type)
  - ✅ Test creating event journals with all calendar fields (start_time, end_time, is_all_day, location, sync_invitees)
  - ✅ Test filtering event journals by calendar_id
  - ✅ Added 4 tests in `backend/tests/integration/api/test_calendar_endpoints.py`
- ✅ Add integration tests for calendar filtering
  - ✅ Test filtering journals by calendar_id returns only event journals for that calendar
  - ✅ Test that non-event journals are excluded from calendar filter results
  - ✅ Covered in EVENT journal creation tests
- ⬜ Add E2E test for calendar filter (in Iteration B)
  - Create multiple calendars and event journals
  - Verify filtering by calendar shows only journals for that calendar
  - Verify calendar filter works with other filters

**Contact Relationships Testing**
- ✅ Add integration tests for POST /api/journals with contact relationships
  - ✅ Test that contact relationships are properly created in journal_contact_relationships table
  - ✅ Test that journals with contacts can be filtered by contact_id
  - ✅ Test combined filters (NOTE type + contact) with API-created journals
  - ✅ Added 2 tests in `backend/tests/integration/api/test_journal_api_filters.py`

**NOTE Type Testing**
- ✅ Add integration tests for NOTE type detection
  - ✅ Test that journals created without types are detected as NOTE type
  - ✅ Test that NOTE type filtering works with API-created journals
  - ✅ Test that journals with type-specific data (EVENT) are NOT returned by NOTE filter
  - ✅ Test that journals with contact relationships but no type-specific data are NOTE type
  - ✅ Test combined filters: NOTE type + contact
  - ✅ Added comprehensive regression test in `backend/tests/integration/api/test_journal_api_filters.py`

**Journal Tags Testing**
- ✅ Implement POST /api/journals/tags endpoint
  - ✅ Follow same pattern as POST /api/tags for contact tags
  - ✅ Accept name, color, and optional parent_id
  - ✅ Return created tag with generated UUID
  - ✅ Add proper validation and error handling
  - ✅ Implemented in `backend/app/api/journals/controllers.py` (lines 263-323)
- ✅ Add integration tests for journal tag creation
  - ✅ Test tag creation with all fields (including parent_id for hierarchy)
  - ✅ Test tag creation with minimal fields (name only)
  - ✅ Test validation and error handling (missing name)
  - ✅ Test that created tags can be retrieved via GET /api/journals/tags
  - ✅ Added 4 tests in `backend/tests/integration/api/test_journal_tag_endpoints.py`
- ✅ Add integration tests for journal tag filtering
  - ✅ Test assigning tags to journals via POST /api/journals/{id}/relationships/tags
  - ✅ Test removing tags from journals via DELETE /api/journals/{id}/relationships/tags/{tag_id}
  - ✅ Test filtering journals by tag_id
  - ✅ Added 4 tests in `backend/tests/integration/api/test_journal_tag_endpoints.py`

**Search Functionality Testing**
- ⬜ Add integration tests for search functionality
  - Test simple text search by title (ILIKE query)
  - Test simple text search by content (ILIKE query)
  - Test search combined with type filter
  - Test search combined with contact filter
  - Test search combined with date range filter
  - Test search with special characters and edge cases

**Bug Fixes**
- ✅ Investigate and fix NOTE + contact filter combination issue
  - ✅ **Root Cause**: POST /api/journals endpoint was NOT processing `type_data` field
  - ✅ **Fix**: Added code to process `type_data` and create CalendarInfo/PhotoAlbumData entities (lines 592-705 in controllers.py)
  - ✅ Verify contact relationships are created correctly via API
  - ✅ Verify NOTE type detection works with contact relationships
  - ✅ Add regression tests to prevent future issues
- ✅ Fixed calendar response not including default color
  - ✅ Changed controller to use created entity attributes instead of request attributes
- ✅ Fixed CalendarValidationError not being handled
  - ✅ Changed all calendar/type-specific validation errors to inherit from JournalDomainError
  - ✅ Added error code mappings in error_handlers.py
- ✅ Fixed time field type mismatch
  - ✅ Added time string parsing (HH:MM:SS format) before creating CalendarInfo
- ✅ Fixed PhotoAlbumData type error
  - ✅ Changed immich_album_id to pass string directly (not UUID)

**Acceptance Criteria**
- ✅ POST /api/calendars endpoint has comprehensive integration test coverage (4 tests)
- ✅ Event journal creation with calendar info works correctly via API (4 tests)
- ✅ Calendar filtering returns only event journals for the specified calendar
- ✅ All journal creation APIs (journals, calendars, tags) have comprehensive integration test coverage (18 new tests)
- ✅ All filter combinations work correctly when journals are created via API
- ✅ POST /api/journals/tags endpoint implemented and tested (8 tests)
- ✅ Contact relationships are properly created when journals are created via API
- ✅ NOTE type detection works correctly for journals created via API
- ✅ NOTE + contact filter combination bug is fixed
- ✅ All backend integration tests pass (175 tests, up from 157)
- ✅ E2E tests for combined filters can be un-skipped and pass

**Implementation Notes**
- Integration tests use the actual API endpoints with real PostgreSQL database
- Tests verify both the happy path and error cases
- Tests verify that created data can be queried with all filter combinations
- Event journals MUST have calendar info in type_data when created
- The minimal POST /api/calendars endpoint is sufficient for E2E testing
- Full calendar CRUD operations are planned for Iteration 7 (not required here)

**Files Modified**
- `backend/app/api/journals/controllers.py`:
  - Lines 592-705: Added `type_data` processing for EVENT and PHOTO_ALBUM types
  - Lines 263-323: Added POST /api/journals/tags endpoint
- `backend/app/api/calendars/controllers.py`:
  - Lines 56-76: Fixed to use created entity attributes in response
- `backend/app/api/journals/schemas.py`:
  - Lines 186-217: Added journal tag creation schemas
- `backend/app/core/journal/models/exceptions.py`:
  - Changed all calendar/type-specific validation errors to inherit from JournalDomainError
- `backend/app/api/error_handlers.py`:
  - Lines 39-60, 110-148: Added error code mappings for all validation errors

**Files Created**
- `backend/tests/integration/api/test_journal_api_filters.py`: 2 tests for contact relationships and NOTE type filtering
- `backend/tests/integration/api/test_calendar_endpoints.py`: 8 tests for calendar creation and EVENT journals
- `backend/tests/integration/api/test_journal_tag_endpoints.py`: 8 tests for journal tag creation and filtering

**Test Results**
- Total integration tests: 175 (up from 157)
- New tests added: 18
- All tests passing: ✅
- Quality checks: ✅ ruff format, ✅ ruff check, ✅ mypy (306 files)


### 4.3 Iteration B – Journals List E2E Filter & Search Coverage

**Status:** 🔄 IN PROGRESS - Partial Success (12/15 tests passing, 3 skipped pending Iteration A.5)

**Prerequisites**
- Iteration A complete and merged.
- Iteration A.5 complete for un-skipping combined filter tests.

**Scope**
- Extend Playwright specs for `journals-list` / `journals-workflow` to cover
  the new backend filters plus richer search flows.

**Key Tasks**
- ✅ **PREREQUISITE**: Create backend endpoint for fetching journal tags
  - ✅ Created `GET /api/journals/tags` endpoint in `backend/app/api/journals/controllers.py`
  - ✅ Added `JournalTagResource` and `JournalTagListResponse` schemas
  - ✅ Updated frontend `fetchJournalTags()` to use `/api/journals/tags` instead of `/api/tags`
  - ✅ This was a missing piece - the frontend was fetching contact tags instead of journal tags
- ✅ Add targeted E2E tests for:
  - ✅ Date range filter (from/to) affecting which journals appear.
  - ✅ Contact filter limiting list to journals linked to a specific contact.
  - ⏭️ Tag filter limiting list to journals with a given tag (SKIPPED - needs POST /api/journals/tags from Iteration A.5).
  - ⬜ Calendar filter limiting list to a specific calendar (requires Iteration A.5 calendar/event testing).
  - ⬜ Parent filter (e.g. only root journals vs children of a given parent).
- ⬜ Add E2E tests for search scenarios:
  - ⬜ Simple full-text search by title/content.
  - ⬜ Search combined with one or more filters (type, contact, date), verifying
    results match the intersection.
- ⏭️ Add E2E test for combined filters (date + type + contact) - SKIPPED pending Iteration A.5 fixes
- ⬜ Ensure tests use the existing `TestDataManager` / fixtures and run reliably
  in CI.

**Implementation Notes:**
- Updated E2E tests to match actual UI component structure in `JournalFilters.tsx`:
  - Date range filter uses single popover button with calendar picker (not separate from/to buttons)
  - Contact filter uses `ContactSearchCombobox` with combobox role and search input
  - Tag filter requires waiting for tags API to load before checking checkboxes
  - All tests updated to use correct selectors based on actual component implementation
- Tests added in `frontend/tests/e2e/journals-list.spec.ts`:
  - Date range filtering (lines 190-283)
  - Contact filtering (lines 284-383)
  - Tag filtering (lines 384-481)
  - Combined filters - date + type + contact (lines 482-604)
- Backend filtering fully functional and tested (113 backend tests passing)

**Test Results**
- ✅ 12 tests passing: date range, contact, search, type filters all working
- ⏭️ 3 tests skipped pending Iteration A.5:
  - Tag filter test (needs POST /api/journals/tags endpoint)
  - Combined filters test (NOTE + contact + date - backend returns 0 results)
  - Debug test for NOTE + contact filter (isolated reproduction of the issue)

**Acceptance Criteria**
- 🔄 New E2E tests pass consistently locally and in CI (12/15 passing, 3 skipped pending Iteration A.5).
- ✅ Failures in backend filter logic are surfaced via these tests.
- 🔄 All journal list filters and search options exercised at least once in E2E (partial - date, contact done; tag, combined, calendar, parent, search pending).


### 4.3 Iteration C – Contact Page Parent/Child Hierarchy UI

**Scope**
- Update the contact detail journals section to respect journal hierarchy,
  while preserving existing relationship-type grouping (PARTICIPANT, ABOUT, etc.).

**Key Tasks**
- Adjust the contact-page journals query/transform so that:
  - Root journals (no parent) are shown at the top level.
  - Child journals are nested under their parent journal.
- Add basic expand/collapse behaviour for parent rows when children exist.
- Ensure sorting rules remain sensible (e.g. parents by date, children grouped
  with their parent).
- Keep visual design consistent with current journals section.

**Acceptance Criteria**
- For a contact with parent and child journals, the UI displays a hierarchical
  tree rather than a flat list.
- Collapsing/expanding parents hides/shows their children only.
- Existing contact-journals tests continue to pass (or are minimally adjusted
  to account for the new layout while preserving their intent).


### 4.4 Iteration D – Contact Page Hierarchy E2E Coverage

**Prerequisites**
- Iteration C complete and merged.

**Scope**
- Extend `contact-journals` Playwright specs to validate the hierarchy
  behaviour and avoid regressions.

**Key Tasks**
- Add scenarios that:
  - Create a parent journal and one or more child journals for a contact.
  - Verify that children render nested under the parent.
  - Verify expand/collapse behaviour.
  - Confirm navigation to child journal details still works correctly.

**Acceptance Criteria**
- New hierarchy-focused E2E tests pass and are stable.
- A regression in hierarchy rendering or expand/collapse behaviour would
  cause at least one E2E test to fail.


### 4.5 Iteration E – Journal Detail View E2E Enhancements

**Scope**
- Add E2E coverage for detail-view interactions that are implemented but not
  thoroughly tested.

**Key Tasks**
- Extend `journal-detail` Playwright specs to cover:
  - Adding and removing tags from a journal.
  - Adding and removing contacts on the journal (participants/about/etc.),
    within the limits of the current UI.
  - Assigning/changing the calendar for a journal.
  - Any relevant type-specific controls not yet exercised (e.g. mood rating
    interactions, event-specific fields where supported).
- Revisit and clean up any outdated comments (e.g. around search support) so
  tests and docs accurately reflect current capabilities.

**Acceptance Criteria**
- All interactive fields that are implemented in `JournalDetailView.tsx` have
  at least one passing E2E scenario.
- The journal detail E2E suite reads as an accurate, up-to-date description of
  real user workflows.

