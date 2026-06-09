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
- [x] Immich People sync bidirectionally with local contacts.
- [x] Name-based matching prevents duplicate contacts.
- [x] Conflict resolution UI and MCP for ambiguous matches.
- [x] Birthday sync with precision-aware rules.

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
- [x] Stream consumer handles `contact.created`, `contact.updated`, `contact.birthday_changed` events
- [x] Outbound sync: push name and birthday (FULL precision only) to Immich `PUT /people/{id}`
- [x] Non-full-precision birthdays skipped without clearing Immich's existing birthDate
- [x] Source of truth enforcement: local values win on conflict
- [x] `GET /api/integrations/immich/conflicts` — list unresolved sync conflicts
- [x] `POST /api/integrations/immich/conflicts/{id}/resolve` — resolve by mapping person to contact
- [x] Conflict resolution UI on Immich integration panel: shows Immich person name + thumbnail, candidate contacts, "Link" / "Create New" actions
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
- [x] New `photo_url` field on contacts, populated from Immich feature photos.
- [x] Backend proxy for Immich thumbnails.
- [ ] `ContactAvatar` component displays photos throughout the UI.

#### Phase 1: Backend — Photo URL Field and Proxy Endpoint
**PR Size:** ~5–7 files

Add the `photo_url` field to the contact entity/table and implement the backend image proxy.

**Acceptance Criteria:**
- [x] Migration adds `photo_url` column to `contacts` table (nullable `String(500)`)
- [x] `Contact` entity updated with `photo_url` field
- [x] `GET /api/contacts/{id}/avatar` proxy endpoint — fetches thumbnail from Immich `GET /people/{person_id}/thumbnail` using stored credentials
- [x] Photo URL set to proxy endpoint URL during contact sync (not direct Immich URL)
- [x] `photo_url` included in contact API responses and MCP responses
- [x] Photo URL updated on each people sync cycle

**Required Test Coverage:**
- **Unit:** Proxy URL construction, photo_url field in API schemas.
- **Integration:** Avatar proxy endpoint returns image bytes from mocked Immich. Contact sync populates photo_url.

#### Phase 2: Frontend — Avatar Display ✅
**PR Size:** ~4–6 files

Wire the `ContactAvatar` component to display Immich photos.

**Acceptance Criteria:**
- [x] `ContactAttributes` TypeScript type updated with optional `photo_url` field
- [x] `ContactAvatar` component's `imageUrl` prop wired to `photo_url` from API response
- [x] Avatars display on: contact list, contact detail page, journal participant list, search results
- [x] Graceful fallback to initials when `photo_url` is null or image fails to load
- [x] Loading state while avatar image fetches (AvatarFallback shows initials while image loads)

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
- [x] Immich albums imported as PHOTO_ALBUM journals. *(Phase 1)*
- [x] Date ranges derived from photo timestamps. *(Phase 1)*
- [x] Participants detected from people tags. *(Phase 2)*
- [x] Album cover photo displayed as banner. *(Phase 2)*
- [x] PhotoAlbumData entity cleaned up. *(Phase 1)*

#### Phase 1: PhotoAlbumData Cleanup and Album Sync Backend
**PR Size:** ~8–10 files

Remove the scaffolding `PhotoAlbumData` entity and implement album import using standard integration patterns.

**Architecture note (as implemented):** Album import follows the worker→outbox→backend pattern used by contact sync (the calendar-coupled `JournalOutboxEventProcessor` is *not* reused). The worker emits new `immich_album.created` / `immich_album.updated` outbox events; the backend `InboundEventConsumer` routes the `immich_album.*` prefix to a new `ImmichAlbumOutboxEventProcessor` which creates/updates the journal and records `SyncMetadata` (`integration_source="immich_album"`) + an `external_references` album link. PHOTO_ALBUM type detection now derives from that `SyncMetadata` row. Date-range timezone uses each photo's EXIF timezone with a UTC fallback. The manual `PhotoAlbumTypeEditor` was removed (albums are integration-managed, not user-entered); `PhotoAlbumDataDisplay` now shows the synced album name/link. Album sync is triggerable via `POST /api/integrations/immich/album/sync` and the `sync_immich_albums` ARQ task.

