# Iteration 2.6: Contacts Product Alignment & Intelligence

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 2 (Google integration foundation), Iteration 2.5 (interactive contact editing foundation), existing contact search/indexing infrastructure
**Goal:** Deliver the approved contacts product specification in clean, reviewable slices that build on the current contacts UI, Google Contacts sync, MCP tools, search, relationships, and activity foundations.

## Overview

This iteration turns the current partial contacts implementation into a coherent product. The codebase already has core contacts, tags, favourites, a contact detail view, MCP contact tools, Google Contacts sync foundations, MeiliSearch-backed search, and a field-level activity history service. The work here should extend those foundations rather than replace them.

The sequence below is intentionally conservative:
- preserve a green `main` branch after every task
- keep PRs reviewable by splitting large tasks into small vertical slices
- prefer translation layers and incremental schema changes over disruptive rewrites
- maintain AI-first parity so meaningful user-facing capabilities are also exposed through MCP
- follow mandatory test-first development for every slice

## Current Baseline Summary

The implementation plan is grounded in the current system state:

- `update_contact` in MCP already supports tag updates and can create missing tags by name; dedicated add/remove tag tools are not needed.
- The REST API already exposes contact and tag operations, but current tag hierarchy support is incomplete in API contracts and UI behaviour.
- The sidebar already renders tags, but only as a flat list.
- `/contacts/tags/[id]` already exists, but behaves like a specific tag page rather than the main contact list with inherited child-tag filtering.
- The contact detail page already has a responsive multi-column layout, but important information still sits too low and desktop space is under-used.
- Relationships already exist between contacts, but cannot yet point to the user.
- Search endpoints and MeiliSearch infrastructure already exist, but the top search component still relies on mock-style suggestions and incomplete navigation.
- Google Contacts import/export foundations already exist, including memberships-to-tags transformation, favourites handling, ETag-based sync metadata, and local push detection.
- Contact history already records field-level changes, but does not yet model richer provenance or summary-regeneration activity.

## Delivery Rules

These rules apply to every task below:

1. **Tests first:** write the failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks are passing.
3. **Reviewable PRs:** keep each PR to roughly `<= 10` files where practical; split tasks into smaller slices if needed.
4. **No hacks:** do not bypass domain validation, skip provenance, or introduce temporary parallel data paths that will need immediate cleanup.
5. **MCP parity:** if a capability is meaningful in the UI, explicitly decide whether it must also be exposed through MCP in the same task.
6. **Record follow-up work here:** if a prerequisite or deferred enhancement is discovered mid-task, update this task document rather than leaving code TODOs.
7. **Every phase is shippable:** no phase may rely on a later phase to restore broken behaviour.

## Phase Completion Requirements

Every phase below must meet the same completion bar before merge:

- `main` remains green at the end of the phase.
- No known regressions are introduced in contacts, sync, search, MCP, or surrounding navigation.
- The phase includes explicit **unit, integration, and e2e coverage**.
- The e2e layer must be real and deterministic, not conditional or skipped based on fixture state.
- If a phase is backend-heavy, it still needs a thin end-to-end assertion through the nearest real user workflow (for example integrations UI, contacts UI, or search UI) so the slice is proven in product context.
- Linting, type checking, and the narrowest reliable test targets for the slice must pass before the phase is considered complete.

## Sequencing Strategy

The sequence reflects both user priority and technical dependency:

1. Lock down Google tag sync semantics before expanding local tag hierarchy behaviour.
2. Add hierarchical tag support to filtering and navigation before polishing tag editing UX.
3. Complete tag management across UI and MCP before adjusting page layout that depends on those surfaces.
4. Add important dates and relationships-to-user before AI summary generation, because both are required context inputs.
5. Build AI summary generation and search signals before wiring the final top-search UX.
6. Finish with provenance-aware activity feed work once sync and summary events have stable source metadata.

## Dependency and Parallelisation Notes

