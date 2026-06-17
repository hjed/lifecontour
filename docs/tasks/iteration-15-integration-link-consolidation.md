# Iteration 15: Integration Link Consolidation (fix contact duplication)

**Status:** 🔴 PLANNED
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
3. **Additive then subtractive.** Schema and reads change before any writer is removed; `external_references` is dropped only after all reads/writes have moved.
4. **No silent data loss.** Backfill and cleanup migrations log every quarantined/merged row.

## Dependency and Parallelisation Notes

Phases are largely **sequential** because each depends on the previous one's schema/contract:
P1 (schema+backfill) → P2 (reads) → P3 (writes) → P4 (drop + dedupe). P5 (defensive name reconciliation) and P6 (delete propagation) are independent hardening tasks that may run in parallel with P2+ once P1 lands.

---

## Task Breakdown

### ITER15-001: Consolidate integration links onto `sync_metadata`

**Objective:** Make `sync_metadata` the single canonical store for integration entity links, retire `external_references`, and remove the duplication loop.

**Specification Reference:**
- [Integration Architecture → Core Components](../architecture/integration-architecture.md)
- [Database Design](../architecture/database-design.md)

**Acceptance Criteria (task-level):**
- [ ] Immich → Google → Immich round-trip never creates a duplicate contact (integration test).
- [ ] `external_references` table is dropped; no code reads or writes it.
- [ ] Existing bug-created duplicate contacts are merged; orphaned link rows reconciled.
- [ ] All integration link reads/writes flow through one repository with one schema.

---

#### Phase 1: Schema foundation + backfill (additive migration)

**PR Size:** ~6 files

Extend `sync_metadata` into the superset of both tables, then backfill from `external_references`. No behaviour change.

- Migration `0088_extend_sync_metadata_for_link_consolidation.py` (additive only):
  - Add nullable columns: `reference_data` (Text/JSONB), `internal_entity_type` (VARCHAR(50)), `external_entity_type` (VARCHAR(50)).
  - Backfill `internal_entity_type` / `external_entity_type` for existing rows from `integration_source` (e.g. `google`/`immich` → `contact`/`person`; `immich_album` → `journal`/`album`; `strava` → `journal`/`activity`; snipe-it variants → `gear_item`/`journal`).
  - Backfill from `external_references`: for each row, **upsert** a matching `sync_metadata` row keyed on `(external_system→integration_source, external_entity_id→external_id)`, carrying `internal_entity_id→internal_id`, the entity types, and `reference_data`. Where a `sync_metadata` row already exists, copy `reference_data`/entity types onto it.
  - **Conflict handling:** `external_references` allows duplicate `(external_system, external_entity_id)` rows but `sync_metadata` does not. The migration must deterministically pick one (prefer the row whose `internal_entity_id` matches an existing, non-duplicate contact; tie-break by lowest id) and **log** every skipped row to a temporary `link_backfill_quarantine` audit table for Phase 4.
  - Backfilled-only rows (no prior sync_metadata) get `version_hash = ''` so the next sync re-validates content.
- Update the `SyncMetadata` model (`core_shared/.../models/sync_metadata.py`) with the new columns.

**Required Test Coverage:**
- **Integration (migration):** isolated-DB migration test (mirror `tests/integration/history/test_field_history_migration.py`) covering: contact with only an `external_references(google)` row → backfilled into `sync_metadata`; the bug case (contact with `immich` external_ref + `google` sync_metadata only) → both links present after; duplicate `external_references` rows → one wins, the rest quarantined; album `reference_data` copied intact.
- **Unit:** model column round-trip.

**Required Documentation Updates:**
- `docs/architecture/integration-architecture.md` — note `sync_metadata` as the canonical link store (mark `external_references` deprecated, removal pending).

---

#### Phase 2: Move all reads to `sync_metadata` (this fixes the bug)

**PR Size:** ~8–10 files

Introduce unified link-lookup methods on `SyncMetadataRepository` (or a thin `IntegrationLinkRepository` wrapper) and repoint every reader off `external_references`:

- `find_link_by_external(integration_source, external_id) -> link | None`
- `find_internal_by_external(...) -> (internal_id, internal_uuid, internal_entity_type)`
- `find_external_by_internal(internal_entity_type, internal_id, integration_source)`

Readers to repoint:
- **Backend consumer** (`outbox_event_processor.py`): `_process_contact_created` idempotency (`find_by_external_id`) and `_process_contact_updated`'s `find_contact_by_external_reference` → read `sync_metadata`. **← removes the duplication.**
- `contact_repository.find_by_external_reference` / `get_external_references` → `sync_metadata`.
- **Immich worker**: `_find_external_reference`, `ExternalReferenceRepository.get_immich_person_id` / `get_person_id_to_contact_id_map` / `find_by_internal_entity` → `sync_metadata` (+ `reference_data`/entity types).
- **Album read repo** (`album_sync_read_repository.py`): drop the `external_references` join; read `reference_data` from `sync_metadata`.
- **Merge collision detection** (`repoint_external_references_on_contact_merge` reads) → `sync_metadata`.