**Acceptance Criteria:**
- [x] Migration removes `journal_photo_album_data` table
- [x] `PhotoAlbumData` entity, `SqlPhotoAlbumDataRepository`, and related tests removed
- [x] `PHOTO_ALBUM` type enum value preserved — type detection now based on `SyncMetadata` with `integration_source="immich_album"`
- [x] Frontend `PhotoAlbumTypeEditor` removed and `PhotoAlbumDataDisplay` updated to render synced album data (`ExternalReference`/`SyncMetadata`) instead of `PhotoAlbumData`
- [x] `ImmichSyncService.sync_albums()` — fetches all albums, emits create/update events that create/update journals
- [x] Date range derivation: earliest/latest `takenAt` from album photos → `event_date_range` (with timezone conversion)
- [x] Field merge protection: title, content, date range protected when `journal.updated_at > link.updated_at`
- [x] `SyncMetadata` records: `integration_source="immich_album"`, `external_id`=album UUID, `version_hash`=hash of album metadata

**Required Test Coverage:**
- **Unit:** Date range derivation from photo timestamps, timezone conversion, merge protection logic, version hash calculation. ✅ 16 worker tests (`test_immich_album_sync.py`) + 7 processor-logic tests (`test_immich_album_outbox_processor.py`) + 2 payload-dispatch tests (`test_outbox_events.py`)
- **Integration:** Album sync creates journal with correct date range. Re-sync with local edits preserves protected fields. PhotoAlbumData removal migration succeeds. ✅ 4 processor tests (`test_immich_album_outbox_processor.py`) + 7 type-detection/migration tests (`test_journal_type_detection.py`) + album-sync trigger endpoint test

#### Phase 2: Participant Detection and Album Cover Display
**PR Size:** ~6–8 files

Detect participants from photo people tags and display album cover photos on journals.

**Architecture note (as implemented):** Participant detection follows the worker→outbox→backend pattern.
The Immich worker aggregates the unique people tagged across an album's photos (`ImmichSyncService.aggregate_album_people`) and emits them, plus the album web URL and any public `shared_link_url`, in the `immich_album.*` outbox event's `album_metadata`. The album `version_hash` now folds in the sorted tagged-person ids and the shared-link URL so a pure face-tag or share-link change still triggers a re-sync. The backend `ImmichAlbumOutboxEventProcessor` resolves those person ids to local contacts via a new `ExternalReferenceRepository.get_contact_ids_by_immich_person_ids` reverse lookup (unresolved people are skipped — no orphans) and reconciles `PARTICIPANT` relationships through `SqlJournalContactRelationshipRepository`. Participants are **not** merge-protected: additions always run, but **removals run only when the journal has not been edited locally** (add-only when locally edited, per product decision). The immich-managed contact set is tracked in the album `external_references.reference_data` (`participant_contact_ids`), so the remove step only ever touches that set — **manually-added participants are never removed**. *(Documented limitation: a contact that is both manually added and an immich-tagged person resolves to immich provenance.)* The shared-link URL is persisted in `reference_data`. The album cover is served on-demand by a new `AlbumCoverProxyService` behind `GET /api/journals/{id}/album-cover` (mirrors the contact-avatar proxy: SSRF scheme check, credential lookup, `GET /api/assets/{id}/thumbnail`); the proxy URL is surfaced as `cover_url` on `PhotoAlbumDataSchema` and rendered as a clickable banner (shared `AlbumCoverBanner` component, with graceful `onError` fallback) in the PHOTO_ALBUM section of the journal detail/edit screen, linking to the album in Immich. *(`ImmichApiClient.get_album` is unchanged; Immich's single-album endpoint returns per-asset `people` — verified by the worker tests' fixtured payloads.)*

