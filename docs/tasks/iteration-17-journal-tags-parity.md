# Iteration 17: Journal Tags Parity

**Status:** 🟡 IN PROGRESS (ITER17-001 complete — Phases 1–4; ITER17-002 complete — Phases 1–2; ITER17-003 complete — Phases 1–2)
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
  - `DELETE /api/journals/tags/{tag_id}` — ✅ un-assigns the tag from all journals and deletes it, matching contact behaviour (the 409-when-in-use guard was removed in ITER17-001 Phase 3)
  - `POST /api/journals/tags/{tag_id}/merge` — ✅ folds a tag into another and deletes it (ITER17-001 Phase 4)
  - `POST /api/journals/{id}/relationships/tags`, `DELETE /api/journals/{id}/relationships/tags/{tag_id}`
  - `GET /api/journals?tag_ids=` filter — repeatable, expands each tag to its descendants (ITER17-002 Phase 1); singular `tag_id` still accepted and unioned in
- **Service/repository**: `JournalTagService.create_tag` only; repository (`journal_tag_repository.py`) supports `find_by_name` (case-insensitive), `get_all`, `get_children`, `get_root_tags`, `get_tags_for_journal`, `save`. **No update / delete-with-unassign / merge service methods.**
- **Frontend**:
  - `JournalDetailView.tsx` mounts `JournalTagsEditor` — the journal adapter over the shared `TagsEditor` — giving the detail page a searchable add popover, inline create-with-colour, and dismissible colour-coded badges, with the add affordance always reachable (ITER17-003 Phases 1–2). The legacy select-dropdown `JournalTagBadge.tsx` was deleted.
  - `JournalFilters.tsx` has a multi-select checkbox tag filter, and `fetchJournals` (`frontend/src/lib/api/journals.ts`) sends **every** selected tag as repeated `tag_ids` (ITER17-002 Phase 2).
  - `JournalListItem.tsx` already renders colour-coded tag chips on list items.
  - No journal tag tree in the sidebar (`Sidebar.tsx` renders the tag tree for contacts only). The `?tag=` deep link on `/journals` shipped in ITER17-002 Phase 2, so the sidebar tree has a destination to link to.
  - `JournalCreateForm.tsx` has no tag input.
- **Search**: `journal_indexing_service.py` indexes `tag_ids` as a filterable field.
- **MCP**: `create_journal_entry` / `update_journal_entry` / journal reads support tags. Journal tag listing shipped in ITER17-001 Phase 1 as `list_journal_tags`, alongside which contacts' `list_tags` was renamed `list_contact_tags`; Phase 2 added `update_journal_tag` / `update_contact_tag`, Phase 3 added `delete_journal_tag` / `delete_contact_tag`, and Phase 4 added `merge_journal_tag` while renaming contacts' `merge_tags` to `merge_contact_tags`. The journal and contact tag tool surfaces are now symmetric.
- **History**: no tag domain events for journals — tag changes do not appear in the journal activity feed (contacts publish `TagAssigned` / `TagRemoved` / `TagUpdated` / `TagDeleted` and project them into history).

### Gap summary

| Behaviour (contact tags reference) | Journal tags today | Gap |
|---|---|---|
| Inline editor: searchable add popover, create-new-tag with colour, dismissible colour badges | ✅ Closed — the shared `TagsEditor` is mounted on the journal detail page and the select-dropdown `JournalTagBadge` is deleted (Phases 1–2) | ITER17-003 |
| Sidebar hierarchical tag tree with click-to-filter | Absent | ITER17-004 |
| Tag management: edit name/colour/description/parent, delete, merge (context menu + dialogs) | ✅ Backend closed — create, update, delete and merge (Phases 1–4); the UI surface remains | ITER17-004 |
| `description` field on tags | ✅ Closed — column added in ITER17-001 Phase 1 | ITER17-001 |
| Delete removes tag from all entities | ✅ Closed — delete un-assigns rather than blocking, ITER17-001 Phase 3 | ITER17-001 |
| Multi-tag filter param + hierarchical descendant expansion | ✅ Closed — repeated `tag_ids` with descendant expansion (ITER17-002 Phase 1); the frontend sends every selected tag (Phase 2) | ITER17-002 |
| URL deep link (`?tag=`) on the list page | ✅ Closed — `/journals?tag=<id>` via the generalised `useTagFilter` (ITER17-002 Phase 2) | ITER17-002 |
| Tag change history in activity feed | No tag domain events | ITER17-005 |
| MCP tag management (list, merge) | ✅ Closed — `list_journal_tags` (Phase 1), `update_journal_tag` (Phase 2), `delete_journal_tag` (Phase 3), `merge_journal_tag` (Phase 4) | ITER17-001 |

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
- Contact reference: `backend/app/core/contacts/services/tag_service.py`, `backend/app/api/tags/controllers.py`, and the MCP tools `list_contact_tags` (renamed from `list_tags` in Phase 1) / `merge_contact_tags` (renamed from `merge_tags` in Phase 4) in `backend/app/mcp/domains/contacts/tools.py`
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
- **Contacts' `list_tags` renamed to `list_contact_tags`** so the two namespaces are symmetrically named and neither tool is the ambiguous default. This is a breaking rename for MCP clients, which is acceptable because clients re-fetch the tool list on each session. Each tool's docstring now points at the other. `merge_tags` kept its name for now — it was renamed to `merge_contact_tags` in Phase 4 when the journal merge tool landed beside it.

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
- **`mcp_unified_error_handler` now recognises contacts' `TagNotFoundError` and `DuplicateTagNameError`.** It already special-cased `ContactNotFoundError`, `ContactValidationError`, and the whole `JournalDomainError` tree, but contacts' tag errors fell through to the catch-all — so an unknown tag id came back as a generic "an error occurred" that callers could not distinguish from a server failure. Surfaced by review of `update_contact_tag`; the fix also improves the pre-existing merge tool (renamed `merge_contact_tags` in Phase 4).
- **Clearing a parent over MCP uses a `move_to_root` boolean**, not a null `parent_id`. MCP arguments cannot distinguish "omitted" from "explicitly null", so the REST `set_parent_null` signal needs an explicit argument at the tool boundary. REST keeps the contact-style explicit-null convention.
- **An explicit parent wins over the clear-parent flag** when a caller supplies both, so the two MCP tools cannot diverge on the same argument pair. Unreachable via REST (the controller only sets `set_parent_null` when `parent_id` is explicitly null), but reachable via MCP. Review of this phase surfaced that contacts' `TagService._apply_parent_change` had a flat `if parent_id is not None and tag.parent_id != parent_id: ... elif set_parent_null:` — so passing a `parent_id` **equal to the current parent** alongside the clear flag fell through and cleared it. That condition is now nested to match the journal implementation; it was latent before this phase because only the new MCP tool can reach the combination.
- **Duplicate names and cycles map to `JournalValidationError` (400)**, not the contacts' `DuplicateTagNameError` (409) / `ContactValidationError` (422). This matches the existing journal tag *create* path, which already returns 400 for a duplicate name; journal-domain internal consistency was preferred over cross-domain status-code parity.
- **Split into two commits** because the two-domain MCP work pushed the diff to ~900 lines, past the 500-line PR standard: (A) service + hierarchy validation + REST PATCH, (B) both MCP tools.
- **`_journal_tag_resource` helper extracted** in `backend/app/api/journals/controllers.py` — the list, create, and new update endpoints all built the same JSON:API resource dict by hand.