- **Task 1** must land before **Tasks 2 and 3**.
- **Task 2** should land before **Task 3**, because the tag editing UX depends on stable hierarchy/filter semantics.
- **Task 4** can run in parallel with **Task 5** once **Task 3** is stable.
- **Tasks 5 and 6** can run in parallel.
- **Task 7** depends on **Tasks 5 and 6**.
- **Task 8** should wait for **Task 7** so the user-facing search experience consumes the final ranking inputs.
- **Task 9** should wait for **Task 7** and the sync provenance work introduced earlier, otherwise the activity schema/UI will likely be reworked twice.

## Task Breakdown

### ITER2.6-001: Google Contacts Tag Sync Semantics Foundation
**Objective:** Make Google group/tag sync predictable before extending local tag behaviour further.
**Strategy:** Split into 3 phases so the sync rules are locked down before hierarchy and UX work build on them.

**Relevant documents:**
- [Contacts Product Specification — Google Contacts Sync for Tags](../product-specifications/contacts-product-specification.md#google-contacts-sync-for-tags)
- [Contacts Product Specification — Contact Tags](../product-specifications/contacts-product-specification.md#contact-tags)
- [Integration Architecture — Two-Way Sync (Google Contacts)](../architecture/integration-architecture.md#1-two-way-sync-google-contacts)
- [Integration Architecture — Inbound Sync Flow (Pulling Data from External Systems)](../architecture/integration-architecture.md#inbound-sync-flow-pulling-data-from-external-systems)
- [Testing Strategy — Three-Tier Testing Strategy](../architecture/testing-strategy.md#three-tier-testing-strategy)

#### Phase 1: Reserved Group Rules and Name Translation
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [x] Define backend-configurable reserved Google group rules.
- [x] Ignore `My Contacts` and map `Starred` to favourites.
- [x] Introduce a dedicated translation layer for Google group naming, without relaxing internal `TagName` validation (hierarchical `/` handling will be deferred to ITER2.6-002).
- [x] Add explicit fixtures/examples for reserved, ordinary, and hierarchical group names so later phases reuse the same rules.

**Required Test Coverage:**
- [x] **Unit:** translation helpers, reserved-group filtering, favourite mapping.
- [x] **Integration:** worker/transformer configuration wiring using real settings and fixtures.
- [x] **E2E:** sync-trigger flow proving reserved groups do not surface as ordinary tags and `Starred` still surfaces as favourite behaviour.

#### Phase 2: Google → Local Membership Semantics
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Importing ordinary Google groups creates or matches local tags consistently.
- [x] Group removals in Google remove the corresponding local tag assignment.
- [x] Favourite handling continues to work alongside tag membership import.
- [x] Slash-path inputs are normalised through the translation layer rather than leaking raw sync names into unrelated code.

**Required Test Coverage:**
- [x] **Unit:** membership-to-tag mapping, add/remove semantics, matching rules.
- [x] **Integration:** real-database import scenarios covering created, updated, and removed memberships.
- [x] **E2E:** end-to-end sync scenario showing imported group changes reflected in the contacts UI.

#### Phase 3: Local → Google Push, Conflicts, and Provenance Scaffolding
**PR Size:** ~5-8 files

**Acceptance Criteria:**
- [x] Local tag changes push back to Google where supported.
- [x] Conflict handling preserves local-wins behaviour using the existing ETag/version-hash flow.
- [x] Sync-origin metadata needed by the future activity feed is captured without exposing half-finished UI.
- [x] No-op exports do not create user-visible change entries.

**Required Test Coverage:**
- [x] **Unit:** push payload shaping, conflict classification, no-op detection.
- [x] **Unit:** provenance tracking (`changed_by` passthrough from outbox to history service).
- [x] **Integration:** mocked Google API push/conflict scenarios with real database metadata updates.
- [x] **E2E:** trigger a local tag change and verify the sync workflow completes without regressing visible contact state.

### ITER2.6-002: Hierarchical Tags in Domain, API, Filtering, and Sidebar
**Objective:** Make tag hierarchy a real product capability instead of a partial data model detail.
**Strategy:** Split into 3 phases so hierarchy semantics land before navigation and list UX changes.

**Relevant documents:**
- [Contacts Product Specification — Contact Tags](../product-specifications/contacts-product-specification.md#contact-tags)
- [Contacts Product Specification — Google Contacts Sync for Tags](../product-specifications/contacts-product-specification.md#google-contacts-sync-for-tags)
- [Domain Architecture — Contacts Domain](../architecture/domain-architecture.md#contacts-domain)
- [Domain Architecture — Contacts Domain Adapters](../architecture/domain-architecture.md#contacts-domain-adapters)
- [API Design — Pagination Guidelines](../architecture/api-design.md#pagination-guidelines)
- [Frontend Design — Responsive Layout Guidelines](../architecture/frontend-design.md#responsive-layout-guidelines)

#### Phase 1: Hierarchy Contracts and Descendant Filtering
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Tags can have one parent and that relationship is exposed consistently through backend schemas and frontend types.
- [ ] Update `TagName` validation to support `/` as the delimiter for hierarchical tags.
- [ ] Descendant resolution is implemented centrally rather than duplicated across API, MCP and UI.
- [ ] Filtering by a parent tag includes contacts assigned to descendant tags.
- [ ] Existing flat-tag behaviour continues to work for tags without parents.

**Required Test Coverage:**
- **Unit:** parent/child validation, descendant resolution, filter expansion logic.
- **Integration:** API filtering with parent tags, child-only assignments, and mixed favourite/search filters.
- **E2E:** contacts list scenario proving a parent-tag filter returns child-tag-only contacts.

#### Phase 2: Nested Sidebar Navigation
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] The sidebar renders tags as a nested tree.
- [ ] Deeper levels are expandable/collapsible instead of always fully expanded.
- [ ] The sidebar remains usable when there are no child tags and when several sibling tags exist.
- [ ] Existing non-tag navigation items are not regressed.

**Required Test Coverage:**
- **Unit:** tree-shaping helpers for nested sidebar data.
- **Integration:** frontend data-fetch and type-contract tests against hierarchical responses.
- **E2E:** sidebar expansion/collapse and tag navigation from the real contacts layout.

#### Phase 3: Unify Tag Filtering with the Main Contacts List
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Clicking a tag opens the normal contacts list experience filtered to that tag tree.
- [ ] Favourites and search-within-list continue to work in filtered views.
- [ ] The existing `/contacts/tags/[id]` behaviour is either aligned with the main list flow or safely retired without broken links.
- [ ] Parent-tag filtering remains stable under pagination.

**Required Test Coverage:**
- **Unit:** query-param/state helpers for tag-filtered list state.
- **Integration:** contacts API pagination/filter combinations with tag-tree filtering.
- **E2E:** navigate from sidebar tag → filtered contacts list → pagination/search/favourite regression checks.

### ITER2.6-003: Tag Management UX and MCP Parity
**Objective:** Complete editable tag management across contact surfaces, sidebar management, and MCP.
**Strategy:** Split into 3 phases so backend safety rules land before UI flows and parity checks.

**Relevant documents:**
- [Contacts Product Specification — Contact Tags](../product-specifications/contacts-product-specification.md#contact-tags)
- [Contacts Product Specification — MCP and AI-Agent Parity](../product-specifications/contacts-product-specification.md#mcp-and-ai-agent-parity)
- [Domain Architecture — Contacts Domain](../architecture/domain-architecture.md#contacts-domain)
- [API Design — MCP (Model Context Protocol) Guidelines](../architecture/api-design.md#mcp-model-context-protocol-guidelines)
- [Frontend Design — Form Validation Guidelines](../architecture/frontend-design.md#form-validation-guidelines)
- [Testing Strategy — Frontend Testing with React Testing Library](../architecture/testing-strategy.md#frontend-testing-with-react-testing-library)

#### Phase 1: Tag CRUD, Re-parenting, and Safe Delete Rules
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Backend create/update/delete/re-parent behaviour is explicit and validated.
- [ ] Minimum editable fields are `name` and `colour`, with parent selection support.
- [ ] Deleting a tag removes it from all assigned contacts safely.
- [ ] Re-parenting does not corrupt descendant filtering behaviour.

**Required Test Coverage:**
- **Unit:** tag validation, re-parenting, cascade removal behaviour.
- **Integration:** API CRUD tests with real database state changes across contact assignments.
- **E2E:** admin-style tag CRUD flow proving create/edit/delete changes show up in the contacts UI.

#### Phase 2: Contact Editing Tag Flows
**PR Size:** ~5-8 files

**Acceptance Criteria:**
- [ ] Users can add and remove existing tags while editing a contact.
- [ ] Users can create a missing tag during contact editing without leaving the flow.
- [ ] Tag selection respects hierarchy without forcing users through a separate management page.
- [ ] Existing inline contact editing behaviours remain stable.

**Required Test Coverage:**
- **Unit:** form helpers and tag-selection state handling.
- **Integration:** API + frontend mutation flow tests for add/remove/create tag behaviour.
- **E2E:** edit a contact, add a new tag, remove a tag, and confirm the updated card/detail state.

#### Phase 3: Sidebar Tag Management and MCP Parity
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Sidebar tag management supports create, edit, re-parent, and delete actions using compact menu/modal flows.
- [ ] MCP `update_contact` supports the same tag outcomes as the UI, including creation-by-name where supported today.
- [ ] No dedicated MCP add/remove-tag tools are introduced.
- [ ] UI and MCP tag edits remain behaviourally aligned.

**Required Test Coverage:**
- **Unit:** modal/menu state and MCP tag-update mapping helpers.
- **Integration:** MCP tests covering replacement-style updates, missing-tag creation, and parity with REST behaviour.
- **E2E:** sidebar edit flow plus a follow-up UI verification after an MCP-style tag update.

### ITER2.6-004: Contact Detail Layout Polish
**Objective:** Improve the contact page layout without undoing the existing responsive structure.
**Strategy:** Split into 2 phases so structure changes land before polish and breakpoint hardening.

**Relevant documents:**
- [Contacts Product Specification — Contact Layout Improvements](../product-specifications/contacts-product-specification.md#contact-layout-improvements)
- [Frontend Design — Responsive Layout Guidelines](../architecture/frontend-design.md#responsive-layout-guidelines)
- [Frontend Design — Accessibility Guidelines](../architecture/frontend-design.md#accessibility-guidelines)
- [Frontend Design — Spacing and Layout](../architecture/frontend-design.md#spacing-and-layout)
- [Testing Strategy — End-to-End Testing with Playwright](../architecture/testing-strategy.md#end-to-end-testing-with-playwright)

#### Phase 1: Information Hierarchy Reshuffle
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Contact methods and tags move higher in the desktop information hierarchy.
- [ ] Excessive blank space is reduced without making the page feel cramped.
- [ ] The sidebar remains part of the layout.
- [ ] Existing inline editing, relationships, and activity sections still render and function.

**Required Test Coverage:**
- **Unit:** any layout helper/state logic introduced for section ordering.
- **Integration:** page/component tests for section presence and ordering.
- **E2E:** contact detail smoke test proving the reordered layout still supports common interactions.

#### Phase 2: Visual Polish, Responsiveness, and Accessibility Hardening
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Desktop width is used more effectively while preserving readability.
- [ ] Mobile and tablet breakpoints remain functional.
- [ ] Accessibility landmarks, headings, and keyboard interaction remain sound.
- [ ] The page requires less scrolling for common tasks.

**Required Test Coverage:**
- **Unit:** visual-state helpers if added.
- **Integration:** accessibility-focused component/page tests and responsive layout assertions.
- **E2E:** breakpoint coverage across desktop and mobile-sized contact detail flows.

### ITER2.6-005: Important Dates Foundation and Google-Supported Date Sync
**Objective:** Introduce important dates as a first-class contact concept with explicit precision rules.
**Strategy:** Split into 4 phases so the data model, contracts, UI, and sync semantics can land independently.

**Relevant documents:**
- [Contacts Product Specification — Important Dates](../product-specifications/contacts-product-specification.md#important-dates)
- [Contacts Product Specification — MCP and AI-Agent Parity](../product-specifications/contacts-product-specification.md#mcp-and-ai-agent-parity)
- [Database Design — Migration Strategy](../architecture/database-design.md#migration-strategy)
- [Database Design — Iterative Schema Evolution](../architecture/database-design.md#iterative-schema-evolution)
- [API Design — Input Validation Guidelines](../architecture/api-design.md#input-validation-guidelines)
- [Testing Strategy — Database Integration Testing](../architecture/testing-strategy.md#database-integration-testing)

#### Phase 1: Date Domain and Persistence Foundation
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Contacts can store multiple important dates with explicit type and precision (`full`, `day_month`, `year`).
- [ ] Built-in date types include birthday, marriage anniversary, work anniversary, and first met.
- [ ] If needed, introduce the minimal global configuration mechanism for custom date types instead of hardcoding a one-off path.
- [ ] Persistence and domain rules are centralised and future-proof for MCP and sync use.

**Required Test Coverage:**
- **Unit:** precision validation, built-in/custom type rules, date ordering/display helpers.
- **Integration:** repository and migration-level tests with real database persistence.
- **E2E:** focused contact scenario proving an existing important date can be loaded and displayed end-to-end.

#### Phase 2: API and MCP Contracts
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] REST responses and mutations expose important dates consistently.
- [ ] MCP contact retrieval includes important dates.
- [ ] Validation errors are explicit for unsupported precision/type combinations.
- [ ] Existing contact retrieval payloads are not regressed.

**Required Test Coverage:**
- **Unit:** schema translation and validation helpers.
- **Integration:** API and MCP contract tests for read/write behaviour.
- **E2E:** end-to-end retrieval flow proving important dates are visible in the product after API/MCP changes.

#### Phase 3: Contact Detail Editing and Presentation
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] The contact detail page presents dates in a richer card/section rather than a raw field list.
- [ ] Inline editing supports create, update, and delete flows.
- [ ] Birthday receives stronger presentation by default.
- [ ] The rest of the detail page remains stable.

**Required Test Coverage:**
- **Unit:** date-form state and formatting helpers.
- **Integration:** UI mutation tests against real API mocks/contracts.
- **E2E:** create, edit, and remove important dates from the contact detail page.

#### Phase 4: Google-Supported Date Sync
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Google-supported date types sync bidirectionally.
- [ ] Unsupported local-only date types remain local-only.
- [ ] Sync does not duplicate or silently discard supported dates.
- [ ] Imported dates render correctly in the contact detail UI.

**Required Test Coverage:**
- **Unit:** Google date field mapping and local-only filtering rules.
- **Integration:** import/export sync scenarios with supported and unsupported date types.
- **E2E:** sync-trigger scenario proving a Google-supported date appears correctly in the contact UI.

### ITER2.6-006: Relationships-to-User Extension
**Objective:** Extend the existing relationship model so it can represent the user's relationship to a contact, not just contact-to-contact links.
**Strategy:** Split into 3 phases so model changes land before UI editing and search/MCP consumption.

**Relevant documents:**
- [Contacts Product Specification — Relationships](../product-specifications/contacts-product-specification.md#relationships)
- [Contacts Product Specification — AI Interaction Summary](../product-specifications/contacts-product-specification.md#ai-interaction-summary)
- [Contacts Product Specification — Global Search](../product-specifications/contacts-product-specification.md#global-search)
- [Domain Architecture — Contacts Domain](../architecture/domain-architecture.md#contacts-domain)
- [API Design — MCP (Model Context Protocol) Guidelines](../architecture/api-design.md#mcp-model-context-protocol-guidelines)
- [Testing Strategy — API Integration Testing Guidelines](../architecture/testing-strategy.md#api-integration-testing-guidelines)

#### Phase 1: Relationship Target Model and API Semantics
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] A contact can hold multiple relationships, including relationships to the user.
- [ ] Existing contact-to-contact relationships continue to work unchanged.
- [ ] The API model makes the user target explicit without ambiguous overloading.
- [ ] Validation prevents invalid or contradictory target combinations.

**Required Test Coverage:**
- **Unit:** relationship target validation and serialization rules.
- **Integration:** API create/update/delete/list flows covering contact-target and user-target relationships.
- **E2E:** create and view a user-targeted relationship through the contacts UI.

#### Phase 2: Relationship Management UX
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Relationship creation/editing flows make the user target understandable.
- [ ] Existing relationship management for contact-to-contact links is not regressed.
- [ ] Empty states and edit states read clearly once user-targeted relationships exist.
- [ ] Relationship lists remain usable when a contact has multiple relationships.

**Required Test Coverage:**
- **Unit:** form-state helpers and display-label helpers.
- **Integration:** frontend mutation and rendering tests against the updated relationship contracts.
- **E2E:** add, edit, and delete a user-targeted relationship from the real contact page.

#### Phase 3: MCP and Search-Signal Propagation
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] MCP contact retrieval includes the richer relationship context.
- [ ] Search/indexing inputs can consume the relationship-to-user signal.
- [ ] The new relationship semantics do not break existing MCP or search consumers.
- [ ] Relationship context is available for later AI summary use.

**Required Test Coverage:**
- **Unit:** search-signal and MCP-shaping helpers.
- **Integration:** MCP and indexing tests covering user-target relationships.
- **E2E:** search/contact retrieval scenario proving the relationship signal is visible or used without regressions.

### ITER2.6-007: AI Interaction Summary and Search-Signal Indexing
**Objective:** Replace the current summary behaviour with an evidence-grounded AI interaction summary and expose the resulting signals to search.
**Strategy:** Split into 4 phases so persistence, generation, UI/MCP exposure, and ranking signals can each merge safely.

**Relevant documents:**
- [Contacts Product Specification — AI Interaction Summary](../product-specifications/contacts-product-specification.md#ai-interaction-summary)
- [Contacts Product Specification — Global Search](../product-specifications/contacts-product-specification.md#global-search)
- [Contacts Product Specification — MCP and AI-Agent Parity](../product-specifications/contacts-product-specification.md#mcp-and-ai-agent-parity)
- [Integration Architecture — Event-Driven Scheduling](../architecture/integration-architecture.md#2-event-driven-scheduling)
- [Integration Architecture — Transactional Outbox Pattern](../architecture/integration-architecture.md#transactional-outbox-pattern)
- [Database Design — MeiliSearch Integration](../architecture/database-design.md#meilisearch-integration)

#### Phase 1: Summary Data Model and Control Surface
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Add persistence for generated summary text, follow-up suggestions, status, disable/override state, and generated-at timestamp.
- [ ] Add API contracts for reading summary state and requesting refresh.
- [ ] The summary feature can be safely present in a not-yet-generated state.
- [ ] No existing contact retrieval path breaks when summary data is absent.

**Required Test Coverage:**
- **Unit:** summary-state models, disable/override rules, request validation.
- **Integration:** database and API tests for empty/generated/manual-refresh states.
- **E2E:** contact detail scenario proving the summary container behaves correctly before generation.

#### Phase 2: Asynchronous Generation Pipeline
**PR Size:** ~5-8 files

**Acceptance Criteria:**
- [ ] Summary regeneration is triggered asynchronously after relevant contact activity.
- [ ] The input assembly is bounded to recent history and grounded in available evidence.
- [ ] Low-activity auto-disable works, with user override respected.
- [ ] Normal contact edits do not block on summary generation.

**Required Test Coverage:**
- **Unit:** input assembly, recent-history bounds, low-activity heuristics.
- **Integration:** outbox/background job trigger tests using real persistence.
- **E2E:** edit a contact or related note and verify summary regeneration is queued/completed without blocking the UI.

#### Phase 3: Contact UI and MCP Exposure
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] The contact detail page shows a concise AI-generated summary and follow-up suggestions.
- [ ] The UI shows when the summary was last generated and supports manual refresh.
- [ ] MCP contact retrieval returns the summary, follow-up suggestions, relationship context, and important dates.
- [ ] The summary remains conservative and evidence-grounded rather than speculative.

**Required Test Coverage:**
- **Unit:** summary display/formatting helpers.
- **Integration:** API and MCP tests for summary retrieval and refresh behaviour.
- **E2E:** manual refresh and read-back flow from the contact page.

#### Phase 4: Search-Signal Indexing
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Search indexing receives summary, activity, relationship, tag, journal, and date signals in a controlled way.
- [ ] Ranking inputs are emitted without requiring the final search UI to land in the same PR.
- [ ] Indexing remains robust when summary data is disabled or missing.
- [ ] Existing search indexing is not regressed.

**Required Test Coverage:**
- **Unit:** ranking-signal calculation and fallback rules.
- **Integration:** indexing pipeline tests proving new signals are emitted and stored safely.
- **E2E:** search flow demonstrating the index still serves usable results after the signal changes.

### ITER2.6-008: Global Search UX Completion
**Objective:** Turn the top search box into a real product feature using the existing backend search foundations.
**Strategy:** Split into 3 phases so header interactions, results UX, and final ranking integration remain reviewable.

**Relevant documents:**
- [Contacts Product Specification — Global Search](../product-specifications/contacts-product-specification.md#global-search)
- [Contacts Product Specification — MCP and AI-Agent Parity](../product-specifications/contacts-product-specification.md#mcp-and-ai-agent-parity)
- [Journal System Specification — Search and Filtering](../journal-system-specification.md#search-and-filtering)
- [Database Design — MeiliSearch Integration](../architecture/database-design.md#meilisearch-integration)
- [Frontend Design — Component Architecture](../architecture/frontend-design.md#component-architecture)
- [Frontend Design — Testing Patterns](../architecture/frontend-design.md#testing-patterns)

#### Phase 1: Live Header Suggestions and Recent Searches
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Typing in the top search shows live suggestions plus recent searches.
- [ ] Keyboard navigation behaves predictably.
- [ ] The header component no longer relies on mock/placeholder suggestion behaviour.
- [ ] Existing header navigation is not regressed.

**Required Test Coverage:**
- **Unit:** suggestion-state and keyboard-navigation helpers.
- **Integration:** frontend data-fetch tests against real search suggestion contracts.
- **E2E:** header search typing and suggestion selection flow.

#### Phase 2: Dedicated Grouped Search Results Page
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Pressing Enter navigates to a dedicated search results page.
- [ ] Results are grouped by Contacts and Journals.
- [ ] Empty, loading, and error states are explicit.
- [ ] Recent searches continue to work with the dedicated results flow.

**Required Test Coverage:**
- **Unit:** results-grouping and query-state helpers.
- **Integration:** API/result handling tests for grouped contacts+journals responses.
- **E2E:** header Enter → results page → grouped results interaction.

#### Phase 3: Ranking Consumption and Final Search Regression Pass
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Contact ranking in the UI reflects favourites, tags, relationships, journal signals, recent activity, and summary relevance.
- [ ] The search experience works from the header without requiring a custom callback path.
- [ ] AI-facing global search remains aligned with the same broad behaviour.
- [ ] Search remains understandable even if explanation UI is deferred.

**Required Test Coverage:**
- **Unit:** ranking-display or result-shaping helpers used by the UI.
- **Integration:** search response/regression tests consuming the enhanced ranking signals.
- **E2E:** end-to-end search scenario covering header entry, ranking-sensitive results, and result navigation.

### ITER2.6-009: Provenance-Aware Contact Activity Feed
**Objective:** Make activity history trustworthy by showing meaningful changes and their origin.
**Strategy:** Split into 3 phases so provenance capture lands before UI rendering and final mixed-source regressions.

**Relevant documents:**
- [Contacts Product Specification — Activity Feed](../product-specifications/contacts-product-specification.md#activity-feed)
- [Contacts Product Specification — AI Interaction Summary](../product-specifications/contacts-product-specification.md#ai-interaction-summary)
- [Integration Architecture — Two-Way Sync (Google Contacts)](../architecture/integration-architecture.md#1-two-way-sync-google-contacts)
- [Domain Architecture — Contacts Domain Adapters](../architecture/domain-architecture.md#contacts-domain-adapters)
- [Database Design — Contact History Table](../architecture/database-design.md#contact-history-table)
- [API Design — Error Handling Guidelines](../architecture/api-design.md#error-handling-guidelines)

#### Phase 1: Provenance Capture Model
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Activity/history data distinguishes UI, MCP, sync, and summary-regeneration sources reliably.
- [ ] Provenance capture is added centrally rather than scattered through ad hoc string values.
- [ ] No-op exports do not create activity entries.
- [ ] Existing history retrieval remains backwards-compatible enough for staged UI rollout.

**Required Test Coverage:**
- **Unit:** provenance classification, no-op suppression, summary-event shaping helpers.
- **Integration:** history persistence tests for UI/MCP/sync/source combinations.
- **E2E:** end-to-end edit scenario proving ordinary UI changes still appear in the feed.

#### Phase 2: Activity API Shape and UI Rendering
**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] Provenance is displayed with compact icons and hover text.
- [ ] Summary regeneration appears in the same stream in abbreviated, collapsible form.
- [ ] Existing pagination/load-more behaviour continues to work.
- [ ] Mixed activity types remain understandable without adding filter UI in this iteration.

**Required Test Coverage:**
- **Unit:** activity-item rendering helpers and collapse-state logic.
- **Integration:** API payload tests for provenance-rich history responses.
- **E2E:** contact activity feed scenario covering icons, hover text, and collapsed summary entries.

#### Phase 3: Mixed-Source Regression and Sync Visibility
**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] Meaningful edits from UI, MCP, and sync all appear correctly in one stream.
- [ ] Sync-originated changes appear only when they changed the contact.
- [ ] Summary regeneration entries coexist cleanly with ordinary history entries.
- [ ] The final feed behaviour is stable under pagination and recent updates.

**Required Test Coverage:**
- **Unit:** mixed-source ordering and de-duplication helpers.
- **Integration:** history API scenarios covering UI + MCP + sync + summary updates together.
- **E2E:** full end-to-end edit-history scenario including sync-style entries and no-op export suppression.

## Known Prerequisites and Explicit Follow-up Work

- **Custom date types:** if there is no existing global configuration mechanism suitable for contact date types, Task 5 must start with a minimal configuration slice rather than hardcoding a one-off solution.
- **Reserved Google groups configuration:** Task 1 should deliver backend-configurable reserved groups first; any richer admin UI for editing those rules can be a follow-up if not needed immediately.
- **Search ranking explanations:** desirable, but only after Task 8 if the ranking model is stable and the explanation can be implemented cleanly.
- **Upcoming important dates on contact cards:** desirable follow-up after Task 5; not required to complete the core detail-page experience.
- **User-targeted relationship UX language:** if the current relationship labels read awkwardly once the user becomes a possible target, capture any copy/design follow-up here rather than papering over it in code.

## Definition of Done for the Iteration

This iteration is complete when:

- hierarchical tags are editable, filterable, and Google-sync-aware
- Google group sync behaves predictably, including reserved groups and favourites mapping
- the contact detail page surfaces higher-value information with less scrolling
- important dates and relationships-to-user are available in UI and MCP
- AI interaction summaries are generated asynchronously and exposed consistently
- the top search is a real, grouped contacts+journals experience
- the activity feed clearly shows meaningful changes with provenance
- all completed slices keep `main` green with tests, linting, and type checks passing