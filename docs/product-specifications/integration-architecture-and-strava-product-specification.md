# Integration Architecture & Strava Product Specification

## Overview

This document defines the target product behaviour for refactoring the integration event architecture and building the Strava integration. It is a product specification rather than a technical design.

This specification supersedes `docs/tasks/iteration-5-strava-integration.md`. Where that earlier document conflicts with this specification, this specification takes precedence. Non-conflicting detail from iteration 5 (such as OAuth flow steps, API client methods, and ARQ worker lifecycle) should be treated as supplementary.

This specification assumes iteration 9 (Outdoor Logbook) is complete before Strava sync work begins, as the fitness and outdoor activity type hierarchy must be in place. The integration architecture refactoring can proceed independently and should be completed first.

## Reference and Alignment

This specification evolves and refines behaviour described in:

- `docs/architecture/integration-architecture.md`
- `docs/tasks/iteration-5-strava-integration.md`
- `docs/product-specifications/journals-product-specification.md`
- `docs/product-specifications/outdoor-logbook-product-specification.md`

Where earlier documents assume narrower integration behaviour, this specification should be treated as the product-level refinement.

## Product Goals

The integration architecture and Strava integration should:

1. Replace the current direct-dispatch outbox processor with a proper event bus so that a single domain event can be consumed by multiple independent systems without coupling.
2. Make integrations pluggable — the main backend should not contain integration-specific logic for sync UI, resync controls, or event routing.
3. Enable one-way import of Strava fitness activities into the journal system with automatic merge review for overlapping entries.
4. Present a unified integrations experience where each connected service has consistent UI patterns.
5. Show external system links as metadata on journals and contacts so the user always knows where data came from.

## Product Principles

1. **Single event, multiple consumers:** A domain event is published once. Each consumer (search indexer, AI summary, Google worker, Strava worker) decides independently whether to process it.
2. **Journal is the canonical record:** Strava imports create or merge into journals. The journal is always the source of truth. Strava data enriches but never overrides manual edits without user review.
3. **Pluggable integrations:** Adding a new integration should not require modifying the main backend's event routing, API controllers, or UI page layout. Integrations declare their capabilities and the system renders them.
4. **Conservative merge:** When Strava data overlaps with an existing journal, the system surfaces a review item. It does not auto-merge silently.
5. **AI-first:** All Strava-imported data and external system links are available through MCP.

---

## Part 1: Integration Event Architecture

### Problem Statement

The current architecture has three problems:

1. **No broadcast:** ARQ does not support publishing one event to multiple consumers. The outbox processor manually routes each event type to specific handlers, then separately broadcasts to integration workers. This means adding a new consumer requires modifying the outbox processor.
2. **Integration logic leakage:** Google-specific sync UI, resync controls, and event processing logic is hard-coded into the main backend's outbox processor (`_process_contact_event`, `_process_journal_sync_event`) and API controllers (`/integrations/google/*`).
3. **Duplicated event paths:** Domain events like `JournalCreated` are processed by the search indexer directly, then separately broadcast to integration workers via ARQ. This creates two event paths for the same logical event.

### Target Architecture: Event Bus via Redis Streams

The system already uses Redis (for ARQ). Redis Streams with consumer groups provides the event bus with minimal additional infrastructure.

#### How it works

1. **Outbox relay:** A background process reads unprocessed events from the PostgreSQL outbox table and publishes them to a Redis Stream (e.g. `domain-events`). Once published, the outbox row is marked as relayed.
2. **Consumer groups:** Each consumer system registers a Redis Streams consumer group:
   - `search-indexer` — processes search indexing events
   - `summary-generator` — processes AI summary refresh events
   - `google-worker` — processes contact sync, journal sync, and tag events
   - `strava-worker` — processes journal events (for outbound awareness, future use)
   - Additional consumers can be added without modifying the relay
3. **Independent consumption:** Each consumer group reads events independently and acknowledges them at its own pace. If one consumer is down, others are unaffected. Failed events can be retried per-consumer using Redis Streams pending entries.
4. **Event filtering:** Each consumer filters events by `event_type` prefix or pattern. Only events relevant to the consumer are processed; others are acknowledged and skipped.

#### Why Redis Streams over alternatives

