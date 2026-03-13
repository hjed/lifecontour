# ITER2-002: Google Contacts Integration Implementation Plan

## Overview

This document outlines the implementation plan for ITER2-002: Google Contacts Integration, broken down into 5 manageable slices that can be implemented as separate PRs. The approach leverages Google's advanced sync features (sync-token, ETags) for efficient and robust synchronization.

## Key Architectural Decisions

### 1. Sync Strategy
- **Primary**: Use Google's `sync-token` for efficient incremental updates (29-day validity)
- **Fallback**: Full sync when sync-token expires or is invalid (HTTP 410)
- **Smart Strategy**: Worker automatically chooses between incremental and full sync

### 2. Conflict Resolution
- **Method**: Optimistic concurrency control using Google's ETags
- **Implementation**: Send ETag in `If-Match` header for updates
- **Conflict Handling**: Log `412 Precondition Failed` errors and skip conflicted updates
- **Rationale**: Prevents overwriting changes made directly in Google Contacts

### 3. Credential Management
- **Storage**: Encrypted `refresh_tokens` in database via `GoogleAuthService`
- **Security**: Application-layer encryption using secrets manager key
- **Auto-refresh**: Handle 401 responses by refreshing tokens automatically

### 4. Sync Triggers
- **Primary**: Periodic ARQ cron jobs for all connected users
- **Secondary**: User-initiated sync via API endpoint
- **Both use**: Same `sync_google_contacts` ARQ task for consistency

## Implementation Slices

### Slice 1: Foundational API Client & Credential Management 🟢
**Goal**: Establish secure, authenticated connection to Google People API using official library

**Key Components**:
- `GoogleAuthService`: Manage encrypted OAuth tokens
- `GoogleAPIClient`: Wrapper around `google-api-python-client` with credential management
- Worker secrets configuration for Google API credentials
- Official library: `google-api-python-client google-auth-httplib2 google-auth-oauthlib`

**Deliverable**: Working API client using official Google library with auto-refresh tokens

### Slice 2: Data Modeling & Read-Only Full Sync 🟢
**Goal**: Define data models and implement full synchronization

**Key Components**:
- Pydantic models for Google Contact API responses
- Data transformer (Google → core_shared models)
- `GoogleService.full_sync()` with pagination
- `UserGoogleIntegration` model to store sync_token

**Deliverable**: Service that can fetch all contacts and return sync_token

### Slice 3: Idempotent Persistence & Incremental Sync Logic 🟡
**Goal**: Implement efficient incremental synchronization

**Key Components**:
- `SyncMetadata` model (item_id, external_id, version_hash as ETag)
- Persistence logic for full_sync results
- `GoogleService.incremental_sync()` using sync_token
- Handle created/updated/deleted contacts with soft-deletion

**Deliverable**: Complete sync persistence with incremental updates

### Slice 4: ARQ Worker with Smart Sync Strategy 🟡
**Goal**: Move to background tasks with intelligent sync decisions

**Key Components**:
- `sync_google_contacts(ctx, user_id)` ARQ task
- Session-per-task database pattern
- Smart sync strategy (check token, choose sync type)
- Handle expired tokens (HTTP 410 → full sync)
- DLQ configuration and structured logging

**Deliverable**: Reliable background sync with error handling

### Slice 5: Two-Way Sync & Conflict Resolution 🟡
**Goal**: Complete bidirectional synchronization

**Key Components**:
- Detect local changes since last sync
- Push changes to Google using ETag concurrency control
- Handle conflicts (412 errors) gracefully
- Update SyncMetadata after successful pushes
- Comprehensive integration tests

**Deliverable**: Full two-way sync with conflict resolution

## Technical Implementation Details

### Google People API Features Used
- **Official Python Client**: `google-api-python-client` with built-in authentication
- **Contacts List**: `service.people().connections().list()` with sync_token parameter
- **ETags**: Individual contact versioning for optimistic concurrency
- **Sync Tokens**: Collection-level change tracking (29-day validity)
- **OAuth 2.0**: Secure authentication with refresh token flow via `google-auth-oauthlib`

### Database Schema
```sql
-- User OAuth credentials (encrypted)
UserGoogleAuth: user_id, access_token, refresh_token, expires_at

-- Per-user sync state
UserGoogleIntegration: user_id, sync_token, last_sync_at

-- Per-contact sync metadata
SyncMetadata: item_id, external_id, version_hash, last_synced_at
```

### Error Handling Strategy
- **Token Expiry**: Auto-refresh on 401, fallback to full sync on 410
- **Rate Limiting**: Exponential backoff on 429 responses
- **Conflicts**: Log 412 errors, continue with other contacts
- **Network Issues**: ARQ retry with DLQ for persistent failures

## Risk Mitigation

### Identified Risks
1. **Rate Limiting**: Initial full sync for users with many contacts
2. **Token Revocation**: Users can revoke access from Google settings
3. **Sync Token Expiry**: 29-day validity requires fallback handling
4. **Data Loss**: Conflicts could result in lost changes

### Mitigation Strategies
1. **Rate Limiting**: Exponential backoff, respect 429 responses
2. **Token Revocation**: Graceful handling of invalid_grant errors
3. **Sync Token Expiry**: Automatic fallback to full sync on HTTP 410
4. **Data Loss**: Optimistic concurrency control with ETag validation

## Testing Strategy

### Unit Tests
- Mock Google API responses for all scenarios
- Test data transformers and sync logic
- Verify error handling paths

### Integration Tests
- Real database with transaction isolation
- Mock HTTP responses using respx + httpx
- Test token refresh, conflicts, and sync scenarios

### End-to-End Tests
- Full sync workflow validation
- Two-way sync with conflict resolution
- Error recovery and retry logic

## Success Criteria

Each slice must meet these criteria before moving to the next:
1. **All tests passing** (unit + integration)
2. **Code review approved** by team
3. **Linting and type checking** clean (ruff + mypy)
4. **Documentation updated** for new components
5. **Deployable independently** without breaking existing functionality

## Next Steps

1. **Start with Slice 1**: Focus on authentication and API client
2. **Validate early**: Test with real Google API in development
3. **Iterate based on feedback**: Adjust approach based on real-world testing
4. **Monitor performance**: Track sync times and error rates
5. **Plan for scale**: Consider batch operations for large contact lists