**Required Test Coverage:**
- **Unit:** update validation (duplicate name, invalid colour, cycle prevention), set-parent-null semantics, MCP tool schema/serialisation. — `tests/unit/journal/test_journal_tag_service.py` (`TestUpdateTag`, 13 tests), `tests/unit/journal/test_journal_tag_schemas.py` (`TestJournalTagUpdateAttributes`), `tests/unit/mcp/domains/journals/test_tools.py` + `tests/unit/mcp/domains/contacts/test_tools.py` (tool schema tests)
- **Integration:** PATCH endpoint round-trip with real DB; uniqueness constraint behaviour; MCP update tool test. — `tests/integration/api/test_journal_tag_endpoints.py` (`TestUpdateJournalTagEndpoint`, 14 tests), `tests/integration/journal/test_journal_tag_repository_integration.py` (re-parent round-trip, case-insensitive lookup), `tests/integration/mcp/test_journal_tag_mcp.py` (`TestUpdateJournalTagMCPTool`, 8 tests), `tests/integration/mcp/test_contact_tools_integration.py` (2 `update_contact_tag` tests)
- **E2E:** deferred to ITER17-004 — no frontend surface edits journal tags, and `JournalTag` in `frontend/src/types/journals.ts` still carries only id/name/color. Deferral taken as stated.

#### Phase 3: Delete Parity (REST + MCP) ✅ COMPLETE

**Estimated diff:** ~400 lines · **Actual:** ~630 changed lines (~520 added, ~110 removed), split into two commits: (A) service + REST + their tests, (B) both MCP tools + their tests.

**Acceptance Criteria:**
- [x] `JournalTagService.delete_tag(tag_id, transaction)`: deleting a tag removes it from all journals (assignments cascade via existing FK) and deletes the tag — matching contact behaviour. The current 409-when-in-use guard in `DELETE /api/journals/tags/{tag_id}` is removed. — the usage-count query and `JournalTagInUseError` are gone; the service now does find-by-id → `JournalTagNotFoundError` (404) → `tag_repo.delete`.
- [x] Child tags of a deleted tag are re-parented to NULL (existing `ON DELETE SET NULL`), matching contact behaviour. — no application code needed; locked in by repository integration tests against the real FK.
- [x] **MCP (same phase):** tag delete is reachable via MCP to the same extent it is for contact tags. — added `delete_journal_tag` **and** `delete_contact_tag` (see decisions below).
- [x] Journals affected by delete are re-indexed in MeiliSearch — **deferred to ITER17-005 Phase 2** (see decisions below).

**Decisions taken (Phase 3):**
- **Re-indexing deferred to ITER17-005 Phase 2.** Re-indexing is event-driven, and journal tags publish no domain events yet — so there is nothing to hook. Contacts are the reference and they behave the same way: `TagAssigned`/`TagRemoved` re-index a contact, but `TagDeleted` does not. Mirroring contacts therefore means shipping no re-indexing here, and the journal tag domain events in ITER17-005 Phase 2 are the correct home for it.
- **Delete tools added in both domains.** As in Phase 2 with update, the contact baseline exposed **no** delete tool, so "match it exactly" would have shipped zero MCP work and violated delivery rule 7. The phase added `delete_journal_tag` and `delete_contact_tag`, each docstring pointing at the other, matching the Phase 1/2 naming convention.
- **`JournalTagInUseError` removed rather than deprecated.** Nothing raised it once the guard was gone and no caller caught it; leaving the class behind would imply the 409 path still existed.
- **The existence check moved from the controller into the service.** Previously the controller pre-checked via `JournalTagRepository` and raised its own 404, which meant the controller took a repository dependency purely for validation. The service now owns it and raises `JournalTagNotFoundError`, which the existing journal domain error handler already maps to 404 — so the controller dropped its `tag_repo` dependency and its bespoke `HTTPException`. This also gives the MCP tool the same 404 semantics for free.
- **No frontend change was needed:** no frontend code calls `DELETE /api/journals/tags/{id}`, so the removed 409 path had no client. `api-design.md` likewise needed no change — it documented no 409-on-delete contract for journal tags. `journal-system-specification.md` **did** need updating: it described DELETE as a bare 204, so it now states the un-assign and child-re-parenting semantics alongside the 400/404 responses.

