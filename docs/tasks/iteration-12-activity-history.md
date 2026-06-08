# Iteration 12: Activity History (Journals + Unified Foundation)

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (Journal core + events), Iteration 5 (Redis Streams event bus, transactional outbox relay, stream consumers), existing contact activity history
**Goal:** Deliver field-level activity history for journals of all types, displayed at the bottom of the journal UI with full provenance, by generalising the existing contact-history infrastructure into a single shared, **event-driven** system — and migrating contacts onto that same foundation.

## Overview

This iteration delivers the approved [Activity History Product Specification](../product-specifications/activity-history-product-specification.md) in incremental, shippable slices.

Today, contact history is written as a **synchronous dual-write**: the service layer must call *both* `history_service.record_*()` *and* `event_publisher.publish(...)` in the same transaction. This is the fragility the spec's "integrity by construction" principle targets — it is easy to publish an event but forget to write history (or vice versa).

This iteration replaces that with a **history projection**: history becomes a read model derived from the domain events already flowing through the `pms:domain-events` Redis Stream. A single `publish(...)` is the only write a mutation must perform; a new `HistoryProjectionConsumer` (modelled exactly on the existing `SearchIndexerConsumer`) consumes events and writes history rows.

```
service.update():
    repo.save(...)
    publish(JournalUpdated{ journal_id, changed_fields:{f:(old,new)}, source, changed_by })
                        │
              outbox_events (same txn)  →  outbox relay  →  pms:domain-events stream
                        ├─ SearchIndexerConsumer        (exists)
                        └─ HistoryProjectionConsumer    (NEW) → field_history rows
```

Two properties follow from going async, and are designed for throughout:

1. **Provenance travels in the event.** Today provenance is passed as service/controller arguments (`changed_by="ui", source=Provenance.UI`). The consumer cannot see those, so `source` + `changed_by` are added to event payloads.
2. **At-least-once delivery → idempotent projection.** Stream redelivery must not double-write. A unique key on the history row plus `ON CONFLICT DO NOTHING` guarantees this. Each row's timestamp is taken from `event.occurred_at`, not wall-clock at projection time, so ordering reflects when the change happened.

## Reference Documents

- **[Activity History Product Specification](../product-specifications/activity-history-product-specification.md)** — approved product behaviour for this iteration
- **[Integration Architecture](../architecture/integration-architecture.md)** — event bus, transactional outbox relay, and stream consumer patterns (the `HistoryProjectionConsumer` follows the documented consumer pattern)
- **[Contacts Product Specification](../product-specifications/contacts-product-specification.md)** — Activity Feed behaviour and provenance principles (the reference implementation)
- **[Journals Product Specification](../product-specifications/journals-product-specification.md)** — journal domain, types, and MCP parity expectations
- **[Domain Architecture](../architecture/domain-architecture.md)** — domain layer, ports & adapters, event handling
- **[Database Design](../architecture/database-design.md)** — schema and data-layer standards
- **[Testing Strategy](../architecture/testing-strategy.md)** — unit/integration/E2E patterns, conftest fixtures, Docker PostgreSQL
- **[Iteration 5: Integration Architecture & Strava](./iteration-5-integration-architecture-and-strava.md)** — origin of the Redis Streams event bus and consumer groups
- **[Iteration 11: Immich Integration](./iteration-11-immich-integration.md)** — consumer/processor and reviewable-PR reference

### External Documentation

- **SQLAlchemy Core** — https://docs.sqlalchemy.org/en/20/ (use the `writing-sql` skill before authoring queries)
- **Alembic** — https://alembic.sqlalchemy.org/en/latest/ (use the `creating-migrations` skill for sequential naming)
- **FastAPI** — https://fastapi.tiangolo.com/ (context7 `fastapi/fastapi`)
- **Dishka** — https://dishka.readthedocs.io/en/stable/ (consumer + service DI wiring)
- **FastMCP v2** — https://gofastmcp.com/llms.txt (context7 `websites/gofastmcp`) for the journal history MCP tool
- **React Testing Library** — https://testing-library.com/docs/react-testing-library/intro
- **Playwright** — https://playwright.dev/docs/intro (use the `playwright-skill` and `running-e2e-tests` skills)

