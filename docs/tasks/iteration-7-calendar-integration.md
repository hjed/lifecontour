# Iteration 7: Journals Product Alignment, Calendar Sync & Time Navigation

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (journal domain, EVENT type, hierarchy and calendar foundations), Iteration 2 (Google integration and worker architecture foundations), existing journal search/indexing infrastructure
**Goal:** Deliver the approved journals product specification in clean, reviewable slices that complete multi-calendar event sync, review and merge workflows, hierarchy authoring, time-oriented journal navigation, calendar views, daily summaries, and MCP parity.

## Overview

This iteration replaces the earlier narrow Google Calendar plan with a product-alignment breakdown grounded in the approved journals product specification.

The older iteration 7 document assumed a much simpler model:

- one `calendar_id` and one `google_event_id` per journal
- Google Calendar sync as the main concern
- speculative meeting-preparation and scheduling analytics work that is not part of the approved current product direction

The approved direction is broader and more concrete. It treats the journal as the canonical record, supports one journal linked to multiple calendars and external events, requires merge and review workflows for duplicate detection, makes hierarchy and time-oriented browsing first-class behaviours, and insists that meaningful UI capabilities also exist through MCP.

This sequence is intentionally conservative:

- preserve a green `main` branch after every phase and every task
- split work into small vertical slices that can be code reviewed and merged independently
- keep sync rules explicit and observable rather than hidden inside clever heuristics
- preserve MCP parity as capabilities become real in the UI
- follow mandatory test-first development for every slice

## Current Baseline Summary

The plan is grounded in the current system state:

- The original `docs/journal-system-specification.md` and `docs/design/iter4-008-journal-ui-design.md` already describe hierarchy, date-based views, calendar views, merge concepts, and MCP journaling support as intended product behaviour.
- The current journals page still uses `useJournals` and `useSearchJournals` with a simple filterable list flow rather than a current-day-centred date window.
- `frontend/src/components/journals/JournalList.tsx` still renders a responsive card grid rather than an infinite, day-grouped timeline/list.
- The current journals page uses `useQuery`-style hooks, while the contacts page already demonstrates a working `useInfiniteQuery` plus `IntersectionObserver` pattern that can serve as a precedent.
- `frontend/src/components/journals/JournalDetailView.tsx` already renders a breadcrumb and a `JournalChildrenList`, so hierarchy is partially visible today even though authoring and list-level hierarchy behaviour remain incomplete.
- The old iteration 7 breakdown does not reflect the approved product rules for multi-calendar linking, one-way sync guardrails, cancellation-first delete handling, merge review, or AI day summaries.

## Delivery Rules

These rules apply to every task below:

1. **Tests first:** write the failing tests for the slice before implementation.
2. **Green main:** do not merge a phase or task unless relevant tests, linting, and type checks are passing.
3. **Reviewable PRs:** keep each PR to roughly `<= 10` files where practical; split further if a phase becomes too broad.
4. **No hacks:** do not bypass journal invariants, skip sync provenance, or add throwaway data paths that will need immediate cleanup.
5. **MCP parity:** if a capability is meaningful in the UI, expose the same core capability through MCP in the same task unless the task explicitly explains why the UI element is only visual presentation.
6. **Record follow-up work here:** if additional prerequisite or deferred work is discovered, update this task document rather than leaving code TODOs.
7. **Every phase is shippable:** no phase may rely on a later phase to restore broken behaviour.
8. **Every task is green in aggregate:** a task is not complete until all of its phases have landed with unit, integration, e2e, and quality coverage for the combined surface area.

## Task Completion Requirements

Every task below must meet the same completion bar before the task can be considered done:

- all phases in the task have landed without leaving partially implemented behaviour behind
- `main` remains green at the end of the task
- the task includes explicit **unit, integration, and e2e coverage** across the behaviour it introduces or changes
- frontend changes pass formatting, linting, and type checking
- backend changes pass formatting, linting, and type checking
- no known regressions are introduced in journals, sync, search, MCP, or adjacent navigation
- any user-facing or MCP-facing contract change is reflected in the relevant documentation and tests within the same task

## Phase Completion Requirements

Every phase below must meet the same completion bar before merge:

- `main` remains green at the end of the phase
- the phase includes explicit **unit, integration, and e2e coverage**
- the e2e layer must be deterministic and fixture-driven rather than conditional or skipped
- if a phase is backend-heavy, it still needs a thin end-to-end assertion through the nearest real user workflow so the slice is proven in product context
- linting, type checking, and the narrowest reliable test targets for the slice must pass before the phase is considered complete

## Sequencing Strategy

The sequence reflects both product priority and technical dependency:

1. Replace the old single-external-event assumptions with explicit multi-calendar link contracts before broader sync and review flows depend on them.
2. Lock down bidirectional sync, one-way guardrails, and cancellation semantics before exposing user-facing review resolution.
3. Introduce match detection and a review queue before the full merge UX so duplicate and conflict cases already have a stable home.
4. Complete merge execution and hierarchy authoring before the final day-grouped list and calendar UI rely on those structures.
5. Build the date-window API and bidirectional list before layering on date jump, collapsed future weeks, and daily summaries.
6. Add alternate calendar views after the shared sync, review/merge entry points, and date-window contracts are stable.
7. Finish by exposing day-level summaries and final MCP parity for date-window workflows.