**Required Test Coverage:**
- **Unit:** delete semantics (assignments removed, children re-parented to NULL). — `tests/unit/journal/test_journal_tag_service.py` (`TestDeleteTag`: deletes when unused, deletes when in use with no usage query issued, 404 on unknown id), plus `delete_journal_tag` / `delete_contact_tag` tool-schema tests in `tests/unit/mcp/domains/{journals,contacts}/test_tools.py`
- **Integration:** delete removes assignments from journals with real DB; hierarchy re-parenting; MCP delete tool test. — `tests/integration/api/test_journal_tag_endpoints.py` (`TestDeleteJournalTagEndpoint`, 5 tests), `tests/integration/journal/test_journal_tag_repository_integration.py` (`test_delete_cascades_assignments`, `test_delete_sets_child_parent_id_null`), `tests/integration/mcp/test_journal_tag_mcp.py` (`TestDeleteJournalTagMCPTool`, 4 tests), `tests/integration/mcp/test_contact_tools_integration.py` (2 `delete_contact_tag` tests). Search index state after delete is not asserted — see the re-indexing deferral above.
- **E2E:** deferred to ITER17-004 Phase 3 — no frontend surface deletes journal tags in this phase; the MCP integration tests are the equivalent bar for the tool surface. Deferral taken as stated.

#### Phase 4: Tag Merge (REST + MCP) ✅ COMPLETE (except the re-indexing criterion, deferred to ITER17-005 Phase 2)

**Estimated diff:** ~500 lines · **Actual:** ~1050 changed lines, split into two commits: (A) repository + service + REST + their tests (~680), (B) both MCP tools + their tests (~380).

**Acceptance Criteria:**
- [x] `JournalTagService.merge_tag(source_id, target_id, transaction)` mirroring contact merge semantics:
  - all assignments of the source tag are repointed to the target — duplicates are resolved by **deleting the source rows the journal already holds for the target before the `UPDATE`**, not by `ON CONFLICT DO NOTHING` (see decisions below)
  - children of the source tag are re-parented to the target
  - the source tag is deleted
  - merging a tag into itself or into a descendant is rejected
- [x] `POST /api/journals/tags/{tag_id}/merge` endpoint following the contact merge endpoint shape. — 204 No Content, JSON:API body carrying `target_tag_id`.
- [x] **MCP (same phase):** journal tags can be merged via MCP, mirroring the contact `merge_tags` tool semantics and reusing `JournalTagService.merge_tag`. — added `merge_journal_tag`; contacts' `merge_tags` **renamed to `merge_contact_tags`** (see decisions below).
- [ ] Journals affected by merge are re-indexed in MeiliSearch — **NOT DONE, deferred to ITER17-005 Phase 2** as Phase 3 anticipated (see decisions below). Left unticked deliberately: the work is not done, only justified. **Known consequence until then:** a merged journal's search document keeps `tag_ids` pointing at the deleted source tag, so tag-filtered search returns stale results until that journal is next re-indexed for another reason.

**Decisions taken (Phase 4):**
- **The merge SQL lives in the repository, not the service.** Contacts' `TagService.merge_tags` inlines three `text()` statements straight into the service using the injected transaction. The journal domain keeps services SQL-free per ports-and-adapters, and every other journal service already does, so the row work went into `JournalTagRepository.merge_into(source_id, target_id)` and `merge_tag` holds only validation and delegation. Deliberate, justified divergence from the contact reference under delivery rule 4.
- **Dedupe is a pre-`DELETE`, not `ON CONFLICT DO NOTHING`.** The acceptance criterion as written named the wrong mechanism: the conflicting statement is an `UPDATE ... SET tag_id`, and `ON CONFLICT` is only available on `INSERT`. The source rows whose journal already carries the target are deleted first, which is also exactly what contacts' `merge_tags` and `repoint_tags` do. `test_merge_into_dedupes_overlapping_assignments` was verified to fail with a duplicate-key violation when that step is removed.
- **Validation errors map to `JournalValidationError` (400) and `JournalTagNotFoundError` (404)**, where contacts raise a bare `ValueError` the controller converts to 400. This follows the Phase 2 decision to keep journal-domain internal consistency over cross-domain status-code parity.
- **`merge_into` defends the self-parent case itself rather than trusting its caller.** When the target is a child of the source, the naive child-adoption `UPDATE` would set `target.parent_id = target` — a self-cycle that would poison every later ancestry walk. `validate_merge_target` already rejects that combination, so the path is unreachable through the service, but the repository is directly callable and its integration tests exercise it directly. Step 3 therefore uses `CASE WHEN id = :target_id THEN NULL`, promoting the target to the root (the position the source it replaces vacated). This matches the precedent in migration `0048_case_insensitive_tags.py`, which guards the same shape. Pinned by `test_merge_into_target_that_is_a_child_of_source`.
- **The ancestry walk was refactored to report *which* condition it hit.** `_check_circular_reference` previously raised for both "found the tag" and "the data contains a cycle", so merge's re-labelling wrapper reported a genuine corrupt-data cycle as "Cannot merge a tag into its own descendant" — pointing the caller at the wrong problem. The walk now returns a `_AncestryWalk` outcome (`FOUND` / `CYCLE` / `CLEAR`) and each caller phrases its own error, blaming `parent_id` or `target_tag_id` as appropriate.
- **No row locking, matching contacts.** Validation and the merge writes share one REQUEST-scoped connection and therefore one transaction, but there is no `SELECT ... FOR UPDATE`, so concurrent `A→B` and `B→A` merges could both validate before either executes. Contacts' `merge_tags` has the identical weakness; this is faithful parity rather than a new defect, and a single-user system makes it theoretical. Recorded rather than silently inherited.
- **Descendant detection reuses the shared ancestry walk.** The target is a descendant of the source exactly when the source appears in the target's ancestry — the same walk re-parenting already makes — so `validate_merge_target` calls `_walk_ancestry` rather than duplicating it, and raises against `target_tag_id`. The walk's `visited` set means a corrupt parent cycle in the data cannot spin the request forever — covered by `test_merge_terminates_on_cyclic_ancestry`, which also asserts the cycle is *not* misreported as a descendant-merge.
- **`merge_tags` renamed to `merge_contact_tags`**, closing the follow-up item Phase 1 recorded when `list_tags` became `list_contact_tags`. Breaking for MCP clients, acceptable on the same grounds as Phase 1 (clients re-fetch the tool list each session). The contacts `TagService.merge_tags` *service* method keeps its name — only the tool is renamed. Each tool's docstring points at the other.
- **Re-indexing deferred to ITER17-005 Phase 2**, matching Phase 3's delete deferral and the expectation ITER17-005 Phase 2 already records. Re-indexing is event-driven, journal tags publish no domain events yet, and contacts do not re-index on tag merge either. Search index state after merge is therefore not asserted here.
- **Commit A ran to ~680 lines, over the 500-line standard.** The service/REST slice was not further splittable without shipping an endpoint whose service did not exist (violating delivery rule 9), and roughly half of it is test code. Recorded rather than hidden.

