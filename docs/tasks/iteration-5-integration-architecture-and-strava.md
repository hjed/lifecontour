# Iteration 5: Integration Architecture & Strava Integration

**Status:** 🟡 IN PROGRESS
**Dependencies:** Iteration 4.5 (fitness & activity types), Iteration 7 (calendar sync, merge/review, MCP parity — partial), Iteration 9 (outdoor logbook activity types — partial)
**Goal:** Replace the hard-coded outbox processor with a Redis Streams event bus, make integrations pluggable, and deliver one-way Strava activity import with merge review.

## Overview

This iteration supersedes the earlier [iteration-5-strava-integration.md](./iteration-5-strava-integration.md). It addresses architectural debt in the event processing system before layering Strava on top.

The work is split into two streams:
1. **Infrastructure (Tasks 1–2):** Event bus migration and pluggable integration UI — no dependency on iteration 9.
2. **Strava (Tasks 3–6):** OAuth, activity import, participant detection, external links — depends on iteration 9 activity types.

## Reference Documents

- **[Integration Architecture & Strava Product Specification](../product-specifications/integration-architecture-and-strava-product-specification.md)** — approved product behaviour for this iteration
- **[Integration Architecture](../architecture/integration-architecture.md)** — event-driven integration patterns
- **[Journals Product Specification](../product-specifications/journals-product-specification.md)** — merge, review, hierarchy
- **[Outdoor Logbook Product Specification](../product-specifications/outdoor-logbook-product-specification.md)** — activity types Strava maps to
- **[Domain Architecture](../architecture/domain-architecture.md)** — domain patterns and service layer
- **[API Design](../architecture/api-design.md)** — REST and MCP API patterns
- **[Frontend Design](../architecture/frontend-design.md)** — Next.js, shadcn/ui, form guidelines
- **[Testing Strategy](../architecture/testing-strategy.md)** — test-first workflow

## Delivery Rules

These rules apply to every task:

1. **Tests first:** write failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks pass.
3. **Reviewable PRs:** keep each PR to roughly ≤ 10 files where practical.
4. **MCP parity:** if a capability is meaningful in the UI, expose through MCP in the same task.
5. **Full vertical slice:** each task delivers backend, frontend (where applicable), and MCP together.
6. **Every task is shippable:** no task may rely on a later task to restore broken behaviour.
7. **No behaviour change in infrastructure tasks:** Tasks 1–2 must produce identical observable behaviour. The change is structural, not functional.

## Dependency and Parallelisation Notes

- **Task 1** has no external dependencies beyond what is already complete. It can start immediately.
- **Task 2** depends on **Task 1** (consumer groups must exist before integration registry consumes events).
- **Task 3** depends on **Task 1** (Strava worker publishes to Redis Streams, not ARQ). Does not depend on iteration 9.
- **Task 4** depends on **Task 3** (OAuth and API client required) AND **ITER9-003** (new activity types: CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING must exist for type mapping).
- **Task 5** depends on **Task 4** (journals must exist to add participants and links to).
- **Task 6** depends on **Task 5** (external links and Strava data must exist for MCP exposure).
- **Tasks 1 and 2** can run in parallel with iteration 9 work since they are infrastructure-only.

### External Dependencies