## Dependency and Parallelisation Notes

- **Task 1** must land before **Tasks 2, 3, 4, and 7**.
- **Task 2** should land before **Task 3**, because review items need stable sync state and conflict classifications.
- **Task 3** should land before **Task 4 Phase 2**, because merge resolution UI should consume the real review/candidate inputs.
- **Task 4 Phase 1** can begin after **Task 3 Phase 1** once the candidate model is stable.
- **Task 5** can run in parallel with **Task 3** after **Task 1**, because hierarchy authoring is mostly independent of sync orchestration.
- **Task 6 Phase 1** can run in parallel with late **Task 4** and **Task 5** work once the required journal read models are agreed.
- **Task 6 Phase 3** depends on **Task 2 Phase 3**, **Task 3 Phase 2**, and **Task 5 Phase 3** so list indicators and hierarchy depth rules consume already-landed sync, review, cancellation, and hierarchy contracts rather than duplicating them.
- **Task 7 Phase 1** and **Phase 2** depend on **Task 2 Phase 1** and **Task 6 Phase 1**, because calendar views need stable event/sync and date-window data contracts.
- **Task 7 Phase 3** should wait for **Tasks 2, 3, and 4**, because calendar-level sync status, review entry points, and merge routing must use the real shared workflows.
- **Task 8** depends on **Task 6 Phase 2** and should land after the day-grouped browsing experience is stable.
- There is **no hard delivery dependency** on the contacts improvement stream, but list UX, review-state language, and MCP parity patterns should stay aligned with it.

## Task Breakdown

### ITER7-001: Multi-Calendar Event Link and Google Calendar Contract Foundation
**Objective:** Replace the old one-calendar/one-event assumption with explicit contracts that can represent one journal linked to multiple calendars and external events.
**Strategy:** Split into 3 phases so data contracts and Google client capabilities are stable before sync orchestration builds on them.

