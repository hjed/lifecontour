# Iteration 18: Home Dashboard and Tasks

**Status:** 🟡 IN PROGRESS — fully broken down: 5 iterations, **61 phases**, one PR each, with per-phase
acceptance criteria and diff estimates calibrated against iteration 17's recorded actuals.
**ITER18-001 Phases 1–6 and 9 complete** (task tables + domain entity; task repository; journal-date
resolution and the future-dated rule; the creation service and its core invariants; create over REST and
MCP; the status lifecycle over both surfaces; text update and delete over both surfaces).
**ITER18-002 Phases 1 and 3 complete** (the delete guard: journal deletion is refused, explanatorily, for
any journal anchoring a task; and merge, which is never refused — it re-points task links onto the
survivor and de-duplicates them, so `POST /api/journals/{id}/merge` can no longer raise a raw integrity
error). **ITER18-002 Phase 2 must merge next**, per the Sequencing Strategy — the delete refusal is not
yet shaped for REST and MCP callers.
**Dependencies:** Iteration 4 (journal core, contact relationships, event date ranges), Iteration 7
(daily summaries, calendar sync, day-grouped journal browsing, journal merge), Iteration 12 (unified
event-driven field history), Iteration 5 (Redis Streams event bus, outbox relay, stream consumers),
Iteration 16 (the outdoor logbook dashboard — the composite read-only projection precedent)
**Goal:** Introduce **Tasks** as a journal-anchored core entity and replace the placeholder home page
with the daily-briefing **Home Dashboard**, with full MCP parity, delivering the
[Home Dashboard & Tasks Product Specification](../product-specifications/home-dashboard-and-tasks-product-specification.md).

## Overview

Two intertwined pieces of work. **Tasks** are a new core entity: short commitments anchored to exactly
two journals — the journal the commitment arose in and the future journal where it matters. **The Home
Dashboard** replaces `/`, which today is six static cards, with the user's daily briefing: the AI summary
as the headline over three evidence sections (agenda, tasks due this week, upcoming contact dates).

The two ship together because neither is complete alone: the dashboard is where tasks surface, and tasks
are much of what makes the dashboard worth opening. The specification's *Delivery Notes* name the
incoherent splits explicitly, and the iteration boundaries below are drawn to avoid every one of them.

Almost all of the supporting machinery already exists — daily summaries, event journals with times and
participants, contact important dates with precision, the domain-event outbox and its stream consumers,
the shared field-history projection, and a precedent for a read-only composite dashboard endpoint. Tasks
are the only genuinely new entity.

### Key References

- **Product specification:** [Home Dashboard & Tasks](../product-specifications/home-dashboard-and-tasks-product-specification.md)
  — the behaviour contract for everything below.
