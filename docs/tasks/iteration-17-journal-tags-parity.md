# Iteration 17: Journal Tags Parity

**Status:** 🟡 IN PROGRESS (ITER17-001 Phase 1 complete)
**Dependencies:** Iteration 4 (journal tag tables and relationship endpoints), Iteration 4.6 (journal tag filtering + detail-view tag add/remove), Iteration 12 (unified event-driven history), Iteration 2.6 (contact tag management UX — the reference behaviour)
**Goal:** Bring journal tag functionality to exact parity with contact tags across the UI, backend management operations, filtering, history, and MCP.

## Overview

Contacts have a complete tag experience: a rich inline editor with search and create-new-tag flow, colour-coded badges, a hierarchical tag tree in the sidebar with context-menu management (edit / delete / merge), URL-driven tag filtering that includes descendant tags, tag change history, and MCP tag tools. Journal tags share the same data model shape (hierarchical, coloured, unique names) but expose only a fraction of this: a basic select-dropdown add/remove on the detail page and a checkbox filter panel.

This iteration closes the gap so that journal tags behave **exactly like contact tags**. Journal tags remain a **separate tag namespace** (`journal_tags` vs `tags`, per the journal system specification) — parity means matching behaviour, not merging the two tag systems.

### Key References

- **Contacts product spec — Contact Tags**: `docs/product-specifications/contacts-product-specification.md` (§Contact Tags, §Tag management experience) — the behaviour contract this iteration replicates for journals
- **Journal spec — Tags**: `docs/journal-system-specification.md` (~lines 174–198: separate hierarchical tag system; ~line 1098: tag chips clickable to filter, inline editable; ~line 1115: hierarchical tag selector)
- **Reference implementation (contacts)**:
  - Editor: `frontend/src/components/contacts/ContactTagsEditor.tsx`
  - Management: `frontend/src/components/contacts/TagManagementDialog.tsx`, `TagContextMenu.tsx`, `CreateTagDialog.tsx`
  - Sidebar tree: `frontend/src/components/layout/Sidebar.tsx` (TagTreeNavigation), `frontend/src/lib/tags/buildTagTree.ts`
  - URL filter: `frontend/src/hooks/useTagFilter.ts` (`/contacts?tag=<id>`)
  - Backend: `backend/app/api/tags/controllers.py`, `backend/app/core/contacts/services/tag_service.py`, hierarchical filter expansion in `backend/app/core/contacts/services/contact_service.py` (`_expand_tag_ids_with_descendants`)

## Current Baseline (verified)

### What journal tags already have

- **Database**: `journal_tags` (UUID PK, unique `name`, `parent_id` hierarchy, `color`, and `description` since migration `0102`) and `journal_tag_assignments` (composite PK `(journal_id, tag_id)`, cascade deletes) — migration `0012_create_journal_relationships_and_tags.py`.
- **Backend endpoints** (`backend/app/api/journals/controllers.py`):
  - `GET /api/journals/tags`, `POST /api/journals/tags`
  - `DELETE /api/journals/tags/{tag_id}` — **returns 409 Conflict when the tag is in use** (contact tag delete instead removes the tag from all contacts)
  - `POST /api/journals/{id}/relationships/tags`, `DELETE /api/journals/{id}/relationships/tags/{tag_id}`
  - `GET /api/journals?tag_id=` filter (singular)
- **Service/repository**: `JournalTagService.create_tag` only; repository (`journal_tag_repository.py`) supports `find_by_name` (case-insensitive), `get_all`, `get_children`, `get_root_tags`, `get_tags_for_journal`, `save`. **No update / delete-with-unassign / merge service methods.**
- **Frontend**:
  - `JournalTagBadge.tsx` wired into `JournalDetailView.tsx` with working `useAddJournalTag` / `useRemoveJournalTag` mutations — but add uses a plain `Select` dropdown (no search, no inline create, badges not colour-coded, and the "Add Tag" button is hidden when there are no unassigned tags, so an empty tag list is a dead end).
  - `JournalFilters.tsx` has a multi-select checkbox tag filter, but `fetchJournals` (`frontend/src/lib/api/journals.ts`) **only sends the first selected tag** as singular `tag_id`.
  - `JournalListItem.tsx` already renders colour-coded tag chips on list items.
  - No journal tag tree in the sidebar (`Sidebar.tsx` renders the tag tree for contacts only); no `?tag=` deep link on `/journals`.
  - `JournalCreateForm.tsx` has no tag input.
