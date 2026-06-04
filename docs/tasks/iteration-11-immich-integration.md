# Iteration 11: Immich Integration

**Status:** 🟡 IN PROGRESS
**Dependencies:** Iteration 5 (Integration Architecture, Generic Dashboard, Redis Streams Event Bus), Iteration 7.1 (Journal Contact Links)
**Goal:** Deliver a bidirectional integration with a self-hosted Immich instance for contact/people sync (including avatars), album import as PHOTO_ALBUM journals, and on-demand album creation from journal date ranges.

## Overview

This iteration delivers the approved [Immich Integration Product Specification](../product-specifications/immich-integration-product-specification.md) in incremental, shippable slices. Each task delivers end-to-end functionality across backend, frontend, and MCP where applicable.

The work builds on the existing Redis Streams event bus and pluggable integration UI from Iteration 5, and the journal contact link system from Iteration 7.1.

## Reference Documents

- **[Immich Integration Product Specification](../product-specifications/immich-integration-product-specification.md)** — approved product behaviour for this iteration
- **[Integration Architecture](../architecture/integration-architecture.md)** — event-driven integration patterns
- **[Contacts Product Specification](../product-specifications/contacts-product-specification.md)** — contact management and sync principles
- **[Iteration 5: Integration Architecture & Strava](./iteration-5-integration-architecture-and-strava.md)** — foundation for the event bus and dashboard
- **[Iteration 10: Snipe-IT Integration](./iteration-10-snipe-it-integration.md)** — API key auth pattern reference

## Delivery Rules

1. **Tests first:** write failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks pass.
3. **Reviewable PRs:** keep each PR to roughly ≤ 10 files where practical.
4. **MCP parity:** if a capability is meaningful in the UI, expose through MCP in the same task.
5. **Full vertical slice:** each task delivers backend, frontend (where applicable), and MCP together.
6. **Every task is shippable:** no task may rely on a later task to restore broken behaviour.

## Dependency and Parallelisation Notes

- **Task 1 (Infrastructure & Auth)** can begin immediately. It depends only on Iteration 5's completed generic dashboard.
- **Task 2 (Contact Sync)** depends on Task 1 (API client and auth required).
- **Task 3 (Contact Avatars)** depends on Task 2 (contacts must be synced before avatars are meaningful).
- **Task 4 (Album Import)** depends on Task 1 (API client) and Task 2 (contact sync for participant detection). Includes PhotoAlbumData cleanup.
- **Task 5 (External Links & Logbook Export)** depends on Tasks 2 and 4 (synced data must exist for links).
- **Task 6 (Album Creation)** depends on Task 4 (album import patterns established). **Implement last.**

---

## Task Breakdown

### ITER11-001: Immich Worker Infrastructure, Auth, and Registry

**Objective:** Establish the Immich integration worker, implement API key authentication, and register Immich in the generic integrations dashboard.