**Acceptance Criteria:**
- [x] Sync fetches all assets in album, resolves tagged people to local contacts via `ExternalReference`
- [x] Resolved contacts added as PARTICIPANT on journal via `JournalContactRelationship`
- [x] Change detection on re-sync: new people added, removed people removed (removals gated by merge protection — add-only when locally edited)
- [x] Unresolved Immich people (not yet synced as contacts) skipped — no orphan participants
- [x] Shared link detection: query `GET /shared-links`, store URL in `ExternalReference.reference_data` JSON
- [x] `GET /api/journals/{id}/album-cover` proxy endpoint — fetches album cover thumbnail from Immich
- [x] Journal edit/detail screen: album cover photo displayed as banner (fetched on-demand, not persisted)
- [x] Banner clickable to open album in Immich web UI

**Required Test Coverage:**
- **Unit:** Participant resolution from people tags, change detection (add/remove), shared link extraction. ✅ 6 worker tests (`test_immich_album_sync.py`: people aggregation, version hash with people/share-link, share-URL map), 3 core_shared tests (`test_external_reference_repository.py`: reverse lookup), 8 processor tests (`test_immich_album_outbox_processor.py`: resolve/skip-unresolved/add-only/remove/preserve-manual + shared_link reference_data), 6 album-cover proxy tests (`test_album_cover_proxy_service.py`)
- **Integration:** Album with tagged people → participants created on journal. Re-sync with removed tag → participant removed. Cover photo proxy returns image bytes. ✅ 6 processor integration tests (`test_immich_album_outbox_processor.py`: create participants, remove-on-resync, add-only-when-locally-edited, preserve-manual, unresolved skipped, shared_link persisted) + 3 album-cover route tests (`test_album_cover_route.py`)
- **E2E:** PHOTO_ALBUM journal shows album cover banner and participant list. ✅ Covered at the component level per the repo's "component-only e2e → Jest" convention (banner render / clickable Immich link / no-cover / on-error fallback in `JournalTypeSection.test.tsx` + `JournalTypeDataDisplay.test.tsx`; participant list via `JournalContactBadge` tests). A fully-stubbed Playwright spec was intentionally not added (mirrors the `contact-avatars.spec.ts` → `ContactAvatar.test.tsx` migration).

---

### ITER11-005: External Links and Logbook Export

**Objective:** Surface Immich external links on journals and contacts, ensure MCP parity, and enhance the logbook PDF export with album shared links.

