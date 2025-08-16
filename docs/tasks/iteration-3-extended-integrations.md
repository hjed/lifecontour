# Iteration 3: Extended Integrations

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 2 (Integration Architecture Foundation)
**Goal:** Expand integration capabilities with Immich photos, Strava activities, and financial data

## Overview

This iteration leverages the integration architecture established in Iteration 2 to add:
- Immich photo service integration with person-to-contact matching
- Strava activity integration with automatic journal entry creation
- Firefly III financial integration with transaction linking
- Enhanced MCP tools for cross-integration search and management
- Unified integration management dashboard

## Prerequisites

- Iteration 2 must be completed (Dishka migration, ARQ workers, production patterns)
- Integration architecture foundation established
- Google Contacts integration working as reference implementation
- Production resilience patterns implemented

## Tasks

### ITER3-001: Immich Integration 🟡 PLANNED
**Description:** Implement Immich photo service integration with person matching
**Strategy:** Break into 4 manageable slices following established integration patterns

#### Slice 1: Immich API Client & Authentication 🟡 PLANNED
**PR Size:** ~5 files (API client, auth models, configuration, tests)

**Acceptance Criteria:**
- [ ] Create `integrations/immich` package structure following Google Contacts pattern
- [ ] Implement `ImmichAPIClient` using Immich REST API
- [ ] Create `UserImmichAuth` DB model for API key storage with encryption
- [ ] Implement `ImmichAuthService` for credential management
- [ ] Add Immich configuration to worker secrets management
- [ ] Write integration tests for API client connectivity and authentication
- [ ] Add database migration for Immich auth tables

**Architecture Notes:**
- Follow established patterns from Google Contacts integration
- Use EncryptionService for secure API key storage
- Implement proper error handling and retry logic

#### Slice 2: Album & Photo Data Modeling 🟡 PLANNED
**PR Size:** ~6 files (Data models, transformer, sync service, tests)

**Acceptance Criteria:**
- [ ] Define Pydantic models for Immich API responses (albums, photos, people)
- [ ] Create `Album` and `Photo` domain entities in core_shared
- [ ] Implement `ImmichDataTransformer` for API data to domain model mapping
- [ ] Create `UserImmichIntegration` DB model for sync state management
- [ ] Implement `ImmichSyncService.full_sync_albums()` and `full_sync_photos()`
- [ ] Write comprehensive unit tests for data transformation and sync logic
- [ ] Add database migrations for album and photo tables

#### Slice 3: Person-to-Contact Matching 🟡 PLANNED
**PR Size:** ~4 files (Matching service, algorithms, tests)

**Acceptance Criteria:**
- [ ] Create `PersonMatchingService` for name-based contact matching
- [ ] Implement fuzzy name matching algorithms with confidence scoring
- [ ] Add manual person-to-contact linking capabilities
- [ ] Create `PersonContactLink` model for storing confirmed matches
- [ ] Implement matching result review and approval workflow
- [ ] Write unit tests for matching algorithms and edge cases
- [ ] Add database migration for person-contact link table

#### Slice 4: ARQ Worker & Album Linking 🟡 PLANNED
**PR Size:** ~5 files (ARQ task, album linking, UI integration, tests)

**Acceptance Criteria:**
- [ ] Create ARQ task `sync_immich_data(ctx, user_id)` using Dishka patterns
- [ ] Implement album linking to journal entries and calendar events
- [ ] Add photo metadata extraction and indexing for search
- [ ] Create album browsing and management UI components
- [ ] Implement person-to-contact linking UI with confidence indicators
- [ ] Write integration tests for complete Immich sync workflow
- [ ] Add Immich health checks to integration monitoring

### ITER3-002: Strava Integration 🟡 PLANNED
**Description:** Implement Strava activity integration with journal automation
**Strategy:** Break into 3 slices focusing on activity sync and journal integration

#### Slice 1: Strava API Client & OAuth 🟡 PLANNED
**PR Size:** ~5 files (OAuth flow, API client, auth models, tests)

**Acceptance Criteria:**
- [ ] Create `integrations/strava` package structure
- [ ] Implement Strava OAuth 2.0 flow with refresh token management
- [ ] Create `UserStravaAuth` DB model with encrypted token storage
- [ ] Implement `StravaAPIClient` using Strava API v3
- [ ] Add automatic token refresh logic for expired access tokens
- [ ] Write integration tests for OAuth flow and API connectivity
- [ ] Add database migration for Strava auth tables

#### Slice 2: Activity Data Sync 🟡 PLANNED
**PR Size:** ~6 files (Activity models, sync service, transformation, tests)

**Acceptance Criteria:**
- [ ] Define Pydantic models for Strava activity API responses
- [ ] Create `Activity` domain entity in core_shared
- [ ] Implement `StravaDataTransformer` for activity data mapping
- [ ] Create `StravaSyncService` with incremental sync using activity timestamps
- [ ] Implement activity deduplication and conflict resolution
- [ ] Write unit tests for activity sync and transformation logic
- [ ] Add database migrations for activity tables

#### Slice 3: Journal Integration & ARQ Worker 🟡 PLANNED
**PR Size:** ~5 files (Journal automation, ARQ task, UI components, tests)