## Delivery Rules

1. **Tests first:** write failing tests for the slice before implementation (TDD red → green → refactor).
2. **Green main:** do not merge a phase unless relevant tests, linting (`ruff`, `pnpm lint`), and type checks (`mypy`, `pnpm type-check`) pass.
3. **Reviewable PRs:** keep each PR to roughly ≤ 10 files where practical.
4. **MCP parity:** if a capability is meaningful in the UI, expose it through MCP in the same task.
5. **No behaviour regression for contacts:** the existing contact activity feed must look and behave identically throughout; the full existing contact-history test suite is the regression gate.
6. **Every phase is shippable:** no phase may rely on a later phase to restore broken behaviour.

## Incremental Value Chunks

The work is split into three chunks, each independently shippable and valuable. They are ordered to front-load the headline journal value and isolate the riskiest change (the contact migration) to last.

- **ITER12-001 — Shared History Foundation.** A pure refactor that generalises the contact-history table, model, repository, API schemas, and frontend components into an entity-agnostic shared system. *No behaviour change.* Value: the reusable foundation and a clean seam, with contacts continuing to work exactly as today (still synchronous, for now).

- **ITER12-002 — Journal History (end-to-end).** Enrich journal events, build the event-driven `HistoryProjectionConsumer` for journal events, expose a journal history API + MCP tool, and render the activity feed at the bottom of the journal UI. Value: **the user-facing journal history feature.** No duplication risk because journals have no prior history.

- **ITER12-003 — Migrate Contacts to Event-Driven Projection.** Enrich contact events with provenance, extend the projection consumer to contact events, and remove the synchronous dual-write. Value: integrity-by-construction for contacts, completing the unified system.

| Chunk | Delivers | User-visible? | Risk |
|---|---|---|---|
| ITER12-001 | Shared foundation, no behaviour change | No | Low (refactor under existing tests) |
| ITER12-002 | Journal history (UI + API + MCP) | **Yes** | Medium (new consumer, async) |
| ITER12-003 | Contacts on event-driven path | No (parity) | Medium (removes working dual-write) |

---

## Task Breakdown

### ITER12-001: Shared History Foundation

**Objective:** Generalise the contact-specific history infrastructure into an entity-agnostic, shared system reusable by both contacts and journals, with **no change to current behaviour**.