- **Already in the stack:** Redis 8 is deployed. No new infrastructure.
- **Consumer groups:** Native support for multiple independent consumers with at-least-once delivery.
- **Persistence:** AOF is already enabled (`--appendonly yes`). Events survive Redis restarts.
- **Python support:** `redis-py` has mature async support for Streams.
- **Simplicity:** No new container, no new dependency, no new operational burden.

NATS JetStream was considered but rejected because it would add a new infrastructure component for a single-user system where Redis already provides sufficient messaging capabilities.

#### What this replaces

- The hard-coded event routing in `OutboxProcessor._process_single_event` is replaced by the relay + consumer group pattern.
- The `TaskQueueService.broadcast_journal_event` / `broadcast_tag_event` methods are replaced by consumers reading from the stream.
- ARQ remains for long-running tasks (sync jobs, webhook processing) but is no longer used for event fan-out.

#### Outbox pattern preserved

The outbox table and transactional writes remain unchanged. The relay process is the only reader of the outbox. This preserves the atomicity guarantee: domain events are written in the same database transaction as the business operation.

#### Inbound events from integrations

Integration workers that need to push data into the main system (e.g. Google Calendar → Journal, Strava → Journal) continue to write to the outbox table. These inbound events are relayed to the same Redis Stream and processed by the appropriate consumer (the main backend's inbound event processor). This keeps the pattern consistent for both directions.

The inbound event processor in the main backend is a consumer group (`inbound-processor`) that handles:
- `contact.*` events (from Google Contacts worker)
- `journal_event.*` events (from Google Calendar worker, future Strava worker)
- `journal_review.*` events (match detection)
- `ContactSummaryRefreshRequested` events

This processor replaces the current hard-coded routing in `OutboxProcessor._process_single_event` but performs the same operations.

---

## Part 2: Pluggable Integration UI

### Problem Statement

The current integrations page (`frontend/src/app/integrations/page.tsx`) is a monolithic Google-specific page. Adding Strava would require duplicating the same patterns (connect/disconnect, sync controls, sync history, health) with Google-specific component names replaced by Strava-specific ones.

### Target Behaviour

The integrations page should be a generic dashboard that renders integration panels dynamically.

#### Backend integration registry

The main backend exposes an API endpoint that returns the list of available integrations and their capabilities:

```
GET /api/integrations
```

Each integration declares:
- `id` — unique identifier (e.g. `google`, `strava`)
- `name` — display name
- `status` — connection status (connected, disconnected, error, token_expired)
- `capabilities` — list of supported features (e.g. `contacts_sync`, `calendar_sync`, `activity_import`)
- `sync_summary` — last sync time, sync count, error summary
- `needs_reauth` / `needs_reconsent` — boolean flags

#### Frontend integration panels

The integrations page renders a panel for each integration using shared components:
- **Connection controls:** Connect/disconnect buttons, OAuth flow handling
- **Sync controls:** Per-capability sync buttons (e.g. "Sync Contacts", "Sync Calendar", "Import Activities")
- **Sync history:** Recent sync jobs for this integration
- **Health status:** Worker health and error summary

Each integration panel is a composition of shared components configured by the integration's declared capabilities. No integration-specific page components should exist in the main page layout.

#### Integration-specific settings

Each integration may have settings (e.g. which Google Calendars to sync, Strava activity type mapping preferences). These should be rendered as sub-pages or modals accessible from the integration panel, not hard-coded into the main integrations page.

---

## Part 3: Strava Integration

### Scope

The Strava integration provides one-way import of fitness activities from Strava into the journal system.

### In Scope

- Strava OAuth 2.0 authentication with automatic token refresh
- Strava webhook registration for real-time activity notifications
- Activity data import (incremental sync via webhook, full sync on first connection)
- Automatic FITNESS + activity type journal creation from Strava activities
- GPX track import via Strava Streams API, stored as Route entities
- Merge review queue integration for duplicate/overlap detection
- Participant detection from Strava activity athletes
- Manual Strava ID-to-contact mapping
- Integration management UI within the generic integrations dashboard
- Strava activity link stored as external system metadata on journals
- MCP parity for Strava-linked journal data

### Out of Scope

- Write-back to Strava (title, gear, description sync back) — flagged as future
- Strava segment data import
- Strava social features (kudos, comments)
- Two-way sync of any kind

### Strava OAuth & Authentication

The Strava OAuth flow follows the same pattern as Google OAuth:

1. User clicks "Connect Strava" in the integrations dashboard
2. Redirect to Strava authorization URL with `activity:read_all` scope
3. User authorizes the application
4. Strava redirects back with authorization code
5. Exchange code for access token and refresh token
6. Store encrypted tokens in database
7. Register webhook subscription for real-time activity notifications

Token refresh is automatic on 401 responses. Webhook subscription is re-established if it lapses.

Disconnecting Strava revokes the OAuth token, removes the webhook subscription, and clears the stored credentials. Imported journals and their data remain.

### Activity Import

#### Sync triggers

- **Real-time (webhooks):** Strava supports webhook push subscriptions via the `push_subscriptions` API. Each application gets one subscription that covers all authorised athletes. When an activity is created, updated (title, type, or privacy), or deleted, Strava POSTs an event payload (`object_type`, `aspect_type`, `object_id`, `owner_id`) to the callback URL. The callback must respond with HTTP 200 within 2 seconds; failed deliveries are retried up to 3 times. On receiving a webhook, the Strava worker fetches the full activity detail and creates an outbox event. Webhook subscription requires a publicly accessible callback endpoint with a validation handshake (`hub.challenge` echo).
- **Full sync:** On first connection, the worker fetches all historical activities (paginated). The user can also trigger a full sync manually.
- **Manual:** The user can trigger a sync from the integrations dashboard.

#### Activity type mapping

Strava activity types map to journal types as follows:

| Strava Type | Journal Types |
|-------------|--------------|
| Run | JOGGING, FITNESS |
| TrailRun | JOGGING, OUTDOOR_ACTIVITY, FITNESS |
| Hike | BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS |
| Walk | BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS |
| Ride | FITNESS |
| MountainBikeRide | OUTDOOR_ACTIVITY, FITNESS |
| Swim | FITNESS |
| Kayaking | KAYAKING, OUTDOOR_ACTIVITY, FITNESS |
| Canoeing | CANOEING, OUTDOOR_ACTIVITY, FITNESS |
| RockClimbing | CLIMBING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS |
| NordicSki | CROSS_COUNTRY_SKIING, BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS |
| AlpineSki | DOWNHILL_SKIING, OUTDOOR_ACTIVITY, FITNESS |
| Snowshoe | BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS |
| Rowing | FITNESS |
| Surfing | FITNESS |
| Yoga | FITNESS |
| Other | FITNESS |

Unmapped Strava types default to FITNESS only. The mapping should be configurable per-user in future but is fixed for the initial implementation.

#### Data transformation

Each Strava activity is transformed into journal data:

| Strava Field | Journal Field |
|-------------|--------------|
| name | title |
| description | content |
| start_date + elapsed_time | event_date_range |
| distance | fitness_data.distance (metres) |
| total_elevation_gain | fitness_data.elevation_gain |
| *(derived from GPX altitude stream)* | fitness_data.elevation_loss |
| moving_time | fitness_data.duration (seconds) |
| calories | fitness_data.calories |
| average_heartrate | fitness_data.heart_rate_avg |
| max_heartrate | fitness_data.heart_rate_max |
| id | fitness_data.strava_activity_id |

**Elevation loss** is not provided directly by the Strava API. It is calculated from the altitude stream fetched for GPX generation: the sum of all negative altitude deltas between consecutive track points. This means elevation loss is only available for activities with GPS data. For activities without GPS data, elevation loss remains null.

#### GPX Track Import

When a Strava activity has GPS data available (checked via `start_latlng` being non-null), the worker fetches the activity's streams (latlng, altitude, time) from the Strava Streams API and converts them to GPX format.

The GPX data is stored as a Route entity linked to the journal, using the existing `Route` entity and `RouteService`:
- `route.journal_id` = the created journal's ID
- `route.name` = the Strava activity name
- `route.gpx_data` = the generated GPX XML

When multiple Strava activities are merged into a single journal, each activity's GPX track becomes a separate Route on the target journal. The existing merge service's `_move_routes` method handles this correctly.

#### Deduplication

Activities are deduplicated by `strava_activity_id` stored in `fitness_data.strava_activity_id`. If an activity with the same Strava ID already exists, the import is treated as an update rather than a create.

### Merge Review Integration

When a Strava activity is imported, the system uses the existing `MatchCandidateDetector` to check for overlapping journals on the same date:

1. The Strava worker creates a `journal_event.created` outbox event with the transformed activity data.
2. The inbound event processor creates the journal.
3. The inbound event processor emits a `journal_review.detect_matches` event (same as Google Calendar flow).
4. The match detection processor finds same-day journals and runs AI similarity assessment.
5. If matches are found, `ReviewItem` entries are created for user review.
6. The user resolves matches through the existing review queue UI (merge, dismiss, or keep separate).

This reuses the entire existing merge detection and review pipeline. No Strava-specific merge logic is needed.

#### Multi-activity merge scenario

A hike may be recorded as two Strava activities (e.g. multi-day trip, recording restart). When both activities import, the match detector will flag the second activity as a potential match for the first (same date range, similar title). The user can then merge them through the review queue, combining their fitness data and GPX tracks into a single journal.

#### Merge with Google Calendar events

A Strava activity may correspond to a Google Calendar event that was already imported as an EVENT journal (e.g. "Saturday Bushwalk"). The match detector will identify the overlap via title similarity and date range. When the user merges them:
- The target journal gains FITNESS and activity type data from Strava
- The Google Calendar external event link is preserved
- The Strava reference (via `strava_activity_id`) is preserved in fitness data
- Future Google Calendar updates continue to sync to this journal

This scenario already works through the existing merge service. The merge service's `_merge_type_data` handles combining type-specific data, and `_move_external_links` preserves external references.

### Participant Detection

Strava activities may include other athletes (from group activities or segment efforts). The Strava worker should:

1. Extract athlete names from the Strava activity's `athlete` field and any `segment_efforts` with other athletes.
2. Match athlete names against existing contacts using a name-based search.
3. If a confident name match is found, add the contact as a PARTICIPANT on the journal via the existing `JournalContactRelationship` system.
4. If no match is found, no participant is added (conservative approach).

#### Manual Strava-to-Contact Mapping

Users should be able to manually map a Strava athlete ID to a contact. This handles cases where names differ between Strava and the local contact record. The mapping is stored and used for future imports from that athlete.

The mapping is stored as a simple table:
- `user_id`, `strava_athlete_id`, `contact_id`

Once mapped, all future activities involving that Strava athlete automatically add the contact as a participant.

### Sync Metadata

Strava sync state is tracked using the existing `SyncMetadata` model:
- `integration_source` = `"strava"`
- `internal_id` = journal ID
- `external_id` = Strava activity ID
- `version_hash` = hash of the Strava activity's last update timestamp

The existing `SyncJob` model tracks sync job history (full sync, webhook-triggered sync).

---

## Part 4: External System Links on Journals & Contacts

### Purpose

When a journal or contact is linked to an external system (Google Calendar, Google Contacts, Strava), the detail page should show which external systems are connected. This helps the user understand data provenance and provides quick access to the external record.

### Required Behaviour

- External system links should appear as metadata on the journal or contact detail page — not in the header, but in a secondary information area.
- Each link shows the external system's icon and a clickable link to the item in the external system (when a URL is constructable).
- A journal may have links to multiple external systems simultaneously (e.g. Google Calendar + Strava).
- A contact may have links to multiple external systems (e.g. Google Contacts).

### Data Source

External system links are derived from existing data:
- **Journals:** `JournalExternalEventLink` records (for calendar-linked journals) and `fitness_data.strava_activity_id` (for Strava-linked journals)
- **Contacts:** `SyncMetadata` records where `integration_source` matches the external system

No new database tables are needed. The UI queries existing sync metadata and external link records.

### URL Construction

- **Google Calendar:** `https://calendar.google.com/calendar/event?eid={base64_encoded_id}`
- **Google Contacts:** `https://contacts.google.com/person/{resource_name}`
- **Strava:** `https://www.strava.com/activities/{strava_activity_id}`

Where a URL cannot be constructed (e.g. missing external ID), the icon is shown without a link.

### MCP Parity

External system links should be included in MCP responses for contacts and journals, providing the integration source name and external URL where available.

---

## Part 5: Future Considerations (Out of Scope)

The following capabilities are explicitly flagged as future work:

### Strava Write-Back

Future iterations may support syncing select fields back to Strava:
- Journal title → Strava activity name
- Gear item references → Strava gear
- Journal content → Strava activity description

The sync metadata model already supports tracking sync direction. The `SyncMetadata.version_hash` field enables change detection in both directions. No additional schema changes are needed to support future bidirectional sync.

### Strava Gear Mapping

When gear items are implemented (from the outdoor logbook specification), Strava gear references could be mapped to local gear items. This would enable automatic gear usage tracking from Strava activities.

### Additional Strava Data

- Segment efforts and personal records
- Training load and fitness metrics
- Social features (kudos, comments)
- Photo imports from Strava activities

---

## Delivery Notes

This specification defines target product behaviour. Delivery should be phased to preserve coherence and maintain a green main branch.

### Suggested Phasing

1. **Event bus infrastructure:** Replace the outbox processor's direct dispatch with Redis Streams relay and consumer groups. Migrate **all** existing consumers to consumer groups: search indexer, AI summary generator, and Google worker (contacts, calendar, tags). Each becomes an independent consumer group reading from the same `domain-events` stream. Verify no behaviour change end-to-end.

2. **Pluggable integration UI:** Refactor the integrations page to use a generic dashboard pattern. Create the backend integration registry API. Migrate Google to the new pattern.

3. **Strava OAuth & API client:** Implement Strava OAuth flow, API client, webhook registration. Add Strava to the integration registry.

4. **Strava activity import:** Implement activity sync, data transformation, GPX import, and journal creation via the outbox pattern. Wire up merge review queue.

5. **Participant detection & external links:** Implement Strava athlete-to-contact matching, manual mapping UI, and external system link display on journal/contact detail pages.

6. **MCP parity:** Ensure all Strava-imported data and external system links are available through MCP tools.

Each phase should deliver working, testable functionality with full test coverage before moving to the next. Phase 1 is a prerequisite for all other phases. Phases 3–6 require iteration 9 (Outdoor Logbook) to be complete.

## Iteration 5 Compatibility Notes

The following elements from the original `iteration-5-strava-integration.md` are absorbed unchanged:

- **ITER5-001 (OAuth & API Client):** OAuth flow steps, `UserStravaAuth` model, `StravaAPIClient` methods, encrypted token storage. All compatible.
- **ITER5-002 (Activity Data Sync):** Pydantic models for Strava API responses, `UserStravaIntegration` model, incremental sync strategy. Compatible, with activity type mapping updated to include iteration 9 types (CANOEING, DOWNHILL_SKIING, etc.).
- **ITER5-004 (ARQ Worker):** Worker lifecycle, Dockerised deployment, health checks. Compatible, but event communication now uses Redis Streams instead of ARQ-based broadcast.

The following elements are superseded:

- **ITER5-003 (Merge Logic):** The custom `JournalMergeService` described in iteration 5 is replaced by the existing `JournalMergeService` and `MatchCandidateDetector` which are already implemented. No new merge service is needed.
- **ITER5-005 (UI):** The Strava-specific UI components are replaced by the generic integrations dashboard pattern described in Part 2.
- **Architecture Notes:** The ARQ-based event broadcast is replaced by Redis Streams consumer groups.

## Success Criteria

This work will be successful when:

1. Domain events are published once to a Redis Stream and consumed independently by search, summary, Google, and Strava consumer groups.
2. The integrations page renders integration panels dynamically from a backend registry without integration-specific page components.
3. Strava activities are automatically imported as journals with correct type mapping, fitness data, and GPX tracks.
4. Imported Strava activities trigger the merge review queue when they overlap with existing journals.
5. Strava athlete names are matched to contacts and added as journal participants where confident.
6. Journal and contact detail pages show external system link metadata for all connected integrations.
7. All Strava-imported data is accessible through MCP tools.
8. Adding a hypothetical new integration would require only a new worker, a consumer group registration, and an integration registry entry — no changes to the main backend's event routing or UI layout.
