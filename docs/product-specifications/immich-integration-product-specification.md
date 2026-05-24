# Immich Integration Product Specification

## Overview

This document defines the target product behaviour for the Immich photo management integration. It is a product specification rather than a technical design.

The Immich integration connects the personal management system with a self-hosted Immich instance to provide:
- Two-way contact synchronisation with Immich's "People" feature
- Album import as PHOTO_ALBUM journals with participant detection
- Contact avatar support using Immich feature photos
- On-demand album creation from journal date ranges

This specification supersedes `docs/tasks/iteration-6-immich-integration.md`. Where that earlier document conflicts with this specification, this specification takes precedence.

## Reference and Alignment

This specification evolves and refines behaviour described in:

- `docs/architecture/integration-architecture.md`
- `docs/tasks/iteration-6-immich-integration.md`
- `docs/product-specifications/contacts-product-specification.md`
- `docs/product-specifications/integration-architecture-and-strava-product-specification.md`
- `docs/product-specifications/journals-product-specification.md`

Where earlier documents assume narrower integration behaviour, this specification should be treated as the product-level refinement.

## Product Goals

1. Establish two-way contact synchronisation between the personal management system and Immich People, with the **personal management system as the source of truth**.
2. Import Immich albums as PHOTO_ALBUM journal entries, deriving date ranges from photo timestamps and participants from people tags.
3. Introduce contact avatar support as a new capability, powered by Immich feature photos.
4. Enable on-demand album creation in Immich from a journal's date range with optional public sharing links.
5. Integrate seamlessly into the existing pluggable integrations dashboard alongside Google, Strava, and Snipe-IT.
6. Provide full MCP parity for all Immich features.

## Product Principles

1. **Personal management system is the source of truth**: For contacts, local data wins in conflicts. Immich data enriches but does not override local edits.
2. **Standard integration patterns**: Use the existing Redis Streams event bus, outbox pattern, sync metadata, and external references. Reuse existing infrastructure wherever possible.
3. **Pluggable integration UI**: Follow the generic integrations dashboard pattern.
4. **AI-first**: All Immich-linked data is available through MCP tools.

---

## Part 1: Authentication & Configuration

Immich uses API key authentication, similar to the Snipe-IT integration.

### Connection Setup

1. **Base URL Configuration**: The user provides their Immich instance's Base URL in the integrations dashboard.
2. **API Key Authentication**: The user generates an API key in Immich's web interface (Account Settings → API Keys) and enters it in the integrations dashboard.
3. **Credential Storage**: The API key is stored encrypted in the database using the existing `EncryptionService`, in a `user_immich_auth` table (per-user).
4. **Validation**: On save, the system validates the API key by calling the Immich server info endpoint. If validation fails, the key is not stored.

### Configuration Fields

- `immich_server_url` — The base URL of the Immich instance (e.g. `https://photos.example.com`)
- `api_key` — Encrypted Immich API key
- `created_at`, `updated_at` — Audit timestamps

The existing `immich_base_url` and `immich_api_key` fields in `backend/app/infrastructure/config.py` should be removed in favour of per-user database storage.

---

## Part 2: Contact Sync (People) — Two-Way

Immich "People" map to the system's contacts. This is a two-way synchronisation with the personal management system as the source of truth.

### Sync Rules

- **Two-Way Sync**: Changes in either system are synchronised to the other.
- **Source of Truth**: The personal management system. When conflicts occur (both sides changed between syncs), local values win.
- **Field Mapping**:

| Immich Person Field | Contact Field | Sync Direction |
|---|---|---|
| `name` | `first_name` + `last_name` | Bidirectional |
| `birthDate` | `ImportantDate` (type=BIRTHDAY, precision=FULL) | Bidirectional |
| Feature photo thumbnail | `photo_url` (new field) | Immich → Local only |

- **Name Parsing**: Immich stores a single `name` string. The system splits on the last space: everything before is `first_name`, the last token is `last_name`. When pushing to Immich, `first_name` and `last_name` are concatenated with a space.

### Contact Matching on Import

When syncing a new Immich person inbound, the system must attempt to match them to an existing local contact before creating a new one. Matching uses name-based comparison:

1. **Exact match**: `"{first_name} {last_name}"` matches `person.name` (case-insensitive)
2. **Middle initial variants**: Match with or without middle initials (e.g. "John A Smith" matches "John Smith")
3. **Abbreviated last name**: Match where the Immich name uses only the first letter of the last name (e.g. "John S" matches "John Smith")