**Specification Reference:**
- [Part 1: Authentication & Configuration](../product-specifications/immich-integration-product-specification.md#part-1-authentication--configuration)
- [Part 8: Immich ARQ Worker](../product-specifications/immich-integration-product-specification.md#part-8-immich-arq-worker)

**Acceptance Criteria (task-level):**
- [ ] `integration_workers/immich/` package structure created following isolated worker pattern.
- [ ] API key auth with encrypted DB storage working end-to-end.
- [ ] Integration registry includes Immich with connect/disconnect controls.

#### Phase 1: Worker Package, Auth Model, and Registry
**PR Size:** ~7–9 files

Create the worker scaffold, database models for auth, and integrate with the pluggable dashboard.

**Acceptance Criteria:**
- [x] `integration_workers/immich/` package created (following Strava/Snipe-IT worker structure)
- [x] Migration creates `user_immich_auth` table (`user_id`, `server_url`, `api_key` encrypted, `created_at`, `updated_at`)
- [x] Remove legacy `immich_base_url` and `immich_api_key` from `backend/app/infrastructure/config.py`
- [x] `ImmichIntegrationProvider` implements registry interface: derives status from `user_immich_auth` state
- [x] `POST /api/integrations/immich/connect` — validates API key against Immich `GET /server/about`, stores encrypted credentials
- [x] `POST /api/integrations/immich/disconnect` — removes credentials
- [x] Immich panel appears in integrations dashboard with Server URL + API Key inputs and Connect/Disconnect controls
- [x] Worker tests and linting are setup and included in ci

**Required Test Coverage:**
- **Unit:** API key encryption/decryption, registry provider status derivation, connect endpoint validation logic.
- **Integration:** Connect with valid key (mocked Immich API), connect with invalid key rejected, disconnect cleanup.
- **E2E:** Immich panel appears in dashboard, connect form submits cleanly.

#### Phase 2: API Client and Worker Shell
**PR Size:** ~6–8 files

Build the `ImmichApiClient` with all methods needed for sync, and the ARQ worker container.

**Acceptance Criteria:**
- [x] `ImmichApiClient` class using `httpx` async client with API key header injection
- [x] Client methods: `get_server_info()`, `get_all_people()`, `get_person(id)`, `update_person(id, data)`, `get_person_thumbnail(id)`, `get_all_albums()`, `get_album(id)`, `create_album(data)`, `search_assets(filters)`, `get_asset_thumbnail(id)`, `get_shared_links()`, `create_shared_link(data)`
- [x] Pydantic response models: `ImmichPerson`, `ImmichAlbum`, `ImmichAsset`, `ImmichSharedLink`
- [x] `integration_workers/immich/worker.py` — ARQ worker entry point with health checks
- [x] Worker registers as `immich-worker` consumer group on Redis Stream
- [x] Immich worker added to `docker-compose.yml` and CI
- [x] `ImmichWorkerStreamConsumer` for consuming outbound domain events
- [x] Release build included immich worker

**Required Test Coverage:**
- **Unit:** Response model parsing for each endpoint, API key header injection, error handling (401, 404, 500).
- **Integration:** API client with mocked HTTP responses (httpx MockTransport) for each method.

#### Phase 3: Periodic Sync Infrastructure
**PR Size:** ~3–5 files

Set up the periodic sync scheduling and manual sync triggers.

**Acceptance Criteria:**
- [x] `periodic_sync_all_immich_accounts(ctx)` ARQ task — iterates all connected users and triggers sync
- [x] Manual sync trigger from integrations dashboard via `POST /api/integrations/immich/sync`
- [x] `SyncJob` records created for each sync run
- [x] Sync controls visible on Immich integration panel (Sync People, Sync Albums buttons)
- [x] MCP: `trigger_sync` tool updated/verified for Immich
- [x] Full and partial sync supported

**Required Test Coverage:**
- **Unit:** Periodic task iterates users, sync job creation.
- **Integration:** Manual sync trigger endpoint, sync job recorded in DB, manual trigger successfully hits agent.
- **E2E:** Sync button visibility when connected/disconnected, sync trigger API call via Playwright.

---

### ITER11-002: Contact Sync (People) — Two-Way

**Objective:** Implement bidirectional contact synchronisation between Immich People and local contacts, with name-based matching and conflict resolution.

**Specification Reference:**
- [Part 2: Contact Sync — Two-Way](../product-specifications/immich-integration-product-specification.md#part-2-contact-sync-people--two-way)
- [Part 9: Contact Name Matcher extraction](../product-specifications/immich-integration-product-specification.md#part-9-commonalities-with-existing-integrations)

**Acceptance Criteria (task-level):**
- [ ] Immich People sync bidirectionally with local contacts.
- [ ] Name-based matching prevents duplicate contacts.
- [ ] Conflict resolution UI and MCP for ambiguous matches.
- [ ] Birthday sync with precision-aware rules.

#### Phase 1: Inbound People Sync and Name Matching
**PR Size:** ~8–10 files

Implement the core inbound sync: fetch Immich people, match to contacts, create/update as needed.

**Acceptance Criteria:**
- [x] `ImmichSyncService.sync_people(user_id)` fetches all people from Immich, processes each
- [x] `ContactNameMatcher` utility extracted to `core_shared` — supports: exact match, middle initial variants, abbreviated last name (reusable by Strava)
- [x] Immich name parsing: split on last space → `first_name` + `last_name`
- [x] Matching flow: check `ExternalReference` first → `ContactNameMatcher` → single match auto-links → multiple matches create conflict → no match creates new contact
- [x] `ExternalReference` records created for each person-to-contact mapping
- [x] `SyncMetadata` tracks sync state with version hash of name + birthDate
- [x] Birthday sync inbound: create BIRTHDAY `ImportantDate` (precision=FULL) if contact has none; skip if existing
- [x] Conflict records stored in a `pending_entity_mappings` table for unresolved ambiguous matches

**Required Test Coverage:**
- **Unit:** ContactNameMatcher (exact, middle initial, abbreviated last name, case insensitive, no match, multi-match), name parsing, birthday sync skip logic. ✅ 18 tests in core_shared, 15 tests in immich worker
- **Integration:** Full people sync with mocked Immich API — new contact creation, existing contact matching, conflict detection, birthday creation.

#### Phase 2: Outbound Contact Sync and Conflict Resolution
**PR Size:** ~7–9 files

Push local contact changes to Immich and provide conflict resolution UI + MCP.

**Acceptance Criteria:**
- [ ] Stream consumer handles `contact.created`, `contact.updated`, `contact.birthday_changed` events
- [ ] Outbound sync: push name and birthday (FULL precision only) to Immich `PUT /people/{id}`
- [ ] Non-full-precision birthdays skipped without clearing Immich's existing birthDate
- [ ] Source of truth enforcement: local values win on conflict
- [x] `GET /api/integrations/immich/conflicts` — list unresolved sync conflicts
- [x] `POST /api/integrations/immich/conflicts/{id}/resolve` — resolve by mapping person to contact
- [ ] Conflict resolution UI on Immich integration panel: shows Immich person name + thumbnail, candidate contacts, "Link" / "Create New" actions
- [x] MCP tools: `list_immich_conflicts`, `resolve_immich_conflict`

**Required Test Coverage:**
- **Unit:** Outbound sync field mapping, birthday precision filtering, conflict resolution logic.
- **Integration:** Contact update → outbound sync to mocked Immich API. Conflict resolution → ExternalReference created, re-sync succeeds.
- **E2E:** Conflict resolution dialog appears and resolves correctly.

---

### ITER11-003: Contact Avatars (Feature Photo)

**Objective:** Add contact avatar support using Immich People feature photos. This is a new capability for the contacts system.

**Specification Reference:**
- [Part 2: Contact Avatar — New Capability](../product-specifications/immich-integration-product-specification.md#contact-avatar-feature-photo--new-capability)

**Acceptance Criteria (task-level):**
- [ ] New `photo_url` field on contacts, populated from Immich feature photos.
- [ ] Backend proxy for Immich thumbnails.
- [ ] `ContactAvatar` component displays photos throughout the UI.

#### Phase 1: Backend — Photo URL Field and Proxy Endpoint
**PR Size:** ~5–7 files

Add the `photo_url` field to the contact entity/table and implement the backend image proxy.

**Acceptance Criteria:**
- [ ] Migration adds `photo_url` column to `contacts` table (nullable `String(500)`)
- [ ] `Contact` entity updated with `photo_url` field
- [ ] `GET /api/contacts/{id}/avatar` proxy endpoint — fetches thumbnail from Immich `GET /people/{person_id}/thumbnail` using stored credentials
- [ ] Photo URL set to proxy endpoint URL during contact sync (not direct Immich URL)
- [ ] `photo_url` included in contact API responses and MCP responses
- [ ] Photo URL updated on each people sync cycle

**Required Test Coverage:**
- **Unit:** Proxy URL construction, photo_url field in API schemas.
- **Integration:** Avatar proxy endpoint returns image bytes from mocked Immich. Contact sync populates photo_url.

#### Phase 2: Frontend — Avatar Display
**PR Size:** ~4–6 files

Wire the `ContactAvatar` component to display Immich photos.

**Acceptance Criteria:**
- [ ] `ContactAttributes` TypeScript type updated with optional `photo_url` field
- [ ] `ContactAvatar` component's `imageUrl` prop wired to `photo_url` from API response
- [ ] Avatars display on: contact list, contact detail page, journal participant list, search results
- [ ] Graceful fallback to initials when `photo_url` is null or image fails to load
- [ ] Loading state while avatar image fetches

**Required Test Coverage:**
- **Unit:** ContactAvatar renders image when URL present, falls back to initials when absent/errored.
- **E2E:** Contact with Immich link shows avatar image. Contact without link shows initials.

---

### ITER11-004: Album Import as PHOTO_ALBUM Journals

**Objective:** Import Immich albums as journals with PHOTO_ALBUM type, derive date ranges from photos, detect participants from people tags, and display album cover photos.

**Specification Reference:**
- [Part 3: Album Sync — Two-Way](../product-specifications/immich-integration-product-specification.md#part-3-album-sync-journals--two-way)
- [Part 3: Cleanup — PhotoAlbumData Entity](../product-specifications/immich-integration-product-specification.md#cleanup-photoalbumdata-entity)

**Acceptance Criteria (task-level):**
- [ ] Immich albums imported as PHOTO_ALBUM journals.
- [ ] Date ranges derived from photo timestamps.
- [ ] Participants detected from people tags.
- [ ] Album cover photo displayed as banner.
- [ ] PhotoAlbumData entity cleaned up.

#### Phase 1: PhotoAlbumData Cleanup and Album Sync Backend
**PR Size:** ~8–10 files

Remove the scaffolding `PhotoAlbumData` entity and implement album import using standard integration patterns.

**Acceptance Criteria:**
- [ ] Migration removes `journal_photo_album_data` table
- [ ] `PhotoAlbumData` entity, `SqlPhotoAlbumDataRepository`, and related tests removed
- [ ] `PHOTO_ALBUM` type enum value preserved — type detection now based on `SyncMetadata` with `integration_source="immich_album"`
- [ ] Frontend `PhotoAlbumTypeEditor` and `PhotoAlbumDataDisplay` updated to work with `ExternalReference` data instead of `PhotoAlbumData`
- [ ] `ImmichSyncService.sync_albums(user_id)` — fetches all albums, creates/updates journals
- [ ] Date range derivation: earliest/latest `takenAt` from album photos → `event_date_range` (with timezone conversion)
- [ ] Field merge protection: title, content, date range protected when `journal.updated_at > link.updated_at`
- [ ] `SyncMetadata` records: `integration_source="immich_album"`, `external_id`=album UUID, `version_hash`=hash of album metadata

**Required Test Coverage:**
- **Unit:** Date range derivation from photo timestamps, timezone conversion, merge protection logic, version hash calculation.
- **Integration:** Album sync creates journal with correct date range. Re-sync with local edits preserves protected fields. PhotoAlbumData removal migration succeeds.

#### Phase 2: Participant Detection and Album Cover Display
**PR Size:** ~6–8 files

Detect participants from photo people tags and display album cover photos on journals.

**Acceptance Criteria:**
- [ ] Sync fetches all assets in album, resolves tagged people to local contacts via `ExternalReference`
- [ ] Resolved contacts added as PARTICIPANT on journal via `JournalContactRelationship`
- [ ] Change detection on re-sync: new people added, removed people removed
- [ ] Unresolved Immich people (not yet synced as contacts) skipped — no orphan participants
- [ ] Shared link detection: query `GET /shared-links`, store URL in `ExternalReference.reference_data` JSON
- [ ] `GET /api/journals/{id}/album-cover` proxy endpoint — fetches album cover thumbnail from Immich
- [ ] Journal edit/detail screen: album cover photo displayed as banner (fetched on-demand, not persisted)
- [ ] Banner clickable to open album in Immich web UI

**Required Test Coverage:**
- **Unit:** Participant resolution from people tags, change detection (add/remove), shared link extraction.
- **Integration:** Album with tagged people → participants created on journal. Re-sync with removed tag → participant removed. Cover photo proxy returns image bytes.
- **E2E:** PHOTO_ALBUM journal shows album cover banner and participant list.

---

### ITER11-005: External Links and Logbook Export

**Objective:** Surface Immich external links on journals and contacts, ensure MCP parity, and enhance the logbook PDF export with album shared links.

**Specification Reference:**
- [Part 4: Integration Links](../product-specifications/immich-integration-product-specification.md#part-4-integration-links-external-system-links)
- [Part 6: Logbook Export Enhancement](../product-specifications/immich-integration-product-specification.md#part-6-logbook-export-enhancement)

**Acceptance Criteria (task-level):**
- [ ] External links displayed for Immich-linked journals and contacts.
- [ ] MCP responses include Immich external links and support search filters.
- [ ] Logbook PDF export includes album shared links.

#### Phase 1: External Links and MCP
**PR Size:** ~5–7 files

Extend external link helpers and MCP tools for Immich.

**Acceptance Criteria:**
- [ ] `build_journal_external_links` and `build_contact_external_links` in `external_link_helpers.py` extended for Immich sources
- [ ] URL construction: People → `{server_url}/people/{person_id}`, Albums → `{server_url}/albums/{album_id}`
- [ ] Journal detail page: Immich album link displayed alongside other external links
- [ ] Contact detail page: Immich person link displayed
- [ ] If public shared link exists: displayed as additional link with source `"immich_shared"`
- [ ] MCP: `get_journal` and `get_contact` responses include Immich external links via `ExternalLinkSchema`
- [ ] MCP: `search_journals` supports `integration_source=immich_album` filter

**Required Test Coverage:**
- **Unit:** URL construction for Immich people and albums, external link helper extension, MCP schema updates.
- **Integration:** API returns correct external links for Immich-linked journals and contacts, MCP search filters work.
- **E2E:** PHOTO_ALBUM journal shows Immich album link. Immich-linked contact shows person link.

#### Phase 2: Logbook Export Enhancement
**PR Size:** ~3–5 files

Add album shared links to the logbook PDF export.

**Acceptance Criteria:**
- [ ] `LogbookEntryData` extended with `album_shared_link: str | None` field
- [ ] `LogbookExportRepository` populates `album_shared_link` from `ExternalReference.reference_data` for PHOTO_ALBUM journals
- [ ] `LogbookPdfRenderer._render_entry` renders shared link as clickable hyperlink: `📷 Photo Album: {url}`
- [ ] Link positioned after the contacts/participants line in entry layout

**Required Test Coverage:**
- **Unit:** PDF renderer includes album link when present, omits when absent.
- **Integration:** Logbook export with PHOTO_ALBUM journal includes shared link in PDF text.

---

### ITER11-006: Album Creation from Journal Date Range

**Objective:** Enable on-demand Immich album creation from a journal's date range with photo selection and optional public sharing links. **Implement last.**

**Specification Reference:**
- [Part 5: Album Creation from Journal Date Range](../product-specifications/immich-integration-product-specification.md#part-5-album-creation-from-journal-date-range)

**Acceptance Criteria (task-level):**
- [ ] Users can create Immich albums from journal date ranges.
- [ ] Photo selection dialog with deselection.
- [ ] Optional public shared link creation.
- [ ] MCP parity for album creation.

#### Phase 1: Backend — Date Range Photo Search and Album Creation
**PR Size:** ~6–8 files

Implement the backend APIs for searching photos by date range and creating albums.

**Acceptance Criteria:**
- [ ] `POST /api/integrations/immich/search-photos` — queries Immich `POST /search/metadata` with `takenAfter`/`takenBefore` from journal's `event_date_range` (with timezone-aware day boundary expansion)
- [ ] Returns photo thumbnails and metadata for UI display
- [ ] `POST /api/integrations/immich/create-album` — accepts journal ID, selected asset IDs, and `create_shared_link` boolean
- [ ] Creates album in Immich via `POST /albums` with `albumName` = journal title
- [ ] If `create_shared_link=true`: creates shared link via `POST /shared-links`, stores URL in `ExternalReference.reference_data`
- [ ] Creates `SyncMetadata` and `ExternalReference` records linking journal to new album
- [ ] Adds `PHOTO_ALBUM` type to journal's type list
- [ ] MCP tools: `search_immich_photos_for_journal(journal_id)`, `create_immich_album_for_journal(journal_id, create_shared_link, exclude_asset_ids)`

**Required Test Coverage:**
- **Unit:** Timezone day boundary expansion, album creation request construction, shared link storage.
- **Integration:** Search photos returns results from mocked Immich. Create album → SyncMetadata + ExternalReference + PHOTO_ALBUM type added.

#### Phase 2: Frontend — Photo Selection Dialog and Create Album Button
**PR Size:** ~5–7 files

Build the UI for browsing photos and creating albums from journal edit screens.

**Acceptance Criteria:**
- [ ] "Create Album" button visible on journal edit screen when: Immich connected, `event_date_range` set, no existing linked album
- [ ] Button triggers photo search; loading state while fetching
- [ ] Photo selection dialog: grid of photo thumbnails with checkboxes (all selected by default)
- [ ] User can deselect individual photos
- [ ] Checkbox option: "Create public shared link"
- [ ] On confirm: calls create-album API, shows success state, journal refreshes to show album banner and external link
- [ ] Button hidden when journal already has a linked album

**Required Test Coverage:**
- **Unit:** Create Album button visibility logic, photo selection state management.
- **E2E:** Open journal without album, click Create Album, deselect a photo, confirm creation, verify album banner appears.

---

## Success Criteria

- Immich People sync bidirectionally with contacts, with name matching and conflict resolution.
- Contact avatars display Immich feature photos throughout the UI.
- Immich albums import as PHOTO_ALBUM journals with correct date ranges and participants.
- Album cover photos display as banners on journal edit screens.
- External system links appear on journals and contacts for Immich-linked entities.
- Users can create Immich albums from journal date ranges with optional shared links.
- The logbook PDF export includes album shared links.
- All Immich features are accessible through MCP tools.
- The integration follows the pluggable dashboard pattern and can be connected/disconnected independently.

## Phase Summary

| Task | Phases | Total est. PRs |
|---|---|---|
| ITER11-001: Worker Infrastructure & Auth | 3 | 3 |
| ITER11-002: Contact Sync (People) | 2 | 2 |
| ITER11-003: Contact Avatars | 2 | 2 |
| ITER11-004: Album Import | 2 | 2 |
| ITER11-005: External Links & Export | 2 | 2 |
| ITER11-006: Album Creation | 2 | 2 |
| **Total** | **13** | **13** |