**Required Test Coverage:**
- **Integration (the regression):** reproduce Immich creates email-less contact → outbound push writes `sync_metadata(google,…)` → Google inbound `contact.updated`/`created` → assert **exactly one** contact and it is updated, not duplicated.
- **Integration:** idempotency — re-delivering `contact.created` for an already-linked external id is skipped; album display data still resolves from `reference_data`.
- **Worker integration:** Immich create-vs-update decision still correct reading `sync_metadata`.

**Required Documentation Updates:**
- `docs/architecture/integration-architecture.md` — inbound/outbound flow now keys dedup on `sync_metadata`.

---

#### Phase 3: Move all writes to `sync_metadata`; stop writing `external_references`

**PR Size:** ~8–10 files

Every writer persists the canonical link (and `reference_data`/entity types) to `sync_metadata` only:

- Backend `ExternalReferenceService.create/update/upsert_contact_reference` → write `sync_metadata` (or delete the service and inline via the repo).
- Immich worker `_create_external_reference` → `sync_metadata` upsert.
- Album `upsert_or_insert` / `delete` → `sync_metadata` (`reference_data`).
- Merge repoint (`repoint_external_references_on_contact_merge`) → operate on `sync_metadata` rows only.
- Confirm the **Google outbound push** and **Immich outbound push** set `internal_entity_type`/`external_entity_type` (they already write `sync_metadata`).
- Ensure all link writes occur inside the existing committed unit of work (no swallowed-and-uncommitted writes; align with the #945 commit-timing rule).

**Required Test Coverage:**
- **Integration:** each write path (inbound create/update, immich auto-link, album create, contact merge) produces the correct single `sync_metadata` row and **zero** `external_references` writes.
- **Unit:** repository write methods.

---

#### Phase 4: Drop `external_references` + clean up existing duplicates

**PR Size:** ~5–7 files

- Migration `0089_dedupe_bug_created_contacts.py` (data migration):
  - Identify duplicate contacts created by this bug: an email-less Immich-origin contact and a `google`-sourced contact representing the same person (match on normalised name + Immich/Google link lineage; cross-check the Phase 1 quarantine table). Merge them via the existing contact-merge logic (survivor = the contact retaining the richest data / oldest id), repointing `sync_metadata` links. **Dry-run mode + full logging**; require an explicit flag/threshold guard to avoid over-merging.
  - Reconcile orphaned links (sync_metadata rows whose `internal_id` no longer exists).
- Migration `0090_drop_external_references.py`: drop the `external_references` table and its indexes after confirming no readers/writers remain (grep gate in PR description).
- Remove `external_reference.py` model, `ExternalReferenceService`, `ExternalReferenceRepository`, and dead imports.

**Required Test Coverage:**
- **Integration (migration):** seed bug-shaped duplicates in an isolated DB → run dedupe → assert single merged contact with both links; assert idempotent (re-run is a no-op); assert non-duplicates untouched.
- **Integration:** drop migration leaves all sync flows green.

**Required Documentation Updates:**
- `docs/architecture/integration-architecture.md` & `database-design.md` — remove `external_references`; document the consolidated schema.

---

#### Phase 5 (hardening, parallelisable): name-based reconciliation fallback for email-less contacts

**PR Size:** ~4 files

Defence in depth so an email-less contact can never silently duplicate even outside this loop: in the inbound consumer, when email reconciliation finds no match, fall back to `ContactNameMatcher` (already used by the Immich worker) against existing contacts; a single confident match reconciles (update), multiple matches record a conflict, none creates as today.

**Required Test Coverage:**
- **Unit/Integration:** email-less inbound contact with a single existing name match → reconciled, not duplicated; ambiguous match → conflict, not silent create.

---

#### Phase 6 (hardening, parallelisable): propagate local deletes to Google

**PR Size:** ~3 files

Address the observed "deletes don't stick — Google re-adds them": ensure a local contact delete emits `ContactDeleted` and the Google worker's `_delete_contact_from_google_for_event` removes the remote record (and the `sync_metadata` link), so a cleaned-up duplicate is not re-imported. Verify the merge-source delete path also propagates.

**Required Test Coverage:**
- **Integration:** delete a synced contact → remote delete invoked, link row removed, subsequent inbound sync does not recreate it.

---

## Risks & Mitigations

- **Backfill ambiguity** (duplicate `external_references` rows): deterministic winner + quarantine table + Phase 4 review (no silent loss).
- **Wide blast radius of read/write repoint:** phased, additive-first, each phase independently green; grep-gate before the drop migration.
- **Over-aggressive dedupe in Phase 4:** dry-run + logging + conservative match criteria + idempotent re-run.
- **Worker/backend deploy skew:** Phases 1–2 keep `external_references` intact, so an older worker still writing it stays correct until Phase 3/4.