**Specification Reference:**
- [Activity History — Product Principles](../product-specifications/activity-history-product-specification.md#product-principles)
- [Activity History — Scope](../product-specifications/activity-history-product-specification.md#scope)

**Acceptance Criteria (task-level):**
- [ ] History table, domain model, repository, API schemas, and frontend components are entity-agnostic and shared.
- [ ] `Provenance` lives in a shared module usable by both domains.
- [ ] The contact activity feed behaves and looks identically (regression gate green).

#### Phase 1: Backend — Generalise Table, Model, and Repository
**PR Size:** ~8–10 files

Generalise the data layer while keeping the existing contact write/read paths working unchanged.

**Acceptance Criteria:**
- [ ] Alembic migration renames `contact_field_history` → `field_history` (table is already entity-agnostic via `entity_type` + `entity_id`); existing rows preserved.
- [ ] Migration adds nullable `event_id VARCHAR` column and a unique index on `(event_id, entity_type, entity_id, field_name)` for projection idempotency (existing rows keep `event_id = NULL`).
- [ ] `Provenance` enum relocated from `core_shared/.../contacts/value_objects.py` to a shared module (e.g. `core_shared/.../history/`), re-exported from the old path for compatibility; add any journal-relevant sources (e.g. `GOOGLE_CALENDAR`).
- [ ] `ContactFieldHistoryEntry` generalised to `FieldHistoryEntry` (shared), with a compatibility alias.
- [ ] Repository generalised (`field_history_repository.py`) with `record_change` using `INSERT ... ON CONFLICT DO NOTHING`, and `get_history_for_aggregate(root_type, root_id, limit, offset)` backed by a per-root **aggregation strategy** (the current hard-coded contact `WHERE` becomes the "contact" strategy).
- [ ] Contact history endpoint and `ContactHistoryService` continue to work via the generalised repository.

**Required Test Coverage:**
- **Integration:** migration applies and preserves existing rows; unique index rejects duplicate `(event_id, entity_type, entity_id, field_name)`; `record_change` is idempotent on re-insert; `get_history_for_aggregate` returns correct aggregation + pagination for the contact strategy. Use `async_connection` / `clean_database` fixtures from `tests/integration/conftest.py` (never a new `DatabaseProvider`).
- **Unit:** `Provenance` re-export, `FieldHistoryEntry` construction/alias.
- **Regression:** existing contact history unit + integration tests remain green unchanged.

#### Phase 2: Frontend — Generalise Activity Feed Components and Types
**PR Size:** ~6–8 files

Move the activity-feed components and types to a shared location, parameterised by entity, with a thin contact wrapper.

**Acceptance Criteria:**
- [ ] `ActivityFeed.tsx` and `ActivityItem.tsx` moved from `components/contacts/` to `components/history/`, parameterised by entity type and data hook.
- [ ] History types promoted from `types/contacts.ts` to a shared `types/history.ts` (re-exported for compatibility).
- [ ] Provenance icon/label map extended for any new sources.
- [ ] Existing contact usage rewired through the shared component with no visual or behavioural change.

**Required Test Coverage:**
- **Unit (RTL):** shared `ActivityFeed`/`ActivityItem` render entries, provenance icons/labels, Load-More pagination, loading/empty/error states.
- **Regression:** existing contact activity-feed component tests and the `contact-activity-feed.spec.ts` E2E remain green.

---

### ITER12-002: Journal History (End-to-End)

**Objective:** Deliver field-level history for journals of all types via the event-driven projection, surfaced at the bottom of the journal UI and through MCP.

**Specification Reference:**
- [Activity History — Activity History Behaviour](../product-specifications/activity-history-product-specification.md#activity-history-behaviour)
- [Activity History — MCP and AI-Agent Parity](../product-specifications/activity-history-product-specification.md#mcp-and-ai-agent-parity)

**Acceptance Criteria (task-level):**
- [ ] Meaningful journal changes of every type are recorded with field-level diffs and provenance.
- [ ] Journal history is available via API and MCP and rendered at the bottom of the journal detail screen.
- [ ] Projection is idempotent (no duplicates on stream redelivery).

#### Phase 1: Event Enrichment + History Projection Consumer (Journal Events)
**PR Size:** ~8–10 files

Add provenance to journal events and build the consumer that writes history from them.

**Acceptance Criteria:**
- [ ] Journal domain events (`JournalCreated`, `JournalUpdated`, `JournalDeleted`, `JournalTypeAdded`, `JournalTypeRemoved`, `RouteCreated/Updated/Deleted`, `GearItemUpdated`) carry `source: Provenance` and `changed_by: str` in `event_data`; provenance is plumbed from the API/MCP/worker boundary into the service → event.
- [ ] `RouteUpdated`, `RouteDeleted`, and `GearItemUpdated` additionally carry `journal_id` so route/gear changes can be grouped to their parent journal.
- [ ] `HistoryService.project_event(event)` maps each journal event type → one or more `FieldHistoryEntry` rows (updates → one row per `changed_fields` entry; create/delete → marker row; type add/remove → `field_name="types"`), with `created_at = event.occurred_at`.
- [ ] A "journal" aggregation strategy resolves the `(entity_type, entity_id)` set for a journal (journal + type-specific data + routes + gear).
- [ ] `HistoryProjectionConsumer` (`app.infrastructure.events.history_projection_consumer`, group `history-projection`) consumes the relevant journal event types from `pms:domain-events`, subclassing `DeadLetterConsumerMixin, StreamConsumer`; writes rows idempotently.
- [ ] Consumer registered in `backend/app/main.py` and DI wiring alongside the other consumers.

**Required Test Coverage:**
- **Unit:** each journal event carries `source`/`changed_by` (and `journal_id` for route/gear); `project_event` produces exactly the expected rows per event type, carrying provenance and `occurred_at` (mirror `tests/unit/contacts/test_events.py`).
- **Integration:** publishing journal events to the stream → consumer writes correct `field_history` rows; **redelivery of the same event writes no duplicates**; malformed event → dead-letter. Mirror the search-indexer consumer integration tests.

#### Phase 2: Journal Changed-Fields Coverage (All Types) + History API
**PR Size:** ~7–9 files

Ensure every journal mutation publishes accurate `changed_fields`, and expose the read API.

**Acceptance Criteria:**
- [ ] Journal service computes `changed_fields` as `{field: (old, new)}` for base fields **and** type-specific data tables (covering all journal types), routes, and gear — modelled on the contact `_calculate_changed_fields` pattern.
- [ ] Every journal create/update/delete/type/route/gear mutation publishes an event with accurate `changed_fields` + provenance, and produces no history when nothing changed.
- [ ] `GET /api/journals/{journal_id}/history?page=&limit=` returns paginated JSON:API history (mirrors the contact history endpoint), 404 for a missing journal, with shared `HistoryAttributes`/`HistoryResource`/`HistoryListResponse` schemas and converter.

**Required Test Coverage:**
- **Unit:** `changed_fields` calculation for base fields, at least two type-specific data tables, routes, and gear; "no change → no event" cases.
- **Integration (end-to-end backend):** through the real service + outbox + relay + consumer path, updating a journal field (and a type-specific field, and a route/gear field) results in correctly-grouped history retrievable via the endpoint, with correct old/new/provenance; endpoint empty state, pagination, 404, and JSON:API shape (mirror `tests/integration/api/test_history_endpoints.py`).

#### Phase 3: Journal History UI + MCP Parity
**PR Size:** ~6–8 files

Surface journal history to users and AI agents.

**Acceptance Criteria:**
- [ ] `useJournalHistory` hook + `fetchJournalHistory` client (mirror the contact history hook), with appropriate query keys and stale time.
- [ ] Shared `<ActivityFeed entity="journal" id={journalId} />` rendered at the **bottom of `JournalDetail.tsx`** (after the type sections), with provenance icons/labels and Load-More pagination.
- [ ] MCP `get_journal_history` tool returns field-level history with provenance, matching the API.
- [ ] UI accounts for async projection (waits for entries to appear rather than asserting immediately).

**Required Test Coverage:**
- **Unit (RTL):** journal activity feed renders entries with provenance and pagination; empty/loading/error states.
- **E2E (Playwright):** each test creates its own data (no conditional/skip logic). Editing a journal shows the change at the bottom of the screen with correct provenance (using `waitFor` for async projection); pagination works; coverage across multiple journal types (e.g. NOTE, EVENT, a fitness/outdoor type). Model on `contact-activity-feed.spec.ts`.
- **Integration:** MCP `get_journal_history` returns expected entries.

---

### ITER12-003: Migrate Contacts to Event-Driven Projection

**Objective:** Move contact history onto the same event-driven projection and remove the synchronous dual-write, completing "integrity by construction" without changing the user-visible feed.

**Specification Reference:**
- [Activity History — Product Principles (Integrity by construction)](../product-specifications/activity-history-product-specification.md#product-principles)
- [Activity History — Delivery Notes](../product-specifications/activity-history-product-specification.md#delivery-notes)

**Acceptance Criteria (task-level):**
- [ ] Contact history is produced solely by the `HistoryProjectionConsumer` from contact events.
- [ ] The synchronous `history_service.record_*` dual-write is removed.
- [ ] The contact activity feed is unchanged for users; the full existing contact-history suite passes via the event path.

#### Phase 1: Enrich Contact Events + Extend Projection Consumer
**PR Size:** ~7–9 files

Carry provenance on contact events and teach the consumer to project them — **before** removing the dual-write, to avoid a gap.

**Acceptance Criteria:**
- [ ] Contact domain events (`ContactCreated`, `ContactUpdated`, `ContactDeleted`, relationship/tag/important-date/summary events) carry `source` + `changed_by` in `event_data`, plumbed from the existing controller/MCP/worker provenance values.
- [ ] A "contact" aggregation strategy (already extracted in ITER12-001) is used by the projection reads.
- [ ] `HistoryProjectionConsumer` extended to handle the contact event types, writing the same rows the dual-write produces today (validated against snapshots), still idempotent.
- [ ] The dual-write remains in place this phase; the consumer is feature-flagged or otherwise prevented from double-writing until Phase 2 (e.g. enable contact projection and remove the dual-write atomically in Phase 2). *Implementation note: keep contact projection inert until Phase 2 to avoid duplicates.*

**Required Test Coverage:**
- **Unit:** contact events carry `source`/`changed_by`; `project_event` for each contact event type yields rows equivalent to the current `record_*` output.
- **Integration:** consumer projects contact events into equivalent history rows (compared against the dual-write output), idempotently.

#### Phase 2: Remove the Synchronous Dual-Write
**PR Size:** ~6–8 files

Switch contacts fully onto the projection and delete the redundant write path.

**Acceptance Criteria:**
- [ ] Direct `history_service.record_*` calls removed from `contact_service.py`, contact controllers, and relationship controllers; the `changed_by`/`source` arguments now feed the published events instead.
- [ ] Contact history is produced only by the projection consumer.
- [ ] No duplicate entries; ordering and content match prior behaviour.

**Required Test Coverage:**
- **Integration (end-to-end):** through the real service + outbox + relay + consumer path, contact create/update/tag/relationship/important-date/summary changes produce the expected history; no duplicates.
- **Regression:** the full existing contact-history unit + integration suite passes against the event-driven path; `contact-activity-feed.spec.ts` E2E passes (with `waitFor` for async, if needed).

---

## Success Criteria

- Journals of every type show a complete, ordered, field-level history with provenance at the bottom of the detail screen.
- Journal history is retrievable via the REST API and MCP, matching the UI.
- Contacts and Journals share one history model, API shape, and activity-feed component.
- History is produced solely from domain events for both domains — no service-layer dual-write remains.
- Projection is idempotent: stream redelivery never produces duplicate entries.
- The contact activity feed is unchanged for users; the full existing contact-history suite passes.

## Phase Summary

| Task | Phases | Total est. PRs |
|---|---|---|
| ITER12-001: Shared History Foundation | 2 | 2 |
| ITER12-002: Journal History (end-to-end) | 3 | 3 |
| ITER12-003: Migrate Contacts to Projection | 2 | 2 |
| **Total** | **7** | **7** |

## Risks & Mitigations

- **Async visibility lag** (history appears moments after a change): UI/E2E use `waitFor`; React Query stale time is acceptable for an audit log. Inherent to the event-driven design.
- **Duplicate rows on stream redelivery:** unique index `(event_id, entity_type, entity_id, field_name)` + `ON CONFLICT DO NOTHING` (covered by Phase ITER12-001/2 tests).
- **Contact regression from removing the dual-write:** sequenced last; full existing contact suite is the gate; provenance added to events *before* the dual-write is removed.
- **Routes/gear not grouping to their journal:** `journal_id` added to `RouteUpdated`/`RouteDeleted`/`GearItemUpdated` (ITER12-002 Phase 1).
- **Lost provenance during migration:** event enrichment lands before the corresponding dual-write removal in every case.
