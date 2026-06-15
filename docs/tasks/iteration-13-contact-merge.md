# Iteration 13: Contact Merge

**Status:** 🔵 PLANNED — sub-iterations and phases defined; ready to implement
**Dependencies:** Iteration 2.6 (contacts product alignment — relationships-to-user, tags, summary), Iteration 5 (Redis Streams event bus, transactional outbox relay, stream consumers), Iteration 11 (Immich integration worker), Iteration 12 (shared `field_history` foundation + event-driven projection), existing Google Contacts sync worker, existing journal merge feature
**Goal:** Let the user merge two contacts into a single surviving record — preserving and deduplicating the full contact aggregate (relationships, journal links, methods, addresses, notes, tags, important dates), reconciling external sync links, and keeping a complete audit trail — with full parity across the web UI and MCP. Mirror the established journal merge UX and conflict-handling, deliberately **without** AI auto-detection or a review queue.

## Overview

Contacts accumulate duplicates from manual entry, Google/Immich sync, and name-match auto-linking, and there is currently no way to combine two of them. This iteration delivers the approved [Contact Merge Product Specification](../product-specifications/contact-merge-product-specification.md).

The journal domain already ships a mature merge workflow — a `JournalMergeService`, a `merge_journals` MCP tool, a REST merge endpoint, and a field-by-field `MergeResolutionDialog` — described in the [Journals Product Specification](../product-specifications/journals-product-specification.md#journal-merge). Contact merge intentionally reuses that survivor model, conflict-resolution vocabulary, and dialog UX so the two domains feel like one consistent merge concept. The difference is scope: contacts have a richer aggregate (sub-entities and external sync links) and **no** AI-assisted detection or Needs Review queue at this stage — finding the pair is a manual action.

This iteration is split into independently shippable **sub-iterations** (incremental value chunks). The detailed phase breakdown for each chunk is intentionally deferred to a second planning pass; this document defines the chunks, their value, sequencing, and the documentation each depends on.

## Reference Documents

- **[Contact Merge Product Specification](../product-specifications/contact-merge-product-specification.md)** — approved product behaviour for this iteration
- **[Journals Product Specification — Journal Merge](../product-specifications/journals-product-specification.md#journal-merge)** — the established merge pattern this iteration mirrors (survivor model, conflict resolution, MCP parity)
- **[Contacts Product Specification](../product-specifications/contacts-product-specification.md)** — the contact aggregate (relationships, tags, important dates, summary) and MCP parity expectations
- **[Activity History Product Specification](../product-specifications/activity-history-product-specification.md)** — provenance and audit-trail behaviour for the merge event and history re-pointing
- **[Integration Architecture & Strava Product Specification](../product-specifications/integration-architecture-and-strava-product-specification.md)** — event-bus and worker reconciliation patterns referenced by external sync
- **[Integration Architecture](../architecture/integration-architecture.md)** — Redis Streams event bus, transactional outbox relay, stream consumers, and two-way sync (Google Contacts, Immich)
- **[Domain Architecture](../architecture/domain-architecture.md)** — domain layer, ports & adapters, services, and domain events
- **[Database Design](../architecture/database-design.md)** — schema, unique constraints, and transaction-management (`@transactional` / `unit_of_work`) standards
- **[Testing Strategy](../architecture/testing-strategy.md)** — unit/integration/E2E patterns, conftest fixtures, Docker PostgreSQL
- **[Iteration 12: Activity History](./iteration-12-activity-history.md)** — shared entity-agnostic `field_history` table/model/repository and event-driven projection (basis for history re-pointing)
- **[Iteration 11: Immich Integration](./iteration-11-immich-integration.md)** — Immich worker, person linking, and the reviewable-PR reference
- **[Iteration 5: Integration Architecture & Strava](./iteration-5-integration-architecture-and-strava.md)** — origin of the Redis Streams event bus and consumer groups

### Existing implementation to mirror or extend

These are the closest existing analogues; the second-pass phase breakdown will reference exact files and line ranges.

- **Journal merge service** — `backend/app/core/journal/services/journal_merge_service.py` (survivor selection, re-parenting, dedupe-on-transfer, conflict detection, override application)
- **Journal merge MCP tool** — `backend/app/mcp/domains/journals/tools.py` (`merge_journals`, override JSON contract)
- **Journal merge REST endpoint** — `backend/app/api/journals/controllers.py` (`POST /api/journals/{id}/merge`, JSON:API override schema)
- **Journal merge UI** — `frontend/src/components/journals/MergeJournalDialog.tsx`, `MergeResolutionDialog.tsx`, and `frontend/src/lib/api/journals.ts` (`useMergeJournal`)
- **Contact aggregate** — `backend/app/core/contacts/services/contact_service.py`, `contact_relationship_service.py`, and `backend/app/infrastructure/contacts/contact_tables.py` (relationship partial unique indexes, `journal_contact_relationships` composite PK, sub-entity tables)
- **Contact events** — `backend/app/core/contacts/models/events.py` (no `ContactMerged` event exists yet) and the Google/Immich workers under `integration_workers/`
- **External links** — `backend/app/core/integrations/external_reference_service.py`, `core_shared/.../models/external_reference.py`, and `core_shared/.../models/sync_metadata.py`

### External Documentation

- **SQLAlchemy Core** — https://docs.sqlalchemy.org/en/20/ (use the `writing-sql` skill before authoring queries)
- **Alembic** — https://alembic.sqlalchemy.org/en/latest/ (use the `creating-migrations` skill for sequential naming)
- **FastAPI** — https://fastapi.tiangolo.com/ (context7 `fastapi/fastapi`)
- **Dishka** — https://dishka.readthedocs.io/en/stable/ (service + worker DI wiring)
- **FastMCP v2** — https://gofastmcp.com/llms.txt (context7 `websites/gofastmcp`) for the `merge_contacts` tool
- **shadcn/ui** — https://ui.shadcn.com/docs (context7 `websites/ui_shadcn`) for the merge dialogs
- **React Testing Library** — https://testing-library.com/docs/react-testing-library/intro
- **Playwright** — https://playwright.dev/docs/intro (use the `playwright-skill` and `running-e2e-tests` skills)

## Delivery Rules

These rules apply to every sub-iteration below:

1. **Tests first:** write the failing tests for the slice before implementation (TDD red → green → refactor).
2. **Green main:** do not merge a slice unless relevant tests, linting (`ruff`, `pnpm lint`), and type checks (`mypy`, `pnpm type-check`) pass.
3. **Reviewable PRs:** keep each PR to roughly ≤ 10 files where practical; split into smaller vertical slices if needed.
4. **MCP parity:** any merge capability meaningful in the UI must be exposed through MCP in the same slice.
5. **Non-destructive:** a merge must never silently lose relationships, journal links, history, or sync links; duplicates collapse rather than duplicate.
6. **No hacks:** do not bypass domain validation, skip provenance, or orphan external links; record follow-up work in this document rather than as code TODOs.
7. **Every slice is shippable:** no slice may rely on a later slice to restore broken behaviour.
8. **Transactions in the service layer:** the merge is a single unit of work (`@transactional` / `unit_of_work`); controllers and MCP tools must not open transactions.

## Incremental Value Chunks

The work is split into five independently shippable sub-iterations. They are ordered to deliver a usable merge through MCP/API first, then add full conflict control, then the user-facing UI, and finally the two cross-cutting concerns (history fidelity and external-system reconciliation) that can land in parallel once the engine exists.

- **ITER13-001 — Core Local Merge Engine (backend + REST + MCP).** A `ContactMergeService` that absorbs a source contact into a user-chosen survivor: re-point and dedupe the full aggregate (relationships with self-loop drop, journal links, methods, addresses, notes, tags, important dates), delete the source, request AI-summary regeneration for the survivor, and record the merge as a history event. Conflicts resolve by a default policy (survivor wins; prefer non-empty). Exposed via a REST merge endpoint and a `merge_contacts` MCP tool taking explicit survivor + source IDs. Value: a complete, deduplicating merge usable end-to-end by API and AI agents.

- **ITER13-002 — Field-by-Field Conflict Resolution (overrides).** Extend the service contract, REST endpoint, and `merge_contacts` tool with per-field overrides (survivor / source / custom) for the scalar identity fields, mirroring the journal merge override JSON. Value: deliberate conflict resolution for API and AI agents, not just survivor-wins.

- **ITER13-003 — Web Merge Experience (UI).** The contact-detail merge entry point, a search combobox to pick the other contact, an explicit survivor selector, a field-by-field resolution dialog (mirroring `MergeResolutionDialog`), and a preview/confirm + success flow. Value: the user-facing contact merge feature.

- **ITER13-004 — History Re-pointing & Merge Audit.** Re-point the source contact's `field_history` rows onto the survivor so the unified record carries both contacts' full audit trail, and surface the merge event in the contact activity feed with `ui`/`mcp` provenance. Value: a complete, non-destructive audit trail after merge.

- **ITER13-005 — External Sync Reconciliation.** A new `ContactMerged` domain event consumed by the Google and Immich workers: carry over links from different services onto the survivor; for a same-service collision, consolidate onto the survivor's remote then delete the source remote (Google) or unlink the orphaned source (Immich, no delete API). Value: external services stay consistent with the merged contact.

| Chunk | Delivers | Surface | User-visible? | Risk |
|---|---|---|---|---|
| ITER13-001 | Deduplicating merge engine, survivor-wins | REST + MCP | Via MCP/API | Medium (aggregate re-point + dedupe constraints) |
| ITER13-002 | Per-field conflict overrides | REST + MCP | Via MCP/API | Low (extends 001 contract) |
| ITER13-003 | Merge dialog + resolution UI | Web UI | **Yes** | Medium (new UI, mirrors journal dialogs) |
| ITER13-004 | History re-pointing + merge event in feed | Backend + UI feed | Yes (activity feed) | Medium (touches shared `field_history`) |
| ITER13-005 | Remote link reconciliation | Integration workers | No (consistency) | High (two integrations, no native merge API) |

## Sequencing and Parallelisation

- **ITER13-001** must land first — every other chunk builds on the merge engine and event.
- **ITER13-002** depends on **ITER13-001** (extends its service/REST/MCP contract).
- **ITER13-003** depends on **ITER13-002**, because the resolution dialog consumes the per-field override contract.
- **ITER13-004** depends on **ITER13-001** and can run in parallel with **002 / 003**. Until it lands, the source's history rows are orphaned (not lost) — acceptable interim state since 001 still records the merge event.
- **ITER13-005** depends on **ITER13-001** emitting the `ContactMerged` event and can run in parallel with **002 / 003 / 004**. It may itself be split per service (Google first, Immich second) in the phase pass.

## Out of Scope (carried from the specification)

- AI-assisted duplicate detection, a contacts "Needs Review" queue, an on-demand duplicate-finder helper, and automatic/bulk merging. Finding the pair to merge is a manual action in both UI and MCP. These may be revisited later by reusing the journal domain's detection and review-queue patterns.

## Task Breakdown

Each sub-iteration below defines its objective, the specification and code it builds on, the high-level outcomes its phases collectively satisfy, and a **phase breakdown**. Phases are sized to merge to a green `main` independently and to stay within a ~600-line diff (implementation + tests). A phase need not expose a user-facing feature on its own — the sub-iteration is the shippable unit — but every phase must leave `main` green and introduce no broken or half-wired runtime path. Sizes are estimates grounded in the closest existing analogue (line counts noted where they drove the split).

### Sizing findings that shaped the phases

These were established by reviewing the current code and drive the phase boundaries below:

- **No re-point / FK-update methods exist** on any contact repository (`contact_repository.py`, `contact_relationship_repository.py`, `journal_contact_relationship_repository.py`) or on `field_history_repository.py` — they only add/delete. Every re-point is **net-new** repository code with its own dedupe/constraint handling, which is why the engine (ITER13-001) is split by collection rather than shipped as one service like the 598-line `journal_merge_service.py`.
- **No database migration is required.** All merging is `UPDATE`/`DELETE` on existing tables; `ContactMerged` is a domain event, not a table; the merge audit reuses the entity-agnostic `field_history` table.
- **Constraint hotspots** the re-point code must honour: `contact_relationships` two partial unique indexes + the `ck_contact_relationships_no_self_reference` check (a re-point that creates a self-loop is **rejected**, so self-loops must be dropped first); `contact_methods` global email-unique and one-primary-per-`(contact, type)`; one-primary address per contact; the `uq_contact_birthday` per contact; and the `journal_contact_relationships` / `contact_tags` composite PKs.
- **Contacts still record history via synchronous dual-write** (the event-driven `HistoryProjectionConsumer` from Iteration 12 covers journals only). The merge audit row is therefore written **inline** in the merge transaction via `ContactHistoryService`, not via a projection.
- **External-reference rows have no `ON DELETE CASCADE`.** Deleting the source contact in ITER13-001 leaves its `external_references` / `sync_metadata` rows inert-but-orphaned until ITER13-005 reconciles them — an acceptable interim state, but ITER13-005 should follow ITER13-001 closely (see Sequencing).
- **Reuse:** `frontend/src/components/contacts/ContactSearchCombobox.tsx` (already used by `AddRelationshipForm`, `ImmichConflicts`, `GlobalSearch`) is the source picker; `useMergeTag` in `frontend/src/lib/api/contacts.ts` is the exact hook/cache-invalidation template for `useMergeContact`; the journal merge dialogs and `journals-merge.spec.ts` are the UI/E2E templates.

### ITER13-001: Core Local Merge Engine (backend + REST + MCP)

**Objective:** Provide a single service operation that merges a source contact into a user-chosen surviving contact, re-pointing and deduplicating the entire contact aggregate, deleting the source, regenerating the survivor's AI summary, and recording the merge — exposed through a REST endpoint and a `merge_contacts` MCP tool.

**Builds on:**
- `JournalMergeService` (`backend/app/core/journal/services/journal_merge_service.py`) — survivor model, dedupe-on-transfer, transactional merge
- `ContactService` / `ContactRelationshipService` and `backend/app/infrastructure/contacts/contact_tables.py` — aggregate writes and the relationship partial unique indexes / `journal_contact_relationships` composite PK that govern dedupe
- `merge_journals` tool and journal merge controller for the MCP/REST shape

**Specification reference:**
- [Contact Merge — Product model](../product-specifications/contact-merge-product-specification.md#product-model)
- [Contact Merge — Required behaviour](../product-specifications/contact-merge-product-specification.md#required-behaviour)
- [Contact Merge — Sub-entity merge rules](../product-specifications/contact-merge-product-specification.md#sub-entity-merge-rules)
- [Contact Merge — MCP and AI-Agent Parity](../product-specifications/contact-merge-product-specification.md#mcp-and-ai-agent-parity)

**Outcomes the phases must satisfy:**
- A user-chosen survivor keeps its ID; the source is deleted after a successful, atomic merge.
- Relationships re-point in both directions, self-loops between the two contacts are dropped, and remaining relationships dedupe per the existing partial unique indexes.
- Journal links re-point and dedupe on `(journal, contact, relationship_type)`.
- Methods, addresses, notes, important dates, and tags carry over with exact duplicates collapsed, respecting global email uniqueness and one-primary-per-type.
- The survivor's AI summary is regenerated (request the existing summary-refresh event).
- The merge is recorded as a history event (source ID, survivor ID, provenance); a `ContactMerged` domain event is emitted for downstream consumers (ITER13-005).
- A REST merge endpoint and a `merge_contacts` MCP tool accept explicit survivor + source IDs and return the unified contact.

#### Phase 1: Relationship & journal-link re-point (repository + service skeleton)
**PR Size:** ~480 lines (repo ~140, service skeleton ~90, tests ~250)

Build the hardest re-points first, behind a not-yet-exposed `ContactMergeService`. No runtime path reaches this code yet, so it merges green as additive code under test.

**Status:** ✅ DONE — repository re-points, service skeleton, and DI wiring implemented with unit + integration coverage; all backend quality gates (pytest, `ruff`, `mypy`) green locally.

> **Ownership note (deviation):** the `contacts` table has **no `user_id`/owner column** (contacts are single-user in this system — verified in `contact_tables.py` and the `core_shared` `Contact` entity), so the AC's "same owner" precondition is **not applicable** at the data layer. Phase 1 validates only *both exist* + *distinct*. A cross-owner check can be added if/when contacts gain ownership.

**Acceptance Criteria:**
- [x] `ContactRelationshipRepository` gains a `repoint_contact(source_id, survivor_id, transaction)` that re-points both `from_contact_id` and `to_contact_id`, **drops self-loops** between the two contacts before they violate `ck_contact_relationships_no_self_reference`, and dedupes the result against `uq_contact_relationships_contact_target` and `uq_contact_relationships_user_target` (delete-colliding-then-update — the unique constraints are partial indexes, so a plain `UPDATE … ON CONFLICT` cannot name them).
- [x] `JournalContactRelationshipRepository` gains a `repoint_contact(source_id, survivor_id, transaction)` that re-points and dedupes on the `(journal_id, contact_id, relationship_type)` composite PK.
- [x] A new `ContactMergeService.merge_contacts(survivor_id, source_id, transaction)` (decorated `@transactional`) validates preconditions (both exist, distinct; *same owner* N/A — see note) and invokes the two re-points. No scalar/sub-entity handling yet.
- [x] `ContactMergeService` is wired in `backend/app/infrastructure/di/contacts.py` (REQUEST scope).

**Required Test Coverage:**
- [x] **Integration:** relationship re-point dedupes duplicates, drops the inter-contact self-loop, preserves to-user relationships, and handles both directions; journal-link re-point dedupes on the composite PK. Use `async_connection` / `clean_database` from `tests/integration/conftest.py`. (`backend/tests/integration/contacts/test_contact_merge_repoint_integration.py`, 7 tests.)
- [x] **Unit:** precondition validation (self-merge, missing survivor, missing source) raises; happy path delegates to both re-points. (`backend/tests/unit/contacts/test_contact_merge_service.py`, 4 tests. Cross-owner case omitted — not applicable, see note.)

#### Phase 2: Sub-entity re-point + source deletion + summary refresh
**PR Size:** ~520 lines (repo methods ~190, service ~80, tests ~250)

Complete the aggregate merge so the service produces a correct unified contact under the default (survivor-wins / prefer-non-empty) policy. Still not exposed.

**Status:** ✅ DONE — `ContactRepository.repoint_methods/addresses/notes/important_dates/tags` + the completed `ContactMergeService.merge_contacts` (scalar prefer-non-empty, source delete, `merged_from` history row, summary-refresh event) implemented with unit + integration coverage. All backend quality gates (pytest, `ruff`, `mypy`) green locally (516 contacts tests pass).

> **Email-uniqueness note (clarification):** `ix_contact_methods_email_unique` (migration `0025`) makes email values unique **system-wide**, so two contacts can never pre-hold the same email — the literal "colliding email" pre-state is impossible to construct. The AC is therefore satisfied as (a) distinct emails from both contacts coexisting on the survivor after re-point, and (b) the **primary-email** collision being demoted (`ix_contact_methods_primary_unique`, survivor's primary wins). Exact-value duplicate collapse is verified via **phone** (no global-uniqueness constraint). The one-primary **address** invariant is likewise enforced by `idx_contact_addresses_unique_primary` (DB-level), handled by demote-then-re-point.

**Acceptance Criteria:**
- [x] `ContactRepository` gains re-point methods for contact methods, addresses, notes, important dates, and tags that carry rows from source to survivor and collapse exact duplicates.
- [x] Constraint collisions are resolved during re-point: global email uniqueness and one-primary-per-`(contact, method_type)` for methods; one-primary address; `uq_contact_birthday`; `contact_tags` PK dedupe. Survivor's existing primary/value wins on collision.
- [x] `ContactMergeService` applies scalar fields with prefer-non-empty (survivor wins on conflict — overrides arrive in ITER13-002), re-points all sub-entities, deletes the source contact, and requests survivor summary regeneration by emitting `ContactSummaryRefreshRequested`.
- [x] The merge is recorded as an inline `field_history` row on the survivor (e.g. `field_name = "merged_from"`, `old_value = <source_id>`) via `ContactHistoryService`, carrying provenance.

**Required Test Coverage:**
- [x] **Integration:** full-aggregate merge produces a deduplicated survivor; source is deleted; colliding email / duplicate primary / duplicate tag / duplicate birthday resolve without constraint violation; the merge `field_history` row is written. (`backend/tests/integration/contacts/test_contact_merge_aggregate_integration.py`, 10 tests.)
- [x] **Unit:** prefer-non-empty scalar policy; `ContactSummaryRefreshRequested` emitted for the survivor. (`backend/tests/unit/contacts/test_contact_merge_service.py`, extended to 10 tests.)

#### Phase 3: `ContactMerged` event + REST endpoint + MCP tool (survivor-wins)
**PR Size:** ~540 lines (event ~30, endpoint ~120, MCP tool ~90, schemas ~60, tests ~240)

Expose the engine. **This phase makes contact merge live via API and MCP.**

**Status:** ✅ DONE — `ContactMerged` event emitted via the dual publisher, `POST /api/contacts/{id}/merge` REST endpoint, and the `merge_contacts` MCP tool implemented with unit + integration coverage. All backend quality gates (pytest, `ruff`, `ruff format`, `mypy`) green locally.

> **Ownership note (deviation, carried from Phase 1):** the `contacts` table has **no `user_id`/owner column** (contacts are single-user), so "enforce ownership of both" reduces to **existence** at the data layer — matching the existing `get_contact` MCP tool, which checks only existence. The service validates *both exist* + *distinct*; the MCP tool surfaces those as error payloads. A cross-owner check can be added if/when contacts gain ownership.

**Acceptance Criteria:**
- [x] A `ContactMerged(survivor_contact_id, source_contact_id, …)` domain event is added to `backend/app/core/contacts/models/events.py` and emitted by `ContactMergeService` via the dual publisher, carrying provenance (`source`/`changed_by`). The **search indexer** consumes it to de-index the deleted source's now-stale document (the merge deliberately does **not** emit `ContactDeleted` for the source — the Google worker consumes that to delete the *remote* contact unconditionally, which contradicts merge semantics). The integration-worker `ContactMerged` handlers (consolidate / carry-over / remote delete) are still ITER13-005; an absent worker consumer must not error.
- [x] `POST /api/contacts/{id}/merge` (JSON:API; path id = survivor, body carries `source_contact_id`) calls `ContactMergeService` and returns the unified contact via `ContactConverter.to_resource`. The controller opens no transaction. `ContactMergeConflictError` (self-merge) maps to **409**; missing contact to **404**.
- [x] A `merge_contacts` MCP tool takes explicit survivor + source IDs, validates existence of both (see ownership note), calls the service, and returns the unified contact. Mirrors `merge_journals`; registered alongside the other contact tools via `register_contact_tools`.

**Required Test Coverage:**
- [x] **Integration (REST):** end-to-end merge via the endpoint; source deleted; journal links / sub-entities consolidated; survivor-wins / prefer-non-empty scalar resolution; self-merge → 409 and missing survivor/source → 404. (`backend/tests/integration/api/test_contact_merge_endpoint.py`, 5 tests.)
- [x] **Integration/Unit (MCP):** `merge_contacts` registered with the right schema (`survivor_contact_id` + `source_contact_id`); mounted-HTTP merge returns the unified contact and deletes the source; self-merge / not-found return error payloads. (`backend/tests/integration/mcp/test_contact_tools_integration.py`, 2 tests.)
- [x] **Unit (service):** `ContactMerged` is published with the survivor/source IDs and the passed provenance. (`backend/tests/unit/contacts/test_contact_merge_service.py`, extended to 12 tests.)

### ITER13-002: Field-by-Field Conflict Resolution (overrides)

**Objective:** Allow callers to deliberately resolve scalar-field conflicts (name parts, company, job title, photo, favourite) per field — survivor value, source value, or a custom value — through the service, REST endpoint, and MCP tool.

**Builds on:**
- ITER13-001's merge service and contracts
- The journal override contract in `MergeResolutionDialog` ↔ `merge_journals` (the JSON override shape to mirror)

**Specification reference:**
- [Contact Merge — Field conflict resolution](../product-specifications/contact-merge-product-specification.md#field-conflict-resolution)

**Outcomes the phases must satisfy:**
- When only one contact has a value, the survivor takes it (prefer non-empty) with no prompt.
- When both differ, the caller can specify per-field overrides; absent an override, the default policy from ITER13-001 applies.
- The override contract is consistent across REST and MCP and mirrors the journal merge override JSON.

#### Phase 1: Per-field overrides in service, REST, and MCP
**PR Size:** ~420 lines (service ~120, schemas ~70, tests ~230)

A single phase: the override contract spans all three surfaces and is small enough to land together.

**Status:** ✅ DONE — per-field overrides land across the service (`overrides` mapping + override-aware `_merge_scalars` + `has_scalar_conflicts`), the REST `MergeContactOverrides` schema/controller, and the `merge_contacts` MCP tool's optional `overrides` mapping. Overridden fields are surfaced in the merge audit (`ContactUpdated`) payload. All backend quality gates green locally (`ruff`, `ruff format`, `mypy` over 372 files, **577 contacts unit+integration tests pass**). UI/browser E2E is **deferred to ITER13-003** (the merge UI phase); an **API-level Playwright E2E** (`frontend/tests/e2e/contacts-merge-api.spec.ts`, Chromium, 2 specs) covers the override contract end-to-end through the REST surface now.

> **`is_favourite` note:** `is_favourite` is a boolean OR-merge (default `False`) with no meaningful "both set and differing" state, so it is **excluded from `has_scalar_conflicts`** (documented in `_CONFLICT_FIELDS`). It remains fully overridable — an explicit `is_favourite=False` override is honoured (the override path keys on "present and not `None`", not truthiness).

> **Override semantics:** an override is a mapping `field_name → concrete value to apply`; the caller (UI/agent) resolves the survivor / source / custom choice into a value before calling, mirroring the journal `MergeResolutionDialog` ↔ `merge_journals` contract. Absent keys fall back to the ITER13-001 prefer-non-empty default. The REST converter does not expose `company`/`job_title` (an ITER13-001 display limitation, unchanged here); those overrides are verified directly against the database in the integration test.

**Acceptance Criteria:**
- [x] `ContactMergeService.merge_contacts` accepts an `overrides` mapping for the scalar identity fields (`first_name`, `last_name`, `middle_name`, `nick_name`, `company`, `job_title`, `photo_url`, `is_favourite`); each field resolves to the survivor value, the source value, or a caller-supplied custom value, falling back to the ITER13-001 default when unspecified.
- [x] A `has_scalar_conflicts(survivor, source)` helper reports fields where both sides hold differing non-empty values (mirrors `has_base_conflicts` in `journal_merge_service.py`; `is_favourite` excluded — see note).
- [x] The REST `MergeContactOverrides` schema and the MCP `merge_contacts` request schema both carry the override mapping, mirroring `MergeOverrides` / `MergeJournalMCPRequest`.

**Required Test Coverage:**
- [x] **Unit:** each scalar field honours survivor / source / custom; `has_scalar_conflicts` boundary cases (one-empty is not a conflict; equal values are not a conflict; both-empty is not a conflict); `is_favourite=False` override honoured; absent-override regression; overridden fields recorded in the audit event. (`backend/tests/unit/contacts/test_contact_merge_service.py`, extended to 27 tests.)
- [x] **Integration:** REST and MCP merges apply overrides end-to-end. (`backend/tests/integration/api/test_contact_merge_endpoint.py` + `backend/tests/integration/mcp/test_contact_tools_integration.py`.)
- [x] **E2E (API-level, Chromium):** override merge (survivor / source / custom + `is_favourite=False`) and no-override survivor-wins merge through the REST surface; source deleted. (`frontend/tests/e2e/contacts-merge-api.spec.ts`.) Browser/UI E2E deferred to ITER13-003.

### ITER13-003: Web Merge Experience (UI)

**Objective:** Deliver the user-facing merge flow on the web: entry point, contact selection, survivor choice, field-by-field conflict resolution, and a preview/confirm step.

**Builds on:**
- ITER13-002's override contract
- `MergeJournalDialog.tsx` / `MergeResolutionDialog.tsx` and `useMergeJournal` as the component and hook templates; existing contact search components for the combobox

**Specification reference:**
- [Contact Merge — Web Experience](../product-specifications/contact-merge-product-specification.md#web-experience)

**Outcomes the phases must satisfy:**
- A merge entry point on the contact detail experience.
- A search selector to find the other contact, mirroring the journal merge combobox.
- An explicit survivor selector.
- A field-by-field resolution dialog (survivor / source / custom) shown only when conflicts exist.
- A preview/confirm step and a clear success state, reusing existing shadcn/ui components.

#### Phase 1: `MergeContactResolutionDialog` component
**PR Size:** ~530 lines (component ~400, tests ~130)

Build the conflict-resolution dialog as a self-contained, not-yet-reachable component (mirrors the 409-line `MergeResolutionDialog.tsx`). Merges green; nothing routes to it yet.

**Status:** ✅ DONE — `MergeContactResolutionDialog.tsx` (+ exported `detectContactConflicts` helper) and the `MergeContactOverrides` frontend type implemented with RTL coverage. All frontend quality gates green locally (`pnpm quality:check` exit 0; 6 new tests pass; 283 contacts component tests pass, no regressions).

> **Conflict-field scope (clarification):** the frontend `ContactResource.attributes` exposes only `first_name, last_name, middle_name, nick_name, photo_url, is_favourite`. The dialog detects conflicts on the **text** identity fields (`first_name, last_name, middle_name, nick_name, photo_url`). `is_favourite` is **excluded** from conflict detection (boolean OR-merge, no meaningful "both differ" state — consistent with the ITER13-002 `_CONFLICT_FIELDS` note). `company`/`job_title` are **not exposed** on the frontend resource (the documented ITER13-001 display limitation), so they cannot be surfaced in the UI; they remain overridable via MCP/API (the `MergeContactOverrides` type still carries them for parity). No contact identity field is multiline, so the custom-value control is `Input` (no `Textarea` branch needed).

**Acceptance Criteria:**
- [x] `MergeContactResolutionDialog.tsx` detects scalar-field conflicts (both sides non-empty and differing) across the contact identity fields and renders a per-field `RadioGroup` (survivor / source / custom) with `Input`/`Textarea` for custom values, building the override object on submit. Reuse the `ResolutionChoice` / `FieldResolution` shapes from the journal dialog. (Custom uses `Input`; no contact identity field is multiline — see note.)
- [x] When no conflicts exist, the dialog reports "no conflicts" and resolves immediately (the parent can merge directly).

**Required Test Coverage:**
- [x] **Component (RTL):** conflict detection (incl. `is_favourite` exclusion + empties), radio selection, custom text input, override-object construction, the no-conflict path, and the null-props loading guard. (`frontend/src/components/contacts/__tests__/MergeContactResolutionDialog.test.tsx`, 6 tests.)

#### Phase 2: `MergeContactDialog` + hook + detail-page entry (feature reachable)
**PR Size:** ~470 lines (dialog ~180, hook+types ~100, page wiring ~40, tests ~150)

Wire the reachable flow. **This phase makes contact merge usable in the web UI** — and only now, because the resolution dialog (Phase 1) already exists, so no survivor-wins-without-UI gap is shipped.

**Acceptance Criteria:**
- [ ] `useMergeContact` + `mergeContact` + `MergeContactOverrides` are added to `frontend/src/lib/api/contacts.ts`, following the existing `useMergeTag` mutation + cache-invalidation pattern (invalidate `contactKeys.all` and both contacts' detail caches; success/error toasts).
- [ ] `MergeContactDialog.tsx` lets the user pick the other contact via the existing `ContactSearchCombobox` (excluding the current contact), choose which contact survives, then hands off to `MergeContactResolutionDialog`.
- [ ] A "Merge" entry point is added to the contact detail page action area (`frontend/src/app/contacts/[id]/page.tsx`, alongside Delete).

**Required Test Coverage:**
- [ ] **Component (RTL):** source selection (survivor exclusion), survivor toggle, hand-off to the resolution dialog, and mutation invocation.

#### Phase 3: End-to-end merge flow
**PR Size:** ~320 lines (E2E spec, test-only)

**Acceptance Criteria:**
- [ ] A Playwright spec (modelled on `frontend/tests/e2e/journals-merge.spec.ts`) creates two contacts with conflicting fields and overlapping relationships/journal links, opens the merge dialog from the detail page, selects the source, picks the survivor, resolves conflicts, confirms, and asserts the survivor holds the consolidated data and the source is gone. Deterministic test data per the project's E2E rules (no conditional/skipped assertions).

**Required Test Coverage:**
- [ ] **E2E:** the full conflict-resolution merge path and a no-conflict (direct) merge path, validated on Chromium.

### ITER13-004: History Re-pointing & Merge Audit

**Objective:** Ensure the surviving contact carries the complete, non-destructive audit trail of both contacts, and that the merge itself is visible in the activity feed.

**Builds on:**
- Iteration 12's shared `field_history` table, repository, aggregation strategies, and event-driven projection
- The merge history event recorded in ITER13-001

**Specification reference:**
- [Contact Merge — History and Audit](../product-specifications/contact-merge-product-specification.md#history-and-audit)
- [Activity History Product Specification](../product-specifications/activity-history-product-specification.md)

**Outcomes the phases must satisfy:**
- The source contact's `field_history` rows are re-pointed onto the survivor so the unified record's aggregate history is complete.
- The merge event appears in the survivor's activity feed with correct `ui`/`mcp` provenance and references the absorbed source.

#### Phase 1: Re-point contact history onto the survivor ✅ Complete
**PR Size:** ~230 lines (repo ~50, service wiring ~30, tests ~150)

A single phase. Sub-entity history rows (`entity_type` in `contact_method` / `contact_address` / …) need no change — those rows keep their own ids, which ITER13-001 re-pointed to the survivor — so only the top-level `entity_type = "contact"` rows move.

**Acceptance Criteria:**
- [x] `SqlFieldHistoryRepository` gains `repoint_entity_history(old_entity_id, new_entity_id, entity_type, transaction)` that re-points the source contact's top-level history rows to the survivor, respecting the `(event_id, entity_type, entity_id, field_name)` idempotency index (`ON CONFLICT DO NOTHING`). Implemented as a single copy-then-delete statement (the only form that supports `ON CONFLICT DO NOTHING`), preserving `event_id` / `created_at` / `source` / `changed_by`.
- [x] `ContactMergeService` calls the re-point within the merge transaction (after the source's sub-entities have moved, before the source row is deleted), so the survivor's aggregate history (`get_history_for_aggregate("contact", survivor_id)`) returns both contacts' prior changes plus the ITER13-001 merge row. `FieldHistoryRepository` is injected via Dishka (provided by `JournalProvider`).

**Required Test Coverage:**
- [x] **Integration:** after a merge, the survivor's aggregate history includes the source's pre-merge changes and the merge event; re-running the re-point is idempotent; the activity-feed endpoint surfaces the merge row with correct provenance.

**Delivered tests:**
- Unit: `tests/unit/contacts/test_contact_merge_service.py::test_repoints_history_then_deletes_source` (re-point called with `(source, survivor, "contact", tx)` before the source delete).
- Integration (repo): `tests/integration/history/test_field_history_repository_integration.py` — moves top-level rows / leaves sub-entity rows; preserves provenance + event_id; idempotent re-run; conflicting-row dedup.
- Integration (merge): `tests/integration/contacts/test_contact_merge_aggregate_integration.py::test_merge_repoints_source_history_onto_survivor`.
- Integration (feed): `tests/integration/infrastructure/events/test_contact_history_projection_integration.py::TestMergeHistoryFeed::test_merge_event_surfaces_in_activity_feed_with_provenance` (real merge endpoint + outbox→projection→`GET /history`, asserts `merged_from` with `ui` provenance + re-pointed change).
- E2E: `frontend/tests/e2e/contacts-merge-api.spec.ts` → "Contact merge history re-pointing (ITER13-004)" (Chromium, polls the async feed).

### ITER13-005: External Sync Reconciliation

**Objective:** Keep external services (Google Contacts, Immich) consistent with the merged contact by reconciling external references and remote records in response to the merge.

**Builds on:**
- The `ContactMerged` event emitted by ITER13-001
- The Google Contacts and Immich workers under `integration_workers/`, `ExternalReferenceService`, and `SyncMetadata`
- The event-bus / consumer-group patterns from Iterations 5, 11, and 12

**Specification reference:**
- [Contact Merge — External Sync Reconciliation](../product-specifications/contact-merge-product-specification.md#external-sync-reconciliation)

**Outcomes the phases must satisfy:**
- Different-service links from both contacts are carried over onto the survivor.
- For a same-service collision: consolidate merged data onto the survivor's remote, then delete the source's remote where supported (Google); for services without delete (Immich), keep the survivor's link and unlink the orphaned source.
- Reconciliation is driven by the `ContactMerged` event consumed by the relevant workers, following the documented consumer pattern; no merge runs synchronously inside the request.
- May be split into per-service phases (Google, then Immich) in the phase pass.

#### Phase 1: Re-point external references & sync metadata (backend)
**PR Size:** ~410 lines (service/consumer ~210, tests ~200)

Stop the merge from orphaning links: re-point the source's `external_references` and `sync_metadata` onto the survivor and detect same-service collisions. (The `external_references` table has no `ON DELETE CASCADE`, so this is the fix for the interim orphaning noted in Sizing findings.)

> **Inline-vs-consumer decision (documented per AC):** the *local* re-point of `external_references` / `sync_metadata` runs **inline in the merge transaction** (alongside the ITER13-004 history re-point), because these are local `UPDATE`/`DELETE`s — not remote calls — and doing them in the merge's single unit of work guarantees no orphan can survive a committed merge. The spec only forbids running *remote* calls inline; the async remote reconciliation stays in the Google/Immich workers (Phases 2/3) consuming `ContactMerged`. To let those workers act on a same-service collision after the source's local row is removed, the `ContactMerged` event is extended with an `external_collisions` payload (the spec's "external references to reconcile").

> **E2E note:** no E2E in this phase — it is backend-only with no UI/API surface change and no public read API over external references. Real E2E lands with the observable remote behaviour in Phases 2/3, mirroring how backend-only ITER13-001 P1/P2 shipped without E2E.

**Acceptance Criteria:**
- [x] `ExternalReferenceService.repoint_contact_references(source_id, survivor_id, transaction)` re-points the source contact's references to the survivor: links to services the survivor lacks carry over (`UPDATE internal_entity_id`); a service present on **both** contacts is flagged as a same-service collision — the survivor's link is kept, the source's local row is deleted, and the collision (`external_system`, `external_entity_type`, source + survivor `external_id`) is returned for remote reconciliation. Returns `list[ExternalReferenceCollision]`.
- [x] Source `sync_metadata` rows are re-pointed (carry-over) or deleted (collision) consistently with the references, scoped by `(integration_source, external_id)` so an unrelated journal sync row sharing the source's integer id is left untouched.
- [x] Re-pointing runs **inline in the merge transaction** (after the history re-point, before the source delete) so a deleted source never leaves resolvable-looking orphans. **Decision (documented):** inline, not a `ContactMerged` consumer — these are local `UPDATE`/`DELETE`s (not remote calls; the spec only forbids running *remote* calls inline), so doing them in the merge's single unit of work guarantees no orphan can survive a committed merge (mirrors the ITER13-004 history re-point). The async remote reconciliation stays in the Google/Immich workers (Phases 2/3); the same-service collisions are carried on the extended `ContactMerged.external_collisions` payload so the workers can act after the source's local row has gone.

**Required Test Coverage:**
- [x] **Integration:** different-service links land on the survivor; a same-service pair is flagged once; no `external_references` / `sync_metadata` rows remain pointing at the deleted source. (`backend/tests/integration/contacts/test_contact_merge_external_refs_integration.py`, 5 tests: carry-over, collision-flagged-once, no-orphans, an unrelated-sync-row-scoping guard, and a direct `ExternalReferenceService.repoint_contact_references` test.)
- [x] **Unit:** the merge calls `repoint_contact_references` once before the source delete, and propagates the returned collisions onto the `ContactMerged` event (`external_collisions`); no-collision path yields an empty payload. (`backend/tests/unit/contacts/test_contact_merge_service.py`, `TestContactMergeExternalReferences`, 3 tests.)

**Status:** ✅ DONE — `ExternalReferenceService.repoint_contact_references` + `ExternalReferenceCollision`, the extended `ContactMerged.external_collisions` payload, and the inline merge wiring (constructor + `di/contacts.py`) implemented with unit + integration coverage. All backend quality gates green locally (`ruff check`, `ruff format`, `mypy` over 372 files; 556 contacts unit+integration tests + 30 merge endpoint/MCP tests pass). No E2E this phase — see note above (backend-only, no UI/API surface or public read over external references; real E2E lands with the workers in Phases 2/3).

#### Phase 2: Google worker — consolidate then delete source remote
**PR Size:** ~290 lines (worker handler ~90, wiring ~20, tests ~180)

**Acceptance Criteria:**
- [ ] `ContactMerged` is added to the Google worker's subscribed event types (`stream_consumer_tasks.py` / `_OUTBOUND_EVENT_TYPES`).
- [ ] On `ContactMerged` where both contacts had a Google link, the worker ensures the survivor's Google contact reflects the merged data, then deletes the source's Google contact via the existing `google_client.delete_contact()` and cleans the source's `sync_metadata` (reusing the existing delete flow). A 404 on the source remote is treated as success.

**Required Test Coverage:**
- [ ] **Integration (worker):** same-service merge deletes exactly the source remote and cleans its sync metadata; survivor link preserved; different-service merge triggers no Google deletion.

#### Phase 3: Immich worker — unlink orphaned source (no remote delete)
**PR Size:** ~190 lines (handler ~60, wiring ~10, tests ~120)

**Acceptance Criteria:**
- [ ] `ContactMerged` is added to the Immich worker's subscribed event types.
- [ ] Because the Immich API exposes no person delete, the handler keeps the survivor's link and unlinks the source's orphaned reference (and cleans its `sync_metadata`); it must not attempt a remote delete and must not dead-letter on the event.

**Required Test Coverage:**
- [ ] **Integration (worker):** same-service merge unlinks the source reference and leaves the survivor's Immich link intact; the event is acknowledged without error.