| Dependency | Required By | Status |
|---|---|---|
| ITER7-003 (Match Detection & Review Queue) | Task 4 Phase 3 (merge review for Strava imports) | ✅ Phase 1 COMPLETE, Phases 2–3 COMPLETE |
| ITER7-004 (Journal Merge Execution) | Task 4 Phase 3 (merge Strava + existing journals) | ✅ Phases 1–3 COMPLETE |
| ITER9-003 (New Outdoor Activity Types) | Task 4 (Strava type mapping for CANOEING, DOWNHILL_SKIING, etc.) | ❌ NOT STARTED |
| ITER9-002 (Modified Types — CLIMBING, KAYAKING) | Task 4 (Strava type mapping for kayaking rapids) | ❌ NOT STARTED |
| ITER7-008 (AI Daily Summary) | None — not a dependency | ✅ Phase 1 COMPLETE ([#666](https://github.com/hjed/personal-management-system/pull/666)) |

---

## Task Breakdown

### ITER5-001: Redis Streams Event Bus Migration

**Objective:** Replace the hard-coded outbox processor dispatch with a Redis Streams relay and independent consumer groups, so that a single domain event is published once and consumed independently by all systems.

**Strategy:** Split into 4 phases. Phase 1 builds the relay and base consumer framework. Phases 2–3 migrate existing consumers one boundary at a time. Phase 4 removes legacy code. Each phase preserves identical observable behaviour — the old and new paths coexist via a feature flag until Phase 4.

**Specification Reference:**
- [Part 1: Integration Event Architecture](../product-specifications/integration-architecture-and-strava-product-specification.md#part-1-integration-event-architecture)
- [Integration Architecture — Transactional Outbox Pattern](../architecture/integration-architecture.md#transactional-outbox-pattern)

**Acceptance Criteria (task-level):**
- [x] Outbox relay publishes events to a Redis Stream (`domain-events`)
- [x] Search indexer, AI summary generator, Google worker, and inbound event processor each run as independent consumer groups
- [x] All existing tests pass without modification (behaviour unchanged)
- [x] Failed events are retried per-consumer independently
- [x] No hard-coded event routing remains in `OutboxProcessor`

#### Phase 1: Outbox Relay, Base Consumer Framework, and Stream Infrastructure
**PR Size:** ~6–8 files

Introduce the relay process, the base `StreamConsumer` class, consumer group management, and the migration for tracking relay state. No existing consumers are migrated yet — this phase is pure infrastructure.

**Acceptance Criteria:**
- [x] Migration adds `relayed_at` column to outbox table
- [x] `OutboxRelay` reads unprocessed outbox events, publishes to `pms:domain-events` Redis Stream, marks `relayed_at`
- [x] Relay is idempotent — re-publishing an already-relayed event is a no-op
- [x] Base `StreamConsumer` class with: consumer group creation, event reading (`XREADGROUP`), acknowledgement (`XACK`), event filtering by `event_type` pattern, retry via pending entries list
- [x] Configuration for stream name, consumer group names, batch size, poll interval
- [x] Feature flag (`USE_STREAM_CONSUMERS`) to run relay alongside existing `OutboxProcessor` — both paths active during migration

**Required Test Coverage:**
- **Unit:** relay batch processing, idempotency detection, `StreamConsumer` base class event filtering and ack logic.
- **Integration:** relay reads real outbox rows, publishes to Redis Stream, marks as relayed. Base consumer reads and acknowledges events from stream.

#### Phase 2: Migrate Search Indexer and Summary Generator to Consumer Groups
**PR Size:** ~5–7 files

Extract the `SearchIndexer` and `ContactSummaryRefreshRequested` processing from `OutboxProcessor._process_single_event` into independent stream consumers. These two are the simplest consumers (no external API calls, no complex DI trees).

**Acceptance Criteria:**
- [x] `SearchIndexerConsumer` (group: `search-indexer`): handles `Contact*`, `Journal*`, `TagAssigned`, `TagRemoved`, `ImportantDate*` events for MeiliSearch indexing, plus daily summary invalidation for journal events
- [x] `SummaryConsumer` (group: `summary-generator`): handles `ContactSummaryRefreshRequested` events, generates AI summaries, then updates search index
- [x] Both consumers acknowledge irrelevant events immediately (no processing)
- [x] Existing `SearchIndexer.process_event` logic reused — consumer is a thin wrapper
- [x] `stream_event_to_outbox_event` adapter converts `StreamEvent` to `OutboxEvent` for reuse
- [x] Feature flag: when `USE_STREAM_CONSUMERS=true`, search/summary events are processed via stream consumers instead of `OutboxProcessor`
- [x] `OutboxProcessor` gated: skips `SearchIndexer.process_event`, `_process_summary_generation_event`, `_invalidate_daily_summary_for_journal_event` when flag is enabled
- [x] Contact sync and ARQ broadcast now processed by Phase 3 stream consumers (`InboundEventConsumer`, `GoogleOutboundConsumer`)
- [x] Consumers wired as `asyncio.Task`s in FastAPI lifespan alongside `OutboxRelay`
- [x] All existing search indexing and summary generation tests pass unchanged

**Required Test Coverage:**
- **Unit:** `SearchIndexerConsumer` event routing (30 tests), `SummaryConsumer` event filtering (16 tests), `StreamEventAdapter` (6 tests), `OutboxProcessor` feature flag gating (5 tests). ✅ All 108 event tests pass.
- **Integration:** SearchIndexerConsumer processes ContactCreated + JournalCreated events from real Redis stream, acknowledges irrelevant events. SummaryConsumer processes ContactSummaryRefreshRequested from real Redis stream. ✅ 4 integration tests pass.
- **E2E:** create/update a contact and journal, verify search results update correctly via stream consumer path.

#### Phase 3: Migrate Inbound Processors and Google Outbound Broadcast
**PR Size:** ~6–8 files

Migrate the remaining consumers: the inbound event processors (`_process_contact_event`, `_process_journal_sync_event`) and the Google outbound broadcast (`_process_tag_event`, `_process_journal_event`). These are more complex due to deep DI trees and external API integration.

**Acceptance Criteria:**
- [x] `InboundEventConsumer` (group: `inbound-processor`): handles `contact.*` (contact sync from Google), `journal_event.*` (journal sync from Google Calendar), `journal_review.*` (match detection)
- [x] `GoogleOutboundConsumer` (group: `google-worker`): handles `JournalCreated`, `JournalUpdated`, `JournalDeleted`, `TagUpdated`, `TagDeleted` events for broadcasting to Google integration worker via ARQ
- [x] Inbound consumer reuses existing `OutboxEventProcessor` and `JournalOutboxEventProcessor` logic
- [x] Google outbound consumer reuses existing `TaskQueueService.broadcast_*` methods
- [x] Consumer failure isolation: inbound processor failure does not block Google outbound or search indexing
- [x] All `OutboxProcessor._process_single_event` routing now fully replaced by stream consumers

**Required Test Coverage:**
- **Unit:** `InboundEventConsumer` routing for contact/journal/review events (26 tests), `GoogleOutboundConsumer` event filtering (28 tests), `OutboxProcessor` Phase 3 gating (8 tests). ✅ All 165 event tests pass.
- **Integration:** inbound contact sync event flows through stream consumer → `OutboxEventProcessor`. Inbound journal event flows through → `JournalOutboxEventProcessor`. Google outbound event triggers ARQ broadcast. ✅ 6 integration tests pass.
- **E2E:** existing Google sync and journal import workflows produce identical results via stream consumers.

#### Phase 3.5: Migrate Google Worker to Direct Stream Consumer
**PR Size:** ~5–7 files

Migrate the Google integration worker from receiving journal/tag events via ARQ enqueue to reading directly from the Redis Stream. The product specification states "ARQ remains for long-running tasks (sync jobs, webhook processing) but is no longer used for event fan-out." Phase 3's `GoogleOutboundConsumer` in the backend was a transitional pattern — it reads stream events but still enqueues ARQ jobs. This phase completes the migration by making the Google worker itself a stream consumer.

**Acceptance Criteria:**
- [x] `StreamConsumer` base class moved from `backend/app/infrastructure/events/` to `core_shared/` so it can be used by both backend and integration workers
- [x] Backend `stream_consumer.py` re-exports from `core_shared` for backward compatibility
- [x] `GoogleWorkerStreamConsumer` in `integration_workers/google/`: consumer group `google-worker`, handles `JournalCreated`, `JournalUpdated`, `JournalDeleted`, `TagUpdated`, `TagDeleted`
- [x] Google worker `_handle_event` calls `process_journal_event` / `process_tag_event` directly (no ARQ enqueue)
- [x] Google worker startup launches `GoogleWorkerStreamConsumer` as an `asyncio.Task` alongside existing ARQ worker
- [x] `process_journal_event` and `process_tag_event` removed from ARQ `functions` list (consumed via stream, not ARQ)
- [x] `GoogleOutboundConsumer` removed from backend (replaced by worker's own consumer)
- [x] `TaskQueueService.broadcast_journal_event` / `broadcast_tag_event` methods removed
- [x] Backend `main.py` no longer starts `GoogleOutboundConsumer` task

**Required Test Coverage:**
- **Unit:** `GoogleWorkerStreamConsumer` routes journal events to `process_journal_event`, tag events to `process_tag_event`, irrelevant events ACKed immediately. Backend `StreamConsumer` re-export verified. `TaskQueueService` broadcast methods removed from test coverage. ✅ 29 new unit tests + 1411 backend unit tests pass.
- **Integration:** full broadcast flow — publish domain event to Redis Stream → Google worker stream consumer reads → `process_journal_event`/`process_tag_event` called directly. Verified with real Redis. ✅ 4 integration tests pass.
- **E2E:** existing Google sync and journal import workflows produce identical results with direct stream consumption. ✅ 48 E2E tests pass.

#### Phase 4: Legacy Cleanup, Dead-Letter Handling, and Observability
**PR Size:** ~4–6 files

Remove the old `OutboxProcessor._process_single_event` monolithic dispatch, the feature flag, and add operational tooling.

**Acceptance Criteria:**
- [x] `OutboxProcessor` class and `run_outbox_processor_loop` removed entirely — relay is sole background task
- [x] Feature flag `USE_STREAM_CONSUMERS` removed — stream path is the only path
- [x] `processed_at` column removed from `outbox_events` table (migration) — relay path (`relayed_at`) is the sole dispatch mechanism
- [x] Dead-letter handling: events exceeding max retry count are moved to a dead-letter stream and persisted to `dead_letter_events` database table (displayable on integration dashboard, replayable)
- [x] Consumer lag monitoring endpoint: pending entry count per consumer group (for health checks)
- [x] `integration-architecture.md` updated: replace OutboxProcessor direct-dispatch sections with Redis Streams consumer group architecture. Remove the "Planned Migration" banner added in this iteration
- [x] `architecture.md` updated if it references ARQ-based event fan-out or OutboxProcessor direct dispatch
- [x] Old iteration 5 doc (`iteration-5-strava-integration.md`) — verify superseded banner is still accurate

**Required Test Coverage:**
- **Unit:** dead-letter classification, lag calculation helpers, dead-letter repository CRUD. ✅
- **Integration:** verify dead-letter behaviour for permanently failing events (stream + DB persistence). Verify lag monitoring returns accurate counts. ✅
- **E2E:** full regression — contact CRUD, journal CRUD, Google sync, search all working end-to-end. ✅

---

### ITER5-002: Pluggable Integration Dashboard

**Objective:** Replace the monolithic Google-specific integrations page with a generic dashboard that renders integration panels dynamically from a backend registry.

**Strategy:** Split into 3 phases: backend registry API, shared frontend components with Google migration, then sync history/health/settings surfaces. The current `page.tsx` is ~660 lines of Google-specific UI — splitting the frontend migration across two phases keeps PRs reviewable.

**Specification Reference:**
- [Part 2: Pluggable Integration UI](../product-specifications/integration-architecture-and-strava-product-specification.md#part-2-pluggable-integration-ui)

**Dependencies:** ITER5-001 (consumer groups must exist so integration status reflects stream-based health)

**Acceptance Criteria (task-level):**
- [x] Backend exposes `GET /api/integrations` returning all registered integrations with status, capabilities, and sync summary
- [x] Frontend integrations page renders panels from the registry without integration-specific page components
- [x] Google integration fully migrated to the new pattern
- [x] Sync history, health status, and integration-specific settings accessible from each panel
- [x] Adding a new integration requires only a registry entry, not page layout changes

#### Phase 1: Backend Integration Registry API and MCP Tool ✅
**PR Size:** ~5–7 files

Create the integration registry domain model, REST API, and MCP tool. No frontend changes yet.

**Acceptance Criteria:**
- [x] `IntegrationRegistryService` with pluggable provider registration
- [x] `GoogleIntegrationProvider` implements the registry interface: derives status from OAuth token state and `SyncJob` history
- [x] `GET /api/integrations` endpoint returns list of registered integrations
- [x] Each integration entry: `id`, `name`, `status` (connected/disconnected/error/token_expired), `capabilities` (list), `sync_summary` (last sync time, count, errors), `needs_reauth`, `needs_reconsent`
- [x] `list_integrations` MCP tool returns the same data
- [x] Integration provider registration via Dishka DI
- [x] `integration-architecture.md` updated: add pluggable integration registry pattern and `GET /api/integrations` API documentation

**Required Test Coverage:**
- **Unit:** registry population, status derivation from token/worker state, capability declaration.
- **Integration:** API endpoint tests with Google connected, disconnected, and token_expired states. MCP tool test.
- **E2E:** Verify `GET /api/integrations` returns expected structure with Google entry.

#### Phase 2: Shared Panel Components and Google Connection Migration
**PR Size:** ~6–8 files

Create shared frontend components and migrate Google's connect/disconnect and sync controls from the monolithic page to the generic dashboard pattern.

**Execution Plan:**
1. Update `frontend/src/types/integrations.ts` to include registry schemas and `/api/health/dead-letters` types.
2. Add React Query hooks `useIntegrations` and `useDeadLetters` in `frontend/src/lib/api/integrations.ts`.
3. Create generic `IntegrationPanel`, `ConnectionControls`, `SyncControls` components.
4. Create `DeadLetterQueue` display.
5. Modify `frontend/src/app/integrations/page.tsx` to dynamically render `IntegrationPanel` components based on the registry.
6. Verify UI accessibility, run frontend tests (`pnpm lint`, `pnpm type-check`), and verify E2E tests pass locally.

**Acceptance Criteria:**
- [x] `IntegrationPanel` component: renders any integration from registry data (name, status badge, capability list)
- [x] `ConnectionControls` component: connect/disconnect buttons with OAuth flow handling (parameterised by integration ID and OAuth URL)
- [x] `SyncControls` component: per-capability sync buttons (e.g. "Sync Contacts", "Sync Calendar") driven by `capabilities` array
- [x] Integrations page renders panels dynamically from `GET /api/integrations` — no Google-specific layout
- [x] Google connect/disconnect, sync contacts, sync calendar migrated to shared components
- [x] Dead-letter queue observability: ensure API access to dead-letter events is available and surfaced in the dashboard
- [x] Existing Google integration E2E tests pass with the new component structure

**Required Test Coverage:**
- **Unit:** `IntegrationPanel` rendering for connected/disconnected/error states, `SyncControls` button visibility by capability.
- **Integration:** panel rendering with mocked registry responses for single and multiple integrations.
- **E2E:** connect/disconnect Google and trigger sync through the generic dashboard.

#### Phase 3: Pluggable Integration Observability ✅

**Goal:** Provide full visibility into integration syncs and health status.

- [x] Implement generic `GET /api/integrations/{id}/sync-history` endpoint
- [x] Create generic `SyncHistory` component for integration panel
  - [x] Paginated table of sync jobs
  - [x] Filter by sync type/status
- [x] `HealthStatus` component: worker health indicator (last heartbeat, pending events from consumer lag)
- [x] Integration-specific settings accessible from panel via modal or sub-page (e.g. Google Calendar selection, future Strava type mapping)
  - [x] Settings rendered dynamically from integration-declared settings schema — not hard-coded per integration
  - [x] Existing Google Calendar selection UI (CalendarSettingsDialog) accessible from the Google panel settings
- [x] Unit, Integration, and E2E Tests for the new observability components

**Required Test Coverage:**
- **Unit:** `SyncHistory` rendering with various job states, `HealthStatus` indicator logic.
- **Integration:** sync history endpoint with real `SyncJob` data. Settings modal rendering.
- **E2E:** view sync history for Google, verify health indicator, access calendar settings from generic panel.

---

### ITER5-003: Strava OAuth & API Client

**Objective:** Implement Strava OAuth 2.0 flow, API client, and webhook registration. Add Strava to the integration registry.

**Strategy:** Split into 3 phases: auth model and OAuth flow, API client, then webhook and worker infrastructure.

**Specification Reference:**
- [Part 3: Strava Integration — OAuth & Authentication](../product-specifications/integration-architecture-and-strava-product-specification.md#strava-oauth--authentication)
- [Part 3: Sync Triggers](../product-specifications/integration-architecture-and-strava-product-specification.md#sync-triggers)
- [Iteration 5 (original) — ITER5-001](./iteration-5-strava-integration.md#iter5-001-strava-oauth--api-client)

**Dependencies:** ITER5-001 (Strava worker publishes to Redis Stream), ITER5-002 (Strava needs integration registry). Does NOT depend on iteration 9.

**Acceptance Criteria (task-level):**
- [ ] Strava OAuth flow working end-to-end
- [ ] `StravaAPIClient` can fetch athlete profile, list activities, get activity detail, get activity streams
- [ ] Strava webhook subscription registered and validated
- [ ] Strava appears in integration registry dashboard with connection controls
- [ ] Encrypted token storage using existing `EncryptionService`

#### Phase 1: Strava Auth Model, OAuth Flow, and Registry Entry
**PR Size:** ~5–7 files

Establish the Strava package structure, auth persistence, OAuth flow endpoints, and register Strava in the integration registry so it appears in the dashboard.

**Acceptance Criteria:**
- [x] `integration_workers/strava/` package structure following isolated worker pattern
- [x] `UserStravaAuth` model in `core_shared/models/` (user_id, access_token encrypted, refresh_token encrypted, expires_at, athlete_id, strava_webhook_subscription_id)
- [x] Database migration for `user_strava_auth` table
- [x] OAuth endpoints: `POST /api/integrations/strava/oauth/authorize`, `POST /api/integrations/strava/oauth/callback` (token exchange), `DELETE /api/integrations/strava/oauth/disconnect` (token revocation + credential cleanup)
- [x] `StravaIntegrationProvider` implements registry interface: derives status from `UserStravaAuth` state
- [x] Strava panel appears in integrations dashboard with Connect/Disconnect controls
- [x] New worker is setup in CI with tests and integration tests
- [x] New worker is setup in docker.

**Required Test Coverage:**
- **Unit:** OAuth URL generation, token exchange parsing, token refresh logic, disconnect cleanup.
- **Integration:** OAuth flow with mocked Strava API, registry provider status derivation.
- **E2E:** "Connect Strava" button appears in dashboard, OAuth redirect initiates correctly.

#### Phase 2: Strava API Client
**PR Size:** ~4–6 files

Build the `StravaAPIClient` with all methods needed for activity import. This is a pure client layer with no sync logic.

**Acceptance Criteria:**
- [x] `StravaAPIClient` class using `httpx` async client with token injection
- [x] `get_athlete()` — fetch authenticated athlete profile
- [x] `list_activities(after, before, page, per_page)` — paginated activity listing
- [x] `get_activity(activity_id)` — full activity detail including `start_latlng`
- [x] `get_activity_streams(activity_id, keys)` — fetch latlng, altitude, time streams for GPX generation
- [x] Pydantic response models: `StravaAthlete`, `StravaActivity`, `StravaActivityStream`
- [x] Rate limiting: respect Strava's 100 requests/15 minutes and 1000 requests/day limits
- [x] Automatic token refresh on 401 responses: `StravaTokenService.refresh_tokens()` method + `StravaAPIClient` retry logic (moved from Phase 1 — no Phase 1 endpoints trigger 401)
- [x] Ensure code is placed appropriately in the worker according to the architecture design

**Required Test Coverage:**
- **Unit (29 tests):** response model parsing for each endpoint (11), rate limit header handling and enforcement (7), API client endpoint routing and token refresh (11).
- **Integration (7 tests):** API client with mocked Strava HTTP responses (httpx MockTransport) for each method, including error responses (401 refresh flow, 429, 500).

#### Phase 3: Webhook Subscription and Worker Shell ✅ COMPLETE
**PR Size:** ~5–7 files

Implement Strava webhook handling and the ARQ worker container for background processing.

**Acceptance Criteria:**
- [x] Webhook callback endpoint: `GET /api/integrations/strava/webhook` handles `hub.challenge` validation handshake
- [x] Webhook callback endpoint: `POST /api/integrations/strava/webhook` receives activity create/update/delete events, responds 200 within 2 seconds
- [x] Webhook events acknowledged immediately, enqueued as ARQ tasks for async processing
- [x] Webhook subscription created automatically on successful OAuth connect (Phase 1 endpoint updated)
- [x] Webhook subscription deleted on disconnect
- [x] Webhook subscription verification and forced resubscribe mechanism
- [x] `integration_workers/strava/worker.py` — ARQ worker entry point with health checks
- [x] Strava worker added to `docker-compose.yml` (follows Google worker container pattern) ✅ ALREADY EXISTS
- [x] Worker registers as `strava-worker` consumer group on Redis Stream
- [x] `integration-architecture.md` updated: add Strava worker to the integration workers section, webhook subscription pattern, and deployment topology

**Required Test Coverage:**
- **Unit (11 tests):** webhook service subscribe/unsubscribe/verify/force_resubscribe (7), worker task dispatch create/update/delete/ignore (4), stream consumer group name/patterns/event handling/stream name (4).
- **Integration (7 tests):** webhook GET validation handshake (2), webhook GET reject wrong token (1), webhook GET reject missing params (1), webhook POST activity create/update/delete (3), webhook POST non-activity ignore (1).
- **E2E:** simulated webhook delivery triggers ARQ task enqueue (verified via test Redis).

---

### ITER5-004: Strava Activity Import and Merge Review

**Objective:** Import Strava activities as journals with correct type mapping, fitness data, GPX tracks, and merge review detection.

**Strategy:** Split into 4 phases: data transformation, sync orchestration + journal creation, GPX/route storage + dedup + sync state, merge review wiring.

**Specification Reference:**
- [Part 3: Activity Import](../product-specifications/integration-architecture-and-strava-product-specification.md#activity-import)
- [Part 3: Merge Review Integration](../product-specifications/integration-architecture-and-strava-product-specification.md#merge-review-integration)
- [Part 3: GPX Track Import](../product-specifications/integration-architecture-and-strava-product-specification.md#gpx-track-import)
- [Part 3: Deduplication](../product-specifications/integration-architecture-and-strava-product-specification.md#deduplication)
- [Part 3: Sync Metadata](../product-specifications/integration-architecture-and-strava-product-specification.md#sync-metadata)

**Dependencies:**
- ITER5-003 (OAuth and API client)
- **⚠️ ITER9-003** (new activity types CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING must exist for full type mapping)
- **⚠️ ITER9-002** (KAYAKING rapids_grade field for kayaking type mapping)
- ITER7-003 Phase 1 (match candidate detection — ✅ COMPLETE)
- ITER7-004 Phases 1–2 (journal merge service — ✅ COMPLETE)

> [!IMPORTANT]
> This task can begin with basic type mapping (FITNESS-only fallback for unmapped types) before ITER9 completes, but the full activity type mapping table requires ITER9-003 and ITER9-002.

**Acceptance Criteria (task-level):**
- [x] Strava activities create journals with correct type hierarchy
- [x] Fitness data populated (distance, elevation, duration, calories, heart rate)
- [x] GPX tracks stored as Route entities when GPS data available
- [x] Elevation loss calculated from GPX altitude stream
- [x] Deduplication by `strava_activity_id`
- [x] Imported journals trigger merge review detection for same-day overlaps

#### Phase 1: Data Transformation and Type Mapping ✅ COMPLETE
**PR Size:** ~5–7 files

Pure transformation logic with no I/O or sync orchestration. Converts Strava API responses into journal domain data.

**Acceptance Criteria:**
- [x] `StravaDataTransformer` class: maps Strava activity type → journal type hierarchy per the [type mapping table](../product-specifications/integration-architecture-and-strava-product-specification.md#activity-type-mapping)
- [x] Field transformation: Strava fields → journal fields per the [data transformation table](../product-specifications/integration-architecture-and-strava-product-specification.md#data-transformation)
- [x] `GpxGenerator`: converts Strava streams (latlng, altitude, time) into GPX XML
- [x] `ElevationCalculator`: computes elevation loss from altitude stream (sum of negative deltas between consecutive points); returns null when no altitude data
- [x] Unmapped Strava activity types default to FITNESS only
- [x] Note: Pydantic response models (`StravaActivity`, `StravaActivityStream`) already exist from ITER5-003 Phase 2

**Required Test Coverage:**
- **Unit (54 tests):** 18 type mapping tests (all Strava types in mapping table + unmapped), 19 field transformation tests (all data fields + edge cases), 8 GPX generation tests (full/partial streams, empty, well-formed XML, time offsets), 9 elevation loss tests (ascending, descending, mixed, empty, null, flat, rounding). ✅ All pass.
- **Integration (7 tests):** round-trip transformation tests with realistic Strava API response fixtures covering Run, Hike, Ride, Kayaking, unmapped (Yoga), activity with streams, and activity without streams. ✅ All pass.

#### Phase 2: Sync Orchestration and Journal Creation ✅ COMPLETE
**PR Size:** ~6–8 files

Wire the transformer into the sync flow: fetch activities from Strava, transform, create outbox events, and process into journals.

**Acceptance Criteria:**
- [x] `StravaSyncService`: orchestrates full sync and single-activity sync
- [x] Full sync: fetches all historical activities (paginated) on first connection, creates `journal_event.created` outbox events for each
- [x] Webhook-triggered sync: fetches single activity by ID on webhook notification, creates outbox event
- [x] Inbound event processor handles Strava `journal_event.created` events — creates journal with FITNESS data and activity type data
- [x] Manual sync trigger: "Import Activities" button in Strava integration panel triggers full sync via ARQ task
- [x] Sync progress tracking: `SyncJob` records created for full sync and webhook-triggered sync
- [x] Delete handling: Strava `activity.delete` webhook → soft-delete or cancel the linked journal

**Required Test Coverage:**
- **Unit (19 tests):** sync orchestration logic (13 StravaSyncService tests), outbox event construction, fitness data persistence (3 processor tests), delete event handling. ✅ All pass.
- **Integration:** full sync with mocked Strava API → outbox events → journal creation in database. Webhook-triggered single activity sync. Backend integration tests all pass.
- **E2E (5 tests):** Strava panel rendering, connect OAuth redirect, sync controls visible, import triggers POST to correct endpoint. ✅ All pass.

#### Phase 3: GPX Route Storage, Deduplication, and Sync Metadata ✅ COMPLETE
**PR Size:** ~5–7 files

Add GPX track persistence, activity deduplication, and sync state tracking to the import pipeline.

**Acceptance Criteria:**
- [x] GPX tracks from `GpxGenerator` stored as `Route` entities via existing `RouteService` (route.name = activity name, route.gpx_data = generated XML)
- [x] Route linked to journal via `route.journal_id`
- [x] GPS availability check: only fetch streams and create routes when `start_latlng` is non-null
- [x] Elevation loss from `ElevationCalculator` written to `fitness_data.elevation_loss` during import
- [x] Deduplication: `strava_activity_id` in `fitness_data` checked before import — existing activity treated as update, not duplicate create
- [x] `SyncMetadata` records: `integration_source="strava"`, `internal_id`=journal ID, `external_id`=Strava activity ID, `version_hash`=hash of full activity `model_dump_json()` for robust change detection
- [x] Update flow: when Strava activity is updated (webhook), fetch latest data and update existing journal + route

**Required Test Coverage:**
- **Unit:** GPS availability check, deduplication logic, sync metadata hash calculation, update-vs-create decision. ✅ 29 backend processor tests, 142 worker tests pass.
- **Integration:** import activity with GPS → verify Route created with GPX data. Re-import same activity → verify update not duplicate. Import activity without GPS → verify no Route, elevation_loss is null. ✅ 6/6 integration tests pass.
- **E2E:** import activity with GPS track, verify route visible on journal detail page. ✅ 1 E2E test passes (strava-route-display.spec.ts).


#### Phase 4: Merge Review Queue Integration ✅ COMPLETE
**PR Size:** ~3–5 files

Wire Strava imports into the existing merge detection and review pipeline.

**Acceptance Criteria:**
- [x] Imported Strava journals emit `journal_review.detect_matches` events (same pattern as Google Calendar flow)
- [x] `MatchCandidateDetector` finds same-day overlapping journals and creates `ReviewItem` entries
- [x] Multi-activity scenario: second Strava activity on same day flagged as potential match for first
- [x] Cross-integration scenario: Strava activity flagged as match for existing Google Calendar EVENT journal
- [x] User resolves via existing review queue UI (merge, dismiss, keep separate)
- [x] On merge: fitness data, GPX tracks (routes), and external links preserved on target journal via existing `JournalMergeService._move_routes` and `_merge_type_data`

**Required Test Coverage:**
- **Unit:** match detection for Strava-sourced journals, cross-integration matching rules. ✅
- **Integration:** import two overlapping Strava activities → verify review items created. Import activity matching existing calendar event → verify cross-integration review item. ✅
- **E2E:** import overlapping activity, see review queue item, merge via existing UI, verify combined fitness data and routes. ✅

---

### ITER5-005: Participant Detection and External System Links

**Objective:** Match Strava athletes to contacts, support manual Strava-to-contact mapping, and show external system links on journal/contact detail pages.

**Strategy:** Split into 3 phases: automatic participant detection backend, manual mapping UI, then external link display. Participant detection is backend-first since the UI for manual mapping is a secondary flow.

**Specification Reference:**
- [Part 3: Participant Detection](../product-specifications/integration-architecture-and-strava-product-specification.md#participant-detection)
- [Part 3: Manual Strava-to-Contact Mapping](../product-specifications/integration-architecture-and-strava-product-specification.md#manual-strava-to-contact-mapping)
- [Part 4: External System Links](../product-specifications/integration-architecture-and-strava-product-specification.md#part-4-external-system-links-on-journals--contacts)

**Dependencies:** ITER5-004 (journals must exist to add participants and links to)

**Acceptance Criteria (task-level):**
- [x] Strava athlete names auto-matched to contacts during import
- [x] Manual Strava athlete → contact mapping UI
- [x] External system links displayed on journal and contact detail pages
- [ ] External links available through MCP

#### Phase 1: Automatic Participant Detection ✅ COMPLETE
**PR Size:** ~5–7 files

Backend-only: detect Strava athletes, match to contacts, add as participants during import.

**Acceptance Criteria:**
- [x] Strava sync pipeline extracts athlete names from activity data (`athlete` field, group activity participants)
- [x] Name-based contact search using existing contact search infrastructure (MeiliSearch or SQL ILIKE)
- [x] Confidence threshold: only add participant when name match is unambiguous (exact or near-exact match)
- [x] Matched contacts added as PARTICIPANT on the journal via existing `JournalContactRelationship` system
- [x] No participant added if no confident match (conservative — no false positives)
- [x] Migration creates `strava_athlete_mappings` table: `user_id`, `strava_athlete_id`, `strava_athlete_name`, `contact_id`, `created_at`
- [x] Mapping table checked before name search — manual mappings (Phase 2) take priority over name matching
- [x] All future imports for a mapped athlete automatically add the contact as participant

**Required Test Coverage:**
- **Unit:** name matching confidence logic, mapping table lookup priority, athlete name extraction from activity data. ✅
- **Integration:** import activity with known athlete name → verify PARTICIPANT relationship created. Import with unknown athlete → verify no participant. Import with ambiguous match → verify no participant. ✅

#### Phase 2: Manual Strava Athlete-to-Contact Mapping UI ✅ COMPLETE
**PR Size:** ~4–6 files

Add UI for manually mapping a Strava athlete to a contact when automatic detection fails.

**Acceptance Criteria:**
- [x] Journal detail page: when a Strava-imported journal has unmatched athletes, show "Link participant" action
- [x] Mapping dialog: searchable contact combobox to select a contact for a given Strava athlete
- [x] `POST /api/integrations/strava/athlete-mappings` endpoint: create/update mapping
- [x] `GET /api/integrations/strava/athlete-mappings` endpoint: list current mappings
- [x] `DELETE /api/integrations/strava/athlete-mappings/{id}` endpoint: remove mapping
- [x] Integration settings panel: view and manage all Strava athlete mappings
- [x] After creating a mapping, retroactively add the contact as PARTICIPANT to existing journals with that athlete

**Required Test Coverage:**
- **Unit:** mapping dialog component, mapping CRUD API schema validation.
- **Integration:** create mapping → verify participant retroactively added to existing journals. Delete mapping → verify no effect on existing relationships.
- **E2E:** open Strava journal with unmatched athlete, create manual mapping, verify participant appears.

#### Phase 3: External System Link Display on Journals and Contacts ✅ COMPLETE
**PR Size:** ~5–7 files

Show data provenance on journal and contact detail pages with clickable links to external records.

**Acceptance Criteria:**
- [x] Journal detail page: secondary metadata area shows external system links
- [x] Contact detail page: secondary metadata area shows external system links
- [x] Icons for each system: Google Calendar, Google Contacts, Strava
- [x] Clickable link to external record where URL constructable:
  - Strava: `https://www.strava.com/activities/{strava_activity_id}`
  - Strava Athelete: (Format TBC)
  - Google Calendar: `https://calendar.google.com/calendar/event?eid={base64_encoded_id}`
  - Google Contacts: `https://contacts.google.com/person/{resource_name}`
- [x] Icon shown without link when URL cannot be constructed (missing external ID)
- [x] Multiple links shown when journal linked to multiple systems (e.g. Google Calendar + Strava after merge)
- [x] Data derived from existing records — no new tables: `JournalExternalEventLink`, `fitness_data.strava_activity_id`, `SyncMetadata`
- [x] `GET /api/journals/{id}/external-links` and `GET /api/contacts/{id}/external-links` endpoints (or embedded in existing detail responses)

**Required Test Coverage:**
- **Unit:** URL construction helpers for each external system (including edge cases: missing ID, malformed resource name).
- **Integration:** API/component tests for journals with Google-only, Strava-only, both, and neither.
- **E2E:** view Strava-imported journal → verify Strava link. View Google Calendar journal → verify Google link. View merged journal → verify both links.

---

### ITER5-006: MCP Parity for Strava Data and External Links

**Objective:** Ensure all Strava-imported data and external system links are available through MCP tools.

**Strategy:** Split into 2 phases: journal MCP extensions, then contact MCP extensions and integration-level tools.

**Specification Reference:**
- [Product Spec — MCP Parity](../product-specifications/integration-architecture-and-strava-product-specification.md#mcp-parity)
- [Journals Product Specification — MCP and AI-Agent Parity](../product-specifications/journals-product-specification.md#mcp-and-ai-agent-parity)

**Dependencies:** ITER5-005 (external links and participant data must exist)

**Acceptance Criteria (task-level):**
- [ ] MCP journal responses include external system links (source, URL)
- [ ] MCP contact responses include external system links
- [ ] MCP `search_journals` can filter by integration source
- [ ] Strava fitness data fully exposed in MCP journal responses
- [ ] Integration status available via MCP

#### Phase 1: Journal MCP Extensions
**PR Size:** ~3–5 files

Extend journal MCP tools to include external links and integration source filtering.

**Acceptance Criteria:**
- [x] `get_journal` MCP response includes `external_links` array with `{source, url, external_id}` for each linked system
- [x] `search_journals` supports `integration_source` filter parameter (e.g. `integration_source=strava` returns only Strava-imported journals)
- [x] Fitness data fields verified complete in MCP journal response (distance, elevation_gain, elevation_loss, duration, calories, heart_rate_avg, heart_rate_max, strava_activity_id)
- [x] External links for journals with multiple sources (Google + Strava) correctly returned

**Implementation Notes:**
- `ExternalLinkSchema` added to `schemas.py` with `source`, `url` (nullable), `external_id` fields
- `JournalConverter.to_response` extended to accept and convert `ExternalLinkInfo` objects
- `_fetch_journal_external_links` helper fetches Strava links from `journal_fitness_data` and Google Calendar links from `journal_external_event_links`
- `_parse_integration_source_filter` validates `strava` and `google_calendar` sources
- `_fetch_journal_ids_by_integration_source` uses SQL-level filtering for efficient source-based queries
- Reuses `build_journal_external_links` from `external_link_helpers.py` for URL construction

**Required Test Coverage:**
- **Unit:** MCP response schema includes external links fields, integration source filter validation.
- **Integration:** MCP test for journal with Strava link, journal with Google link, search by integration source.

#### Phase 2: Contact MCP Extensions and Integration Status Tool
**PR Size:** ~3–5 files

Extend contact MCP tools and add integration management tools.

**Acceptance Criteria:**
- [ ] `get_contact` MCP response includes `external_links` array with `{source, url, external_id}`
- [ ] `list_integrations` MCP tool returns same data as `GET /api/integrations` (already added in ITER5-002 Phase 1 — verify Strava data is complete)
- [ ] `trigger_sync` MCP tool: trigger a sync for a specific integration (e.g. Strava full sync)
- [ ] Strava athlete-to-contact mappings accessible via MCP (query by contact or by athlete ID)

**Required Test Coverage:**
- **Unit:** contact external links schema, trigger_sync parameter validation.
- **Integration:** MCP test for contact with Google link, trigger_sync for Strava, athlete mapping query.

---

## Delivery Notes

This iteration is structured so that **Tasks 1–2 (infrastructure) can proceed immediately** while iteration 9 work continues in parallel. **Tasks 3–6 (Strava) require iteration 9 activity types** for the full type mapping, but Task 3 (OAuth) and Task 4 Phase 1 (transformation) can begin early with FITNESS-only fallback.

The infrastructure tasks (1–2) are high-value standalone deliverables that benefit the Google integration and future integrations regardless of Strava timing.

### Phase Summary

| Task | Phases | Total est. PRs |
|---|---|---|
| ITER5-001: Redis Streams Event Bus | 5 | 5 |
| ITER5-002: Pluggable Integration Dashboard | 3 | 3 |
| ITER5-003: Strava OAuth & API Client | 3 | 3 |
| ITER5-004: Activity Import & Merge Review | 4 | 4 |
| ITER5-005: Participants & External Links | 3 | 3 |
| ITER5-006: MCP Parity | 2 | 2 |
| **Total** | **20** | **20** |

