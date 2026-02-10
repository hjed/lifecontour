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


### 4.2 Iteration B – Journals List E2E Filter & Search Coverage

**Status:** 🔄 IN PROGRESS - Tests Added, Needs Verification

**Prerequisites**
- Iteration A complete and merged.

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
  - ✅ Tag filter limiting list to journals with a given tag.
  - ⬜ Calendar filter limiting list to a specific calendar.
  - ⬜ Parent filter (e.g. only root journals vs children of a given parent).
- ⬜ Add E2E tests for search scenarios:
  - ⬜ Simple full-text search by title/content.
  - ⬜ Search combined with one or more filters (type, contact, date), verifying
    results match the intersection.
- ✅ Add E2E test for combined filters (date + type + contact)
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

**Acceptance Criteria**
- ⬜ New E2E tests pass consistently locally and in CI.
- ✅ Failures in backend filter logic are surfaced via these tests.
- 🔄 All journal list filters and search options exercised at least once in E2E (partial - date, contact, tag, combined done; calendar, parent, search pending).


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