**Specification Reference:**
- [Part 4: Integration Links](../product-specifications/immich-integration-product-specification.md#part-4-integration-links-external-system-links)
- [Part 6: Logbook Export Enhancement](../product-specifications/immich-integration-product-specification.md#part-6-logbook-export-enhancement)

**Acceptance Criteria (task-level):**
- [x] External links displayed for Immich-linked journals and contacts. *(Phase 1)*
- [x] MCP responses include Immich external links and support search filters. *(Phase 1)*
- [x] Logbook PDF export includes album shared links. *(Phase 2)*

#### Phase 1: External Links and MCP
**PR Size:** ~5–7 files

Extend external link helpers and MCP tools for Immich.

**Architecture note (as implemented):** Three Immich link sources are surfaced through the existing external-link plumbing: `immich` (contact → person, URL `{server_url}/people/{person_id}`), `immich_album` (journal → album, URL `{server_url}/albums/{album_id}`), and `immich_shared` (the full public `shared_link_url` from the album `external_references.reference_data`). The shared helpers in `external_link_helpers.py` gained `build_immich_person_url`/`build_immich_album_url` plus new `immich_album_links`/`immich_server_url` (journals) and `immich_server_url` (contacts) params; the URL is built from the server URL rather than re-using the stored `album_url` so people and album links share one construction path. The user's Immich server URL is read via a new read-only `ImmichTokenService.get_server_url` (no API-key decryption, so link display never fails on a decrypt error) — used by the REST controllers directly and by the MCP tools via a new `get_immich_token_service` MCP dependency resolver, so the lookup has a single implementation. The album id + shared link come from `SqlJournalRepository.get_immich_album_links`, which delegates to `AlbumSyncReadRepository.find_external_links` (the repo that already owns all album `external_references` SQL and the `_decode_reference_data` JSON decoder); `shared_link_url` is coerced to `str | None` so a malformed/non-string value can never reach `.strip()`. REST controllers (`get_journal_external_links`, `get_contact_external_links`) and the MCP tools (`_fetch_journal_external_links`, `get_contact`) all feed the same helpers. `search_journals` adds `immich_album` to `_VALID_INTEGRATION_SOURCES` and a `_fetch_journal_ids_by_integration_source` branch that scopes by `sync_metadata.internal_id` joined to `journals.user_id` (Immich albums key on the integer `internal_id`, not the UUID column Snipe-IT uses). The frontend `ExternalLinksDisplay` is unchanged (it renders any source); only `external-links.ts` gained icons/labels (`Immich Photo`/`Immich Album`/`Immich Shared Link`). E2E follows the repo's Immich convention (real page nav + `page.route` stub of the `external-links` endpoint, since Immich link data is sync-derived and not seedable via `TestDataManager`).

**Acceptance Criteria:**
- [x] `build_journal_external_links` and `build_contact_external_links` in `external_link_helpers.py` extended for Immich sources
- [x] URL construction: People → `{server_url}/people/{person_id}`, Albums → `{server_url}/albums/{album_id}`
- [x] Journal detail page: Immich album link displayed alongside other external links
- [x] Contact detail page: Immich person link displayed
- [x] If public shared link exists: displayed as additional link with source `"immich_shared"`
- [x] MCP: `get_journal` and `get_contact` responses include Immich external links via `ExternalLinkSchema`
- [x] MCP: `search_journals` supports `integration_source=immich_album` filter

**Required Test Coverage:**
- **Unit:** URL construction for Immich people and albums, external link helper extension, MCP schema updates. ✅ 17 helper tests (`test_external_link_helpers.py`: person/album URL builders + journal album/shared + contact person links) + 3 MCP tests (`test_external_links_mcp.py`: `immich_album` filter parse, error-message advertises it, converter surfaces album/shared links) + 6 frontend unit tests (`external-links.test.ts`: immich/immich_album/immich_shared icon+label)
- **Integration:** API returns correct external links for Immich-linked journals and contacts, MCP search filters work. ✅ 3 REST tests (`test_external_links_endpoints.py`: journal album+shared, journal album-only, contact person) + 3 MCP tests (`test_journal_external_links_mcp.py`: `get_journal` album+shared, `search_journals` immich_album filter; `test_contact_tools_integration.py`: `get_contact` immich person link)
- **E2E:** PHOTO_ALBUM journal shows Immich album link. Immich-linked contact shows person link. ✅ 2 Playwright specs (`journal-detail.spec.ts`: album+shared links render with href/target/rel/aria-label; `contacts.spec.ts`: person link renders) + 3 component tests (`ExternalLinksDisplay.test.tsx`: album/shared/person link render with accessible labels)

#### Phase 2: Logbook Export Enhancement
**PR Size:** ~3–5 files

Add album shared links to the logbook PDF export.

**Architecture note (as implemented):** `LogbookEntryData` (the `@dataclass` in `core_shared/.../journals/logbook_export.py`) gained a singular `album_shared_link: str | None = None` field. `SqlLogbookExportRepository.get_logbook_entries` populates it with **one batched query** over all `final_journal_ids` (the method is batched throughout; a per-journal `AlbumSyncReadRepository.find_external_links` call would have been the only N+1). The query mirrors `AlbumSyncReadRepository`'s SQL/constants (`INTEGRATION_SOURCE`/`EXTERNAL_SYSTEM`/`EXTERNAL_ENTITY_TYPE`/`INTERNAL_ENTITY_TYPE`) and **reuses its malformed-tolerant `_decode_reference_data` static decoder**, so a corrupt `reference_data` row can never 500 the export. Rows are `ORDER BY er.id` and the first non-empty `shared_link_url` per journal wins (collapsing the multi-album case into the singular field). `LogbookPdfRenderer._render_entry` renders the link with the existing `small_style` immediately after the participants line and before the inter-entry `Spacer`, as `📷 Photo Album: <a href="{url}">{url}</a>` with the URL `_safe_str`-escaped (XML-safe) in both the `href` and the visible text; the line is omitted entirely when the field is `None`. The 📷 emoji has no Helvetica glyph (renders as a missing-glyph box) but the PDF text layer keeps `Photo Album: {url}`, so tests assert on the ASCII substrings only. Backend-only change — no UI/frontend or MCP changes (the album shared link is already exposed via the Phase 1 `immich_shared` external link).

**Acceptance Criteria:**
- [x] `LogbookEntryData` extended with `album_shared_link: str | None` field
- [x] `LogbookExportRepository` populates `album_shared_link` from `ExternalReference.reference_data` for PHOTO_ALBUM journals
- [x] `LogbookPdfRenderer._render_entry` renders shared link as clickable hyperlink: `📷 Photo Album: {url}`
- [x] Link positioned after the contacts/participants line in entry layout

**Required Test Coverage:**
- **Unit:** PDF renderer includes album link when present, omits when absent. ✅ 2 renderer tests (`test_logbook_pdf_renderer.py`: `test_photo_album_link_rendered_when_present` asserts `Photo Album:` + URL in extracted PDF text; `test_photo_album_link_absent_when_none` asserts the line is omitted)
- **Integration:** Logbook export with PHOTO_ALBUM journal includes shared link in PDF text. ✅ 2 repository tests (`test_logbook_export_repository.py`: `album_shared_link` populated from a seeded `sync_metadata`+`external_references` link; `None` when `reference_data` has no `shared_link_url`) + 1 full-pipeline test (`test_logbook_pdf_renderer_integration.py`: repo→data service→renderer renders the URL into the PDF) + 1 API test (`test_logbook_export_api.py`: `POST /api/journals/export/outdoor-logbook` returns a PDF whose text contains the shared link — end-to-end over HTTP)
- **E2E:** ✅ Covered by the API integration test above (renders a real PDF over HTTP and asserts the shared-link URL). The existing `frontend/tests/e2e/logbook-export.spec.ts` (PDF download regression) re-runs unchanged. No new Playwright content assertion was added because the album/shared-link data is Immich-sync-derived (not seedable via `TestDataManager`) and PDF internals aren't assertable in Playwright — mirroring the Phase 1 sync-derived convention. No new UI is introduced, so there is no new accessibility surface.

---

### ITER11-006: Album Creation from Journal Date Range

**Objective:** Enable on-demand Immich album creation from a journal's date range with photo selection and optional public sharing links. **Implement last.**

**Specification Reference:**
- [Part 5: Album Creation from Journal Date Range](../product-specifications/immich-integration-product-specification.md#part-5-album-creation-from-journal-date-range)

**Acceptance Criteria (task-level):**
- [x] Users can create Immich albums from journal date ranges. *(backend + MCP — Phase 1; journal-edit UI — Phase 2)*
- [x] Photo selection dialog with deselection. *(Phase 2)*
- [x] Optional public shared link creation. *(Phase 1)*
- [x] MCP parity for album creation. *(Phase 1)*

#### Phase 1: Backend — Date Range Photo Search and Album Creation
**PR Size:** ~6–8 files

Implement the backend APIs for searching photos by date range and creating albums.

**Architecture note (as implemented):** The Immich-domain backend code now lives in an `app/core/integrations/immich/` package (the album-import processor, avatar/album-cover/asset-thumbnail proxies, and the album-creation service), with the Immich HTTP client in an `immich/adapters/` subpackage (`adapters/album_api_client.py`). Album *creation* is a synchronous, user-initiated flow (search → pick → confirm), so — unlike album *import*'s worker→outbox→backend path — the backend talks to Immich directly via `ImmichAlbumApiClient` (httpx, SSRF scheme check, `x-api-key`), mirroring the existing avatar/album-cover proxies (the backend cannot import the isolated worker package). Any upstream contract break — a non-JSON body (e.g. an HTML error page from a reverse proxy), a non-dict payload, or an album-creation response missing its `id` — is mapped to `ImmichAlbumApiError` → **502**, never a 500. A new `ImmichAlbumCreationService` orchestrates both endpoints: it loads + ownership-checks the journal (`SqlJournalRepository.find_by_id`), reads the user's timezone (`SqlUserSettingsRepository.get_timezone`), and expands the journal's UTC `event_date_range` to full local-day boundaries back into UTC via a pure `compute_search_window` helper (the reverse of the worker's date-range derivation, so a 15 Jan Sydney journal captures photos taken late on 14 Jan UTC). Photo search returns each asset's id, original filename and capture time plus a **backend proxy** `thumbnail_url` (`GET /api/integrations/immich/assets/{id}/thumbnail`, served by a new `AssetThumbnailProxyService` cloned from the album-cover proxy) so the browser never sees the Immich URL/API key. Album creation **reuses the album-import persistence** — `SyncMetadataRepository.upsert` (`integration_source="immich_album"`) + `AlbumSyncReadRepository.upsert_link` (the same `reference_data` shape: `album_id`/`album_name`/`asset_count`/`album_url`/`thumbnail_asset_id`/`shared_link_url`) — so a created album is indistinguishable from an imported one, and because PHOTO_ALBUM type is derived from that `sync_metadata` row, **writing it is what adds the PHOTO_ALBUM type** (no separate type write). The album `version_hash` is computed by a **shared** `core_shared.immich_album_hash.compute_album_version_hash` helper that the worker's `calculate_album_version_hash` now also delegates to, so the worker and backend produce identical hashes for the same album state (no shifted-field divergence; a later worker sync reconciles cleanly). Creation is rejected with **400** when the selection is empty (`asset_ids` `min_length=1` on the request schema *and* a service-level `EmptyAlbumSelectionError` guard so the MCP path is covered too — checked before any Immich call), **409** when the journal already has a linked album (`find_external_links` non-empty — guarded by a `SELECT … FOR UPDATE` lock on the journal row so two concurrent create requests serialise rather than both creating an album), **404** when the journal is missing/not owned, **400** when Immich is not connected, and **502** on an upstream Immich error. The shared-link public URL is built as `{server_url}/share/{key}` (matching the worker's `build_album_share_urls`). The MCP `create_immich_album_for_journal` tool searches first then includes all matching assets minus `exclude_asset_ids` (the deselection inverse), so MCP needs no photo-grid UI; excluding every candidate yields an empty selection and is rejected without creating an album. New REST routes hang off the existing `immich_auth_controller` router; new Dishka providers (`ImmichAlbumApiClient` APP-scope, `AssetThumbnailProxyService` + `ImmichAlbumCreationService` REQUEST-scope) and a `get_immich_album_creation_service` MCP resolver wire it up.

**Acceptance Criteria:**
- [x] `POST /api/integrations/immich/search-photos` — queries Immich `POST /search/metadata` with `takenAfter`/`takenBefore` from journal's `event_date_range` (with timezone-aware day boundary expansion)
- [x] Returns photo thumbnails and metadata for UI display *(asset id + original filename + capture time + backend-proxied `thumbnail_url`)*
- [x] `POST /api/integrations/immich/create-album` — accepts journal ID, selected asset IDs, and `create_shared_link` boolean
- [x] Creates album in Immich via `POST /albums` with `albumName` = journal title
- [x] If `create_shared_link=true`: creates shared link via `POST /shared-links`, stores URL in `ExternalReference.reference_data`
- [x] Creates `SyncMetadata` and `ExternalReference` records linking journal to new album
- [x] Adds `PHOTO_ALBUM` type to journal's type list *(derived from the `immich_album` `SyncMetadata` row)*
- [x] MCP tools: `search_immich_photos_for_journal(journal_id)`, `create_immich_album_for_journal(journal_id, create_shared_link, exclude_asset_ids)`

**Required Test Coverage:**
- **Unit:** Timezone day boundary expansion, album creation request construction, shared link storage, shared version-hash. ✅ 5 timezone tests (`test_immich_album_creation_timezone.py`: +offset spec example / −offset / multi-day / naive-UTC / unknown-tz fallback) + 12 service tests (`test_immich_album_creation_service.py`: search mapping + window, not-found/not-owned/not-connected guards, create writes SyncMetadata+ExternalReference, shared-link URL, already-linked skip, empty-selection skip, album-name=title) + 9 API-client tests (`test_immich_album_api_client.py`: search `takenAfter`/`takenBefore` + unwrap, create-album/shared-link payloads, SSRF reject, 401/404/500 + connection error + non-JSON body + non-dict + missing-id contract breaks) + 4 proxy tests (`test_asset_thumbnail_proxy_service.py`) + 5 shared-hash tests in core_shared (`test_immich_album_hash.py`: known layout, person-id order independence, name/desc strip, per-field change, backend↔worker layout parity)
- **Integration:** Search photos returns results from mocked Immich. Create album → SyncMetadata + ExternalReference + PHOTO_ALBUM type added. ✅ 9 REST tests (`test_immich_album_creation_api.py`: search returns proxy thumbnail URLs, search 404 not-owned, search 400 not-connected, create links journal + writes SyncMetadata/ExternalReference + `get_types()` includes PHOTO_ALBUM, create with shared link persisted, create 409 already-linked, create 400 empty selection, create 502 on malformed Immich response, asset-thumbnail proxy returns bytes) + 3 MCP tests (`test_immich_album_creation_mcp.py`: search tool, create tool honours `exclude_asset_ids` + marks PHOTO_ALBUM, exclude-all creates nothing)
- **E2E:** The browser flow (open journal → Create Album → deselect → confirm → banner) is delivered in **Phase 2** (the spec lists E2E only under Phase 2). Phase 1 is backend-only; per the repo's ITER11-005 convention (Immich sync-derived data is not seedable via `TestDataManager`), the Phase-1 end-to-end guarantee is the full-HTTP integration test above (real app + DB, Immich stubbed via respx).

#### Phase 2: Frontend — Photo Selection Dialog and Create Album Button
**PR Size:** ~5–7 files

Build the UI for browsing photos and creating albums from journal edit screens.

**Architecture note (as implemented):** Phase 2 is **pure frontend** — no backend, schema, or MCP changes; it wires the journal edit screen (`JournalDetailView`, which is the inline-edit surface) to the Phase 1 search/create endpoints. Three new components plus one API module: `frontend/src/lib/api/immich-albums.ts` exposes `searchImmichPhotos`/`createImmichAlbum` (mapping the caller's camelCase to the backend's snake_case body and flattening the JSON:API search response to a flat `ImmichPhoto[]`) and two React-Query mutation hooks — `useImmichPhotoSearch` (search is modelled as an **on-demand mutation** so the button gets its own loading state and the dialog opens with the result) and `useCreateImmichAlbum` (on success invalidates `journalKeys.detail(id)` **and** `externalLinkKeys.journal(id)` so the album banner + external links refresh without a reload). `CreateAlbumButton` owns the **visibility logic** — it renders only when Immich is `connected` (via the existing `useIntegrations()` hook), the journal has an `event_date_range.start`, and the journal does **not** already include the `PHOTO_ALBUM` type (the already-linked guard) — and on click fires the search then opens `CreateAlbumDialog` (if the search returns no photos it shows an informational toast instead of an empty dialog — honouring spec trigger condition #4 without an expensive per-render existence pre-check on every journal load); visibility requires a **complete** `event_date_range` (both `start` and `end`) so a half-open range can't surface a button that the backend search would reject. `CreateAlbumDialog` holds the **selection state** as a `Set<string>` seeded with **all** photo ids (deselect-not-select UX), renders the thumbnail grid as **selectable cards** — each whole tile is a single `role="checkbox"` control (so clicking anywhere on the thumbnail toggles it; the Radix `Checkbox` is a visual-only `aria-hidden` indicator, avoiding the native-`<label>`-can't-toggle-a-Radix-button trap) with `aria-label` = filename — inside a `ScrollArea`, offers the "Create public shared link" checkbox, disables confirm when the selection is empty, and closes on success. The banner + links display is **reused unchanged** (`AlbumCoverBanner` / `PhotoAlbumDataDisplay` via `JournalTypeSection`, and `ExternalLinksDisplay`). The thumbnails consume the Phase 1 backend proxy URLs so the browser never sees the Immich URL/key. For E2E, Immich data is sync-derived and not seedable via `TestDataManager`, so the journal is seeded for real and the Immich-backed endpoints (`/api/integrations`, search-photos, create-album, the thumbnail + album-cover proxies) plus the post-create journal/external-links responses are stubbed with `page.route` — the same convention as `immich-conflicts.spec.ts` / the ITER11-005 `journal-detail.spec.ts` PHOTO_ALBUM test; the create-album route flips a flag so the journal-detail stub injects the `PHOTO_ALBUM` type into the *real* backend response only after creation, exercising the genuine refresh path.

**Acceptance Criteria:**
- [x] "Create Album" button visible on journal edit screen when: Immich connected, `event_date_range` set, no existing linked album
- [x] Button triggers photo search; loading state while fetching
- [x] Photo selection dialog: grid of photo thumbnails with checkboxes (all selected by default)
- [x] User can deselect individual photos
- [x] Checkbox option: "Create public shared link"
- [x] On confirm: calls create-album API, shows success state, journal refreshes to show album banner and external link
- [x] Button hidden when journal already has a linked album

**Required Test Coverage:**
- **Unit:** Create Album button visibility logic, photo selection state management. ✅ 9 button tests (`CreateAlbumButton.test.tsx`: renders when connected+date-range+no-album; hidden when disconnected / no date range / **incomplete range missing `end`** / already-linked; click triggers search; loading state disables + `aria-busy`; opens the dialog when the search returns photos; shows a toast instead of an empty dialog when no photos match — honouring spec trigger condition #4 without an expensive per-render pre-check) + 7 dialog tests (`CreateAlbumDialog.test.tsx`: all-selected-by-default, deselect toggles a photo + updates count, **clicking the whole thumbnail tile toggles it**, confirm sends only selected `assetIds`, shared-link choice passed through, confirm disabled when none selected) + 5 API-client tests (`immich-albums.test.ts`: search POSTs `journal_id` + flattens response, create maps camelCase→snake_case body, both surface `errors[0].detail`, **a non-numeric journal id throws before any network call**)
- **Integration:** Full button→search→dialog→deselect→confirm wiring with real hooks and only the HTTP boundary mocked. ✅ 1 flow test (`CreateAlbumFlow.integration.test.tsx`: button appears once integrations resolve connected, search opens the dialog with both photos checked, deselecting one then confirming POSTs create-album with the reduced `asset_ids` + `create_shared_link`, and the journal-detail + external-links query caches are invalidated). The real backend search/create endpoints are covered by the Phase 1 REST integration tests above.
- **E2E:** Open journal without album, click Create Album, deselect a photo, confirm creation, verify album banner appears. ✅ 1 Playwright spec (`journal-album-create.spec.ts`, Chromium): seeds a real dated journal, stubs the Immich endpoints, then opens the journal → asserts the button is visible + accessibly named → clicks it → asserts the dialog (accessible name) shows both photos checked by default and checkboxes are labelled → deselects one → ticks "Create public shared link" → confirms → asserts the create-album request succeeds, the dialog closes, the `immich_album` + `immich_shared` external links render, and (after expanding the PHOTO_ALBUM section) the album cover banner is visible.

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