**Required Test Coverage:**
- **Unit:** merge validation (self-merge, descendant-merge rejection), MCP merge tool schema/serialisation. — `tests/unit/journal/test_journal_tag_service.py` (`TestMergeTag`, 8 tests: delegation, unrelated-target-with-parent, self-merge, unknown source, unknown target, direct descendant, deep descendant, cyclic-ancestry termination), `tests/unit/journal/test_journal_tag_schemas.py` (`TestJournalTagMergeRequest`, 3 tests), `tests/unit/mcp/domains/journals/test_tools.py` (`test_merge_journal_tag_tool_schema`) and `tests/unit/mcp/domains/contacts/test_tools.py` (`test_merge_contact_tags_tool_schema`, which also asserts the old `merge_tags` name is gone). Tool **serialisation** is covered at the integration level, not here — `test_merge_journal_tag_moves_assignments_and_children` pins the response `summary` names both tags and reports the deletion.
- **Integration:** merge with overlapping assignments (no duplicate-key failure), hierarchy re-parenting, ~~search index state after merge~~ (struck: nothing re-indexes on merge, per the deferral above — this bullet has no implementation to test), MCP merge tool test against a real DB. — `tests/integration/journal/test_journal_tag_repository_integration.py` (5 tests: re-point, dedupe overlap, re-parent children, target-is-a-child-of-source self-parent guard, source deleted), `tests/integration/api/test_journal_tag_endpoints.py` (`TestMergeJournalTagEndpoint`, 10 tests), `tests/integration/mcp/test_journal_tag_mcp.py` (`TestMergeJournalTagMCPTool`, 6 tests), `tests/integration/mcp/test_contact_tools_integration.py` (2 tests covering the renamed tool and the absence of the old name).
- **E2E:** deferred to ITER17-004 Phase 3 — no frontend surface merges journal tags in this phase; the MCP and API integration tests are the equivalent bar. Deferral taken as stated.

---

### ITER17-002: Journal List Tag Filtering Parity

**Objective:** Match contact list tag filtering: multiple tags, hierarchical descendant expansion, and URL deep-linking.
**Strategy:** Two phases — backend param upgrade first, then frontend wiring — to stay within the 500-line diff standard.

**Relevant documents:**
- Contact reference: `_expand_tag_ids_with_descendants` in `backend/app/core/contacts/services/contact_service.py`; `useTagFilter` hook.

#### Phase 1: Backend Multi-Tag and Hierarchical Filtering ✅ COMPLETE

**Estimated diff:** ~450 lines · **Actual:** ~190 lines of production code plus ~530 lines of tests

**Acceptance Criteria:**
- [x] `GET /api/journals` accepts repeated `tag_ids` query params (list), keeping `tag_id` working for backward compatibility (or migrating all callers in the same PR — state the choice). — **`tag_id` kept** and unioned with `tag_ids` (see decisions below).
- [x] Tag filtering expands each requested tag to include all descendant tags before querying, matching contact behaviour (a journal tagged only with a child tag appears when filtering by the parent). — new `JournalTagRepository.get_descendants_for_tags` recursive CTE + `JournalTagHierarchyService.get_all_descendants_bulk` + `JournalService._expand_tag_ids_with_descendants`.
- [x] Multiple tags combine the same way the contacts list combines them (verify: contacts use a single JOIN over the expanded ID set, i.e. logical OR across tags — replicate exactly). — verified: contacts use a single `JOIN` + `tag_id IN (...)` + `SELECT DISTINCT` (`_build_contact_filter_query_parts`); the journal repository's `_add_relationship_filters` now does the same over `journal_tag_assignments` and keeps its existing `DISTINCT`.