#### Conflict Resolution

If multiple local contacts match the same Immich person name:

- The system flags a **sync conflict** and does not auto-assign
- The conflict is surfaced in:
  - **Integrations dashboard**: A conflict resolution dialogue listing the ambiguous Immich person and candidate local contacts, allowing the user to pick the correct match or create a new contact
  - **MCP**: A tool to list unresolved conflicts and resolve them by mapping an Immich person ID to a contact ID
- Once resolved, the mapping is stored in `ExternalReference` and used for all future syncs

### Birthday Sync Rules

- **Inbound (Immich → Local)**: If an Immich person has a `birthDate` and the local contact has no birthday `ImportantDate`, create one with `precision=FULL`. If the local contact already has a birthday, do not overwrite (source of truth is local).
- **Outbound (Local → Immich)**: If a local contact has a birthday `ImportantDate` with `precision=FULL`, sync it to Immich's `birthDate`. If the precision is `DAY_MONTH` or `YEAR` only, do **not** sync to Immich (Immich requires full dates). Ensure that a re-sync does not clear a birthday in Immich when the local contact has a non-full-precision date — the system should simply skip that field.

### Contact Avatar (Feature Photo) — New Capability

This is a new feature for the contacts system. Immich People have a "feature photo" (the thumbnail used to represent a person). This photo should be used as the contact's avatar image.

#### Implementation

- **New field**: Add `photo_url` to the `Contact` entity and `contacts` table.
- **Backend proxy**: The backend provides a proxy endpoint that fetches the person thumbnail from Immich's `GET /people/{id}/thumbnail` API. This ensures the frontend works even if the Immich instance is not directly reachable from the browser. The proxy URL is stored as the contact's `photo_url`.
- **Frontend**: The existing `ContactAvatar` component already supports an `imageUrl` prop. Wire this to the new `photo_url` field.
- **Sync**: The `photo_url` is updated on each contact sync from Immich. It is not synced back to Immich (the feature photo is managed in Immich's UI).
- **Fallback**: When no photo URL is available, the existing initials fallback in `ContactAvatar` continues to work.

### Sync Mechanisms

- **Periodic sync**: A scheduled ARQ task runs on a configurable interval (default: every 6 hours) to sync all people.
- **Manual sync**: The user can trigger a full sync from the integrations dashboard.
- **No webhooks**: Immich does not support webhook push subscriptions. Periodic sync is the primary mechanism.

### Sync Metadata

People sync state is tracked using the existing `SyncMetadata` model:
- `integration_source` = `"immich"`
- `internal_id` = contact ID
- `external_id` = Immich person UUID
- `version_hash` = hash of the Immich person's name + birthDate for change detection

Contact-to-Immich-person mapping is tracked via `ExternalReference`:
- `internal_entity_type` = `"contact"`
- `internal_entity_id` = contact ID
- `external_system` = `"immich"`
- `external_entity_type` = `"person"`
- `external_entity_id` = Immich person UUID

---

## Part 3: Album Sync (Journals) — Two-Way

Immich albums are imported as journals with the `PHOTO_ALBUM` type. This is a two-way sync with field-level merge protection.

### Album-to-Journal Mapping

| Immich Album Field | Journal Field | Notes |
|---|---|---|
| `albumName` | `title` | Bidirectional with merge protection |
| Photo date range (min/max `takenAt`) | `event_date_range` | Protected after local edit |
| `description` | `content` | Bidirectional with merge protection |
| People tagged in photos | Journal participants | Detected from album photo people tags |
| Shared link URL | Stored as reference data | Included in logbook export |
| Album cover photo | Displayed as banner on journal | Fetched on-demand, not persisted |

### Date Range Derivation

The journal's `event_date_range` is derived from the photos in the album:
- `start` = earliest `takenAt` timestamp across all photos in the album
- `end` = latest `takenAt` timestamp across all photos in the album
- Timezone handling: Photo timestamps from Immich are in UTC. The system must convert them to the user's configured timezone for date range calculation to ensure correct day boundaries.

### Field Merge Protection

Following the same pattern as Google Calendar's `InboundFieldMerger`:

- **Always update from Immich**: (none — all fields are protected after local edit)
- **Protected when locally edited** (journal.updated_at > link.updated_at): `title`, `content`, `event_date_range_start`, `event_date_range_end`
- **Rationale**: Unlike Google Calendar where time fields always take inbound values, Immich date ranges cannot be synced back. If a user corrects a date range locally, a re-sync must not overwrite it.

### Participant Detection from People Tags

When an album is imported or re-synced:

1. The system fetches all assets (photos) in the album via `GET /albums/{id}`
2. For each asset, the system checks which Immich People are tagged (face detection data)
3. Each tagged Immich person is resolved to a local contact using the `ExternalReference` mapping (established during contact sync)
4. Resolved contacts are added as `PARTICIPANT` relationships on the journal via the existing `JournalContactRelationship` system
5. **Change detection**: On re-sync, the participant list is recalculated. New people are added, removed people are removed. This ensures participants stay accurate as photos are added/removed from albums or people are tagged/untagged.

If an Immich person has not been synced to a local contact yet, they are skipped for participant detection (no orphan participants).

### Album Cover Photo Display

- The album's cover photo (Immich's `albumThumbnailAssetId`) is displayed as a banner image on the journal edit/detail screen.
- The image is fetched on-demand from Immich via the backend proxy (same pattern as contact avatars). It is **not** persisted locally.
- The cover photo is clickable to open the album in Immich's web UI.