**Acceptance Criteria:**
- [ ] Create ARQ task `sync_strava_activities(ctx, user_id)` using Dishka
- [ ] Implement automatic journal entry creation from activities
- [ ] Add activity linking to existing journal entries and events
- [ ] Create activity statistics and analytics components
- [ ] Implement activity-based insights and recommendations
- [ ] Write integration tests for complete Strava workflow
- [ ] Add Strava monitoring to integration health checks

### ITER3-003: Firefly III Integration 🟡 PLANNED
**Description:** Implement financial data integration with transaction linking
**Strategy:** Break into 3 slices for transaction sync and financial insights

#### Slice 1: Firefly III API Client 🟡 PLANNED
**PR Size:** ~4 files (API client, auth models, configuration, tests)

**Acceptance Criteria:**
- [ ] Create `integrations/firefly` package structure
- [ ] Implement `FireflyAPIClient` using Firefly III REST API
- [ ] Create `UserFireflyAuth` DB model for personal access token storage
- [ ] Implement secure token management with encryption
- [ ] Add Firefly III configuration to worker secrets
- [ ] Write integration tests for API connectivity and authentication
- [ ] Add database migration for Firefly auth tables

#### Slice 2: Transaction Data Sync 🟡 PLANNED
**PR Size:** ~6 files (Transaction models, sync service, categorization, tests)

**Acceptance Criteria:**
- [ ] Define Pydantic models for Firefly III transaction API responses
- [ ] Create `Transaction` domain entity in core_shared
- [ ] Implement `FireflyDataTransformer` for transaction data mapping
- [ ] Create `FireflySyncService` with date-based incremental sync
- [ ] Implement transaction categorization and tagging
- [ ] Write unit tests for transaction sync and categorization
- [ ] Add database migrations for transaction tables

#### Slice 3: Financial Insights & Contact Linking 🟡 PLANNED
**PR Size:** ~5 files (Linking logic, analytics, ARQ task, tests)

**Acceptance Criteria:**
- [ ] Create ARQ task `sync_firefly_transactions(ctx, user_id)` using Dishka
- [ ] Implement transaction linking to contacts and events
- [ ] Add financial insights and spending analytics
- [ ] Create transaction history and trend visualization
- [ ] Implement budget tracking and financial goal monitoring
- [ ] Write integration tests for complete Firefly workflow
- [ ] Add Firefly monitoring to integration health checks

### ITER3-004: Integration MCP Tools 🟡 PLANNED
**Description:** Add comprehensive integration management tools to MCP interface
**Strategy:** Single focused task for MCP tool enhancement

**PR Size:** ~6 files (MCP tools, search integration, management tools, tests)

**Acceptance Criteria:**
- [ ] Implement cross-integration search tools (photos, activities, transactions)
- [ ] Add integration status monitoring and control tools via MCP
- [ ] Create sync management tools for all integrations
- [ ] Implement conflict resolution tools via MCP interface
- [ ] Add integration analytics and insights tools
- [ ] Create bulk sync and management operations
- [ ] Implement data export and import tools via MCP
- [ ] Add integration health monitoring tools
- [ ] Write comprehensive MCP integration tests
- [ ] Document integration MCP capabilities for AI assistants

**MCP Tools to Implement:**
- `search_across_integrations()` - Global search across all integrated data
- `get_integration_status()` - Status of all user integrations
- `trigger_sync()` - Manual sync trigger for specific integrations
- `resolve_conflicts()` - Conflict resolution assistance
- `get_integration_insights()` - Analytics and insights across integrations
- `export_integration_data()` - Data export capabilities
- `manage_integration_auth()` - Authentication management

## Architecture Notes

- **Consistency:** All integrations follow patterns established in Google Contacts integration
- **Dependency Injection:** Use Dishka framework throughout for type safety and lifecycle management
- **Task Queue:** ARQ with Redis for all background processing
- **Data Models:** Domain entities in core_shared, integration-specific models in respective packages
- **Authentication:** Encrypted credential storage using established EncryptionService
- **Sync Strategy:** Incremental sync where supported by APIs, full sync fallback
- **Error Handling:** Comprehensive retry logic, dead letter queues, and monitoring
- **Testing:** Unit tests for business logic, integration tests for API interactions

## Integration Patterns

Each integration follows this established pattern:
1. **API Client:** HTTP client with authentication and error handling
2. **Data Models:** Pydantic models for API responses, domain entities for business logic
3. **Transformer:** Convert API data to domain models with validation
4. **Sync Service:** Business logic for data synchronization and conflict resolution
5. **ARQ Worker:** Background task for scheduled and triggered sync operations
6. **UI Components:** Management interface for configuration and monitoring
7. **MCP Tools:** AI assistant integration for data access and management

## Dependencies

- **External Services:**
  - Immich instance with API access
  - Strava developer account and API credentials
  - Firefly III instance with personal access tokens
- **Internal Dependencies:**
  - Iteration 2 completed (Dishka, ARQ, production patterns)
  - Integration architecture foundation
  - MCP server with FastMCP v2

## Success Criteria

- All three integrations working with bidirectional sync where applicable
- Unified integration management dashboard
- Cross-integration search and analytics
- Comprehensive MCP tools for AI assistant integration
- Production-ready monitoring and error handling
- Complete test coverage for all integration workflows

## Next Steps

This iteration sets the foundation for:
- Journal system with automatic content from integrations (Iteration 4)
- Calendar integration with event linking (Iteration 5)
- Advanced analytics and insights across all data sources (Iteration 6)
