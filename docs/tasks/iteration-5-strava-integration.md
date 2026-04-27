# Iteration 5: Strava Integration

**Status:** ⛔ SUPERSEDED
**Superseded By:** [Iteration 5: Integration Architecture & Strava Integration](./iteration-5-integration-architecture-and-strava.md)

> [!CAUTION]
> This document has been superseded. The new iteration 5 document expands the scope to include event bus migration (Redis Streams) and pluggable integration UI in addition to Strava. The [Integration Architecture & Strava Product Specification](../product-specifications/integration-architecture-and-strava-product-specification.md) defines the target product behaviour.
>
> Non-conflicting detail from this document (OAuth flow steps, API client methods, ARQ worker lifecycle) remains valid as supplementary reference.

**Dependencies:** Iteration 4.5 (Fitness & Activity Types)
**Goal:** Integrate Strava activities with automatic journal entry creation and merge capabilities

## Overview

This iteration implements Strava integration following the [journal system specification](../journal-system-specification.md#strava-integration) and [integration architecture](../architecture/integration-architecture.md):

**Core Features:**
- Strava OAuth 2.0 authentication with automatic token refresh
- Activity data synchronization (incremental sync)
- Automatic FITNESS journal creation from Strava activities
- GPX track import and storage
- Merge logic for duplicate detection and conflict resolution
- ARQ worker for background sync following isolated worker architecture
- Integration management UI with sync status and conflict resolution

**Integration Behavior:**
- **Import:** Strava activities automatically create FITNESS + OUTDOOR_ACTIVITY journals
- **Merge:** When Strava activity matches existing journal, prompt user for field-by-field resolution
- **Sync Direction:** One-way (Strava → Journal, read-only, no write-back)
- **Change Tracking:** All changes attributed to 'strava' source for audit trail

## Prerequisites

- Iteration 4.5 completed (FITNESS and activity types)
- Integration architecture with ARQ workers (from Iteration 2)
- Dishka dependency injection framework
- Outbox pattern for change events
- Strava developer account and API credentials

## Tasks

### ITER5-001: Strava OAuth & API Client 🟡 PLANNED
**Description:** Implement Strava OAuth 2.0 flow and API client
**Strategy:** Single task for authentication foundation
**Specification Reference:** [Strava Integration](../journal-system-specification.md#strava-integration)

**PR Size:** ~5 files (OAuth flow, API client, auth models, tests)

**Acceptance Criteria:**
- [ ] Create `integration_workers/strava/` package structure following isolated worker pattern
- [ ] Implement Strava OAuth 2.0 flow:
  - Authorization URL generation
  - Token exchange from authorization code
  - Automatic token refresh for expired access tokens
  - Token revocation on disconnect
- [ ] Create `UserStravaAuth` model in `core_shared/models/`:
  - `id`, `user_id`, `access_token` (encrypted), `refresh_token` (encrypted)
  - `expires_at`, `athlete_id`, `created_at`, `updated_at`
- [ ] Implement `StravaAPIClient` using Strava API v3:
  - Get athlete profile
  - List activities (with pagination)
  - Get activity details
  - Get activity streams (GPX data)
  - Automatic token refresh on 401 responses
- [ ] Use `EncryptionService` for secure token storage
- [ ] Add database migration for Strava auth tables
- [ ] Write integration tests for OAuth flow and API connectivity
- [ ] Document Strava API integration in code comments

**OAuth Flow:**
1. User clicks "Connect Strava" in UI
2. Redirect to Strava authorization URL
3. User authorizes application
4. Strava redirects back with authorization code
5. Exchange code for access token and refresh token
6. Store encrypted tokens in database

### ITER5-002: Strava Activity Data Sync 🟡 PLANNED
**Description:** Implement activity data synchronization with incremental sync
**Strategy:** Single task for sync service
**Specification Reference:** [Strava Integration](../journal-system-specification.md#strava-integration)

**PR Size:** ~6 files (activity models, sync service, transformation, tests)

**Acceptance Criteria:**
- [ ] Define Pydantic models for Strava API responses:
  - `StravaActivity` (id, name, type, start_date, distance, elevation, duration, etc.)
  - `StravaActivityStream` (GPX data, heart rate, etc.)
- [ ] Create `UserStravaIntegration` model for sync state:
  - `id`, `user_id`, `last_sync_at`, `last_activity_id`, `sync_status`
  - `created_at`, `updated_at`
- [ ] Implement `StravaDataTransformer`:
  - Map Strava activity types to journal types (Run → JOGGING, Ride → FITNESS, Hike → BUSHWALKING, etc.)
  - Transform Strava metrics to FITNESS data (distance, elevation, heart rate, etc.)
  - Convert activity streams to GPX format
  - Extract activity metadata (weather, route, etc.)
- [ ] Create `StravaSyncService` in `integration_workers/strava/`:
  - `full_sync_activities()` - Initial sync of all activities
  - `incremental_sync_activities()` - Sync new activities since last sync
  - Activity deduplication by `strava_activity_id`
  - Conflict detection (matching by date range + activity type)
- [ ] Add database migration for Strava integration state
- [ ] Write unit tests for data transformation and sync logic
- [ ] Write integration tests for sync service
- [ ] Document Strava activity type mapping in code comments

**Activity Type Mapping:**
- Run → JOGGING (requires FITNESS)
- Ride → FITNESS only
- Hike → BUSHWALKING (requires OUTDOOR_ACTIVITY, FITNESS)
- Walk → BUSHWALKING (requires OUTDOOR_ACTIVITY, FITNESS)
- Swim → FITNESS only
- Other → FITNESS only

### ITER5-003: Strava-to-Journal Mapping & Merge Logic 🟡 PLANNED
**Description:** Implement automatic journal creation and merge conflict resolution
**Strategy:** Single task for journal integration
**Specification Reference:** [Merge Behavior](../journal-system-specification.md#strava-integration)

**PR Size:** ~7 files (journal creation, merge logic, conflict resolution, tests)

**Acceptance Criteria:**
- [ ] Implement automatic journal creation from Strava activities:
  - Create journal with title from activity name
  - Set event_date_range from activity start/end times
  - Add FITNESS type with Strava metrics
  - Add activity-specific type based on activity type mapping
  - Store `strava_activity_id` in fitness data
  - Set change source to 'strava' for audit trail
- [ ] Implement duplicate detection:
  - Match by `strava_activity_id` (exact match)
  - Match by date range + activity type (fuzzy match)
  - Calculate confidence score for fuzzy matches
- [ ] Create `JournalMergeService` for conflict resolution:
  - Generic merge function for any field conflicts
  - Field-by-field comparison (Strava vs manual)
  - User confirmation workflow
  - Preserve both data sources in merge history
  - Maintain Strava reference after merge
- [ ] Implement merge UI workflow:
  - Show side-by-side comparison of conflicting fields
  - Allow user to choose Strava or manual value for each field
  - Preview merged result before applying
  - Undo merge capability
- [ ] Add change events for journal creation and merges
- [ ] Write unit tests for merge logic
- [ ] Write integration tests for journal creation and merging
- [ ] Document merge algorithm in code comments

**Merge Workflow:**
1. Strava activity imported
2. System detects potential duplicate (by date + type)
3. User notified of conflict
4. User reviews side-by-side comparison
5. User chooses which data to keep for each field
6. System merges journals with user preferences
7. Strava reference maintained in merged journal

### ITER5-004: Strava ARQ Worker 🟡 PLANNED
**Description:** Implement background sync worker following isolated worker architecture
**Strategy:** Single task for ARQ worker
**Specification Reference:** [Integration Architecture](../architecture/integration-architecture.md)

**PR Size:** ~5 files (ARQ task, worker setup, monitoring, tests)

**Acceptance Criteria:**
- [ ] Create ARQ task `sync_strava_activities(ctx, user_id)` in `integration_workers/strava/worker.py`:
  - Use Dishka DI for service injection
  - Idempotent operation (safe for redelivery)
  - Incremental sync by default, full sync on first run
  - Error handling with retry logic (exponential backoff)
  - Dead letter queue for failed syncs
- [ ] Implement worker lifecycle management:
  - Worker startup with Dishka container initialization
  - Graceful shutdown with resource cleanup
  - Health check endpoint
- [ ] Add worker monitoring:
  - Sync status tracking (in_progress, completed, failed)
  - Sync duration metrics
  - Activity count metrics
  - Error logging with context
- [ ] Create worker Dockerfile following isolated worker pattern:
  - Separate container from main app
  - Minimal dependencies (only Strava-specific)
  - Environment variable configuration
- [ ] Add worker to docker-compose.yml
- [ ] Write integration tests for ARQ worker
- [ ] Document worker deployment in code comments

**Worker Architecture:**
- Isolated container with own dependencies
- Message-based communication via ARQ
- Idempotent operations for safe redelivery
- Full audit trail via change events
- Conflict resolution with user confirmation

### ITER5-005: Strava UI & Management 🟡 PLANNED
**Description:** Build integration management UI with sync status and conflict resolution
**Strategy:** Single task for UI components
**Specification Reference:** [Integration Architecture](../architecture/integration-architecture.md)

**PR Size:** ~6 files (UI components, integration page, conflict resolution, tests)

**Acceptance Criteria:**
- [ ] Create `StravaIntegration` component in `frontend/src/components/integrations/`:
  - Connect/disconnect Strava button
  - OAuth flow handling
  - Sync status display (last sync time, activity count)
  - Manual sync trigger button
  - Sync history with timestamps
- [ ] Create `StravaSyncStatus` component:
  - Real-time sync progress (if in progress)
  - Sync statistics (activities synced, conflicts detected)
  - Error display with retry option
- [ ] Create `StravaMergeConflict` component:
  - Side-by-side comparison of conflicting fields
  - Field-by-field selection (Strava vs manual)
  - Preview merged result
  - Apply/cancel merge actions
- [ ] Add Strava integration to settings page
- [ ] Implement real-time sync status updates (polling or WebSocket)
- [ ] Add activity import history view
- [ ] Write Jest unit tests for components
- [ ] Write Playwright e2e tests for complete workflow:
  - Connect Strava account
  - Trigger sync
  - View imported activities as journals
  - Resolve merge conflict
- [ ] Document Strava integration UI in code comments

**UI Features:**
- OAuth flow with redirect handling
- Sync status with progress indicator
- Manual sync trigger
- Conflict resolution workflow
- Activity import history
- Disconnect with confirmation

## Architecture Notes

**Isolated Worker Architecture:**
- Separate Docker container for Strava worker
- Message-based communication via ARQ task queue
- Idempotent operations for safe message redelivery
- Full audit trail via change events
- Conflict resolution with user confirmation

**Change Event Tracking:**
- All journal changes attributed to 'strava' source
- Enables audit trail of modifications
- Supports future analytics on integration usage
- Allows rollback of integration changes

**Merge Strategy:**
- Generic merge function for any field conflicts
- User-driven conflict resolution (not automatic)
- Preserve both data sources in merge history
- Maintain Strava reference after merge

**Sync Strategy:**
- Incremental sync by default (new activities only)
- Full sync on first connection
- Sync triggered manually or on schedule
- Deduplication by `strava_activity_id`

## Testing Strategy

**Unit Tests:**
- OAuth token refresh logic
- Activity type mapping
- Data transformation (Strava → Journal)
- Merge conflict detection
- Merge resolution logic

**Integration Tests:**
- OAuth flow with mock Strava API
- Activity sync with real database
- Journal creation from Strava data
- Merge workflow with conflict resolution
- ARQ worker with Dishka DI

**E2E Tests (Playwright):**
- Connect Strava account (with mock OAuth)
- Trigger activity sync
- View imported activities as journals
- Resolve merge conflict
- Disconnect Strava account

## Success Criteria

- ✅ Strava OAuth 2.0 authentication working
- ✅ Activity data synchronization (incremental and full)
- ✅ Automatic FITNESS journal creation from Strava
- ✅ GPX track import and storage
- ✅ Merge logic for duplicate detection
- ✅ User-driven conflict resolution workflow
- ✅ ARQ worker following isolated worker architecture
- ✅ Integration management UI with sync status
- ✅ All tests passing (unit, integration, e2e)
- ✅ System in working state after each PR
- ✅ Change events with 'strava' source attribution

## Next Steps

**Immediate:** Iteration 6 (Immich Integration)
- Immich API client and authentication
- Album and photo data synchronization
- Photo display in journals
- Album linking to journal entries

**Then:** Iteration 7 (Google Calendar Integration)
- Calendar sync with EVENT journals
- Bidirectional synchronization
- Advanced calendar features