**Decisions taken (Phase 1):**
- **`tag_id` (singular) retained rather than migrated.** The journal list UI still sends it and the frontend migration is ITER17-002 Phase 2, which must not depend on this phase shipping first (the "every phase is shippable" rule). The controller unions `tag_id` into `tag_ids`, so either spelling — or both at once — works.
- **The legacy `tag_id` now expands to descendants too.** Applying expansion to only the new param would have made the two spellings behave differently, and Phase 2's switch to `tag_ids` would have silently changed results. Behaviour change is deliberate and matches the contacts contract.
- **Expansion lives in the service, not the repository or controller**, mirroring `ContactService._expand_tag_ids_with_descendants`. `JournalService` takes `JournalTagHierarchyService` as an **optional** constructor dependency (like the existing optional `contact_relationship_repo`) so the many direct constructions in tests and workers keep working; without it, tag filtering simply stays flat rather than failing.
- **Both query params are typed `UUID` at the controller**, so a malformed id is a **400 validation error** instead of the **500** it produced before this phase (asyncpg raises `DataError` when binding a non-UUID to the `uuid` column — verified against the running database, not assumed). Contacts get this for free from `list[int]`; journals needed the annotation. Ids are converted back to strings for the service/repository, which already bound them as strings. The service still skips unparseable ids when calling the hierarchy lookup, as defence in depth for non-REST callers.
- **Repository params renamed `tag_id` → `tag_ids`** on `JournalRepository.get_all` / `count_all`. All call sites (MCP tools, the daily-summary assembler, `JournalService`) pass by keyword, so the rename is contained.

**Required Test Coverage:**
- **Unit:** descendant expansion logic. — `tests/unit/journal/test_journal_service.py` (`TestTagFilterExpansion`, 7 tests: multi-level expansion for list and count, dedup across tags, leaf pass-through, no-filter short-circuit, malformed uuid, missing-hierarchy fallback), `tests/unit/journal/test_journal_tag_hierarchy_service.py` (`TestGetAllDescendantsBulk`, 2 tests)
- **Integration:** repository/service filter tests — parent tag returns child-tagged journals; multi-tag combinations; combined with type/date filters (existing AND semantics preserved). — `tests/integration/journal/test_journal_tag_repository_integration.py` (`TestGetDescendantsForTags`, 6 tests), `tests/integration/journal/test_journal_repository_integration.py` (union, DISTINCT/count, AND with date range, empty list), `tests/integration/api/test_journal_tag_endpoints.py` (`TestJournalHierarchicalTagFiltering`, 9 tests: parent→child, root→grandchild, no upward expansion, multi-`tag_ids` union with `meta.total_count`, both-tags-counted-once, legacy `tag_id` expansion, `tag_id`+`tag_ids` union, AND with `type`, unknown tag, malformed id → 400)
- **E2E:** existing journal list filter specs continue to pass (frontend behaviour unchanged this phase). — `frontend/tests/e2e/journals-list.spec.ts` tag filter (still asserts the singular `tag_id` request), run on Chromium.

#### Phase 2: Frontend Multi-Tag Params and URL Deep Link ✅ COMPLETE

**Estimated diff:** ~350 lines · **Actual:** ~200 lines of production code plus ~500 lines of tests

**Prerequisites:** Phase 1 merged.

**Acceptance Criteria:**
- [x] `fetchJournals` sends **all** selected tags, not just the first. — one repeated `tag_ids` param per selected tag in `frontend/src/lib/api/journals.ts`; `useJournals` and `useInfiniteJournals` both route through it, so both gained multi-tag support with no further change.
- [x] `/journals?tag=<id>` deep link filters the list (reuse or generalise `useTagFilter`), and the filter UI reflects the URL state. — `useTagFilter` gained an optional `basePath` (default `/contacts`); `/journals` passes `'/journals'`. The page merges the URL tag into `effectiveFilters`, which feeds both the query **and** `JournalFilters`, so the tag's checkbox renders checked.
- [x] `JournalFilters.tsx` checkbox behaviour is unchanged from the user's perspective apart from now actually applying every selected tag. — the component is untouched; it was already controlled and already accumulated into `tag_ids`.

**Decisions taken (Phase 2):**
- **`useTagFilter` generalised with a defaulted `basePath` rather than a second hook.** The whole hook differed only in the literal `/contacts`; a defaulted parameter keeps every contact call site and its existing tests untouched, satisfying delivery rule 5 (reuse before rebuild).
- **The URL is the single source of truth for the deep-linked tag.** `filters.tag_ids` holds only panel-selected tags; `effectiveFilters` unions the URL tag in for querying and display, and `handleFiltersChange` strips it back out. Unchecking the URL tag calls `clearTag()` rather than storing a contradictory local state, so the URL and the UI can never disagree.
- **The page was split into `JournalsPage` (Suspense boundary) and `JournalsPageContent`**, matching `/contacts` — `useSearchParams` requires a Suspense boundary in the app router.
- **Contacts-parity heading added** ("<Tag> Journals" plus a matching subtitle and the `Tag` icon) although the acceptance criteria did not require it. Delivery rule 4 makes the contacts implementation the specification, and it gives the deep-link e2e test a user-visible anchor.
- **The legacy singular `tag_id` param is no longer sent by the frontend.** Phase 1 deliberately kept the backend accepting it, so this is not a breaking change; the backend contract is unchanged and non-REST callers keep working.
- **E2E helper extended:** `TestDataManager.createJournalTag` now accepts a string `parent_id` via a new `JournalTagCreateRequest` type (journal tags are UUID-keyed, unlike the integer-keyed contact `TagCreateRequest`), so the parent→child descendant test can build a real hierarchy.
- **Dismissible active-tag badge added, matching contacts.** The journals filter panel is collapsible, so without the badge a user arriving via `/journals?tag=<id>` with the panel hidden would have no in-page control to remove the filter (only the global Clear, which also wipes search and the anchor date). Mirrors `data-testid="active-tag-filter"` / `clear-tag-filter` and the `aria-label={\`Remove <tag> filter\`}` from `/contacts`.
- **`hasActiveFilters` is computed explicitly rather than by counting filter keys.** `JournalFilters` emits `tag_ids: undefined` when the last tag is unchecked, so `Object.keys(filters).length` counted a phantom key — leaving the Clear button visible, empty days collapsed and the empty state blaming filters when none were active. `handleFiltersChange` now deletes the key, and the three call sites share one `hasActiveFilters` flag, matching `contacts/page.tsx`.
- **Union rather than replace, diverging from contacts.** Contacts' `effectiveFilters` *replaces* panel selections with the URL tag; journals unions them, so a deep link plus panel selections behave additively. Deliberate — the union is what "multi-tag filtering" means for this page — and now documented in the journal system specification.
- **Journal search still ignores tag filters** (`useSearchJournals` has no tag parameter — adding one is a backend/MeiliSearch change, out of scope for a frontend-only phase). Contacts passes its active tag into search. Rather than let the tag-named heading imply a narrowing that does not happen, the results summary says so explicitly while a search is active. **Follow-up:** add tag filtering to the journal search endpoint and thread `effectiveFilters` into `useSearchJournals`.
- **Pre-existing e2e flake observed, not introduced:** `journals-list-ready` intermittently fails to appear on the first `/journals` load of a cold dev server. Reproduced on an unmodified checkout (`journal-infinite-scroll.spec.ts`) and passes on re-run; recorded here rather than attributed to this phase.
- **Diff ran to ~700 lines, over the 500-line standard** (roughly 200 production, 500 test). Splitting further would have shipped either a multi-tag param with no deep link or a deep link whose filter panel disagreed with the URL — both worse than a single coherent slice. Recorded rather than hidden, as in ITER17-001 Phase 4.