- **Wireframe:** [Home Dashboard Wireframe](../design/home-dashboard-wireframe.md) — the numbered
  structural inventory (**W1**–**W33**) that the dashboard acceptance criteria are checked against, and
  the durable [Claude Design link](https://claude.ai/design/p/488fbcbb-4dea-4005-ad0c-56b290e3055e?file=Home+Dashboard.dc.html).
- **Related specifications:** [Journals](../product-specifications/journals-product-specification.md)
  (daily summary, merge, cancellation stance), [Contacts](../product-specifications/contacts-product-specification.md)
  (importance signals), [Activity History](../product-specifications/activity-history-product-specification.md)
  (provenance).
- **Architecture:** [Domain Architecture](../architecture/domain-architecture.md),
  [API Design](../architecture/api-design.md) (including the *Outdoor Dashboard Endpoint* section — the
  singleton-resource convention this work reuses),
  [Database Design](../architecture/database-design.md#transaction-management--commit-timing),
  [Frontend Design](../architecture/frontend-design.md),
  [Integration Architecture](../architecture/integration-architecture.md#redis-stream-consumer-architecture)
  (consumer group table).

## Current Baseline (verified)

Verified against the code at the time of writing, not assumed.

### Tasks

**Nothing existed** at the time of writing — no table, entity, service, endpoint, MCP tool, or frontend
surface, and no `tasks` string anywhere in the domain layer. Every part of the tasks model in ITER18-001
is new.

**Since ITER18-001 Phase 1:** the `tasks`, `task_intermediate_journals` and `task_contacts` tables exist
(migration `0105`), as do the `Task` entity and `TaskStatus` enum in
`core_shared/core_shared/models/tasks/`.

**Since ITER18-001 Phase 2:** the persistence layer exists — the `TaskRepository` port
(`backend/app/core/tasks/models/repositories.py`), its `SqlTaskRepository` adapter, and `TaskProvider`
registered in both the application and integration-test containers. It covers save / find-by-id /
delete plus intermediate-journal and contact link add, remove and list, all owner-scoped, with
idempotent link adds. There is still no service, endpoint, MCP tool or frontend surface, and no
invariant enforcement beyond task ownership.

**Since ITER18-001 Phase 4:** tasks are creatable in the domain. `TaskService.create_task`
(`backend/app/core/tasks/services/task_service.py`, provided at request scope by `TaskProvider`)
enforces the specification's core invariants as one `@transactional` unit of work — both anchors exist
and belong to the acting user, the due journal is future-dated at the moment it is set, creating and
due may be the same journal, and referenced contacts exist — raising `TaskAnchorJournalNotFoundError`
(404) or `TaskDueJournalNotFutureError` (400). There is still no endpoint, MCP tool or frontend
surface, and no status, retargeting or link operation beyond what creation writes.

**Since ITER18-001 Phase 5:** tasks are creatable by a user. `POST /api/journals/{journal_id}/tasks`
(`backend/app/api/tasks/`) and the MCP tool `create_task` (`backend/app/mcp/domains/tasks/tools.py`)
both call the `@transactional` service and open no transaction of their own; the shared MCP error
handler now renders `TaskDomainError`s rather than flattening them into "internal error". Neither
surface accepts a date or the service's `now`. There is still **no way to read a task back** — no get,
no list, no frontend surface — and no status, retargeting or link operation. Because tasks now hold
`ON DELETE RESTRICT` references to journals, **journal delete and merge can fail at the database**
until ITER18-002 Phases 1–3 land.

**Since ITER18-001 Phases 6 and 9:** a task can be moved through its lifecycle, reworded and destroyed.
`PATCH /api/tasks/{id}` carries the text, the status, or both; `DELETE /api/tasks/{id}` answers 204 and
takes the task's link rows with it, leaving the journals and contacts alone. The MCP tools are
`create_task`, `set_task_status`, `update_task_text` and `delete_task`. `TaskService.update_task` owns
text and status under one `FOR NO KEY UPDATE` read and one write, and `set_status` delegates to it, so
neither surface can drift from the other. There is still **no way to read a task back**, no retargeting
(Phases 7–8) and no link operation (Phases 10–11).

### The home page

- `frontend/src/app/page.tsx` renders six static `Card`s (Contacts, Journal, Calendar, Photos, AI
  Integration, System Status) inside an `AuthGuard`. It fetches nothing.
- Its Jest test `frontend/src/__tests__/app/page.test.tsx` asserts the heading, subtitle, layout classes
  and all six cards, driven by the `homePageTestUtils.FEATURE_CARDS` fixture in
  `frontend/src/test-utils/index.tsx`. **All three must be retired together** with the placeholder — the
  fixture exists only for this page.
- Chrome comes from `frontend/src/app/layout.tsx`: sticky `Header`, fixed `DesktopSidebar`, and
  `main.md:pl-64 > .container.mx-auto.px-4.py-6` with a `Breadcrumb`. This matches the wireframe's frame
  (**W1**) exactly, so the dashboard needs no chrome changes.
- `Header.tsx` links `/` from the home icon. The sidebar (`Sidebar.tsx`, `navigationSections`) has
  **no** entry for the home page.

### Daily summaries

- `DailySummaryService` (`backend/app/core/journal/services/daily_summary_service.py`) orchestrates
  cache check → input assembly → eligibility → `GENERATING` marker (its own unit of work) → Gemini call
  with no transaction held → persist. Timezone comes from `UserSettingsRepository` with
  `DEFAULT_TIMEZONE` fallback (`app/core/settings/timezone_utils.py`).
- Inputs are assembled by `DailySummaryInputAssembler` into `DailySummaryInput` (journals, journal
  count, event count, contact names, mood values) — **journal-only today**.
- `DailySummaryEligibilityChecker.DEFAULT_MIN_JOURNALS = 2`, applied to every day including today.
- Cached in `journal_daily_summaries` (migration `0049`), unique on `(user_id, summary_date)`, with
  `status` ∈ pending/generating/generated/failed/disabled and the four counters the wireframe's stat
  footer (**W10**) displays. `JournalDailySummary.get_display_text()` returns text only when
  `GENERATED`.
- Surfaces: `GET /api/journals/daily-summary/{date}` and
  `POST /api/journals/daily-summary/{date}/regenerate`
  (`backend/app/api/journals/daily_summary_controller.py`); MCP `get_daily_summary`; frontend
  `DailySummaryView` inside `DayGroupedJournalList`.
- **Cache invalidation lives in the search consumer**: `SearchIndexerConsumer`
  (`app/infrastructure/events/search_indexer_consumer.py`) invalidates summaries for
  `_JOURNAL_INVALIDATION_EVENTS = {JournalCreated, JournalUpdated, JournalDeleted}`. There is **no**
  staleness rule — a summary generated yesterday for today's date is served from cache today.

### Journals

- `Journal` (`core_shared/models/journals/entities.py`) carries `user_id`, `title`, `content`,
  `event_date_range` (`EventDateRange` value object, start/end timestamps) and hierarchy fields. There is
  **no status column on the journal itself**.
- **Cancellation is per-event-type data**: `CalendarInfo.event_state` is an `EventState`
  (`invited`/`tentative`/`confirmed`/`cancelled`). The frontend already derives
  `isCancelled = type_data.event.event_state === EventState.CANCELLED` in `JournalListItem.tsx`, which
  is the same signal the agenda (**W18**) and the cancelled-due-journal lapsed rule need.
- All-day vs timed lives on `CalendarInfo` too (`is_all_day`, `start_time`, `end_time`, `location`,
  `timezone`) — everything the agenda's ordering rules (**W12**, **W13**) require.
- Delete: `JournalWriteService.delete_journal` (`@transactional`) → `JournalService.delete_journal`;
  REST `DELETE /api/journals/{id}`; MCP `delete_journal`. **No blocking concept exists today.**
- Merge: `JournalMergeService` (`journal_merge_service.py`) absorbs content, tags, contacts, type data,
  routes and children, then deletes the source; REST `POST /api/journals/{id}/merge`; MCP
  `merge_journals`. Any new task links must be added to its re-pointing set.
- Day grouping in the list is **client-side** (`frontend/src/lib/journal-grouping.ts`,
  `groupJournalsByDay`) over local time; server-side windows are computed in the user's timezone (see the
  outdoor dashboard, below).

### Contacts

- Important dates: `contact_important_dates` (`app/infrastructure/contacts/contact_tables.py`) with
  `date_type` ∈ `birthday`/`marriage_anniversary`/`work_anniversary`/`first_met`/`custom` (+
  `custom_date_types`), and `precision` ∈ `full`/`day_month`/`year` (`DatePrecision`,
  `core_shared/models/contacts/important_date_types.py`), constrained so `day_month` has no year and
  `year` has no month/day.
- The only read path is `ContactRepository.get_important_dates(contact_id)` — **there is no query for
  "important dates occurring in a window"**, and recurrence is not resolved anywhere. Both are new work
  in ITER18-004.
- **Importance is a search-side concern today**: `CONTACTS_INDEX_SETTINGS`
  (`app/infrastructure/search/meilisearch_client.py`) appends `is_favourite:desc`,
  `journal_count_30d:desc`, `activity_count_30d:desc` after the six standard MeiliSearch rules — that
  precedence order is pinned by `tests/unit/infrastructure/search/test_ranking_rules.py`. The values are
  computed when indexing (`search_indexer.py`) and exposed to the frontend through
  `meta.search_metadata` (`frontend/src/utils/searchUtils.ts`, `extractContactRankingSignals`). No SQL
  path produces them, so the dashboard needs one.

### Events, history and search

- Publish path: services publish through `OutboxEventPublisher` inside their unit of work → `OutboxRelay`
  (`outbox_relay.py`) publishes unrelayed rows to the `pms:domain-events` Redis stream → consumer groups.
- Consumers (`docs/architecture/integration-architecture.md`): `search-indexer`,
  `history-projection`, `summary-generator`, `inbound-processor`, `google-worker`, over the shared
  `StreamConsumer` base with declarative `routes` / `event_type_patterns` and a `DeadLetterConsumerMixin`.
  A consumer only sees the patterns it subscribes to, so **an unrecognised event type is ignored by
  construction** — no change is needed to make the search indexer skip task events, only a test pinning
  it.
- History: `field_history` is entity-agnostic (`entity_type`, `entity_id`, `field_name`, `old_value`,
  `new_value`, `changed_by`, `source`, `event_id`, `created_at`).
  `HistoryService.project_event` (`app/core/history/services/history_service.py`) is a pure
  event → rows mapping with a `_HANDLERS` dispatch table keyed on event type;
  `HistoryProjectionConsumer` owns the idempotent writes (`ON CONFLICT DO NOTHING` on
  `(event_id, entity_type, entity_id, field_name)`). Reads go through
  `FieldHistoryRepository.get_history_for_aggregate(root_type, id, …)` with per-root-type aggregation
  strategies (`"journal"`, `"contact"`), wrapped by thin read services
  (`JournalHistoryService`, `ContactHistoryService`).

### The composite-dashboard precedent

`OutdoorDashboardService` (`app/core/journal/services/outdoor_dashboard_service.py`) +
`SqlOutdoorDashboardRepository` + `GET /api/journals/outdoor-dashboard` +
`OutdoorDashboardResource` (a **singleton JSON:API resource whose id is the user id**) + MCP
`get_outdoor_dashboard` + `frontend/src/app/journals/outdoor-logbook/page.tsx` with one shared TanStack
query (`frontend/src/lib/api/outdoor-dashboard.ts`) feeding independent widget components. It is
read-only (no unit of work), takes no date parameters, and anchors every window on "today" in the user's
configured timezone. ITER18-004 follows this shape.

### Gap summary

| Capability the specification requires | Today | Iteration |
|---|---|---|
| Tasks entity, invariants, lifecycle, journal anchoring, retargeting, lapsed | Nothing exists | ITER18-001 |
| Tasks visible and actionable on journals; created from a journal | Nothing exists | ITER18-001 |
| Tasks over MCP with identical invariants | Nothing exists | ITER18-001 |
| Journal delete blocked by task anchors, with explanatory errors | Delete always succeeds | ITER18-002 |
| Merge re-points task links; cancellation lapses not-done tasks | Merge re-points tags/contacts/children only | ITER18-002 |
| Task domain events, field history, contact activity records | Nothing exists | ITER18-003 |
| Tasks excluded from search without breaking the indexer | True by construction, untested | ITER18-003 |
| Home dashboard with summary, agenda, tasks, upcoming dates | Six static placeholder cards | ITER18-004 |
| Important dates occurring in the next seven days, recurrence resolved | No windowed/recurrence query | ITER18-004 |
| Contact importance ranking outside search | MeiliSearch ranking rules only | ITER18-004 |
| Home page in the primary navigation as the default view | Header icon link only | ITER18-004 |
| Summary inputs extended with agenda, tasks and dates | Journal-only inputs | ITER18-005 |
| Today always eligible for a summary | Two-journal threshold applies to today | ITER18-005 |
| Today's summary regenerated when it was not generated today | No staleness rule | ITER18-005 |
| Invalidation follows summary inputs, lazily | Journal events only | ITER18-005 |

## Delivery Rules

These apply to every iteration and every phase below.

1. **Tests first.** Write the failing tests for the slice before implementing it. No exceptions.
2. **Green main.** Do not merge a phase unless the relevant tests, linting and type checks pass.
3. **Reviewable PRs.** Each phase is **one PR**, independently mergeable, of roughly **≤ 500 changed lines
   including tests**. Estimates below are derived from the measured record in
   *[Phase Sizing Calibration](#phase-sizing-calibration)*, not guessed. If an estimate grows past 500
   mid-implementation, split the phase rather than raising an oversized PR — unless splitting would break
   rule 9, in which case the overrun is recorded in the phase before work starts.
4. **The specification is the acceptance bar; the wireframe is the acceptance bar for layout.** Where they
   conflict, the specification wins and the divergence is recorded in
   [the wireframe document](../design/home-dashboard-wireframe.md) *and* here.
5. **MCP parity in the same phase.** A capability that lands in REST or the UI lands in MCP in the same
   phase, never as a trailing task. MCP tools are controller-equivalent: they call `@transactional`
   services and never open transactions themselves.
6. **Transactions in the service layer.** Every write commits via `@transactional` or
   `unit_of_work(connection)`; controllers and MCP tools open none. There is no commit backstop.
7. **Reuse before rebuild.** Prefer extending existing components, services and helpers (the outdoor
   dashboard projection shape, `EventDateRange` windowing, `HistoryService` dispatch, the shared history
   feed, `TestDataManager`) over new parallel machinery. Where extraction would bloat a PR, duplicate and
   record the consolidation as follow-up here.
8. **No accumulating backlog.** Nothing in this iteration may introduce a `/tasks` route, a global task
   list, or a task index. If a phase finds itself needing one, that is a design error, not a scope
   increase.
9. **Every phase is shippable.** No phase may rely on a later phase to restore behaviour it broke.
10. **Record decisions and follow-ups here.** Divergences, deferrals and discoveries are appended to this
    document as they happen, in the style of iteration 16 and 17.

## Phase Completion Requirements

Every phase must meet the same bar before merge:

- `main` is green at the end of the phase.
- Explicit **unit, integration and e2e** coverage. E2E may be deferred only for a phase with no
  user-visible surface, and the deferral must be stated in the phase.
- E2E is deterministic and fixture-driven: each test creates its own journals, tasks, contacts and dates.
  No conditional logic on data state, no skipping on missing data, no multi-outcome assertions. Empty
  states get their own tests, never an `if` branch inside a populated one.
- Timezone-sensitive behaviour is tested across a day boundary, not only at midday. Date windows are
  anchored with `UserSettingsRepository.get_timezone`, never UTC-today.
- Linting, type checking and the narrowest reliable test targets for the slice pass.

## Phase Sizing Calibration

Every phase estimate below is calibrated against what previous iterations actually cost, because
[iteration 17](./iteration-17-journal-tags-parity.md) recorded both numbers for every phase it shipped.
Twelve of its thirteen shipped phases have a recorded actual, and **every one of those overran its
estimate**:

| Phase | Estimated | Actual (tracked diff) | Ratio | What drove it |
|---|---:|---:|---:|---|
| ITER17-001 P1 — description column + MCP listing | 350 | *not recorded* | — | the one shipped phase with no actual |
| ITER17-001 P2 — tag update, REST + MCP | 500 | ~900 | 1.8× | MCP tools added in two domains; shipped as two commits |
| ITER17-001 P3 — delete parity, REST + MCP | 400 | ~630 | 1.6× | same shape, smaller service change |
| ITER17-001 P4 — tag merge, REST + MCP | 500 | ~1050 | 2.1× | repository SQL + validation + both domains' tools |
| ITER17-002 P1 — backend multi-tag filtering | 450 | ~720 (190 prod + 530 test) | 1.6× | tests 2.8× production |
| ITER17-002 P2 — frontend params + deep link | 350 | ~700 (200 prod + 500 test) | 2.0× | tests 2.5× production |
| ITER17-003 P1 — shared tags editor extraction | 500 | ~1360 | 2.7× | extraction rewrote the existing contact call sites |
| ITER17-003 P2 — detail view wiring + e2e | 300 | ~1250 gross / ~90 net | — | deletions and moves dominate; net was tiny — the one phase that came in *under* estimate on a net basis |
| ITER17-004 P1 — sidebar tag tree | 450 | ~1000 (~260 prod, 70% tests) | 2.2× | test volume |
| ITER17-004 P2 — create/edit dialogs | 450 | ~3150 across 24 files | **5.8×** | shared-dialog migration of *both* domains at once |
| ITER17-004 P3 — delete/merge dialogs | 400 | ~711 (~130 prod, 81% tests) | 1.8× | test volume |
| ITER17-005 P1 — assignment/removal events | 450 | ~1440 | 3.2× | 2 event types + projection + every publish path |
| ITER17-005 **P2a** — tag rename events | 760 | ~1270 | 1.7× | 1 event type + projection; P2 as planned was estimated ~1200 before the 2a/2b split, and P2b (~700) has not shipped |

**Two different ratios live in that table, and conflating them is the trap.** The *Ratio* column is
estimate→actual (median **≈2.0×**) — useful for judging how optimistic an estimate is. It is **not** the
production→tracked multiplier. Iteration 17 recorded the production/test split for six phases, and that
multiplier is far larger:

| Phase | Production | Tracked | Multiplier |
|---|---:|---:|---:|
| ITER17-002 P1 | ~190 | ~720 | 3.8× |
| ITER17-002 P2 | ~200 | ~700 | 3.5× |
| ITER17-004 P1 | ~260 | ~1000 | 3.8× |
| ITER17-004 P2 | ~1040 | ~3150 | 3.0× |
| ITER17-004 P3 | ~130 | ~711 | 5.5× |
| ITER17-005 P2a | ~200 | ~1270 | 6.4× |

Median **≈3.8×**. Tests, fixtures and helpers are 60–81% of every diff this repo produces. The sizing
rules below follow from that record and apply to every phase in this document:

1. **Estimate production lines, then multiply by 4** for the tracked total. A ≤500-line PR therefore means
   **≤125 production lines**; ≤150 production lines lands near 600. Phase estimates below give both
   numbers, computed at ×4.
2. **Be honest about the achievable floor.** A phase shipping a service method + REST + MCP for one
   capability has never landed under ~630 in this repo (ITER17-001 P3) and typically costs ~900. Such
   phases are budgeted at **600–700 and flagged**, not written down to 500 and discovered later. The
   500-line standard is met by pure-logic, single-surface and frontend-component phases; capability
   triples sit above it and say so.
3. **One capability per phase**, where a capability is one service method plus the surfaces that expose it.
4. **Substantial validation gets its own phase.** Where a service method's own logic is the hard part
   (task invariants, retarget semantics, recurrence resolution, importance ranking), it ships as a
   service-plus-unit-tests phase *ahead* of the phase that exposes it. That phase is mergeable on its own:
   tested domain logic with no caller yet, exactly as ITER17-001 Phase 1 shipped a column before a UI.
5. **MCP parity stays in the same phase as its REST counterpart** (delivery rule 5) — never a phase later.
   Narrow the capability instead. This is the constraint that drove ITER17-001's overruns, and the
   response here is smaller slices, not deferred MCP.
6. **At most two new domain event types per phase.** Iteration 17's own conclusion, recorded verbatim
   there: *"a future phase adding an event type should budget ~600 test lines per type up front"* — borne
   out by ITER17-005 P1 (2 types, ~1440) and P2a (1 type, ~1270). This is why ITER18-003 is nine phases,
   not the three a naive reading would suggest.
7. **Never touch two domains in one phase.** ITER17-004 P2's 5.8× came entirely from migrating contacts
   and journals together. Phases here that read contact data (ITER18-004 Phases 7–9) do so through new
   read paths; the only phase that extracts from an *existing* contact/search code path
   (ITER18-004 Phase 8a) is isolated for exactly this reason.
8. **Component extraction or migration: assume the higher end (5×+)** and count every existing call site
   the change rewrites, not just the new component.
9. **Every new e2e spec file is its own phase** — budget ~150–250 lines per spec plus the
   `TestDataManager` helpers it needs, which are test infrastructure and count toward the diff.
10. **Coherence beats size.** Where splitting a phase would ship a dead end named in the specification's
    *Delivery Notes* (or break delivery rule 9), the phase stays whole and states its expected overrun in
    advance.
11. **Count test fixtures, factories and helpers; do not count generated output** (`ds-bundle/`, lockfiles,
    migrations' autogenerated boilerplate).
12. **Record the actual next to the estimate** when each phase lands, as iterations 16 and 17 did. That is
    what made these tables possible, and the next iteration's estimates depend on it. Record the
    production/test split too — six data points is a thin basis for a ×4 multiplier.
13. **A phase introducing a port + adapter pair is ×6, not ×4** — added after ITER18-001 Phase 2 came in
    at 1270 against a 440 estimate (2.9×) *and* against a 800-line pre-recorded overrun. Two costs the
    ×4 rule misses: a port ABC costs roughly as much as its adapter in a codebase that documents every
    abstract method (191 vs 288 lines there), and **owner scoping multiplies test volume**, because
    proving a second user cannot reach the first's data needs its own seeded foreign rows per method
    group. Count the port as a first-class production artefact, not a header file.
14. **A *rule-defining* phase is ×6 too** — added after ITER18-001 Phase 3 came in at 814 against a 360
    estimate (2.3×) with **no** port, adapter or owner scoping, so rule 13's stated cause cannot explain
    it. The common factor is narrower than "ports": when a phase's deliverable is a *decision* rather than
    a capability — which local date, is it future-dated, does this recur in the window — it is only
    meaningful at its boundaries, and every boundary is a test carrying the arithmetic that makes it
    readable. 123 production lines bought 28 tests there. **Apply ×6 whenever a phase's acceptance
    criteria read as a matrix**; ×4 remains right for phases that wire an existing rule to a new surface.
    ITER18-004 Phase 9 (important-date occurrence resolution) and Phase 10 (contact importance signals)
    are the next two this catches — both are estimated at ×4 today.
15. **A phase exposing an existing rule on N surfaces costs ~one rejection matrix per surface** — added
    after ITER18-001 Phase 5 came in at 2036 against a 600 estimate (3.4×) and **5.6× its own
    production**, despite being exactly the "wires an existing rule to a new surface" case rule 14 says
    ×4 still fits. It does not. The service was already written and tested, yet the endpoint and the MCP
    tool each needed the *whole* rejection matrix — 17 and 12 near-identical tests — because the two
    surfaces render errors through completely different machinery, and a shared service is no evidence
    that both callers reach it. That is not defensive over-testing: the phase found a real defect on
    exactly that seam (every task rejection reaching AI clients as "internal error"), invisible to the
    service and endpoint tests alike. **Budget a capability triple's *surfaces* at roughly the same test
    volume each, and take ×6-against-production as the working default for any phase with more than one
    entry point.** ITER18-001 Phases 6, 8, 9, 10, 11, 13 and 14 are all REST+MCP pairs estimated at ×4
    today.
16. **Estimate a multi-capability phase as N × S × properties, and prefer splitting it** — added after
    ITER18-001 Phase 9 came in at **3,300 tracked against a 600 estimate (5.5×) and 8.6× its own
    production**, well above Phase 6's 5.6×. Phase 9 shipped *two* capabilities (text update, delete) on
    *three* surfaces (service, endpoint, tool), and each surface re-asserted the same handful of
    properties per capability — editable in all three statuses, the lapsed case, no inferred link, the
    cross-user answer, the blast radius. Rule 15 budgets per surface; this refines it: the test volume
    is **capabilities × surfaces × properties**, so a second capability roughly doubles a phase that was
    already at rule 15's ceiling. Two consequences. **The 500-line limit in rule 3 is unreachable for any
    REST+MCP capability phase in this domain, and should be restated rather than repeatedly breached.**
    Phase 9's two halves come to ~1,300–1,400 lines *each*; even a single capability on three surfaces
    (Phase 6) came to 2,483. Delivery rule 5 requires MCP parity in the same phase, and a surface's tests
    are not optional — Phase 5 found a real defect on exactly that seam. The workable form of rule 3 for
    this iteration is **one capability per phase, ~1,500 tracked lines**, with the 500-line figure kept
    for phases that add no new entry point. And **the remaining capability phases should each carry one
    capability**: ITER18-001 Phases 10 (attach *and* detach), 11 (link *and* unlink, plus a batching
    follow-up) and 13 (get *and* list-by-journal) are each two capabilities under one heading and should
    be split, or re-estimated at roughly ×9 against production.

**Programme size:** 61 phases — and therefore 61 PRs — across the five iterations
(ITER18-001: 22, ITER18-002: 5, ITER18-003: 9, ITER18-004: 17, ITER18-005: 8). That count is the honest
consequence of a 500-line PR standard over a new core entity plus a new page; the alternative is fewer,
larger PRs that review badly. **Expected landing zone:** most phases 400–600 tracked lines, capability
triples 600–700, and the flagged exceptions up to ~750.

## Wireframe Conformance

The dashboard's layout contract is [the wireframe](../design/home-dashboard-wireframe.md), whose elements
are numbered **W1**–**W33**.

- Every UI-bearing acceptance criterion below cites the `W` element(s) it satisfies.
- The dashboard e2e suite must assert the **structural** wireframe facts, not screenshots: section order,
  all-day-before-timed ordering, the five-item cap, the show-more label, the cancelled marker, the
  collapsed-by-default tomorrow disclosure, and each declared state (**W33**).
- Any deliberate divergence must be recorded in both documents with its reason. The eight already known
  are listed under *Known gaps and divergences* in the wireframe document: gaps 1–4 and 8 are resolved by
  ITER18-004, gap 5 (lapsed presentation) by ITER18-001, and gaps 6–7 are informational.
- The wireframe is built from the real synced design system, so implementation uses the existing
  `components/ui` primitives. If a new shared primitive is genuinely needed, it must also be added to
  `frontend/.design-sync/` (entry, `componentSrcMap`, docs stub, preview) per `CLAUDE.md`.

## Sequencing Strategy

```text
ITER18-001 (tasks core) ──┬── ITER18-002 (anchor integrity)
                          ├── ITER18-003 (events + history)
                          ├── ITER18-004 (home dashboard) ── ITER18-005 (summary extension)
                          └──────────────────────────────────┘
```

Phase counts: ITER18-001 → 22, ITER18-002 → 5, ITER18-003 → 9, ITER18-004 → 17, ITER18-005 → 8.

0. **A hard ordering constraint cuts across iterations 001 and 002.** ITER18-001 Phase 1 gives the task
   anchors `ON DELETE RESTRICT` foreign keys, and ITER18-001 Phase 5 makes tasks creatable. From that
   moment, both `DELETE /api/journals/{id}` **and** `POST /api/journals/{id}/merge` — which ends by
   deleting the absorbed journal — raise a raw integrity error for any journal that anchors a task. Both
   are shipped features, so **ITER18-002 Phases 1–3 must merge immediately after ITER18-001 Phase 5**,
   before the rest of ITER18-001 proceeds. Treating anchor integrity as later clean-up breaks delivery
   rule 9 for every phase in between.
1. **ITER18-001 is otherwise the gate.** Everything else needs the entity, and it is the largest at 22
   phases. Useful cross-iteration starts: ITER18-004 Phases 1–12 (endpoint, page shell, summary card,
   agenda, occurrence resolution, importance signals, upcoming dates) and ITER18-005 Phases 1–2 need
   **nothing** from ITER18-001, so they can run in parallel with it from day one. ITER18-004 Phase 5 does
   need ITER18-001 Phase 3 (the shared date helper), and ITER18-005 Phase 3 needs ITER18-004 Phase 5.
2. **ITER18-002 and ITER18-003 are independent of each other** and can run in parallel once 001 lands.
   002 should not lag far behind 001: until it ships, deleting a journal can violate the model's core
   invariant (the specification names this as an incoherent split), so 001's phase plan must either
   include the delete guard or 002 must follow immediately.
3. **ITER18-004 needs 001** for its tasks section, and nothing else. Its summary and agenda sections
   depend only on what exists today, so its own phase split can front-load them.
4. **ITER18-005 needs 001** (tasks as inputs) and is *better after* 004 (the always-eligible-today rule
   is what keeps the dashboard headline from being blank on quiet days), but does not require it: the
   journals view consumes the same summary.
5. **ITER18-003 is not a prerequisite for anything user-visible**, but should not be deferred past 004 —
   a dashboard that mutates task state with no history trail is a gap in the activity-history contract.

## Iteration Breakdown

> Each iteration below is **independently deliverable**: it leaves the application working, is useful on
> its own, and does not depend on a later iteration to restore behaviour.
>
> **Phases are one PR each.** A phase must be independently mergeable — it breaks nothing on merge, ships
> its own tests, and leaves `main` green. The specification's *coherence* requirements (a tasks section
> needs its inline done action; a domain model needs journal display) bind at **iteration** granularity,
> not phase granularity: an intermediate phase may leave a capability reachable only over MCP, or a
> service method with no caller yet, provided nothing that previously worked is broken. Where a split
> would ship a user-visible dead end, the phase stays whole (calibration rule 8).
>
> Estimates are given as **production lines → tracked total** per calibration rule 1. Record the actual
> beside the estimate when each phase lands.

### ITER18-001: Tasks Core — Model, Anchoring, Lifecycle, Journal UI, MCP

**Objective:** Deliver the Tasks entity end to end: the model and its invariants, journal anchoring and
retargeting, the three-state lifecycle, contact links, lapsed behaviour, the REST surface, the matching
MCP tools, and the journal-facing UI that makes tasks creatable and actionable.

**Independently deliverable because:** on its own it gives the user (and an agent) the whole capture →
defer → complete → resurrect loop inside journals. It carries no dependency on the dashboard, and the
specification's *Delivery Notes* forbid the alternative split (a domain model without journal display
leaves tasks uncreatable and invisible).

**Relevant documents:**

- Specification §*Tasks* (product model, core invariants, creating a task, status and lifecycle, journal
  links and retargeting, lapsed tasks, contacts on tasks, where tasks appear)
- [Domain Architecture](../architecture/domain-architecture.md) (ports and adapters, domain enums),
  [API Design](../architecture/api-design.md) (JSON:API + FastMCP patterns)
- `creating-migrations` skill for migration naming; `writing-sql` skill before any query work
- Reference implementations: `journal_contact_relationship_repository.py` (explicit structured links),
  `JournalTagService` (validation-in-service, SQL-in-repository), `journal_tag_service` MCP tools (the
  REST+MCP-per-phase pattern from iteration 17)

**Acceptance Criteria:**

- [ ] Migration creates the task tables: a task (owner, text, status, creating journal, due journal) plus
      a link table for intermediate journals and one for contacts. Foreign keys express what the model
      requires: both anchors `NOT NULL`; intermediate and contact links cascade on delete of the task;
      the anchors do **not** cascade from the journal side (deletion is blocked in ITER18-002, so the
      FK must not silently destroy tasks in the meantime — `ON DELETE RESTRICT` or equivalent).
- [ ] Domain entity and status enum with exactly three values — not done (default), done, cancelled —
      following the project's domain-enum pattern.
- [ ] **Core invariants enforced in the service layer, identically for REST and MCP:** a task always has
      both a creating and a due journal; neither can be absent at any point in its life; the due journal
      must be an **existing** journal; the due journal's date must be in the future relative to today in
      the **user's timezone** at the moment it is set; creating and due may be the same journal.
- [ ] A journal's date for invariant purposes is the date of its `event_date_range.start` interpreted in
      the user's timezone — the same date the journal list groups it under.
- [ ] Invariant 4 is checked **only when the due journal is set**, never continuously. A task whose due
      journal has moved into the past is lapsed, not invalid.
- [ ] **No bare date picker and no implicit journal creation** on any surface, including MCP. Attempting
      to set a due journal that does not exist, or that is not future-dated, returns a clear, actionable
      error naming the constraint.
- [ ] Creating a task takes its creating journal from the journal it is created *from* — never chosen
      separately — plus text, a due journal, and optionally contacts.
- [ ] Status transitions: done is reversible; cancelled is soft and reversible **only** by retargeting to
      a new future journal (which returns the task to not done); marking done or cancelled requires no
      journal and creates no journal link; text and contact links are editable in any status.
- [ ] Hard delete exists but is the exception: the UI leads with cancel and treats delete as secondary,
      matching the journals specification's stance.
- [ ] **Retargeting:** the creating journal is immutable; the due journal may be retargeted at any time in
      any status; the previous due journal is **automatically retained as an intermediate journal** (the
      one automatic link in the model); retargeting always leaves the task not done; retargeting a
      **done** task reopens it and the UI must confirm before it happens; the new due journal must satisfy
      the future-dated invariant whatever the previous status.
- [ ] **Intermediate links are otherwise explicit only** — nothing is inferred from where the user
      happened to be when editing. They can be removed; the creating and due links cannot (the due link
      can only be replaced).
- [ ] **Lapsed** is derived, never stored: a not-done task whose due journal's date has passed, **or**
      whose due journal is cancelled (`EventState.CANCELLED`). Lapsed tasks remain visible on every
      journal they link to, clearly marked, with resurrect / cancel / done available inline. They are
      never auto-cancelled and never auto-rolled-forward.
- [ ] Contact links are plain references: no relationship type, role or attendance status; contacts are
      never parsed out of the task text.
- [ ] **REST surface** (JSON:API, following the journal controllers' conventions): create a task from a
      journal; update text; set status; retarget the due journal; attach/detach an intermediate journal;
      link/unlink a contact; read one task with its journals and contacts; list a journal's tasks **by
      link role**; list not-done tasks due within a forward window (default seven days); delete.
- [ ] **MCP tools shipped in the same phase as each REST capability**, covering the specification's list:
      create, update text, set status, retarget, attach/detach journal, link/unlink contact, get one, list
      by journal and role, list due within a forward window (default seven days). Every invariant and
      error message applies identically, and each tool's documentation lives in its docstring/schema —
      not in `mcp-setup.md`.
- [ ] All writes commit via `@transactional` services; controllers and MCP tools open no transactions.
- [ ] **Journal detail UI** shows the journal's tasks in three groups — **due** in this journal,
      **created** in this journal, **mentioned** in this journal — each entry showing the task text, its
      status, its linked contacts, and for lapsed tasks a clear lapsed marker plus inline resurrect,
      cancel and done. Rows reuse the dashboard row idiom (**W22**, **W23**, **W24**, **W27**) so the two
      surfaces read alike; the lapsed marker is journal-only and never appears on the dashboard
      (wireframe gap 5).
- [ ] **Create-from-journal UI**: task text plus a due-journal picker that favours recent and near-future
      journals and supports search across future journals by title and date, without becoming a journal
      browser. Optional contact selection. When the user has no future journals, the UI says so plainly
      and offers to create one instead of showing an empty picker.
- [ ] **Journal list** carries a lightweight indicator that a journal has tasks due in it, consistent with
      its other list-level indicators.
- [ ] No `/tasks` route, no global list, no status-filter browser, and no task in global search.

**Required Test Coverage:**

- **Unit:** every invariant, including the same-journal case and the "must be future when set, not
  continuously" distinction; the day-boundary calculation in a non-UTC timezone; status transition
  matrix (including cancelled → reopened only via retarget, and done → reopened on retarget); the
  automatic previous-due → intermediate link; lapsed derivation for both causes (date passed, due journal
  cancelled) and its non-application to done/cancelled tasks; MCP tool schemas.
- **Integration:** real-database round trips for each endpoint and each MCP tool; FK behaviour (task
  deletion cascades its links; a journal that anchors a task cannot be destroyed silently); the future-date
  invariant evaluated across a day boundary for a non-UTC user; error payload shape for each rejected
  invariant, over both REST and MCP.
- **E2E:** create a task from a journal and see it on the journal; tick it done and see the status change;
  retarget it to a later journal and see the previous journal retained as a mention; resurrect a lapsed
  task from the journal it was due in; the no-future-journals message. Separate deterministic fixtures for
  each; extend `TestDataManager` with task and future-journal helpers rather than reaching into the API
  ad hoc.

**Open decisions:**

1. ~~**Primary key type**~~ — ✅ **settled in Phase 1: `Integer` serial.** See *Decisions taken (Phase 1)*.
2. ~~**Where the due-journal "future" boundary sits** for a multi-day journal whose range straddles
   today~~ — ✅ **settled in Phase 3: the journal's date is its start date, so a trip that started
   yesterday and ends tomorrow is *past*** and cannot be a due journal. Confirmed against the
   specification's own definition ("the date of the start of its event date range") before it became a
   validation rule, and pinned by a test plus its mirror so the rule cannot later be "fixed" into
   consulting `end`. Phase 3 also settled the adjacent question the entry did not ask: the boundary is
   **strict** — a journal starting later *today* is not future-dated either. See *Decisions taken
   (Phase 3)*.
3. ~~**Whether task text has a length bound**, and whether it is markdown or plain~~ — ✅ **settled in
   Phase 1: plain text, `TEXT`, no length bound.** See *Decisions taken (Phase 1)*.
4. ~~**Whether MCP gets a delete tool**~~ — ✅ **settled in Phase 9: yes, `delete_task` ships.** The entry
   said Phase 7; Phase 7 had not landed when Phase 9 came up, and Phase 9's own criterion already named
   the tool, so it was settled where the work was. The specification's MCP list omits delete while
   listing every other operation, but principle 1 (no meaningful UI-only behaviour) decides it the
   other way: an agent that can create a task by mistake must be able to undo that mistake, and the
   alternative is a user cleaning up after their assistant by hand. The stance the specification
   actually cares about — cancel is ordinary, delete is the exception — is carried by the tool's
   *description* rather than by its absence, and that description is test-asserted. See *Decisions
   taken (Phase 9)*.

#### Phase 1: Schema, Tables and Domain Entity ✅ COMPLETE

**Prerequisites:** none.
**Estimated diff:** ~110 production → **~440 tracked** (×4) · **Actual:** ~290 production →
**~1270 tracked** (migration 145, `core_shared` tasks package 145; 873 lines of tests; ~110 lines of
docs). The production overrun is the migration itself — three tables with eight foreign keys and their
indexes came to 145 lines against an estimate that assumed one table. The test multiplier held.

**Acceptance Criteria:**

- [x] Alembic migration (sequential naming per the `creating-migrations` skill) creates the task table
      (owner, text, status, creating journal, due journal, timestamps) plus the intermediate-journal and
      contact link tables. — `0105_create_tasks_tables.py` creates `tasks`,
      `task_intermediate_journals` and `task_contacts`; `alembic heads` reports `0105 (head)`.
- [x] Anchor FKs are `NOT NULL` and **do not cascade from the journal side** (`ON DELETE RESTRICT` or
      equivalent). Link rows cascade from the task side; the contact-link FK is `ON DELETE CASCADE` from
      the contact side, so deleting a contact drops its links without touching tasks. — both anchors
      `ON DELETE RESTRICT`; both link tables cascade from `task_id`; `task_contacts.contact_id` and
      `task_intermediate_journals.journal_id` cascade from their own side. All four directions are
      asserted against real Postgres.
- [x] Status is a `CHECK`-constrained column matching the three-value domain enum; text carries the length
      bound from open decision 3. — `ck_tasks_status CHECK (status IN ('not_done', 'done', 'cancelled'))`,
      default `'not_done'`; `text` is unbounded `TEXT` per the decision below.
- [x] Domain entity + status enum in `core_shared`, following the project's domain-enum pattern, with
      construction-time validation of text and the presence of both anchors. —
      `core_shared/core_shared/models/tasks/` (`entities.Task`, `task_status.TaskStatus`,
      `exceptions.TaskValidationError`).
- [x] **Primary key type decided and justified here.** — `Integer` serial; see *Decisions taken* below.

**Decisions taken (Phase 1):**

- **Open decision 1 — primary key is `Integer` serial.** The specification makes tasks full domain-event
  citizens whose events project into field history, and `DomainEvent.aggregate_id` is typed `int`
  (`core_shared/core_shared/stream_client.py`) while `field_history.entity_id` is `Integer`
  (`app/infrastructure/contacts/contact_tables.py`). A UUID task id could not be an event aggregate id or
  a history entity id without migrating a table shared with contacts and journals — the wall iteration 17
  hit. Integer also matches the `journals.id` and `contacts.id` every task FK points at. **ITER18-003
  Phase 6 needs no extra migration and no re-estimate.** The accepted cost is enumerable ids in URLs,
  which owner-scoped reads (Phase 2) mitigate.
- **Open decision 3 — task text is plain text in an unbounded `TEXT` column.** Not markdown. The entity
  validates non-empty (after strip) and nothing else. A bound was deliberately declined rather than
  forgotten; it can be added later as a `CHECK` without a column type change. "Short text" therefore
  remains a product convention expressed by the UI, not a database constraint.
- **No SQLAlchemy `Table` object for the task tables.** The journal domain — the domain tasks are
  anchored to — defines none; only contacts and the event infrastructure do. The migration is the
  schema's source of truth and repositories use raw SQL (Phase 2). This also avoids colliding with the
  existing `app/infrastructure/tasks/` package, which holds ARQ background jobs, not domain tasks.
- **The intermediate link table is named `task_intermediate_journals`**, not a generic
  `task_journal_links`: the creating and due anchors are *columns* on `tasks`, so the link table holds
  intermediate links only and the name says so.
- **Entity carries no link collections.** Intermediate-journal and contact links are separate repository
  methods in Phase 2 (calibration rule 3), so `Task` holds only its own columns.

**Required Test Coverage:** unit — entity validation and enum behaviour. Integration — migration applies
cleanly; the anchor FK **refuses** a journal delete; contact deletion drops links only. No e2e (no surface
— deferral stated).

- **Unit (24 tests):** `backend/tests/unit/tasks/test_task_entity.py` — valid construction, default
  status, empty/whitespace owner and text rejected, unbounded text accepted, both anchors mandatory and
  positive, **creating == due accepted** (invariant 6), non-enum status rejected, error field/status-code
  shape. `backend/tests/unit/tasks/test_task_status_enum.py` — exactly three members, their stored
  values, `str()`, round-trip from string, invalid value raises.
- **Integration (13 tests):** `backend/tests/integration/tasks/test_tasks_migration.py` — `0104 → 0105`
  creates all three tables with the expected columns, downgrade drops them, re-upgrade recreates them;
  the status CHECK accepts every `TaskStatus` and rejects anything else; the column defaults to
  `not_done`. `backend/tests/integration/tasks/test_task_tables_constraints.py` — deleting the creating
  anchor is refused; deleting the due anchor is refused; deleting an intermediate-only journal drops the
  link and spares the task; deleting a task cascades its links while sparing journals and contacts;
  deleting a contact drops its task links only; both anchors are `NOT NULL`; creating and due may be the
  same journal; duplicate intermediate and contact links violate the composite primary keys (the basis
  of Phase 2's idempotent link adds).
- **E2E:** none — deferral taken as stated. Phase 1 ships no user-visible surface; e2e coverage for
  ITER18-001 lands in Phase 22.
- **Docs:** `docs/architecture/database-design.md` gained a *Tasks — journal-anchored commitments
  (ITER18-001)* section covering the three tables, the FK-direction table, the status CHECK and the
  integer-PK justification.

#### Phase 2: Task Repository ✅ COMPLETE

**Prerequisites:** Phase 1.
**Estimated diff:** ~110 production → **~440 tracked** (×4) · **Overrun recorded before work started
(delivery rule 3): ~380 production → ~800 tracked** · **Actual:** ~530 production → **~1270 tracked**
(1271 insertions, 47 deletions across 18 files: 533 production, ~756 tests and fixtures, ~29 docs).

The original figure assumed a repository class alone; the phase ships a port ABC (191), the SQL
adapter (288), a `TaskNotFoundError`, a Dishka provider and two container registrations. Rule 3
prefers splitting an oversized PR, and the natural split was **2a** (port + save/find/delete + row
mapper + DI) and **2b** (link add/remove). It was declined: the deliverable is *one class plus its
port*, so 2b would reopen and rewrite 2a's interface file — churn rather than reviewability.

**The advance estimate undershot too, and that is the finding worth carrying forward.** 1270 against
440 is **2.9×** — the same ratio Phase 1 hit, not the 1.9× predicted. Two things the ×4 rule does not
capture drove it: **a port ABC costs roughly as much as its adapter** in a codebase that documents
every abstract method (191 vs 288 here), and **owner scoping multiplies test volume** — five of the
23 integration tests exist only to prove a second user cannot reach the first's data, and each needs
its own seeded foreign rows. **A phase introducing a port + adapter pair should be estimated at ×6,
not ×4**, and the port counted as a first-class production artefact rather than a header file.

**Acceptance Criteria:**

- [x] Repository with save / find-by-id / delete plus intermediate-journal and contact link add/remove.
      **Only these** — each later read (by journal role, forward window, list indicator) belongs to the
      phase that consumes it, per calibration rule 3. — `TaskRepository`
      (`backend/app/core/tasks/models/repositories.py`) and `SqlTaskRepository`
      (`backend/app/core/tasks/adapters/sql/task_repository.py`). No read starting from a journal, a
      date or a link role was added; see *Decisions taken* on the two link listings that were.
- [x] A single row-mapping helper rather than duplicated per-query mapping (the `_row_to_tag` lesson from
      ITER17-001 Phase 1). — one `_TASK_COLUMN_NAMES` tuple, one `_TASK_COLUMNS` string interpolated
      into every query, one `_row_to_task`. A unit test asserts a row carrying exactly the declared
      columns maps cleanly, so the list and the mapper cannot drift.
- [x] Link adds are idempotent at the repository level, so a retry cannot create a duplicate row. —
      `INSERT … ON CONFLICT (task_id, <linked id>) DO NOTHING RETURNING task_id` over the composite
      primary keys; the `RETURNING` clause is what lets the method report whether a row was created.
      Asserted for both link tables by adding twice and counting rows.
- [x] All reads are **owner-scoped** at the repository boundary — no method can return another user's
      task. — every method takes `user_id` and every statement filters on it. The link tables carry no
      `user_id`, so link operations reach the owner through `_require_task_owned` first. Asserted
      against a **real second user's rows** rather than an absent id, because a query that dropped its
      filter would still return nothing for an id that never existed.

**Decisions taken (Phase 2):**

- **Owner scoping is written into the port, not left to the adapter.** `TaskRepository` documents it
  as part of the contract: a task the acting user does not own is treated exactly like one that does
  not exist. This is also `writing-sql` skill rule 2.
- **`TaskNotFoundError` (404) added to `core_shared.models.tasks`.** `save`'s update path and `delete`
  raise it when the owner-scoped statement matches no row, mirroring `SqlJournalRepository` and
  `JournalNotFoundError`. A missing row and another user's row are deliberately indistinguishable, and
  the message says nothing about ownership.
- **Link add/remove return `bool`; `find_by_id` returns `None`; everything else raises.** The `bool` is
  the idempotency signal ("was there a change"), and because `_require_task_owned` runs first it can
  never quietly mean "not your task". `find_by_id` is the lookup, so absence is its natural result;
  every other method operates on a task the caller claims to own, so absence is an error.
- **Two link listings were added beyond the AC's literal method list** —
  `list_intermediate_journal_ids` and `list_contact_ids`. The three reads the AC defers all start from
  a journal, a date or a link role; these read a task's **own** links. Without them the integration
  tests would have to assert link state with raw SQL, bypassing the very repository boundary the
  owner-scoping criterion exists to prove. Phase 12's read model builds on them.
- **DI registration lands here, in both containers.** `TaskProvider`
  (`backend/app/infrastructure/di/tasks.py`) is registered in `app/infrastructure/di/container.py`
  **and** in the integration-test container in `tests/integration/conftest.py`, so the two cannot
  drift and Phase 5's controllers inherit a working wiring. An integration test resolves
  `TaskRepository` through a real Dishka request scope; without it a typo in the provider would stay
  hidden until Phase 5.
- **Phase 1's seeding helpers were lifted into `tests/integration/tasks/task_seeding.py`** and
  `test_task_tables_constraints.py` now imports them (delivery rule 7). The module also carries the
  `OTHER_USER_ID` the owner-scoping tests need.
- **`updated_at` advancing is not asserted across an insert/update pair.** PostgreSQL's `now()` is
  transaction-scoped and the integration fixture holds one transaction open, so both statements stamp
  the same instant; a `>` assertion would fail and a `>=` one would prove nothing. The update test
  asserts instead that `created_at` survives, that the returned `updated_at` matches what the
  statement actually wrote, and that a re-read sees the new text and status.
- **The repository enforces persistence and task ownership only.** Whether the due journal exists,
  belongs to the acting user and is future-dated *at the moment it is set* needs journal data and the
  user's timezone; those remain Phases 3 and 4, unchanged and not partially anticipated here.
- **The ownership guard takes `FOR KEY SHARE`** — added in review. Checking ownership in a statement
  of its own leaves a window: a concurrent transaction could delete the task between the check and
  the statement it guards, and the caller would then get a raw foreign-key violation from the link
  insert, or a bare `False`/`[]` from the remove and list — three different answers to the one
  question the port answers with `TaskNotFoundError`. `FOR KEY SHARE` is the weakest lock that blocks
  a delete, so a concurrent update of the task's text or status still proceeds, and it is the same
  lock the link insert's own foreign-key check takes on the parent row anyway. The single-statement
  alternative (`INSERT … SELECT … FROM tasks WHERE …`) was rejected: it cannot distinguish "not your
  task" from "already linked" without `ON CONFLICT DO UPDATE … RETURNING (xmax = 0)`, which trades a
  one-word lock hint for an obscure idiom and a dead tuple on every retry.
- **A genuinely concurrent test is not possible under the integration fixture**, and this is stated
  rather than papered over: the fixture holds a single savepoint-bound transaction, so a second
  connection could not even see the task, let alone race it. What is tested is the serialised form
  (every link method reports a deleted task as `TaskNotFoundError`, never an `IntegrityError`) plus
  the lock itself, asserted through the row's `xmax` — which PostgreSQL stamps with the locking
  transaction's id. That second test was mutation-checked: removing `FOR KEY SHARE` makes it fail.

**Required Test Coverage:** integration — round-trip save/read/delete, link add/remove idempotency, link
cascade on task delete, and owner scoping (another user's id returns nothing). No e2e.

- **Unit (5 tests):** `backend/tests/unit/tasks/test_task_row_mapping.py` — the mapper populates every
  attribute; the stored status string becomes the `TaskStatus` enum (parametrised over all three);
  creating == due survives mapping; an unknown status raises rather than producing a bad entity; a row
  carrying exactly the declared columns maps cleanly.
- **Integration (25 tests):** `backend/tests/integration/tasks/test_task_repository_integration.py` —
  *save/find:* id and timestamps assigned, default `not_done`, full field round-trip with the status
  enum, creating == due, update of text and status preserving `created_at`, unknown id returns `None`.
  *Owner scoping (5):* `find_by_id` cannot see another user's task; `save` cannot re-own it; `delete`
  cannot remove it; all three intermediate-journal methods and all three contact methods raise for it.
  *Delete:* removes the task, raises for an unknown id, cascades both link tables while sparing the
  journals and contacts. *Links:* add returns `True`, a repeat returns `False` with the row count still
  1, remove returns `True` then `False`, list returns every link — each asserted for both link tables.
  *DI:* `TaskRepository` resolves through a real Dishka request scope to a `SqlTaskRepository`.
  *Vanished task (2, added in review):* every link method reports a deleted task as
  `TaskNotFoundError` rather than leaking an `IntegrityError`, and the ownership guard takes a row
  lock — asserted through the row's `xmax`, and mutation-checked by removing the lock.
- **E2E:** none — deferral taken as stated. Phase 2 ships no controller, MCP tool or frontend surface;
  e2e coverage for ITER18-001 lands in Phase 22. The iteration-level coverage the specification attaches
  to later phases (invariants, the timezone day boundary, the status matrix, lapsed derivation, MCP
  schemas, REST/MCP error payloads) is **not** claimed by this phase.
- **Docs:** `docs/architecture/domain-architecture.md` — the Tasks domain's *Ports* and *Repository
  contract* entries. `docs/architecture/database-design.md` — how the composite primary keys become
  `ON CONFLICT DO NOTHING`, and that owner scoping reaches the link tables through the task.
- **Gates run locally:** `ruff format --check`, `ruff check` and `mypy` clean for both `backend`
  (841 source files) and `core_shared` (125); the full `tests/unit/` suite, `tests/integration/tasks/`
  (36 tests — 13 from Phase 1, 23 new) and `tests/integration/api/` (which exercises the test-container
  change) all pass.

#### Phase 3: Journal-Date Resolution and the Future-Dated Rule ✅ COMPLETE

**Prerequisites:** none (pure logic over existing journal data).
**Estimated diff:** ~90 production → **~360 tracked** (×4) · **Overrun recorded before work started
(delivery rule 3): ~120 production → ~480–550 tracked.** Two things the original figure missed. The
fourth acceptance criterion ("reusable by ITER18-004's windowing rather than re-derived there") is only
met if this phase ships the local-day **window** builder as well as the date resolver — otherwise
ITER18-004 Phase 5 copies `OutdoorDashboardService._window` for a third time, which is exactly what the
criterion exists to prevent. And the required coverage names **DST transition days** in the plural over
four distinct behaviours (date resolution, today anchoring, the predicate, the window), which is a test
matrix rather than a test. · **Actual:** ~123 production → **~814 tracked** (814 insertions, 23 deletions
across 6 files: 123 production — 115 in the new module, 8 in the DI provider — 479 tests, 212 docs).

**The pre-recorded overrun undershot as well, and the reason is the one worth carrying forward.** 814
against 360 is **2.3×** on the estimate, but against *production* it is **6.6×**. Calibration rule 13
introduced ×6 after Phase 2 and attributed it to *port + adapter pairs*.
That attribution is too narrow: this phase has no port, no adapter and no owner scoping, and still came in
at ×6. **The real driver is how much of the deliverable is a rule that has to be pinned case by case.**
This phase's entire product is a decision (which local date, is it future) that only means anything at the
boundaries, so every boundary — two timezone directions, local midnight either side, two DST transitions,
a multi-day journal and its mirror — is a test, and each test carries the instant arithmetic that makes it
readable. 123 production lines bought 28 tests. **Suggested amendment to rule 13:** apply ×6 to
*rule-defining* phases as well as port+adapter ones — anything whose acceptance criteria read as a matrix
rather than a capability. ×4 remains right for phases that mostly wire an existing rule to a new surface.

**Acceptance Criteria:**

- [x] A helper resolving a journal's **date** as the date of `event_date_range.start` in the user's
      timezone (`UserSettingsRepository.get_timezone`, `resolve_timezone`) — the same date the journal list
      groups it under. Never UTC-today. — `journal_date(journal, tz)` over `local_date(moment, tz)` in
      `backend/app/core/journal/services/journal_date_resolver.py`; the timezone comes from
      `JournalDateResolver.timezone_for`, which is `resolve_timezone(await get_timezone(user_id))`.
      Asserted against a real `user_settings` row, and against the UTC fallback when there is none.
      **Partial on one clause, deliberately:** "the same date the journal list groups it under" holds by
      *rule* but not unconditionally in fact — see *Divergence recorded (Phase 3)* below.
- [x] A predicate answering "is this journal future-dated relative to today in the user's timezone". —
      `is_future_dated(journal, tz, now=None)`, plus the resolver method of the same name. **Strictly
      after today**: a journal starting later the same local day is *not* future-dated, per specification
      invariant 4 ("in the future relative to today"). Recorded as a decision below because it is the one
      reading of the invariant that has a product consequence.
- [x] Open decision 2 settled here: a multi-day journal that started yesterday and ends tomorrow is
      **past**, because a journal's date is its start date. — Settled as written and pinned by
      `test_a_multi_day_journal_that_started_yesterday_and_ends_tomorrow_is_past`, with
      `test_a_multi_day_journal_starting_tomorrow_is_future_dated` as its mirror so the rule cannot be
      "fixed" into consulting `end`. The open-decision entry above is struck through.
- [x] Reusable by ITER18-004's windowing rather than re-derived there. — `local_day_window(day, tz)`
      returns the user's local day as an `EventDateRange`, which is the shape ITER18-004 Phase 5's overlap
      query needs; that phase's prerequisite line now names the module. The pure functions take a
      `ZoneInfo` rather than a `user_id` so a batch caller resolves the timezone once.

**Divergence recorded (Phase 3) — the journal list groups by the *browser's* timezone:**

The acceptance criterion defines a journal's date as its start "in the user's timezone — **the same date
the journal list groups it under**", and treats those as one thing. They are not, and the phase found it
rather than assuming it. `groupJournalsByDay` (`frontend/src/lib/journal-grouping.ts`) buckets a journal
with `format(parseISO(start), 'yyyy-MM-dd')`, and `date-fns` `format` renders in the **browser's** local
timezone. The backend has no access to that, and the project's standing rule is that date windows are
anchored with `UserSettingsRepository.get_timezone` — so this phase implements the configured-timezone
reading, which is the one the specification's invariant is written in ("relative to today in the user's
timezone").

The two agree whenever the browser's timezone matches the configured one, which is the ordinary case. They
disagree when the user is travelling, or has set a timezone that is not their device's. The visible
consequence is narrow and worth stating exactly: a journal can be listed under one day while the tasks
invariant judges it by another, so a due journal that looks like tomorrow in the list can be rejected as
not future-dated (or the reverse). Nothing is corrupted by this — the rule is applied consistently
server-side — but the message the user sees would name a date their screen disagrees with.

Deliberately **not** fixed here: aligning them means either sending the configured timezone to the client
and grouping with it, or rendering the grouping server-side — a frontend change in a backend-only phase,
touching a shipped list this phase has no other reason to open. **Follow-ups recorded:** ITER18-004 Phase 3
(the page shell) is the natural place to make the configured timezone available client-side, and Phase 20
(create-a-task's due-journal picker) is the first surface where a user would *see* the disagreement,
because it shows future journals and their dates while the server decides which of them are eligible. Both
are named here so neither inherits the assumption that the two dates already agree.

**Decisions taken (Phase 3):**

- **The module lives in the journal domain, not tasks and not settings.** A journal's date is journal
  knowledge. `app/core/settings/timezone_utils.py` is a **leaf** imported by journal, contacts and
  integrations; importing `Journal` into settings would couple that leaf to a domain and affect every
  existing importer. The tasks domain is the wrong direction for the other consumer: ITER18-004 Phase 5's
  agenda is a journal read with nothing to do with tasks, and the iteration's own sequencing says 004
  needs 001 "for its tasks section, **and nothing else**". Cross-domain imports of this shape are already
  precedented (`contact_merge_service.py` imports `app.core.journal.models.repositories`).
- **Pure functions over `ZoneInfo`, with a thin async wrapper — and no `resolve_date(user_id, journal)`.**
  The obvious convenience method is exactly the one that produces an N+1: Phase 12's lapsed derivation
  evaluates every due journal in a list, and a per-journal `get_timezone` would be a settings read per
  row. `timezone_for` is public so the batch path is the natural one.
- **`now: datetime | None`, not the dashboards' `anchor: date | None`.** The behaviour under test *is* the
  instant → local-date derivation, which a `date` anchor bypasses entirely; there is no `freezegun` or
  `time-machine` in this repo, so an injectable anchor is the only way to test a day boundary. The two
  conventions compose rather than compete: ITER18-004 keeps `anchor: date | None` on its service methods
  and obtains that date from `await resolver.today(user_id)`.
- **Day boundaries are built from the date, with `datetime.combine(day, time.min/max, tz)`.** The
  alternative idiom — `compute_search_window` (`album_creation_service.py`) zeroing the time components of
  an instant inside the day with `replace` — was checked against real `zoneinfo` rather than assumed
  broken, and it is **not** wrong on transition days: `ZoneInfo` resolves each end's offset from its own
  local wall time, so both forms give the same 23- or 25-hour day. Building from the date is preferred for
  a smaller reason: the result does not depend on which instant you happened to start from, `fold`
  included, and it is the idiom `OutdoorDashboardService._window` already uses. Recorded because the
  opposite is a plausible-sounding claim that a reviewer would otherwise have to re-derive.
- **Existing timezone call sites were deliberately not migrated.** `OutdoorDashboardService._window` /
  `._user_timezone` and `compute_search_window` should collapse onto this module. Doing it here would
  rewrite two shipped features inside a phase whose own deliverable has no caller yet — the ITER17-003 P1
  mistake (an extraction that rewrote its call sites came in at 2.7×). **Follow-up recorded:** migrate
  them when ITER18-004 Phase 5 lands, which is the first phase with a reason to touch that code.
- **The Dishka test needs `InfrastructureProvider`.** Dishka validates the whole graph at container
  construction, and `JournalProvider`'s other factories need `Settings`. It is not a dependency of the
  resolver; the test says so, so nobody later mistakes it for one.

**Required Test Coverage:** unit — the boundary either side of local midnight for a non-UTC user; the
multi-day straddling case; a journal starting exactly today; DST transition days. Integration — resolution
against a real user-settings row and the UTC fallback when no timezone is set. No e2e.

- **Unit (23 tests):** `backend/tests/unit/journal/test_journal_date_resolver.py`. *Journal date (7):*
  `journal_date` is `local_date` of the start; a four-day journal is dated by its first day; either side
  of Sydney local midnight (13:00Z → the 30th, 14:30Z → the 31st); New York 01:00Z resolves to the
  previous UTC date; a naive start is read as UTC; both 2026 Sydney transitions — spring forward
  (4 Oct, +10→+11) and fall back (5 Apr, +11→+10) — where the pre-transition offset would give the
  neighbouring date. *Today (3):* local date not UTC date, in both directions; defaulting to the real
  clock. *Future-dated (7):* tomorrow, today, yesterday; the multi-day straddling case and its mirror; the
  boundary is the user's midnight, not UTC's (a UTC reading answers it the other way); a transition day
  compared by local date. *Window (2):* midnight to the final microsecond in the user's timezone; a
  spring-forward day is 23 hours — asserted on the **UTC-converted** endpoints, because subtracting two
  aware datetimes that share a `tzinfo` is naive arithmetic in Python and would report a flat 24.
  *Resolver wiring (4):* reads the setting, falls back to UTC on an unknown name, and applies the user's
  timezone in `today` and `is_future_dated`.
- **Integration (5 tests):** `backend/tests/integration/journal/test_journal_date_resolver.py` —
  resolution against a real `user_settings` row (Sydney), asserting the stored instant's UTC date is the
  30th while the resolved date is the 31st, and that the start survives the `TIMESTAMPTZ` round trip as an
  aware instant; the UTC fallback for a user with no settings row; the UTC fallback for a stored name the
  tz database does not know (the column has no `CHECK`, so it can hold one); future-dating decided on the
  user's local day where a UTC reading disagrees; and the resolver resolving through a real Dishka request
  scope. Journals are seeded at **fixed instants**, not offsets from `now()` — a test that asserts a date
  cannot be anchored on a moving one, which is why `tests/integration/tasks/task_seeding.create_journal`
  (a `days_offset` helper) was not reused.
- **E2E:** none — deferral taken as the phase states. Phase 3 ships no controller, MCP tool or frontend
  surface; e2e coverage for ITER18-001 lands in Phase 22.
- **Docs:** `docs/architecture/domain-architecture.md` gained a *Journal date resolution (user-local)*
  section (the rule, the pure/async split and its N+1 rationale, the `combine`-not-`replace` boundary
  rule, the placement argument and the standing duplication to collapse); `JournalDateResolver` was added
  to the Journal Domain's services; the Tasks Domain's *Domain Services* line now says the date semantics
  live in the journal domain and that `TaskService` consumes rather than re-derives them.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` and `core_shared`;
  `mypy` clean over 839 backend source files and `core_shared`; the full `tests/unit/` suite; and
  `tests/integration/journal/` plus `tests/integration/tasks/` (the latter covering the `JournalProvider`
  change). No frontend or e2e gates — the phase changes no frontend file and ships no user-visible
  surface.

#### Phase 4: Creation Service and Core Invariants ✅ COMPLETE

**Prerequisites:** Phases 2 and 3.
**Estimated diff:** ~120 production → **~480 tracked** (×4) · **Overrun recorded before work started
(delivery rule 3): ~190 production → ~900 tracked** · **Actual:** ~332 production → **~1923 tracked**
(1923 insertions, 41 deletions across 13 files: 332 production — service 218, exceptions 58, DI 33,
error handlers 11, service package 1, package exports 11 — 1341 tests and fixtures, 250 docs). The ×4
figure assumes a phase that wires an existing rule to a new surface. This one *defines* the rules, so
Phase 3's suggested amendment to calibration rule 13 — **×6 for rule-defining phases, whose acceptance
criteria read as a matrix rather than a capability** — applies here directly, and for the same reason:
the deliverable only means anything at its boundaries, so every boundary is a test (the strict
today/tomorrow edge, a non-UTC day boundary and its mirror, each anchor, each ownership violation,
each rejected contact).

**The pre-recorded overrun undershot as well — the third phase running — and the pattern is now
consistent enough to state as a rule.** 1923 against 480 is 4.0× on the estimate; against *production*
it is **5.8×**, which lands on the ×6 Phase 2 proposed and Phase 3 confirmed. What the advance figure
missed was not the service (218 against ~130 predicted) but the **test-to-production ratio for a rule
that only exists at its boundaries: 1341 test lines against 332 production, or 4.0× the production line
count in tests alone.** 36 unit tests and 15 integration tests, and none of them is redundant — each
pins a different corner of the same five-line predicate. **Suggested amendment to rule 13:** for a
rule-defining phase, estimate the tests at ~4× the production estimate and the total at ×6, rather than
applying a flat multiplier to a guessed production figure.

**A note on where the review rounds landed, because it bears on how to test the next rule-defining
phase.** Four of the six findings the PR's automated review raised were about *boundaries the tests did
not reach* — a clock read twice across midnight, a row deleted between its check and its write — rather
than about the rule itself, which the 44 tests written first had covered. The one that mattered most
was only catchable against a real database: the unit test for the vanished-anchor mapping was built on
a hand-written error and passed while the code was wrong. **For a rule whose failure mode is an
error-message shape, the integration test is not a confirmation of the unit test — it is the only real
test.**

Rule 3 prefers splitting an oversized PR. **Splitting was declined.** The only available cut is
"service now, invariants later", which would ship a create path that skips its own rules — a direct
breach of rule 9 (no phase may rely on a later one to restore behaviour it broke), and the invariants
are the phase's entire product. The alternative cut, separating unit from integration coverage, splits
tests from the code they pin.

**Divergence recorded before work started (Phase 4) — contacts have no owner:**

The third acceptance criterion requires that a linked contact belong to the acting user. **It cannot be
enforced as written, and the reason is structural, not an omission here.** The `contacts` table has no
`user_id` or owner column (`backend/app/infrastructure/contacts/contact_tables.py`), the `core_shared`
`Contact` entity carries none, and no code path anywhere in the backend validates contact ownership —
`JournalContactService.add_contact_to_journal` links a contact to a journal without any such check.
Contacts are single-user in this system. Iteration 13 hit the same wall and recorded it the same way
(*"the AC's 'same owner' precondition is not applicable at the data layer"*,
[iteration-13-contact-merge.md](./iteration-13-contact-merge.md)).

So the enforceable half ships — **the contact must exist**, checked in the service before anything is
written — and the ownership half is recorded here rather than faked. The alternative, inventing a
transitive rule ("a contact linked to one of your journals"), would be a product decision the
specification does not make, in a phase with no mandate to make it. The integration test the criterion
asks for ("a contact owned by another user (rejected)") is therefore written as *a non-existent contact
is rejected, and no task or link row is written*. **Follow-up:** if contacts ever gain ownership, this
service's contact check is the single place the rule lands.

**Acceptance Criteria:**

- [x] `TaskService.create_task` as a `@transactional` unit of work, taking creating journal, text, due
      journal and optional contacts. — `backend/app/core/tasks/services/task_service.py`. Keyword-only
      arguments so a caller cannot transpose the two journal ids, and `contact_ids` is optional as the
      specification has it. The decorator's own guard means the `transaction` parameter cannot be
      dropped without failing at import.
- [x] Invariants enforced here so every entry point inherits them: both anchors present; the due journal
      **exists**; the due journal is future-dated per Phase 3; creating and due may be the same journal.
      — presence stays on the entity (`Task.__post_init__`, so it costs no query); existence, ownership
      and future-dating are the service's. Creating == due is not special-cased: the anchor ids are
      de-duplicated before the read, so the same journal is fetched once and satisfies both.
- [x] **Ownership is an invariant, not an assumption:** both journals must belong to the acting user, as
      must any linked contact. A task can never span owners. — **journals in full; contacts diverge, as
      recorded above.** Ownership is enforced by the *query* rather than by a comparison: one
      `find_by_ids_for_user(user_id, [creating, due])` resolves both anchors, so a journal belonging to
      somebody else is simply absent from the result. Asserted against a **real second user's journals**
      on each anchor, not against an absent id.
- [x] Distinct, actionable domain errors per violated invariant, mapped to the journal/task domain's
      existing error-to-status conventions. — `TaskAnchorJournalNotFoundError` (404, carrying which
      anchor) and `TaskDueJournalNotFutureError` (400, carrying the journal's date and today's) in
      `core_shared/core_shared/models/tasks/exceptions.py`, both `TaskDomainError` subclasses so the
      already-registered `DomainError` handler covers them. Four `error_code_map` entries added — the
      two new errors plus `TASK_NOT_FOUND` and `TASK_VALIDATION_ERROR`, which Phases 1–2 shipped
      unmapped and which would otherwise have reached Phase 5's payloads as `DOMAIN_ERROR`.
- [x] The future-date check happens **only** at set time; nothing re-validates it on read. This is what
      makes a lapsed task reachable at all — see Phase 22's fixture recipe. — the check lives on the
      write path, and `is_future_dated` has exactly one caller outside its own module. Pinned
      positively rather than by absence: `test_the_rule_is_applied_only_when_the_anchor_is_set` creates
      against a backdated `now` so the due journal was future *then* and is three days past *now*, and
      the task reads back cleanly. Two honest limits on that evidence. The only read path this phase
      ships is `TaskRepository.find_by_id`, which never had validation to skip, so the "nothing
      re-validates" half is really proved by Phase 12–13's read model rather than here. And the recipe
      is a **backend fixture** recipe: Phase 22 drives Playwright through REST, which must *not* expose
      `now` (see the decision below), so its lapsed fixtures will seed the row directly or through the
      repository — not through this call.

**Decisions taken (Phase 4):**

- **Existence and ownership are one error, not two — and the guarantee is indistinguishability, not
  silence.** A journal the acting user does not own and a journal that does not exist raise the same
  `TaskAnchorJournalNotFoundError` with a byte-identical message for the same id. This is the stance
  `TaskRepository`'s port already documents for tasks, extended to their anchors, and it is what stops
  a rejected create being used to probe for another user's journals. A test asserts the two rejections
  are indistinguishable once the ids are stripped, so a future "more helpful" message cannot quietly
  reintroduce the leak. The message *does* name the constraint — a journal must exist and be yours —
  because a user who picked an unusable journal needs to know why; what it never does is **attribute**
  the failure to one half or the other. The distinction was sharpened after the PR review caught the
  exception's docstring claiming the stronger, false property ("says nothing about ownership").
- **One error class carrying which anchor, rather than one class per anchor.** The rule is single —
  *both anchors must exist and be yours* — so it gets one error with an `anchor` attribute, in the
  shape `TaskValidationError(field, message)` already established. A `TaskJournalAnchor` literal type
  names the two roles. The wider *link role* vocabulary (due / created / mentioned) that Phase 13's
  list-by-role needs is deliberately **not** introduced here; it belongs to the phase that reads it.
- **`ContactNotFoundError` is reused, not duplicated.** An unknown contact id is a contacts-domain
  fact, it already exists with the right status and error code, and delivery rule 7 prefers reuse. The
  service imports it across domains, which is precedented (`contact_merge_service` imports the journal
  repositories).
- **Contact existence is one batched read**, `find_names_by_ids`, whose contract already states that
  only contacts that exist appear in the result. Looping `contact_exists` would have been an N+1 on a
  path where a user may name several people.
- **The timezone is fetched once per create and handed to the pure predicate**, rather than calling
  `JournalDateResolver.is_future_dated` per journal. Phase 3 split the module that way precisely so
  batch callers would not read settings per row, and this is the first caller to honour it.
- **`now` is an explicit parameter on the service method — and must never reach it from a request.**
  There is no `freezegun` in this repo, and the behaviour under test *is* the instant-to-local-date
  derivation, so an injectable clock is the only way to test either side of a day boundary. It defaults
  to the real clock, so no caller has to know about it. But it is also a **loaded gun**: a controller
  that bound it from the request body — which a `**payload`-style wiring would do silently — would make
  invariant 4 opt-out for every client. The docstring says so at the parameter, and Phase 5 carries an
  acceptance criterion that neither surface accepts it.
- **A row that vanishes between its check and the write keeps its domain error** — raised by the PR's
  automated review, and the same class of finding Phase 2 took on `FOR KEY SHARE`. The anchor checks
  are a plain read, so a journal deleted in the window before the insert fails the foreign key and
  would surface a raw `IntegrityError` — a 500 where the caller was promised a 404. The violation is
  now mapped back to `TaskAnchorJournalNotFoundError`, naming the anchor, and the same one row over for
  a vanished contact. **Locking was considered and rejected:** closing the window needs an owner-scoped
  *locking* read on `JournalRepository` — another domain's port — to change an outcome that is
  identical either way, since the journal is gone and the task cannot anchor to it. Nothing is at risk
  in the data (the anchors are `ON DELETE RESTRICT`); only which error the caller sees. A violation
  naming anything else is re-raised untouched, so a broken constraint cannot masquerade as a 404.
- **The match is against the driver's message, not `str(error)` — and only a real database found
  that.** SQLAlchemy's string form appends the failing statement, whose column list names **both**
  anchors, so matching against it reports whichever is tested first. The unit test built on a
  hand-written error passed; the integration test, which deletes the journal inside the transaction and
  lets PostgreSQL raise, failed and named the wrong anchor. The fix reads `error.orig`. The unit test's
  fabricated statement now carries the full column list too, so it would catch the same mistake —
  mutation-checked by restoring `str(error)`, which fails both suites.
- **The clock is read once per create** — raised by the PR's automated review. `is_future_dated` and
  the error's `today_in` were each passed a bare `now=None`, so each read the clock independently: a
  create landing on local midnight could be refused against one day and told about another. The service
  now resolves the instant before the predicate and passes it to both. Resolving it here rather than
  comparing dates inline is deliberate — it keeps the definition of "future-dated" in the journal
  domain's predicate rather than re-deriving `>` in the tasks domain. Pinned by asserting the predicate
  receives a concrete instant and that the error's `today` is that instant's date; mutation-checked by
  restoring the two bare `now`s.
- **The one thing `@transactional` really guarantees is now tested.** Every rejection in this phase
  happens *before* the first write, so "no partial task" holds structurally on those paths whether or
  not a unit of work is open — which means none of them would notice the decorator being deleted.
  `test_a_failure_while_linking_rolls_the_task_back` makes the contact link fail *after* the task row
  exists and asserts the row is gone; it was mutation-checked by removing `@transactional`, which makes
  it (and only it) fail.
- **Contact links are written in a loop, and that is a knowing deferral.** Each `add_contact` re-proves
  task ownership with its own `SELECT … FOR KEY SHARE`, so N contacts cost 2N statements to link a task
  the service created three lines earlier — an odd asymmetry next to the batched existence check.
  Batching it means a new `add_contacts` on the port and its adapter, which is Phase 11's surface, not
  this one's. **Follow-up recorded for Phase 11.**
- **A `make_task_container` helper replaced the two hand-rolled DI containers.** `TaskProvider` no
  longer stands alone — `TaskService` needs the journal, contact and settings graphs, and Dishka
  validates the whole graph at construction — so Phase 2's DI test broke the moment the factory landed.
  Rather than paste the provider list twice, both tests build through one helper in
  `tests/integration/tasks/task_seeding.py`, whose docstring records why `InfrastructureProvider` and
  `IntegrationProvider` are in the list despite the tasks domain needing neither.
- **`create_journal` gained an optional `start`** rather than a second seeding helper. Tests asserting
  *a date* cannot be anchored on a moving instant (Phase 3's rule), while tests that only need "a
  future journal" are clearer against the real clock; one helper now serves both, and the docstring
  says which to use.

**Deferred out of the phase (recorded, not dropped):** the PR review also questioned the bare
`assert saved.id is not None` idiom used to narrow a repository-assigned id. It is an established
convention with three prior call sites and `python -O` is not used anywhere in this repository, so
changing only the tasks one would leave the codebase inconsistent about a rule that should be uniform.
Raised as a codebase-wide question in **issue #1261** rather than settled inside a phase PR. A second
suggestion — guarding against the service's repositories being bound to a different `AsyncConnection`
than its `transaction` — was declined: both come from one Dishka request scope so they cannot diverge,
and the check would require the service to reach past `TaskRepository` into the SQL adapter's
connection, which is the coupling the port exists to prevent.

**Required Test Coverage:** unit — each invariant including the same-journal case and each ownership
violation. Integration — the service against real journals, including another user's journal as the due
journal (rejected) and a contact owned by another user (rejected). No e2e.

- **Unit (31 tests):** `backend/tests/unit/tasks/test_task_service_create.py`. Repositories are mocked;
  `JournalDateResolver` is the **real** collaborator over a mocked settings repository, because the
  timezone rule is part of the behaviour under test. *Creation (7):* the saved entity's text, anchors
  and default `NOT_DONE`; the persisted row is what the caller gets; contacts become link rows against
  the assigned id; no contacts means no link and no contact read; duplicates collapse keeping
  first-mention order; existence is one batched call; **creating == due is accepted and fetched once**.
  *Anchors (7):* a missing creating journal, a missing due journal, both missing (the creating anchor is
  named, deterministically); the lookup is the owner-scoped one and `find_by_id` is never used; the
  message leaks no ownership language; empty text is rejected before any I/O; a zero anchor id is
  rejected. *Future-dated (10):* tomorrow accepted, **today rejected** (the strict boundary Phase 3
  settled), yesterday rejected; a multi-day journal already under way rejected and dated by its start;
  **the same journal as both anchors rejected when it is not future-dated** — invariant 6's proviso, and
  the case where collapsing the two roles could skip the date check along with the second lookup (added
  in review); the message carries both dates; **the Sydney pair** — a journal a UTC reading would accept
  is rejected on the user's local day, and its mirror is accepted where UTC would reject — plus the
  timezone being read exactly once, and **the clock being resolved once** so the decision and the
  message cannot disagree across a midnight (added from the PR review). *Contacts (2):* an unknown id
  is rejected and nothing is saved. *Vanished rows (4, added in review):* a foreign-key violation on
  either anchor is reported as that anchor's 404 and a violated contact link as `ContactNotFoundError`,
  while a violation naming anything else is re-raised untouched.
- **Unit (5 tests):** `backend/tests/unit/api/test_task_error_mapping.py` — each task error's JSON:API
  code and status, that the two creation failures are told apart, that Phase 1–2's errors are mapped
  too, and that the base class still renders generically.
- **Integration (15 tests):** `backend/tests/integration/tasks/test_task_service_create_integration.py`
  against real PostgreSQL. *Creation (3):* the row survives the round trip with both anchors and the
  default status; contacts and task are both visible once the create returns (one unit of work);
  creating == due against a real row. *Unit of work (1, added in review):* a contact link that fails
  **after** the task row exists rolls the task back — the one case that distinguishes `@transactional`
  from the structural "validate before writing" guarantee, and mutation-checked by deleting the
  decorator. *Vanished anchor (2, added in review):* a journal deleted inside the transaction, between
  the anchor check and the insert, still reports its anchor's 404 — the violation raised by real
  PostgreSQL rather than hand-built, which is what caught the `str(error)` bug the unit tests missed.
  *Ownership (3):* another user's journal rejected as the **due**
  anchor and as the **creating** anchor, with no task row written either time; and a foreign journal
  producing an error indistinguishable from an absent one. *Future-dating (3):* the Sydney case decided
  on the user's local day where UTC disagrees, with nothing written; the UTC fallback for a user with no
  settings row deciding the same pair the other way; and **the set-time-only rule**, creating against a
  backdated `now` so the resulting task is already lapsed and still reads back. *Contacts (2):* an
  unknown contact id rejected with no task and no link row, and a valid contact alongside an invalid one
  linking nothing. *DI (1):* `TaskService` resolves through a real Dishka request scope. Phase 2's
  repository DI test was updated to the same helper (its own count unchanged).
- **E2E:** none — deferral taken as the phase states. Phase 4 ships no controller, MCP tool or frontend
  surface, so there is nothing for Playwright to drive; ITER18-001's e2e lands in Phase 22.
- **Docs:** `docs/architecture/domain-architecture.md` gained a *Task creation invariants* section (the
  layer table for who enforces which rule, the three load-bearing properties of the service half, and
  the contact-ownership divergence), and the Tasks Domain's *Domain Services* entry now names
  `TaskService` instead of deferring it.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (846 files) and
  `core_shared`; `mypy` clean over 844 backend source files and 93 in `core_shared`; the full
  `tests/unit/` suite (2704 tests); and `tests/integration/tasks/`, `tests/integration/journal/` and
  `tests/integration/api/` together (1060 tests). No frontend or e2e gates — the phase changes no
  frontend file and ships no user-visible surface.

#### Phase 5: Create — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 4.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — a capability triple, at the measured floor
for service + REST + MCP (calibration rule 2) · **Overrun recorded before work started (delivery rule 3):
~290 production → ~1300 tracked** · **Actual:** ~362 production → **~2036 tracked** (1968 insertions,
68 deletions across 19 files: 362 production — MCP tool 120, REST schemas 121, controller 84, error
handler 20, DI 6, registration 9, packages 2 — 1384 tests and fixtures, 290 docs; includes both
review rounds)

**Why the advance figure is higher than the estimate.** The ×4 assumes a capability triple where the
service is the bulk of the production line count. Here the service already exists, so the phase is
*two thin surfaces over one thick rule* — and the rule only means anything at its boundaries, which
Phase 4 measured at 4× the production line count in tests alone. The same eleven-row rejection matrix
has to be proved **twice**, once per surface, because "both surfaces inherit the invariants" is the
phase's actual product and a shared service is not evidence that both callers reach it. Two entry
points, two error-rendering conventions (JSON:API codes and the MCP response builder), and roughly
900 lines of test against ~290 of production.

**Splitting was declined.** The only available cut is "REST now, MCP later", which is a direct breach
of delivery rule 5 — MCP parity lands in the same phase, never as a trailing task — and the second cut,
separating the rejection matrix from the surfaces it is asserted against, splits tests from the code
they pin.

**The pre-recorded overrun undershot for the fourth phase running — 2036 against a 1300 advance figure
and a 600 estimate — and the reasoning behind it was sound; only the arithmetic was optimistic.** The
production estimate was nearly right (362 against ~290). What it under-counted, again, was the tests:
1384 lines, **3.8× the production line count**, against the 900 predicted. Against production the
total is **5.6×**, which lands inside the ×6 band Phases 2–4 established, so the *shape* of the rule
holds. **The refinement this phase suggests to calibration rule 13** is that a phase which puts N
surfaces over an existing rule costs roughly one full rejection matrix per surface, not one matrix plus
a small delta: the 15 endpoint tests and the 12 tool tests are near-identical in structure and neither
is redundant, because the two surfaces render errors through entirely different machinery (JSON:API
codes; the MCP response builder). The phase found a real defect on exactly that seam — see the
decisions — which the endpoint tests could never have caught.

**Acceptance Criteria:**

- [x] `POST /api/journals/{journal_id}/tasks` (JSON:API) creates a task whose creating journal is the path
      journal — never a body field. — `backend/app/api/tasks/controllers.py`, its own router rather than
      an addition to the 139 KB `journals/controllers.py`, registered under `/api` after the journals
      router (the paths do not overlap: nothing in that router matches `/{journal_id}/tasks`). The
      request schema carries no `creating_journal_id` at all, and sending one is a 400, so the rule is
      enforced by the contract rather than by the controller ignoring a field.
- [x] MCP `create_task` in the same PR, taking creating journal, due journal, text and optional contacts,
      with the same errors; documentation lives in the docstring/schema, not `mcp-setup.md`. —
      `backend/app/mcp/domains/tasks/tools.py`. Both anchors are arguments here because an AI client has
      no request path to take the first from. `mcp-setup.md` and `mcp-tools.md` are untouched.
- [x] Both surfaces reject a non-existent, non-future or non-owned due journal with a message naming the
      constraint, and neither offers a bare date nor creates a journal implicitly. — **this needed a
      change to shared code to be true on the MCP side; see the decisions below.** Neither surface has a
      date field: REST's schema has none and rejects `due_date` outright, and the tool declares no date
      parameter.
- [x] Controller and tool open no transactions; both call the `@transactional` service. — both pass the
      request-scoped `AsyncConnection` straight through as `transaction=`. Pinned positively rather than
      by inspection: `test_the_row_is_committed_before_the_response` reads the row back *after* the
      response, which only succeeds if the service's unit of work committed.
- [x] **Neither surface exposes `TaskService.create_task`'s `now` parameter.** — asserted four ways.
      The REST attributes model has no such field, sets `extra="forbid"`, and a request carrying `now`
      is a 400 with no task row written; the tool's *generated schema* (not merely its signature) has no
      `now` property, and a call passing one is refused as an unexpected keyword before the service is
      reached.
- [x] **Decide the status code for a rejected due journal deliberately.** — **confirmed as 404, not
      overridden**; the reasoning is recorded in full below, and nothing in the controller or the mapping
      changed as a result.
- [ ] **This is the phase after which journal delete and merge can hit the anchor FK.** ITER18-002
      Phases 1–3 must merge immediately after it — see the Sequencing Strategy. — **unchanged and now
      live.** Tasks are creatable by a user as of this phase, so `journals` rows can now be referenced by
      `ON DELETE RESTRICT` anchors: a journal delete or merge that hits one currently fails at the
      database rather than being handled. Left unticked deliberately — it is a handover, not something
      this phase can complete.

**Decision taken before work started (Phase 5) — the rejected due journal answers 404, confirmed
rather than overridden:**

The criterion asks for this to be settled deliberately either way, so here is the reasoning rather
than the outcome alone.

- **404 for a body-supplied reference to a missing row is already this codebase's convention, not an
  accident of the tasks domain.** `POST /api/journals/{journal_id}/relationships/contacts` answers 404
  through `ContactNotFoundError` for a body `contact_id` today. Overriding the tasks case would make
  tasks the exception, and the next phase adding a body-supplied reference would have no rule to follow.
- **Overriding only the due anchor would split one rule across two status codes.** Phase 4 deliberately
  made *both anchors must exist and be yours* a single error carrying which anchor it is about. A
  mapping that answered 400 for `due` and 404 for `creating` would re-separate at the boundary what the
  domain joined, and — because the mapping is what MCP inherits — the two halves of one rule would be
  reported to an AI client as two different kinds of failure.
- **The ambiguity the criterion names is real, and it is answered in the payload rather than the status
  line.** A client cannot tell *from 404 alone* whether the path journal or the body's due journal was
  the problem. It does not have to: the JSON:API error carries `code: TASK_ANCHOR_JOURNAL_NOT_FOUND`
  and a detail naming which anchor and which id. An integration test asserts that a rejected **due**
  journal's payload names the due journal's id and not the path journal's, so a later "tidier" message
  cannot collapse the distinction. What the payload still never reveals is *why* the anchor was
  unreachable — absent or someone else's — which is Phase 4's indistinguishability guarantee, and it
  survives unchanged.

Nothing is caught in the controller and no mapping changes, which is the property the criterion
actually protects: both surfaces get the same answer from the same place.

**Decisions taken (Phase 5):**

- **"Both surfaces reject with a message naming the constraint" was false on the MCP side until this
  phase fixed shared code, and no test in the repository would have said so.**
  `mcp_unified_error_handler` maps contact and journal domain errors by class; a `TaskDomainError` fell
  through to the catch-all and came back as *"Internal error — an error occurred while create_task"*.
  Every task rejection would have reached an AI client as an apparent server fault: unactionable, and
  indistinguishable from a real bug. A `TaskDomainError` branch now mirrors the journal one (404 → "Not
  found", otherwise "Task error", both carrying the domain's own message). This is the clearest
  argument for the phase's insistence on proving the matrix **once per surface** — the service was
  correct, the endpoint was correct, and the tool was still wrong. Two tests keep the branch honest at
  both edges: an unrelated `DomainError` must still fall through, and a `RuntimeError` must still be an
  internal error, so a genuine bug is never dressed up as an actionable rejection.
- **The created resource carries no `self` link.** JSON:API convention wants one, but this phase ships
  no endpoint to read a task back — that is Phase 13 — and a link that 404s is worse than an absent
  one. It arrives with the read model.
- **The response does not echo the contact links.** `create_task` returns a `Task`, which carries no
  contacts; re-deriving the linked set in the controller would be a second definition of what got
  linked, sitting next to a read model (Phase 11/13) that does not exist yet.
- **Timezone sensitivity is asserted on the journal's *date*, not against a clock.** The phase
  completion bar wants day-boundary coverage, and Phase 4 met it by injecting `now` — which is exactly
  what neither surface may expose. Asserting "today" from out here would race real midnight. So the
  assertion is on the *journal's* rendered date, which is a pure function of its start and the user's
  timezone, under **Pacific/Kiritimati (+14) and Pacific/Midway (−11)**: 25 hours apart, so their local
  dates differ at *every* instant, and a UTC reading fails one of the pair whenever the test runs.
  Deterministic, clock-free, and it fails for the right reason.
- **A new `app/api/tasks/` package rather than more of `journals/controllers.py`.** The endpoint hangs
  off a journal path but belongs to the tasks domain, and that file is already 139 KB. The routers do
  not overlap — nothing in the journals router matches `/{journal_id}/tasks` — so no ordering
  constraint like the `/journals/series` one applies.
- **`extra="forbid"` is on the create schemas, not on the shared JSON:API base.** Tightening
  `JsonApiCreateRequest` would silently change every domain's tolerance for unknown fields, which is a
  codebase-wide decision and not this phase's to make. **Follow-up:** worth asking whether the other
  create surfaces should forbid unknown attributes too.
- **`register_task_tools` also added a line to the MCP server's own instructions.** That is the
  server-level description an AI client reads before choosing a tool, not a per-tool catalogue, so it
  does not breach the "tools document themselves" convention. It states the two things a model cannot
  infer from any single tool: there is no separate task list, and there is no due date.
- **The JSON:API resource type is pinned, not merely defaulted** — raised by the PR's automated review.
  `type` was a plain `str` with a `"tasks"` default, copying every other create schema in this
  repository, so a body declaring `"contacts"` created a task and was answered with `"tasks"`. A
  generic JSON:API client picks its request shape from the type it declares, which makes that a
  mutation on a resource type the client never asked for. It is now `Literal["tasks"]`, so a mismatch
  is a 400. **This diverges from the other create surfaces**, which all still accept any type; the
  divergence is toward the specification and is recorded rather than propagated. It also sits oddly
  next to `extra="forbid"` in the original: forbidding an unknown *attribute* while accepting the wrong
  *resource* was the inconsistency the review found. JSON:API prescribes **409 Conflict** for a type
  mismatch; **400 is used deliberately**, because reaching 409 needs the controller to catch and
  re-raise, which breaks the "controller catches nothing" rule this phase is built on and would not be
  inherited by MCP (which has no resource type at all). **Follow-up:** whether the other create
  surfaces should pin their types too is a codebase-wide question, not this phase's to settle.
- **`extra="forbid"` had a gap at the request envelope** — raised by the PR's automated review, second
  round, and it is the same class of finding as the resource type above. Extras were forbidden on the
  attributes and the data member but not on the request root, whose shared `JsonApiCreateRequest` base
  ignores unknown members — so `now` *inside* `attributes` was refused while `now` beside `data` was
  silently dropped. Nothing reads it, so nothing was exploitable; what was wrong is that the guard the
  acceptance criterion asks for had a hole in it, and a guard with a hole is no guard to whoever finds
  the hole. All three levels are closed now, asserted at both the schema and the endpoint. **The
  lesson worth carrying forward:** "the schema forbids unknown fields" is a claim about a *nesting
  depth*, not a model, and a JSON:API envelope has three of them.
- **Three task test files had copy-pasted the same fixture block** — caught by the Sonar duplication
  gate at 3.2% on new code, not by review. `journal_repository`, `user_settings_repository`, `anchors`
  and the two row-count constants now live in `tests/integration/tasks/task_seeding.py`, which was
  already the shared home for task seeding, and are imported where needed. They are exported from a
  helper module rather than a `conftest.py` because their three consumers sit in different directories
  (`tasks/`, `api/`, `mcp/`) whose only common conftest is the root integration one — where
  task-specific fixtures do not belong. This also touched Phase 4's service integration test, which is
  where the duplication started; deduplicating two of three copies would have left the gate failing and
  the reuse rule half-applied.

**Required Test Coverage:** unit — request/response schemas and the MCP tool schema. Integration — endpoint
and tool against a real database, one test per rejected invariant on each surface, including cross-user
attempts. E2E deferred to Phase 22.

- **Unit (18 tests):** `backend/tests/unit/api/test_task_schemas.py` — the minimal body; contacts
  optional; the defaulted resource type **and a mismatched one rejected** (added in review); text and
  due journal required; **no `creating_journal_id` field and sending one rejected**; **no `now` field,
  sending one rejected, unknown attributes rejected in general, and `now` refused at each of the three
  nesting levels — inside `attributes`, beside them, and beside `data` itself** (the last added in
  review); no date field and `due_date` rejected; the response resource's anchors, the status
  rendering as `not_done`, and timestamps optional.
- **Unit (7 tests):** `backend/tests/unit/mcp/domains/test_task_tools_schema.py` — asserted against the
  **generated tool schema**, which is what a model actually reads, rather than the Python signature:
  the three required arguments, contacts optional, the injected service and connection absent from the
  contract, no `now`, no date parameter, a non-empty description, and the due-journal parameter stating
  the future-dated constraint (a model that cannot see the rule keeps proposing past journals).
- **Unit (7 tests):** `backend/tests/unit/mcp/shared/test_task_error_handling.py` — each task error's
  rendering through the shared handler, plus the two "not too broad" guards. All five of the first kind
  were red before the branch landed, which is how the gap above was found.
- **Integration (17 tests):** `backend/tests/integration/api/test_task_endpoints.py` against real
  PostgreSQL. *Creation (4):* the resource and its anchors; **the row read back after the response**
  (~~the only way to tell a committed write from an open transaction~~ — **corrected in Phase 6**: under
  the savepoint fixture that read sees the row with or without `@transactional`, so it shows only that
  the write happened before the response; see *Decisions taken (Phase 6)*); creating == due; contacts
  linked.
  *Unreachable anchors (3):* an absent due journal naming the due anchor **and not the path journal's
  id**; another user's due journal byte-identical to an absent one once the ids are stripped; another
  user's *path* journal rejected as the creating anchor — each with no task row written.
  *Future-dating (3):* a past due journal with both dates, and the Kiritimati/Midway pair.
  *Rejected bodies (7):* unknown contact (nothing written, no link row), empty text, `now`, `due_date`,
  `creating_journal_id`, **a body declaring another resource type**, and **`now` at the request root**
  (the last two added in review).
- **Integration (12 tests):** `backend/tests/integration/mcp/test_task_tools_mcp.py` — the same matrix
  through `tools/call` over the mounted MCP HTTP transport, including the indistinguishability pair and
  the timezone pair, and a call carrying `now` refused as an unexpected keyword with no row written.
  The last one is asserted on the *rejection reason* rather than on `now` appearing in the body, which a
  request echo would satisfy either way.
- **E2E:** none — deferred as the phase states. The phase ships no frontend surface; ITER18-001's e2e
  lands in Phase 22.
- **Docs:** `docs/architecture/api-design.md` gained a *Task Endpoints* section (the route table and the
  five conventions this surface pins down). `mcp-setup.md` and `mcp-tools.md` deliberately untouched.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (865 files) and
  `core_shared` (128); `mypy` clean over 860 backend files and 126 in `core_shared`; the full
  `tests/unit/` suite (2741 tests); and `tests/integration/tasks/`, `tests/integration/api/` and
  `tests/integration/mcp/` together (841 tests). No frontend or e2e gates — the phase changes no
  frontend file and ships no user-visible surface.

#### Phase 6: Status Lifecycle — Service, REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple
**Actual:** **366 production → 2,483 tracked** (2,483 insertions, 87 deletions: 366 production — service
78, REST schemas 51, controller 63, MCP tool 58, `core_shared` predicate and error 65, repository
locking read 50, error handler 2, server instructions 1 — 1,913 tests and fixtures, 204 docs). The
`~200 → ~1,050` figure first recorded here was wrong: it was written from memory before the diff was
measured, and it under-counted the tests by roughly half. The final figures include the review round
(the locking read and its three tests).

**Why it ran to 3.6× the estimate, and what that says about the calibration rule.** The production
estimate was almost exactly right (304 against ~150 for the two surfaces plus a service method, against
a ×2 under-count). What overran is what has overrun in every phase of this iteration: the tests, at
**5.6× the production line count**. A transition matrix is 3×3, and a *capability triple* asserts it
three times — once as a pure rule, once per surface — so the test volume is the cell count times the
surface count, not a multiple of the production lines. **Calibration refinement:** for a phase whose
subject is a *matrix* rather than a *path*, estimate tests from cells × surfaces, not from a multiplier
on production. **Delivery rule 3 was breached**: the overrun should have been recorded before work
started, and was not — the honest reading is that the phase should have been recognised as oversized at
planning time and the estimate revised then.

**Acceptance Criteria:**

- [x] `TaskService.set_status` handles the full transition matrix: done is reversible to not done;
      cancelled is reachable from any state; **cancelled → not done is rejected here**, because reopening
      happens only by retargeting (Phase 7). — the matrix is a pure predicate,
      `is_status_transition_allowed` in `core_shared/models/tasks/task_status.py`; the service applies it
      and raises `TaskStatusTransitionError`. All nine cells are asserted.
- [x] Marking done or cancelled requires no journal and creates no journal link. — no journal repository
      call is made on any path (asserted against the mock), and `task_intermediate_journals` is asserted
      empty after a status change on all three surfaces.
- [x] `PATCH /api/tasks/{id}` (status) plus MCP `set_task_status` in the same PR, accepting the three values
      and rejecting anything else. — the status parameter is the domain enum on both surfaces, so the three
      values are in the JSON:API schema *and* in the generated tool schema.
- [x] Both surfaces 404 on another user's task. — and byte-identically to an absent id once the ids are
      stripped, so neither surface can be used to probe for another user's tasks.

**Decisions taken (Phase 6):**

- **`cancelled → done` is refused as well as `cancelled → not done`.** The criterion names only the
  second. The specification gives cancelled exactly one exit — retargeting onto a new future journal,
  which revalidates the future-dated rule and always lands on *not done* — so allowing a status call to
  reach *done* from cancelled would be a second exit that skips those rules, and would in addition assert
  that a commitment was met after being declared irrelevant. Keeping it as one rule ("cancelled is left
  only by retargeting") is simpler than two half-rules, and the refusal message names retargeting so a
  client or an agent can act on it. The specification's *"mark it done, if it turns out they did it"*
  affordance is about **lapsed** tasks, which are not done, and is untouched.
- **A refused transition answers 409, not 400.** The body is well formed and the status it names is real;
  what it conflicts with is the state the task is in. `ContactMergeConflictError` is the existing 409
  precedent. The MCP handler needed no change — it branches on 404 versus everything else, so a 409 comes
  through as an actionable "Task error" carrying the domain message.
- **Setting the status a task already has is a no-op, not a write.** It returns the task without saving,
  so `updated_at` does not move and no status change is recorded that did not happen — which matters for
  ITER18-002's history projection, whose events are derived from writes. This is also what keeps
  `cancelled → cancelled` out of the refusal set: asking for the status a task already has is not a
  reopening.
- **`PATCH /api/tasks/{id}` is a member route, and there is still no collection.** The specification's
  "no `/tasks` route, no global list" is about a *collection*: no endpoint lists tasks because no screen
  does. A status change involves no journal at all — the due journal is not even re-read, which is what
  keeps a lapsed task completable — so routing it through a journal would imply a relationship the
  operation does not have. `api-design.md`'s "no `/api/tasks` index" was narrowed to say so.
- **The body's `data.id` must match the path, refused with 400.** Every other update surface in this
  repository requires `data.id` and none checks it; JSON:API says a mismatch is an error, and preferring
  the path silently would let a client change a task it believes it is not touching. This is the **only**
  thing the controller decides — an envelope concern with no domain rule and no MCP counterpart behind
  it — so the "controller catches nothing" rule survives intact. 400 rather than JSON:API's suggested
  409 keeps it consistent with Phase 5's type-mismatch choice, and 409 is now reserved for the lifecycle
  refusal, where it says something specific. **Follow-up:** this is the third divergence in a row where
  the tasks surface is stricter than its neighbours (pinned resource type, three-level `extra="forbid"`,
  and now the id match). Whether the other update surfaces should check `data.id` too is a codebase-wide
  question, recorded rather than propagated — the same disposition Phase 5 took.
- **The status parameter is the domain enum on both surfaces, not a string.** A model reads the generated
  tool schema to decide what to send; a plain string would leave it guessing at "complete", "closed" or
  "todo" and learning the answer only from a rejection. A test asserts the schema enumerates exactly the
  three values, and another that the tool description names retargeting as the way out of cancelled — a
  model that cannot see that rule retries the refused call instead.
- **"Read the row back after the response" never proved a commit, and this phase's review caught it.**
  Phases 4–6 all carried a test whose docstring called that read *"the only way to tell a committed
  write from one still sitting in an open transaction"*. It is not: the integration fixture owns an
  outer transaction and marks the connection, so `unit_of_work` stands a SAVEPOINT in for the commit and
  the row is visible to any later read on that connection **whether or not the service is
  `@transactional`**. This was verified rather than argued — with the decorator removed, all 34 endpoint
  tests still passed. Two things follow. The claims are corrected wherever they appear (the test names
  and docstrings say what the assertion actually shows: the write happened before the client was
  answered). And the property itself is now asserted where it *is* observable: a repository subclass
  looks at `connection.get_nested_transaction()` while it writes, which is non-`None` exactly while a
  unit of work is open — the one test in this phase that fails when the decorator is deleted.
  **Follow-up:** every other domain's "committed before the response" test rests on the same false
  evidence. Worth a pass over `testing-strategy.md` to make the observing-repository idiom the standard
  way to assert a unit of work, rather than repeating a read that cannot fail.
- **The read takes a row lock, because without one the refusal rule could be bypassed by timing.**
  This was first written down here as a *"harmless today, revisit in Phase 9"* follow-up — the argument
  being that status is the only mutable field, so a stale whole-row write could not lose anybody's
  edit. **That was wrong**, and the pull request's automated review said so: the lost update is not a
  lost *field*, it is a lost *decision*. Two overlapping calls both read `not_done`, both find their
  transition allowed, and the later write wins — so cancelling a task while somebody else marks it done
  leaves it **done**, with both callers answered `200`. That is `cancelled → done`, the transition this
  entire phase exists to refuse, reached by interleaving rather than by request. `set_status` now reads
  through `find_by_id_for_update`, whose `FOR NO KEY UPDATE` holds the row until the unit of work
  commits, so the second call waits and then decides against the status the first one actually wrote.
  `FOR NO KEY UPDATE` rather than `FOR UPDATE` so a link insert's foreign-key check on the same row —
  which takes `FOR KEY SHARE`, the lock the repository already uses in `_require_task_owned` — is not
  made to queue behind somebody marking a task done. **The lesson worth carrying:** "nothing else is
  mutable yet" is an argument about *fields*, and a read-decide-write sequence can lose a *rule*
  regardless of how many fields it touches. Phases 7–9 inherit the locking read rather than needing to
  discover it.
- **Test seeding was shared rather than copied**, following the Phase 5 duplication lesson. `create_task`
  and `stored_status` joined `tests/integration/tasks/task_seeding.py`; `task_repository` joined the root
  integration conftest (three directories consume it); and the `service` fixture the two service test
  files had in common moved to a new `tests/integration/tasks/conftest.py`, removing the copy Phase 4
  left in the creation test. Tasks are seeded **through the repository**, not by driving the surface
  under test, because reaching *cancelled* through the service is itself one of the behaviours asserted.

**Required Test Coverage:** unit — the transition matrix including every rejected transition. Integration —
both surfaces against a real database, plus the cross-user 404. E2E deferred to Phase 22.

- **Unit (17 tests):** `backend/tests/unit/tasks/test_task_status_transitions.py` — all nine cells against
  the pure predicate, a guard asserting the two lists *are* the whole matrix so no cell can be forgotten,
  done's reversibility and cancelled's reachability stated in their own right, and the refusal error's
  shape (409, both statuses in the message and on the object, and the word *retarget*).
- **Unit (18 tests):** `backend/tests/unit/tasks/test_task_service_set_status.py` — each permitted
  transition persisted; the read is owner-scoped; text and both anchors untouched; **the journal and
  settings repositories are never touched at all** (asserted on `mock_calls`, not on named methods, so
  a method added to the port later cannot slip through) and no link is written; both refusals raise and never call `save`; an unknown task and another
  user's task both raise `TaskNotFoundError` with identical messages and no write; every same-status call
  returns without saving.
- **Unit (36 tests, 18 new):** `backend/tests/unit/api/test_task_schemas.py` (extended) — the three status values
  accepted and a fourth rejected; `status` required; `data.id` required; the resource type pinned; and
  the update request refusing `text`, `due_journal_id`, `creating_journal_id`, `now` and unknown fields at
  each of the three nesting levels.
- **Unit (13 tests, 6 new):** `backend/tests/unit/mcp/domains/test_task_tools_schema.py` (extended) — the tool is
  registered, `task_id` and `status` are required, the status parameter enumerates exactly the three
  domain values in the **generated schema**, injected collaborators are absent, no journal parameter is
  offered, and the description names retargeting.
- **Unit (9 tests, 2 new):** `backend/tests/unit/mcp/shared/test_task_error_handling.py` (extended) — the refusal
  renders as an actionable "Task error" rather than "Not found" (a cancelled task exists; it is the move
  that is refused), and carries the way out.
- **Integration (16 tests):** `backend/tests/integration/tasks/test_task_service_set_status_integration.py`
  — every permitted transition read back from the **database** rather than from the returned object; a
  **lapsed** task still completable (the due journal is not re-validated); no intermediate link row; the
  anchors unchanged; `updated_at` unmoved by a same-status call; both refusals leaving the stored row
  untouched; another user's task not found and not modified; an absent id giving the identical message.
  It also carries the two tests that are sensitive to the *mechanism* rather than the outcome, both
  added because a review found the property they pin was unasserted: a repository that observes the
  connection while it writes proves the unit of work is open around it (the phase's only
  decorator-sensitive test), and a second reader-for-update proves the row lock blocks until the first
  transaction commits. Alongside them, an **overlapping two-connection call** — the done starts while
  the cancel's unit of work still holds the row — pins every outcome: the cancel succeeds, the done is
  refused, the row ends *cancelled*. It commits outside the fixture's rolled-back transaction under a
  one-off user id and deletes its rows in a `finally`. **It is deliberately not the regression detector:**
  measured against the unlocked read it fails only about one run in three, because the done's read can
  land after the cancel commits and be refused for the right reason by accident. Making it fail every
  time needs the done to read *before* the cancel commits, and a barrier for that deadlocks against the
  lock under test — so the every-time guarantee is the reader-for-update test and the unit test that
  `set_status` uses the locking read, and this one exists to exercise the whole path.
- **Integration (34 tests, 17 new):** `backend/tests/integration/api/test_task_endpoints.py` (extended) — each
  permitted transition over HTTP; the row read back **after** the response (which shows the write
  happened before the client was answered — *not* that it committed; see the decision above); no link
  row; the same-status no-op; both refusals answering 409 `TASK_STATUS_TRANSITION_REFUSED` with the row
  unchanged; the cross-user 404 proved byte-identical to an absent one; and four rejected bodies
  (unknown status, `text`, `now`, no status) plus `now` at the request root, another resource type, and
  a body id disagreeing with the path — the last asserting *neither* task moved.
- **Integration (22 tests, 10 new):** `backend/tests/integration/mcp/test_task_tools_mcp.py` (extended) — the same
  matrix through `tools/call` over the mounted MCP transport, including the written row, the absence of
  link rows, the same-status no-op (so neither surface has behaviour the other lacks), the actionable
  refusal, the indistinguishable cross-user answer, and a fourth status value refused by the transport
  before the service is reached.
- **E2E:** none — deferred as the phase states. The phase ships no frontend surface; ITER18-001's e2e
  lands in Phase 22.
- **Docs:** `docs/architecture/api-design.md`'s *Task Endpoints* section gained the `PATCH` row and four
  conventions (member route versus collection, 409 for a refused transition, the `data.id` match, and the
  second MCP tool). `mcp-setup.md` and `mcp-tools.md` deliberately untouched — the tools document
  themselves.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (869 files) and
  `core_shared` (128); `mypy` clean over 864 backend files and 126 in `core_shared`; the full
  `tests/unit/` suite (2,802 tests); and `tests/integration/tasks/`, `tests/integration/api/` and
  `tests/integration/mcp/` together (882 tests). No frontend or e2e gates — the phase changes no frontend
  file and ships no user-visible surface.

#### Phase 7: Retargeting Semantics — Service

**Prerequisites:** Phase 6.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] `TaskService.retarget_due_journal` revalidates the future-dated and ownership rules at set time,
      whatever the current status.
- [ ] The **previous due journal is automatically retained as an intermediate journal** — the model's one
      automatic link — without duplicating an existing intermediate link for the same journal.
- [ ] Retargeting always leaves the task **not done**: not done stays not done; cancelled is reopened; done
      is reopened.
- [ ] Reopening a **done** task requires an explicit acknowledgement argument; without it the service
      refuses with an error the UI and an agent can act on.
- [ ] The creating journal is immutable — no code path can change it.

**Required Test Coverage:** unit — each status's outcome, the automatic intermediate link and its
de-duplication, the acknowledgement requirement, creating-journal immutability, future-date and ownership
revalidation. Integration — retarget round-trip with real journals. No e2e.

#### Phase 8: Retargeting — REST and MCP

**Prerequisites:** Phase 7.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] A retarget endpoint (`PATCH /api/tasks/{id}` due journal, or a dedicated sub-resource — state the
      choice) and MCP `retarget_task` in the same PR, both carrying the reopen acknowledgement.
- [ ] Both return the resulting task including its new intermediate link, so a caller sees the trail
      without a second read.
- [ ] Reopening a done task without acknowledgement returns a distinguishable error, not a generic
      validation failure.

**Required Test Coverage:** unit — schemas and tool schema. Integration — both surfaces, the
unacknowledged-reopen rejection, and the intermediate link in the response. E2E deferred to Phase 22.

#### Phase 9: Text Update and Delete — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple.
**Revised before work started (delivery rule 3):** ~300 production → **~1,700 tracked**. The original
figure treats this as a capability *triple*; it is a **quadruple** — text update × 2 surfaces, delete
× 2 surfaces — and Phase 6 had already measured this domain's tests at 5.6× production. **This is the
first phase in the iteration to record the overrun *before* work rather than after**, which is what
delivery rule 3 asks for and what Phase 6 explicitly noted it had failed to do.

**Rule 3's 500-line limit was nonetheless breached, and the escape clause does not cover it.** That
clause permits an overrun only where splitting would break rule 9 (every phase shippable), and
splitting this one into "text update" and "delete" would not have: both halves ship independently. The
honest accounting is that the phase was split*table* and was not split, for a weaker reason — the two
halves share one `PATCH` schema change, and separating them would have put half a contract in each PR.
What the actual numbers then show is that splitting would not have reached 500 either: each half comes
to roughly 1,300–1,400 lines on its own. **No REST+MCP capability phase in this domain fits in 500
lines**, because a capability's tests are its rules times its surfaces, and this domain has three. That
is a finding about the 500-line rule rather than an excuse for this PR — see calibration rule 16.
**Actual:** **311 production → 3,300 tracked** (3,300 insertions, 176 deletions: 311 production —
service 158, MCP tools 79, controller 74 net, REST schemas 50, server instructions 1 — 2,690 tests and
fixtures, 299 docs, of which 270 are this entry).

**The production estimate was right; the revised test estimate was 58% low.** 311 against ~300 is the
closest production call in this iteration. The tests came to **8.6× production**, well above even
Phase 6's 5.6×; roughly 300 of those lines are the review round (a second false-evidence test found and
fixed in Phase 6's file as well as this one, the REST half of criterion 3, the combined-write refusal on
both halves, and a link-cascade over-reach case). The reason is the one Phase 6 identified, one step
further along: the subject is
not a matrix but a *pair* of capabilities, each asserted on three surfaces (service, endpoint, tool)
and each surface asserting the same handful of properties — editable in all three statuses, the
lapsed case, no inferred link, the cross-user answer. **Calibration refinement:** for a phase shipping
*N* capabilities across *S* surfaces, the test volume scales with N × S × (properties per capability),
so estimate from that product rather than from a multiplier on production lines. A quadruple in this
domain is a ~2,700-line PR, which is over the 500-line rule — the honest reading is that the 500-line
rule and the "MCP parity in the same phase" rule are in tension for any multi-capability phase, and
that ITER18-001's remaining capability phases (10, 11, 13, 14) should each be planned as **one
capability**, not two.

**Acceptance Criteria:**

- [x] Text is editable in **any** status, through `PATCH /api/tasks/{id}` and MCP `update_task_text`. —
      asserted for all three statuses on all three of the service, the endpoint and the tool, plus the
      *lapsed* case (a task due in a past journal), because the due journal is never re-read.
- [x] Hard delete via `DELETE /api/tasks/{id}` and MCP `delete_task` (open decision 4 — **settled here,
      see below**), removing the task and its link rows and nothing else. — both link tables are
      asserted empty afterwards and both anchors, the intermediate journal, the contact and a sibling
      task are all asserted to survive, on both surfaces.
- [x] Both docstrings make cancel the ordinary action and delete the exception, consistent with the
      journals specification's stance. — and the MCP one is asserted as a *test*, not merely written:
      the description must name cancelling, name `set_task_status` as the tool that does it, say the
      deletion cannot be undone, and say the journals and contacts survive.
- [x] Both surfaces 404 on another user's task. — byte-identically to an absent id once the ids are
      stripped, on the edit and the delete, with the foreign row proved untouched in each case.

**Decisions taken (Phase 9):**

- **Open decision 4 is settled here, and the answer is to ship `delete_task`.** The entry says "settled
  in Phase 7"; Phase 7 has not landed and this phase's own criterion already names the tool, so it is
  settled where the work is. The specification's MCP list omits delete while listing every other
  operation, but **principle 1 (no meaningful UI-only behaviour)** decides it the other way: an agent
  that can create a task by mistake must be able to undo that mistake, and the alternative is a user
  cleaning up after their assistant by hand. The stance the specification actually cares about —
  cancel is ordinary, delete is the exception — is preserved by the *description* rather than by the
  tool's absence, which is why that description is test-asserted rather than left to prose.
  **The specification itself was amended**, on review's prompting: delivery rule 4 makes it the
  acceptance bar, so recording the addition only here would leave the next reader re-litigating the
  same omission. Its list is prefaced "MCP **must** support the ability to" — a floor rather than an
  inventory — and the section opens "There must be no meaningful UI-only behaviour in this work", which
  reads as *requiring* the tool rather than merely permitting it. `delete a task` is now on that list,
  with a paragraph recording why it had been ambiguous rather than excluded.
- **One service method owns text and status, and `set_status` delegates to it.** A `PATCH` may carry
  both, because JSON:API sends the attributes that changed. Applying them as two service calls would
  be two units of work and two read-decide-write sequences, so a client rewording *and* completing a
  task in one request could have half of it applied. `TaskService.update_task` therefore takes both
  optionally under one locking read and one write, and `set_status` — Phase 6's signature, and the
  intent the MCP tool exposes — became a three-line delegation. Two implementations of the transition
  matrix would be two places for it to drift and only one of them would be the one a given caller hit.
  Phase 6's 34 status tests all pass unchanged, which is the evidence the delegation preserved
  behaviour; a new test pins that the two entry points produce the same result.
- **Phase 6's row lock is inherited rather than re-tested.** `update_task` reads, decides and writes,
  which is exactly the shape that loses a *rule* rather than a field when two calls overlap — so it
  keeps `find_by_id_for_update`. Because `set_status` now delegates, Phase 6's two-connection
  overlapping-call test already exercises this code path end to end; duplicating that machinery
  (committed rows under a one-off user id, cleanup in a `finally`) would add cost without adding
  coverage. That the locking read is the one used is pinned per-method in the unit tests instead.
- **`delete_task` takes no locking read, and its absence is pinned by a test.** Unlike the update it
  decides nothing from what it read: one owner-scoped statement either removes a row or does not, and
  `rowcount == 0` is already `TaskNotFoundError`. Adding a read would add a round trip and a second
  way for the two to disagree. Worth stating because "the other member-route method locks, so this one
  should" is the plausible-looking change a later reader might make.
- **The links are left to the cascade, deliberately.** The service issues one `DELETE`; the link rows
  go because migration 0105's foreign keys say so. A service that walked the link tables could leave
  half of them behind, and would give the tasks domain the power to delete rows by enumeration rather
  than by constraint. A unit test asserts `remove_contact` and `remove_intermediate_journal` are never
  called, and an integration test asserts the cascade actually happens — the second is a property of
  the *schema*, so a database is the only place it can be shown.
- **A `PATCH` naming no change is refused (400) even though the service treats it as a no-op.** Down in
  the service an empty update is simply nothing to do, and putting a transport's rule there would be
  the wrong layer. Out at JSON:API it is a client that built a body wrong, and answering 200 would tell
  it an edit it thinks it made was applied. The rule lives in a Pydantic `model_validator`, so the
  controller still decides exactly one thing (the `data.id` match) and the "controller catches nothing"
  rule survives. This also settles explicit `null`: text is required on a task, so `{"text": null}`
  cannot mean "remove it" and is read as "not sent".
- **Text is validated by the entity, not by the schema.** `dataclasses.replace(task, text=…)` re-runs
  `Task.__post_init__`, so blank text raises the existing `TaskValidationError` (400) on every surface.
  Adding `min_length` to the request model would put a second rule beside the first that a later change
  to one would silently leave inconsistent with the other. Phase 1's decisions hold: no length bound,
  and the text is **not** trimmed — creation does not trim, and trimming on one path only would make a
  task's text depend on which surface last wrote it. Both are asserted.
- **`update_task_text` offers no `status`, and `set_task_status` no `text`.** The combined write exists
  for the `PATCH` body that genuinely carries both; a model gets one tool per intent, so it never has
  to reason about what leaving a field out will do. A test asserts a status smuggled into
  `update_task_text` is refused by the transport before the service is reached.
- **Test doubles were shared rather than copied a third time**, continuing Phase 5's lesson and Phase
  6's action on it. `set_status`, `update_task` and `delete_task` all start from the same position — one
  persisted task, reached by the owner-scoped locking read, with the journal, contact and settings
  repositories present but forbidden — so those fixtures moved out of
  `test_task_service_set_status.py` into `tests/unit/tasks/conftest.py`, with the constants and the
  entity builder in `task_doubles.py` beside it (a fixture cannot be imported; a plain function can).
  `test_task_service_create.py` keeps its own, because creation genuinely *configures* those
  repositories rather than merely forbidding them.
- **`test_task_error_handling.py` was deliberately not extended.** The shared MCP handler branches on
  the error *type*, and both types these tools can raise — `TaskNotFoundError` and
  `TaskValidationError` — are already asserted there. A copy under a different operation name would
  assert nothing the existing tests do not.
- **A second false-evidence test was found and fixed, this one Phase 6's.** Phase 6 corrected the "read
  the row back to prove a commit" claim; the same class of mistake survived one row over, in
  `test_asking_for_the_current_status_does_not_touch_the_row`. PostgreSQL's `now()` is
  `transaction_timestamp()` — constant across a transaction — and the integration fixture runs each
  test inside one, so the `DEFAULT now()` the seed row carries and the `updated_at = now()` an update
  writes are the *identical value*. "`updated_at` did not move" therefore held whether or not the no-op
  existed, and Phase 9's review demonstrated it by deleting the short-circuit and watching the test
  pass. Phase 9's own copy of that assertion had inherited the flaw. Both are fixed the same way: a
  shared `backdate_updated_at` helper moves the timestamp to a value `now()` cannot produce, and each
  is paired with a **positive** test that a real change *does* move it — without which a backdated
  timestamp that never moves is equally consistent with "the column is never written". All four were
  verified by deleting the short-circuit and confirming the two negative tests fail. **The lesson worth
  carrying**, and the second instance of it in this iteration: an assertion that a *timestamp* did not
  change is only evidence if something other than the code under test could have changed it.

**Required Test Coverage:** unit — text validation bounds, schemas, tool schemas. Integration — edit in each
status; delete removes link rows and leaves journals and contacts untouched; cross-user 404. E2E deferred to
Phase 22.

Counts below are `pytest --collect-only` figures, not hand-counted. Phase 9's review found the first
draft of this list inflated by 15–50% because the numbers were written from the test *functions* while
the surrounding text spoke of *tests*, and several are parametrised. Since this section is the
calibration record later phases estimate from, the distinction matters: **collected** tests are quoted,
with the function count in brackets where the two differ.

- **Unit (23 tests, 17 functions):** `backend/tests/unit/tasks/test_task_service_update_text.py` — the text written and
  returned in each of the three statuses and the status carried through unchanged in each (rewording a
  cancelled task must not quietly reopen it); the anchors, owner and id untouched; the journal, contact
  and settings repositories **never touched at all** (asserted on `mock_calls`, per Phase 6) and no link
  row written; the *locking* read used and the plain read not; blank, whitespace-only and tab/newline
  text refused with no save; no length bound (10,000 characters accepted) and no trimming; an unknown
  task and another user's task both raising identical messages with no write; the same text a no-op and
  an empty update a no-op; text and status together in **one** save; a refused transition taking the
  text edit with it; and blank text refused *before* the transition is considered, so a doubly-invalid
  request has a stable answer.
- **Unit (7 tests):** `backend/tests/unit/tasks/test_task_service_delete.py` — the delete owner-scoped;
  **no read precedes it** (the design decision, pinned rather than assumed); the link tables not walked;
  no other domain touched and nothing saved; and `TaskNotFoundError` propagating identically for an
  unknown id and another user's task.
- **Unit (2 tests added; 20 collected):** `backend/tests/unit/tasks/test_task_service_set_status.py`
  (extended) — the delegation: a status-only call leaves the text alone, and produces the same result as
  the equivalent combined update. Its existing tests are the real regression guard and pass unchanged;
  its fixtures moved to the shared conftest.
- **Unit (5 tests added, 2 rewritten; 39 collected):** `backend/tests/unit/api/test_task_schemas.py`
  (extended) — text alone, status alone and both together accepted; a body naming neither rejected; a
  body of explicit nulls rejected; empty text passing the schema and reaching the domain rather than
  being refused twice. The old "status is required" test became "a body naming no change is rejected",
  and `text` moved out of the forbidden-attributes list into the accepted ones.
- **Unit (5 tests):** `backend/tests/unit/api/test_task_endpoint_docs.py` (new) — acceptance criterion
  3's **REST half**, which the first draft of this phase left unasserted while asserting the MCP half
  five times over (found by review): the `DELETE` docstring — which FastAPI publishes verbatim as the
  endpoint's OpenAPI description — must lead with "prefer cancelling", name the status change that
  cancels, say the deletion is permanent, and say the journals and contacts are untouched. Plus the
  `PATCH` docstring stating the at-least-one-attribute rule, which a client cannot infer from the schema.
- **Unit (16 tests added; 29 collected):** `backend/tests/unit/mcp/domains/test_task_tools_schema.py`
  (extended) — both tools registered; their required parameters; injected collaborators absent; no
  journal parameter on either; no `now`; no `status` on `update_task_text`; the text parameter saying it
  *replaces*; the description saying text is editable in **any status**; and four assertions on
  `delete_task`'s description carrying acceptance criterion 3 (leads with "prefer cancelling", names
  `set_task_status`, says it cannot be undone, says the journals and contacts are untouched). The first
  two were tightened after review pointed out that `"cancel" in description` is satisfied by the
  substring inside *cancelled*, so a description reading "deleting is tidier than cancelling" would have
  passed while saying the opposite.
- **Integration (22 tests, 19 functions):** `backend/tests/integration/tasks/test_task_service_update_and_delete_integration.py`
  — the text read back **from the database** in each status; a lapsed task still editable; no link row
  created; the anchors unchanged; text and status travelling together; blank text leaving the row
  untouched; `updated_at` unmoved by a same-text call; the task row gone and **both** link tables
  emptied by a delete while the journals, the contact and a sibling task all survive; **a second task
  sharing the same intermediate journal and the same contact keeping both of its links** (added after
  review: every other link assertion is an unqualified `COUNT(*)` over a table where only the doomed
  task has rows, so a delete that over-reached along the *journal* or *contact* side of a link would
  have satisfied all six of them); the cross-user edit and delete both not found with the row intact
  and byte-identical to an absent id; a repeat delete not found; and the two decorator-sensitive tests —
  an observing repository proving the unit of work is open around the write and around the delete (both
  verified to fail with `@transactional` removed, and to pass with it restored).
- **Integration (14 tests added; 51 collected):** `backend/tests/integration/api/test_task_endpoints.py` (extended) —
  `PATCH` text in each status over HTTP with the row read back after the response; text and status in
  one request; **a refused status taking the text edit with it (409, both columns unchanged) and its
  mirror, blank text beside a valid status (400, both unchanged)** — added after review, because
  half-applying a combined request is the exact failure the single-service-call design exists to
  prevent and it was previously asserted only against the service; the lapsed case; no link row; blank
  text 400 with the row unchanged; the cross-user 404 proved byte-identical; `DELETE` answering **204
  with an empty body** and removing the row; the link rows gone with all three journals and the contact
  still present; a sibling task untouched; a repeat delete 404; and the cross-user delete 404 with the
  foreign row intact. The rejected-bodies parametrisation swapped `text` (now accepted) for
  `due_journal_id` (Phase 8's, still refused) and renamed the empty-attributes case.
- **Integration (11 tests added; 35 collected):** `backend/tests/integration/mcp/test_task_tools_mcp.py` (extended) —
  the same matrix through `tools/call` over the mounted MCP transport, because a shared service is not
  evidence both callers reach it: `update_task_text` in each status with the row read back, the lapsed
  case, no link row, blank text refused naming the field, the indistinguishable cross-user answer, and
  a status argument refused by the transport; `delete_task` confirming with `{"deleted": true,
  "task_id": …}`, emptying both link tables while the journals and contact survive, a sibling task
  untouched, a second delete not found, and the cross-user delete not found with the row intact.
- **E2E:** none — deferred as the phase states. The phase changes no file under `frontend/` and ships no
  user-visible surface; ITER18-001's e2e lands in Phase 22.
- **Docs:** `docs/architecture/api-design.md`'s *Task Endpoints* gained the `DELETE` row, a rewritten
  `PATCH` row, and five conventions (the at-least-one-attribute rule and what explicit `null` means;
  text and status as one change; 204-and-no-body with the cascade's blast radius and the repeat-delete
  404; delete-is-the-exception carried by what the surfaces say; and the four MCP tools with the
  one-tool-per-intent rule). `docs/architecture/domain-architecture.md` gained the service's mutation
  surface. `mcp-setup.md` and `mcp-tools.md` deliberately untouched — the tools document themselves.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (879 files) and
  `core_shared` (129); `mypy` clean over 874 backend files and 127 in `core_shared`; the full
  `tests/unit/` suite (**2,882 tests**); and `tests/integration/tasks/`, `tests/integration/api/` and
  `tests/integration/mcp/` together (**969 tests**). No frontend or e2e gates — the phase changes no
  frontend file and ships no user-visible surface.

#### Phase 10: Intermediate Journal Links — REST and MCP

**Prerequisites:** Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple

**Acceptance Criteria:**

- [ ] Attach and detach an intermediate journal, over REST and MCP in the same PR.
- [ ] Intermediate links are **explicit only** — no code path infers one from an edit — and attaching is
      idempotent rather than duplicating.
- [ ] The creating and due links cannot be detached through this surface; attempting it is a clear error.
- [ ] Attaching a journal that is already the creating or due journal is rejected: it is already linked in
      a stronger role.
- [ ] The journal must belong to the acting user.

**Required Test Coverage:** unit — role rules and idempotency. Integration — attach/detach round-trips and
each rejection on both surfaces, including the cross-user journal. E2E deferred to Phase 22.

#### Phase 11: Contact Links — REST and MCP

**Prerequisites:** Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple

**Acceptance Criteria:**

- [ ] Link and unlink a contact over REST and MCP in the same PR; linking is idempotent.
- [ ] Links carry **no** relationship type, role or attendance status, and nothing parses contacts out of
      the task text.
- [ ] Contact links are editable in any status; the contact must belong to the acting user. **Read
      Phase 4's contact divergence first** — `contacts` has no owner column, so the enforceable rule is
      existence. If this phase does not change that, it inherits the divergence rather than restating
      the criterion as met.
- [ ] Deleting a contact removes its task links without touching the tasks — the FK direction fixed in
      Phase 1, asserted here.
- [ ] **Follow-up from Phase 4: batch the link write.** `TaskService.create_task` links contacts in a
      loop, and each `add_contact` re-proves task ownership with its own `SELECT … FOR KEY SHARE` — 2N
      statements for N contacts. This is the phase that owns the contact-link surface, so an
      `add_contacts` on the port and its adapter belongs here, with `create_task` migrated onto it.

**Required Test Coverage:** unit — schemas, tool schemas, idempotency. Integration — round-trips, contact
deletion behaviour, cross-user rejection, both surfaces. E2E deferred to Phase 22.

#### Phase 12: Read Model and Lapsed Derivation

**Prerequisites:** Phases 3 and 10.
**Estimated diff:** ~120 production → **~480 tracked** (×4)

**Acceptance Criteria:**

- [ ] `lapsed` is **derived in the read model, never stored**: a not-done task whose due journal's date has
      passed in the user's timezone (Phase 3's predicate), **or** whose due journal is cancelled
      (`EventState.CANCELLED`).
- [ ] The derivation reports **why** a task lapsed — date passed vs due journal cancelled — as structured
      data, so surfaces can word it differently. ITER18-002 Phase 4 depends on this distinction; the UI
      wording itself lives in Phase 16.
- [ ] Done and cancelled tasks are never lapsed.
- [ ] The read model carries the task with its journals by role and its contacts, in the shape both read
      surfaces (Phase 13) and the dashboard (ITER18-004) consume.

**Required Test Coverage:** unit — both lapse causes, across a day boundary in a non-UTC timezone, and
non-application to done/cancelled tasks. Integration — derivation against a real cancelled event journal and
a real past-dated journal. No e2e.

#### Phase 13: Get and List-by-Journal — REST and MCP

**Prerequisites:** Phase 12.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple

**Acceptance Criteria:**

- [ ] `GET /api/tasks/{id}` returns the task with its journals (by role) and contacts, including the lapsed
      flag and reason; MCP `get_task` matches. Another user's task 404s on both.
- [ ] `GET /api/journals/{id}/tasks` returns the journal's tasks **grouped by link role** — due here,
      created here, mentioned here; MCP `list_journal_tasks` matches, with an optional role filter.
- [ ] Nested journals and contacts are fetched in **one query per collection**, not per task — an N+1 here
      is a correctness concern at journal scale.

**Required Test Coverage:** unit — role grouping and serialisation. Integration — both surfaces against real
journals including a cancelled event journal; the cross-user 404; a query-count assertion proving the nested
collections do not N+1. E2E deferred to Phase 22.

#### Phase 14: Upcoming-Window Listing — REST and MCP

**Prerequisites:** Phase 12.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple

**Acceptance Criteria:**

- [ ] A listing of **not-done** tasks whose due journal falls between today and *N* days ahead inclusive,
      default seven, ordered by due-journal date soonest first, anchored on today in the user's timezone.
- [ ] Lapsed, done and cancelled tasks are excluded. **The only fixture that makes the lapsed exclusion
      non-vacuous is a not-done task whose due journal is inside the window but `EventState.CANCELLED`** — a
      date-passed lapse cannot fall inside a forward window by construction. That fixture is required.
- [ ] MCP `list_upcoming_tasks` with the same default and semantics, in the same PR.
- [ ] The response carries task text, due journal id/title/date and linked contacts, in one query per
      collection. This is the query ITER18-004's tasks section consumes, so its shape is settled here.

**Required Test Coverage:** unit — window arithmetic and ordering, including a task due exactly on the
boundary day. Integration — both surfaces with tasks inside, outside, on the boundary, done, cancelled and
cancelled-journal-lapsed; window anchoring for a non-UTC user near midnight; no N+1. E2E deferred to
Phase 22.

#### Phase 15: Frontend — Task API Client

**Prerequisites:** Phase 13.
**Estimated diff:** ~90 production → **~360 tracked** (×4)

**Acceptance Criteria:**

- [ ] `frontend/src/lib/api/tasks.ts` + types: TanStack Query hooks for the read surfaces and mutations,
      following the journals client's conventions (query-key factory, error handling, toasts).
- [ ] **Every mutation routes through `frontend/src/lib/invalidate-after-mutation.ts`**, which cancels
      in-flight queries before invalidating them. Iteration 17 spent two bug fixes establishing this
      (issue #1203 and a `fetchNextPage` race) and routed all 77 mutation handlers through it; a new client
      that reintroduces bare `invalidateQueries` reintroduces the flake.
- [ ] Query keys are structured so a journal's task list and the dashboard's task section can be
      invalidated independently.

**Required Test Coverage:** unit — hook behaviour against a mocked client, and a test pinning that
mutations cancel before invalidating, in that order.

#### Phase 16: Frontend — Journal Task Display

**Prerequisites:** Phase 15.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] A `JournalTasksSection` component renders the three groups — due, created, mentioned — on the journal
      detail view, showing each task's text, status and linked contacts.
- [ ] Rows reuse the dashboard row idiom (**W22**, **W23**, **W27**) so the two surfaces read alike.
- [ ] Lapsed tasks are clearly marked and the marker **states which reason applies**, in wording distinct
      between date-passed and due-journal-cancelled (the data comes from Phase 12).
- [ ] A journal with no tasks renders nothing rather than an empty container; an empty group is omitted.
- [ ] Read-only in this phase: no action buttons yet, which breaks nothing that previously worked.

**Required Test Coverage:** unit (RTL) — the three groups, both lapsed reasons, the no-tasks case, contact
rendering, and accessible grouping labels. E2E deferred to Phase 22.

#### Phase 17: Frontend — Inline Status Actions

**Prerequisites:** Phases 6 and 16.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] Inline done / return-to-not-done / cancel actions on each row (**W24** idiom), with optimistic update
      and rollback on failure, routed through `invalidateAfterMutation`.
- [ ] Cancel is presented as the ordinary action; delete, where offered, is visually secondary and
      confirmed.
- [ ] Actions are keyboard reachable and announce their result.

**Required Test Coverage:** unit (RTL) — each action's happy path and failure rollback, keyboard operation,
and cancel-before-invalidate ordering. E2E deferred to Phase 22.

#### Phase 18: Frontend — Retarget and Resurrect Dialog

**Prerequisites:** Phases 8 and 17.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] A retarget dialog offering **future** journals, used both to extend a deadline and to resurrect a
      lapsed or cancelled task.
- [ ] Reopening a **done** task shows an explicit confirmation before it happens, and only then sends the
      acknowledgement from Phase 7.
- [ ] Lapsed rows expose resurrect, cancel and done inline, per the specification.
- [ ] The dialog surfaces the service's rejection (a journal that is no longer future-dated) against the
      field rather than as a toast-only failure.

**Required Test Coverage:** unit (RTL) — resurrect from lapsed and from cancelled, the done-reopen
confirmation gate, rejection rendering, and dialog focus management. E2E deferred to Phase 22.

#### Phase 19: Frontend — Attach and Detach Mention Links

**Prerequisites:** Phases 10 and 16.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Acceptance Criteria:**

- [ ] From a journal, the user can **attach an existing task** to the journal they are viewing, creating an
      intermediate ("mentioned") link — one of the two deliberate actions the specification names.
- [ ] A mention link can be **removed** from the journal that carries it; creating and due links offer no
      remove affordance.
- [ ] The task picker for attaching is scoped and searchable rather than listing every task — there is no
      global task list, and this affordance must not become one.

**Required Test Coverage:** unit (RTL) — attach, detach, the absence of remove on anchor links, and that
the picker is search-scoped rather than an unbounded list. E2E deferred to Phase 22.

#### Phase 20: Frontend — Create a Task from a Journal

**Prerequisites:** Phases 5 and 16.
**Estimated diff:** ~160 production → **~640 tracked** (×4) — the due-journal picker is the bulk and does
not split usefully from the form it lives in

**Acceptance Criteria:**

- [ ] A create-task affordance on the journal detail view, using `Form`/`FormField`/`FormMessage` with
      react-hook-form and Zod per the project's form standard.
- [ ] The creating journal is the journal being viewed and is never presented as a choice.
- [ ] A due-journal picker listing recent and near-future journals first, with search across future
      journals by title and date — a picker, not a journal browser. **No bare date picker anywhere.**
- [ ] Optional contact selection.
- [ ] With no future journals, the UI says so plainly and offers to create one instead of an empty picker.
- [ ] Service validation errors (non-future journal, missing text) surface against the right field.

**Required Test Coverage:** unit (RTL) — successful create, the empty-future-journals state, picker search
and ordering, field-level error mapping, and keyboard/ARIA behaviour of the picker. E2E deferred to
Phase 22.

#### Phase 21: Journal List "Tasks Due" Indicator

**Prerequisites:** Phase 12.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Acceptance Criteria:**

- [ ] The journal list response carries a lightweight per-journal signal that tasks are **due** in it
      (count or boolean — state the choice), computed in **one query for the whole page** rather than per
      row.
- [ ] `JournalListItem` renders the indicator consistently with its existing list-level indicators.
- [ ] Journals with no tasks due render no indicator; done, cancelled and lapsed tasks do not light it up.

**Required Test Coverage:** unit — indicator rendering rules. Integration — the list query emits the signal
with one query for many journals (assert the query count) and excludes non-due and lapsed tasks. E2E in
Phase 22.

#### Phase 22: E2E — The Journal Task Surface

**Prerequisites:** Phases 16–21.
**Estimated diff:** ~160 production → **~640 tracked** (×4)

**Acceptance Criteria:**

- [ ] `TestDataManager` gains deterministic helpers for tasks and for future / past / cancelled journals,
      reused rather than ad-hoc API calls in specs.
- [ ] **The lapsed fixture recipe is stated explicitly, because no API path produces a lapsed task
      directly:** create a future journal, create the task against it, then either cancel that journal or
      move its `event_date_range` into the past through the existing journal update endpoint — which
      deliberately does not re-validate task invariants (Phase 4). The spec asserts that non-revalidation
      so the recipe cannot silently stop working.
- [ ] **Fixture dates account for the e2e user having no configured timezone**, so backend day boundaries
      are UTC: a journal created at "today local noon" can read as tomorrow (or as future when a *past*
      journal was intended). Build fixtures from explicit UTC offsets, not local wall-clock times.
- [ ] Separate deterministic specs, each building its own fixtures: create a task and see it grouped as
      *created* / *due*; tick it done; retarget it and see the previous journal appear as *mentioned*;
      attach an existing task as a mention and detach it; resurrect a lapsed task; the no-future-journals
      message; the journal list indicator.
- [ ] No conditional logic on data state, no skips, no multi-outcome assertions.
- [ ] Green on both e2e projects (`firefox`, `Mobile Chrome`).

**Required Test Coverage:** this phase *is* the e2e coverage for ITER18-001; unit and integration coverage
landed in Phases 1–21.

### ITER18-002: Journal Anchor Integrity — Delete, Merge, Cancellation

**Objective:** Make journal operations respect the two-anchor invariant: block deletion of an anchoring
journal with an explanatory, actionable failure; re-point task links through merge; treat a cancelled due
journal as lapsing its not-done tasks.

**Independently deliverable because:** it changes only the behaviour of existing journal operations and
is complete in itself. Without it, journal deletion can leave the model in a state the specification says
is impossible, so it should follow ITER18-001 closely.

**Relevant documents:**

- Specification §*Journal Anchor Integrity* (deletion, merge, cancellation)
- `JournalMergeService`, `JournalWriteService.delete_journal`, `EventState`
- [API Design](../architecture/api-design.md) for error-response conventions

**Acceptance Criteria:**

- [ ] Deleting a journal that is the **creating** or **due** journal of **any** task is **blocked**,
      regardless of task status — a done task's link to the journal it was created in is part of the
      record.
- [ ] The failure is **explanatory, not opaque**: it names each blocking task and, for each, links to a
      journal where that task can be actioned — the task's due journal, or its creating journal when the
      due journal is the one being deleted. Because tasks have no route of their own, the link always
      targets a journal detail view.
- [ ] The same failure is returned over **REST and MCP**, identifying the blocking tasks and the journals
      that surface them, so an agent can resolve them without the UI.
- [ ] Deleting a journal that is only an **intermediate** link succeeds; the link is removed and the task
      is otherwise unaffected.
- [ ] The journal delete UI surfaces the blocking tasks with working links, and continues to steer the
      user toward cancelling rather than deleting.
- [ ] **Merge is not blocked.** Task links pointing at the absorbed journal are re-pointed at the
      surviving journal; a task can never end up linked twice to the same journal in the same role
      (duplicate links collapse); a surviving journal that becomes both creating and due for a task is
      permitted; merge never changes a task's status.
- [ ] **Cancelling a journal** is permitted and does not change task links. A not-done task whose **due**
      journal is cancelled is treated as lapsed — it leaves the dashboard and stays on its journals — and
      the journal listing on the task makes clear the reason is cancellation rather than the passage of
      time.
- [ ] Not wireframe-bearing: the dashboard wireframe covers no journal-operation surface, and lapsed tasks
      are deliberately absent from it (wireframe gap 5). The only new UI is the delete-failure explanation
      on the journal detail view.

**Required Test Coverage:**

- **Unit:** blocking-task detection by role; the choice of which journal each blocking task links to;
  merge link re-pointing and duplicate collapse, including the creating-equals-due outcome.
- **Integration:** delete blocked with the full error payload over REST and MCP; delete permitted when
  only intermediate links exist; merge re-points and dedupes against the real schema (a duplicate-key
  violation must be impossible, and the test must fail if the dedupe step is removed); merge leaves status
  untouched; cancelling a due journal lapses its not-done tasks and leaves done/cancelled ones alone.
- **E2E:** attempting to delete a journal with a task due in it shows the explanatory dialog whose link
  navigates to a journal where the task can be actioned; after cancelling or retargeting the task, the
  delete succeeds.

**Open decisions:**

1. ~~**HTTP status for the blocked delete**~~ — ✅ **settled in Phase 1: `409 Conflict`.** The journal
   domain has exactly two 409s and both are the right precedent: `RouteInUseError`, which is the same
   "you cannot delete this, something depends on it" refusal, and `JournalMergeConflictError`. Journal-
   domain consistency and cross-domain parity agree here, so iteration 17's tie-breaker never had to be
   applied. `JournalHasAnchoredTasksError` carries the status; the JSON:API body listing the blockers is
   Phase 2's.
2. ~~**Whether merge also collapses an intermediate link that duplicates a new anchor link**~~ — ✅
   **settled in Phase 3: yes, the redundant intermediate link is dropped.** (Recorded here as "settled
   in Phase 2", but Phase 2 is the delete-guard *surface*; Phase 3 is the phase that touches merge, so
   it is settled where it is implemented.) The recommendation stands as written: an intermediate link
   says "the task was mentioned here", which the creating or due anchor already says in a stronger
   form, so keeping both would be the same fact twice. The rule is applied to the **survivor** in both
   directions — an intermediate link absorbed into an anchor, and an anchor absorbed into a journal
   already linked as intermediate — and is the fourth of the repository's four statements, run last
   because it reads the anchors the third has just moved.

> **These phases are not optional follow-up work.** From the moment ITER18-001 Phase 5 makes tasks
> creatable, the `ON DELETE RESTRICT` anchor FKs mean `DELETE /api/journals/{id}` **and**
> `POST /api/journals/{id}/merge` (which ends by deleting the absorbed journal) raise a raw integrity
> error for any journal anchoring a task. Both are shipped features. Phases 1–3 below must merge
> **immediately after** ITER18-001 Phase 5, ahead of the rest of ITER18-001, or delivery rule 9 is broken
> for the intervening phases.

#### Phase 1: Blocking Detection and the Delete Guard ✅ COMPLETE

**Prerequisites:** ITER18-001 Phase 5 (task creation exists). Deliberately **not** the read model — the
action journal is the task's own due/creating id, which Phase 2 of ITER18-001 already provides.
**Estimated diff:** ~120 production → **~480 tracked** (×4) · **Actual:** ~458 production → **~1440
tracked** (production: the rule 148, the port and adapter 130, the guard and its backstop 60, wiring and
the sync fallback 120; tests: 980 across two new files, one new sync test and ~20 updated construction
sites; docs 182 on top). **Roughly 3× the estimate, and about 2.8× the repository's 500-line PR
standard** — recorded rather than smoothed over, because the cause is reusable calibration:

- **The wiring was estimated as one edit and is twenty-four.** `JournalService` is constructed in four
  production places and twenty test ones, so making the guard a required collaborator — the right call,
  see below — cost more in mechanical updates than the guard itself did in logic.
- **A "no unhandled error" criterion reaches further than the surface it names.** Two paths the phase
  never mentions had to be handled: the concurrent-insert window, and the calendar-sync deleter.
- **The ×4 test multiplier held for the *new* files but not for the phase.** The two new suites are ~2.1×
  their production, in line with the rule being pure; what the estimate missed is that a phase touching a
  widely-constructed service also drags a long tail of unrelated test edits behind it.

**For the phases that follow:** a phase that changes a shared constructor should budget its construction
sites explicitly, and one whose acceptance criterion says "no caller ever sees X" should enumerate the
callers before estimating.

**Acceptance Criteria:**

- [x] A repository query returns, for a journal, every task anchored to it as **creating or due**, with the
      journal each blocking task can be actioned from (its due journal, or its creating journal when the
      due journal is the one being deleted) — one query, not one per task. —
      `TaskAnchorRepository.find_tasks_anchored_to_journal` (`app/core/tasks/models/repositories.py`),
      implemented by `SqlTaskAnchorRepository`: one statement matching both anchor columns, joined twice
      to `journals` so both anchor titles arrive with the row, `ORDER BY t.id`. Pinned by counting the
      statements PostgreSQL actually receives for three blockers.
- [x] `JournalService.delete_journal` refuses when that set is non-empty, raising a domain error carrying
      the blocking tasks and their action journals — **regardless of task status**, since a done task's
      creating link is part of the record. — `JournalHasAnchoredTasksError` (409), raised before anything
      else is read or written; asserted for `not_done`, `done` and `cancelled`.
- [x] A journal linked **only** as an intermediate journal still deletes; its link rows go with it and the
      tasks are otherwise unaffected. — asserted end to end: journal gone, `task_intermediate_journals`
      row cascaded away, task row and both anchors unchanged.
- [x] The guard replaces the raw FK violation: no caller ever sees an unhandled `IntegrityError`. — the
      guard runs on the *only* path that reaches `JournalRepository.delete` through the service, the
      delete itself is wrapped for the check-then-act window, and the background calendar-sync deleter
      now cancels rather than fails. Merge is the stated exception — it deletes the absorbed journal
      directly and is Phase 3's.

**Decisions taken (Phase 1):**

- **Open decision 1 — `409 Conflict`,** on the `RouteInUseError` precedent; see the struck decision above.
- **The rule lives in the journal domain, the query in the tasks domain.** Which roles block and which
  anchor supplies the action journal are pure functions in
  `core_shared/core_shared/models/journals/task_anchor.py`, alongside the `BlockingTask` the error
  carries; the SQL that finds the rows stays in the tasks domain, which owns the `tasks` table. Putting
  `BlockingTask` in the journal package rather than the task one is deliberate: `core_shared.models.tasks`
  now imports nothing from `models.journals`, so the task read models ITER18-001 still has to ship cannot
  close an import cycle between two eagerly re-exporting packages.
- **`task_anchor_repo` is a required keyword-only constructor argument.** `JournalService` already has
  two optional collaborators, but both *degrade a feature* when absent (flat tag filtering, no contact
  relationships) whereas a missing guard would let a delete leave the model in a state the specification
  calls impossible. Keyword-only and last, so the one positional construction site still compiles and
  mypy names the other twenty-three.
- **`SqlTaskAnchorRepository` is provided by `JournalProvider`, not `TaskProvider`.** Dishka validates
  the entire graph at construction, so a `JournalProvider.journal_service` depending on something
  `TaskProvider` supplies would break every container that registers one without the other — about a
  dozen test containers, including the one the whole API integration suite runs on. The adapter needs
  only the connection, so provision follows the consumer while ownership stays with the tasks domain.
- **The query is deliberately not owner-scoped** — the one task read that is not. It stands in for a
  foreign-key check and has to see every row the `RESTRICT` anchors see; a row it filtered away would
  come back as the raw `IntegrityError` the guard exists to replace. `delete_journal` and the journal
  lookup before it are themselves unscoped, so nothing new is exposed. Recorded in the port docstring.
- **The check-then-act window is closed by a backstop, not a lock.** Under READ COMMITTED a task can be
  anchored to the journal between the guard and the `DELETE`. Locking every candidate row to prevent it
  would cost more than the outcome is worth — the delete fails either way — so the `DELETE` is wrapped
  instead: an `IntegrityError` re-runs the guard and raises the same explanatory error, and re-raises the
  original untouched when the re-check is empty, so an unrelated constraint can never masquerade as a
  task conflict. Same shape as ITER18-001 Phase 4's vanished-anchor handling.
- **A blocker that vanishes mid-race is retried, not reported.** Raised by the PR's automated review: if
  the racing task is cancelled, retargeted or deleted between the foreign key firing and the guard
  looking, the re-check comes back empty and the original violation was re-raised — a 500 about a row
  that no longer exists, which is exactly what the "no unhandled `IntegrityError`" criterion forbids.
  Nothing blocks the journal by then, so the delete is retried **once**; a second failure is a constraint
  the guard cannot explain and propagates untouched. Covered at both levels, and the integration test
  stages the race by having the second look-up remove the task, as the racing writer would have.
- **Deleting somebody else's journal now reports it missing, on both surfaces.** Also raised by the
  review, as the highest-severity finding, and it was right: the delete path never compared the journal's
  owner to the acting user, so the new refusal would have named *another user's* task text and journal
  titles to any authenticated caller who guessed an id — a disclosure the previous foreign-key 500 did
  not make. The REST controller and the MCP tool now read the journal owner-scoped first and raise
  `JournalNotFoundError`, which is the MCP read tool's existing stance and says nothing about whether the
  journal exists. **The wider hole is older and larger than this phase:** `GET /api/journals/{id}` and the
  other journal endpoints still do not check ownership, and `JournalService` takes no user id at all.
  Only the surface this phase changed is fixed here; the rest is recorded as **issue #1267**.
- **And the backstop only works because the `DELETE` sits in a SAVEPOINT — which only a real database
  showed.** A failed statement poisons its transaction, so the re-check query PostgreSQL would refuse
  outright passed happily against a mocked connection. Wrapping the delete in `savepoint(transaction)`
  confines the aborted statement, leaving the request's transaction usable for the re-read and for
  whatever the caller does next. Pinned by an integration test that stages the race — the first look-up
  misses, which is exactly what the window produces, while the row is really there for the foreign key
  to refuse on — and mutation-checked by removing the savepoint, which fails it.
- **A cancelled calendar event now cancels an anchored instance instead of failing — on both of its
  paths.** `JournalOutboxEventProcessor` deletes far-future recurring instances, which is exactly the
  profile of a task's due journal. Left alone, the guard would have turned a routine sync event into a
  permanent retry loop over a journal that is never going to become deletable. Both the series fan-out
  and the **single** `journal_event.cancelled` path now catch the refusal and mark the instance
  cancelled — the same outcome an instance the existing deletion-protection facts protect already gets,
  and the escape hatch the guard steers users toward. The second path was missed on the first pass and
  found by the PR's automated review; the deletion attempt removes the instance's external links before
  it reaches the journal, so both call sites wrap it in a savepoint and the refused attempt leaves no
  trace. Mutation-checked at each site by removing its catch.
- **`JournalWriteService.delete_journal` was not touched**: it delegates to `JournalService`, so a second
  guard there would be duplicate enforcement, not defence in depth.

**Required Test Coverage:** unit — blocking detection by role and the action-journal choice, including the
delete-the-due-journal case. Integration — blocked delete raises the domain error (not an `IntegrityError`)
for not-done, done and cancelled tasks; intermediate-only delete succeeds; a task-free journal still
deletes; one query for many tasks. No e2e (Phase 5).

- **Unit (19 tests):** `backend/tests/unit/journal/test_journal_delete_guard.py`. *The rule (7):* a task
  created in the journal blocks and is actioned from its due journal; a task due in it is actioned from
  its creating journal; creating == due blocks in both roles and is actioned from that same journal (the
  delete was refused, so it is still there to open); a row anchored to neither blocks nothing — the rule
  is total rather than trusting the query's filter; and each of the three statuses is carried through.
  *The error (7):* it is a 409; it maps to its own response code rather than the catch-all; it names the
  task and the action journal's title *and* id in one phrase, so a caller can build a link from the
  message alone; it steers toward cancelling the journal; it names every blocker in order with the right
  count; it renders each role's prose exactly; and a roleless task is refused rather than described.
  *The guard (5):* it refuses before `delete` or any event; it asks the repository exactly once for the
  journal being deleted; a journal nothing anchors still deletes and publishes; the `IntegrityError`
  backstop explains a task inserted in the window; an unrelated violation is re-raised untouched.
- **Integration (13 tests):** `backend/tests/integration/tasks/test_journal_delete_guard_integration.py`
  (12) — the due journal refused for each of the three statuses with the creating journal as the action
  journal and the journal row still present; the creating journal refused with the due journal as the
  action journal; creating == due refused in both roles; the failure carries no constraint text; a task
  that appears after the check still gets the explanation, on a connection still usable afterwards; an
  intermediate-only journal deletes with its link row and leaves the task and anchors whole; a task-free
  journal deletes; three blockers arrive in **one** statement in id order; a journal only mentioned by a
  task has no blockers; and the container resolves both the adapter and a guard-carrying `JournalService`.
  Plus `test_journal_series_sync_processor.py` (2) — a series cancellation whose instance a task is due
  in reports `deleted=0, cancelled=1`, and a single instance cancellation of the same shape reports no
  deletion; both leave the journal cancelled rather than gone, the task's anchor intact and, for the
  single path, the external link the attempt had removed restored by the savepoint. Plus the two
  ownership tests below.
- **Ownership (2 tests):** `tests/integration/api/test_journal_endpoints.py` and
  `tests/integration/mcp/test_journal_tools_integration.py` — deleting another user's journal, with a
  task anchored to it, answers exactly as it does for an id that never existed and leaves the journal
  standing. Both were mutation-checked, and without the check the other user's task text is right there
  in the response: a 409 over REST, and the tool payload over MCP.
- **Statement counting, not call counting.** `AsyncConnection.execute` cannot be patched (the attribute is
  read-only), which turned out to be the better test: the "one query" assertion listens for
  `before_cursor_execute` and counts round trips to PostgreSQL, so a repository that looped internally
  would be caught however it issued its queries.
- **Mutation checks, including two that did not say what was expected.** Removing the `except
  IntegrityError` backstop fails the window test at both levels; removing the outbox processor's catch
  fails the series-cancellation test. The other two are worth recording because they were *surprises*:
  - **Removing the pre-check leaves every blocked-delete integration test green.** The backstop catches
    the same violation and raises the same error, so the two mechanisms overlap by construction. What
    discriminates the pre-check is the unit assertion that `journal_repo.delete` is never called and no
    event is published — that fails, along with the window test. The pre-check is kept regardless: it is
    what the acceptance criterion asks for, it refuses without issuing a doomed `DELETE` or dirtying the
    transaction, and it is the only one of the two that can be reached without a failed statement.
  - **Removing `ORDER BY t.id` fails nothing.** Three rows inserted in one transaction come back in
    insertion order on a plan this small, so the assertion is a canary rather than a test. Kept because
    the order is a real guarantee the error message depends on and the plan is not; recorded here rather
    than left to look load-bearing.
- **Seeding:** `tests/integration/tasks/task_seeding.py` gained `create_task` and
  `link_intermediate_journal`, both raw inserts. `TaskService` can only produce a not-done task due in a
  future journal, and the states worth guarding — done, cancelled, due in a journal that has since
  passed — are ones a task reaches later in its life.
- **E2E:** none — deferral taken as stated. No frontend file changes in this phase; the delete-failure
  dialog and its e2e land in Phase 5.
- **One line of Phase 2's surface is here, with its test.** `error_handlers.py` gained the
  `JOURNAL_HAS_ANCHORED_TASKS` code entry, so a blocked `DELETE /api/journals/{id}` is already a clean 409
  rather than the `DOMAIN_ERROR` catch-all, and the REST and MCP docstrings say the call can be refused.
  The structured payload listing the blockers — what Phase 2 is actually for — is not here.
- **Docs:** `docs/architecture/domain-architecture.md` gained a *The journal delete guard* section (the
  rule's home, the unscoped query, the required collaborator, the provider placement, the savepoint-backed
  backstop, the sync fallback, and why merge is deliberately unguarded).

#### Phase 2: Delete Guard Surfaces — REST and MCP

**Prerequisites:** Phase 1.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] `DELETE /api/journals/{id}` returns the structured error (status per open decision 1), naming each
      blocking task and its action journal.
- [ ] MCP `delete_journal` returns the equivalent in the same PR, so an agent can resolve the blockage
      without the UI.
- [ ] The payload is explanatory prose **plus** machine-readable ids — not an opaque constraint message —
      and the ids are enough to build a link without a further lookup.

**Required Test Coverage:** unit — error-to-response mapping and payload schema. Integration — both
surfaces with several blocking tasks, with a done-only blocker, and with intermediate-only links (succeeds).
No e2e (Phase 5).

#### Phase 3: Merge — Re-pointing and De-duplication ✅ COMPLETE

**Prerequisites:** ITER18-001 Phase 5. **Merged after Phase 1**, which changed where this phase's row
work lives — see below.
**Estimated diff:** ~140 production → **~560 tracked** (×4) · **Actual:** ~274 production → **~1277
tracked** across 12 files (production 274 — repository SQL and its docstrings 213, port contract 47,
service 8, DI 3, MCP tool construction 3 — 810 tests and fixtures, 193 docs). The production estimate
was the right order (274 against 140, and 154 of it before four review findings were addressed), which
is roughly what calibration rule 13's ×4 assumes for a phase that wires an existing rule to a new
surface. **The tests did not follow: 810 test lines against 274 production is 3.0×, and the total is
4.7× the production figure.**

**Why the tests overran when the production code did not.** The four statements are short, but each one
exists to prevent a *different* failure the others cannot: a `RESTRICT` refusal, a silent `CASCADE`
deletion, a primary-key collision, and a redundant row. None of those is observable from the others'
tests, and none is observable at all without a real database — so the phase needs one integration test
per failure mode plus their mirrors (446 lines), and then the same journey again at each of the two
merge surfaces, because REST resolves the service from Dishka while the MCP tool constructs it by hand
and neither proves the other. This is Phase 4's rule-defining pattern in a different guise: **when the
deliverable is "an operation that must not corrupt data", the test count is set by the number of ways
the data can be corrupted, not by the size of the code that prevents it.** Suggested amendment to rule
13: for a phase whose acceptance criteria are *integrity* outcomes, estimate tests at ~4–5× production
even when the production estimate itself is sound.

**The re-point lives on `TaskAnchorRepository`, and Phase 1 is why.** This phase was built first, against
`TaskRepository`, and rebasing onto Phase 1 made that placement obviously wrong twice over. Phase 1 had
introduced a port for exactly this boundary — the journal domain asking about task rows it does not own —
with the explicit rationale that the journal domain "must not be handed the ability to write tasks in
order to find out whether it may delete a journal". A merge service holding the full `TaskRepository`
could change a task's text, status or contacts, or delete one outright; holding `TaskAnchorRepository` it
can do exactly two things, both of which are anchor integrity. The port's "deliberately not owner-scoped"
paragraph was already written, and re-pointing needs the same exemption for the same reason.

**It also deleted a lesson this phase had recorded.** Before the rebase, giving `JournalMergeService` a
`TaskRepository` broke **eleven test containers** — Dishka validates the whole graph at construction, so
every container registering `JournalProvider` without `TaskProvider` failed with
`GraphMissingFactoryError` before a single test body ran, and each had to register a provider it had no
interest in. Phase 1 had already solved that by providing `SqlTaskAnchorRepository` **from
`JournalProvider`**, following the consumer while ownership stays with the tasks domain. Moving onto that
port took those eleven files back to untouched and cut the phase from 24 changed files to 12. **The
carry-forward is not "cross-domain dependencies tax every container" but the narrower, more useful rule
Phase 1 found first: when one domain needs a sliver of another, give it a port scoped to the question and
provide it from the consumer's own provider — the alternative fans out over every container in the
suite.**

**Deviation recorded before work started — where the "re-pointing rules" unit tests went.**

The required coverage below asks for **unit** tests of "re-pointing rules and the creating-equals-due
outcome". Those rules are four set-based statements over two tables; the only way to unit-test them
would be to re-express them as a pure Python function that production never calls, and then assert the
copy rather than the code. **So the split was moved rather than the coverage:** the unit tests hold the
service's *orchestration* — that the re-point happens exactly once, with the ids the right way round,
**before** the source journal is deleted, and that merge touches no other task-repository method (which
is how "merge never changes a status" is asserted at that level, since the service has no other route
to a task). The rules themselves are pinned against the real schema in
`tests/integration/tasks/test_journal_merge_task_links_integration.py`.

This follows Phase 4's recorded finding directly — *"for a rule whose failure mode is an error-message
shape, the integration test is not a confirmation of the unit test — it is the only real test"* — and
here it is stronger still, because two of the four failure modes (a primary-key violation and an
`ON DELETE CASCADE`) **cannot exist** outside a database. The de-duplication test was verified as a
genuine detector rather than assumed to be one: with statement 1 removed,
`test_duplicate_intermediate_links_collapse` fails on the duplicate key, and passes again when it is
restored.

**Six latent bugs review caught, and what they say about writing a set-based repair.**

The first two were in the fourth statement's *scope* rather than in any of the four statements' logic,
and neither was reachable from a surface that ships today — which is exactly why they needed a reviewer
rather than a test.

1. **The redundancy cleanup deleted bystanders.** As first written, statement 4 said "no task keeps an
   intermediate link to a journal that is now one of its anchors" and applied it to every task, with a
   code comment claiming that state could only arise from this merge. **It cannot claim that.** Nothing
   forbids the shape, and the specification's own retarget rule *manufactures* it: retargeting keeps the
   previous due journal as an intermediate link (§*Retargeting*), so retargeting back onto that journal
   leaves it an anchor and an intermediate link at once. An unrelated merge into that journal would then
   silently delete a task's record of where it had been. Fixed by reading the ids of the tasks that
   reference the absorbed journal **before** anything moves — afterwards there is nothing left pointing
   at it to identify them by — and restricting statement 4 to that set. **The lesson: a set-based repair
   states an invariant over the whole table, so it is only safe if the invariant is actually enforced.
   Ours was not; scoping to the rows the operation touched is the honest version.**
2. **Passing the same journal as source and target destroyed its links.** `merge_journals` refuses a
   self-merge upstream, so the repository never saw it — but the port presents the method as a general
   primitive and promises idempotence, and statement 1's `EXISTS` matches each intermediate link against
   itself, so every one would have been deleted. Fixed with an early return.

The **third through sixth** came from the PR review, and they are the ones that bite hardest on the
phase's own promise, because every one of them ends with a merge failing on task rows.

3. **A task anchored to the absorbed journal mid-merge.** The affected-task read is a non-locking
   snapshot, so a concurrent `create_task` could anchor a task to the absorbed journal *after* the
   re-point and *before* the merge's delete: nothing moves it, and the delete then fails on the
   `RESTRICT` foreign key. Closed by taking `FOR UPDATE` on the absorbed journal before the snapshot —
   inserting a task takes `FOR KEY SHARE` on each anchor journal to hold its own foreign key, and
   `FOR UPDATE` is the weakest mode that conflicts with it, so a concurrent creation waits for the merge
   and then fails its own anchor check against a journal that is genuinely gone.
4. **Two merges into the same survivor.** If a task has intermediate links to *two* journals and both are
   absorbed into the same target concurrently, both merges clear the de-duplication step before either
   has written its `(task_id, target)` link, and the second `UPDATE` violates the composite primary key.
   **This one is not reachable through `JournalMergeService` today** — it writes the target journal row
   at step 1, so two merges into the same target already serialise there — but that is a property of one
   caller rather than of the method, and a caller that stopped writing the target would silently reopen
   it. Closed by locking the survivor as well, **in ascending id order** so two merges sharing a journal
   queue rather than deadlock.

5. **The lock order was a claim, not yet a fact.** Sorting the two journal ids inside
   `repoint_journal_links` only prevents a deadlock if that call is the transaction's **first** claim on
   either row — and it was the *last* step of the merge, by which time `journal_repo.save(target)` had
   already taken the survivor's row lock out of order. Two merges in opposite directions (A into B, B
   into A) would each hold the other's target and deadlock. Fixed by moving the re-point to **step 0**,
   before every other write, which is where the ordering guarantee actually holds. The unit test was
   strengthened from "before the delete" to "before the save *and* the delete", so the property that
   matters is the one asserted.
6. **And one deadlock no lock order can close, recorded rather than hidden.** Inserting a task takes its
   `FOR KEY SHARE` locks in foreign-key declaration order — creating anchor, then due anchor — which is
   the task's own pairing, not an ordering of ids. A task created with its creating anchor on the
   survivor and its due anchor on the absorbed journal grabs the higher id first, against this method's
   lower-id-first, and PostgreSQL aborts one side. **This is strictly smaller than the window the lock
   closes** — before it, *any* concurrent creation anchoring to the absorbed journal failed the merge —
   but it is not zero, and the docstring says so instead of claiming the locks made deadlock impossible,
   which is what it claimed before review round 3.

**All of these are documented rather than pinned**, on the same terms ITER18-001 Phase 2 recorded for
`_require_task_owned`'s `FOR KEY SHARE`: the integration fixture is one savepoint-bound transaction, so a
second connection cannot see the journals involved, and the serialised form of any of these cases does
not distinguish a held lock from an absent one. **The general lesson, learned three times over in one
phase: "never blocked" is a concurrency claim. A snapshot read followed by a delete does not make it
true; nor does a guarantee resting on what some other layer happens to write first; nor does sorting
lock acquisitions in one method while an earlier statement in the same transaction has already taken one
of them.**

**The first two fixes are pinned by tests that were verified to fail without them**, on the same footing
as the de-duplication detector: `test_a_bystanders_redundant_link_is_left_alone` (which needed a second,
genuinely-merged task, because without one the new early return means statement 4 never runs and the
test would have passed for the wrong reason) and `test_repointing_a_journal_onto_itself_changes_nothing`,
the one test that calls the repository directly because no merge can reach that case.

**Acceptance Criteria:**

- [x] `JournalMergeService` re-points every task link from the absorbed journal to the survivor — creating,
      due and intermediate — **before** it deletes the source, so the merge never trips the anchor FK. —
      new step 10 in `merge_journals`, immediately before `_publish_events_and_cleanup` (which is what
      deletes the source). The ordering is asserted directly, not implied: a unit test records the call
      order and fails if the step moves after the delete.
- [x] A task can never end up linked twice to the same journal **in the same role**; duplicates are removed
      **before** the update statement rather than relying on `ON CONFLICT`, which is unavailable on an
      `UPDATE` (the ITER17-001 Phase 4 lesson). — statement 1 is a `DELETE … WHERE EXISTS` in the same
      shape as `JournalTagRepository.merge_into`. The two anchors are single-valued columns, so the
      same-role duplicate is only reachable through `task_intermediate_journals`, which is where the
      composite primary key lives.
- [x] A survivor that becomes both the creating and the due journal of a task is permitted and the task is
      unaffected. — not special-cased: statement 3 re-points both anchors in one `UPDATE` with a `CASE`
      per column, so a task anchored to the source in both roles simply ends up with the survivor in
      both. Asserted with text and status unchanged.
- [x] The cross-role redundancy in open decision 2 is handled as decided. — statement 4, in both
      directions, with a test each, and **restricted to the tasks this merge touched** for the reason
      recorded above.
- [x] Merge **never** changes a task's status, and merge is never blocked by tasks — it stays usable for
      calendar-sync workflows, as the specification requires. — `status` and `text` are absent from
      statement 3's `SET` list; asserted per status value (`not_done`, `done`, `cancelled`) and, at the
      unit level, as "no other repository method is called".
- [x] The row work lives in the repository, not the service, matching the journal domain's SQL-free service
      convention. — `TaskAnchorRepository.repoint_journal_links` owns all four statements plus the locks;
      the service's addition is one keyword-argument call. It sits on the **anchor** port Phase 1
      introduced, not on `TaskRepository`, so the journal domain can move task links without also being
      handed the ability to change a task's text, status or contacts. Like everything on that port it is
      **journal-scoped rather than owner-scoped**, and deliberately so: the source journal is about to be
      deleted and its anchors are `RESTRICT`, so a row skipped by an owner filter would fail the merge.
      The merge has already established that both journals share an owner.

**Required Test Coverage:** unit — re-pointing rules and the creating-equals-due outcome. Integration —
merge with overlapping links raises no duplicate-key error **and the test fails if the de-duplication step
is removed**; merging a journal that anchors a task succeeds end to end (the regression this phase exists to
prevent); children/tags/contacts behaviour unchanged; status untouched. No e2e (Phase 5).

**Delivered:** 4 unit tests (`tests/unit/journal/test_journal_merge_service.py::TestTaskLinkRepointing`)
and 17 integration tests — 15 in `tests/integration/tasks/test_journal_merge_task_links_integration.py`
(13 test functions, one parametrised over the three statuses) covering each anchor, the intermediate
link, duplicate collapse, creating-equals-due, both cross-role directions, the bystander whose link must
survive, the self-repoint no-op, every status, orphan rows, an untouched unrelated task and
children/tags/contacts still moving; plus one at each merge surface
(`tests/integration/api/test_journal_merge_endpoint.py`, `tests/integration/mcp/test_journal_tools_integration.py`)
because the REST path resolves the service from Dishka while the MCP tool builds it by hand, so neither
is evidence for the other. `tests/integration/tasks/task_seeding.py` gains a shared `create_task`
seeder, which deliberately goes through the repository rather than `TaskService.create_task`: the
future-dated rule is a creation-time invariant, so the service cannot produce a done or cancelled task
to merge around. **No e2e and no frontend code**, as the phase specifies — the delete-failure UI and its
e2e are Phase 5.

#### Phase 4: Cancellation as a Lapse Reason

**Prerequisites:** ITER18-001 Phase 12.
**Estimated diff:** ~100 production → **~400 tracked** (×4)

**Acceptance Criteria:**

- [ ] Cancelling a journal changes no task links.
- [ ] A not-done task whose **due** journal is cancelled reads as lapsed with the cancellation reason
      through every read surface — the behaviour derived in ITER18-001 Phase 12, pinned here end to end
      against real journal cancellation rather than a constructed read model.
- [ ] Cancelling a journal that is a task's **creating** journal changes nothing about the task.
- [ ] Cancelling a journal that anchors a task is never blocked — cancellation is the escape hatch the
      delete guard steers users toward.
- [ ] The UI wording for the two lapse reasons ships in ITER18-001 Phase 16; this phase adds no frontend
      code.

**Required Test Coverage:** integration — cancel a due journal and observe the lapse with the cancellation
reason through `get_task`, `list_journal_tasks` and the upcoming-window listing (where it must be excluded);
done and cancelled tasks unaffected; cancelling a creating journal is inert; cancellation is never blocked.
No unit work beyond what Phase 12 covers. No e2e (Phase 5).

#### Phase 5: Frontend — Delete Failure Explanation and E2E

**Prerequisites:** Phases 2–4.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] The journal delete flow surfaces the blocking tasks: each named, each linking to the journal where it
      can be actioned, with working navigation.
- [ ] The dialog continues to steer toward cancelling the journal rather than deleting it.
- [ ] A delete that succeeds is unchanged from today's behaviour.
- [ ] E2E: deleting a journal with a task due in it shows the explanation; following the link reaches a
      journal where the task can be actioned; after cancelling or retargeting the task, the delete succeeds;
      merging a journal that anchors a task succeeds. Deterministic per-test fixtures, built with the
      Phase 22 helpers and their UTC-boundary caveat.

**Required Test Coverage:** unit (RTL) — the failure dialog rendered from the error payload, with one
blocker and with several. E2E as above, on both e2e projects.

### ITER18-003: Task Events, Field History, and Activity Records

**Objective:** Make tasks full domain-event citizens: publish the specification's event set with
provenance, project it into `field_history`, surface a linked contact's tasks in their activity history,
and pin that the search indexer ignores task events.

**Independently deliverable because:** it adds records and history to an entity that already works, with
no change to task behaviour. Nothing else depends on it, but it should not lag ITER18-004.

**Relevant documents:**

- Specification §*Events and history*, §*Tasks and search*, §*Contacts on tasks*
- [Activity History Product Specification](../product-specifications/activity-history-product-specification.md);
  [Iteration 12](./iteration-12-activity-history.md) for the projection pattern
- `HistoryService._HANDLERS`, `HistoryProjectionConsumer`, `SearchIndexerConsumer`,
  `FieldHistoryRepository.get_history_for_aggregate`

**Acceptance Criteria:**

- [ ] Task writes publish domain events through the existing outbox publisher, **inside the same unit of
      work** as the write, covering at minimum: task created, text updated, status changed, due journal
      retargeted, journal linked/unlinked, contact linked/unlinked, task deleted.
- [ ] Every event carries provenance (`source`) and actor (`changed_by`) consistent with the activity
      history specification, so UI, MCP, system and integration origins are distinguishable.
- [ ] `HistoryService` projects each task event into `field_history` rows under a task entity type, via
      the existing pure-mapping dispatch table; `HistoryProjectionConsumer` writes them idempotently, so
      stream redelivery produces no duplicates. Row timestamps come from `event.occurred_at`.
- [ ] A task's change history is **readable**, with MCP parity, and rendered on the journal surface that
      owns the task (tasks have no route of their own — see open decision 1).
- [ ] A task appears in a linked contact's activity history as a **read-only record** alongside their
      journals and other activity: not actionable from there, and not filterable down to "everything
      outstanding". This is a record of the past, not a third working surface.
- [ ] The search indexer **ignores** task events rather than failing on them: no tasks index is created,
      no task is ever returned by global search, and a task event never dead-letters in the
      `search-indexer` group.
- [ ] Not wireframe-bearing: history and activity records are journal- and contact-page surfaces, absent
      from the dashboard wireframe by design.

**Required Test Coverage:**

- **Unit:** the projection mapping for each event type, including the field names and marker fields used
  for create/delete/status/retarget, and that an unknown event type projects to no rows.
- **Integration:** publish → relay → projection end to end for each event type, asserting idempotency on
  redelivery; the `search-indexer` group consumes a task event without indexing anything and without
  dead-lettering; a contact's activity history includes the task entry with the right provenance; the
  task history read surface (REST + MCP) returns entries in the expected order.
- **E2E:** a task change made in the UI appears in the relevant activity feed with UI provenance; a task
  linked to a contact appears on that contact's activity history and offers no action there.

**Open decisions:**

1. **Where task history is read from** — settled in **Phase 4**. Tasks have no route, so either (a) a
   task-scoped read (`GET /api/tasks/{id}/history` + `get_task_history`, registering a `"task"`
   aggregation strategy), rendered in an expandable row on the journal, or (b) folding task rows into the
   due journal's existing feed. (a) keeps the aggregation model honest and matches the journal/contact
   precedent; (b) adds no new surface.
2. **Whether task events need typed payload models** in `core_shared/models/outbox_events.py` — settled in
   **Phase 1**. The existing typed models cover integration-sync payloads (`contact.*`,
   `journal_event.*`), while domain events like `JournalTagAssigned` are not in that dispatch map. Match
   the domain-event convention unless a worker needs to consume task events.
3. **Whether the contact-activity entry updates on task status change** or records only the link —
   settled in **Phase 5**. The specification asks for "a read-only record alongside their journals", which
   the simpler link-based entry satisfies.

> **Why nine phases for "add some events".** Iteration 17 measured it: two event types plus their
> projection cost ~1440 lines (ITER17-005 Phase 1) and *one* type plus projection cost ~1270
> (Phase 2a), and it recorded the conclusion — *"a future phase adding an event type should budget ~600
> test lines per type up front"*. Tasks need nine event types. Calibration rule 6 therefore caps this
> iteration at two new types per phase, with the projection split from the publishing.

#### Phase 1: Events — Task Created and Deleted

**Prerequisites:** ITER18-001 Phase 9.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] Domain event classes for task created and task deleted, following the journal/contact domain-event
      conventions (`source` provenance, `changed_by`, `occurred_at`, aggregate id).
- [ ] Each is published through `OutboxEventPublisher` **inside the same unit of work** as its write, so an
      event never exists for a write that rolled back.
- [ ] Provenance is threaded from the caller, so UI, MCP, system and integration origins are
      distinguishable on every event.
- [ ] Open decision 2 recorded here: whether task events need typed payload models in
      `core_shared/models/outbox_events.py` (that dispatch map covers integration-sync payloads; domain
      events like `JournalTagAssigned` are absent from it, which is the convention to match unless a worker
      must consume task events).
- [ ] The aggregate id is the task id, consistent with the integer decision taken in ITER18-001 Phase 1.

**Required Test Coverage:** unit — event construction and payload shape for both types. Integration — each
write leaves exactly one outbox row with the right type, provenance and payload; a rolled-back write leaves
none. No e2e.

#### Phase 2: Events — Text Updated and Status Changed

**Prerequisites:** Phase 1, ITER18-001 Phase 6.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] Event classes and publishing for text updated and status changed.
- [ ] Status-change events carry old and new status in the `changed_fields` shape the history projection
      expects — `[old, new]` after the JSON round trip through Redis.
- [ ] Same-unit-of-work publishing and provenance threading as Phase 1.

**Required Test Coverage:** unit — payload shape per type, including the positional `changed_fields` form.
Integration — outbox rows per operation; rollback leaves none. No e2e.

#### Phase 3: Events — Due Journal Retargeted

**Prerequisites:** Phase 1, ITER18-001 Phase 8.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] Event class and publishing for the due-journal retarget, carrying old and new due journal.
- [ ] A retarget publishes **both** its retarget event and the automatic intermediate-link event (whose
      class lands in Phase 4) in a deterministic order, so the projection can render the trail coherently.
      Until Phase 4 lands, the auto-link is carried as part of the retarget payload rather than a second
      event — state which shape is chosen.
- [ ] A retarget that also reopens a done task makes the status change visible in the event stream, not
      only in the task row.

**Required Test Coverage:** unit — payload including the old/new pair and the reopen case. Integration —
outbox rows and their ordering. No e2e.

#### Phase 4: Events — Journal Linked and Unlinked

**Prerequisites:** Phase 3, ITER18-001 Phase 10.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] Event classes and publishing for intermediate journal linked and unlinked.
- [ ] The automatic link created by a retarget publishes the same event type as a manual attach, with
      provenance distinguishing system-derived from user-initiated.
- [ ] Same-unit-of-work publishing and provenance threading.

**Required Test Coverage:** unit — payloads and the provenance distinction. Integration — outbox rows for
manual attach/detach and for the retarget-derived link. No e2e.

#### Phase 5: Events — Contact Linked and Unlinked

**Prerequisites:** Phase 1, ITER18-001 Phase 11.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] Event classes and publishing for contact linked and unlinked.
- [ ] Same-unit-of-work publishing and provenance threading.
- [ ] With this phase the specification's full event set is published: created, text updated, status
      changed, due journal retargeted, journal linked/unlinked, contact linked/unlinked, deleted.

**Required Test Coverage:** unit — payloads. Integration — outbox rows per operation; a completeness test
asserting every task write path publishes exactly one event. No e2e.

#### Phase 6: History Projection — Lifecycle Events

**Prerequisites:** Phases 1–2.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] `HistoryService._HANDLERS` gains handlers for created, deleted, text updated and status changed,
      mapping each to `field_history` rows under a task entity type, with marker field names consistent
      with the journal and contact conventions.
- [ ] `HistoryProjectionConsumer` subscribes to the task event patterns; writes stay idempotent
      (`ON CONFLICT DO NOTHING` on `(event_id, entity_type, entity_id, field_name)`), so stream redelivery
      is safe.
- [ ] Row `created_at` comes from `event.occurred_at`, not projection time.
- [ ] If ITER18-001 Phase 1 chose a UUID primary key, this phase also migrates `field_history.entity_id`
      off `Integer` — a shared table — and its estimate rises accordingly. With the integer default, no
      migration is needed.
- [ ] The consumer table in `docs/architecture/integration-architecture.md` is updated.

**Required Test Coverage:** unit — projected rows per event type and that an unknown type projects to none.
Integration — publish → relay → projection per type, asserting idempotency on redelivery. No e2e.

#### Phase 7: History Projection — Retarget and Link Events, and Search Isolation

**Prerequisites:** Phases 3–6.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] Handlers for retarget, journal linked/unlinked and contact linked/unlinked, producing rows that read
      as a trail (which journal, in which role, when).
- [ ] The **search indexer ignores task events**: no tasks index, no task document, no task event
      dead-lettering in the `search-indexer` group, and global search never returns a task. This holds by
      construction because the consumer only sees subscribed patterns — this phase **pins it with a test**
      so a future pattern change cannot silently start indexing tasks.
- [ ] With this phase every published task event has a projection; none is written and then unread.

**Required Test Coverage:** unit — projected rows per event type. Integration — end-to-end projection per
type with idempotency; the `search-indexer` group consumes a task event without indexing or dead-lettering.
No e2e.

#### Phase 8: Task History Read Surface — REST and MCP

**Prerequisites:** Phase 7.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple

**Acceptance Criteria:**

- [ ] Open decision 1 settled and recorded. If (a): a `"task"` aggregation strategy is registered alongside
      `"journal"` and `"contact"`, with a thin read service mirroring `JournalHistoryService`.
- [ ] **The delete case is the decision's discriminator:** tasks are hard-deleted, so a task-scoped read
      must resolve history by id **without requiring the task row to exist**, with ownership carried on the
      history rows — otherwise the `TaskDeleted` projection is written to a surface that can never read it.
- [ ] `GET /api/tasks/{id}/history` (paginated, most recent first) using the shared
      `History{Attributes,Resource,ListResponse}` schemas, scoped to the authenticated user so history
      cannot leak across users (the ITER12-002 lesson).
- [ ] MCP `get_task_history` in the same PR, mirroring `get_journal_history`.
- [ ] Provenance and actor are visible on every entry.

**Required Test Coverage:** unit — schema conversion and pagination. Integration — a task with a mixed event
history reads back in order on both surfaces; **a deleted task's history is still readable**; another user's
task history 404s. E2E in Phase 9.

#### Phase 9: Contact Activity Record and Frontend History

**Prerequisites:** Phase 8, ITER18-001 Phase 16.
**Estimated diff:** ~160 production → **~640 tracked** (×4) — the only phase touching the contacts surface,
and deliberately read-only (calibration rule 7)

**Acceptance Criteria:**

- [ ] A linked contact's activity history includes their tasks as **read-only records** alongside journals
      and other activity, per open decision 3.
- [ ] Entries are **not actionable** from the contact page and cannot be filtered down to "everything still
      outstanding" — a record of the past, not a third working surface.
- [ ] A task's own change history renders on the journal surface that owns it, reusing the shared
      history/activity feed components rather than a bespoke list.
- [ ] E2E: a task change made in the UI appears in the relevant feed with UI provenance; a task linked to a
      contact appears on that contact's history and offers no action there.

**Required Test Coverage:** unit (RTL) — feed rendering of task entries, provenance labels, absence of
actions. Integration — the contact history read includes task records with correct provenance. E2E as above,
on both e2e projects.

### ITER18-004: The Home Dashboard

**Objective:** Replace the placeholder home page with the daily briefing in the wireframe: the AI summary
as headline over agenda, tasks due this week, and upcoming contact dates, assembled server-side in one
round trip and anchored on today in the user's timezone.

**Independently deliverable because:** it is a self-contained new page over a new read-only projection.
It needs ITER18-001 for its tasks section, and nothing later. Its own phasing must not ship a tasks
section without the inline done action — the specification names that as an incoherent split.

**Relevant documents:**

- Specification §*The Home Dashboard* (purpose, composition, today's summary, agenda, tasks, upcoming
  dates, contact importance, loading/freshness/errors, navigation)
- **[Home Dashboard Wireframe](../design/home-dashboard-wireframe.md)** — W1–W33 and the seven known gaps
- Precedent: `OutdoorDashboardService` / `SqlOutdoorDashboardRepository` /
  `GET /api/journals/outdoor-dashboard` / `outdoor-logbook/page.tsx` /
  `frontend/src/lib/api/outdoor-dashboard.ts`
- [API Design — Outdoor Dashboard Endpoint](../architecture/api-design.md) for the singleton-resource
  convention; `writing-sql` skill for the new windowed queries

**Acceptance Criteria — page frame and summary:**

- [ ] `/` renders the dashboard inside the existing chrome with no chrome changes (**W1**); the
      placeholder cards, `frontend/src/__tests__/app/page.test.tsx` and the now-unused
      `homePageTestUtils.FEATURE_CARDS` fixture are **all removed** in the same phase.
- [ ] Page header: `h1` "Today" plus the localised full date and framing line (**W2**). The page takes no
      date parameters — it is always about now, anchored server-side on the user's configured timezone.
- [ ] The three evidence sections sit in an independent-height three-column grid on `lg`, stacking to one
      column in the order Agenda → Tasks → Upcoming dates below it (**W3**), each a `section` with an
      `sr-only` heading and labelled lists (**W4**).
- [ ] The summary card shows the **same** daily summary entity the journals view shows for today —
      distinguished visually from the evidence cards (**W5**) with its header label and a **Regenerate**
      action (**W6**) — read-only, with no edit affordance.
- [ ] All three summary states render per the wireframe: generated in full as prose (**W7**), generating
      with its badge and placeholder line (**W8**), and unavailable as one quiet line that makes clear the
      rest of the page still works (**W9**). Regeneration is user-requestable.
- [ ] The key-stats footer (journals, events, contacts, average mood out of ten) renders in the generated
      state only, from the counters the summary entity already carries (**W10**).

**Acceptance Criteria — agenda:**

- [ ] Card header and description per **W11**. Today's event journals are listed with **all-day items
      pinned above timed items** (**W12**) and timed items in ascending start-time order (**W13**).
- [ ] Each entry shows its title linking to the journal (**W14**), its time, its location where present
      (**W13**), its tags (**W15**) and its participants where present (**W16**), with the type accent bar
      (**W17**).
- [ ] Cancelled events are shown **clearly marked** — struck through with a cancelled badge and muted
      styling (**W18**) — or omitted; they must never appear as if they are still happening. The signal is
      `CalendarInfo.event_state == CANCELLED`.
- [ ] **Tomorrow** appears beneath today, collapsed by default, with its date label and event count
      (**W19**), expanding **in place** into entries of the same form (**W20**).
- [ ] When nothing is scheduled today, the agenda says so in a single line rather than rendering an empty
      container — built in the idiom of **W29** (wireframe gap 1).

**Acceptance Criteria — tasks:**

- [ ] Card header and description per **W21**. The section shows **not-done tasks whose due journal falls
      between today and seven days ahead, inclusive**, ordered by due-journal date soonest first
      (**W22**), capped at **five**, with a show-more revealing the remainder of the seven-day window
      (**W28**).
- [ ] Each entry shows the task text (**W23**), a relative due chip (`Today`, `Tomorrow`, then a short
      absolute form) (**W25**), the due journal's title as a link to it (**W26**), and any linked contacts
      (**W27**).
- [ ] Each entry offers **marking done inline** without leaving the dashboard (**W24**), and the section
      updates in place afterwards.
- [ ] Done, cancelled and **lapsed** tasks never appear — no overdue section, counter, badge or
      notification anywhere on the page.
- [ ] When the window is empty the section says so in one line, reading as a good outcome rather than an
      error or omission (**W29**).

**Acceptance Criteria — upcoming dates:**

- [ ] Card header and description per **W30**. The section shows important contact dates falling in the
      next **seven days**, matching the tasks window.
- [ ] Recurring dates (birthdays, anniversaries) are **resolved to their occurrence within the window**,
      respecting the stored precision: a `day_month` date still produces an occurrence, and a `full` date
      can show an age or a count of years where meaningful (**W31**).
- [ ] Each entry shows the contact (linking to them), the date type, the occurrence date and **how many
      days away** it is (**W31**), ordered by date ascending then by **contact importance descending**.
- [ ] The section is capped with a show-more revealing the rest of the window (**W32**); the cap value is
      an open decision (wireframe gap 3).
- [ ] When nothing falls in the window, the section says so in one line (**W29** idiom, wireframe gap 2).
- [ ] **Contact importance is inferred, never configured**: favourite status, then recent journal count,
      then recent activity count — the same signals and the **same order of precedence** the MeiliSearch
      contact ranking rules use, so a contact who ranks highly in search ranks highly here. No new
      user-facing importance field is introduced.

**Acceptance Criteria — assembly, resilience and navigation:**

- [ ] All four sections are retrievable **together in one round trip** as a read-only singleton resource
      whose id is the user id, following the outdoor dashboard convention, with no date parameters and
      every window anchored on today in the user's timezone.
- [ ] Nothing on the page mutates data except the inline task action and the user-requested summary
      regeneration (the wireframe's Regenerate control, **W6**, which persists even in the unavailable
      state).
- [ ] **Sections render independently:** a failed or missing summary must not prevent the agenda, tasks
      and dates from displaying, and vice versa.
- [ ] There is deliberately **no composite dashboard MCP tool** in this iteration. Agents compose the
      equivalent view from the daily summary tool, journal browsing, the task listing tools from
      ITER18-001, and the contacts tools. The tradeoff is recorded here as accepted, and no underlying
      capability is UI-only.
- [ ] The home page is reachable from the **primary navigation** and is the default view after sign-in —
      a deliberate addition to the wireframe, which shows only the header link (wireframe gap 4).
- [ ] Accessibility and responsiveness: labelled sections and lists (**W4**), keyboard-reachable inline
      actions (**W24**), disclosure state exposed on the tomorrow toggle (**W19**), single-column stacking
      below `lg` with no horizontal overflow (**W3**), and semantic colour classes so both themes work.

**Required Test Coverage:**

- **Unit:** section assembly and ordering rules (all-day before timed; time ascending; tasks soonest
  first; dates ascending then importance descending, including the tie-break precedence); the five-item
  cap and its show-more remainder; relative due-label derivation (today / tomorrow / absolute) at a day
  boundary; recurrence resolution for each `DatePrecision`, including a 29 February birthday and a
  window that crosses a year boundary; age/years derivation only where precision allows.
- **Integration:** the endpoint returns all four sections in one call with the expected shape; windows are
  anchored in the user's timezone (a test user in a non-UTC zone near midnight gets the *local* today);
  cancelled events are marked; lapsed, done and cancelled tasks are absent while the same tasks are
  present on their journals; a summary failure still returns the other three sections; the inline done
  action commits and the next read reflects it.
- **E2E (wireframe conformance):** with deterministic fixtures, the page renders the four sections in
  wireframe order with their headings; all-day items precede timed ones; exactly five tasks show with the
  show-more label naming the full count; ticking a task off removes it in place without navigation;
  expanding Tomorrow reveals its entries; a cancelled event carries its marker; the summary's three states
  (**W33**) and the three empty states each have their own test with their own fixtures — never a
  conditional branch. Also assert the placeholder cards are gone and the nav entry works.

**Open decisions:**

1. **Endpoint placement and name** — settled in **Phase 1**. `GET /api/dashboard` (a new top-level
   singleton) versus `GET /api/home-dashboard`; the outdoor precedent lives under `/api/journals/` because
   it is journal-scoped, which this is not.
2. **How the SQL side obtains the importance signals** — settled in **Phase 8**. Reuse the computation that
   feeds the search index (`search_indexer._fetch_complete_contact_data`) by extracting it into a shared
   read, or query the index itself. Extraction keeps the dashboard independent of MeiliSearch availability
   and is the likely answer; either way the precedence order must be pinned by a test alongside
   `test_ranking_rules.py`.
3. **The upcoming-dates cap** (wireframe gap 3) — settled in **Phase 8** (payload) and **Phase 9** (UI).
   Five matches the tasks section; the wireframe shows three rows and a show-more naming five.
4. **Which date types count as "important dates" for the dashboard** — settled in **Phase 7**. All five
   types, or only the recurring ones? `first_met` with `year` precision has no in-window occurrence.
5. **Whether "tomorrow" expansion is server-provided or lazily fetched** — settled in **Phase 4**. One
   round trip argues for including tomorrow in the payload; collapsed-by-default argues for lazy.

#### Phase 1: Dashboard Endpoint Skeleton and Section Envelope

**Prerequisites:** none.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] A read-only `HomeDashboardService` (no unit of work) and a **singleton JSON:API resource whose id is
      the user id**, following `OutdoorDashboardService` / `OutdoorDashboardResource` exactly.
- [ ] The endpoint (name per open decision 1) takes **no date parameters** and anchors "today" in the
      user's configured timezone via `UserSettingsRepository.get_timezone`, never UTC-today.
- [ ] The payload declares all four sections from the outset, present but empty, so later phases fill a
      stable contract rather than changing it.
- [ ] **Per-section resilience is in the contract**: every section can independently report unavailable and
      distinguishes *unavailable* from *empty*; a failure in one never fails the request. Asserted now,
      before three sections depend on it.
- [ ] DI wiring registered. No composite MCP dashboard tool is added; the deliberate omission and its
      accepted tradeoff are recorded in the service docstring.

**Required Test Coverage:** unit — assembly, per-section error isolation, empty-vs-unavailable, timezone
anchoring. Integration — the four-section envelope in one call; an injected section failure still yields 200
with the others. No e2e.

#### Phase 2: Summary Section in the Payload

**Prerequisites:** Phase 1.
**Estimated diff:** ~100 production → **~400 tracked** (×4)

**Acceptance Criteria:**

- [ ] The summary section returns today's existing daily summary — the **same** entity the journals view
      shows — with its status and the four counters the stat footer renders (**W10** data).
- [ ] A missing, failed or disabled summary renders as the section's unavailable state rather than an
      error, per the Phase 1 contract.
- [ ] Read-only: the payload exposes no mutation affordance; regeneration remains the existing endpoint.

**Required Test Coverage:** unit — mapping each `SummaryStatus` to the section's state. Integration — the
section against real summary rows in each status. No e2e.

#### Phase 3: Page Shell — Retire the Placeholder, Add Navigation

**Prerequisites:** Phase 1.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — net smaller than it looks: the placeholder
deletions offset the new page (the ITER17-003 Phase 2 gross-vs-net lesson)

**Acceptance Criteria:**

- [ ] `frontend/src/app/page.tsx` renders the dashboard: `h1` "Today", the localised full date and framing
      line (**W2**), inside the existing chrome unchanged (**W1**).
- [ ] The three evidence sections sit in an independent-height three-column grid on `lg`, stacking to one
      column in the order Agenda → Tasks → Upcoming dates below it (**W3**), each a `section` with an
      `sr-only` heading and a labelled list container (**W4**) — rendered as empty-state cards until their
      phases land.
- [ ] The six placeholder cards, `frontend/src/__tests__/app/page.test.tsx` **and** the now-unused
      `homePageTestUtils.FEATURE_CARDS` fixture in `frontend/src/test-utils/index.tsx` are all removed in
      this PR; leaving the fixture behind would imply the placeholder still exists.
- [ ] A primary-navigation entry for the dashboard (wireframe gap 4), and the home page is the default view
      after sign-in.
- [ ] One shared TanStack query feeds the page so concurrent section mounts dedupe into a single fetch,
      following `frontend/src/lib/api/outdoor-dashboard.ts`.
- [ ] No horizontal overflow at any breakpoint; semantic colour classes so both themes work.

**Required Test Coverage:** unit (RTL) — header, section scaffolding and labelling, single-column stacking
markers, nav entry active state, and that the removed fixture has no remaining importers. E2E in Phase 17.

#### Phase 4: Summary Card

**Prerequisites:** Phases 2 and 3.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] The summary card renders visually distinguished from the evidence cards with its accent bar and
      header label (**W5**, **W6**), including the **Regenerate** action wired to the existing regenerate
      endpoint — which **persists in the unavailable state**, as the wireframe shows (**W9**).
- [ ] All three states render per the wireframe: generated as full prose (**W7**), generating with badge
      and placeholder line (**W8**), unavailable as one quiet line making clear the rest of the page works
      (**W9**).
- [ ] The key-stats footer — journals, events, contacts, average mood out of ten — renders **only** in the
      generated state (**W10**).
- [ ] The summary text is read-only; the only mutation on the whole page besides the inline task action is
      this user-requested regeneration.
- [ ] A summary failure degrades to **W9** while the other sections continue to render.

**Required Test Coverage:** unit (RTL) — each of the three states, the stat footer's presence and absence,
the regenerate action's happy and failure paths, its presence in the unavailable state, and that a summary
error does not throw the page. E2E in Phase 17.

#### Phase 5: Agenda — Today's Query and Ordering

**Prerequisites:** Phase 1, ITER18-001 Phase 3 (the date helper —
`backend/app/core/journal/services/journal_date_resolver.py`; use `local_day_window` for the day window
and `JournalDateResolver.today` for the anchor, and migrate `OutdoorDashboardService._window` onto it
while you are here, per Phase 3's recorded follow-up).
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] A repository query returns today's event journals for the user with everything the section needs —
      title, all-day flag, start/end times, location, tags, participants, `event_state` — in **one query**,
      not one per journal.
- [ ] The service orders them **all-day first, then timed ascending by start** (**W12**, **W13**), windowed
      on the user's local day with the `EventDateRange` overlap semantics the outdoor dashboard uses.
- [ ] The section reports empty distinctly from unavailable, so the UI can show one line.

**Required Test Coverage:** unit — ordering with several all-day items, a multi-day journal overlapping
today, and the empty case. Integration — the query against real journals with calendar info; day-boundary
anchoring for a non-UTC user; a query-count assertion for the nested tags/participants. No e2e.

#### Phase 6: Agenda — Cancelled Events and Tomorrow

**Prerequisites:** Phase 5.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Acceptance Criteria:**

- [ ] Cancelled events are returned **flagged** rather than filtered, so the UI can mark them (**W18**);
      the payload must never present a cancelled event as active.
- [ ] Tomorrow's entries are resolved per open decision 5, with the event count available for the collapsed
      label (**W19**).
- [ ] Open decision 5 is constrained by the one-round-trip criterion: **tomorrow ships inside the payload**
      unless that criterion is amended in the same PR and the divergence recorded here. It is one extra
      day of a small list, not a second page of data.

**Required Test Coverage:** unit — cancelled flagging and the tomorrow count. Integration — a cancelled
journal appears flagged, not omitted; tomorrow's window is the user's local tomorrow. No e2e.

#### Phase 7: Agenda — Card

**Prerequisites:** Phases 3 and 6.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] Card header and description per **W11**; entries as bordered rows with the type accent bar (**W17**)
      and hover affordance.
- [ ] Each entry shows its title linking to the journal (**W14**), its time in `tabular-nums` with location
      where present (**W13**), colour-coded tags (**W15**) and participants as an overlapping avatar stack
      with overflow count (**W16**).
- [ ] All-day entries render their uppercase marker instead of a time and appear above timed entries
      (**W12**).
- [ ] Cancelled entries render struck through, muted, with the cancelled badge (**W18**).
- [ ] Nothing scheduled today renders a **single line**, not an empty container (wireframe gap 1, in the
      **W29** idiom).

**Required Test Coverage:** unit (RTL) — ordering as rendered, each entry element, the cancelled treatment,
the empty line, and accessible list labelling. E2E in Phase 17.

#### Phase 8: Tomorrow Disclosure

**Prerequisites:** Phase 7.
**Estimated diff:** ~120 production → **~480 tracked** (×4)

**Acceptance Criteria:**

- [ ] A disclosure row beneath today's list: chevron direction by state, the date label, and the
      right-aligned event count (**W19**), collapsed by default.
- [ ] Expanding reveals tomorrow's entries **in place**, in exactly the form of **W12**–**W18** (**W20**) —
      no navigation, no separate route.
- [ ] Disclosure state is exposed to assistive technology (`aria-expanded` on the trigger, a controlled
      region) and the toggle is keyboard operable.
- [ ] Nothing scheduled tomorrow shows the row with a zero count and an empty line when expanded, rather
      than hiding the control.

**Required Test Coverage:** unit (RTL) — collapsed default, expand/collapse, chevron and `aria-expanded`
state, count label, empty-tomorrow case. E2E in Phase 17, gating clicks on `aria-expanded` rather than
visibility (the recorded Radix slide-in race).

#### Phase 9: Important-Date Occurrence Resolution

**Prerequisites:** none (pure logic).
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] A pure occurrence-resolution helper in `core_shared`: given a stored important date and a window,
      return the occurrence within it, or nothing.
- [ ] `DatePrecision` is respected: `day_month` still produces an occurrence; `full` produces one **and** a
      derived age or count of years; `year` produces none (no month/day to place).
- [ ] Open decision 4 settled: which `date_type` values participate.
- [ ] Edge cases handled explicitly: 29 February in a non-leap year, a window crossing the year boundary, a
      date whose occurrence is today, and a `full` date in the future (age would be negative).
- [ ] Pure and I/O-free, so it is unit-testable and reusable by ITER18-005 Phase 6.

**Required Test Coverage:** unit — each precision, each date type, both boundary edge cases, the leap-day
rule, the future-dated `full` case, and the age/years derivation including a same-day occurrence. No
integration or e2e (no I/O).

#### Phase 10: Contact Importance Signals — Shared Read

**Prerequisites:** none.
**Estimated diff:** ~120 production → **~480 tracked** (×4) — isolated precisely because it rewrites an
existing call site in the search domain (calibration rules 7 and 8)

**Acceptance Criteria:**

- [ ] The favourite / recent-journal-count / recent-activity-count computation that today lives inside
      `search_indexer._fetch_complete_contact_data` is available as a **shared read** usable outside the
      indexer, per open decision 2.
- [ ] The indexer is refactored onto that shared read with **no behaviour change** — the existing search
      ranking must produce identical documents, and the existing indexer tests must pass untouched.
- [ ] The dashboard's use of it does not depend on MeiliSearch being available.
- [ ] The precedence order (favourite → journal count → activity count) is expressed once and pinned by a
      test that fails if it changes, mirroring `tests/unit/infrastructure/search/test_ranking_rules.py`.

**Required Test Coverage:** unit — the shared read's ordering contract and the precedence test. Integration
— the refactored indexer produces byte-identical documents for a fixture contact; the shared read works with
MeiliSearch unavailable. No e2e.

#### Phase 11: Upcoming Dates — Windowed Query, Ranking and MCP Tool

**Prerequisites:** Phases 1, 9 and 10.
**Estimated diff:** ~160 production → **~640 tracked** (×4) — capability triple

**Acceptance Criteria:**

- [ ] A windowed query returns candidate important dates for the next seven days in **one query**, resolved
      through the Phase 9 helper.
- [ ] Ordering is **date ascending, then contact importance descending**, using Phase 10's shared read.
- [ ] **No** new user-configured importance field is introduced anywhere.
- [ ] The section carries the full in-window count so the UI can label its show-more (**W32**), with the cap
      resolved per open decision 3 and the *wireframe's own* depiction (three rows, "Show all 5") taken into
      account.
- [ ] **MCP parity:** an agent can retrieve the same windowed, ranked list — the specification says agents
      compose the dashboard from "the contacts tools for upcoming dates", and no such tool exists today
      (`list_contacts`, `search_contacts`, `get_contact`, `get_contact_relationships`, `list_contact_tags`
      are the whole surface). A `list_upcoming_important_dates` tool ships in this PR, or delivery rule 5 is
      knowingly broken and recorded as an exception here.
- [ ] The section reports empty distinctly from unavailable.

**Required Test Coverage:** unit — ordering including a same-day tie broken by each signal in turn, and cap
plus remainder count. Integration — the query against real contacts and dates; window anchoring for a
non-UTC user; a query-count assertion (no N+1); a contact with no importance signals; the MCP tool against a
real database. No e2e.

#### Phase 12: Upcoming Dates — Card

**Prerequisites:** Phases 3 and 11.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] Card header and description per **W30**; one row per occurrence with avatar, contact name linking to
      the contact, type badge, full occurrence date, and the right-aligned **"in N days"** chip in
      `tabular-nums` (**W31**).
- [ ] The type badge carries the derived age or years where precision allows (`Birthday · turns 35`,
      `Anniversary · 34 years`) and degrades to the bare type otherwise (**W31**).
- [ ] Show-more reveals the rest of the window and names the full count (**W32**).
- [ ] Nothing in the window renders a single line (wireframe gap 2, **W29** idiom).

**Required Test Coverage:** unit (RTL) — row rendering for each precision; the "in N days" values including
today, tomorrow and **a near-midnight non-UTC case**; cap and show-more behaviour; the empty line. E2E in
Phase 17.

#### Phase 13: Tasks Section — Backend Assembly

**Prerequisites:** Phase 1 and ITER18-001 Phase 14.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Acceptance Criteria:**

- [ ] The tasks section reuses ITER18-001 Phase 14's upcoming-window listing rather than a second query
      implementation.
- [ ] **Settled here:** the payload carries the **whole seven-day window** with its total count, and the
      five-item cap is applied by the UI. Capping server-side would make the show-more a second request,
      contradicting the one-round-trip criterion; the window is small by construction. If the window is
      instead capped server-side, the show-more's second call is named and costed in Phase 14. The same
      choice applies to upcoming dates (Phase 11) and is recorded once here.
- [ ] Done, cancelled and **lapsed** tasks are absent — with the cancelled-due-journal fixture that makes
      the lapsed exclusion non-vacuous — while the same tasks remain present on their journals, asserted
      explicitly.
- [ ] Each entry carries text, due-journal id/title, the relative-date material the chip needs (**W25**),
      and linked contacts, with no per-row follow-up request.

**Required Test Coverage:** unit — cap/remainder arithmetic, ordering, exclusion rules. Integration —
payload against real tasks in every status plus a boundary-day task and a cancelled-due-journal task;
window anchoring for a non-UTC user; no N+1. No e2e.

#### Phase 14: Tasks Section — Card with Inline Done

**Prerequisites:** Phases 3 and 13, ITER18-001 Phases 6 and 15.
**Estimated diff:** ~170 production → **~680 tracked** (×4) — **deliberately over the standard**
(calibration rule 10). The specification names "a dashboard tasks section without the inline done action" as
an incoherent split, so the card and its action ship in one PR, as **two commits**: (A) the card,
(B) the inline action and in-place update.

**Acceptance Criteria:**

- [ ] Card header and description per **W21**; up to five rows, soonest first, in the shared row idiom
      (**W22**).
- [ ] Each row shows the task text (**W23**), the relative due chip — `Today`, `Tomorrow`, then a short
      absolute form (**W25**) — the "Due in *journal*" link (**W26**) and any linked contacts with names
      (**W27**).
- [ ] An inline **Done** button on every row (**W24**) marks the task done **without leaving the page**,
      after which the section updates in place and the row disappears.
- [ ] The mutation routes through `invalidateAfterMutation` (cancel before invalidate) — the discipline
      iteration 17 established across all 77 mutation handlers after two flake fixes.
- [ ] No overdue section, counter or badge appears anywhere on the page, and lapsed tasks never render here.
- [ ] The summary card is **not** regenerated underneath the user when a task is ticked — the section
      updates, the summary refreshes on next load (the contract ITER18-005 Phase 7 relies on).

**Required Test Coverage:** unit (RTL) — row rendering; each relative-chip case **including a near-midnight
non-UTC boundary**; the done action's optimistic update and rollback; cancel-before-invalidate ordering; and
that ticking a task triggers no summary refetch. E2E in Phase 17.

#### Phase 15: Tasks Section — Show More and Empty State

**Prerequisites:** Phase 14.
**Estimated diff:** ~90 production → **~360 tracked** (×4)

**Acceptance Criteria:**

- [ ] Show-more reveals the remainder of the seven-day window from the already-fetched payload and names the
      full count (**W28**).
- [ ] The empty window renders the check icon and one line, reading as a good outcome rather than an error
      (**W29**).
- [ ] Revealing the remainder does not refetch and does not change the five-row default on next load.

**Required Test Coverage:** unit (RTL) — show-more label and reveal, no refetch on expand, and the empty
state. E2E in Phase 17.

#### Phase 16: Section Resilience, Loading and Accessibility

**Prerequisites:** Phases 4, 7, 12, 15.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] Each section renders its own loading skeleton and its own unavailable state; one section failing never
      blanks the others (the contract asserted server-side in Phase 1, proven here through the UI).
      Neither state is depicted in the wireframe — see wireframe gap 8 — so both are built in the idiom of
      **W9** and **W29**.
- [ ] Nothing on the page mutates data except the inline task action and the user-requested summary
      regeneration.
- [ ] Keyboard traversal reaches every action in a sensible order; the sections' labelled headings and lists
      survive the final layout (**W4**).
- [ ] No horizontal overflow at mobile widths with long journal titles, long contact names and long tag
      sets — the wide-content cases most likely to break the grid (**W3**).

**Required Test Coverage:** unit (RTL) — per-section loading and error rendering with the other sections
still present; **keyboard traversal order across all interactive elements**; section and list labelling after
layout; long-content layout assertions. E2E in Phase 17 covers the mobile project.

#### Phase 17: E2E — Dashboard Wireframe Conformance

**Prerequisites:** Phases 3–16.
**Estimated diff:** ~160 production → **~640 tracked** (×4)

**Acceptance Criteria:**

- [ ] Deterministic fixture-driven specs asserting the **structural** wireframe facts: the four sections in
      wireframe order with their headings; all-day entries above timed ones; a cancelled event carrying its
      marker; exactly five task rows with a show-more naming the full count; the collapsed-by-default
      tomorrow disclosure expanding in place; upcoming dates ascending with their "in N days" chips.
- [ ] Ticking a task off removes it from the section **without navigation** and without the summary
      changing.
- [ ] Each declared state (**W33**) has its own test with its own fixtures: summary generated, generating and
      unavailable; tasks populated and empty; and the agenda and upcoming-dates empty states.
- [ ] The placeholder cards are gone and the navigation entry reaches the dashboard.
- [ ] **Fixtures account for the e2e user having no configured timezone** (backend day boundaries are UTC),
      so "today" and "tomorrow" fixtures are built from explicit UTC offsets — otherwise a local-noon
      journal lands on the wrong dashboard day.
- [ ] No conditional logic on data state, no skips, no multi-outcome assertions; green on both `firefox` and
      `Mobile Chrome`.

**Required Test Coverage:** this phase *is* the e2e coverage for ITER18-004; unit and integration coverage
landed in Phases 1–16.

### ITER18-005: Extending the Daily Summary

**Objective:** Turn the daily summary from a retrospective note on the journals page into the dashboard's
forward-looking headline: extended inputs, always eligible for today, never stale, and invalidated by its
actual inputs.

**Independently deliverable because:** it changes the summary in place, on both surfaces that already
render it. It needs tasks to exist (ITER18-001) and is most valuable alongside ITER18-004, but the
journals view consumes the same summary, so it stands alone.

**Relevant documents:**

- Specification §*Extending the Daily Summary* (extended inputs, eligibility, freshness, tone and
  safety) and §*The daily summary over MCP*
- `DailySummaryService`, `DailySummaryInputAssembler`, `DailySummaryEligibilityChecker`,
  `DailySummaryPromptBuilder`, `journal_daily_summaries`, `SearchIndexerConsumer._JOURNAL_INVALIDATION_EVENTS`
- [Journals Product Specification](../product-specifications/journals-product-specification.md)
  §*AI Daily Summary and Key Stats* — the constraints that continue to apply

**Acceptance Criteria:**

- [ ] **Current-day inputs are augmented** with: the day's agenda (today's event journals with times,
      locations and participants), tasks due between today and seven days ahead, and important contact
      dates falling in the next seven days.
- [ ] **Past-day inputs are augmented** with the tasks that were due in that day's journals and how they
      resolved — where "resolved" is each task's status **at generation time**, not a point-in-time
      reconstruction. Field history is never replayed to rebuild past status, and this consequence is
      documented in the code: a past-day summary regenerated after a lapsed task was finally completed
      describes it as done.
- [ ] Forward-looking material (upcoming dates, next-week tasks) is **current-day only**; a past-day
      summary describes that day.
- [ ] **Eligibility:** today is **always** eligible regardless of journal count; past days keep the
      existing two-journal threshold and continue to produce no summary below it.
- [ ] **Freshness:** today's summary is regenerated on read if it was not generated **today in the user's
      timezone**. Otherwise caching is unchanged — a summary generated today is served from cache, and
      concurrent generation is still prevented.
- [ ] **Invalidation follows inputs, not only journals:** a day's summary is invalidated by changes to that
      day's journals (as today), by changes to the tasks feeding it (created, retargeted into or out of
      the window, status changed, contact links changed), and — for the current day — by changes to
      important contact dates falling in the window.
- [ ] Invalidation is **lazy**: it marks the cached summary stale and the next read regenerates. Ticking
      four tasks in a row costs one regeneration, not four, and a summary is never regenerated underneath
      a user acting on the dashboard — the sections beneath update in place and the summary refreshes on
      the next load.
- [ ] Explicit user-requested regeneration continues to work.
- [ ] **Tone and safety constraints are carried into the prompt**: short and practical; grounded only in
      the journals, agenda, tasks and dates it was given; descriptive rather than speculative; never
      inventing commitments; read-only; and it **must not restate the sections beneath it item by item** —
      its value is in connecting them. The prompt-level instructions are assertable and are asserted
      (ITER18-005 Phase 3); the model's adherence to them is not mechanically testable and is not claimed
      to be.
- [ ] **MCP** `get_daily_summary` picks up the extended inputs, the always-eligible-today rule and the
      staleness refresh automatically, because they are properties of the summary rather than of the
      requesting surface. No new tool is required; the docstring is updated where behaviour it describes
      changes.
- [ ] Wireframe-bearing only through the dashboard's summary card: the extension must not change the read
      contract that **W7**, **W9** and **W10** consume, and the always-eligible rule is what keeps
      **W7** from falling back to **W9** on a quiet day.

**Required Test Coverage:**

- **Unit:** eligibility (today with zero and one journal is eligible; a past day with one journal is not);
  staleness across the user's timezone (a summary generated at 22:00 yesterday is stale at 07:00 today,
  and one generated at 00:30 today is not); prompt construction includes each new input group for the
  current day and **excludes** forward-looking material for past days; the event → invalidation mapping
  for each new event type; mood/stat counters unchanged.
- **Integration:** a stale today-summary is regenerated on read while a fresh one is served from cache;
  four rapid task mutations produce one regeneration; a task retargeted out of the window invalidates the
  day that lost it and the day that gained it; an important-date change invalidates only the current day;
  MCP `get_daily_summary` reflects all of the above; concurrent generation is still prevented.
- **E2E:** on a day with fewer than two journals but tasks due, the dashboard shows a summary rather than
  the unavailable state; with AI unconfigured the unavailable line renders (**W9**) and the other three
  sections still work; requesting a regeneration updates the card.

**Open decisions:**

1. **Where the staleness check belongs** — settled in **Phase 2**. Inside `DailySummaryService.generate`
   (so every caller, including MCP, gets it) versus at the read boundary. The service is the likely answer,
   given the specification frames it as a property of the summary.
2. **How "stale" is represented** — settled in **Phase 2**. A new status value versus comparing
   `generated_at` against today in the user's timezone versus a nullable `invalidated_at` column. The lazy
   invalidation in Phase 6 pushes toward an explicit marker so an input change can mark a summary stale
   without regenerating it.
3. **Whether task and important-date invalidation stays in `SearchIndexerConsumer`** (where journal
   invalidation lives today, incidentally) or moves to a consumer that owns summary freshness — settled in
   **Phase 6**. Moving it is cleaner but touches existing behaviour.
4. **Prompt budget** — settled across **Phases 3–5**. Adding agenda, tasks and dates grows the prompt;
   decide whether any input group needs a cap, and record it so a busy day cannot silently drop material.

#### Phase 1: Eligibility — Today Is Always Eligible

**Prerequisites:** none.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Acceptance Criteria:**

- [ ] Eligibility distinguishes **today** from a past day in the user's timezone: today is eligible
      regardless of journal count; a past day keeps the existing two-or-more-journals threshold and still
      produces no summary below it.
- [ ] "Today" is resolved through the user's configured timezone, never UTC-today.
- [ ] A day with zero journals still produces a summary attempt rather than a `DISABLED` row — the quiet-day
      case the dashboard headline exists for.
- [ ] Future dates keep whatever behaviour they have today; this phase does not change them.

**Required Test Coverage:** unit — today with zero and one journal is eligible; a past day with one is not,
with two is; the timezone boundary either side of local midnight. Integration — the service persists a
generated (not disabled) summary for a journal-less today. No e2e (Phase 8).

#### Phase 2: Freshness — Regenerate a Summary Not Generated Today

**Prerequisites:** Phase 1.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] Today's summary is regenerated on read when it was **not generated today in the user's timezone** — a
      summary produced yesterday evening must not be served this morning.
- [ ] The check lives where open decision 1 settles it, so REST **and** MCP inherit it without their own
      logic.
- [ ] Staleness representation per open decision 2, chosen so Phase 7 can mark a summary stale without
      regenerating it (a migration here if a column is chosen).
- [ ] Otherwise caching is unchanged: a summary generated today is served from cache, and the existing
      concurrent-generation guard still prevents double generation.
- [ ] Past-day summaries are **not** subject to the staleness rule — only today's must reflect today.

**Required Test Coverage:** unit — a summary generated at 22:00 yesterday is stale at 07:00 today; one
generated at 00:30 today is not; past days unaffected; the user's timezone is the one used. Integration —
stale read regenerates while a fresh read serves cache; concurrent reads still generate once; MCP
`get_daily_summary` inherits both. No e2e (Phase 8).

#### Phase 3: Extended Inputs — Today's Agenda

**Prerequisites:** Phase 1 and ITER18-004 Phase 5.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] `DailySummaryInputAssembler` gathers the current day's agenda — today's event journals with times,
      locations and participants — into `DailySummaryInput`, reusing ITER18-004 Phase 5's read rather than a
      second query implementation.
- [ ] `DailySummaryPromptBuilder` includes the agenda for the **current day only**; a past-day prompt is
      unchanged by this phase.
- [ ] Cancelled events are excluded or marked as cancelled in the prompt — never presented as something the
      user is doing.
- [ ] The prompt keeps the existing tone constraints and gains the explicit instruction not to restate the
      dashboard sections item by item.
- [ ] Prompt-size handling per open decision 4, with any cap stated rather than silently truncating.

**Required Test Coverage:** unit — the prompt contains agenda material for today and none for a past day;
cancelled-event handling; the no-events case adds nothing rather than an empty heading; the
do-not-restate instruction is present. Integration — assembly against real journals. No e2e (Phase 8).

#### Phase 4: Extended Inputs — Tasks Due in the Current Window

**Prerequisites:** Phase 3 and ITER18-001 Phase 14.
**Estimated diff:** ~120 production → **~480 tracked** (×4)

**Acceptance Criteria:**

- [ ] Tasks due between today and seven days ahead are assembled into the current day's input and appear in
      the prompt, reusing ITER18-001 Phase 14's listing.
- [ ] Forward-looking task material appears for the **current day only**.
- [ ] Lapsed tasks are not presented to the model as outstanding commitments.
- [ ] Linked contacts travel with each task, so the model can connect a task to a person — the connective
      work the specification says is the summary's whole value.

**Required Test Coverage:** unit — window contents; exclusion of lapsed, done and cancelled; contacts
present; no forward-looking material on a past-day prompt. Integration — assembly against real tasks in each
status. No e2e (Phase 8).

#### Phase 5: Extended Inputs — Past-Day Task Resolution

**Prerequisites:** Phase 4.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Acceptance Criteria:**

- [ ] For a **past day**, the tasks that were due in that day's journals are assembled with **how they
      resolved** — each task's status **at the moment the summary is generated**, not a reconstruction.
      Field history is never replayed.
- [ ] That consequence is documented in the code and here: a past-day summary regenerated after a lapsed
      task was finally completed describes it as done, which is the honest answer to "what became of this"
      and matches what the user sees on the journal.
- [ ] Past-day prompts carry no forward-looking material of any kind.

**Required Test Coverage:** unit — resolution reflects current status for each of done, cancelled and still
not-done; no forward-looking material. Integration — a past day whose task was completed after the fact
reads as done. No e2e (Phase 8).

#### Phase 6: Extended Inputs — Upcoming Contact Dates

**Prerequisites:** Phase 3 and ITER18-004 Phase 9.
**Estimated diff:** ~130 production → **~520 tracked** (×4)

**Acceptance Criteria:**

- [ ] Important contact dates falling in the next seven days are assembled into the **current day's** input
      and appear in the prompt, reusing ITER18-004 Phase 9's occurrence-resolution helper rather than
      re-deriving recurrence.
- [ ] Past-day prompts contain no upcoming-dates material at all.
- [ ] Where precision allows, the derived age or years travels with the date so the model need not infer it.
- [ ] The existing stat counters and mood average are unchanged by any of Phases 3–6.

**Required Test Coverage:** unit — current-day inclusion, past-day exclusion, precision-dependent extras,
the empty-window case adding nothing, and counters unchanged. Integration — assembly against real contacts
and dates. No e2e (Phase 8).

#### Phase 7: Input-Driven Lazy Invalidation

**Prerequisites:** Phases 2, 4, 6 and ITER18-003 Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] Invalidation follows the summary's **inputs**: journal changes (as today), task changes (created,
      retargeted into or out of the window, status changed, contact links changed) and — for the current
      day — important-date changes in the window.
- [ ] A retarget invalidates **both** the day that lost the task and the day that gained it.
- [ ] Invalidation is **lazy**: it marks the cached summary stale and the next read regenerates. Four task
      ticks in a row cost **one** regeneration, not four — asserted, not assumed.
- [ ] A summary is never regenerated underneath a user acting on the dashboard; the sections update in place
      and the summary refreshes on the next load (paired with ITER18-004 Phase 14's no-refetch criterion).
- [ ] Explicit user-requested regeneration still works and bypasses the laziness.
- [ ] **Important-date invalidation needs an event that does not exist today:** the contacts domain
      publishes `ImportantDateAdded` and `ImportantDateDeleted` but no *updated* event, so editing a stored
      birthday currently publishes nothing. Either add the missing event (and count its cost against
      calibration rule 6) or record "an edited important date does not invalidate today's summary until the
      next journal or task change" as an accepted limitation, in this document.
- [ ] Placement per open decision 3, with the consumer table in
      `docs/architecture/integration-architecture.md` updated if subscriptions change.

**Required Test Coverage:** unit — the event → invalidated-day mapping for every event type, including the
two-day retarget case. Integration — publish → relay → invalidation marks stale without regenerating; a
subsequent read regenerates once; four rapid mutations produce one regeneration; an important-date change
invalidates only the current day (or the recorded limitation is asserted); an explicit regenerate still
forces one. No e2e (Phase 8).

#### Phase 8: E2E — Summary on the Dashboard

**Prerequisites:** Phases 1–7 and ITER18-004 Phase 17.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] Deterministic specs: on a day with fewer than two journals but tasks due, the dashboard shows a
      generated summary rather than the unavailable state (the always-eligible rule — **W7**, not **W9**).
- [ ] With AI unconfigured the unavailable line renders (**W9**), the Regenerate control is still present,
      and the agenda, tasks and dates sections still work.
- [ ] Requesting a regeneration updates the card.
- [ ] Ticking a task off does not change the summary text in place — the "never regenerated underneath the
      user" contract, observable end to end.
- [ ] Fixtures are per-test and deterministic, built with the UTC-boundary caveat from ITER18-001 Phase 22;
      the AI response is stubbed through the existing override rather than calling a real model.

**Required Test Coverage:** this phase *is* the e2e coverage for ITER18-005; unit and integration coverage
landed in Phases 1–7.

## Specification Coverage Map

Every section of the product specification is claimed by at least one iteration; several are shared
across iterations, as the rows below show. Nothing is unclaimed.

| Specification section | Iteration |
|---|---|
| Tasks → Product model, Core invariants, Creating a task | ITER18-001 |
| Tasks → Status and lifecycle, Journal links and retargeting | ITER18-001 |
| Tasks → Lapsed tasks | ITER18-001 (derivation, journal display) · ITER18-002 (cancellation cause) · ITER18-004 (absence from the dashboard) |
| Tasks → Contacts on tasks | ITER18-001 (links) · ITER18-003 (contact activity record) |
| Tasks → Events and history | ITER18-003 |
| Tasks → Tasks and search | ITER18-003 |
| Tasks → Where tasks appear | ITER18-001 (journals) · ITER18-004 (dashboard) |
| Journal Anchor Integrity → Deletion, Merge, Cancellation | ITER18-002 |
| Home Dashboard → Purpose, Composition | ITER18-004 |
| Home Dashboard → Today's summary | ITER18-004 (rendering) · ITER18-005 (content and freshness) |
| Home Dashboard → Agenda, Tasks, Upcoming dates | ITER18-004 |
| Home Dashboard → Contact importance for dashboard ranking | ITER18-004 |
| Home Dashboard → Loading, freshness, and errors; Navigation | ITER18-004 |
| Extending the Daily Summary → Extended inputs, Eligibility, Freshness, Tone and safety | ITER18-005 |
| MCP → Tasks over MCP | ITER18-001 |
| MCP → The dashboard over MCP (deliberate omission) | ITER18-004 |
| MCP → The daily summary over MCP | ITER18-005 |
| Success criteria 1, 6, 7 | ITER18-004 (+ ITER18-005 for 7) |
| Success criteria 2, 3, 4, 5 | ITER18-001 (+ ITER18-002 for 4) |
| Success criterion 8 | ITER18-001, ITER18-003, ITER18-005 (MCP parity per iteration) |

## Out of Scope

Restating the specification's exclusions, because each is a plausible-looking addition a phase might
otherwise drift into: a global tasks list, `/tasks` route or task browser; task assignment or any
multi-user notion; sub-tasks, hierarchy or dependencies; priorities, effort or scheduling; recurring
tasks; reminders, notifications or push; tasks in global search; external task-system integrations;
rich text, attachments or checklists inside a task; dashboard customisation, widget reordering or
user-configurable layout; and editing the AI daily summary.

Task events are designed so future integrations can consume task activity without new plumbing, which is
why tasks are full domain-event citizens from the outset (ITER18-003).

## Follow-ups and Decisions

Appended as the work proceeds, in the style of iterations 16 and 17.

- **Record the actual diff beside each phase's estimate as it lands**, in the
  `**Estimated diff:** … · **Actual:** …` form iteration 17 used. The
  [calibration table](#phase-sizing-calibration) exists only because iteration 17 did this, and the
  estimates here are only as good as the record the next iteration inherits. If a phase overran, say what
  drove it.
- **Open decisions are now attached to the phase that settles them**, and each must be recorded as a
  *Decisions taken* note on that phase when it lands — the iteration-16/17 convention.
- **The ×4 multiplier means "≤500 lines" is only achievable for some phase shapes.** Pure-logic,
  single-surface, small-frontend and assembly phases land at 360–520. Capability triples (service + REST +
  MCP in one PR, as delivery rule 5 requires) land at 600–640 — the measured floor in this repo, not
  padding. One phase is above even that and says so: **ITER18-004 Phase 14** (~680), where the tasks card
  and its inline done action cannot ship apart without creating the dead end the specification warns
  about; it is planned as one PR of two commits.
- **If a phase's actual comes in materially under ~4× its production estimate, say so** — the multiplier
  rests on six recorded data points and deserves to be corrected downward if the evidence supports it.
- **Wireframe divergences** are tracked in
  [the wireframe document](../design/home-dashboard-wireframe.md#known-gaps-and-divergences); gaps 1–4 are
  resolved by ITER18-004's acceptance criteria above.
