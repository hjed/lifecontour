# Iteration 17: Journal Tags Parity

**Status:** 🔵 PLANNED
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

- **Database**: `journal_tags` (UUID PK, unique `name`, `parent_id` hierarchy, `color`) and `journal_tag_assignments` (composite PK `(journal_id, tag_id)`, cascade deletes) — migration `0012_create_journal_relationships_and_tags.py`. **No `description` column** (contact tags have one).
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
- **MCP**: `create_journal_entry` / `update_journal_entry` / journal reads support tags; `list_tags` and `merge_tags` MCP tools are **contact-only** (`backend/app/mcp/domains/contacts/tools.py`).
- **History**: no tag domain events for journals — tag changes do not appear in the journal activity feed (contacts publish `TagAssigned` / `TagRemoved` / `TagUpdated` / `TagDeleted` and project them into history).

### Gap summary

| Behaviour (contact tags reference) | Journal tags today | Gap |
|---|---|---|
| Inline editor: searchable add popover, create-new-tag with colour, dismissible colour badges | Plain select dropdown, no create, no colours, dead end when no tags exist | ITER17-003 |
| Sidebar hierarchical tag tree with click-to-filter | Absent | ITER17-004 |
| Tag management: edit name/colour/description/parent, delete, merge (context menu + dialogs) | Create only; delete 409s when in use; no update/merge | ITER17-001, ITER17-004 |
| `description` field on tags | Missing column | ITER17-001 |
| Delete removes tag from all entities | Delete blocked (409) when in use | ITER17-001 |
| Multi-tag filter param + hierarchical descendant expansion | Singular `tag_id`, first-selected-only, no hierarchy expansion | ITER17-002 |
| URL deep link (`?tag=`) on the list page | Absent | ITER17-002 |
| Tag change history in activity feed | No tag domain events | ITER17-005 |
| MCP tag management (list, merge) | Contact-only tools | ITER17-001 (with the matching API changes) |

## Delivery Rules

These rules apply to every task below:

1. **Tests first:** write the failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks are passing.
3. **Reviewable PRs:** keep each PR to roughly `<= 10` files where practical; split tasks into smaller slices if needed.
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

1. **ITER17-001** (backend management operations, REST + MCP delivered together per phase) unblocks the sidebar management UI.
2. **ITER17-002** (filtering parity) is independent of 001 and can run in parallel.
3. **ITER17-003** (detail-page editor) needs only existing endpoints and can start immediately.
4. **ITER17-004** (sidebar tree + management dialogs) depends on ITER17-001.
5. **ITER17-005** (history events) depends on ITER17-001 for update/delete/merge events; assignment events can land first if split.

## Task Breakdown

### ITER17-001: Journal Tag Management Backend (update, delete parity, merge, description) with MCP Parity

**Objective:** Give journal tags the same management operations as contact tags — full update (name, colour, description, parent), delete that un-assigns rather than blocks, and merge — exposed through **both REST and MCP in the same phase** as each capability lands.
**Strategy:** Two phases — schema + update first, then delete/merge behaviour change. Each phase ships its REST endpoint and the matching MCP tooling together.