**Required Test Coverage:**
- **Unit:** frontend filter param construction; `useTagFilter` generalisation. — `frontend/src/lib/api/__tests__/journals.test.ts` (4 tests: repeated `tag_ids` for many tags, single tag without the legacy `tag_id`, no tag param when none selected, and the combined-filter URL), `frontend/src/hooks/__tests__/useTagFilter.test.ts` (3 new tests for `basePath`, plus the 7 existing contact tests unchanged), `frontend/src/components/journals/__tests__/JournalFilters.test.tsx` (3 tests: checked state from props, second tag accumulates, unchecking removes only that id), `frontend/src/app/journals/__tests__/page.test.tsx` (8 tests: URL tag applied to the query, reflected in the panel, named in the heading, unchecking clears the param, union with a panel-selected tag, the dismissible badge remains operable with the filter panel hidden, no phantom `tag_ids` key after the last tag is unchecked, and a no-tag regression guard).
- **Integration:** n/a beyond RTL (no new backend). Phase 1's `tests/integration/api/test_journal_tag_endpoints.py` (55 tests) was re-run as a regression check on the contract this phase consumes.
- **E2E:** filter journals by a parent tag and assert a child-tagged journal appears; deep-link `/journals?tag=` renders a filtered list; multi-tag selection returns the union. — `frontend/tests/e2e/journals-list.spec.ts`, run on Chromium: `should include child-tagged journals when filtering by a parent tag`, `should return the union of journals when multiple tags are selected` (asserts two `tag_ids` values on the wire), `should filter the list from a /journals?tag= deep link and clear it` (heading, filtered list, checked checkbox, and URL param dropped on uncheck). The existing `should filter journals by tag` test now asserts `tag_ids=` instead of `tag_id`.

---

### ITER17-003: Journal Detail Tag Editor Parity

**Objective:** Replace the select-dropdown tag UI on the journal detail page with an editor matching `ContactTagsEditor` exactly: searchable add popover, inline create-new-tag with colour picker, dismissible colour-coded badges.
**Strategy:** Two phases — build the component with its unit tests first, then wire it into the detail view with e2e coverage. Prefer extracting a shared, domain-agnostic tags editor component parameterised over the tag type and mutation hooks; if extraction proves too large, build `JournalTagsEditor` as a structural copy and record consolidation as follow-up.

