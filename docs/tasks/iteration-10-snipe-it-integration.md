# Iteration 10: Snipe-IT Integration

**Status:** 🟢 IN PROGRESS
**Dependencies:** Iteration 5 (Integration Architecture, Generic Dashboard), Iteration 9 (Gear Items, GEAR_MAINTENANCE)
**Goal:** Deliver a bidirectional integration with a self-hosted Snipe-IT instance for gear and maintenance tracking, establishing Snipe-IT as the authoritative source for equipment data while linking it to journal activities via a new GEAR_USAGE journal type.

## Overview

This iteration delivers the approved [Snipe-IT Integration Product Specification](../product-specifications/snipe-it-integration-product-specification.md) in incremental, shippable slices. Each task delivers end-to-end functionality across backend, frontend, and MCP where applicable.

The work builds on the existing Redis Streams event bus and pluggable integration UI from Iteration 5, and the gear item entity and maintenance tracking from Iteration 9.

## Reference Documents

- **[Snipe-IT Integration Product Specification](../product-specifications/snipe-it-integration-product-specification.md)** — approved product behaviour for this iteration
- **[Integration Architecture](../architecture/integration-architecture.md)** — event-driven integration patterns
- **[Iteration 5: Integration Architecture & Strava](./iteration-5-integration-architecture-and-strava.md)** — the foundation for the event bus and dashboard
- **[Iteration 9: Outdoor Logbook](./iteration-9-outdoor-logbook.md)** — the foundation for gear items and maintenance

## Delivery Rules

1. **Tests first:** write failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks pass.
3. **Reviewable PRs:** keep each PR to roughly ≤ 10 files where practical.
4. **Full vertical slice:** each task delivers backend, frontend, and MCP together.
5. **Every task is shippable:** no task may rely on a later task to restore broken behaviour.

## Dependency and Parallelisation Notes

- **Task 1 (Infrastructure & Auth)** can begin once Iteration 5's generic integrations dashboard is complete. It does not strictly require Iteration 9.
- **Task 2 & 3 (Gear Item Sync)** requires Iteration 9's Gear Items foundation.
- **Task 4 (Maintenance Sync)** requires Iteration 9's GEAR_MAINTENANCE journal type.
- **Task 5 (Gear Usage)** is independent of Iteration 9's outdoor types but introduces a new journal type, so it follows the standard type addition pattern.

---

## Task Breakdown

### ITER10-001: Snipe-IT Worker Infrastructure, Auth, and Registry
**Objective:** Establish the Snipe-IT integration worker, implement OAuth (Passport) authentication, and register Snipe-IT in the generic integrations dashboard.