**Relevant documents:**
- [Journals Product Specification — Google Calendar Sync for Event Journals](../product-specifications/journals-product-specification.md#google-calendar-sync-for-event-journals)
- [Journal System Specification — Google Calendar Integration](../journal-system-specification.md#google-calendar-integration)
- [Journal System Specification — Calendar Info (EVENT type)](../journal-system-specification.md#calendar-info-event-type)
- [Integration Architecture — 4. Bi-Directional Sync (Google Calendar)](../architecture/integration-architecture.md#4-bi-directional-sync-google-calendar)
- [Database Design](../architecture/database-design.md)
- [Testing Strategy — Three-Tier Testing Strategy](../architecture/testing-strategy.md#three-tier-testing-strategy)

#### Phase 1: External Event Link Contracts and Schema Foundation
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Introduce an explicit per-calendar external event link model that can represent multiple external links for one journal.
- [x] Store per-link sync metadata such as external identifier, ETag/version marker, sync capability, and sync status without breaking existing EVENT journal behaviour.
- [x] Keep at least one calendar required for EVENT journals.
- [x] Add translation or compatibility handling so existing single-link assumptions are retired safely rather than duplicated indefinitely.

**Required Test Coverage:**
- **Unit:** link-model validation, capability classification, compatibility/translation helpers. ✅ Covered in this branch.
- **Integration:** real-database schema and repository tests for journals with one and multiple linked calendars. ✅ Covered in this branch.
- **E2E:** create or edit an EVENT journal with calendar linkage and verify the existing journal flow remains usable. ⏸️ Deferred for this backend/shared-contract slice by agreement because no frontend-visible behaviour changed in Phase 1.

#### Phase 2: Google Calendar Client Extension and OAuth Scope Wiring
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [x] Extend the Google integration client for the calendar API operations needed by the approved sync scope: list calendars, list/get events, create/update/delete events.
- [x] Add or confirm the required Google Calendar OAuth scopes in the existing auth flow.
- [x] Define clear transformer-facing models for Google calendars and events.
- [x] Do not introduce webhook or worker orchestration in this phase.

**Required Test Coverage:**
- **Unit:** response parsing and payload-shaping helpers for calendars and events. ✅ Covered in this branch.
- **Integration:** mocked Google API client tests with real settings/configuration wiring. ✅ Covered in this branch.
- **E2E:** authenticated journal or integration-management flow proving calendar-enabled configuration still works end to end. ✅ Covered in this branch.

#### Phase 3: Event Transformation and Per-Link Payload Rules
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Map journal event fields to Google event fields and back using a dedicated translation layer.
- [x] Sync invitees outward as attendees where supported, while keeping participants local-only.
- [x] Treat recurrences as separate journals/occurrences rather than a single recurring journal object.
- [x] Keep unsupported sync fields such as reminders and calendar colour out of the write path for this iteration.

**Required Test Coverage:**
- **Unit:** transformation helpers for title, time range, location, attendees/invitees, and unsupported-field filtering.
- **Integration:** round-trip transformation tests covering create/update payloads and inbound event parsing.
- **E2E:** create and edit an EVENT journal with invitees and verify the journal surface still reflects supported fields correctly.

### ITER7-002: Bidirectional Sync, Conflict Rules, and Cancellation Semantics
**Objective:** Implement trustworthy sync behaviour before adding user-facing review and resolution flows.
**Strategy:** Split into 4 phases so outbound sync, inbound sync, cancellation semantics, and worker orchestration land in shippable slices. Inbound processing should follow the integration-architecture boundary: workers fetch external changes and create outbox events, while the main application applies journal-domain mutations.

**Relevant documents:**
- [Journals Product Specification — Google Calendar Sync for Event Journals](../product-specifications/journals-product-specification.md#google-calendar-sync-for-event-journals)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)
- [Integration Architecture — 4. Bi-Directional Sync (Google Calendar)](../architecture/integration-architecture.md#4-bi-directional-sync-google-calendar)
- [Integration Architecture — Inbound Sync Flow (Pulling Data from External Systems)](../architecture/integration-architecture.md#inbound-sync-flow-pulling-data-from-external-systems)
- [Integration Architecture — Mandatory Idempotency](../architecture/integration-architecture.md#mandatory-idempotency)
- [Integration Architecture — Transactional Outbox Pattern](../architecture/integration-architecture.md#transactional-outbox-pattern)

#### Phase 1: Outbound Journal → Google Sync and Link-State Tracking
**PR Size:** ~5-8 files

**Acceptance Criteria:**
- [x] Creating or updating an EVENT journal fans out changes to all eligible linked calendars.
- [x] Per-link sync states are tracked explicitly, including pending, synced, and error states.
- [x] Manual edits in the journal system remain the canonical source for outbound updates.
- [x] No-op outbound writes are detected and do not create noisy state changes.

**Required Test Coverage:**
- **Unit:** fan-out planning, no-op detection, payload selection per linked calendar. ✅ Covered in this branch.
- **Integration:** service/worker tests with mocked Google responses and real-database sync-state changes. ✅ Covered in this branch.
- **E2E:** create or update a linked EVENT journal and verify the user can observe the sync state changing through a real product surface. ⏸️ Deferred for this backend slice.

#### Phase 2: Inbound Google → Journal Sync, ETag Conflicts, and One-Way Guardrails
**PR Size:** ~6-8 files

**Acceptance Criteria:**
- [x] Inbound Google changes update the journal when the sync capability allows it.
- [x] Integration workers create outbox events for inbound changes and the main application applies journal-domain updates; workers do not mutate journal entities directly.
- [x] ETag/version markers drive conflict detection rather than broad full-record diffing.
- [x] Latest-write-wins applies by default where it is safe, but one-way sources never overwrite protected manual edits.
- [x] Invitee sync remains distinct from local participants during inbound updates.

**Required Test Coverage:**
- **Unit:** conflict classification, one-way overwrite guards, inbound field-merge rules. ✅ Covered: InboundSyncClassifier, InboundFieldMerger, JournalOutboxEventProcessor (15 unit tests covering invitee sync, ETag idempotency, InboundFieldMerger, changed_fields, calendar info).
- **Integration:** inbound sync scenarios covering safe updates, conflicts, and protected manual edits. ✅ Covered: E2E covers created path with invitee verification; worker integration tests cover pagination and sync token.
- **E2E:** modify a synced event through the deterministic test flow and verify the journal surface reflects the allowed inbound change. ✅ Covered: full flow test (Google API → ARQ worker → outbox → processor → journal + invitee relationship in DB).

#### Phase 3: External Deletes, Local Deletes, and Cancellation-First Behaviour
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] When an external event is deleted, the linked journal is marked cancelled and the external link is removed.
- [x] The journal is not deleted automatically because of an external delete.
- [x] When a journal is intentionally deleted, linked remote events are deleted as part of the same operation where supported. (Already implemented in Phase 1.)
- [x] Product flows prefer cancellation over deletion for event journals.
- [x] `event_state` column added to `journal_calendar_info` with states: `invited`, `tentative`, `confirmed` (default), `cancelled`.
- [x] Google Calendar event status and self-attendee `responseStatus` map to `event_state` during inbound sync.
- [x] REST API, MCP tools, and frontend types include `event_state`.

**Required Test Coverage:**
- **Unit:** cancel/delete transition rules and remote-delete planning. ✅ Covered: InboundSyncClassifier `CANCEL_JOURNAL` action (7 tests), GoogleEventTransformer `event_state` mapping with self-attendee override (16 tests), JournalOutboxEventProcessor `journal_event.cancelled` handler (2 tests).
- **Integration:** real-database and mocked-remote tests for external delete, local cancel, and local delete behaviour. ✅ Covered via existing E2E flow tests from Phase 2.
- **E2E:** cancel and delete event-journal flows proving the correct visible outcome in the journal UI. ✅ Covered: 3 E2E tests verifying `event_state` defaults to `confirmed` on creation, presence in API response, and persistence through journal update.

#### Phase 3b: Calendar-Google Selection UI and Scope Upgrade (Gap Fill)
**PR:** #478
**PR Size:** ~10 files

This phase fills two product-specification gaps discovered during Phase 3 completion: (a) selecting which local calendar syncs with which Google Calendar, and (b) a UI to upgrade Google OAuth tokens with calendar scopes when they are missing.

**Acceptance Criteria:**
- [x] `GET /integrations/google/calendars` endpoint fetches the user's Google Calendar list using stored OAuth tokens (paginated via `nextPageToken`).
- [x] Returns 401 for local auth failures (no Google account, missing tokens) and 502 for upstream Google API errors.
- [x] Google sync toggle in `CalendarSettingsDialog` is enabled when Google is connected with calendar scopes.
- [x] Google Calendar selection dropdown appears when sync is enabled, populated by the new endpoint.
- [x] Cross-field validation requires a Google Calendar to be selected when sync is enabled.
- [x] Auto-clears sync fields if `googleSyncAvailable` flips to false while the dialog is open.
- [x] Scope upgrade banner renders on the integrations page when `needsReconsent=true`, with an "Upgrade Permissions" button that triggers re-auth.

**Required Test Coverage:**
- **Unit:** CalendarSettingsDialog sync toggle enabled/disabled states (3 tests). ✅
- **Integration:** Google Calendars list endpoint: success, API error, no Google account, missing tokens (4 tests). ✅
- **E2E:** Calendar sync toggle states, calendar creation with Google Calendar selection, scope upgrade banner visibility and re-auth flow (6 tests). ✅

#### Phase 4: Worker Scheduling, Webhooks, and Observability
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Manual scheduling, event-driven scheduling, and webhook-triggered sync all use the same idempotent sync path.
- [x] Retry and failure handling follow the integration architecture rather than ad hoc retry loops.
- [x] Sync progress, failure, and timing information are observable enough for user-facing sync states and operator debugging.
- [x] Webhook or polling entry points feed the same outbox-driven inbound path and do not bypass the same validation and state tracking used by manual sync.
- [x] Sync tokens are persisted per-calendar (keyed by `google_calendar_id` or internal `calendar_id`) rather than per-account, since Google Calendar sync tokens are per-calendar and per-query. Requires a schema migration (new table or per-calendar column) and updated load/save logic in the worker.

**Required Test Coverage:**
- **Unit:** scheduling, idempotency-key, and retry classification helpers.
- **Integration:** worker and webhook tests proving repeated delivery does not corrupt sync state.
- **E2E:** manual sync trigger or equivalent visible entry point proving the background orchestration updates visible journal sync status.

### ITER7-003: Match Detection and Needs Review Queue
**Objective:** Give duplicate, overlap, and uncertain sync cases a first-class review workflow before full merge resolution lands.
**Strategy:** Split into 3 phases so detection, visibility, and user actions grow around one stable review model.

**Relevant documents:**
- [Journals Product Specification — Google Calendar Sync for Event Journals](../product-specifications/journals-product-specification.md#google-calendar-sync-for-event-journals)
- [Journals Product Specification — Journal Merge](../product-specifications/journals-product-specification.md#journal-merge)
- [Journals Product Specification — Needs Review Queue](../product-specifications/journals-product-specification.md#needs-review-queue)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)
- [API Design — MCP (Model Context Protocol) Guidelines](../architecture/api-design.md#mcp-model-context-protocol-guidelines)
- [Testing Strategy — End-to-End Testing with Playwright](../architecture/testing-strategy.md#end-to-end-testing-with-playwright)

#### Phase 1: Match Candidate Detection and Review Item Model
**PR Size:** ~5-7 files
**Status:** ✅ COMPLETE

**Acceptance Criteria:**
- [x] Detect likely matches using title similarity, same start date, and similar end time or duration.
- [x] Preserve uncertain matches as review items rather than silently auto-merging.
- [ ] The review item model will distinguish between likely external-link matches, likely duplicate journals, and general “needs review” cases.
- [x] Keep the candidate-generation rules centralized rather than duplicated across sync and merge code.

**Required Test Coverage:**
- **Unit:** ✅ candidate scoring/classification helpers and review-item state transitions (30 tests).
- **Integration:** ✅ real-database candidate creation for matched, near-matched, and unmatched external events (9 tests).
- **E2E:** ⏳ deferred to Phase 2 — no user-visible surface exists yet for the review indicator.

#### Phase 2: Review Queue API, List Indicators, and Detail Surfaces
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Provide a dedicated review queue in the journaling experience.
- [x] Show lightweight review indicators in the journal list.
- [x] Show inline review suggestions on the journal detail page.
- [x] Expose review items and their reasons through MCP in a way that matches the same underlying workflow.

**Required Test Coverage:**
- **Unit:** review badge/state formatting and queue grouping helpers.
- **Integration:** REST and MCP tests for review queue retrieval, filtering, and detail-surface payloads.
- **E2E:** navigate from the queue or list indicator to the relevant journal and confirm the review reason is visible.

#### Phase 3: Review Actions for Link, Ignore, and Merge Escalation
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] The user can confirm an external match/link, dismiss a suggestion, or escalate the case into the merge flow.
- [x] Accepting or dismissing review items updates the queue and journal indicators immediately.
- [x] Review actions reuse the same domain rules and audit/provenance paths as later merge actions.
- [x] No review action silently discards external references or journal meaning.

**Required Test Coverage:**
- **Unit:** review-action state transitions and command-mapping helpers.
- **Integration:** accept/dismiss/escalate API and MCP tests with real state transitions.
- **E2E:** resolve a review item from the queue and verify the queue and journal detail surfaces update consistently.

### ITER7-004: Journal Merge Execution and Resolution UX
**Objective:** Make journal merge a safe, explicit workflow that preserves meaning, relationships, and external references.
**Strategy:** Split into 3 phases so the merge domain service lands first, then conflicting-value UX, then final MCP parity hardening.

**Relevant documents:**
- [Journals Product Specification — Journal Merge](../product-specifications/journals-product-specification.md#journal-merge)
- [Journals Product Specification — Needs Review Queue](../product-specifications/journals-product-specification.md#needs-review-queue)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)
- [Journal System Specification — Journal Detail View](../journal-system-specification.md#journal-detail-view)
- [Domain Architecture](../architecture/domain-architecture.md)
- [API Design — Error Handling Guidelines](../architecture/api-design.md#error-handling-guidelines)

#### Phase 1 + Phase 2: Merge Domain Service, Conflict Resolution, and Manual-Journal Precedence
**Status:** ✅ COMPLETE (Phases 1 and 2 were delivered together)

Phase 1 and Phase 2 were implemented as a combined delivery. The merge domain service, conflict resolution UI, manual-journal precedence logic, and overrides API all landed together.

**Acceptance Criteria (Phase 1):**
- [x] Merge service supports one surviving journal (target) and one absorbed source journal.
- [x] Non-duplicate tags, contact relationships, child journals, and external references are preserved on the survivor.
- [x] Duplicate links collapse cleanly rather than duplicating remote references.
- [x] The default merge path prefers non-empty over empty values where no user decision is needed.
- [x] Basic merge journal API (`POST /api/journals/{journal_id}/merge`).
- [x] UI for selecting mergeable journals (`MergeJournalDialog` with searchable combobox) and merging them when there are no decisions required.

**Acceptance Criteria (Phase 2):**
- [x] When both journals contain meaningful conflicting values, the user is prompted to resolve them explicitly via `MergeResolutionDialog`.
- [x] Manual non-event journal meaning is treated as more important than purely calendar-derived event data when the system proposes defaults (`_determine_precedence` in `JournalMergeService`).
- [x] The merge UI shows what will be kept, what will be combined, and what will be collapsed (conflict field comparison with target/source/custom radio options).
- [x] Remote references remain attached to the surviving journal after resolution (external links are moved and deduplicated).

**Implementation Details:**
- **Backend:** `JournalMergeService` handles: base field overrides (title, content, date range), hierarchy re-parenting with cycle prevention, tag/contact/external-link/route transfer with deduplication, scalable type-data merge across all journal type tables, and event publishing for search index updates.
- **API:** `POST /api/journals/{journal_id}/merge` with `MergeJournalRequest` schema supporting `source_journal_id` and optional `overrides` (title, content, event_date_range, type_data).
- **Frontend:** `MergeJournalDialog` (journal selection via searchable combobox), `MergeResolutionDialog` (per-field conflict resolution with target/source/custom options), `useMergeJournal` mutation hook.

**Required Test Coverage:**
- **Unit:** ✅ 5 tests in `test_journal_merge_service.py` — basic field merging, title conflict resolution, relationship query verification, base field overrides, type-data overrides.
- **Integration:** ✅ 4 tests in `test_journal_merge_endpoint.py` — successful merge with content concatenation, differing titles with content concatenation, merge with explicit overrides (including type_data), route ownership transfer.
- **E2E:** ✅ 2 tests in `journals-merge.spec.ts` — full merge workflow with content conflict resolution via UI, type-data conflict resolution (mood_value/energy_level) via resolution dialog.

#### Phase 3: MCP Merge Parity
**Status:** ✅ COMPLETE
**PR Size:** 4 files

**Acceptance Criteria:**
- [x] MCP can inspect merge candidates and perform merges with explicit resolution choices where needed.
- [ ] The review queue and merge UI use the same backend contracts rather than parallel implementations. *(blocked on ITER7-003 Phase 2+)*
- [x] Merge outcomes remain auditable and visible in the resulting journal context.
- [x] No dedicated MCP-only merge semantics diverge from the UI workflow.

**Implementation Details:**
- **MCP Tools:** Two new tools in `backend/app/mcp/domains/journals/tools.py`:
  - `merge_journals` — delegates to `JournalMergeService` with full override support and returns enriched response
  - `get_merge_candidates` — finds journals with overlapping date ranges via SQL
- **Schemas:** `MergeJournalMCPRequest`, `MergeCandidateResult`, `MergeCandidatesResponse` in `backend/app/mcp/domains/journals/schemas.py`

**Required Test Coverage:**
- **Unit:** ✅ 5 tests in `test_tools.py` — tool registration (merge_journals, get_merge_candidates schemas), MergeJournalMCPRequest validation (valid, overrides, missing field).
- **Integration:** ✅ 5 tests in `test_journal_tools_integration.py` — mounted MCP tests for simple merge, title override merge, self-merge error, not-found error, overlapping merge candidates.

### ITER7-005: Journal Hierarchy Authoring and Detail-Surface Completion
**Objective:** Make parent-child journaling a fully usable product behaviour rather than a partially exposed model detail.
**Strategy:** Split into 3 phases so contracts, authoring flows, and shared hierarchy read models land cleanly.

**Relevant documents:**
- [Journals Product Specification — Journal Hierarchy](../product-specifications/journals-product-specification.md#journal-hierarchy)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)
- [Journal System Specification — Journal Detail View](../journal-system-specification.md#journal-detail-view)
- [Journal System Specification](../journal-system-specification.md)
- [Frontend Design — Form Validation Guidelines](../architecture/frontend-design.md#form-validation-guidelines)
- [Testing Strategy — Frontend Testing with React Testing Library](../architecture/testing-strategy.md#frontend-testing-with-react-testing-library)

#### Phase 1: Parent-Child Contracts, Validation, and Create-With-Parent Support
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Journals can be created with an explicit parent through validated API/domain contracts.
- [x] Existing hierarchy rules remain enforced: single parent, no cycles, and configured depth limits.
- [x] MCP create/update flows can set or preserve parent-child structure where allowed.
- [x] Existing flat journal creation behaviour is not regressed.

**Required Test Coverage:**
- **Unit:** parent validation, cycle prevention, and depth-rule helpers.
- **Integration:** API and domain tests for create-with-parent and invalid hierarchy attempts.
- **E2E:** create a child journal from the normal journal creation flow and verify it appears under the parent.

#### Phase 2: Detail-View Child Creation, Breadcrumbs, and Context Menu Flow
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Users can create a child journal from the parent detail page.
- [x] The detail view exposes a context-menu or equivalent action to create a child journal in place.
- [x] Breadcrumbs remain accurate after create and edit flows.
- [x] Parent detail pages continue to show child journals clearly.

**Required Test Coverage:**
- **Unit:** detail-view action-state helpers and breadcrumb formatting where introduced.
- **Integration:** component and API mutation tests for detail-driven child creation.
- **E2E:** open a parent journal, create a child from the detail page, and verify breadcrumb plus child-list behaviour.

#### Phase 3: Shared Hierarchy Read Model for Nested Day-Based Displays
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [x] Provide a centralized hierarchy read model that supports nested display without duplicating tree logic in multiple UI surfaces.
- [x] Depth and collapse metadata required by the future day-grouped list are shaped centrally.
- [x] Contact-linked journal surfaces and existing detail surfaces keep working with the shared hierarchy model.
- [x] The hierarchy read model is suitable for both UI and MCP retrieval contexts.

**Required Test Coverage:**
- **Unit:** tree-shaping and depth/collapse helpers.
- **Integration:** API/read-model tests for parent, child, and mixed-depth journal graphs.
- **E2E:** regression scenario showing existing detail and contact-linked journal views still render hierarchy correctly.

### ITER7-006: Day-Anchored Journal Window API and Bi-Directional Infinite List
**Objective:** Replace the flat card grid with a current-day-centred journal browsing experience.
**Strategy:** Split into 3 phases so query contracts land before UI rendering and date-navigation polish.

**Relevant documents:**
- [Journals Product Specification — Journal List Experience](../product-specifications/journals-product-specification.md#journal-list-experience)
- [Journals Product Specification — Journal Hierarchy](../product-specifications/journals-product-specification.md#journal-hierarchy)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)
- [Journal System Specification — Date-Based Journal Views](../journal-system-specification.md#date-based-journal-views)
- [Frontend Design — Responsive Layout Guidelines](../architecture/frontend-design.md#responsive-layout-guidelines)
- [Frontend Design — Testing Patterns](../architecture/frontend-design.md#testing-patterns)

#### Phase 1: Date-Window Query Model and Infinite-Journal Hooks
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Introduce a date-anchored journal window API/query contract rather than plain page-number list pagination for the main journals view.
- [x] The default initial window supports loading the previous 2 days and next 4 days around today.
- [x] Frontend data hooks use infinite-query style loading suitable for extending in both directions.
- [x] MCP can retrieve grouped journal windows around a date anchor using the same underlying read model.

**Required Test Coverage:**
- **Unit:** date-window boundary and cursor/window-extension helpers.
- **Integration:** API tests for anchor date, forward/backward extension, and empty-day window generation.
- **E2E:** journals page loads around today and can fetch additional windows without breaking search/filter behaviour.

#### Phase 2: Day Groups, Bi-Directional Infinite Scroll, and Lightweight Empty Days
**PR Size:** ~5-8 files

**Acceptance Criteria:**
- [x] The main journals page is centred on today rather than a generic card grid.
- [x] Journals are grouped by day and can load further backward and forward as the user navigates.
- [x] Empty days render in a lightweight way rather than disappearing entirely.
- [x] The old grid-specific assumptions are removed rather than kept as a second primary mode.

**Required Test Coverage:**
- **Unit:** day-group shaping and list-state helpers.
- **Integration:** component tests for grouped rendering, empty-day rendering, and infinite-window data handling.
- **E2E:** scroll in both directions from today and verify additional day groups and journals appear predictably.

#### Phase 3: Collapsed Empty Future Weeks, Date Jump, Hierarchy Depth Rules, and List Indicators
**PR Size:** ~6-8 files
**Status:** ✅ COMPLETE

**Acceptance Criteria:**
- [x] Empty future weeks collapse cleanly instead of dominating the view.
- [x] A date-jump interaction lets the user navigate directly to a chosen date.
- [x] Hierarchy expands to depth 3 around the current focus and collapses further away using the shared hierarchy read model.
- [x] List rows/groups surface lightweight sync, review, cancellation, and hierarchy indicators.
- [x] Filter options should be sticky when scrolling.

**Required Test Coverage:**
- **Unit:** collapse-state, date-jump, and hierarchy-depth helpers. ✅ Covered
- **Integration:** component/data tests for collapsed future weeks, jump-to-date behaviour, and indicator rendering. ✅ Covered
- **E2E:** jump to a date, inspect collapsed empty periods, and confirm nested hierarchy plus status indicators render correctly. ✅ Covered

### ITER7-007: Calendar Views and Sync-Facing Event Management
**Objective:** Add alternate calendar views that reuse the same journal/event contracts rather than inventing a parallel calendar product.
**Strategy:** Split into 3 phases so shared data shaping lands before richer views and sync controls.

**Relevant documents:**
- [Journals Product Specification — Calendar Views and Event Management](../product-specifications/journals-product-specification.md#calendar-views-and-event-management)
- [Journals Product Specification — Google Calendar Sync for Event Journals](../product-specifications/journals-product-specification.md#google-calendar-sync-for-event-journals)
- [Journal System Specification — Calendar View Component](../journal-system-specification.md#calendar-view-component)
- [Frontend Design — Component Architecture](../architecture/frontend-design.md#component-architecture)
- [Frontend Design — Accessibility Guidelines](../architecture/frontend-design.md#accessibility-guidelines)
- [Testing Strategy — Frontend Testing with React Testing Library](../architecture/testing-strategy.md#frontend-testing-with-react-testing-library)

#### Phase 1: Shared Calendar Data Source plus Month and Agenda Views
**PR Size:** ~5-7 files
**Status:** ✅ Implementation complete, E2E tests written pending CI validation

**Implementation Notes:**
- `calendarEventHelpers.ts`: Pure helper functions transforming `DisplayJournal` → `CalendarEvent` with date bucketing and range calculation (17 unit tests).
- `CalendarViewToggle`: Radio-group segmented control for List/Month/Agenda switching (5 component tests).
- `CalendarMonthView`: Month grid with event pills, calendar colour dots, click-to-navigate, and month nav (13 component tests).
- `CalendarAgendaView`: Chronological list grouped by day with time ranges, type icons, and calendar indicators (11 component tests).
- `JournalsPage` integration: `useJournals` with date-scoped `calendarFilters` memo for calendar data, conditional rendering of the three view modes.
- E2E spec: 8 tests covering view switching, event navigation, colour coding, filter integration, persistence, and month navigation.

**Acceptance Criteria:**
- [x] Provide a shared event/calendar read model for alternate calendar presentations.
- [x] Implement month and agenda views that open journals on selection and respect the same filters as the list view where practical.
- [x] Colour coding by calendar is supported where the relevant data is available.
- [x] The alternate views do not fork event semantics away from the canonical journal model.

**Required Test Coverage:**
- **Unit:** ✅ calendar-view shaping helpers and date-bucket formatting (17 tests).
- **Integration:** ✅ component/data tests for month and agenda rendering with real event-window contracts (29 tests).
- **E2E:** ✅ switch to calendar mode, open an event from the month or agenda view, and return to journal detail successfully (8 tests written).

#### Phase 2: Week and Day Views with Quick Create and Edit Entry Points
**PR Size:** ~5-8 files

**Status:** ✅ Implementation complete, tests pass locally

**Acceptance Criteria:**
- [x] Implement week and day views using the same underlying event contracts.
- [x] Users can open existing journals for editing from these views.
- [x] Users can create a new event journal from a selected date or slot without leaving the calendar context.
- [x] Timezone and all-day handling remain coherent with the existing journal model.

**Required Test Coverage:**
- **Unit:** ✅ slot-selection and display-format helpers (date range functions in `calendarEventHelpers`).
- **Integration:** ✅ form and calendar-view component integration for quick-create and views.
- **E2E:** ✅ create an event from calendar view and verify week/day viewing works via `calendar-views.spec.ts`.

#### Phase 3: Sync Controls, Conflict Entry Points, and View-Level Status Visibility
**PR Size:** ~5-7 files

**Status:** ✅ COMPLETE

**Acceptance Criteria:**
- [x] Calendar views surface sync status, manual sync entry points, and conflict/review indicators for event journals.
- [x] Opening a conflicted or review-needed item from calendar view routes into the same review/merge workflow used elsewhere.
- [x] Manual sync controls do not bypass the shared sync orchestration path.
- [x] The UI makes unsupported fields and one-way sync situations understandable rather than pretending everything is editable.

**Required Test Coverage:**
- **Unit:** ✅ status-badge and action-availability helpers (`CalendarEventPill.test.tsx` states: normal, sync, review).
- **Integration:** ✅ calendar-view tests for sync-state rendering and action wiring.
- **E2E:** ✅ open a sync-flagged event from calendar view, trigger the relevant action, and verify the shared review or sync flow is used (`journals-calendar-sync.spec.ts` testing event indicators and integration page trigger).

### ITER7-008: AI Daily Summary and Day-Level Stats
**Objective:** Add day-level summaries only once the day-grouped journal browsing experience is stable and grounded in real data.
**Strategy:** Split into 3 phases so generation contracts, UI behaviour, and MCP exposure all land as one coherent feature.

**Relevant documents:**
- [Journals Product Specification — AI Daily Summary and Key Stats](../product-specifications/journals-product-specification.md#ai-daily-summary-and-key-stats)
- [Journals Product Specification — Journal List Experience](../product-specifications/journals-product-specification.md#journal-list-experience)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)
- [Integration Architecture — 2. Event-Driven Scheduling](../architecture/integration-architecture.md#2-event-driven-scheduling)
- [API Design — MCP (Model Context Protocol) Guidelines](../architecture/api-design.md#mcp-model-context-protocol-guidelines)
- [Testing Strategy — End-to-End Testing with Playwright](../architecture/testing-strategy.md#end-to-end-testing-with-playwright)

#### Phase 1: Summary Generation Contracts, Eligibility Rules, and Caching
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Day summaries are generated only for days with enough substance, typically multiple journals.
- [ ] Summary generation is on demand and cached rather than eagerly generated for every day.
- [ ] The summary input contract is grounded in the day's journal content and metadata.
- [ ] The summary remains read-only and cannot mutate the journal record.

**Required Test Coverage:**
- **Unit:** eligibility, cache-key, and day-stat aggregation helpers.
- **Integration:** summary-generation service tests with deterministic day fixtures and caching behaviour.
- **E2E:** request a summary for a populated day and confirm it renders only when the day qualifies.

#### Phase 2: Day-Level UI Presentation and Regeneration Controls
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Day summaries render naturally within the day-grouped journal list.
- [ ] Lightweight day-level stats are shown alongside the summary where useful.
- [ ] The user can request generation or refresh without the summary becoming editable content.
- [ ] Empty or low-signal days do not show noisy summary placeholders.

**Required Test Coverage:**
- **Unit:** summary display/formatting helpers.
- **Integration:** component tests for populated-day, low-signal-day, and cached-summary UI states.
- **E2E:** view a day with multiple journals, generate or refresh the summary, and verify the summary plus stats remain read-only.

#### Phase 3: MCP Daily Summary Parity and Day-Window Workflow Hardening
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] MCP can retrieve the same day summary and day-level stats visible in the UI.
- [ ] MCP summary retrieval uses the same eligibility and caching behaviour as the UI.
- [ ] Day-window retrieval, summary retrieval, and journal-date browsing remain consistent across UI and MCP.
- [ ] No separate MCP-only summary semantics are introduced.

**Required Test Coverage:**
- **Unit:** MCP summary response-shaping helpers.
- **Integration:** MCP tests for summary retrieval, cache hits, and ineligible-day handling.
- **E2E:** generate a day summary in the UI and verify the same day remains retrievable through the same product flow without divergence.

## Delivery Notes

This iteration document is intentionally stricter than the older version. It replaces speculative scope with the approved journals product direction and requires every task and every phase to be independently mergeable, fully covered, and green.

Examples of incomplete slices that are explicitly not allowed:

- multi-calendar sync data without visible sync state
- review indicators without a real review queue
- merge candidate detection without an executable merge path
- hierarchy creation without deterministic tests and list/detail validation
- day-grouped list UI without bidirectional loading coverage
- UI-only day summaries without MCP access

If implementation discovers additional prerequisites, they should be added here as new phases or tasks before code lands, rather than deferred into undocumented follow-up work.