**Relevant documents:**
- [Frontend Design — Component Architecture](../architecture/frontend-design.md#component-architecture)
- Contact reference: `frontend/src/components/contacts/ContactTagsEditor.tsx`, `TAG_COLORS` in `frontend/src/lib/constants.ts`

#### Phase 1: Tags Editor Component and Unit Tests ✅ COMPLETE

**Estimated diff:** ~500 lines · **Actual:** ~1360 changed lines (~1040 added, ~320 removed), roughly half tests — the extraction also rewrote `ContactTagsEditor` into an adapter (see decisions below)

**Acceptance Criteria:**
- [x] Assigned tags render as dismissible badges with the tag colour (border/dot styling identical to the contact editor). — same badge/border markup, now in the shared `TagsEditor`.
- [x] Adding a tag opens a searchable popover listing unassigned tags filtered by the query (autocomplete), not a plain select.
- [x] When the search query matches no existing tag, the user can create a new tag inline with name + colour (from `TAG_COLORS`), which is created via `POST /api/journals/tags` and immediately assigned. — new `createJournalTag` / `useCreateJournalTag`; the adapter awaits create then assign.
- [x] The add affordance is available even when there are no unassigned tags or no tags at all (the create flow is always reachable).
- [x] Duplicate assignment is prevented in the UI; already-assigned tags do not appear in the add list.
- [x] Accessibility matches the contact editor: labelled controls, keyboard operability, `aria-label` on remove buttons (plus `aria-label` on each colour swatch and the search input).
- [x] The component is exported but not yet mounted in `JournalDetailView` (existing behaviour unchanged this phase — the phase is shippable with no user-visible change). — `JournalTagsEditor` is imported only by its own test; `JournalDetailView` still uses `JournalTagBadge`.

**Decisions taken (Phase 1):**
- **Generic extraction over structural copy.** Rather than duplicate `ContactTagsEditor`, the shared render/interaction logic was lifted into a domain-agnostic `frontend/src/components/shared/TagsEditor.tsx` operating on a normalised `TagView` view-model plus callbacks, and **both** domains became thin adapters over it (`ContactTagsEditor` refactored, `JournalTagsEditor` new). This is the iteration's preferred path (delivery rule 5) and **closes the "Shared tag component consolidation" follow-up below** now rather than deferring it. The contact refactor is behaviour-preserving — proven by its existing, unchanged `ContactTagsEditor.test.tsx`.
- **Self-fetch vs prop asymmetry lives in the adapters.** The contact adapter self-fetches assigned tags via `useContactTags(contactId)`; the journal adapter takes `assignedTags` as a prop because journal tags are embedded on the journal detail resource and there is no per-journal assigned-tags endpoint. The shared core is agnostic to both.
- **`JournalTag` gained `parent_id`.** The flat `JournalTag` type now carries `parent_id?: string | null` and `fetchJournalTags` maps it, so the editor renders the `Parent › Child` hierarchy path like contacts. This updated the existing `useJournalTags` mapping test expectation.
- **`useCreateJournalTag` toast uses a literal string** (`'Tag created successfully'`), matching the sibling `useAddJournalTag` / `useRemoveJournalTag` pattern rather than a `SUCCESS_MESSAGES` constant.
- **Shipped as one slice rather than the planned two.** The intent was to split the extraction (shared `TagsEditor` + contact adapter refactor) from the journal adapter for the 500-line rule, but the repository's pre-commit hook type-checks the **whole** project while stashing unstaged edits — so an intermediate commit left the journal files referencing a `useCreateJournalTag`/`parent_id` that had been stashed away, failing `tsc`. The phase is a single reviewable slice on one PR; roughly half the diff is tests. Recorded rather than hidden, as in ITER17-001 Phase 4.

**Required Test Coverage:**
- **Unit (RTL):** shared-core `frontend/src/components/shared/__tests__/TagsEditor.test.tsx` (badges/colour, remove, open popover, add existing, search filtering, duplicate prevention, create-with-colour, always-reachable add, a11y, loading, error, hierarchy path); journal-adapter `frontend/src/components/journals/__tests__/JournalTagsEditor.test.tsx` (mapping, assign, remove, create-then-assign order, create-failure keeps form open, loading/error); API `frontend/src/lib/api/__tests__/journals.test.ts` (`createJournalTag` POST body + error, `useCreateJournalTag` invalidation, `parent_id` mapping). The existing `ContactTagsEditor.test.tsx` runs unchanged as the refactor regression proof. — **4 suites, 63 tests, all passing.**
- **Integration:** n/a (no backend change).
- **E2E:** deferred to Phase 2 (component not yet mounted).

#### Phase 2: Detail View Wiring and E2E ✅ COMPLETE

**Estimated diff:** ~300 lines · **Actual:** ~1250 changed lines gross, ~90 net. The gross figure is misleading three ways: 367 removed lines are the outright deletion of `JournalTagBadge` and its test; ~280 lines of the `TagsEditor.tsx` diff are pure re-indentation from wrapping the add popover in a ternary (`git diff -w` reports **16 added / 12 removed** for that file); and roughly two thirds of the remainder is test code. Reviewable as one slice.

**Prerequisites:** Phase 1 merged.

**Acceptance Criteria:**
- [x] `JournalDetailView.tsx` uses the new editor; the old `JournalTagBadge` select flow is removed (keep the read-only badge rendering if still used elsewhere). — the component had no other consumer (`JournalListItem` renders its own colour chips), so it and its test were **deleted** rather than kept.
- [x] Mutations use the existing `useAddJournalTag` / `useRemoveJournalTag` / journal-tag query hooks with cache invalidation, and errors surface to the user (toast), not only `console.error`. — the detail view no longer owns any tag mutation; `JournalTagsEditor` calls the hooks, which already invalidate `journalKeys.detail` + `journalKeys.lists` and `toast.error` on failure. The legacy `console.error` swallow died with `JournalTagBadge`.
- [x] Existing journal-detail tag e2e tests are updated to the new interaction and still cover add + remove.

**Decisions taken (Phase 2):**
- **`JournalTagBadge` deleted, not retained.** The AC's "keep the read-only badge rendering if still used elsewhere" clause did not apply: `JournalDetailView` was its only consumer. Keeping an unmounted component would have left a second, worse tag UI in the tree.
- **No backend or integration-test work.** The phase is frontend-only — `POST`/`DELETE /api/journals/{id}/relationships/tags` and `POST /api/journals/tags` already existed and were already used by the Phase 1 hooks. The doc's "Integration: mutation hook tests if new hooks are added" bullet is met at the hook layer instead: `useAddJournalTag` / `useRemoveJournalTag` gained the request/invalidation/toast coverage that `contact-tag-mutations.test.ts` has for contacts (Phase 1 had already covered `useCreateJournalTag`). Backend `pytest`/`ruff`/`mypy` gates are **not applicable** to this phase.
- **The tags block is now a `fieldset`/`legend`.** The editor is a set of related controls, so the native grouping element gives it an accessible name (still `role=group` to assistive tech) while keeping the visual style shared with the sibling Contacts/Series sections. An earlier `div` + `role='group'` + `aria-labelledby` was replaced during review: it needed a hard-coded `id` that would collide if the view were ever rendered twice, and SonarCloud flags explicit `role="group"` in favour of the semantic element.
- **`TestDataManager.trackJournalTag(tagId)` added.** The inline-create e2e test creates a tag *through the UI*, so the data manager cannot track it at creation time; without this the tag would be orphaned in the shared journal tag namespace and leak into other tests' tag lists.
- **A failed tag-definitions fetch no longer blanks the assigned badges.** Phase 1's shared `TagsEditor` early-returned an error message *instead of* the whole editor when `isError` was set. Mounting it made that user-visible: journal tags are embedded on the journal resource, so a failed `GET /api/journals/tags` was hiding badges the page already had — and their remove buttons — a regression against the old `JournalTagBadge`, which always rendered its `tags` prop. Delivery rule 9 ("no phase may rely on a later phase to restore broken behaviour") made this in-scope. The error now replaces only the **add affordance** (which genuinely needs the definitions); badges stay rendered and removable. Fixed in the shared core, so contacts benefit identically.
- **Journal tag removal remains non-optimistic** while contacts' `useRemoveContactTag` is optimistic. Out of scope for this phase's ACs; recorded as follow-up below rather than silently skipped. The e2e removal test keeps its `toPass` click-and-assert retry for this reason.

**Required Test Coverage:**
- **Unit (RTL):** `frontend/src/components/journals/__tests__/JournalDetailView.test.tsx` — the `JournalTagBadge` mock is gone, so the real `JournalTagsEditor` + shared `TagsEditor` mount. New `Tags Section` suite (8 tests): colour-coded assigned badges, accessible group name, assign-from-search-popover, already-assigned tags excluded from the add list, remove, add affordance reachable with an empty tag namespace, inline create-then-assign, and no legacy `tag-select`. **32 tests in the file, all passing** (7 of the new ones verified failing against the pre-change component).
- **Integration:** `frontend/src/lib/api/__tests__/journals.test.ts` — new `useAddJournalTag` and `useRemoveJournalTag` suites (4 tests each: request shape, detail+list invalidation, success toast, error toast), mirroring `contact-tag-mutations.test.ts`. No backend change, so no backend integration tests (see decisions).
- **E2E:** `frontend/tests/e2e/journal-detail.spec.ts` `Tag Management` (4 tests) — add an existing tag via the search popover (opened by keyboard), create a new tag inline with an explicitly chosen colour and assert the badge's `border-color`, remove a tag, and the add affordance stays reachable on an untagged journal. All fixture-created via `TestDataManager`; no skips, no multi-outcome assertions, and no conditionals on data state. The removal test keeps a pre-existing `if (await tagBadge.isVisible())` *inside* its `toPass` retry — a transient-UI guard, not a data-state branch — because removal is not optimistic (see decisions).
- **Shared-core regression fix:** `frontend/src/components/shared/__tests__/TagsEditor.test.tsx` gained a test proving assigned badges stay visible and removable when the tag-definitions request fails, one proving the add popover does not spring back open holding a stale query once the error clears, and the existing error test now also asserts the add button stands down.

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
- [ ] Search re-indexing of affected journals on tag delete/merge is driven by these events. **ITER17-001 Phases 3 and 4 deferred delete and merge re-indexing here** (journal tags publish no events yet, and contacts likewise do not re-index on `TagDeleted` or on tag merge), so this phase now owns both.

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
- **Contact tag ID typing across MCP ([#1139](https://github.com/hjed/personal-management-system/issues/1139)):** `list_contact_tags` returns `TagInfo.id` as a string while the write tools (`merge_contact_tags`, `update_contact_tag`, `delete_contact_tag`) take ints, so an AI caller cannot round-trip an ID between them. Phase 2's and Phase 4's tools matched the existing convention rather than fix half the surface. Align `TagInfo`, `UpdatedTagInfo`, and the contact tag write tools in one change. Journal tags are unaffected — UUID-keyed and stringified consistently.
- **Contacts' merge SQL still lives in the service:** `TagService.merge_tags` inlines its `text()` statements, which is what ITER17-001 Phase 4 deliberately declined to copy into the journal domain. Moving it into `SqlTagRepository` would bring contacts in line with the journal implementation and the ports-and-adapters rule; out of scope for this iteration since it touches no journal behaviour.
- **Shared tag component consolidation:** ~~if ITER17-003/004 duplicate the contact editor/dialog components rather than generalising them, consolidate into shared domain-agnostic components afterwards.~~ ✅ **Closed for the editor** in ITER17-003 Phase 1: the contact and journal tag *editors* now share `frontend/src/components/shared/TagsEditor.tsx`. The management *dialogs* (`TagManagementDialog`, `CreateTagDialog`, `TagContextMenu`) in ITER17-004 remain candidates for the same treatment.
- **Tags at journal creation time:** `JournalCreateForm.tsx` has no tag input (the API supports tags on create via MCP). Contacts likewise only edit tags from the detail/edit surfaces, so this is not a parity gap — treat as an independent enhancement if wanted.
- **Search document tag names:** the journal search document indexes `tag_ids` only, while the MCP search converter reads a non-existent `tag_names` field (`backend/app/mcp/domains/journals/converters.py` line ~225) and contact documents index tag names as searchable text. Aligning journal search to also index tag names (making journals findable by tag text) is a small follow-up once events from ITER17-005 exist to keep names fresh on rename.
- **Journal tag filter semantics doc:** record the OR-across-tags semantics (inherited from contacts) in the API design doc if it isn't already stated.
- **Optimistic journal tag removal:** contacts' `useRemoveContactTag` removes the badge from the cache immediately and rolls back on failure; `useRemoveJournalTag` waits for the DELETE plus a refetch, so the badge lingers for a round-trip. Noted in ITER17-003 Phase 2 (outside its ACs) — the e2e removal test carries a `toPass` retry because of it. Aligning the two would let that retry go.

## Definition of Done for the Iteration

This iteration is complete when, for journal tags, a user can do everything they can do with contact tags:

- Edit tags on a journal through a searchable editor with inline tag creation and colour-coded badges
- Manage journal tags from the sidebar tree: create, rename, recolour, describe, re-parent, delete, and merge
- Filter the journals list by tag — from the sidebar, by URL, and with parent tags including child-tagged journals
- See tag changes in the journal activity feed with provenance
- Perform the same tag operations through MCP
- All phases keep `main` green with unit, integration, and e2e coverage, linting, and type checks passing