**Specification Reference:**
- [Part 1: Authentication & Configuration](../product-specifications/snipe-it-integration-product-specification.md#part-1-authentication--configuration)
- [Integration Architecture — Worker Pattern](../architecture/integration-architecture.md)

**Acceptance Criteria (task-level):**
- [x] `integration_workers/snipeit/` package structure created.
- [ ] `UserSnipeItAuth` model handles tokens and user mapping.
- [x] Integration registry includes Snipe-IT.

#### Phase 1: Worker Package and Registry UI ✅ COMPLETE
**PR Size:** ~5-7 files
Create the worker scaffold and integrate with the existing pluggable dashboard.
**Acceptance Criteria:**
- [x] `integration_workers/snipeit` package created following standard worker architecture.
- [x] `SnipeItIntegrationProvider` implements the integration registry interface.
- [x] Settings modal added to the frontend integrations dashboard for configuring Base URL and mapping the user.
**Required Test Coverage:**
- **Unit:** Registry returns correct metadata. ✅
- **E2E:** Settings modal opens and submits Base URL cleanly. ✅

#### Phase 2: Database Models and OAuth Connect Flow ✅ COMPLETED
**PR Size:** ~5-7 files
Implement the OAuth 2.0 connection using the Base URL from Phase 1.
**Acceptance Criteria:**
- [x] Migration creates `user_snipe_it_auth` table (encrypted tokens, user ID mapping).
- [x] OAuth connect/callback endpoints implemented in the main backend, pointing to the dynamic Snipe-IT Base URL.
- [x] Disconnect flow removes the database record.
**Required Test Coverage:**
- **Unit:** Token encryption and state parameter generation.
- **Integration:** Auth endpoints handle successful/failed token exchanges.

#### Phase 3: Webhook Communication & Stream Processing
- [x] Implement `POST /api/integrations/snipeit/webhook` to accept Snipe-IT webhooks
  - [x] Fast immediate response to caller
  - [x] Transform payload and publish to `pms:domain-events` Redis stream
- [x] Create `SnipeItWorkerStreamConsumer` within the worker container
  - [x] Register on stream using `snipeit-worker` consumer group
  - [x] Acknowledge events post-processing
- [x] Add worker lifecycle hooks to manage the stream consumer task
- [x] Testing:
  - [x] Unit test: Webhook endpoint accepts payload and publishes to stream
  - [x] Integration test: Webhook endpoint successfully publishes to the Redis stream messages.

### ITER10-002: Gear Item Import & Periodic Sync (Snipe-IT → App)
**Objective:** Sync assets from Snipe-IT into the personal management system's `gear_items` table. Snipe-IT is the Source of Truth.

**Specification Reference:**
- [Part 2: Gear Items Sync](../product-specifications/snipe-it-integration-product-specification.md#part-2-gear-items-sync-two-way)

**Acceptance Criteria (task-level):**
- [ ] Gear items populated in app from Snipe-IT.
- [x] Webhooks keep items in sync.

#### Phase 1: API Client and Data Transformation ✅ COMPLETE
**PR Size:** ~5-7 files
Implement the external API communication layer and map models.
**Acceptance Criteria:**
- [x] `SnipeItAPIClient` configured with OAuth tokens can GET assets by user ID.
- [x] Transformer converts a Snipe-IT Asset payload into a `GearItem` entity.
- [x] Rate limiting is handled and transient errors surface appropriately for upstream retry logic
**Required Test Coverage:**
- **Unit:** Transformer handles missing optional fields and type coercion correctly. ✅

#### Phase 2: Initial Full Sync Process ✅ COMPLETED
**PR Size:** ~6-8 files
Handle batch importing when the user connects the integration.
**Acceptance Criteria:**
- [x] Worker ARQ job triggered on successful connection to fetch all relevant assets.
- [x] Import is resilient and batched like the Strava and Google Integrations
- [x] Fetched assets are upserted into `gear_items`.
- [x] `SyncMetadata` tracks the mapping between `gear_item.id` and Snipe-IT Asset ID.
**Required Test Coverage:**
- **Integration:** API mock returns multiple assets, DB reflects accurate creation/updates.

#### Phase 3: Webhook Processing
**PR Size:** ~5-7 files
Process incoming webhooks to keep gear items up to date incrementally.
**Acceptance Criteria:**
- [x] Worker processes asset creation/update events from the stream.
- [x] Corresponding `GearItem` is upserted or created.
**Required Test Coverage:**
- **Unit:** Correctly processes webhook payload structure.
- **Integration:** Stream event results in updated `gear_items` row.

### ITER10-003: Gear Item Export (App → Snipe-IT)
**Objective:** Enable two-way sync for gear item edits. Changes made in the app sync back to Snipe-IT.

**Specification Reference:**
- [Part 2: Gear Items Sync](../product-specifications/snipe-it-integration-product-specification.md#part-2-gear-items-sync-two-way)

**Acceptance Criteria (task-level):**
- [x] App edits to gear items are sent to Snipe-IT.

#### Phase 1: Outbox Event Publishing
**PR Size:** ~4-6 files
Emit events when gear items change locally.
**Acceptance Criteria:**
- [x] Core backend emits a `GearItemUpdated` domain event when a gear item is modified.
**Required Test Coverage:**
- **Integration:** Gear Item update endpoint successfully writes to the outbox.

#### Phase 2: Export Consumer and API PATCH
**PR Size:** ~6-8 files
Consume the local event and push it to the remote API.
**Acceptance Criteria:**
- [x] `SnipeItAPIClient` implements the PATCH method for assets.
- [x] Worker consumes `GearItemUpdated`, checks `SyncMetadata`, and updates the Snipe-IT asset.
- [x] Conflict resolution: If version hash mismatches, Snipe-IT wins and local update is skipped/overwritten on next inbound sync.
**Required Test Coverage:**
- **Integration:** Consumed event results in correct API mock call.

### ITER10-004: Gear Maintenance Sync (Two-Way)
**Objective:** Sync Snipe-IT asset maintenance records to and from the `GEAR_MAINTENANCE` journal type.

**Specification Reference:**
- [Part 3: Asset Maintenance Sync](../product-specifications/snipe-it-integration-product-specification.md#part-3-asset-maintenance-sync-two-way)
- [Outdoor Logbook: GEAR_MAINTENANCE](../product-specifications/outdoor-logbook-product-specification.md#gear_maintenance)

**Acceptance Criteria (task-level):**
- [x] Snipe-IT maintenance records populate as `GEAR_MAINTENANCE` journals.
- [x] Local `GEAR_MAINTENANCE` creations push to Snipe-IT.

#### Phase 1: Snipe-IT to App Sync (Inbound) ✅ COMPLETE
**PR Size:** ~8-10 files
Pull remote maintenance and map to journals.
**Acceptance Criteria:**
- [x] `SnipeItAPIClient` can fetch maintenance records.
- [x] Worker transforms maintenance records into `journal_event.created`/`updated` outbox events for `GEAR_MAINTENANCE`.
- [x] Inbound processor handles the events and creates the journals.
- [x] Maintenance type string mappings handled gracefully.
**Required Test Coverage:**
- **Integration:** Simulated worker event successfully creates a `GEAR_MAINTENANCE` journal in the database. ✅

#### Phase 2: App to Snipe-IT Sync (Outbound) ✅ COMPLETE
**PR Size:** ~6-8 files
Push local maintenance to the remote API.
**Acceptance Criteria:**
- [x] Worker listens for `JournalCreated` and `JournalUpdated` where type is `GEAR_MAINTENANCE`.
- [x] Worker pushes a new or updated maintenance record to Snipe-IT.
- [x] Deleting a `GEAR_MAINTENANCE` journal deletes the record it pushed and removes its sync and claim rows.
- [x] Deleting a journal **imported** from Snipe-IT deletes the record it came from, named on the deletion event since an import's sync row names no journal.
- [x] A record no live journal holds is imported as a new journal rather than hidden as unchanged or failing every sync.
**Required Test Coverage:**
- **Integration:** Local journal creation results in an API mock call to create the maintenance record in Snipe-IT. ✅
- **Integration:** Deleting a pushed journal deletes its Snipe-IT record; a journal with only a claim posts nothing. ✅
- **Integration:** Deleting an imported journal deletes its record, keeps a forbidden one's row, and never deletes a record a live journal holds. ✅
- **Integration:** A record whose journal is gone is imported again, unchanged or edited; one whose create is still pending waits. ✅

### ITER10-005: Gear Usage Journal Type and Checkouts
**Objective:** Introduce the `GEAR_USAGE` journal type to record gear being used, syncing outbound to Snipe-IT as an asset checkout.

**Specification Reference:**
- [Part 4: Gear Usage & Checkouts](../product-specifications/snipe-it-integration-product-specification.md#part-4-gear-usage--checkouts)

**Acceptance Criteria (task-level):**
- [ ] `GEAR_USAGE` journal type implemented.
- [ ] Journal creation triggers a checkout in Snipe-IT.

#### Phase 1: Backend Domain for GEAR_USAGE
**PR Size:** ~7-9 files
Create the foundational data model for the new type.
**Acceptance Criteria:**
- [x] Migration adds `journal_gear_usage_data` table.
- [x] `GEAR_USAGE` added to `JournalType` enum (no dependencies).
- [x] `GearUsageData` entity, repository, and JSON API schemas added to `core_shared` and `backend`.
**Required Test Coverage:**
- **Unit/Integration:** Full CRUD testing for the new journal type data.

#### Phase 2: Frontend Editor for GEAR_USAGE ✅ COMPLETED
**PR Size:** ~6-8 files
Build the user interface for logging gear usage.
**Acceptance Criteria:**
- [x] `GearUsageTypeEditor` component created.
- [x] Includes gear item selector.
- [x] Includes date pickers for checkout buffer dates (defaulting to parent journal dates).
- [x] **Crucial:** The buffer dates UI is conditionally enabled/visible only when the Snipe-IT integration is connected.
- [x] Added to journal creation/editing forms.
**Required Test Coverage:**
- **E2E:** Can successfully create a journal entry with the `GEAR_USAGE` type via the UI, and buffer dates behave conditionally based on integration status.

#### Phase 3: Snipe-IT Checkout Sync
**PR Size:** ~5-7 files
Sync the usage event to Snipe-IT.
**Acceptance Criteria:**
- [x] Worker consumes `JournalCreated` events containing `GEAR_USAGE` data.
- [x] Worker pushes a checkout request to the Snipe-IT API for the specified dates and mapped user.
- [x] Migration adds `snipeit_checkout` to the `integration_source` check constraint.
**Required Test Coverage:**
- [x] **Unit:** API client `checkout_asset` method (4 tests).
- [x] **Unit:** Sync service `push_checkout_create` method (6 tests).
- [x] **Unit:** Stream consumer routes GEAR_USAGE events to checkout sync (2 tests).
- [x] **Integration:** Consumed event results in a checkout API call (3 tests).

#### Phase 4: Snipe-IT Check-in (Asset Return)
**PR Size:** ~8-10 files
Return assets to Snipe-IT when the usage period ends. Snipe-IT does not auto-check-in
at `expected_checkin`, so without this an asset stays checked out forever.
**Acceptance Criteria:**
- [x] `SnipeItAPIClient.checkin_asset` posts to `POST /hardware/{id}/checkin`.
- [x] `SnipeItSyncService.push_checkin_create` returns the asset, resolving it from the
  recorded `snipeit_checkout` sync metadata so it still works after the journal is deleted.
- [x] Check-in is idempotent via a `snipeit_checkin` `SyncMetadata` row.
- [x] Migration adds `snipeit_checkin` to the `integration_source` check constraint.
- [x] Triggers: journal deletion (`JournalDeleted`), journal update reconcile, immediate
  check-in on create when the period is already past, and a periodic sweep cron.
**Required Test Coverage:**
- [x] **Unit:** API client `checkin_asset` method (4 tests).
- [x] **Unit:** Sync service `push_checkin_create` + immediate-on-create (6 tests).
- [x] **Unit:** Stream consumer routes JournalDeleted/JournalUpdated to check-in (3 tests).
- [x] **Integration:** Check-in lifecycle, post-deletion resolution, immediate-on-create,
  idempotency, and the periodic sweep query (6 tests).

### ITER10-006: External Links and MCP Parity
**Objective:** Surface Snipe-IT external links in the UI and ensure all capabilities are accessible via MCP.

**Specification Reference:**
- [Part 5: UI & Dashboard Integration](../product-specifications/snipe-it-integration-product-specification.md#part-5-ui--dashboard-integration)

**Acceptance Criteria (task-level):**
- [x] Deep links available in UI.
- [x] AI agent can fully utilize new features.

#### Phase 1: UI External Links ✅ COMPLETED
**PR Size:** ~4-6 files
Add contextual links.
**Acceptance Criteria:**
- [x] Gear Item detail/management page shows an external link to the Snipe-IT asset. (Handled via API as there is no dedicated view yet)
- [x] Journal detail page shows an external link for `GEAR_MAINTENANCE` and `GEAR_USAGE` entries.
**Required Test Coverage:**
- **E2E:** External links are present and correctly formed in the UI when sync metadata exists. ✅

#### Phase 2: MCP Parity ✅ COMPLETED
**PR Size:** ~3-5 files
Expose functionality to the AI assistant.
**Acceptance Criteria:**
- [x] MCP generic journal tools handle `GEAR_USAGE` creation and updates.
- [x] `get_journal` and gear item retrieval tools include the Snipe-IT external link in the prompt text.
**Required Test Coverage:**
- **Unit:** AI prompt templates successfully format the external links. ✅

## Success Criteria
- Bidirectional sync of Gear Items working reliably with Snipe-IT as the source of truth.
- Maintenance records stay synchronized in both directions.
- Gear usage records trigger checkouts in Snipe-IT.
- Generic integrations dashboard handles the custom Base URL and User mapping cleanly.
- All integration actions gracefully handle API rate limits or network issues with retries.
