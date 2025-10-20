# Iteration 3: Extended Integrations

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 2 (Integration Architecture Foundation)
**Goal:** Expand integration capabilities with Firefly III financial data and unified integration management

## Overview

This iteration leverages the integration architecture established in Iteration 2 to add:
- Firefly III financial integration with transaction linking
- Enhanced MCP tools for cross-integration search and management
- Unified integration management dashboard

**Note:** Strava and Immich integrations have been moved to Iterations 5 and 6 respectively, after the journal system is implemented in Iteration 4.

## Prerequisites

- Iteration 2 must be completed (Dishka migration, ARQ workers, production patterns)
- Integration architecture foundation established
- Google Contacts integration working as reference implementation
- Production resilience patterns implemented

## Tasks

### ITER3-001: Firefly III Integration 🟡 PLANNED
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

### ITER3-002: Integration Management Dashboard 🟡 PLANNED
**Description:** Build unified integration management UI
**Strategy:** Single task for integration management interface

**PR Size:** ~5 files (Dashboard component, integration cards, sync controls, tests)

**Acceptance Criteria:**
- [ ] Create `IntegrationDashboard` component in `frontend/src/components/integrations/`:
  - List all integrations (Google Contacts, Firefly III)
  - Show connection status for each integration
  - Display last sync time and sync statistics
  - Manual sync trigger buttons
  - Connect/disconnect controls
- [ ] Create integration-specific management cards:
  - Google Contacts: sync status, contact count, last sync
  - Firefly III: sync status, transaction count, last sync
- [ ] Implement sync status monitoring:
  - Real-time sync progress (polling or WebSocket)
  - Sync history with timestamps
  - Error display with retry options
- [ ] Add integration health checks:
  - Connection status indicators
  - API health monitoring
  - Error rate tracking
- [ ] Write Jest unit tests for components
- [ ] Write Playwright e2e tests for integration management workflows
- [ ] Document integration management UI in code comments

**UI Features:**
- Unified dashboard for all integrations
- Connection status indicators
- Manual sync triggers
- Sync history and statistics
- Error handling and retry options

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

**Integration Preparation for Journal System:**
- Firefly III transactions will link to journal entries (Iteration 4)
- Strava and Immich integrations moved to Iterations 5 and 6 after journal system
- Integration architecture ready for additional integrations

## Testing Strategy

**Unit Tests:**
- Firefly III API data transformation
- Transaction categorization logic
- Sync service business logic

**Integration Tests:**
- Firefly III API client with mock API
- Transaction sync with real database
- ARQ worker with Dishka DI

**E2E Tests (Playwright):**
- Connect Firefly III account
- Trigger transaction sync
- View transactions in dashboard
- Link transaction to contact

## Dependencies

- **External Services:**
  - Firefly III instance with personal access tokens
- **Internal Dependencies:**
  - Iteration 2 completed (Dishka, ARQ, production patterns)
  - Integration architecture foundation
  - MCP server with FastMCP v2

## Success Criteria

- ✅ Firefly III financial integration with transaction linking functional
- ✅ Integration management dashboard with monitoring
- ✅ All integrations following established patterns and best practices
- ✅ All integration workers using Dishka dependency injection
- ✅ Production-ready error handling and monitoring
- ✅ Complete test coverage for all integration workflows
- ✅ System in working state after each PR

## Next Steps

**Immediate:** Iteration 4 (Journal Core & Base Types)
- Journal system with integration linking
- Preparation for Strava and Immich integrations
- Event-based architecture for integrations

**Then:** Iteration 5 (Strava Integration)
- Strava activity sync with automatic journal creation
- GPX track import and display

**Then:** Iteration 6 (Immich Integration)
- Photo album linking to journals
- Photo display in journal entries