- **Search**: `journal_indexing_service.py` indexes `tag_ids` as a filterable field.
- **MCP**: `create_journal_entry` / `update_journal_entry` / journal reads support tags; `merge_tags` is still **contact-only** (`backend/app/mcp/domains/contacts/tools.py`). Journal tag listing shipped in ITER17-001 Phase 1 as `list_journal_tags`, alongside which contacts' `list_tags` was renamed `list_contact_tags`.
- **History**: no tag domain events for journals — tag changes do not appear in the journal activity feed (contacts publish `TagAssigned` / `TagRemoved` / `TagUpdated` / `TagDeleted` and project them into history).

### Gap summary

| Behaviour (contact tags reference) | Journal tags today | Gap |
|---|---|---|
| Inline editor: searchable add popover, create-new-tag with colour, dismissible colour badges | Plain select dropdown, no create, no colours, dead end when no tags exist | ITER17-003 |
| Sidebar hierarchical tag tree with click-to-filter | Absent | ITER17-004 |
| Tag management: edit name/colour/description/parent, delete, merge (context menu + dialogs) | Create only; delete 409s when in use; no update/merge | ITER17-001, ITER17-004 |
| `description` field on tags | ✅ Closed — column added in ITER17-001 Phase 1 | ITER17-001 |
| Delete removes tag from all entities | Delete blocked (409) when in use | ITER17-001 |
| Multi-tag filter param + hierarchical descendant expansion | Singular `tag_id`, first-selected-only, no hierarchy expansion | ITER17-002 |
| URL deep link (`?tag=`) on the list page | Absent | ITER17-002 |
| Tag change history in activity feed | No tag domain events | ITER17-005 |
| MCP tag management (list, merge) | List closed in Phase 1 (`list_journal_tags`); merge still contact-only | ITER17-001 (with the matching API changes) |

## Delivery Rules

These rules apply to every task below:

1. **Tests first:** write the failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks are passing.
3. **Reviewable PRs:** keep each phase's diff to roughly **≤ 500 changed lines** (including tests). If an estimate exceeds that during implementation, split the phase further rather than raising an oversized PR.
4. **Behaviour parity is the acceptance bar:** when in doubt, the contact tags implementation is the specification. Divergence (other than the UUID vs Integer PK and separate namespace) must be justified in this document.
5. **Reuse before rebuild:** prefer extracting shared components/utilities from the contact implementation (e.g. `buildTagTree`, `TAG_COLORS`, editor/dialog structure) over duplicating them. Where extraction would bloat a PR, duplicate first and record the consolidation as follow-up here.
6. **Transactions:** all new write endpoints commit via `@transactional` service methods or `unit_of_work`; controllers and MCP tools never open transactions.
7. **MCP parity:** management operations available in the UI must be available through MCP.
8. **Record follow-up work here:** if a prerequisite or deferred enhancement is discovered mid-task, update this document.
9. **Every phase is shippable:** no phase may rely on a later phase to restore broken behaviour.

## Phase Completion Requirements

Every phase below must meet the same completion bar before merge:

- `main` remains green at the end of the phase.
- The phase includes explicit **unit, integration, and e2e coverage** (e2e may be deferred only for phases with no user-visible surface, and the deferral must be stated).
- The e2e layer must be deterministic and fixture-driven (each test creates its own tags/journals; no conditional logic on data state).
- Linting, type checking, and the narrowest reliable test targets for the slice must pass.

## Sequencing Strategy

1. **ITER17-001** (backend management operations, REST + MCP delivered together per phase) unblocks the sidebar management UI phase-by-phase: Phase 2 (update) unblocks ITER17-004 Phase 2; Phases 3–4 (delete/merge) unblock ITER17-004 Phase 3.
2. **ITER17-002** (filtering parity) is independent of 001 and can run in parallel.
3. **ITER17-003** (detail-page editor) needs only existing endpoints and can start immediately.
4. **ITER17-004** (sidebar tree + management dialogs) — Phase 1 needs only ITER17-002; later phases follow the matching ITER17-001 phases.
5. **ITER17-005 Phase 1** (assignment/removal events) has no ITER17-001 dependency and can run in parallel; Phase 2 (management events) follows ITER17-001 Phases 2–4.

## Task Breakdown

### ITER17-001: Journal Tag Management Backend (update, delete parity, merge, description) with MCP Parity