**Relevant documents:**
- [Database Design — Migration Strategy](../architecture/database-design.md#migration-strategy)
- [API Design](../architecture/api-design.md) (REST and FastMCP patterns)
- Contact reference: `backend/app/core/contacts/services/tag_service.py`, `backend/app/api/tags/controllers.py`, and the MCP tools `list_tags` / `merge_tags` in `backend/app/mcp/domains/contacts/tools.py`
- Memory note: MCP tool documentation lives in docstrings/schemas, not in `mcp-setup.md`.
- MCP rules: MCP tools are controller-equivalent — they call `@transactional` services and never open transactions.

#### Phase 1: Description Column and Tag Update (REST + MCP)

**PR Size:** ~8-10 files

**Acceptance Criteria:**
- [ ] Alembic migration adds nullable `description TEXT` to `journal_tags` (follow the sequential naming convention in the `creating-migrations` skill).
- [ ] `JournalTag` domain model and repository read/write `description`.
- [ ] `JournalTagService.update_tag(tag_id, transaction, name, color, description, parent_id, set_parent_null)` mirroring the contact `TagService.update_tag` signature and validation:
  - name uniqueness (case-insensitive) with a clear validation error on conflict
  - colour format validation (7-char hex `#RRGGBB`)
  - parent hierarchy cycle prevention (a tag cannot become its own ancestor)
- [ ] `PATCH /api/journals/tags/{tag_id}` endpoint following the contact `PATCH /api/tags/{tag_id}` request/response shape.
- [ ] `GET /api/journals/tags` and `POST /api/journals/tags` include `description` in resources.
- [ ] **MCP (same phase):** journal tags are listable via MCP with hierarchy, colour, and description — either by extending the existing `list_tags` tool with a domain parameter or adding a journal-scoped equivalent (match whichever pattern the MCP domain structure prefers; document the choice) — and tag update is reachable via MCP to the same extent it is for contact tags (verify the contact baseline first and match it exactly).
- [ ] Write path commits via `@transactional`/`unit_of_work` in the service layer; MCP tools call the same `@transactional` service and do not open transactions.

**Required Test Coverage:**
- **Unit:** update validation (duplicate name, invalid colour, cycle prevention), set-parent-null semantics, MCP tool schema/serialisation.
- **Integration:** PATCH endpoint round-trip with real DB; uniqueness constraint behaviour; migration applies cleanly; MCP list/update tool tests mirroring the contact tag MCP tests.
- **E2E:** deferred to ITER17-004 (no UI surface yet); MCP integration tests are the equivalent bar for the tool surface.

#### Phase 2: Delete Parity and Merge (REST + MCP)

**PR Size:** ~8-10 files

**Acceptance Criteria:**
- [ ] `JournalTagService.delete_tag(tag_id, transaction)`: deleting a tag removes it from all journals (assignments cascade via existing FK) and deletes the tag — matching contact behaviour. The current 409-when-in-use guard in `DELETE /api/journals/tags/{tag_id}` is removed.
- [ ] Child tags of a deleted tag are re-parented to NULL (existing `ON DELETE SET NULL`), matching contact behaviour.
- [ ] `JournalTagService.merge_tag(source_id, target_id, transaction)` mirroring contact merge semantics:
  - all assignments of the source tag are repointed to the target (duplicate `(journal_id, tag_id)` rows resolved via `ON CONFLICT DO NOTHING`)
  - children of the source tag are re-parented to the target
  - the source tag is deleted
  - merging a tag into itself or into a descendant is rejected
- [ ] `POST /api/journals/tags/{tag_id}/merge` endpoint following the contact merge endpoint shape.
- [ ] **MCP (same phase):** journal tags can be merged via MCP, mirroring the contact `merge_tags` tool semantics and reusing `JournalTagService.merge_tag`; tag delete is reachable via MCP to the same extent it is for contact tags.
- [ ] Journals affected by delete/merge are re-indexed in MeiliSearch (their `tag_ids` change) — verify how contact tag events drive re-indexing and mirror it (may move to ITER17-005 if event-driven; state the choice in the PR).

**Required Test Coverage:**
- **Unit:** merge validation (self-merge, descendant-merge rejection), delete semantics, MCP merge tool schema/serialisation.
- **Integration:** merge with overlapping assignments (no duplicate-key failure), delete removes assignments from journals, hierarchy re-parenting, search index state after delete/merge, MCP merge/delete tool tests against a real DB.
- **E2E:** deferred to ITER17-004.

---

### ITER17-002: Journal List Tag Filtering Parity

**Objective:** Match contact list tag filtering: multiple tags, hierarchical descendant expansion, and URL deep-linking.
**Strategy:** Single phase — backend param upgrade plus frontend wiring.

**Relevant documents:**
- Contact reference: `_expand_tag_ids_with_descendants` in `backend/app/core/contacts/services/contact_service.py`; `useTagFilter` hook.

#### Phase 1: Multi-Tag, Hierarchical, URL-Driven Filtering

**PR Size:** ~7-9 files

**Acceptance Criteria:**
- [ ] `GET /api/journals` accepts repeated `tag_ids` query params (list), keeping `tag_id` working for backward compatibility (or migrating all callers in the same PR — state the choice).
- [ ] Tag filtering expands each requested tag to include all descendant tags before querying, matching contact behaviour (a journal tagged only with a child tag appears when filtering by the parent).
- [ ] Multiple tags combine the same way the contacts list combines them (verify: contacts use a single JOIN over the expanded ID set, i.e. logical OR across tags — replicate exactly).
- [ ] `fetchJournals` sends **all** selected tags, not just the first.
- [ ] `/journals?tag=<id>` deep link filters the list (reuse or generalise `useTagFilter`), and the filter UI reflects the URL state.
- [ ] `JournalFilters.tsx` checkbox behaviour is unchanged from the user's perspective apart from now actually applying every selected tag.

**Required Test Coverage:**
- **Unit:** descendant expansion logic; frontend filter param construction.
- **Integration:** repository/service filter tests — parent tag returns child-tagged journals; multi-tag combinations; combined with type/date filters (existing AND semantics preserved).
- **E2E:** filter journals by a parent tag and assert a child-tagged journal appears; deep-link `/journals?tag=` renders a filtered list.

---

### ITER17-003: Journal Detail Tag Editor Parity

**Objective:** Replace the select-dropdown tag UI on the journal detail page with an editor matching `ContactTagsEditor` exactly: searchable add popover, inline create-new-tag with colour picker, dismissible colour-coded badges.
**Strategy:** Single phase. Prefer extracting a shared, domain-agnostic tags editor component parameterised over the tag type and mutation hooks; if extraction proves too large, build `JournalTagsEditor` as a structural copy and record consolidation as follow-up.

**Relevant documents:**
- [Frontend Design — Component Architecture](../architecture/frontend-design.md#component-architecture)
- Contact reference: `frontend/src/components/contacts/ContactTagsEditor.tsx`, `TAG_COLORS` in `frontend/src/lib/constants.ts`

#### Phase 1: Tags Editor Component

**PR Size:** ~6-9 files

**Acceptance Criteria:**
- [ ] Assigned tags render as dismissible badges with the tag colour (border/dot styling identical to the contact editor).
- [ ] Adding a tag opens a searchable popover listing unassigned tags filtered by the query (autocomplete), not a plain select.
- [ ] When the search query matches no existing tag, the user can create a new tag inline with name + colour (from `TAG_COLORS`), which is created via `POST /api/journals/tags` and immediately assigned.
- [ ] The add affordance is available even when there are no unassigned tags or no tags at all (the create flow is always reachable) — fixing the current dead end.
- [ ] Duplicate assignment is prevented in the UI; already-assigned tags do not appear in the add list.
- [ ] Mutations use the existing `useAddJournalTag` / `useRemoveJournalTag` / journal-tag query hooks with cache invalidation, and errors surface to the user (toast), not only `console.error`.
- [ ] `JournalDetailView.tsx` uses the new editor; the old `JournalTagBadge` select flow is removed (keep the read-only badge rendering if still used elsewhere).
- [ ] Existing journal-detail tag e2e tests are updated to the new interaction and still cover add + remove.
- [ ] Accessibility matches the contact editor: labelled controls, keyboard operability, `aria-label` on remove buttons.

**Required Test Coverage:**
- **Unit (RTL):** mirror `ContactTagsEditor.test.tsx` — open/close, search filtering, add existing, create new (name + colour), remove, duplicate prevention, error handling.
- **Integration:** mutation hook tests if new hooks are added (mirror `contact-tag-mutations.test.ts`).
- **E2E:** on a journal detail page — add an existing tag, create a brand-new tag inline and see it assigned with its colour, remove a tag. Use fixture-created data; ProseMirror/typing-delay best practices where applicable.

---

### ITER17-004: Sidebar Journal Tag Tree and Tag Management UI

**Objective:** Add a hierarchical journal tag tree to the Journals sidebar section with the same management affordances as contacts: expand/collapse, click-to-filter, context menu with edit / delete / merge dialogs, and a create-tag button.
**Strategy:** Two phases — read-only tree + navigation first, management dialogs second.

**Prerequisites:** ITER17-001 (update/delete/merge endpoints), ITER17-002 (`/journals?tag=` deep link).

**Relevant documents:**
- Contact reference: `Sidebar.tsx` (TagTreeNavigation, TagTreeItem), `buildTagTree.ts`, `TagContextMenu.tsx`, `TagManagementDialog.tsx`, `CreateTagDialog.tsx`

#### Phase 1: Sidebar Tree and Navigation

**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] The Journals sidebar section renders the journal tag tree (nested by `parent_id`) below the existing links, visually and behaviourally identical to the contacts tag tree (expand/collapse chevrons, truncation, icons).
- [ ] `buildTagTree` is reused (generalised over the two tag resource shapes if needed) rather than duplicated.
- [ ] Clicking a tag navigates to `/journals?tag=<id>` and the list filters accordingly (including descendant expansion from ITER17-002); the active tag is highlighted and "All Journals" is not.
- [ ] Loading and error states match the contacts sidebar behaviour.

**Required Test Coverage:**
- **Unit (RTL):** sidebar renders journal tag tree from fixture data; expand/collapse; active-state logic with `?tag=` present.
- **Integration:** n/a beyond RTL (no new backend).
- **E2E:** create tags (parent + child) via API fixtures, open sidebar, expand parent, click child tag, assert the journals list is filtered.

#### Phase 2: Create, Edit, Delete, Merge Dialogs

**PR Size:** ~6-9 files

**Acceptance Criteria:**
- [ ] A create-tag button in the journals sidebar section opens a create dialog (name, colour, optional parent) matching `CreateTagDialog`.
- [ ] Right-click/context menu on a journal tag offers Edit and Delete (and Merge inside the management dialog), matching `TagContextMenu`.
- [ ] The management dialog supports editing name, colour, description, and parent; deleting (with confirmation, warning that the tag is removed from all journals); and merging into another tag — matching `TagManagementDialog` field-for-field.
- [ ] All operations refresh the tag tree, the journals list, and any open journal detail tag editor via query invalidation.
- [ ] Reuse the contact dialog components generalised over domain, or structural copies with the consolidation recorded as follow-up — state the choice in the PR.

**Required Test Coverage:**
- **Unit (RTL):** dialog validation (name required, colour format), delete confirmation flow, merge target selection excluding self/descendants.
- **Integration:** covered by ITER17-001 backend tests.
- **E2E:** rename a tag from the sidebar and see the new name on a tagged journal's detail page; delete a tag and verify it disappears from a journal that had it; merge two tags and verify assignments moved.

---

### ITER17-005: Journal Tag History Events

**Objective:** Publish tag domain events for journals so tag changes appear in the journal activity feed with provenance, matching contact tag history.
**Strategy:** Single phase on top of the Iteration 12 unified history foundation.

**Prerequisites:** ITER17-001 (update/delete/merge operations exist to emit events for).

**Relevant documents:**
- [Activity History Product Specification](../product-specifications/activity-history-product-specification.md)
- Contact reference: `TagAssigned` / `TagRemoved` / `TagUpdated` / `TagDeleted` in `backend/app/core/contacts/models/events.py`; the history projection consumer.

#### Phase 1: Events and History Projection

**PR Size:** ~7-9 files

**Acceptance Criteria:**
- [ ] Journal tag assignment/removal (REST relationship endpoints and MCP create/update paths) publish journal-scoped `TagAssigned` / `TagRemoved` events within the same unit of work, carrying `tag_name`, `source`, and `changed_by` like the contact events.
- [ ] Tag update/delete/merge publish the corresponding events; history entries on affected journals describe the change the same way contact history does.
- [ ] The history projection consumer maps these events into journal history rows (idempotent, `event_id`-keyed) and they render in the journal activity feed.
- [ ] Search re-indexing of affected journals on tag delete/merge is driven by these events if ITER17-001 Phase 2 deferred it here.

**Required Test Coverage:**
- **Unit:** event payload construction for each operation.
- **Integration:** end-to-end — assign/remove/merge a tag → run projection → assert history rows with correct provenance; idempotent replay.
- **E2E:** add and remove a tag on a journal, assert the activity feed at the bottom of the journal page shows both entries.

## Data Model Summary

The only schema change is additive:

```sql
-- ITER17-001 Phase 1
ALTER TABLE journal_tags
  ADD COLUMN description TEXT NULL;
```

Deliberate, accepted asymmetries with contact tags (not to be "fixed" in this iteration):

- `journal_tags.id` is a UUID; contact `tags.id` is an Integer.
- Journal and contact tags are separate namespaces with separate endpoints (`/api/journals/tags` vs `/api/tags`), per the journal system specification.
- Contact `tags.name` has a path-format CHECK constraint (`^[a-zA-Z0-9_&-]+(/…)*$`) tied to Google Contacts group sync; journal tags have no sync and keep their current unconstrained names. If the create flows end up sharing UI validation, journal tags must not inherit the Google-specific constraint.

## Known Follow-up Work

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
