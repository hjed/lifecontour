# Iteration 12: Activity History (Journals + Unified Foundation)

**Status:** ✅ COMPLETE — ITER12-001 (shared foundation) complete (Phase 1 backend + Phase 2 frontend); ITER12-002 **complete** — Phase 1 (journal event enrichment + projection consumer), Phase 2 (changed-fields coverage + journal history API), Phase 3 (journal history UI + MCP read parity), and Phase 4 (type-data history on the MCP/integration/nested write surfaces) all done; ITER12-003 Phase 1 (contact event enrichment + projection handlers, inert) **and Phase 2 (remove the contact dual-write — contacts now fully event-driven)** complete
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
- [x] History table, domain model, repository, API schemas, and frontend components are entity-agnostic and shared. *(Backend table/model/repository done in Phase 1; frontend components + types generalised in Phase 2. Note: REST `ContactHistory*` API schemas remain the contact endpoint's response shape and adopt the shared `History*` schemas in ITER12-002 Phase 2 when the journal history endpoint lands.)*
- [x] `Provenance` lives in a shared module usable by both domains. *(Moved to `core_shared/core_shared/models/history/`, re-exported from contacts for compatibility.)*
- [x] The contact activity feed behaves and looks identically (regression gate green). *(Backend regression suites green in Phase 1; full `contact-activity-feed.spec.ts` E2E + RTL gate confirmed green in Phase 2.)*

#### Phase 1: Backend — Generalise Table, Model, and Repository ✅
**PR Size:** ~8–10 files
**Status:** ✅ COMPLETE

Generalise the data layer while keeping the existing contact write/read paths working unchanged.

**Acceptance Criteria:**
- [x] Alembic migration renames `contact_field_history` → `field_history` (table is already entity-agnostic via `entity_type` + `entity_id`); existing rows preserved. *(`0087_rename_contact_field_history_to_field_history.py`; `rename_table` preserves rows.)*
- [x] Migration adds nullable `event_id VARCHAR` column and a unique index on `(event_id, entity_type, entity_id, field_name)` for projection idempotency (existing rows keep `event_id = NULL`). *(Index `ux_field_history_event_dedup`.)*
- [x] `Provenance` enum relocated from `core_shared/.../contacts/value_objects.py` to a shared module (e.g. `core_shared/.../history/`), re-exported from the old path for compatibility; add any journal-relevant sources (e.g. `GOOGLE_CALENDAR`). *(Added `GOOGLE_CALENDAR`.)*
- [x] `ContactFieldHistoryEntry` generalised to `FieldHistoryEntry` (shared), with a compatibility alias. *(`app/core/history/models.py`; alias kept in `contacts/models/repositories.py`.)*
- [x] Repository generalised (`field_history_repository.py`) with `record_change` using `INSERT ... ON CONFLICT DO NOTHING`, and `get_history_for_aggregate(root_type, root_id, limit, offset)` backed by a per-root **aggregation strategy** (the current hard-coded contact `WHERE` becomes the "contact" strategy). *(`SqlFieldHistoryRepository` + `HistoryAggregationStrategy` registry.)*
- [x] Contact history endpoint and `ContactHistoryService` continue to work via the generalised repository. *(`SqlContactFieldHistoryRepository` is now a thin façade over the shared repo; no API/service changes.)*

**Required Test Coverage:**
- [x] **Integration:** migration applies and preserves existing rows; unique index rejects duplicate `(event_id, entity_type, entity_id, field_name)`; `record_change` is idempotent on re-insert; `get_history_for_aggregate` returns correct aggregation + pagination for the contact strategy. Use `async_connection` / `clean_database` fixtures from `tests/integration/conftest.py` (never a new `DatabaseProvider`). *(`tests/integration/history/`.)*
- [x] **Unit:** `Provenance` re-export, `FieldHistoryEntry` construction/alias. *(`tests/unit/history/`.)*
- [x] **Regression:** existing contact history unit + integration tests remain green unchanged. *(1778 unit + contact history integration + search-indexer suites green.)*

#### Phase 2: Frontend — Generalise Activity Feed Components and Types ✅
**PR Size:** ~6–8 files
**Status:** ✅ COMPLETE

Move the activity-feed components and types to a shared location, parameterised by entity, with a thin contact wrapper.

**Acceptance Criteria:**
- [x] `ActivityFeed.tsx` and `ActivityItem.tsx` moved from `components/contacts/` to `components/history/`, parameterised by entity type and data hook. *(`ActivityFeed` takes an injected `useHistory` hook + `entity` prop; `ActivityItem` is entity-agnostic via `HistoryResource`.)*
- [x] History types promoted from `types/contacts.ts` to a shared `types/history.ts` (re-exported for compatibility). *(`HistoryAttributes`/`HistoryResource`/`HistoryPaginationMeta`/`HistoryListResponse`/`HistoryFilters`; old `ContactHistory*` names re-exported as aliases.)*
- [x] Provenance icon/label map extended for any new sources. *(Added `google_calendar` (Calendar) and `immich` (Camera); all spec-listed sources covered.)*
- [x] Existing contact usage rewired through the shared component with no visual or behavioural change. *(Thin `components/contacts/ActivityFeed.tsx` wrapper supplies `entity="contact"` + `useContactHistory`; the contact detail page import is unchanged.)*

**Required Test Coverage:**
- [x] **Unit (RTL):** shared `ActivityFeed`/`ActivityItem` render entries, provenance icons/labels, Load-More pagination, loading/empty/error states. *(`components/history/__tests__/`; provenance labels covered via the exported `getProvenanceLabel` mapping, triggers via `data-testid`.)*
- [x] **Regression:** existing contact activity-feed component tests and the `contact-activity-feed.spec.ts` E2E remain green. *(Contact wrapper RTL parity test + full E2E spec green; 1339 frontend unit tests + 7 E2E tests passing.)*

---

### ITER12-002: Journal History (End-to-End)

**Objective:** Deliver field-level history for journals of all types via the event-driven projection, surfaced at the bottom of the journal UI and through MCP.

**Specification Reference:**
- [Activity History — Activity History Behaviour](../product-specifications/activity-history-product-specification.md#activity-history-behaviour)
- [Activity History — MCP and AI-Agent Parity](../product-specifications/activity-history-product-specification.md#mcp-and-ai-agent-parity)

**Acceptance Criteria (task-level):**
- [x] Meaningful journal changes of every type are recorded with field-level diffs and provenance. *(REST + all editable single-row types in Phase 2; MCP type-data parity, PLAN/ABSEIL nested per-row history, and Immich PHOTO_ALBUM metadata in Phase 4. TRAVEL nested children are deferred — they have no write path yet.)*
- [x] Journal history is available via API and MCP and rendered at the bottom of the journal detail screen. *(API in Phase 2; MCP `get_journal_history` tool + activity feed at the bottom of `JournalDetailView` in Phase 3.)*
- [x] Projection is idempotent (no duplicates on stream redelivery). *(Unique index `(event_id, entity_type, entity_id, field_name)` + `ON CONFLICT DO NOTHING`, covered by Phase 1 tests.)*

#### Phase 1: Event Enrichment + History Projection Consumer (Journal Events) ✅
**PR Size:** ~8–10 files (exceeded: full UI/MCP/worker provenance plumbing landed in this PR by request)
**Status:** ✅ COMPLETE

Add provenance to journal events and build the consumer that writes history from them.

**Acceptance Criteria:**
- [x] Journal domain events (`JournalCreated`, `JournalUpdated`, `JournalDeleted`, `JournalTypeAdded`, `JournalTypeRemoved`, `RouteCreated/Updated/Deleted`, `GearItemUpdated`) carry `source: Provenance` and `changed_by: str` in `event_data`; provenance is plumbed from the API/MCP/worker boundary into the service → event. *(Events default to `SYSTEM`; UI controllers pass `Provenance.UI`, MCP tools `Provenance.MCP`, the inbound sync processor maps `integration_source` → `STRAVA`/`GOOGLE_CALENDAR`, and the Immich processor passes `Provenance.IMMICH`.)*
- [x] `RouteUpdated`, `RouteDeleted`, and `GearItemUpdated` additionally carry `journal_id` so route/gear changes can be grouped to their parent journal. *(`GearItemUpdated.journal_id` is optional — gear is many-to-many with journals, so a plain gear edit has no single parent and the projection skips it; `delete_route` reads `route.journal_id` before deletion.)*
- [x] `HistoryService.project_event(event)` maps each journal event type → one or more `FieldHistoryEntry` rows (updates → one row per `changed_fields` entry; create/delete → marker row `__created__`/`__deleted__`; type add/remove → `field_name="types"`), with `created_at = event.occurred_at`. *(`app/core/history/services/history_service.py`; pure mapping. Route/gear rows are tagged to the journal with context in `field_name` (`route:<id>:<field>`, `gear:<id>:<field>`). Non-pair `changed_fields` signals — e.g. `{"calendar_info": True}` calendar-sync triggers — produce no history, honouring "meaningful changes only".)*
- [x] A "journal" aggregation strategy resolves the `(entity_type, entity_id)` set for a journal. *(`entity_type='journal' AND entity_id=:root_id` in `core/history/models.py`; route/gear/type changes are all tagged to the journal itself — route/gear ids are UUIDs that cannot live in the integer `entity_id` column, and journal-tagging is deletion-safe — so no joins are needed.)*
- [x] `HistoryProjectionConsumer` (`app.infrastructure.events.history_projection_consumer`, group `history-projection`) consumes the relevant journal event types from `pms:domain-events`, subclassing `DeadLetterConsumerMixin, StreamConsumer`; writes rows idempotently. *(Mirrors `SearchIndexerConsumer`; `record_change` now also writes `created_at = event.occurred_at` via `COALESCE(:created_at, now())`, backward-compatible with the contact dual-write.)*
- [x] Consumer registered in `backend/app/main.py` alongside the other consumers (self-manages its connection like `SearchIndexerConsumer`, so no new Dishka provider).

**Required Test Coverage:**
- [x] **Unit:** each journal event carries `source`/`changed_by` (and `journal_id` for route/gear); `project_event` produces exactly the expected rows per event type, carrying provenance and `occurred_at` (mirrors `tests/unit/contacts/test_events.py`). *(`tests/unit/journal/test_events.py`, `tests/unit/history/test_history_service.py`, `tests/unit/infrastructure/events/test_history_projection_consumer.py`.)*
- [x] **Integration:** publishing journal events to the stream → consumer writes correct `field_history` rows; **redelivery of the same event writes no duplicates**; malformed event → dead-letter; plus a backend end-to-end test through the real service → outbox → relay → consumer path. *(`tests/integration/infrastructure/events/test_history_projection_consumer_integration.py`, `tests/integration/infrastructure/events/test_journal_history_projection_e2e.py`, and `created_at` coverage in `tests/integration/history/test_field_history_repository_integration.py`.)*
- [x] **Regression:** full unit suite (1852), contact-history + contact-service, search-indexer/outbox-relay, journal/route/gear/MCP integration suites green; `ruff` + `mypy` clean.

#### Phase 2: Journal Changed-Fields Coverage (All Types) + History API ✅
**PR Size:** ~7–9 files (slightly exceeded with the shared History API module + tests)
**Status:** ✅ COMPLETE

Ensure every journal mutation publishes accurate `changed_fields`, and expose the read API.

**Design (as built):**
- Base-field `changed_fields` `{field: (old, new)}` is computed **inside `JournalService.update_journal`** (`_calculate_changed_fields`, mirroring contact `_calculate_changed_fields`): it loads the existing journal, diffs `title`/`content`/`event_date_range`/`parent_id`/`order` (event date range rendered as a compact ISO range string), and the `changed_fields` parameter is **removed** from the signature. This converted every producer at once — UI PUT/PATCH controllers, the MCP update tool, the Google inbound processor, and the Immich processor now just pass the merged journal; the Immich `_CHANGED_FIELDS` marker constant was deleted.
- The Google Calendar outbound worker keys sync on `changed_fields` **keys** only (incl. the `calendar_info` marker — verified in `worker.py`), so converting values to `(old, new)` pairs preserves sync. The EVENT type-data path keeps emitting `{"calendar_info": True}` **and** adds real field diffs in the same event (the projection skips the non-pair marker, records the pairs).
- Type-specific `changed_fields` is computed generically in `JournalWriteService.update_type_data` via a snapshot→apply→diff registry (`_TYPE_DATA_TRACKED_FIELDS` + `to_history_value`/`diff_tracked_fields`), with `changed_by`/`source` threaded through and a single `JournalUpdated` published. **All editable single-row types are covered:** EVENT, MOOD_RATING, FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING, ABSEILING_TRIP, CANYONING, CAVING, CANOEING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, OUTDOOR_PLANNING, OUTDOOR_TRAINING, GEAR_MAINTENANCE. A **completeness guard test** (`tests/unit/journal/test_type_data_history_coverage.py`) introspects every type-data dataclass and fails if any `JournalType` or model field isn't explicitly tracked-or-excluded — so new fields/types can't silently drop out of history. (This test caught two pre-existing registry bugs: `route_id` was listed for BUSHWALKING/JOGGING but isn't a field on those models, and EVENT's denormalised `event_start_date`/`event_end_date` needed an explicit exclusion.) PLAN/TRAVEL hold nested child collections, PHOTO_ALBUM is Immich-synced, and GEAR_USAGE has no edit path — all explicitly excluded-with-reason; SNORKELLING/DIVING/DOWNHILL_SKIING are existence-validate-only (no editable fields).
- Route `changed_fields` were **already** `(old, new)` pairs in `RouteRequestConverter.from_update_request`, and gear (`GearItemService.update`) already emits pairs — both flow through `RouteUpdated`/`GearItemUpdated` and the Phase 1 `route:<id>:<field>` / `gear:<id>:<field>` projection unchanged. No service change was needed.
- `GET /api/journals/{journal_id}/history` mirrors the contact endpoint using **new shared** `History{Attributes,Resource,ListResponse}` schemas + `HistoryConverter` (`app/api/history/`, `type="journal_history"`), reading via a thin `JournalHistoryService` over `get_history_for_aggregate("journal", ...)`; DI wired in `JournalProvider`. The endpoint **scopes to the authenticated user** (`journal.user_id != user.id` → 404), matching the route sub-resource endpoints, so journal history can't leak across users.

**Deferred to Phase 4 (not blocking Phase 2):** MCP type-data write history, and integration/nested write-path history (PLAN/TRAVEL nested collections, Immich PHOTO_ALBUM metadata, ABSEILING per-pitch rows) — captured as **ITER12-002 Phase 4** below.

**Acceptance Criteria:**
- [x] Journal service computes `changed_fields` as `{field: (old, new)}` for base fields **and** type-specific data tables (covering all editable journal types), routes, and gear — modelled on the contact `_calculate_changed_fields` pattern. *(`JournalService._calculate_changed_fields`; `JournalWriteService.update_type_data` snapshot/diff over the full `_TYPE_DATA_TRACKED_FIELDS` registry, guarded by `test_type_data_history_coverage.py`; routes/gear already paired.)*
- [x] The existing scalar/marker `changed_fields` producers are converted to emit `(old, new)` pairs: the UI update controllers (`api/journals/controllers.py` PUT + PATCH), the MCP update tool (base fields), the inbound sync processor, and the Immich album processor — so their mutations actually appear in `field_history`. *(All now pass the merged journal; service computes the pairs.)*
- [x] Every journal create/update/delete/type/route/gear mutation publishes an event with accurate `changed_fields` + provenance, and produces no history when nothing changed. *(Empty `changed_fields` → projection writes no rows; Google inbound skips no-op syncs; type-data publishes only on real change, EVENT always carries the sync marker.)*
- [x] `GET /api/journals/{journal_id}/history?page=&limit=` returns paginated JSON:API history (mirrors the contact history endpoint), 404 for a missing/other-user journal, with shared `HistoryAttributes`/`HistoryResource`/`HistoryListResponse` schemas and converter. *(`app/api/history/` + endpoint in `api/journals/controllers.py`, user-scoped.)*

**Required Test Coverage:**
- [x] **Unit:** `changed_fields` calculation for base fields, type-specific data tables, routes, and gear; "no change → no event" cases; **type-data coverage completeness guard**. *(`tests/unit/journal/test_journal_changed_fields.py`, `tests/unit/journal/test_type_data_changed_fields.py` (MoodData + FitnessData + EVENT value coercion), `tests/unit/journal/test_type_data_history_coverage.py` (all types/fields), `tests/unit/api/routes/test_route_changed_fields.py`, existing `tests/unit/journal/test_gear_item_service.py`; updated `test_journal_outbox_event_processor.py`; shared converter unit test `tests/unit/api/test_journal_history_converter.py`.)*
- [x] **Integration (end-to-end backend):** through the real service + outbox + relay + consumer path, updating a journal field, two type-specific fields (MOOD_RATING and a newly-registered type, CLIMBING), and a route field each produce correctly-grouped history retrievable via the journal aggregation, with correct old/new/provenance; endpoint empty state, pagination, 404, other-user 404, and JSON:API shape. *(`tests/integration/infrastructure/events/test_journal_history_projection_e2e.py`, `tests/integration/api/test_journal_history_endpoints.py`.)*
- [x] **Regression:** full unit suite (1993) green; journal/history/mcp/api/integrations/routes/events integration suites green; Google worker journal-event unit tests green; `ruff` + `ruff format` + `mypy` clean.

#### Phase 3: Journal History UI + MCP Parity ✅
**PR Size:** ~6–8 files
**Status:** ✅ COMPLETE

Surface journal history to users and AI agents.

**Design (as built):**
- The frontend reuses the ITER12-001 shared, entity-agnostic feed unchanged: a thin `components/journals/ActivityFeed.tsx` wrapper supplies `entity="journal"` + the new `useJournalHistory` hook to the shared `components/history/ActivityFeed.tsx` (mirroring the contact wrapper). No new feed/pagination UI was written.
- **Placement note:** the Phase 3 AC said "bottom of `JournalDetail.tsx`", but `JournalDetail.tsx` is dead code (imported nowhere). The journal detail route renders **`JournalDetailView.tsx`**, so the feed is mounted there as the last child (after `JournalChildrenList`, i.e. after the type-specific data sections) — satisfying the product spec's "bottom of the journal detail/edit screen".
- The MCP `get_journal_history` tool mirrors `get_route_history` (user-scoped: other-user/missing journal → not-found) and reads via the existing `JournalHistoryService` + `SqlFieldHistoryRepository` (read-only, no transaction). Its `JournalHistoryEntry` schema is field-for-field parity with the REST `HistoryAttributes` (same provenance value coercion as `HistoryConverter`), with `page`/`limit` pagination matching the endpoint.

**Acceptance Criteria:**
- [x] `useJournalHistory` hook + `fetchJournalHistory` client (mirror the contact history hook), with appropriate query keys and stale time. *(`frontend/src/lib/api/journals.ts`: `journalHistoryKeys`, `fetchJournalHistory`, `useJournalHistory` with `staleTime: 2 min`, structurally matching the shared feed's `UseHistoryHook`.)*
- [x] Shared `<ActivityFeed entity="journal" entityId={journalId} />` rendered at the **bottom of the journal detail view** (after the type sections), with provenance icons/labels and Load-More pagination. *(`components/journals/ActivityFeed.tsx` wrapper + mounted as last child of `JournalDetailView.tsx`; provenance + Load-More come from the shared feed.)*
- [x] MCP `get_journal_history` tool returns field-level history with provenance, matching the API. *(`app/mcp/domains/journals/tools.py` `get_journal_history` + `JournalHistoryEntry`/`JournalHistoryResponse` schemas; registered in `register_journal_tools`.)*
- [x] UI accounts for async projection (waits for entries to appear rather than asserting immediately). *(E2E polls the history API with `toPass` until the projected entry lands; React Query 2-min stale time is acceptable for an audit log.)*

**Required Test Coverage:**
- [x] **Unit (RTL):** journal activity feed renders entries with provenance and pagination; empty/loading/error states. *(`frontend/src/components/journals/__tests__/ActivityFeed.test.tsx` — 7 tests: id-threading, journal empty-state copy, entries+provenance (ui+mcp), loading, error, Load-More advances page, className.)*
- [x] **E2E (Playwright):** each test creates its own data (no conditional/skip logic). Editing a journal shows the change at the bottom of the screen with correct provenance (using `toPass` for async projection); pagination works; coverage across multiple journal types (NOTE, EVENT, fitness). Modelled on `contact-activity-feed.spec.ts`. *(`frontend/tests/e2e/journal-history.spec.ts` — 6 tests; empty-state left to RTL since a created journal always projects a `__created__` entry.)*
- [x] **Integration:** MCP `get_journal_history` returns expected entries. *(`tests/integration/mcp/test_journal_tools_integration.py` — entries+provenance+ordering, limit pagination, other-user not-found; plus unit mapping + registration tests in `tests/unit/mcp/domains/journals/test_tools.py`.)*
- [x] **Regression:** full frontend unit suite (1383) green incl. `JournalDetailView` (feed child mocked); backend history/MCP unit + journal-history-endpoint/MCP integration suites green; `ruff` + `mypy` clean.

#### Phase 4: Type-Data History on the Remaining Write Surfaces (MCP + Integrations + Nested) ✅
**PR Size:** ~6 source / ~6 test files
**Status:** ✅ COMPLETE

Phase 2 made **every editable single-row type** produce type-data history on the **REST** surface (registry + completeness guard). This phase closes the remaining write surfaces so the same fields produce history no matter who writes them, completing AI-first parity ([Product Principles](../product-specifications/activity-history-product-specification.md#product-principles)) and the "all fitness and outdoor activity types" scope ([Scope](../product-specifications/activity-history-product-specification.md#scope)).

**Design (as built):**
- **MCP type-data parity.** The MCP `update_journal_entry` tool's type-data writes now route through `JournalWriteService.update_type_data` via a new `get_journal_write_service()` DI helper and an `_apply_mcp_type_data_update` dispatcher (`app/mcp/domains/journals/tools.py`), so they publish `JournalUpdated` and project to history with `Provenance.MCP` (and EVENT preserves the `calendar_info` calendar-sync marker). The duplicate `_update_*_data` helpers remain only for the **create** tool (create history is the `__created__` marker, matching REST). `GEAR_USAGE` is the one type the service does not own (checkout/checkin flow, no history coverage), so the dispatcher applies it directly via the extracted `_update_gear_usage_data` helper — preserving prior behaviour.
- **Nested per-row history (user-chosen granularity).** A `_TYPE_DATA_COLLECTIONS` registry + `diff_collection_rows` helper (`journal_write_service.py`) snapshot nested child collections before/after the update and diff them per-row into `{prefix}:{key}:{field}` history pairs (mirroring the route/gear convention): **PLAN documents** → `plan:doc:<uuid>:<field>` (ids preserved across updates by matching on `url`, so edits read as field changes, not churn; removed urls are deleted), **ABSEIL pitches** → `abseil:pitch:<pitch_number>:<field>`. Short surrogate keys keep `field_name` within `VARCHAR(100)` — no migration. This also **fixed the previously-broken PLAN type-data edit** (the `PUT /types/PLAN/data` endpoint used to raise "not yet supported" → 400); the create + update paths now share one `update_plan_type_data` helper.
- **Immich PHOTO_ALBUM metadata.** `ImmichAlbumOutboxEventProcessor` now takes an `OutboxEventPublisher` and, on update, diffs `album_name`/`asset_count`/`album_url` between the prior and new album reference data, publishing a `JournalUpdated` (`Provenance.IMMICH`, `changed_by="immich_album"`) only when they change. The inbound consumer wires the publisher; the publish commits within the consumer's `unit_of_work`.
- **TRAVEL nested children are deferred (no write path).** `save_flight`/`save_accommodation`/`save_transportation` have no callers and the `TravelTypeEditor` is a placeholder, so there is no write to record. TRAVEL's nested fields stay excluded-with-reason ("no write path — deferred until TRAVEL nested editing exists") in the coverage guard; the `update_type_data` TRAVEL branch still raises.

**Acceptance Criteria:**
- [x] MCP type-data writes produce the same history as the REST path — routed through `JournalWriteService.update_type_data` with `Provenance.MCP`; EVENT calendar sync preserved (`calendar_info` marker emitted). *(`_apply_mcp_type_data_update`; `get_journal_write_service`.)*
- [x] Nested-collection and integration-managed type data produce history: PLAN document changes (per-row `plan:doc:<id>:<field>`), Immich PHOTO_ALBUM metadata changes (album name/asset count/url), and ABSEILING per-pitch changes (per-row `abseil:pitch:<n>:<field>`); coverage guard `_EXCLUDED_FIELDS` reasons updated and a new `_TYPE_DATA_COLLECTIONS` consistency guard added. *(TRAVEL nested deferred — no write path.)*
- [x] No history is produced when a write changes nothing, on every surface. *(Empty diff → no event; unit tests cover the no-op cases.)*

**Required Test Coverage:**
- [x] **Unit:** `diff_collection_rows` (PLAN documents: created/updated/deleted/no-op; field-name length guard) and the ABSEIL pitch collection spec; the MCP dispatcher delegation + GEAR_USAGE bypass; the Immich metadata-diff publish / no-op-suppress; coverage-guard reasons + `_TYPE_DATA_COLLECTIONS` consistency. *(`tests/unit/journal/test_type_data_changed_fields.py`, `test_type_data_history_coverage.py`, `tests/unit/mcp/domains/journals/test_tools.py`, `tests/unit/core/integrations/test_immich_album_outbox_processor.py`.)*
- [x] **Integration (end-to-end backend):** through the real service + outbox + relay + consumer path — an **MCP** type-data edit (history via the endpoint, `Provenance.MCP`), a **PLAN** document add/edit/remove (per-row, grouped to the journal), an **ABSEIL** pitch edit (per-pitch), and an **Immich** album metadata change (`Provenance.IMMICH`) — plus a PLAN type-data endpoint regression (no longer 400). *(`tests/integration/infrastructure/events/test_journal_history_projection_e2e.py`, `tests/integration/api/test_journal_endpoints.py`.)*

#### Phase 5 (deferred): TRAVEL Nested Editing + Per-Row History
**Status:** ⬜ NOT STARTED (deferred from Phase 4 — blocked on a missing write path, not history)

Phase 4 discovered that TRAVEL nested children (**flights / accommodations / transportation**) have **no write path at all**: `TravelDataRepository.save_flight` / `save_accommodation` / `save_transportation` have zero callers, the `update_type_data` TRAVEL branch raises "not yet supported", and `TravelTypeEditor.tsx` is a placeholder. History for a write that cannot happen is impossible, so these fields stay **excluded-with-reason** ("no write path — deferred until TRAVEL nested editing exists") in the coverage guard.

This phase is primarily a **feature** (TRAVEL nested editing), with history falling out for free once the writes exist:
- [ ] Implement TRAVEL nested write paths: extend `update_type_data` (+ a `update_travel_type_data` helper shared with the create path) to persist flights/accommodations/transportation with replace semantics (match-by-natural-key, delete removed), mirroring the PLAN documents implementation; wire the `TravelTypeEditor` UI to the `PUT /types/TRAVEL/data` endpoint.
- [ ] Add `travel:flight:<key>:<field>` / `travel:accom:<key>:<field>` / `travel:transport:<key>:<field>` entries to `_TYPE_DATA_COLLECTIONS` so the edits produce per-row history (reuse `diff_collection_rows`); move the TRAVEL fields from `_EXCLUDED_FIELDS` to covered, updating the coverage guard.
- [ ] Unit + integration (real service → outbox → relay → consumer) coverage mirroring the PLAN/ABSEIL tests; "no change → no event"; plus the relevant UI/RTL coverage for the new editor wiring.

---

### ITER12-003: Migrate Contacts to Event-Driven Projection

**Objective:** Move contact history onto the same event-driven projection and remove the synchronous dual-write, completing "integrity by construction" without changing the user-visible feed.

**Specification Reference:**
- [Activity History — Product Principles (Integrity by construction)](../product-specifications/activity-history-product-specification.md#product-principles)
- [Activity History — Delivery Notes](../product-specifications/activity-history-product-specification.md#delivery-notes)

**Acceptance Criteria (task-level):**
- [x] Contact history is produced solely by the `HistoryProjectionConsumer` from contact events. *(Phase 2: contact event types added to the live subscription; `ContactHistoryService` is read-only.)*
- [x] The synchronous `history_service.record_*` dual-write is removed. *(Phase 2: removed from contact/relationship/merge/summary services; no `record_*` call sites remain in `app/`.)*
- [x] The contact activity feed is unchanged for users; the full existing contact-history suite passes via the event path. *(Phase 2: bulk re-save suppresses per-item markers via `affects_history=False`; full contact E2E + integration regression green.)*

#### Phase 1: Enrich Contact Events + Extend Projection Consumer ✅
**PR Size:** ~7–9 files (slightly exceeded with full provenance plumbing across 3 services + the summary consumer, plus tests)
**Status:** ✅ COMPLETE

Carry provenance on contact events and teach the consumer to project them — **before** removing the dual-write, to avoid a gap.

**Design (as built):**
- Every contact event in `app/core/contacts/models/events.py` gained `source: Provenance` + `changed_by: str` (stored in `event_data`), plumbed from the existing controller/MCP/worker `changed_by`/`source` values through `contact_service.py`, `contact_relationship_service.py`, and the bulk `_save_*` helpers.
- **`ContactUpdated` stays the single event for sub-entity field edits.** Method/address/note field edits continue to publish `ContactUpdated` with a per-sub-entity key (`"method_{id}_{field}"`) — it is a core contact event that downstream consumers (and search) rely on, so it was kept rather than replaced with new event types. `HistoryService._project_contact_updated` **decodes** that key (`_SUBENTITY_FIELD_RE`) back to the correct `contact_method`/`contact_address`/`contact_note` row; plain keys stay on the contact. No search-indexer change was needed.
- Summary changes had **no event**; a new `ContactSummaryUpdated` is now published from `SummaryGenerationService` alongside the history write. The pair is wrapped in a **SAVEPOINT** (`_record_summary_history`) so history and event commit/rollback together (the event publisher + connection are wired in `summary_consumer.py`).
- `HistoryService.project_event` gained per-contact-event handlers (`_row` generalised with an `entity_type` parameter), each reproducing the **exact** rows the dual-write's `record_*` writes — validated by unit-level row assertions and a real-service→outbox→projection equivalence test.
- **Inertness:** the contact event types are defined in `_CONTACT_HISTORY_EVENT_TYPES` but **deliberately kept out** of the consumer's live `event_type_patterns`, so production never double-writes while the dual-write remains. Phase 2 adds them to the subscription and removes the dual-write atomically.
- *Known, documented Phase-2 follow-ups (inert now): see the "Deferred from ITER12-003 Phase 1" list under Phase 2 below.*

**Acceptance Criteria:**
- [x] Contact domain events (`ContactCreated`, `ContactUpdated`, `ContactDeleted`, relationship/tag/important-date/summary events) carry `source` + `changed_by` in `event_data`, plumbed from the existing controller/MCP/worker provenance values. *(All contact events enriched; new `ContactSummaryUpdated` covers summaries.)*
- [x] A "contact" aggregation strategy (already extracted in ITER12-001) is used by the projection reads. *(Unchanged; projection writes to the same `contact`/`contact_method`/… entity types the contact strategy reads.)*
- [x] `HistoryProjectionConsumer` extended to handle the contact event types, writing the same rows the dual-write produces today (validated against snapshots), still idempotent. *(`HistoryService` contact handlers; equivalence proven by `test_*_projection_equals_dual_write`; idempotency by the unique-index `ON CONFLICT DO NOTHING`.)*
- [x] The dual-write remains in place this phase; the consumer is prevented from double-writing until Phase 2. *(Contact types kept out of the live subscription — inertness invariant unit test + an end-to-end inertness integration test confirm `_process_batch` projects no contact rows.)*

**Required Test Coverage:**
- [x] **Unit:** contact events carry `source`/`changed_by`; `project_event` for each contact event type yields rows equivalent to the current `record_*` output, including the `ContactUpdated` sub-entity-key decoding. *(`tests/unit/contacts/test_events.py`, `tests/unit/history/test_history_service.py`, `tests/unit/infrastructure/events/test_history_projection_consumer.py` inertness invariant.)*
- [x] **Integration:** consumer projects contact events into equivalent history rows (compared against the dual-write output), idempotently. *(`tests/integration/infrastructure/events/test_contact_history_projection_integration.py`: per-event projection, redelivery idempotency, end-to-end inertness, and real-service→outbox→projection equivalence for base-field and method-field updates.)*
- [x] **Regression:** affected unit dirs (contacts/history/events/search) + journal/summary unit suites green; contacts/events/history/summary integration tests green; full contact E2E specs (activity feed, inline editing, CRUD/search, tags, relationships, summary) green; `ruff` + `ruff format` + `mypy` clean.

#### Phase 2: Remove the Synchronous Dual-Write ✅
**PR Size:** ~8 production files (test/doc updates push the total higher)
**Status:** ✅ COMPLETE

Switch contacts fully onto the projection and delete the redundant write path.

**Design (as built):**
- The ~24 `history_service.record_*` dual-write calls were removed from `contact_service.py`,
  `contact_relationship_service.py`, `summary_generation_service.py`, **and**
  `contact_merge_service.py` (a later ITER13 addition that recorded an inline `merged_from`
  row with **no** paired event — it now publishes a `ContactUpdated` carrying
  `{"merged_from": (source, survivor)}`, which the projection decodes to the same
  contact-level audit row). Every removed write left its paired domain event in place, so
  history is now derived solely from events.
- `ContactHistoryService` is now **read-only** (its `record_*` methods deleted); it still backs
  the REST `GET /api/contacts/{id}/history` endpoint, the MCP `get_contact_history` tool, and the
  summary generator's history reads. The now-unused write dependency was dropped from the
  relationship, merge, and summary services (and their Dishka providers).
- **Bulk re-save spurious markers (the main correctness gate) — resolved by suppression.** A new
  `affects_history: bool = True` flag on `ContactMethodAdded`/`ContactAddressAdded`/
  `ContactNoteAdded`/`ImportantDateAdded`/`TagAssigned` (in `event_data`) lets the
  **bulk** `update_contact` re-save path (`_handle_update_relations`) emit those per-item events
  with `affects_history=False`; `HistoryService` skips them. The aggregate `ContactUpdated` rows
  (`contact_methods`/`addresses`/`notes`/`important_dates`/`tags`) remain the feed, byte-for-byte
  as before. **Search still consumes the events** (it ignores the flag), so tag/important-date
  indexing is unaffected. Create and standalone add/assign paths keep the default `True`, so their
  per-item "created"/tag markers (which the dual-write *did* record) are preserved.
- **Tags-on-bulk decision (deliberate):** suppressed — the aggregate `tags` row is the feed, so a
  bulk update shows one aggregate `tags` row, not per-tag rows. Locked by the headline
  `test_bulk_update_produces_no_spurious_subentity_markers` integration test.
- Summary: `_record_summary_history` now only publishes `ContactSummaryUpdated` (the
  `record_summary_change` write was dropped); it is written to the outbox on the summary
  connection so it commits atomically with the summary row.
- Contact event types added to the `HistoryProjectionConsumer` live `event_type_patterns`
  (`_JOURNAL_HISTORY_EVENT_TYPES + _CONTACT_HISTORY_EVENT_TYPES`); the Phase 1 inertness invariant
  test was flipped to assert the contact projection is now live.

**Acceptance Criteria:**
- [x] Direct `history_service.record_*` calls removed from `contact_service.py`, contact controllers, and relationship controllers; the `changed_by`/`source` arguments now feed the published events instead. *(Also removed from the merge + summary services; no `record_*` call sites remain in `app/`.)*
- [x] Contact history is produced only by the projection consumer. *(Contact event types added to the live subscription; `ContactHistoryService` is read-only.)*
- [x] No duplicate entries; ordering and content match prior behaviour. *(Unique-index idempotency proven end-to-end; full contact E2E + integration regression green.)*
- [x] The bulk re-save spurious-marker and tags-on-bulk issues (carried over from Phase 1, above) are resolved so the live projection matches the prior feed; contact event types are added to the `HistoryProjectionConsumer` live subscription (`_CONTACT_HISTORY_EVENT_TYPES`). *(`affects_history=False` on bulk re-save events; aggregate rows are the feed.)*

**Required Test Coverage:**
- [x] **Integration (end-to-end):** through the real service + outbox + relay + consumer path, contact create/update/tag/relationship/important-date/summary changes produce the expected history; no duplicates; **a full-contact update that touches sub-entities produces no spurious `created` markers**. *(`tests/integration/infrastructure/events/test_contact_history_projection_integration.py` — `TestContactProjectionEndToEnd`: create+sub-entity markers, base/method-field update, tag assign, important-date add, relationship create, summary update, end-to-end redelivery idempotency, and the headline `test_bulk_update_produces_no_spurious_subentity_markers`.)*
- [x] **Regression:** the full existing contact-history unit + integration suite passes against the event-driven path; `contact-activity-feed.spec.ts` E2E passes (with `toPass` polling for async projection). *(Unit 1407 frontend / full backend unit green; contacts/history/events/api/mcp integration green; `affects_history` flag verified search-safe via the search-indexer suite; 7 activity-feed + 33 contact-regression E2E tests green on Chromium.)*

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
| ITER12-002: Journal History (end-to-end) | 4 | 4 |
| ITER12-003: Migrate Contacts to Projection | 2 | 2 |
| **Total** | **8** | **8** |

## Risks & Mitigations

- **Async visibility lag** (history appears moments after a change): UI/E2E use `waitFor`; React Query stale time is acceptable for an audit log. Inherent to the event-driven design.
- **Duplicate rows on stream redelivery:** unique index `(event_id, entity_type, entity_id, field_name)` + `ON CONFLICT DO NOTHING` (covered by Phase ITER12-001/2 tests).
- **Contact regression from removing the dual-write:** sequenced last; full existing contact suite is the gate; provenance added to events *before* the dual-write is removed.
- **Routes/gear not grouping to their journal:** `journal_id` added to `RouteUpdated`/`RouteDeleted`/`GearItemUpdated` (ITER12-002 Phase 1).
- **Lost provenance during migration:** event enrichment lands before the corresponding dual-write removal in every case.