**Objective:** Give journal tags the same management operations as contact tags — full update (name, colour, description, parent), delete that un-assigns rather than blocks, and merge — exposed through **both REST and MCP in the same phase** as each capability lands.
**Strategy:** Four phases, one management capability per phase (description/list, update, delete, merge), each shipping its REST surface and the matching MCP tooling together to stay within the 500-line diff standard.

**Relevant documents:**
- [Database Design — Migration Strategy](../architecture/database-design.md#migration-strategy)
- [API Design](../architecture/api-design.md) (REST and FastMCP patterns)
- Contact reference: `backend/app/core/contacts/services/tag_service.py`, `backend/app/api/tags/controllers.py`, and the MCP tools `list_contact_tags` (renamed from `list_tags` in Phase 1) / `merge_tags` in `backend/app/mcp/domains/contacts/tools.py`
- Memory note: MCP tool documentation lives in docstrings/schemas, not in `mcp-setup.md`.
- MCP rules: MCP tools are controller-equivalent — they call `@transactional` services and never open transactions.

#### Phase 1: Description Column and MCP Tag Listing ✅ COMPLETE

**Estimated diff:** ~350 lines

**Acceptance Criteria:**
- [x] Alembic migration adds nullable `description TEXT` to `journal_tags` (follow the sequential naming convention in the `creating-migrations` skill). — `0102_add_description_to_journal_tags.py`
- [x] `JournalTag` domain model and repository read/write `description`. — the repository's six duplicated row-mapping blocks were collapsed into a `_row_to_tag` helper so the column is declared once.
- [x] `GET /api/journals/tags` and `POST /api/journals/tags` include `description` in resources.
- [x] **MCP (same phase as the listing surface change):** journal tags are listable via MCP with hierarchy, colour, and description — either by extending the existing `list_tags` tool with a domain parameter or adding a journal-scoped equivalent (match whichever pattern the MCP domain structure prefers; document the choice). — **new `list_journal_tags` tool** (see decision below).

**Decisions taken (Phase 1):**
- **New `list_journal_tags` tool in the journals MCP domain, not a `domain=` parameter on `list_tags`.** REST already separates `/api/tags` from `/api/journals/tags`; journal tags are UUID-keyed with colour and timestamps while contact tags are int-keyed behind a different repository, so one tool would need repository branching and a polymorphic response schema; and `docs/architecture/api-design.md` prescribes per-domain tool organisation with no cross-domain-parameter precedent in the codebase.
- **Contacts' `list_tags` renamed to `list_contact_tags`** so the two namespaces are symmetrically named and neither tool is the ambiguous default. This is a breaking rename for MCP clients, which is acceptable because clients re-fetch the tool list on each session. Each tool's docstring now points at the other. `merge_tags` keeps its name for now — rename it to `merge_contact_tags` in Phase 4 when the journal merge tool lands beside it.

**Required Test Coverage:**
- **Unit:** model/serialisation with and without description; MCP list tool schema. — `tests/unit/journal/test_journal_tag_entity.py`, `tests/unit/journal/test_journal_tag_schemas.py`, `tests/unit/mcp/domains/journals/test_tools.py`
- **Integration:** migration applies cleanly; create/list round-trip with description; MCP list tool test mirroring the contact `list_tags` tests. — `tests/integration/journal/test_journal_tag_repository_integration.py` (all six read paths), `tests/integration/api/test_journal_tag_endpoints.py`, `tests/integration/mcp/test_journal_tag_mcp.py`
- **E2E:** deferred to ITER17-004 (no UI surface yet); MCP integration tests are the equivalent bar for the tool surface. — deferral taken as stated.

#### Phase 2: Tag Update (REST + MCP) ✅ COMPLETE

**Estimated diff:** ~500 lines · **Actual:** ~900 lines, split into two commits (see decisions below)

**Acceptance Criteria:**
- [x] `JournalTagService.update_tag(tag_id, transaction, name, color, description, parent_id, set_parent_null)` mirroring the contact `TagService.update_tag` signature and validation:
  - name uniqueness (case-insensitive) with a clear validation error on conflict — delegated to the new `JournalTagHierarchyService`, which reuses the repository's existing `LOWER(name)` lookup
  - colour format validation (7-char hex `#RRGGBB`) — the updated entity is rebuilt via `dataclasses.replace` so `JournalTag.__post_init__` re-runs, and the resulting `ValueError` is mapped to `JournalValidationError`
  - parent hierarchy cycle prevention (a tag cannot become its own ancestor) — ancestor walk with a `visited` set, mirroring `TagHierarchyService._check_circular_reference`
- [x] `PATCH /api/journals/tags/{tag_id}` endpoint following the contact `PATCH /api/tags/{tag_id}` request/response shape. — validates resource type, path/body id agreement, and derives `set_parent_null` from `model_fields_set`
- [x] **MCP (same phase):** tag update is reachable via MCP to the same extent it is for contact tags. — the contact baseline exposed **no** update tool, so this phase added `update_journal_tag` **and** `update_contact_tag` (see decisions below)
- [x] Write path commits via `@transactional`/`unit_of_work` in the service layer; MCP tools call the same `@transactional` service and do not open transactions.

**Decisions taken (Phase 2):**
- **The contact baseline had no MCP tag-update tool**, so "match it exactly" would have shipped zero MCP work — contradicting this iteration's REST+MCP-per-phase strategy. Rather than propagate the gap into Phases 3 and 4, the phase closed it in **both** domains: `update_journal_tag` (journals) and `update_contact_tag` (contacts). Each tool's docstring points at the other, matching the Phase 1 naming convention.
- **`mcp_unified_error_handler` now recognises contacts' `TagNotFoundError` and `DuplicateTagNameError`.** It already special-cased `ContactNotFoundError`, `ContactValidationError`, and the whole `JournalDomainError` tree, but contacts' tag errors fell through to the catch-all — so an unknown tag id came back as a generic "an error occurred" that callers could not distinguish from a server failure. Surfaced by review of `update_contact_tag`; the fix also improves the pre-existing `merge_tags`.
- **Clearing a parent over MCP uses a `move_to_root` boolean**, not a null `parent_id`. MCP arguments cannot distinguish "omitted" from "explicitly null", so the REST `set_parent_null` signal needs an explicit argument at the tool boundary. REST keeps the contact-style explicit-null convention.
- **An explicit parent wins over the clear-parent flag** when a caller supplies both, so the two MCP tools cannot diverge on the same argument pair. Unreachable via REST (the controller only sets `set_parent_null` when `parent_id` is explicitly null), but reachable via MCP. Review of this phase surfaced that contacts' `TagService._apply_parent_change` had a flat `if parent_id is not None and tag.parent_id != parent_id: ... elif set_parent_null:` — so passing a `parent_id` **equal to the current parent** alongside the clear flag fell through and cleared it. That condition is now nested to match the journal implementation; it was latent before this phase because only the new MCP tool can reach the combination.
- **Duplicate names and cycles map to `JournalValidationError` (400)**, not the contacts' `DuplicateTagNameError` (409) / `ContactValidationError` (422). This matches the existing journal tag *create* path, which already returns 400 for a duplicate name; journal-domain internal consistency was preferred over cross-domain status-code parity.
- **Split into two commits** because the two-domain MCP work pushed the diff to ~900 lines, past the 500-line PR standard: (A) service + hierarchy validation + REST PATCH, (B) both MCP tools.
- **`_journal_tag_resource` helper extracted** in `backend/app/api/journals/controllers.py` — the list, create, and new update endpoints all built the same JSON:API resource dict by hand.

**Required Test Coverage:**
- **Unit:** update validation (duplicate name, invalid colour, cycle prevention), set-parent-null semantics, MCP tool schema/serialisation. — `tests/unit/journal/test_journal_tag_service.py` (`TestUpdateTag`, 13 tests), `tests/unit/journal/test_journal_tag_schemas.py` (`TestJournalTagUpdateAttributes`), `tests/unit/mcp/domains/journals/test_tools.py` + `tests/unit/mcp/domains/contacts/test_tools.py` (tool schema tests)
- **Integration:** PATCH endpoint round-trip with real DB; uniqueness constraint behaviour; MCP update tool test. — `tests/integration/api/test_journal_tag_endpoints.py` (`TestUpdateJournalTagEndpoint`, 14 tests), `tests/integration/journal/test_journal_tag_repository_integration.py` (re-parent round-trip, case-insensitive lookup), `tests/integration/mcp/test_journal_tag_mcp.py` (`TestUpdateJournalTagMCPTool`, 8 tests), `tests/integration/mcp/test_contact_tools_integration.py` (2 `update_contact_tag` tests)
- **E2E:** deferred to ITER17-004 — no frontend surface edits journal tags, and `JournalTag` in `frontend/src/types/journals.ts` still carries only id/name/color. Deferral taken as stated.

#### Phase 3: Delete Parity (REST + MCP)

**Estimated diff:** ~400 lines

**Acceptance Criteria:**
- [ ] `JournalTagService.delete_tag(tag_id, transaction)`: deleting a tag removes it from all journals (assignments cascade via existing FK) and deletes the tag — matching contact behaviour. The current 409-when-in-use guard in `DELETE /api/journals/tags/{tag_id}` is removed.
- [ ] Child tags of a deleted tag are re-parented to NULL (existing `ON DELETE SET NULL`), matching contact behaviour.
- [ ] **MCP (same phase):** tag delete is reachable via MCP to the same extent it is for contact tags.
- [ ] Journals affected by delete are re-indexed in MeiliSearch (their `tag_ids` change) — verify how contact tag events drive re-indexing and mirror it (may move to ITER17-005 if event-driven; state the choice in the PR).

**Required Test Coverage:**
- **Unit:** delete semantics (assignments removed, children re-parented to NULL).
- **Integration:** delete removes assignments from journals with real DB; hierarchy re-parenting; search index state after delete; MCP delete tool test if the contact baseline exposes delete.
- **E2E:** deferred to ITER17-004.

#### Phase 4: Tag Merge (REST + MCP)

**Estimated diff:** ~500 lines

**Acceptance Criteria:**
- [ ] `JournalTagService.merge_tag(source_id, target_id, transaction)` mirroring contact merge semantics:
  - all assignments of the source tag are repointed to the target (duplicate `(journal_id, tag_id)` rows resolved via `ON CONFLICT DO NOTHING`)
  - children of the source tag are re-parented to the target
  - the source tag is deleted
  - merging a tag into itself or into a descendant is rejected
- [ ] `POST /api/journals/tags/{tag_id}/merge` endpoint following the contact merge endpoint shape.
- [ ] **MCP (same phase):** journal tags can be merged via MCP, mirroring the contact `merge_tags` tool semantics and reusing `JournalTagService.merge_tag`.
- [ ] Journals affected by merge are re-indexed in MeiliSearch (same mechanism chosen in Phase 3).

**Required Test Coverage:**
- **Unit:** merge validation (self-merge, descendant-merge rejection), MCP merge tool schema/serialisation.
- **Integration:** merge with overlapping assignments (no duplicate-key failure), hierarchy re-parenting, search index state after merge, MCP merge tool test against a real DB.
- **E2E:** deferred to ITER17-004.

---

### ITER17-002: Journal List Tag Filtering Parity

**Objective:** Match contact list tag filtering: multiple tags, hierarchical descendant expansion, and URL deep-linking.
**Strategy:** Two phases — backend param upgrade first, then frontend wiring — to stay within the 500-line diff standard.

**Relevant documents:**
- Contact reference: `_expand_tag_ids_with_descendants` in `backend/app/core/contacts/services/contact_service.py`; `useTagFilter` hook.

#### Phase 1: Backend Multi-Tag and Hierarchical Filtering

**Estimated diff:** ~450 lines

**Acceptance Criteria:**
- [ ] `GET /api/journals` accepts repeated `tag_ids` query params (list), keeping `tag_id` working for backward compatibility (or migrating all callers in the same PR — state the choice).
- [ ] Tag filtering expands each requested tag to include all descendant tags before querying, matching contact behaviour (a journal tagged only with a child tag appears when filtering by the parent).
- [ ] Multiple tags combine the same way the contacts list combines them (verify: contacts use a single JOIN over the expanded ID set, i.e. logical OR across tags — replicate exactly).

**Required Test Coverage:**
- **Unit:** descendant expansion logic.
- **Integration:** repository/service filter tests — parent tag returns child-tagged journals; multi-tag combinations; combined with type/date filters (existing AND semantics preserved).
- **E2E:** existing journal list filter specs continue to pass (frontend behaviour unchanged this phase).

#### Phase 2: Frontend Multi-Tag Params and URL Deep Link

**Estimated diff:** ~350 lines

**Prerequisites:** Phase 1 merged.

**Acceptance Criteria:**
- [ ] `fetchJournals` sends **all** selected tags, not just the first.
- [ ] `/journals?tag=<id>` deep link filters the list (reuse or generalise `useTagFilter`), and the filter UI reflects the URL state.
- [ ] `JournalFilters.tsx` checkbox behaviour is unchanged from the user's perspective apart from now actually applying every selected tag.

**Required Test Coverage:**
- **Unit:** frontend filter param construction; `useTagFilter` generalisation.
- **Integration:** n/a beyond RTL (no new backend).
- **E2E:** filter journals by a parent tag and assert a child-tagged journal appears; deep-link `/journals?tag=` renders a filtered list; multi-tag selection returns the union.

---

### ITER17-003: Journal Detail Tag Editor Parity

**Objective:** Replace the select-dropdown tag UI on the journal detail page with an editor matching `ContactTagsEditor` exactly: searchable add popover, inline create-new-tag with colour picker, dismissible colour-coded badges.
**Strategy:** Two phases — build the component with its unit tests first, then wire it into the detail view with e2e coverage. Prefer extracting a shared, domain-agnostic tags editor component parameterised over the tag type and mutation hooks; if extraction proves too large, build `JournalTagsEditor` as a structural copy and record consolidation as follow-up.

**Relevant documents:**
- [Frontend Design — Component Architecture](../architecture/frontend-design.md#component-architecture)
- Contact reference: `frontend/src/components/contacts/ContactTagsEditor.tsx`, `TAG_COLORS` in `frontend/src/lib/constants.ts`

#### Phase 1: Tags Editor Component and Unit Tests

**Estimated diff:** ~500 lines

**Acceptance Criteria:**
- [ ] Assigned tags render as dismissible badges with the tag colour (border/dot styling identical to the contact editor).
- [ ] Adding a tag opens a searchable popover listing unassigned tags filtered by the query (autocomplete), not a plain select.
- [ ] When the search query matches no existing tag, the user can create a new tag inline with name + colour (from `TAG_COLORS`), which is created via `POST /api/journals/tags` and immediately assigned.
- [ ] The add affordance is available even when there are no unassigned tags or no tags at all (the create flow is always reachable).
- [ ] Duplicate assignment is prevented in the UI; already-assigned tags do not appear in the add list.
- [ ] Accessibility matches the contact editor: labelled controls, keyboard operability, `aria-label` on remove buttons.
- [ ] The component is exported but not yet mounted in `JournalDetailView` (existing behaviour unchanged this phase — the phase is shippable with no user-visible change).

**Required Test Coverage:**
- **Unit (RTL):** mirror `ContactTagsEditor.test.tsx` — open/close, search filtering, add existing, create new (name + colour), remove, duplicate prevention, error handling.
- **Integration:** n/a (no backend change).
- **E2E:** deferred to Phase 2 (component not yet mounted).

#### Phase 2: Detail View Wiring and E2E

**Estimated diff:** ~300 lines

**Prerequisites:** Phase 1 merged.

**Acceptance Criteria:**
- [ ] `JournalDetailView.tsx` uses the new editor; the old `JournalTagBadge` select flow is removed (keep the read-only badge rendering if still used elsewhere).
- [ ] Mutations use the existing `useAddJournalTag` / `useRemoveJournalTag` / journal-tag query hooks with cache invalidation, and errors surface to the user (toast), not only `console.error`.
- [ ] Existing journal-detail tag e2e tests are updated to the new interaction and still cover add + remove.

**Required Test Coverage:**
- **Unit (RTL):** detail-view integration test with the editor mounted.
- **Integration:** mutation hook tests if new hooks are added (mirror `contact-tag-mutations.test.ts`).
- **E2E:** on a journal detail page — add an existing tag, create a brand-new tag inline and see it assigned with its colour, remove a tag. Use fixture-created data; ProseMirror/typing-delay best practices where applicable.

---

### ITER17-004: Sidebar Journal Tag Tree and Tag Management UI

**Objective:** Add a hierarchical journal tag tree to the Journals sidebar section with the same management affordances as contacts: expand/collapse, click-to-filter, context menu with edit / delete / merge dialogs, and a create-tag button.
**Strategy:** Three phases — read-only tree + navigation first, then create + edit dialogs, then delete + merge — keeping each within the 500-line diff standard.

**Prerequisites:** ITER17-002 (`/journals?tag=` deep link) for Phase 1; the matching ITER17-001 phases for Phases 2–3 (see per-phase prerequisites).

**Relevant documents:**
- Contact reference: `Sidebar.tsx` (TagTreeNavigation, TagTreeItem), `buildTagTree.ts`, `TagContextMenu.tsx`, `TagManagementDialog.tsx`, `CreateTagDialog.tsx`

#### Phase 1: Sidebar Tree and Navigation

**Estimated diff:** ~450 lines

**Acceptance Criteria:**
- [ ] The Journals sidebar section renders the journal tag tree (nested by `parent_id`) below the existing links, visually and behaviourally identical to the contacts tag tree (expand/collapse chevrons, truncation, icons).
- [ ] `buildTagTree` is reused (generalised over the two tag resource shapes if needed) rather than duplicated.
- [ ] Clicking a tag navigates to `/journals?tag=<id>` and the list filters accordingly (including descendant expansion from ITER17-002); the active tag is highlighted and "All Journals" is not.
- [ ] Loading and error states match the contacts sidebar behaviour.

**Required Test Coverage:**
- **Unit (RTL):** sidebar renders journal tag tree from fixture data; expand/collapse; active-state logic with `?tag=` present.
- **Integration:** n/a beyond RTL (no new backend).
- **E2E:** create tags (parent + child) via API fixtures, open sidebar, expand parent, click child tag, assert the journals list is filtered.

#### Phase 2: Create and Edit Dialogs

**Estimated diff:** ~450 lines

**Prerequisites:** Phase 1 merged; ITER17-001 Phase 2 (update endpoint).

**Acceptance Criteria:**
- [ ] A create-tag button in the journals sidebar section opens a create dialog (name, colour, optional parent) matching `CreateTagDialog`.
- [ ] Right-click/context menu on a journal tag offers Edit, matching `TagContextMenu`.
- [ ] The management dialog supports editing name, colour, description, and parent — matching the corresponding `TagManagementDialog` fields exactly.
- [ ] Create/edit operations refresh the tag tree, the journals list, and any open journal detail tag editor via query invalidation.
- [ ] Reuse the contact dialog components generalised over domain, or structural copies with the consolidation recorded as follow-up — state the choice in the PR.

**Required Test Coverage:**
- **Unit (RTL):** dialog validation (name required, colour format), parent selection.
- **Integration:** covered by ITER17-001 backend tests.
- **E2E:** create a tag from the sidebar and assign it to a journal; rename a tag from the sidebar and see the new name on a tagged journal's detail page.

#### Phase 3: Delete and Merge Dialogs

**Estimated diff:** ~400 lines

**Prerequisites:** Phase 2 merged; ITER17-001 Phases 3–4 (delete/merge endpoints).

**Acceptance Criteria:**
- [ ] The context menu / management dialog offers Delete with confirmation, warning that the tag is removed from all journals — matching contact behaviour.
- [ ] The management dialog offers Merge into another tag, with target selection excluding the tag itself and its descendants — matching `TagManagementDialog`.
- [ ] Delete/merge operations refresh the tag tree, the journals list, and any open journal detail tag editor via query invalidation.

**Required Test Coverage:**
- **Unit (RTL):** delete confirmation flow, merge target selection excluding self/descendants.
- **Integration:** covered by ITER17-001 backend tests.
- **E2E:** delete a tag and verify it disappears from a journal that had it; merge two tags and verify assignments moved.

---

### ITER17-005: Journal Tag History Events

**Objective:** Publish tag domain events for journals so tag changes appear in the journal activity feed with provenance, matching contact tag history.
**Strategy:** Two phases on top of the Iteration 12 unified history foundation — assignment/removal events first (no ITER17-001 dependency), then management-operation events.

**Relevant documents:**
- [Activity History Product Specification](../product-specifications/activity-history-product-specification.md)
- Contact reference: `TagAssigned` / `TagRemoved` / `TagUpdated` / `TagDeleted` in `backend/app/core/contacts/models/events.py`; the history projection consumer.

#### Phase 1: Assignment and Removal Events

**Estimated diff:** ~450 lines

**Acceptance Criteria:**
- [ ] Journal tag assignment/removal (REST relationship endpoints and MCP create/update paths) publish journal-scoped `TagAssigned` / `TagRemoved` events within the same unit of work, carrying `tag_name`, `source`, and `changed_by` like the contact events.
- [ ] The history projection consumer maps these events into journal history rows (idempotent, `event_id`-keyed) and they render in the journal activity feed.

**Required Test Coverage:**
- **Unit:** event payload construction for assign and remove.
- **Integration:** end-to-end — assign/remove a tag → run projection → assert history rows with correct provenance; idempotent replay.
- **E2E:** add and remove a tag on a journal, assert the activity feed at the bottom of the journal page shows both entries.

#### Phase 2: Management Operation Events

**Estimated diff:** ~400 lines

**Prerequisites:** Phase 1 merged; ITER17-001 Phases 2–4 (update/delete/merge operations exist to emit events for).

**Acceptance Criteria:**
- [ ] Tag update/delete/merge publish the corresponding events (`TagUpdated` / `TagDeleted` / merge as the contact implementation models it); history entries on affected journals describe the change the same way contact history does.
- [ ] Search re-indexing of affected journals on tag delete/merge is driven by these events if ITER17-001 Phases 3–4 deferred it here.

**Required Test Coverage:**
- **Unit:** event payload construction for update, delete, and merge.
- **Integration:** update/delete/merge a tag → run projection → assert history rows on affected journals; search index consistency if reindexing is event-driven.
- **E2E:** rename a tag used by a journal, assert the journal's activity feed reflects the change.

## Data Model Summary

The only schema change is additive:

```sql
-- ITER17-001 Phase 1 — applied in migration 0102
ALTER TABLE journal_tags
  ADD COLUMN description TEXT NULL;
```

Deliberate, accepted asymmetries with contact tags (not to be "fixed" in this iteration):

- `journal_tags.id` is a UUID; contact `tags.id` is an Integer.
- Journal and contact tags are separate namespaces with separate endpoints (`/api/journals/tags` vs `/api/tags`), per the journal system specification.
- Contact `tags.name` has a path-format CHECK constraint (`^[a-zA-Z0-9_&-]+(/…)*$`) tied to Google Contacts group sync; journal tags have no sync and keep their current unconstrained names. If the create flows end up sharing UI validation, journal tags must not inherit the Google-specific constraint.

## Known Follow-up Work

- **`description` on tags embedded in journal resources:** Phase 1 added `description` to the standalone `/api/journals/tags` resources (its stated scope), but `JournalTagSchema` (`backend/app/api/journals/schemas.py`) and its converter — the shape used for tags embedded in `GET /api/journals/{id}` — still expose only id/name/color. Contacts embed description on the equivalent shape (`TagAttributes` in `backend/app/api/contacts/schemas.py`). ITER17-003 should add it when the detail-page editor needs to display a tag's description.
- **Rename `merge_tags` → `merge_contact_tags`:** Phase 1 renamed contacts' `list_tags` to `list_contact_tags` when `list_journal_tags` landed beside it. `merge_tags` is still contact-only and unscoped; rename it in ITER17-001 Phase 4 when the journal merge tool ships, so both namespaces stay symmetrically named.
- **Contact tag ID typing across MCP ([#1139](https://github.com/hjed/personal-management-system/issues/1139)):** `list_contact_tags` returns `TagInfo.id` as a string while the write tools (`merge_tags`, and `update_contact_tag` added in Phase 2) take ints, so an AI caller cannot round-trip an ID between them. Phase 2's new tool matched the existing `merge_tags` convention rather than fix half the surface. Align `TagInfo`, `UpdatedTagInfo`, `merge_tags`, and `update_contact_tag` in one change. Journal tags are unaffected — UUID-keyed and stringified consistently.
- **Shared tag component consolidation:** if ITER17-003/004 duplicate the contact editor/dialog components rather than generalising them, consolidate into shared domain-agnostic components afterwards.
- **Tags at journal creation time:** `JournalCreateForm.tsx` has no tag input (the API supports tags on create via MCP). Contacts likewise only edit tags from the detail/edit surfaces, so this is not a parity gap — treat as an independent enhancement if wanted.
- **Search document tag names:** the journal search document indexes `tag_ids` only, while the MCP search converter reads a non-existent `tag_names` field (`backend/app/mcp/domains/journals/converters.py` line ~225) and contact documents index tag names as searchable text. Aligning journal search to also index tag names (making journals findable by tag text) is a small follow-up once events from ITER17-005 exist to keep names fresh on rename.
- **Journal tag filter semantics doc:** record the OR-across-tags semantics (inherited from contacts) in the API design doc if it isn't already stated.

## Definition of Done for the Iteration

This iteration is complete when, for journal tags, a user can do everything they can do with contact tags:

- Edit tags on a journal through a searchable editor with inline tag creation and colour-coded badges
- Manage journal tags from the sidebar tree: create, rename, recolour, describe, re-parent, delete, and merge
- Filter the journals list by tag — from the sidebar, by URL, and with parent tags including child-tagged journals
- See tag changes in the journal activity feed with provenance
- Perform the same tag operations through MCP
- All phases keep `main` green with unit, integration, and e2e coverage, linting, and type checks passing
