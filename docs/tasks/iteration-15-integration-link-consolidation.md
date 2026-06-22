# Iteration 15: Integration Link Consolidation (fix contact duplication)

**Status:** 🟡 IN PROGRESS — Phase 1, 2, 3, 4 & 5 complete
**Dependencies:** Iteration 11 (Immich Integration), Iteration 13 (Contact Merge), Iteration 14 (Worker Standardisation)
**Goal:** Eliminate the dual-table inconsistency between `external_references` and `sync_metadata` that causes Immich-origin contacts to be duplicated by Google sync, by consolidating onto a single canonical integration-link store — and migrate/clean up the duplicates already created.

## Overview

Synced contacts and journals are linked to their external system entities by **two overlapping tables**:

- `external_references` — the link the **backend contact code** reads for dedup/idempotency (`find_by_external_reference`, the inbound consumer's reconciliation).
- `sync_metadata` — the link **every integration worker** maintains for change detection (`version_hash`), concurrency (`SELECT FOR UPDATE`), and status/retry.

Both encode the same `(source, external_id) → internal_id` mapping, but no writer touches both consistently. This causes a confirmed, reproducible **contact duplication loop**:

1. Immich creates a **blank, email-less** contact (name + birthday only) and writes `external_references(immich, person_id)`.
2. The resulting `ContactCreated` event makes the **Google outbound worker push the contact to Google**. That push records **`sync_metadata(google, resourceName)` only — it never writes an `external_references(google, …)` row**.
3. **Google inbound sync** later re-imports that same person. The consumer's idempotency (`find_by_external_id`) and contact lookup (`find_contact_by_external_reference`) read **`external_references`, not `sync_metadata`**, so the contact is invisible → the updated-path falls through to the create-path.
4. The only remaining dedup is **email reconciliation**, which is email-only. The Immich contact has **no email** → no match → a **new duplicate contact is created, stamped `google_sync`**.
5. The create-path's `sync_metadata` upsert repoints `(google, resourceName)` to the duplicate, so the original looks "new to Google" again next cycle → it is pushed again → **duplicates regenerate every sync.**

This only affects contacts with an Immich match because only Immich produces email-less contacts; before Immich, every synced contact had an email and reconciled cleanly. See [database-design.md](../architecture/database-design.md) and [integration-architecture.md](../architecture/integration-architecture.md).

### Reference Documents

- [Database Design](../architecture/database-design.md)
- [Integration Architecture](../architecture/integration-architecture.md)
- [Testing Strategy](../architecture/testing-strategy.md)
- [Creating Migrations skill](../../.claude/skills/creating-migrations/SKILL.md)

## Architectural Decision: consolidate onto `sync_metadata` (merge), reject the split

We considered the two options:

| | **A. Merge (chosen)** — one canonical link table (`sync_metadata`) | **B. Split** — `external_references` = identity (backend), `sync_metadata` = bookkeeping (worker) |
|---|---|---|
| Coverage today | `sync_metadata` already used by **every** integration (google, immich, immich_album, strava, snipeit, snipeit_maintenance, snipeit_checkout) | `external_references` used by **only** Immich (person + album) and Google **contacts** (and only written by the *backend*, never the Google worker); Strava/Snipe-IT don't use it at all |
| Dedup key | `UNIQUE(integration_source, external_id)` already exists | `external_references` has **no unique constraint** |
| Internal id types | supports `internal_id` (int) **and** `internal_uuid` (Snipe-IT) | `internal_entity_id` is **int only** |
| Eliminates the bug class? | **Yes** — one row, written once, read everywhere | **No** — still two tables that must be kept in sync; would require *adding* `external_references` writes to Strava, Snipe-IT and the Google outbound worker |

**Decision:** Consolidate all integration-link tracking onto **`sync_metadata`** and retire `external_references`. The split formalises the very dual-write that causes the bug and requires expanding the weaker table to universal coverage. The backend/worker boundary the split proposes doesn't match access reality: both the backend (dedup) and the workers (create-vs-update) read identity, and both write `version_hash`.

`sync_metadata` absorbs the two things `external_references` uniquely provided:
- `reference_data` (JSON) — album display metadata (`album_name`, `asset_count`, `album_url`, `thumbnail_asset_id`, `shared_link_url`) and contact `synced_tags`/etag.
- `internal_entity_type` / `external_entity_type` — explicit entity typing (currently derivable from `integration_source`, but made explicit for safe generic queries).

The table keeps the name `sync_metadata` to avoid churn across ~30 call sites and 8 `integration_source` variants; its expanded role ("the canonical integration link") is documented in `integration-architecture.md`. A rename is deferred to a future iteration.

> **Note on the unique constraint:** consolidating means two contacts can no longer both claim the same `(google, resourceName)` — which is exactly the invariant the bug violated. Legitimate merge "collisions" are two contacts with *different* external ids per system and remain representable.

## Delivery Rules

1. **Tests first.** Every phase writes failing tests before implementation (red → green → refactor).
2. **Green main.** Each phase is an independently reviewable PR (~5–10 files) that leaves the system working with all tests/lint/types passing.
3. **Parallel change (expand → migrate → contract).** `sync_metadata` must be kept **complete and current by every writer before any reader switches to it.** So we **dual-write first**, then move reads, then remove the old writes, then drop the table. Reads never switch to a store that a live write path might not be populating.
4. **No silent data loss.** Backfill and cleanup migrations log every quarantined/merged row.

## Dependency and Parallelisation Notes

Phases are **sequential** because of the parallel-change ordering — reads must not move before writes keep the new store current:
P1 (schema) → P2 (**dual-write + backfill**) → P3 (move reads — *the fix*) → P4 (stop writing `external_references`) → P5 (drop + dedupe). P6 (defensive name reconciliation) and P7 (delete propagation) are independent hardening tasks that may run in parallel once P1 lands.

> **Why dual-write before reads?** The P2 backfill is only a point-in-time snapshot. Several paths today write `external_references` without a paired `sync_metadata` write at the same instant (e.g. the Immich worker's name-match auto-link relies on the consumer to write `sync_metadata` later; album `reference_data` updates). If reads moved to `sync_metadata` before every writer populated it, links created in that window would be invisible → broken dedup. Dual-write closes that window; the backfill handles rows that predate it.

---

## Task Breakdown

### ITER15-001: Consolidate integration links onto `sync_metadata`

**Objective:** Make `sync_metadata` the single canonical store for integration entity links, retire `external_references`, and remove the duplication loop.

**Specification Reference:**
- [Integration Architecture → Core Components](../architecture/integration-architecture.md)
- [Database Design](../architecture/database-design.md)

**Acceptance Criteria (task-level):**
- [x] Immich → Google → Immich round-trip never creates a duplicate contact (integration test — `test_link_consolidation_reads.py`, green through Phase 5).
- [x] `external_references` table is dropped; no code reads or writes it (Phase 5; grep-gated).
- [x] Existing bug-created duplicate contacts are merged; orphaned link rows reconciled (`0092`).
- [x] All integration link reads/writes flow through one repository with one schema (`sync_metadata` via `SyncMetadataRepository` / `IntegrationLinkRepository`).

---

#### Phase 1: Schema foundation (additive migration) — ✅ COMPLETE

**PR Size:** ~3 files

Extend `sync_metadata` into the superset of both tables. Schema only — no data movement, no behaviour change.

> **Migration number:** the head migration is already `0088_add_sync_job_fanout_hierarchy.py`,
> so this phase shipped as **`0089_extend_sync_metadata_for_link_consolidation.py`**
> (`down_revision = "0088"`). The later phases' migration numbers shift up by one accordingly.

- [x] Migration `0089_extend_sync_metadata_for_link_consolidation.py` (additive only):
  - [x] Add nullable columns: `reference_data` (Text/JSON), `internal_entity_type` (VARCHAR(50)), `external_entity_type` (VARCHAR(50)).
  - [x] Backfill `internal_entity_type` / `external_entity_type` for **existing `sync_metadata` rows** from `integration_source` (`google`/`immich` → `contact`/`person`; `immich_album` → `journal`/`album`; `strava` → `journal`/`activity`; `snipeit` → `gear_item`/`hardware`; `snipeit_maintenance` → `journal`/`maintenance`; `snipeit_checkout` → `journal`/`checkout`; `firefly_iii` left NULL — no worker). (Cross-table backfill from `external_references` is Phase 2, after dual-write is live.)
- [x] Update the `SyncMetadata` model (`core_shared/.../models/sync_metadata.py`) with the new columns.
- [x] Populate the columns on the **backend write path** so backfilled values stay consistent with new rows (PR-review feedback — "if we backfill we must update the write at the same time"): `SyncMetadataRepository.upsert` accepts `internal_entity_type` / `external_entity_type` / `reference_data` and persists them, using `COALESCE` on conflict so a writer that omits them never clears existing values. Backend callers (inbound contact create/update → `contact`/`person`; Strava → `journal`/`activity`; Immich album → `journal`/`album`) pass the entity types. **Worker direct-SQL upserts (google/immich/snipeit) and `reference_data` mirroring remain Phase 2 dual-write** — workers can lag safely because of the `COALESCE` guard.

**Required Test Coverage:**
- [x] **Integration (migration):** isolated-DB migration test (`backend/tests/integration/integrations/test_sync_metadata_link_consolidation_migration.py`, uses shared `run_alembic`/`throwaway_database` conftest fixtures) — columns added & nullable, entity-type backfill correct per source, `firefly_iii`/`reference_data` left NULL, existing rows preserved (exact `version_hash`, single row per key), downgrade drops the columns.
- [x] **Integration (write path):** `test_sync_metadata_repository_integration.py` — `upsert` persists the link columns; a later `upsert` omitting them preserves the existing values (COALESCE).
- [x] **Unit:** model column round-trip + mapped-column assertions (`core_shared/tests/test_models.py::TestSyncMetadata`); `upsert` link-column forwarding (`backend/tests/unit/core/integrations/test_sync_metadata_repository.py`).

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — note `sync_metadata` is becoming the canonical link store (mark `external_references` deprecated, removal pending).

---

#### Phase 2: Dual-write + backfill (make `sync_metadata` complete & current) — ✅ COMPLETE

**PR Size:** ~8–10 files

Ensure **every path that writes `external_references` also writes the paired `sync_metadata` link** (carrying `reference_data` + entity types), so the new store stays current. Then backfill the rows that predate dual-write. **Reads are unchanged in this phase** — old `external_references` readers stay correct.

> **Migration number:** the backfill shipped as **`0091_backfill_sync_metadata_from_external_references.py`** (`down_revision = "0090"`); `0089` was the Phase 1 schema migration and `0090` is the unrelated `add_climbing_indoor_and_top_rope` migration already on `main`.

- [x] Dual-write — pair a `sync_metadata` upsert with each `external_references` write that doesn't already have one at the same instant:
  - [x] Immich worker `_create_external_reference` (name-match auto-link) → also upsert `sync_metadata` immediately (previously relied on the consumer's later `contact.updated`).
  - [x] Album `upsert_link` (`reference_data` updates) → mirror `reference_data` onto `sync_metadata`.
  - [x] Confirm the inbound consumer create/update paths and the Google/Immich outbound pushes already write `sync_metadata`; add `internal_entity_type`/`external_entity_type` where missing (Google worker `_upsert_sync_metadata`, Immich worker `_upsert_sync_metadata`).
  - [x] All link writes inside the existing committed unit of work (no swallowed-and-uncommitted writes; align with the #945 commit-timing rule).
- [x] Backfill migration `0091_backfill_sync_metadata_from_external_references.py` (idempotent; ships with / runs after the dual-write deploy so it also closes the dual-write rollout gap):
  - [x] For each `external_references` row, **upsert** a matching `sync_metadata` row keyed on `(external_system→integration_source, external_entity_id→external_id)`, carrying `internal_entity_id→internal_id`, entity types, and `reference_data`. Where a `sync_metadata` row already exists, copy `reference_data`/entity types onto it (preserving its `internal_id`/`version_hash`).
  - [x] **Conflict handling:** `external_references` allows duplicate `(external_system, external_entity_id)` rows but `sync_metadata` does not. Deterministically pick one (prefer the row whose `internal_entity_id` matches an existing internal entity; tie-break by lowest id) and **log** every skipped row to a temporary `link_backfill_quarantine` audit table for Phase 5.
  - [x] Backfilled-only rows (no prior sync_metadata) get `version_hash = ''` so the next sync re-validates content.

**Required Test Coverage:**
- [x] **Integration (dual-write):** each `external_references` write path now produces the paired `sync_metadata` row in the same transaction (`integration_workers/immich/tests/integration/test_immich_external_reference_integration.py::TestAutoLinkDualWrite`; `backend/tests/integration/journal/test_album_sync_read_repository.py::TestAlbumLinkDualWrite`).
- [x] **Integration (migration):** contact with only an `external_references(google)` row → backfilled; the bug case (contact with `immich` external_ref + `google` sync_metadata only) → both links present after; duplicate `external_references` rows → one wins, rest quarantined; album `reference_data` copied intact; re-run is idempotent (`backend/tests/integration/integrations/test_backfill_sync_metadata_migration.py`).
- [x] **Unit:** worker `sync_metadata` writes carry entity types (`integration_workers/immich/tests/unit/test_immich_sync_service.py::test_auto_link_writes_sync_metadata_with_entity_types`; `integration_workers/google/tests/unit/test_worker.py::TestUpsertSyncMetadataEntityTypes`).

**E2E:** not applicable — Phase 2 only changes backend/worker write paths and a migration; reads (and therefore frontend behaviour) are unchanged.

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — describe the dual-write transition state.

---

#### Phase 3: Move all reads to `sync_metadata` (this fixes the bug) — ✅ COMPLETE

**PR Size:** ~8–10 files

With `sync_metadata` now complete and kept current by dual-write, a thin
`IntegrationLinkRepository` wrapper (`core_shared/.../repositories/integration_link_repository.py`,
shared by the backend and the workers) provides the unified link-lookup reads, and every reader is
repointed off `external_references`:

- [x] `find_link_by_external(integration_source, external_id) -> link | None`
- [x] `find_internal_by_external(...) -> (internal_id, internal_uuid, internal_entity_type)`
- [x] `find_external_by_internal(internal_entity_type, internal_id, integration_source)`
- [x] plus `get_immich_person_id` / `get_contact_ids_by_immich_person_ids` (the Immich link reads).

Readers repointed:
- [x] **Backend consumer** (`outbox_event_processor.py`): `_process_contact_created` idempotency now reads `sync_metadata` (`SyncMetadataRepository.find_by_external_id`); `_process_contact_updated`'s contact lookup (`contact_repository.find_by_external_reference`) reads `sync_metadata`; the email-reconciliation link-existence check reads `sync_metadata`. **← removes the duplication.**
- [x] `contact_repository.find_by_external_reference` / `get_external_references` → `sync_metadata` (the contacts API + MCP external-links reads follow via the repo).
- [x] **Immich worker**: `_find_external_reference`, `sync_contact_outbound` link lookup, `get_immich_person_id` (avatar proxy), `get_contact_ids_by_immich_person_ids` (album participant detection) → `sync_metadata`.
- [x] **Album read repo** (`album_sync_read_repository.py`): the display reads (`find_by_journal_id` / `find_external_links` / `find_cover_asset`) drop the `external_references` join and read `reference_data` from `sync_metadata`.
- [x] **Merge collision detection** (`ExternalReferenceService.repoint_contact_references` reads) → `sync_metadata` (the dual-table UPDATE/DELETE writes remain until Phase 4).

> **Scope note:** Contact `synced_tags`/`etag` `reference_data` reads (`find_external_reference`, `_update_synced_tags_reference`) stay on `external_references` — Phase 2 mirrors only *album* `reference_data` into `sync_metadata`, so the contact `reference_data` write (and its read) move together in Phase 4. Phase 3 moves the *identity* reads + *album* `reference_data` reads.

**Required Test Coverage:**
- [x] **Integration (the regression):** Immich creates email-less contact → outbound push writes `sync_metadata(google,…)` → Google inbound `contact.updated`/`created` → asserts **exactly one** contact, updated not duplicated (`backend/tests/integration/integrations/test_link_consolidation_reads.py`).
- [x] **Integration:** idempotency — re-delivering `contact.created` for an already-linked external id is skipped (`test_link_consolidation_reads.py`); album display data resolves from `reference_data` in `sync_metadata` (`backend/tests/integration/journal/test_album_sync_read_repository.py`, `backend/tests/integration/api/test_external_links_endpoints.py`).
- [x] **Worker integration:** Immich create-vs-update decision reads `sync_metadata` (`integration_workers/immich/tests/integration/test_immich_external_reference_integration.py::TestCreateVsUpdateReadsSyncMetadata`).
- [x] **Unit:** `IntegrationLinkRepository` lookups (`core_shared/tests/unit/repositories/test_integration_link_repository.py`).

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — inbound/outbound flow now keys dedup on `sync_metadata`.

---

#### Phase 4: Stop writing `external_references` (contract) — ✅ COMPLETE

**PR Size:** ~6–8 files

Now that nothing reads `external_references`, the old half of the dual-write is removed so every writer persists the canonical link (and `reference_data`/entity types) to `sync_metadata` only:

- [x] Backend `ExternalReferenceService`: `upsert_contact_reference` → `sync_metadata` upsert (`version_hash=''`); `repoint_contact_references` → `sync_metadata` rows only; the dead write helpers (`create_external_reference`, `update_external_reference`, `_get_external_reference_by_id`) removed.
- [x] Inbound contact create/update (`outbox_event_processor`): the link `reference_data` (`resource_name`/`etag`/`synced_tags`) is written onto `sync_metadata`; the contact `synced_tags`/`etag` read moved to `IntegrationLinkRepository.find_link_by_external` and the write to the new `SyncMetadataRepository.update_reference_data` (which leaves `version_hash` untouched). *(This is the contact `reference_data` move the Phase 3 scope note deferred to P4.)*
- [x] Immich worker `_create_external_reference` → removed (auto-link keeps the `sync_metadata` upsert); merge-cleanup `_unlink_immich_reference_for_event` deletes `sync_metadata` only.
- [x] Album `AlbumSyncReadRepository.upsert_link` / `find_link` / `delete` → `sync_metadata` only. `upsert_link` became the single writer of the album `sync_metadata` row (`version_hash` + `reference_data` + the merge-protection anchor on `updated_at`); the redundant generic `sync_metadata` upserts in the album processors/creation service were removed so the anchor is never unconditionally bumped.
- [x] Merge repoint (`repoint_contact_references`) → operates on `sync_metadata` rows only.

**Required Test Coverage:**
- [x] **Integration:** each write path produces the correct single `sync_metadata` row and **zero** `external_references` writes — inbound create/update (`test_link_consolidation_writes.py`), immich auto-link (`test_immich_external_reference_integration.py::TestAutoLinkDualWrite`), album create + anchor (`test_album_sync_read_repository.py::TestAlbumLinkWrite`, `test_immich_album_outbox_processor.py`, `test_immich_album_creation_api.py`), contact merge (`test_contact_merge_external_refs_integration.py`), manual immich link (`test_immich_conflicts_api.py`), worker merge-cleanup (`test_contact_merged_reconciliation_integration.py`).
- [x] **Unit:** repository write methods — `SyncMetadataRepository.update_reference_data` (`test_sync_metadata_repository.py`); outbox create carries `reference_data` + synced-tags write to `sync_metadata` (`test_outbox_event_processor.py`); immich auto-link emits no `external_references` (`test_immich_sync_service.py`).

**E2E:** not applicable — Phase 4 only contracts backend/worker write paths; reads (and therefore frontend behaviour) are unchanged from Phase 3. The Phase-3 duplication-loop regression test stays green.

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — `external_references` is now write-free/read-free; album merge anchor lives on `sync_metadata.updated_at`, owned by `upsert_link`.

---

#### Phase 5: Drop `external_references` + clean up existing duplicates — ✅ COMPLETE

**PR Size:** ~5–7 files

> **Discovered during Phase 5:** one live reader was missed by Phase 3 —
> `logbook_export_repository.py` still `LEFT JOIN external_references` to read album
> `reference_data`. It is repointed to `sync_metadata.reference_data` here (Phase 4 already
> made `sync_metadata` the sole album link store) before the drop migration runs.
>
> **Migration numbers:** the head is `0091`, so the dedupe ships as
> **`0092_dedupe_bug_created_contacts.py`** (`down_revision = "0091"`) and the drop as
> **`0093_drop_external_references.py`** (`down_revision = "0092"`).
>
> **Live-method relocation (full removal):** `ExternalReferenceService` /
> `ExternalReferenceRepository` still hosted methods operating on `sync_metadata`/`contacts`.
> They are relocated to the canonical repos: `repoint_contact_references` →
> `SyncMetadataRepository.repoint_contact_links` (+ `ExternalReferenceCollision` renamed
> `IntegrationLinkCollision`); `upsert_contact_reference` → `SyncMetadataRepository.upsert_contact_link`;
> `contact_exists` → `SqlContactRepository.contact_exists`; `find_contact_with_birthday` →
> `IntegrationLinkRepository`. The dead `external_references` readers are deleted.

- [x] Repoint the last live reader (`logbook_export_repository.py`) off the
  `external_references` LEFT JOIN to read album `reference_data` directly from
  `sync_metadata` (a Phase-3 reader missed at the time).
- [x] Migration `0092_dedupe_bug_created_contacts.py` (data migration):
  - [x] Identify duplicate contacts created by this bug: an email-less Immich-origin contact (A) and an email-less `google`-linked contact (B) representing the same person. **Match discriminator:** since email-less is *not* exclusive to Immich (Google can import phone-only/empty contacts), name alone is too weak — a pair must share a normalised name **and** an identical full-precision **birthday** (the attribute the Immich-origin contact always carries and the round-trip preserves), so a false merge would need two distinct people with the same exact name and birthday. Merge B into A (survivor = the email-less Immich-linked original) with the **same re-point SQL the live `ContactMergeService` uses** (relationships, journal links, methods, addresses, notes, important dates, tags, top-level history, `sync_metadata` links), then delete B. **Dry-run mode (`-x dedupe_dry_run`) + full logging**; explicit threshold guard (`-x dedupe_max`/`dedupe_force`) and 1:1-only matching avoid over-merging.
  - [x] Reconcile orphaned links (sync_metadata rows whose `internal_id` no longer exists).
- [x] Migration `0093_drop_external_references.py`: drop the `external_references` table and its indexes after confirming no readers/writers remain (grep gate). The Phase 2 `link_backfill_quarantine` audit table is dropped here too.
- [x] Remove `external_reference.py` model, `ExternalReferenceService`, `ExternalReferenceRepository`, and dead imports — relocating the live methods to the canonical repos (`SyncMetadataRepository.upsert_contact_link` / `repoint_contact_links` + `IntegrationLinkCollision`, `IntegrationLinkRepository.find_contact_with_birthday`, `SqlContactRepository.contact_exists`).

**Required Test Coverage:**
- [x] **Integration (migration):** seed bug-shaped duplicates in an isolated DB → run dedupe → assert single merged contact with both links; assert idempotent (re-run is a no-op); assert non-duplicates untouched (`backend/tests/integration/integrations/test_dedupe_bug_created_contacts_migration.py`, which also covers ambiguous-skip, orphan reconciliation, dry-run, and the threshold guard).
- [x] **Integration:** drop migration leaves all sync flows green (`backend/tests/integration/integrations/test_drop_external_references_migration.py` + the full affected integration suite stays green; the Phase-3 duplication regression `test_link_consolidation_reads.py` remains green).

**E2E:** not applicable — Phase 5 only changes migrations + backend/worker internals; no API/UI behaviour change.

**Required Documentation Updates:**
- [x] `docs/architecture/integration-architecture.md` — `external_references` dropped; `sync_metadata` documented as the sole canonical link store; relocated live methods noted. (`database-design.md` already had no `external_references` references.)

---

#### Phase 6 (hardening, parallelisable): name-based reconciliation fallback for email-less contacts

**PR Size:** ~4 files

Defence in depth so an email-less contact can never silently duplicate even outside this loop: in the inbound consumer, when email reconciliation finds no match, fall back to `ContactNameMatcher` (already used by the Immich worker) against existing contacts; a single confident match reconciles (update), multiple matches record a conflict, none creates as today.

**Required Test Coverage:**
- **Unit/Integration:** email-less inbound contact with a single existing name match → reconciled, not duplicated; ambiguous match → conflict, not silent create.

---

#### Phase 7 (hardening, parallelisable): propagate local deletes to Google

**PR Size:** ~3 files

Address the observed "deletes don't stick — Google re-adds them": ensure a local contact delete emits `ContactDeleted` and the Google worker's `_delete_contact_from_google_for_event` removes the remote record (and the `sync_metadata` link), so a cleaned-up duplicate is not re-imported. Verify the merge-source delete path also propagates.

**Required Test Coverage:**
- **Integration:** delete a synced contact → remote delete invoked, link row removed, subsequent inbound sync does not recreate it.

---

## Risks & Mitigations

- **Reads switching before writes populate the new store:** avoided by the parallel-change ordering — dual-write + backfill (P2) make `sync_metadata` complete and current *before* reads move (P3).
- **Backfill ambiguity** (duplicate `external_references` rows): deterministic winner + quarantine table + Phase 5 review (no silent loss).
- **Wide blast radius of read/write repoint:** phased, additive-first, each phase independently green; grep-gate before the drop migration.
- **Over-aggressive dedupe in Phase 5:** dry-run + logging + conservative match criteria + idempotent re-run.
- **Worker/backend deploy skew:** Phases 1–3 keep `external_references` both written and read (P2 only *adds* `sync_metadata` writes), so an older worker still writing/reading `external_references` stays correct; the old writes are removed only in P4, after reads have moved.
