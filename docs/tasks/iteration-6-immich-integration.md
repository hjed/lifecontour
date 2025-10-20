# Iteration 6: Immich Integration

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (Journal Core with PHOTO_ALBUM type)
**Goal:** Integrate Immich photo service with album linking and photo display in journals

## Overview

This iteration implements Immich integration following the [journal system specification](../journal-system-specification.md#immich-integration) and [integration architecture](../architecture/integration-architecture.md):

**Core Features:**
- Immich API client with API key authentication
- Album and photo data synchronization
- Photo gallery display in journals (inline)
- Album linking to journal entries (PHOTO_ALBUM type)
- Photo metadata extraction for search
- ARQ worker for background sync following isolated worker architecture
- On-demand photo fetching (no local caching)

**Integration Behavior:**
- **Album Linking:** Journals can reference one Immich album via `immich_album_id`
- **Photo Display:** Photos fetched from Immich API on-demand, displayed inline in journal view
- **Sync Direction:** One-way (Immich → Journal, read-only metadata sync)
- **Future Enhancement:** Auto-create albums based on event date range (Phase 9+)

## Prerequisites

- Iteration 4 completed (PHOTO_ALBUM journal type)
- Integration architecture with ARQ workers (from Iteration 2)
- Dishka dependency injection framework
- Immich instance with API access
- Immich API key for authentication

## Tasks

### ITER6-001: Immich API Client & Authentication 🟡 PLANNED
**Description:** Implement Immich API client with API key authentication
**Strategy:** Single task for API foundation
**Specification Reference:** [Immich Integration](../journal-system-specification.md#immich-integration)

**PR Size:** ~5 files (API client, auth models, configuration, tests)

**Acceptance Criteria:**
- [ ] Create `integration_workers/immich/` package structure following isolated worker pattern
- [ ] Implement `ImmichAPIClient` using Immich REST API:
  - Get server info
  - List albums (with pagination)
  - Get album details
  - List photos in album
  - Get photo metadata
  - Get photo thumbnail URL
  - Get photo full-size URL
- [ ] Create `UserImmichAuth` model in `core_shared/models/`:
  - `id`, `user_id`, `api_key` (encrypted)
  - `immich_server_url`, `created_at`, `updated_at`
- [ ] Implement `ImmichAuthService` for credential management:
  - Store API key with encryption
  - Validate API key with Immich server
  - Revoke API key on disconnect
- [ ] Use `EncryptionService` for secure API key storage
- [ ] Add Immich configuration to worker secrets management
- [ ] Add database migration for Immich auth tables
- [ ] Write integration tests for API client connectivity and authentication
- [ ] Document Immich API integration in code comments

**API Key Management:**
- User provides Immich server URL and API key in settings
- API key stored encrypted in database
- API key validated on save
- API key used for all Immich API requests

### ITER6-002: Album & Photo Data Sync 🟡 PLANNED
**Description:** Implement album and photo metadata synchronization
**Strategy:** Single task for sync service
**Specification Reference:** [Immich Integration](../journal-system-specification.md#immich-integration)

**PR Size:** ~6 files (album/photo models, sync service, tests)

**Acceptance Criteria:**
- [ ] Define Pydantic models for Immich API responses:
  - `ImmichAlbum` (id, name, description, asset_count, created_at, updated_at)
  - `ImmichPhoto` (id, album_id, file_path, thumbnail_url, created_at, metadata)
- [ ] Create `UserImmichIntegration` model for sync state:
  - `id`, `user_id`, `last_sync_at`, `sync_status`
  - `created_at`, `updated_at`
- [ ] Implement `ImmichDataTransformer`:
  - Map Immich albums to journal metadata
  - Extract photo metadata (date, location, camera, etc.)
  - Generate thumbnail and full-size URLs
- [ ] Create `ImmichSyncService` in `integration_workers/immich/`:
  - `full_sync_albums()` - Sync all albums
  - `sync_album_photos(album_id)` - Sync photos for specific album
  - Album deduplication by `immich_album_id`
  - Photo metadata extraction for search indexing
- [ ] Add database migration for Immich integration state
- [ ] Write unit tests for data transformation and sync logic
- [ ] Write integration tests for sync service
- [ ] Document Immich data model in code comments

**Sync Strategy:**
- Sync album metadata only (not photo files)
- Photos fetched on-demand when journal viewed
- No local caching of photos (always fetch from Immich)
- Sync triggered manually or on schedule

### ITER6-003: Photo Display in Journals 🟡 PLANNED
**Description:** Implement photo gallery display in journal views
**Strategy:** Single task for photo UI
**Specification Reference:** [Display](../journal-system-specification.md#immich-integration)

**PR Size:** ~6 files (photo gallery component, album selector, tests)

**Acceptance Criteria:**
- [ ] Create `ImmichPhotoGallery` component in `frontend/src/components/journals/`:
  - Fetch photos from Immich API on-demand
  - Display thumbnails in grid layout
  - Click to view full-size image
  - Lightbox for full-size viewing
  - Photo metadata display (date, location, camera)
  - Responsive design for mobile and desktop
- [ ] Create `ImmichAlbumSelector` component:
  - List user's Immich albums
  - Search albums by name
  - Preview album (thumbnail grid)
  - Select album for journal
- [ ] Integrate photo gallery into journal detail view:
  - Display inline in journal content
  - Show album name and photo count
  - Link to Immich for full album view
- [ ] Implement lazy loading for photos (load as user scrolls)
- [ ] Add error handling for failed photo loads
- [ ] Write Jest unit tests for components
- [ ] Write React Testing Library tests for user interactions
- [ ] Document photo display patterns in code comments

**Photo Display Features:**
- Thumbnail grid with lazy loading
- Lightbox for full-size viewing
- Photo metadata overlay
- Link to Immich for full album
- Responsive grid layout

### ITER6-004: Immich ARQ Worker 🟡 PLANNED
**Description:** Implement background sync worker following isolated worker architecture
**Strategy:** Single task for ARQ worker
**Specification Reference:** [Integration Architecture](../architecture/integration-architecture.md)

**PR Size:** ~5 files (ARQ task, worker setup, monitoring, tests)

**Acceptance Criteria:**
- [ ] Create ARQ task `sync_immich_albums(ctx, user_id)` in `integration_workers/immich/worker.py`:
  - Use Dishka DI for service injection
  - Idempotent operation (safe for redelivery)
  - Sync album metadata only (not photo files)
  - Error handling with retry logic (exponential backoff)
  - Dead letter queue for failed syncs
- [ ] Implement worker lifecycle management:
  - Worker startup with Dishka container initialization
  - Graceful shutdown with resource cleanup
  - Health check endpoint
- [ ] Add worker monitoring:
  - Sync status tracking (in_progress, completed, failed)
  - Sync duration metrics
  - Album count metrics
  - Error logging with context
- [ ] Create worker Dockerfile following isolated worker pattern:
  - Separate container from main app
  - Minimal dependencies (only Immich-specific)
  - Environment variable configuration
- [ ] Add worker to docker-compose.yml
- [ ] Write integration tests for ARQ worker
- [ ] Document worker deployment in code comments

**Worker Architecture:**
- Isolated container with own dependencies
- Message-based communication via ARQ
- Idempotent operations for safe redelivery
- Metadata sync only (photos fetched on-demand)

### ITER6-005: Immich UI & Management 🟡 PLANNED
**Description:** Build integration management UI with album browser
**Strategy:** Single task for UI components
**Specification Reference:** [Integration Architecture](../architecture/integration-architecture.md)

**PR Size:** ~6 files (UI components, integration page, album browser, tests)

**Acceptance Criteria:**
- [ ] Create `ImmichIntegration` component in `frontend/src/components/integrations/`:
  - Connect/disconnect Immich button
  - Server URL and API key input
  - Connection status display
  - Manual sync trigger button
  - Sync history with timestamps
- [ ] Create `ImmichSyncStatus` component:
  - Real-time sync progress (if in progress)
  - Sync statistics (albums synced, photos counted)
  - Error display with retry option
- [ ] Create `ImmichAlbumBrowser` component:
  - List all user's albums
  - Search albums by name
  - Filter albums by date
  - Preview album (thumbnail grid)
  - Link album to journal
- [ ] Add Immich integration to settings page
- [ ] Implement real-time sync status updates (polling or WebSocket)
- [ ] Add album import history view
- [ ] Write Jest unit tests for components
- [ ] Write Playwright e2e tests for complete workflow:
  - Connect Immich account
  - Trigger album sync
  - Browse albums
  - Link album to journal
  - View photos in journal
- [ ] Document Immich integration UI in code comments

**UI Features:**
- Server URL and API key configuration
- Connection validation
- Manual sync trigger
- Album browser with search
- Album linking to journals
- Photo gallery in journal view

## Architecture Notes

**Isolated Worker Architecture:**
- Separate Docker container for Immich worker
- Message-based communication via ARQ task queue
- Idempotent operations for safe message redelivery
- Metadata sync only (photos fetched on-demand)

**On-Demand Photo Fetching:**
- Photos not cached locally
- Fetched from Immich API when journal viewed
- Thumbnail URLs generated by Immich
- Full-size URLs generated by Immich
- Reduces storage requirements

**Album Linking:**
- One album per journal (PHOTO_ALBUM type)
- Album referenced by `immich_album_id`
- Photos displayed inline in journal view
- Link to Immich for full album management

**Future Enhancements (Phase 9+):**
- Auto-create albums based on event date range
- Person-to-contact matching (optional)
- Photo-based journal entry suggestions
- Photo metadata search integration

## Testing Strategy

**Unit Tests:**
- API key validation
- Album metadata transformation
- Photo URL generation
- Sync service logic

**Integration Tests:**
- API client with mock Immich API
- Album sync with real database
- Photo metadata extraction
- ARQ worker with Dishka DI

**E2E Tests (Playwright):**
- Connect Immich account (with mock API)
- Trigger album sync
- Browse albums
- Link album to journal
- View photos in journal

## Success Criteria

- ✅ Immich API client with API key authentication
- ✅ Album and photo metadata synchronization
- ✅ Photo gallery display in journals (inline)
- ✅ Album linking to journal entries
- ✅ On-demand photo fetching (no local caching)
- ✅ ARQ worker following isolated worker architecture
- ✅ Integration management UI with album browser
- ✅ All tests passing (unit, integration, e2e)
- ✅ System in working state after each PR

## Next Steps

**Immediate:** Iteration 7 (Google Calendar Integration)
- Google Calendar API extension
- Calendar sync with EVENT journals
- Bidirectional synchronization
- Advanced calendar features (meeting prep, analytics)

**Future Enhancements (Phase 9+):**
- Auto-create albums based on event date range
- Person-to-contact matching
- Photo-based journal entry suggestions
- Photo metadata search integration