### Public Shared Link

If an album has a shared link in Immich (queryable via `GET /shared-links`):
- The shared link URL is stored as `reference_data` JSON on the `ExternalReference` record for the album
- The shared link URL is displayed on the journal detail page alongside other external links
- The shared link URL is included in the logbook PDF export (see Part 6)

### Sync Metadata

Album sync state is tracked using the existing `SyncMetadata` model:
- `integration_source` = `"immich_album"`
- `internal_id` = journal ID
- `external_id` = Immich album UUID
- `version_hash` = hash of album metadata (name, description, asset count, updatedAt)

Album-to-journal mapping is tracked via the existing `PHOTO_ALBUM` type data, but the current `journal_photo_album_data` table and `PhotoAlbumData` entity should be **refactored** to use `SyncMetadata` and `ExternalReference` consistently with other integrations, rather than maintaining a separate `immich_album_id` field. The `journal_photo_album_data` table is not currently used in production and can be cleaned up.

### Cleanup: PhotoAlbumData Entity

The existing `PhotoAlbumData` entity, `journal_photo_album_data` table, and `SqlPhotoAlbumDataRepository` are scaffolding from Iteration 4 that duplicates integration state already handled by `SyncMetadata` and `ExternalReference`. As part of this work:

- Remove the `journal_photo_album_data` table (migration)
- Remove the `PhotoAlbumData` entity from `core_shared`
- Remove `SqlPhotoAlbumDataRepository`
- The `PHOTO_ALBUM` journal type remains as a type enum value
- Album-to-journal linking uses `SyncMetadata` (integration_source = `"immich_album"`) and `ExternalReference` instead

---

## Part 4: Integration Links (External System Links)

### Contacts

Immich-linked contacts display an external link on the contact detail page:
- **Source**: `"immich"`
- **URL**: `{immich_server_url}/people/{person_id}`
- **Data source**: `ExternalReference` records where `external_system = "immich"` and `external_entity_type = "person"`

This follows the same pattern as Google Contacts and Strava external links on contacts.

### Journals

Immich-linked journals (PHOTO_ALBUM type) display an external link on the journal detail page:
- **Source**: `"immich_album"`
- **URL**: `{immich_server_url}/albums/{album_id}`
- **Data source**: `SyncMetadata` records where `integration_source = "immich_album"`

If a public shared link exists, it is displayed as an additional link with source `"immich_shared"`.

### URL Construction

- **Immich People**: `{immich_server_url}/people/{person_id}`
- **Immich Albums**: `{immich_server_url}/albums/{album_id}`
- **Immich Shared Link**: The full shared link URL from Immich's `SharedLinkResponseDto`

The `build_journal_external_links` and `build_contact_external_links` helper functions in `external_link_helpers.py` must be extended to handle Immich sources.

### MCP Parity

External system links for Immich must be included in MCP responses for both contacts and journals, following the existing `ExternalLinkSchema` pattern.

---

## Part 5: Album Creation from Journal Date Range

This feature allows the user to create a new Immich album populated with photos from the journal's time range. **This should be the last feature implemented.**

### Trigger Conditions

A "Create Album" button is available on the journal edit screen when:
1. The Immich integration is connected
2. The journal has an `event_date_range` set
3. The journal does not already have a linked Immich album
4. There are photos in Immich for the journal's date range (checked via `POST /search/metadata` with `takenAfter` and `takenBefore` parameters)

### Timezone Handling

The journal's `event_date_range` stores UTC timestamps. When querying Immich for matching photos:
- Convert the journal's start/end to the user's configured timezone
- Expand to full day boundaries in the user's timezone (start of first day, end of last day)
- Convert back to UTC for the Immich API query
- This ensures that a journal for "15 January" in AEST (+11:00) correctly captures photos taken at 23:00 UTC on 14 January

### User Flow

1. User clicks "Create Album" on the journal edit screen
2. The system queries Immich for photos in the date range (with timezone adjustment)
3. A dialog displays the matching photos with checkboxes (all selected by default)
4. The user can deselect photos they don't want in the album
5. The user chooses whether to create a public shared link for the album
6. On confirm:
   a. Create the album in Immich via `POST /albums` with `albumName` set to the journal title and the selected `assetIds`
   b. If public link requested, create a shared link via `POST /shared-links` with `type = "ALBUM"` and the new `albumId`
   c. Create `SyncMetadata` and `ExternalReference` records linking the journal to the new album
   d. Add the `PHOTO_ALBUM` type to the journal's type list
   e. If a shared link was created, store the URL in the external reference's `reference_data`

### MCP Parity

Album creation must also be available via MCP:
- A tool to check if photos exist in Immich for a given date range
- A tool to create an album from a journal, with an option to create a public link
- The MCP tool should not require photo deselection (it includes all matching photos by default, but accepts an optional exclusion list)

---

## Part 6: Logbook Export Enhancement

### Album Link in PDF Export

When a journal entry in the logbook export has a linked Immich album with a public shared link:
- The shared link URL is rendered in the PDF entry as a clickable hyperlink
- Format: `📷 Photo Album: {shared_link_url}`
- Positioned after the contacts/participants line in the entry layout

This requires:
- Adding an `album_shared_link` field to `LogbookEntryData`
- Populating it from `ExternalReference.reference_data` during logbook data assembly
- Rendering it in `LogbookPdfRenderer._render_entry`

---

## Part 7: UI & Dashboard Integration

### Generic Integrations Dashboard

Immich is added to the generic integrations dashboard API (`GET /api/integrations`).

- **ID**: `immich`
- **Capabilities**: `contacts_sync`, `album_sync`, `album_create`
- **Settings**: Server URL, API Key (masked input)
- **Status indicators**: Connected, disconnected, sync in progress, conflict pending

### Conflict Resolution UI

A dedicated section on the Immich integration panel (or a modal) shows:
- Unresolved contact sync conflicts
- For each conflict: the Immich person's name and thumbnail, and a list of candidate local contacts
- Action buttons: "Link to this contact" or "Create new contact"

### Journal Edit Screen Enhancements

For journals with a linked Immich album:
- **Banner image**: Album cover photo displayed as a header banner
- **Album info**: Album name and photo count
- **External link**: Link to open the album in Immich
- **Shared link**: If present, displayed and copyable

For journals without a linked album but with a valid date range:
- **Create Album button**: Triggers the album creation flow (Part 5)

---

## Part 8: Immich ARQ Worker

The Immich integration worker follows the isolated worker architecture pattern used by Google, Strava, and Snipe-IT workers.

### Worker Structure

```
integration_workers/immich/
├── .env.example
├── Dockerfile
├── pyproject.toml
├── immich_api_client.py      # Immich REST API client
├── immich_auth_service.py    # API key management
├── immich_models.py          # Pydantic models for Immich API responses
├── immich_settings.py        # Worker configuration
├── immich_sync_service.py    # Sync logic (people + albums)
├── immich_data_transformer.py # Data transformation
├── stream_consumer_tasks.py  # Redis Streams consumer for outbound events
├── worker.py                 # ARQ worker entry point
└── tests/
```

### Sync Tasks

- `sync_immich_people(ctx, user_id)` — Full people sync (two-way)
- `sync_immich_albums(ctx, user_id)` — Full album sync (inbound + update detection)
- `periodic_sync_all_immich_accounts(ctx)` — Periodic sync for all connected users

### Stream Consumer

The Immich worker registers a Redis Streams consumer group (`immich-worker`) that listens for:
- `contact.created`, `contact.updated` — For outbound contact sync to Immich
- `contact.birthday_changed` — For birthday sync to Immich
- `journal.updated` — For detecting changes to PHOTO_ALBUM journals that need outbound sync

### Immich API Client Methods

Based on the Immich API (`https://api.immich.app`):

| Method | Immich Endpoint | Purpose |
|---|---|---|
| `get_server_info()` | `GET /server/about` | Validate API key |
| `get_all_people()` | `GET /people` | List all people |
| `get_person(id)` | `GET /people/{id}` | Get person details |
| `update_person(id, data)` | `PUT /people/{id}` | Update name/birthDate |
| `get_person_thumbnail(id)` | `GET /people/{id}/thumbnail` | Get feature photo |
| `get_all_albums()` | `GET /albums` | List all albums |
| `get_album(id)` | `GET /albums/{id}` | Get album with assets |
| `create_album(data)` | `POST /albums` | Create new album |
| `search_assets(filters)` | `POST /search/metadata` | Search photos by date range |
| `get_asset_thumbnail(id)` | `GET /assets/{id}/thumbnail` | Get photo thumbnail |
| `get_shared_links()` | `GET /shared-links` | List shared links |
| `create_shared_link(data)` | `POST /shared-links` | Create album shared link |

---

## Part 9: Commonalities with Existing Integrations

### Opportunities for Deduplication

The following patterns are repeated across Google, Strava, Snipe-IT, and now Immich workers. Where possible, shared logic should be extracted to `core_shared` or common worker utilities:

1. **API key / credential management**: Snipe-IT and Immich both use API key auth with encrypted storage. The auth service pattern (validate, store, revoke) should be standardised.

2. **Contact name matching**: The name-matching logic (exact match, middle initial variants, abbreviated last names) should be extracted from the Strava athlete matching code into a shared `ContactNameMatcher` utility in `core_shared`, as it will now be used by both Strava (athlete matching) and Immich (people matching).

3. **Sync metadata management**: All integrations use the same `SyncMetadata` and `SyncMetadataRepository` patterns. This is already shared via `core_shared`.

4. **External link URL construction**: The `external_link_helpers.py` pattern of `build_*_url` functions should be extended consistently for Immich.

5. **Integration registry provider**: Each integration has a `*IntegrationProvider` class. The pattern is consistent and can remain per-integration, but the interface should be documented.

6. **Worker lifecycle**: Dockerfile, ARQ setup, Dishka DI, health checks — these follow a consistent template across all workers.

7. **Stream consumer pattern**: Each worker has a `stream_consumer_tasks.py` with a consumer group. The event filtering and ACK patterns should be consistent.

---

## Delivery Notes

This specification defines target product behaviour. Delivery should be phased to preserve coherence and maintain a green main branch.

### Suggested Phasing

1. **Immich API client & authentication**: Implement API client, auth service, credential storage. Add Immich to the integration registry. Connect/disconnect UI.

2. **Contact sync (People)**: Implement two-way people sync with name matching, conflict detection, and birthday sync. Extract shared `ContactNameMatcher`. Add conflict resolution UI and MCP tools.

3. **Contact avatar**: Add `photo_url` field to contacts. Implement backend proxy for Immich thumbnails. Wire up `ContactAvatar` component.

4. **Album import**: Implement album sync, date range derivation, participant detection. Refactor `PhotoAlbumData` to use `SyncMetadata`/`ExternalReference`. Album cover photo display.

5. **Integration links**: Extend external link helpers for Immich. Add links to journal and contact detail pages. MCP parity.

6. **Logbook export enhancement**: Add album shared link to PDF export entries.

7. **Album creation from journal**: Implement date-range photo search, album creation flow with photo selection and shared link option. MCP tools. **(Implement last)**

Each phase should deliver working, testable functionality with full test coverage before moving to the next.

## Success Criteria

This work will be successful when:

1. Immich People sync bidirectionally with contacts, with name matching and conflict resolution
2. Contact avatars display Immich feature photos throughout the UI
3. Immich albums import as PHOTO_ALBUM journals with correct date ranges and participants
4. Album cover photos display as banners on journal edit screens
5. External system links appear on journals and contacts for Immich-linked entities
6. Users can create Immich albums from journal date ranges with optional shared links
7. The logbook PDF export includes album shared links
8. All Immich features are accessible through MCP tools
9. The integration follows the pluggable dashboard pattern and can be connected/disconnected independently
10. All tests pass (unit, integration, e2e) and the system is in a working state after each PR
