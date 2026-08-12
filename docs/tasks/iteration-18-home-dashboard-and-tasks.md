# Iteration 18: Home Dashboard and Tasks

**Status:** 🟡 IN PROGRESS — fully broken down: 5 iterations, **63 phases**, one PR each, with per-phase
acceptance criteria and diff estimates calibrated against iteration 17's recorded actuals.
**ITER18-001 Phases 1–15 complete** (task tables + domain entity; task repository; journal-date
resolution and the future-dated rule; the creation service and its core invariants; create over REST and
MCP; the status lifecycle over service, REST and MCP; retargeting semantics in the service — the model's
one automatic link, and its only way back out of a terminal status — and then retargeting over REST and
MCP, which also makes a task's journal trail visible in every task response; text update and delete over
both surfaces; intermediate journal links over both surfaces; contact links over both surfaces; the
read model with the lapsed derivation — which is where a task first becomes readable *whole* — and now
the two surfaces that ask for it: `GET /api/tasks/{id}` and a journal's tasks grouped by link role, with
`get_task` and `list_journal_tasks` beside them, over batched reads that cost one query per collection
however many tasks a journal holds; and the upcoming-window listing the dashboard consumes —
`GET /api/tasks/upcoming` and `list_upcoming_tasks`, over one pure window rule and one statement, reusing
that same batched assembly; and the frontend's task API client, which wraps those routes in TanStack
Query hooks with the query keys structured so a journal's list and the dashboard's section invalidate
independently. **A task is now readable, not only writable, the query the home dashboard is built on
exists, and the frontend can call it** — Phase 15 reserved its `upcoming()` key against an endpoint
that had not landed yet, and Phase 14 is that endpoint. What remains is the components themselves
(16–20), the journal-list indicator whose backend half is still to come (21), and the e2e (22).)
**ITER18-002 Phases 1, 2, 3 and 4 complete** (the delete guard: journal deletion is refused,
explanatorily, for any journal anchoring a task, and that refusal now reaches REST and MCP callers as
machine-readable blockers alongside the prose; merge, which is never refused — it re-points task links
onto the survivor and de-duplicates them, so `POST /api/journals/{id}/merge` can no longer raise a raw
integrity error; and cancellation, the third journal operation, now pinned end to end — a journal
really cancelled, by a user editing its event status or by either calendar-sync route, lapses the
not-done tasks due in it with the cancellation reason, while touching none of their links and never
being refused). Delivery rule 9 is satisfied for all three shipped journal operations; **the rest of
ITER18-001 is next**, per the Sequencing Strategy. ITER18-002's remaining phases are 5 (the
delete-failure UI and its e2e) and 6 (the retarget/merge lock order).
**ITER18-003 Phases 1–6 complete: the specification's full event set is published, and the
lifecycle half of it is now read.** The events (task
created and deleted; text updated and status changed as one `TaskUpdated`; the due-journal retarget,
carrying any reopen; journal linked/unlinked, which took the automatic link out of the retarget's
payload and gave it its own event — so a retarget now publishes **two** events, the link it retains
and then the anchor move; and contact linked/unlinked, which Phase 5 delivered as **more
`changed_fields` on `TaskUpdated` rather than two new types**, because a contact link is a plain
reference and membership is a field of the task).
Every task event is published inside its write's unit of work and
carries provenance from the caller, and Phase 5 pinned the **completeness rule** with a test anchored
to the repository ports rather than to `TaskService`'s method list. **Phase 6 projects the three
lifecycle types into `field_history` under a `task` entity type** — a create marker carrying the
text, one row per changed field, one per person, and a delete marker that outlives the hard-deleted
row — leaving the retarget and journal-link types to Phase 7, where they are asserted absent rather
than assumed. Nothing is user-visible yet — the read surface is Phase 8 and the first screen that
shows it is Phase 9. Phase 3's review added
**Phase 10**: a journal merge re-points task anchors and publishes no task event, which is now the
completeness test's one **named exclusion** and asserted positively rather than merely absent.
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

**Since ITER18-001 Phase 6:** the status lifecycle exists on all three levels. The transition matrix is a
pure predicate (`is_status_transition_allowed` in `core_shared/models/tasks/task_status.py`), applied by
`TaskService.set_status` over a **locking** read (`TaskRepository.find_by_id_for_update`), and exposed as
`PATCH /api/tasks/{id}` and the MCP tool `set_task_status`. Only the two transitions that would *leave*
cancelled are refused, with `TaskStatusTransitionError` (409) naming retargeting as the way out; setting
the status a task already has is a no-op; and no path touches a journal, which is what keeps a lapsed
task completable.

**Since ITER18-001 Phase 7:** the due journal is retargetable in the domain, and with it the lifecycle
closes. `TaskService.retarget_due_journal` moves a task onto a new due journal as one `@transactional`
unit of work: it revalidates existence, ownership and the future-dated rule whatever the task's status,
retains the previous due journal as an intermediate journal (the model's one automatic link,
de-duplicated by the repository's idempotent add), and always lands the task on *not done* — which makes
it the only way out of *cancelled* and, behind a required acknowledgement, out of *done*. Asking for the
journal a task is already due in is a no-op. The new refusal is `TaskReopenNotAcknowledgedError` (409).
The creating journal remains unreachable: no service method other than `create_task` accepts one.

**Since ITER18-001 Phase 8:** the due journal is retargetable by a user and by an agent.
`POST /api/tasks/{task_id}/retarget` (an action sub-resource, the shape
`POST /api/journals/{id}/merge` uses, rather than a field on the status `PATCH`) and the MCP tool
`retarget_task` both call the `@transactional` service and open no transaction of their own, both carry
the `acknowledge_reopen` confirmation, and both refuse an unacknowledged reopen with
`TASK_REOPEN_NOT_ACKNOWLEDGED` — the error code Phase 7 carried forward, now in
`app/api/error_handlers.py`, which is what lets a surface offer *"reopen it anyway"* instead of showing
a generic failure. **Every task response now carries `intermediate_journal_ids`** — create, status
`PATCH` and retarget alike — read through the new non-transactional
`TaskService.list_intermediate_journal_ids`, so a caller sees the journal a task has just left without a
second request. There is still no way to **read** a task back: no get, no list, no frontend surface, and
no text edit, delete or explicit intermediate-journal link.

**Since ITER18-001 Phase 9:** a task can be reworded and destroyed, on both surfaces.
`PATCH /api/tasks/{id}` now carries the text, the status, or both; `DELETE /api/tasks/{id}` answers 204
and takes the task's link rows with it, leaving the journals and contacts alone. The MCP tools are
`create_task`, `set_task_status`, `update_task_text` and `delete_task`. `TaskService.update_task` owns
text and status together under one `FOR NO KEY UPDATE` read and one write — so a `PATCH` carrying both
can never be half-applied — and `set_status` is now a delegation to it, leaving the transition matrix
with a single implementation. `retarget_due_journal` keeps its own path: it revalidates a due journal,
which the text/status update deliberately never does. There is still **no way to read a task back**, no
retarget surface (Phase 8) and no intermediate-journal link operation (Phase 10).

**Since ITER18-001 Phase 11:** a task's contacts are editable.
`POST`/`DELETE /api/tasks/{task_id}/relationships/contacts[/{contact_id}]` and the MCP tools
`link_task_to_contact` / `unlink_task_from_contact` all call `TaskService.link_contact` and
`unlink_contact`, which are `@transactional`, idempotent in both directions, work in every status, and
enforce contact **existence** only — contacts still have no owner column. `TaskRepository.add_contact`
no longer exists: `add_contacts` batches the write and `create_task` uses it. There is still **no way to
read a task's contacts back** — no get, no list, no frontend surface — and no domain event for a link
change (ITER18-003).

**Since ITER18-001 Phase 10:** a task's *intermediate* journals are editable.
`POST`/`DELETE /api/tasks/{task_id}/relationships/intermediate-journals[/{journal_id}]` and the MCP tools
`attach_intermediate_journal_to_task` / `detach_intermediate_journal_from_task` all call
`TaskService.attach_intermediate_journal` and `detach_intermediate_journal`, which are `@transactional`,
idempotent in both directions and work in every status. **Attaching** requires the journal to be the
acting user's; detaching never reads the journal at all, on the cascade reasoning `unlink_contact`
already carries. Attaching a journal that already holds an **anchor** role is refused with
`TaskJournalIsAnchorError` (409), and so is
detaching one that holds an anchor role and no link row — so the two anchors remain reachable only
through `create_task` and `retarget_due_journal`. A journal holding *both* roles at once, which a
retarget onto a previously-attached journal produces, keeps its intermediate link removable. The
task is read *without* a lock here, unlike the status and retarget paths. No port or adapter changed:
Phase 2's `add_intermediate_journal` and `remove_intermediate_journal` already carried the ownership
guard and the idempotence.

**Since ITER18-001 Phase 12:** a task can be **read back whole**, and *lapsed* exists.
`TaskReadService.read_model(user_id, task_id, now=None)`
(`backend/app/core/tasks/services/task_read_service.py`, request-scoped from `TaskProvider`) assembles
a `TaskReadModel` — the task, its journals by role, its contacts — and derives whether it has lapsed
and why. The rule is pure and lives in `core_shared/models/tasks/lapse.py`
(`LapseReason.DATE_PASSED` / `DUE_JOURNAL_CANCELLED`), the shape in
`core_shared/models/tasks/read_model.py`; the dates come from Phase 3's resolver with the user's
timezone taken **once** per read, and the cancellation from the new batch
`CalendarInfoRepository.find_cancelled_journal_ids`. The service is **read-only** — no transaction, no
lock, no domain event. Two things it is not: there is still **no endpoint and no MCP tool** that
returns it (Phase 13), so it has no caller outside its tests; and it assembles **one** task at a time,
because the batched link reads that make a list of them cheap belong with the list that needs them.

**The trail is readable, though not through these two routes.** An earlier draft of this paragraph said
there was still no way to read a task's journals back; **Phase 8 landed while this phase was in flight
and made that false**, exposing `intermediate_journal_ids` on every task-returning response — `create`,
`PATCH` and retarget over REST, and the task-returning MCP tools. There is still no standalone task
`GET` or list (Phase 13), so the trail is read from a write's answer rather than asked for directly.
The two link routes here deliberately do **not** join that set: they answer 204 and `attached`/`changed`
respectively, because re-reading the trail on a link call would report something the caller did not ask
about and bury the one thing it did. **Since ITER18-003 Phase 4** both routes publish: a
`TaskJournalLinked` or `TaskJournalUnlinked` inside the write's unit of work, carrying `ui`/`mcp`
provenance and — on the link — an `origin` separating what a person asked for from the link a retarget
retains.

**Since ITER18-001 Phase 15:** the frontend can reach every task route. `frontend/src/lib/api/tasks.ts`
exports `taskKeys`, `TaskApiError`, two read hooks (`useTask`, `useJournalTasks`) and eight mutation
hooks covering the four task writes and both relationship pairs; `frontend/src/types/tasks.ts` mirrors
the backend schemas, with `TaskReadAttributes extends TaskAttributes` as the API's read shape extends
its written one. Three things Phases 16–21 inherit rather than re-decide: `details()`, `journalLists()`
and `upcoming()` are **siblings** under `['tasks']` so a journal's list and the dashboard invalidate
independently; every mutation refreshes through `invalidateAfterMutation`, and a test forbids a bare
`invalidateQueries` in the file; every mutation also opts out of the app-wide `mutations.retry: 1`,
because a create is not idempotent and a refusal here is often the answer rather than a failure; and
failures carry the JSON:API `code`, so
`TASK_REOPEN_NOT_ACKNOWLEDGED` is a confirmation to ask for (Phase 18) and
`TASK_DUE_JOURNAL_NOT_FUTURE` is a field error to render (Phase 20) rather than two toasts telling the
user something broke. **Nothing renders yet** — no component imports these hooks until Phase 16 — and
there is no upcoming-window hook, because Phase 14's endpoint does not exist; only its key namespace is
reserved. See *Task Query Keys* in `docs/architecture/frontend-design.md`.

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
   out by ITER17-005 P1 (2 types, ~1440) and P2a (1 type, ~1270). This is why ITER18-003 is ten phases,
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

**Programme size:** 63 phases — and therefore 63 PRs — across the five iterations
(ITER18-001: 22, ITER18-002: 6, ITER18-003: 10, ITER18-004: 17, ITER18-005: 8).
ITER18-002 gained its sixth phase during ITER18-001 Phase 7's review — the retarget/merge lock order, and
ITER18-003 gained its tenth during its own Phase 3 — the merge re-point publishing no task event. Both
were found by review rather than by planning, and both are seams **between** two phases' subjects, which
is where this programme's misses keep turning up. That count is the honest
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

Phase counts: ITER18-001 → 22, ITER18-002 → 6, ITER18-003 → 10, ITER18-004 → 17, ITER18-005 → 8.

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
  this one's. **Follow-up recorded for Phase 11 — done there:** `add_contact` was replaced outright
  rather than joined, so there is one way to write a contact link rather than two.
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

#### Phase 7: Retargeting Semantics — Service ✅ COMPLETE

**Prerequisites:** Phase 6.
**Estimated diff:** ~130 production → **~520 tracked** (×4)
**Actual:** **206 production → 2,077 tracked** (2,077 insertions, 92 deletions, excluding this document:
206 production — the service method, its shared journal-resolution helper and the reused anchor-race
mapping 171, the `core_shared` error 33, the export 2 — 1,871 tests and shared seeding). Production
landed at 1.6× the estimate; the tests at **9.1× the production line count**, the highest ratio in the
iteration so far. The figures include the review round (the anchor-race mapping and six tests).

**Why the test ratio rose again, and what that says about the calibration rule.** Phase 6 refined the
rule to *"for a phase whose subject is a matrix rather than a path, estimate tests from cells ×
surfaces"*. Phase 7 has **one** surface, so that refinement predicts a *smaller* ratio and got a larger
one. The reason is that retargeting is not a matrix at all: it is a **path with five independent gates**
(existence, ownership, future-dating, the acknowledgement, the automatic link), and almost every gate has
to be asserted *once per starting status*, because "whatever the current status" is itself an acceptance
criterion. So the multiplier is gates × statuses, and it applies to a single surface.
**Calibration refinement:** count the *conditions the phase promises to hold regardless of state*, and
multiply by the number of states — a service-only phase with three statuses and five gates costs about
what a three-surface phase with one gate does. Delivery rule 3 was **not** breached: the overrun is
recorded here, and the phase was still a single reviewable PR because it ships one method.

**Acceptance Criteria:**

- [x] `TaskService.retarget_due_journal` revalidates the future-dated and ownership rules at set time,
      whatever the current status. — both are re-run through the same owner-scoped read and the same
      `is_future_dated` predicate creation uses. Each is asserted against all three starting statuses in
      the unit tests; the integration tests parametrise the future-dated refusal over all three and assert
      the ownership refusal once, since ownership is decided by the query rather than by the status. A
      journal that exists, is future-dated and belongs to somebody else is refused byte-identically to one
      that never existed.
- [x] The **previous due journal is automatically retained as an intermediate journal** — the model's one
      automatic link — without duplicating an existing intermediate link for the same journal. — the link
      is written through the repository's already-idempotent `add_intermediate_journal`, so
      de-duplication needs no read-then-add and no new port method; the integration test drives a
      three-hop deferral that lands back on an already-linked journal and still finds one row per journal,
      against the live composite primary key.
- [x] Retargeting always leaves the task **not done**: not done stays not done; cancelled is reopened; done
      is reopened. — parametrised over all three statuses at both levels, read back from the `tasks` row.
- [x] Reopening a **done** task requires an explicit acknowledgement argument; without it the service
      refuses with an error the UI and an agent can act on. — `TaskReopenNotAcknowledgedError`, 409, its
      own type rather than a validation failure, and its message names the acknowledgement as the way
      through. The refusal writes nothing — not the status, not the anchor, not the automatic link.
- [x] The creating journal is immutable — no code path can change it. — enforced by **absence**: the
      method has no parameter that could set one, asserted by signature inspection, and a second test
      asserts `create_task` is still the only `TaskService` method that accepts a creating journal at all.

**Decisions taken (Phase 7):**

- **Retargeting onto the journal a task is already due in is a no-op**, mirroring Phase 6's same-status
  no-op. Nothing is written, `updated_at` does not move, no link appears, and no acknowledgement is
  required even for a *done* task. The argument is that nothing is being **set**, and every rule here is a
  set-time rule — which is also what keeps invariant 4 from becoming a continuous one. The case that makes
  this concrete is a **lapsed** task: were the no-op instead a re-validation, asking for the journal the
  task already has would be refused because that journal has passed, which is a refusal of nothing.
- **The acknowledgement gate is checked last, immediately before the write.** It is a confirmation, not a
  validation: a caller who has just confirmed a reopen should not then be told the journal they picked was
  in the past. Existence, ownership and future-dating are all decided first, so the confirmation is the
  final thing standing between a well-formed request and the write. **Review caught that this ordering was
  documented but unasserted** — every acknowledgement test used a valid journal and every journal test
  supplied the acknowledgement, so moving the gate to the top of the method passed the whole suite. Two
  tests now pin it: a *done* task, unacknowledged, retargeted onto a past-dated journal must answer
  `TaskDueJournalNotFutureError`, and onto an unknown one `TaskAnchorJournalNotFoundError`. Verified by
  moving the gate and watching exactly those two fail.
- **Acknowledgement is required only for `done`, never for `cancelled`.** The specification asks the UI to
  say so before reopening a *completed* task; it says the opposite about a cancelled one — retargeting is
  the documented, and only, way out of cancelled, and it is what `TaskStatusTransitionError` tells a
  caller to do. Gating it would be asking the user to confirm the remedy they were just sent to.
- **The refusal is a distinct 409 type, not a validation error.** Phase 8's criterion is that it be
  *distinguishable*, and the reason is behavioural: a surface that can tell it apart can offer "reopen it
  anyway", while one that cannot has only "invalid" to show. 409 for the same reason as
  `TaskStatusTransitionError` — the body is well formed and the journal is real; what it conflicts with is
  the state the task is in. It is deliberately **not** a `TaskStatusTransitionError` subclass, whose
  message tells a caller to retarget and would be circular here.
- **The previous due journal is linked even when it is also the creating journal.** This looks redundant —
  the task is already anchored to that journal — and the merge path drops exactly this shape as redundant.
  It is kept because `TaskAnchorRepository.repoint_journal_links` already documents it as a shape a task
  reaches *without any merge*: "retargeting keeps the previous due journal as an intermediate link". The
  rule was written down in ITER18-002 Phase 3 before this phase existed, and inventing a different one
  here would have made the merge docstring false.
- **The write goes through `_save`, so the anchor race keeps its 404.** Review caught that the retarget
  wrote straight to the repository while creation deliberately routes through `_save`, which maps a
  foreign-key violation on an anchor column back to `TaskAnchorJournalNotFoundError`. The window is
  **wider** here than on creation, which is what makes it worth closing: ITER18-002's delete guard refuses
  to delete a journal that *already* anchors a task, and the new due journal does not anchor this one
  until the update lands — so a concurrent journal delete between the read and the write is permitted, and
  the caller would have received a raw `IntegrityError` (500) in place of the 404 this method's `Raises:`
  block promises. `_save` is now shared by both writers of an anchor column, and two tests cover it: the
  vanished due journal reported as its anchor, and an unrelated integrity error re-raised untouched.
- **Nothing is ever unlinked, including a link that has become redundant.** Retargeting *back* onto a
  journal a task already passed through leaves that journal as both the due anchor and an intermediate
  link. The link is not removed, for two reasons: it is still true — the journal *was* previously due, and
  the specification defines intermediate journals as exactly "discussed, revisited, or previously due" —
  and the specification says intermediate links are removed **deliberately, by the user**, which is a
  different operation with its own phase. The merge path drops redundant links only for tasks it re-points
  itself, and says so precisely because retargeting can produce this shape legitimately. A test asserts
  `remove_intermediate_journal` is never called on any path.
- **The locking read is inherited, not rediscovered.** Phase 6 recorded that a read-decide-write sequence
  can lose a *rule* rather than a field, and that Phases 7–9 inherit the locking read. It matters here for
  a concrete reason worth naming: `retarget_due_journal` decides *whether an acknowledgement was required*
  from the status it read. Without the lock, a retarget that began while a task was not done would go on
  to reopen a task somebody has since marked done, with no acknowledgement at all — the rule this phase
  exists to enforce, bypassed by interleaving.
- **The overlapping-call test is honest about what it does not prove**, following the correction Phase 6
  had to make about its own. Measured against the unlocked read the overlapping test still passes, because
  the retarget's read lands after the other call commits anyway and is refused for the right reason by
  accident; making it fail every time needs a barrier that deadlocks on the lock under test. The
  every-time guarantee is the **unit** test that the locking read is the one used — 37 of the 52 unit
  tests fail when `find_by_id_for_update` is swapped for `find_by_id` — plus Phase 6's repository-level
  lock test. Both substitutions were run rather than argued.
- **The unit-of-work test observes both writes, not one.** A retarget writes twice — the link row and the
  task row — and the two must land together, or a task can end up on a new journal with no record of the
  old one. The observing repository therefore notes *both* calls and the test asserts both were made
  inside an open nested transaction; removing `@transactional` makes it, alone, fail (verified).
- **Two Phase 6 helpers were moved into shared seeding rather than copied**, following the Phase 5
  duplication lesson: `committed_task` — now parameterised by the journals a test needs, since a retarget
  needs somewhere to retarget *to* — and `service_on` now live in
  `tests/integration/tasks/task_seeding.py`, and the Phase 6 file calls them. `stored_anchors` and
  `intermediate_journal_ids` joined them, both reading the raw columns rather than going back through the
  port the service wrote through.
- **The two anchor resolutions share one read.** `_resolve_anchors` (both anchors, for creation) and
  `_resolve_due_journal` (one anchor, for a retarget) both go through `_journals_by_id`, so the property
  that ownership is enforced *by the query* — and therefore that another user's journal is
  indistinguishable from an absent one — has a single place to hold rather than two.

**Required Test Coverage:** unit — each status's outcome, the automatic intermediate link and its
de-duplication, the acknowledgement requirement, creating-journal immutability, future-date and ownership
revalidation. Integration — retarget round-trip with real journals. No e2e.

- **Unit (52 tests):** `backend/tests/unit/tasks/test_task_service_retarget.py` — every status's outcome
  and the persisted due journal; the creating journal accepted as a legitimate target (invariant 6 holds
  on a retarget as it does on creation); text, owner, `created_at` and the creating journal untouched; the
  automatic link written once with the acting user's id, the new due journal never linked, the link still
  written when the previous due journal is also the creating journal, and an already-existing link left to
  the repository's idempotence (the service never lists the links first); the acknowledgement refused,
  accepted, and not required for the other two statuses, its position **after** both journal rules pinned
  by two tests, plus the error's shape (409, a `TaskDomainError` that is not a
  `TaskStatusTransitionError`, `task_id` on the object, *acknowledge* in the message); existence and
  ownership revalidated for all three statuses with the read proved owner-scoped; the future-dated rule
  refused for both *yesterday* and *today* across all three statuses, judged in the user's timezone (a
  Sydney instant that is a different local day) and against the supplied `now` rather than the clock; the
  journal being **left** never read at all, which is what makes a lapsed task resurrectable and is
  asserted on the ids requested rather than on the outcome (an outcome assertion would pass for an
  implementation that reads it and ignores it); a due journal that vanishes before the write still
  reported as its anchor, and an unrelated integrity error re-raised untouched; unknown and other-user
  tasks giving byte-identical `TaskNotFoundError`s; the locking read used and the plain read never; the
  same-journal no-op across all three statuses, reading **no** journal and **no** timezone at all
  (asserted on `mock_calls`, so a method added to either port later cannot slip through); contacts never
  touched, and no link removed on **any** of the four paths — success, no-op, and both refusals; and
  creating-journal immutability by signature.
- **Integration (21 tests):** `backend/tests/integration/tasks/test_task_service_retarget_integration.py`
  — the round trip for all three statuses read back from the `tasks` row; the automatic link as a real row
  and as the only row; de-duplication against the live primary key, both from a pre-seeded link and from a
  three-hop deferral that returns to an already-linked journal; a lapsed task resurrected with the passed
  journal kept in the trail; a cancelled task reopened with no acknowledgement, a done task refused
  without one (status, both anchors and the link table all unchanged) and reopened with one; the creating
  anchor, text and `created_at` unmoved; a past-dated journal refused for every starting status; another
  user's journal refused byte-identically to an absent one; another user's task and an absent id both
  unreachable and unchanged; the same-journal no-op on a **lapsed** task (originally asserted by
  `updated_at` not moving, which Phase 8 found could not fail under these fixtures and replaced with the
  status and anchors — see that phase's decisions); both
  writes proved to run inside one open unit of work (the phase's decorator-sensitive test) with none left
  open; and an overlapping `set_status(done)` proving a retarget cannot reopen without the
  acknowledgement.
- **E2E:** none — deferred as the phase states. The phase ships no frontend surface; ITER18-001's e2e
  lands in Phase 22.
- **Docs:** this document only. `api-design.md` is deliberately untouched — the phase adds no endpoint,
  and Phase 8 is where the retarget surface and its conventions are written down. `mcp-setup.md` and
  `mcp-tools.md` likewise untouched.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (875 files) and
  `core_shared` (129); `mypy` clean over 870 backend files and 127 in `core_shared`; the full
  `tests/unit/` suite (2,878 tests); and `tests/integration/tasks/`, `tests/integration/api/` and
  `tests/integration/mcp/` together (937 tests) — the last two included because they import the shared
  seeding module this phase changed. No frontend or e2e gates — the phase changes no frontend file and
  ships no user-visible surface.

**Raised in review, deferred to ITER18-002 Phase 6: the retarget/merge lock order.** The automated review
on the pull request found that this method locks the **task** row first and the **journals** afterwards
(through the link insert's and the anchor update's foreign keys), while `repoint_journal_links` and its
caller take the **journals** first and the task rows after — opposite orders on the same two kinds of row,
so retargeting a task while a merge absorbs the journal it is due in deadlocks and PostgreSQL aborts one
side. The finding was confirmed against both lock sequences rather than taken at face value. It is **not**
the residual deadlock `repoint_journal_links` already documents against task *creation*: that one cannot
be closed by any lock order, because an insert takes its foreign-key locks in declaration order, whereas a
retarget chooses when it takes each lock. It is therefore a fix rather than an acceptance — but the fix
changes the merge side's counterpart and needs a locking read on the journal domain's port, neither of
which is this phase's subject, so it became **ITER18-002 Phase 6** with its own acceptance criteria. Both
docstrings now carry the ordering so the next reader does not have to rediscover it. Nothing half-applies
in the meantime: the failure mode is an aborted transaction, not a corrupt one.

**Raised in review and declined: the unlocked journal read.** A later review round argued that because
the due journal is read without a lock, a concurrent `update_journal` can move its date into the past
between the check and the write, committing a task against an already-past due journal and violating
invariant 4. The mechanism is real; the conclusion is not. The specification makes invariant 4 a rule
about the moment a due journal is **set** — *"checked when a due journal is set, not continuously. A task
whose due journal has since moved into the past is lapsed, not invalid"* — and **lapsed** is a first-class
state the product is built around, reached with no concurrency at all whenever a user edits a journal a
task is due in. A journal edited a millisecond after the write and one edited a week later produce the
identical, supported state, so a lock would narrow a window onto an outcome that is legitimate either
side of it. `create_task` has had the same shape since Phase 4, so changing one without the other would
also split the rule in two. Declining it is additionally the safer choice: the lock would be a locking
read on the journal domain's port, taken *after* the task row lock on the retarget path, which deepens
exactly the inversion ITER18-002 Phase 6 exists to remove. Recorded in `_require_future_dated`'s docstring
so it is not re-raised.

**Carried forward to Phase 8 — now closed there.** `TaskReopenNotAcknowledgedError` was not in the
JSON:API error-code table in `backend/app/api/error_handlers.py`, so a REST surface would have rendered
it as the generic `DOMAIN_ERROR`. That was correct while no endpoint raised it — but it is exactly what
Phase 8's "returns a distinguishable error, not a generic validation failure" criterion depends on, and
what makes a *"reopen it anyway"* affordance possible. **Phase 8 gave it `TASK_REOPEN_NOT_ACKNOWLEDGED`
in the same PR as the surface**, with a unit test pinning that it no longer falls through to
`DOMAIN_ERROR`.

#### Phase 8: Retargeting — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 7.
**Estimated diff:** ~140 production → **~560 tracked** (×4) · **Actual:** **375 production →
2,303 tracked** (2,303 insertions, 25 deletions across 16 files, excluding this document).
375 production **insertions**: MCP tools 121, controller 113, REST schemas 85, service 49, error
map 7. 1,893 tests and fixtures (1,858 tracked plus the 137-line new unit file, less its overlap
in neither — the new file is untracked, so `git diff` alone undercounts it); 35 docs
(`api-design.md`).

**Counted as insertions only, and every file included — both of which the phase's own review had
to correct.** The first draft of this entry reported 344 production by summing insertions+deletions
per file against an insertions-only total (exactly the mistake Phase 11 recorded and thought it
had retired), omitted the untracked new unit-test file entirely because `git diff` cannot see it,
and silently excluded `api-design.md`. The lesson generalises: **`git diff --stat` is not a
complete measure of a phase whose diff includes new files** — check `git status` for untracked
paths before quoting a total.

**The advance estimate undershot again — the sixth phase running — but Phase 11's suggested
refinement to rule 15 held.** 2,303 against the doc's 560 is 4.1×; against this phase's own
production it is **6.1×**, which is rule 15's multiplier almost exactly, for the second phase in a
row. Phase 11 proposed that *"the ×6 multiplier is reliable; what has been wrong every time is the
production estimate it multiplies — enumerate the artefacts first, then apply ×6."* That is now
confirmed twice. What the ~140 figure missed was not the multiplier but three artefacts: a
service read method, a response-shape change reaching the **two** existing task-returning routes
and the **two** existing task-returning tools (the contact-link routes answer 204 and were
untouched), and a rejection matrix that has to be paid for twice because there are two entry
points.

**Acceptance Criteria:**

- [x] A retarget endpoint and MCP `retarget_task` in the same PR, both carrying the reopen
      acknowledgement. — **The choice is `POST /api/tasks/{task_id}/retarget`, a dedicated action
      sub-resource**, following `POST /api/journals/{id}/merge`. It is not a field on
      `PATCH /api/tasks/{id}` because a retarget is not a field assignment: it forces the status to
      *not done* and writes a link row, so a body able to carry a `status` beside a
      `due_journal_id` would have two answers and no rule for choosing between them — a collision
      Phase 9's `text` field makes concrete rather than hypothetical, and one that would also mean
      relaxing `TaskUpdateAttributes`' required `status`. JSON:API's canonical to-one relationship
      route was considered and rejected: `PATCH .../relationships/due-journal` must return the
      *relationship*, which contradicts the next criterion. The body's `type` names the operation
      (`task-retarget`) and carries no `id` — it is an instruction, not the task's attributes.
- [x] Both return the resulting task including its new intermediate link, so a caller sees the
      trail without a second read. — `intermediate_journal_ids` on the REST attributes and in the
      tool's JSON, asserted **on the response** rather than on the database at both surfaces.
      Populated on **every** task-returning route and tool, not only the retarget: a `tasks`
      resource whose attribute set varied by route would be a worse contract than the one extra
      indexed read it saves, and a `PATCH` on a previously-retargeted task answering `[]` would be
      wrong rather than merely terse. It is an *attribute* rather than a `relationships` member
      because the resource already carries both anchors as attributes. The *uniformity* half is
      asserted on both surfaces — create returning an empty trail and a status change returning the
      trail the task already had, over REST **and** over MCP; review caught that only the REST pair
      was pinned, which left the tool free to drop the argument and still answer a valid-looking
      task.
- [x] Reopening a done task without acknowledgement returns a distinguishable error, not a generic
      validation failure. — **This closes the item Phase 7 carried forward.**
      `TaskReopenNotAcknowledgedError` now maps to `TASK_REOPEN_NOT_ACKNOWLEDGED`; until this PR it
      rendered as the generic `DOMAIN_ERROR`, which is correct for an error no endpoint can raise
      and useless to the endpoint that now does. Pinned three ways at the unit level — it has its
      own code, it does **not** fall through to `DOMAIN_ERROR`, and it is told apart from
      `TaskStatusTransitionError` (two 409s about a task's state, distinct codes, because a refused
      transition tells the caller to retarget and this one *is* the retarget) — and at both
      surfaces the refusal writes nothing: not the status, not the anchor, not the link.

**Decisions taken (Phase 8):**

- **The acknowledgement is a body attribute defaulting to `false`, not a query parameter or a
  header.** It is part of what the caller is asking for; it must be *refused* when misspelled,
  which `extra="forbid"` cannot do for a query string; and MCP has no concept of either. A
  silently-dropped acknowledgement is the worst outcome available here — the caller would believe
  it had confirmed a reopen and be refused for a reason it thought it had answered — so both outer
  nesting levels reject one, each with its own test.
- **The trail is read through a new `TaskService.list_intermediate_journal_ids`, which is not
  `@transactional`.** It is a read: it has nothing to commit, and a unit of work here would commit
  whatever the caller happened to have open. The absence is asserted rather than described — the
  signature is pinned to exactly `{self, user_id, task_id}` and the method is checked for the
  decorator's `functools.wraps` marker — so adding `@transactional` later fails a test rather than
  changing behaviour quietly. It exists because controllers and MCP tools resolve `TaskService`
  and never reach past it into a repository.
- **A test that could not fail was found by probing, not by reading — and Phase 9 found the same
  thing independently, with a better remedy.** The no-op tests originally asserted `updated_at` had
  not moved. That assertion holds whether or not anything was written: `tasks.updated_at` is set
  with `now()`, which in PostgreSQL is the **transaction** timestamp, and every statement in a test
  — the seed insert, the call under test, the read back — shares the savepoint fixture's single
  transaction, so a rewrite stamps exactly the value the insert did. Confirmed by writing the
  opposite test (assert it *does* move on a real retarget) and watching it fail.
  **Phase 7's `test_does_not_touch_the_row` and Phase 6's
  `test_asking_for_the_current_status_does_not_touch_the_row` carried the identical vacuous
  assertion.** This phase's first answer was to drop the timestamp assertion and prove the no-op
  from a field a real write would have changed; **Phase 9's `backdate_updated_at` is strictly
  better and is what survived the merge** — moving the stored timestamp to a value `now()` cannot
  produce makes the original assertion able to fail, which recovers the evidence instead of
  abandoning it, and it works even for a same-status no-op where no other field would have moved.
  Every no-op test on both of this phase's surfaces now backdates first and keeps a paired
  "a real write *does* move it" control. Two phases reaching the same diagnosis from opposite
  directions in the same week is the strongest signal yet that this trap needs the helper rather
  than vigilance.
- **`create_task`'s response reads the trail rather than hardcoding `[]`.** Creation writes no
  intermediate link, so the answer is always empty today — but a renderer that assumed it here
  while querying on the other two routes would be two definitions of one field, and the first to
  drift would be the assumption.
- **The rejection matrix is asserted twice, once per surface**, as Phase 11 recorded: a shared
  service is no evidence that both callers reach it. That includes both indistinguishability pairs
  (another user's journal ≡ an absent one; another user's task ≡ an absent one), the past-dated
  refusal for all three starting statuses, and the four arguments neither surface offers — `now`,
  the creating journal, a status, and a bare date.
- **The acknowledgement gate's position is asserted at both surfaces.** A *done* task retargeted
  onto a *past* journal answers `TASK_DUE_JOURNAL_NOT_FUTURE`, not the reopen refusal — the
  confirmation is checked last, so a caller is never asked to confirm a request that was never
  going to succeed. Phase 7 pinned this in the service; these pin that neither caller reordered it.
  The MCP half was added in review: every other tool test either supplied the acknowledgement or
  named a valid journal, so moving the gate to the top of the tool would have left them all green.

**Required Test Coverage:** unit — schemas and tool schema. Integration — both surfaces, the
unacknowledged-reopen rejection, and the intermediate link in the response. E2E deferred to Phase 22.

**Test counts are stated as *added by this phase*, with the whole-file total beside them.** Phase 7
quoted file totals, which coincided with its own contribution because its files were new; three of
this phase's four unit files and both integration files already existed, so a file total here would
claim 283 tests for a phase that wrote 105. The distinction was raised in review.

- **Unit (49 added; 132 in the four files):** `tests/unit/api/test_task_schemas.py` — the retarget
  request's required due journal, the acknowledgement's default, its rejection when non-boolean,
  the pinned `task-retarget` type, `extra="forbid"` at all three levels, the six attributes it
  refuses (creating journal, status, text, `now`, a bare date, an unknown key), the id bounded to
  `1..INT32_MAX` at both ends, and the trail attribute including that each default is its own list.
  `tests/unit/api/test_task_error_mapping.py` — the new code, its 409, its distinctness from both
  the generic fallback and a refused transition, and a detail naming the task and the way through.
  `tests/unit/mcp/domains/test_task_tools_schema.py` — the tool registered, its required and
  optional parameters, both ids bounded, the four absences, and a description that says a done task
  is reopened and that this is the way out of cancelled.
  `tests/unit/tasks/test_task_service_intermediate_journals.py` — the read delegated owner-scoped,
  order left to the port, empty for an untravelled task, `TaskNotFoundError` propagated, and the
  two assertions that it opens no unit of work.
- **Integration (56 added; 151 in the two surface files):**
  `tests/integration/api/test_task_endpoints.py` and
  `tests/integration/mcp/test_task_tools_mcp.py` — the round trip per starting status read back
  from the `tasks` row; the trail on the response; a three-hop deferral returning to an
  already-linked journal, de-duplicated against the live composite primary key; a lapsed task
  resurrected with the passed journal kept; the creating journal accepted as a target (invariant 6
  on a retarget); the no-op; the unacknowledged refusal writing nothing, the acknowledged reopen,
  and the cancelled reopen needing none; the gate's position; the past-dated refusal per status;
  both indistinguishability pairs; ids beyond `INT32_MAX` on body and path; eight rejected REST
  bodies and four rejected tool arguments; and the create and `PATCH` responses carrying the trail.
- **Trails of more than one journal are compared sorted, and the tests say why.** The port orders
  by `created_at`, which *ties* when several links are written inside one fixture transaction, so
  the tie-break's order is an artefact of the fixture rather than a property of the surface. The
  de-duplication claim is about membership and count, and that is what is asserted.
- **E2E:** none — the phase changes no frontend file and ships no user-visible surface.
  ITER18-001's e2e lands in Phase 22, as the phase states.
- **Docs:** `api-design.md` gains the route and four conventions (the action sub-resource and why
  the two alternatives were rejected; the acknowledgement's shape and its distinct 409; the uniform
  task attribute set; and `retarget_task` in the tool list). `mcp-setup.md` and `mcp-tools.md` are
  deliberately untouched — the tool's docstring and parameter descriptions are its documentation.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (881 files) and
  `core_shared` (129); `mypy` clean — **870 files for `mypy app tests`, 876 for `mypy .`**, the
  difference being the repo root's own modules, and both stated because a review round flagged one
  as stale when the two commands simply count different things; 127 in `core_shared`; the full
  `tests/unit/` suite (**2,996 tests**); and
  `tests/integration/tasks/`, `tests/integration/api/` and `tests/integration/mcp/` together
  (**1,063 tests, exit 0**). No frontend or e2e gates — the phase changes no frontend file.

**What the review round found, and it was a different list again.** Phases 4–6 were reviewed into
*more* tests; Phase 11 into fewer, and into corrected *claims*. This one was reviewed into both,
plus a race:

- **A post-commit read could have turned a committed write into a 404.** The trail is read after
  the service's unit of work commits, and the repository raises `TaskNotFoundError` if the task has
  gone in that window — so a successful create, status change or retarget would have answered 404
  (REST) or *"Not found"* (MCP) for a write that persisted. It was flagged as unreachable-for-now
  and fixed anyway; **Phase 9 landed `DELETE /api/tasks/{id}` on main before this branch merged, so
  the window is now live rather than theoretical** — a good argument for fixing a race the moment
  it is understood rather than when it first bites. Both surfaces answer an empty trail instead,
  which is not a fallback but the literal truth:
  `task_intermediate_journals` cascades from `task_id`, so a task that is gone has no links left to
  list. This is the same class of defect `_save` exists to prevent on the write side, and the
  window is wider here because it straddles a commit.
- **The trail read takes a `FOR KEY SHARE` lock and holds it to the end of the request**, because
  the adapter reaches the links through `_require_task_owned`. Recorded rather than removed: the
  link tables carry no `user_id`, so that guard is the *only* thing making the read owner-scoped,
  and `FOR KEY SHARE` blocks nothing but a delete of that row. The cost — one extra round trip and
  a tail-of-request lock on every task write — is now stated in the method's docstring rather than
  discovered later.
- **Two gaps in this phase's own claim that the answer is uniform across surfaces.** Nothing
  asserted that the `create_task` and `set_task_status` *tools* carried the trail (only the REST
  equivalents were pinned), and the acknowledgement gate's *position* was pinned on the endpoint
  but not the tool — every MCP test either supplied the acknowledgement or named a valid journal,
  so the tool could have reordered the gate and stayed green. Three tests added. The phase had
  written down the principle ("a shared service is no evidence that both callers reach it") and
  then not applied it to itself.
- **Two more assertions that could not fail, in neighbouring files**, both the same `now()` trap:
  Phase 6's `test_asking_for_the_current_status_does_not_touch_the_row` and the repository's
  `test_save_updates_text_and_status`. The first is the one case where the new comment's remedy
  does not apply — a same-status no-op leaves *no* field a real write would have changed — so the
  assertion is dropped and the docstring now points at the unit test that does prove it
  (`save.assert_not_awaited()`). The second's docstring claimed to prove the column was re-stamped;
  it proved only that the returned entity agrees with the stored row, and now says so.
- **Two wrong numbers in this entry**, corrected above: a production total that summed
  insertions+deletions against an insertions-only figure while omitting the untracked new test
  file, and test counts quoted as whole-file totals for files that mostly predate the phase. The
  pattern Phase 11 identified holds: once the tests are thorough, review starts catching *claims*.
- **One review finding was checked and declined.** It reported the `mypy` file count as stale at
  870 against an actual 876. Both numbers are real: `mypy app tests` — the gate this project
  runs — sees 870, and `mypy .` sees 876. Verified by running both rather than taking the finding
  at face value; the entry now names the command instead of the bare number.

**Recorded because it cost most of the phase's debugging time: the local integration stack is
shared between colliding worktrees.** `scripts/workspace_env.py` hashes the workspace path to derive
`CONTAINER_PREFIX` and the test ports, and two worktrees hashed to the same `pms_test_75` /
port 6183. Every pytest session's `_reset_test_database` drops and re-migrates
`personal_management_test`, so a session starting while another runs destroys the other's schema
mid-run. The symptoms are broad and misleading — `relation "journals" does not exist`, connection
refused, `InternalClientError: cannot switch to state 15`, or a hundred setup errors in files the
change never touched — and they land on tests unrelated to the diff. **A stash-and-rerun proved it
environmental**: the clean tree failed the same way in the same window, and the branch passed
1,060/1,060 once the other worktree went idle. Diagnose with
`ps -eo args | grep venv/bin/pytest` before suspecting the diff, and note that a *waiter* shell
polling for the other worktree matches a naive `pgrep -f bin/pytest`, so two agents can wait on
each other indefinitely.

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

#### Phase 10: Intermediate Journal Links — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple · **Overrun recorded
before work started (delivery rule 3): ~350 production → ~2,100 tracked** · **Actual:** **572 production
→ 3,718 tracked** (3,718 insertions, 10 deletions across 17 files, excluding this document). 618
production: service 246, MCP tools 143, controller 92, REST schemas 72, the `core_shared` error 61, the
export 2, the error-code map 2. 3,029 tests and shared seeding; 71 docs.

**Every figure in this entry was re-derived from `git diff --numstat origin/main` and
`pytest --collect-only` at the final tree, after the local review round found fourteen of them stale.**
They had been computed rather than recalled — and then the Phase 8 merge and this review's own fixes
moved them underneath. See *"a merge is a documentation event"* below: the sweep that rule prescribes
has to cover the **numbers**, not just the prose, which is the half its first version missed.

**The estimate is rebuilt the way Phase 11 concluded it should be — enumerate the artefacts, then apply
rule 15's ×6 — rather than by guessing at the capability's size.** The artefacts are: a domain error and
its export (~40), one entry in the JSON:API error-code map (1), two service methods (~120), two REST
request schemas (~55), two routes (~70), and two MCP tools with their registration (~95). That is ~350
production, and ×6 is ~2,100. The ×4 in the line above predates rule 15 and is left standing so the two
numbers can be compared when this phase lands.

**What this phase does *not* pay for, which is why it should sit below Phase 11's 2,853.**
`TaskRepository.add_intermediate_journal`, `remove_intermediate_journal` and
`list_intermediate_journal_ids` already exist — Phase 2 wrote them and Phase 7's automatic link goes
through the first — and they are already owner-scoped through `_require_task_owned`'s
`SELECT … FOR KEY SHARE` and already idempotent through `task_intermediate_journals`' composite primary
key. So the acceptance criterion *"attaching is idempotent rather than duplicating"* is met by a
constraint that is already live and already tested, and **rule 13's port+adapter ×6 does not apply
here**. Rule 15's does: two entry points, so two rejection matrices.

**Splitting was declined, and both cuts considered are recorded rather than implied.** The
*capability* split — attach now, detach later — ships a surface able to create links the user cannot
remove, the same breach of delivery rule 9 Phase 11 refused and a direct contradiction of the
specification's *"Intermediate links can be removed"*. Rule 10 (coherence beats size) applies.

The *layer* split that **sizing rule 4** prescribes — service plus unit tests as one phase, the two
surfaces as the next — was omitted from this entry's first draft and is added here after review asked
for it, because rule 4 explicitly makes such a phase mergeable on its own and it therefore does **not**
breach rule 9. It was still the wrong cut, for a reason particular to this phase: rule 4 exists for
phases where *"a service method's own logic is the hard part"*, and here it is not. The service is two
gates and a delegation over repository methods Phase 2 already wrote and tested. Counted against what
actually landed, the cut splits this phase's production **exactly** in half and leaves both halves well
over 500: the service side is 309 (246 + 61 + 2) with 1,793 lines of unit and service-integration tests
behind it — about **2,100** — and the surface side is 309 (92 + 72 + 143 + 2) with the remaining ~1,236
test lines, about **1,545**. So the split buys two oversized PRs instead of one, and the larger of the two would be
the half rule 4 calls the "hard part" precisely because it is *not* hard here. Splitting the two
*surfaces* from each other is what rule 5 forbids outright. **Recorded as a general observation:** rule
4's cut only helps when production *and its tests* concentrate in the service, and it is worth counting
that before invoking it — here the tests concentrate there while the difficulty does not.

**The pre-recorded figure undershot again — the sixth phase running — and this time the *reason* is not
the production estimate.** 3,718 against the pre-recorded 2,100 is 1.8×; against this phase's own
production it is **6.0×**, which is rule 15's ×6 almost exactly, for the second phase in a row. Phase 11 concluded that
"the ×6 multiplier is reliable; what has been wrong every time is the production estimate it
multiplies", and proposed enumerating the artefacts first. That was done here — every artefact in the
list above was written — and the estimate still came in at 56% of the actual, because **the artefacts
were each about twice as long as guessed**: the service was estimated at 120 lines and landed at 246,
the tools at 95 and landed at 143. Not one of them was missing; all of them were longer.
**Suggested refinement to rule 15:** when a phase's production is enumerated artefact by artefact,
multiply the *artefact estimate* by ~1.5 before applying ×6 — in this repository a "method" means a
method plus twenty lines of docstring recording why it is the way it is, and that prose is what the
enumeration keeps omitting.

**Acceptance Criteria:**

- [x] Attach and detach an intermediate journal, over REST and MCP in the same PR. —
      `POST`/`DELETE /api/tasks/{task_id}/relationships/intermediate-journals[/{journal_id}]` and the MCP
      tools `attach_intermediate_journal_to_task` / `detach_intermediate_journal_from_task`, all four over
      `TaskService.attach_intermediate_journal` and `detach_intermediate_journal`.
- [x] Intermediate links are **explicit only** — no code path infers one from an edit — and attaching is
      idempotent rather than duplicating. — the explicit half is asserted as an *absence*: neither method
      reads or writes a status, touches the contact repository or resolves a timezone, all on `mock_calls`
      rather than on named methods. The one automatic link stays Phase 7's, and the two meet in a test
      that defers a task and then detaches the journal it was deferred from. Idempotency is the composite
      primary key's: there is **no** "is it already attached?" read anywhere, asserted directly
      (`list_intermediate_journal_ids` is never called), and proved against the live constraint by a
      repeat that leaves one row.
- [x] The creating and due links cannot be detached through this surface; attempting it is a clear error. —
      `TaskJournalIsAnchorError`, 409, `TASK_JOURNAL_IS_ANCHOR`, at all three levels for **both** anchors.
      The refusal is explicit rather than a silent success, and that is the point: the repository would
      answer a bare `False` for an anchor, which reads as *"it was not attached"* rather than *"that link
      cannot be removed at all"*. **The refusal is conditioned on there being no link row to remove**,
      which the review round corrected — see the decision below.
- [x] Attaching a journal that is already the creating or due journal is rejected: it is already linked in
      a stronger role. — the same error from the same shared gate, so the two directions cannot drift.
      Invariant 6's case (one journal in both roles) is pinned to report *creating*, because without a
      deliberate order it would report whichever the implementation tested first.
- [x] The journal must belong to the acting user. — enforced by the owner-scoped read `create_task` and
      `retarget_due_journal` already share, so another user's real journal is refused **identically to an
      absent id once the id itself is normalised** at all three levels. The hedge is Phase 6's and is
      restored here: each answer embeds the id the caller supplied, so the two differ exactly there and
      nowhere else. This entry's first draft said *byte-identical*, which is false for any body carrying
      an id, and the review round caught it here, in the REST test's own docstring, and in the sentence
      it had already put into `api-design.md`. The answer is the **journal domain's**
      `JournalNotFoundError`, not `TaskAnchorJournalNotFoundError`, whose message ("a task must be
      anchored to journals that exist") would describe a rule this call is not about.

**What the review round found, and why it is a different list again.** Phases 4–6 were reviewed into
*more* tests and Phase 11 into *fewer*; this phase was reviewed into **one real bug and eight false
claims**. The bug is the detach gate below — the only finding in six phases that changed behaviour a user
could observe rather than a docstring or a number. The claims were: two mutation counts (10 for 12, and
"exactly the two detach refusals" for nine), a file count (18 for 17), *byte-identical* used three times
including in a permanent architecture document, "at both nesting levels" for four fields where only one
was tested out there, "both ids bounded" where only the attach tool's were read, and an acceptance
criterion whose evidence proved something narrower than it claimed (below). It also found a test that
could not fail and two docstrings claiming coverage that lives in another file. **The pattern worth
carrying:** Phase 11 concluded that once a phase's tests are thorough, review starts catching *claims*.
That held — but the claims it caught here were disproportionately **numbers this document invented while
writing itself up**, which is a self-inflicted class the previous phases also produced. Numbers in this
document should be pasted from a command's output, not recalled.

**A third class appeared after the pull request was open, and it is new: claims that were true when
written and were made false by a merge.** This phase sat open long enough for **three** phases to land on
`main` beneath it — 9, ITER18-003 P1, and 8 — and Phase 8 turned this entry's *"there is still no way to
read a task's journals back"* into a falsehood by putting `intermediate_journal_ids` on every
task-returning response. The automated review caught it; nothing in the local process would have, because
the sentence was correct at the moment it was written and no test covers prose. **What to carry:** a
merge is a documentation event, not just a code one. The paragraphs most at risk are the *"there is still
no…"* ones — every phase writes them, and every later phase is trying to make one of them false.

**Acting on that immediately found a second one**, which is why the rule is worth stating rather than
merely noting. Re-reading every *"still no"* sentence in this entry turned up
`TaskReopenNotAcknowledgedError` being described as *"still unmapped"* when Phase 8's merge had mapped it
an hour earlier — the same rot, in a bullet nobody had flagged. Two of this entry's *"still no"* claims
had gone stale, both from the same merge, and the second was found only because the first prompted a
sweep. **So: after every merge from `main`, grep the phase entry for "still no" and re-check each hit.**
It takes a minute and it caught one claim the automated review missed.

**Acceptance criterion 2's evidence was narrowed, because it proved less than it claimed.** The
"explicit only" half was written up as being shown by these two methods reading no status, touching no
contact and resolving no timezone. That is a statement about the *two new methods* and says nothing
about any other code path, which is what the criterion is about. The evidence that actually bears on it
is Phase 6's, and it is restated here rather than assumed: a status change writes no intermediate link
row. The **service** test is the load-bearing one — it loops every status and counts rows
(`test_task_service_set_status_integration.py`); the REST and MCP counterparts make a single `done`
change and assert the trail they report, which is weaker and is described as such rather than counted as
a third matrix. Added to it is this phase's retarget-trail test, pinning that a retarget produces
*exactly one* automatic link. The
absences remain worth asserting — they are what makes the methods cheap and status-independent — but
they are not the criterion.

**Decisions taken (Phase 10):**

- **The detach refusal is about the missing row, not about the anchor — a behaviour change forced by
  review.** As first written, detach refused whenever the journal was an anchor. That made a legitimately
  reachable link **permanently unremovable**: attach a journal, then retarget the task *onto* it, and the
  row this surface wrote is still there — `retarget_due_journal` never unlinks, which Phase 7 decided
  deliberately — while the journal has since become the due anchor. Every later detach answered 409, and
  the row could only be shed by retargeting away again. That contradicts the specification's
  *"Intermediate links can be removed"* for a link the user created through this very method.
  The Decisions list already discussed this exact shape, but only in its **concurrent** form, and
  concluded no lock was needed because the shape is legitimate. That reasoning was right about the shape
  and blind to the sequential path, where this phase's own new refusal turned a benign redundant row into
  a stuck one.
  **The fix runs the delete first and refuses only when it removed nothing.** The anchor column is never
  touched either way — the repository only ever deletes from the link table — so the caller who genuinely
  meant *"stop this task being due here"* still gets told to retarget, and the refusal path still writes
  nothing, a `DELETE` matching no rows being no write. Two alternatives were rejected: having *retarget*
  drop the new due journal's intermediate row changes Phase 7's contract from another phase, and
  recording the stuck row as accepted breaches the specification. **Mutation-checked in both directions**
  — restoring the original order fails exactly the two new regression tests, and removing the gate
  altogether fails ten across all three levels.
- **The foreign key is matched by name, not by its column.** `"journal_id" in message` also matches a
  primary-key violation's `Key (task_id, journal_id)=(…) already exists`, so a *duplicate* would have
  been reported to the caller as a **missing journal** — a 404 for a row that is right there. Unreachable
  while the insert is `ON CONFLICT DO NOTHING`, which is precisely the kind of "safe today" the
  `str(error)` bug in Phase 4 also was, so the guard now matches
  `task_intermediate_journals_journal_id_fkey` and a unit test pins the duplicate being re-raised.

- **The specification's two deliberate acts are one API call.** It names two ways a link is created —
  *"attaches an existing task to the journal they are viewing"* and *"links a journal to a task from the
  task itself"* — and they differ only in which id the user picked first. Both reduce to
  `(task_id, journal_id)`, so a second route would be the same operation under a different name and a
  second place for the anchor rule to be forgotten. Recorded because a reader checking the specification
  against this phase will look for the missing second entry point; the difference belongs to the UI
  affordances Phase 16 onwards will build.
- **The route is `/relationships/intermediate-journals`, the repository's first kebab-case relationship
  member.** A task has three journal relationships and this one manipulates exactly one, so naming it
  `/journals` would promise a route that can set an anchor. The body's resource `type` stays `journals`:
  the relationship's name belongs in the path and the type names what the identifier points at. Every
  earlier relationship route in this API happened to be a single word, so this is a new convention rather
  than a departure from one.
- **One error class covers both directions.** Attaching an anchor and detaching one are the same rule —
  *an anchor role is not an intermediate link* — so `TaskJournalIsAnchorError(task_id, journal_id, anchor)`
  serves both. What differs between them is which call was made, which the caller already knows; what
  they cannot know is which anchor it was and how that anchor is really changed, so the message carries
  both (the creating journal never changes; the due journal is changed by retargeting). Two classes would
  have stated one rule twice.
- **An unreachable journal answers the journal domain's error, reusing Phase 11's contact decision.**
  `JournalNotFoundError` is already 404, already mapped to `JOURNAL_NOT_FOUND`, and already rendered by
  the shared MCP handler as `Not found · Journal`, so an actionable answer cost no new plumbing. The MCP
  test asserts the anchor refusal and the missing-journal refusal do **not** read alike, because their
  remedies differ: *it is already linked* versus *pick another journal*.
- **No port or adapter change, and that is why this phase is smaller than Phase 11.** Phase 2 wrote
  `add_intermediate_journal`, `remove_intermediate_journal` and `list_intermediate_journal_ids`, all
  owner-scoped through `_require_task_owned`'s `FOR KEY SHARE` and all idempotent through the composite
  primary key. Rule 13's ×6 therefore did not apply here; rule 15's did.
- **The task is read *without* a lock, and the reason is not "nothing else is mutable".** Phase 6 needed
  `FOR NO KEY UPDATE` because `set_status` reads a status, decides a rule from it and writes the decision
  back; Phase 7 inherited that. This does not: the only state that can move underneath it is a concurrent
  retarget making the journal the due anchor after the check, and the resulting shape — a due anchor that
  is *also* an intermediate link — is one `retarget_due_journal` produces on its own and which Phase 7
  explicitly declined to clean up ("nothing is ever unlinked, including a link that has become
  redundant"). A lock would narrow a window onto an outcome that is legitimate either side of it, and it
  would deepen the lock-order inversion against journal merge that ITER18-002 Phase 6 exists to remove.
  The *choice* is pinned by a test rather than left to the docstring: `find_by_id` is asserted used and
  `find_by_id_for_update` asserted unused, and swapping them fails 10 of the 25 unit tests.
- **The task gate runs before the journal gate.** Neither ordering leaks — both reads are scoped to the
  *acting* user, so neither can answer a question about somebody else's data — so the tie is broken by
  which resource the caller named as the subject: a 404 on the task beats a 404 on the journal. Asserted
  on the reads made rather than on the outcome, since an outcome assertion would pass for an
  implementation that reads the journal first and discards the answer.
- **The anchor check runs after the journal read, and the order is unobservable.** An anchor is by
  construction a real journal of the caller's — the anchor columns are `ON DELETE RESTRICT` foreign keys
  that creation and retargeting both resolve owner-scoped — so no input reaches one gate and not the
  other. Recorded because the cheaper order (check the anchor first, skip a query) is the obvious review
  suggestion and is equally correct.
- **The vanished-journal race is mapped, and needs no savepoint.** A journal deleted between the check and
  the insert fails the foreign key, and the caller was promised a 404; the violation is matched against
  the driver's *own* message — `_driver_message`, not `str(error)`, which is the Phase 4 bug — and
  re-raised untouched otherwise. **What is matched in that message is the foreign key's full name**, for
  the reason the next bullet records; an earlier draft of this one said "the `journal_id` column", which
  described the behaviour the review round removed and was caught on the pull request by the automated
  review. Unlike `_link_contacts` this needs no `SAVEPOINT`: one journal is named per call, so nothing
  has to run against the aborted transaction to work out which id went missing. Proved against real
  PostgreSQL by a repository that deletes the journal from inside its own read.
- **The MCP tools return `attached` and `changed`**, Phase 11's `linked`/`changed` in this phase's
  vocabulary. `attached` is the resulting state, `changed` says whether a row moved, and `changed` is
  precisely what the REST 204 withholds in order to keep the idempotency invisible to an HTTP client.
  **Phase 8 changed the surrounding context but not this decision.** Every task-*returning* tool now
  carries `intermediate_journal_ids`, so an agent can see a trail without these two tools reporting one —
  which strengthens the case for the pair rather than weakening it. Answering with the whole task here
  would mean re-reading the trail on every link call to report something the caller did not ask about,
  while burying the one thing it did: whether this call moved a row. There is still no `get_task` tool
  (Phase 13), so the trail is read from a write's answer rather than asked for directly.
- **This phase publishes no domain event, and the silence is now asserted.** ITER18-003 Phase 1 landed
  `TaskCreated` and `TaskDeleted` while this phase was in flight, adding an `event_publisher` to
  `TaskService`'s constructor. The specification lists *"journal linked or unlinked"* among the events
  tasks should eventually emit, but that type belongs to the ITER18-003 phase that adds it — rule 6 caps
  a phase at two new event types, and publishing one here would ship an event with no projection behind
  it. Both link methods therefore take the publisher and never reach it, and a test per method asserts
  `mock_calls == []` on it, so the absence is a decision on record rather than something the next phase
  has to guess at.
- **`TaskReopenNotAcknowledgedError` was left unmapped here, and Phase 8 has since mapped it.** When this
  phase added `TASK_JOURNAL_IS_ANCHOR` to the error-code table it deliberately did not map its neighbour,
  because a code for an error no endpoint could raise is untestable at the surface it exists for — Phase 7
  had carried it forward to whichever phase shipped the retarget route. That phase landed while this one
  was open, and `TASK_REOPEN_NOT_ACKNOWLEDGED` now sits directly above `TASK_JOURNAL_IS_ANCHOR` in the
  same table, arriving through the merge rather than through this phase. The reasoning stands; only the
  tense changed. **This was the second sentence in this entry that a merge falsified**, and unlike the
  first it was caught by re-reading the phase's own *"still no"* claims rather than by review.

**Required Test Coverage:** unit — role rules and idempotency. Integration — attach/detach round-trips and
each rejection on both surfaces, including the cross-user journal. E2E deferred to Phase 22.

Counts below are `pytest --collect-only` figures, following the convention Phase 9 established while this
phase was in flight: parametrised cases count as the tests they collect, not as the functions that
generate them. Every number here was read from that command's output rather than counted by hand, which
is also the habit this phase's review round had to impose on the figures above.

- **Unit (29 tests):** `backend/tests/unit/tasks/test_task_service_intermediate_journal_links.py` —
  named for the *links* rather than for intermediate journals in general, because Phase 8 landed
  `test_task_service_intermediate_journals.py` for the trail **read** while this phase was in flight and
  the two collided on the same path. Main's file was kept byte-identical and this one renamed, which also
  matches its integration counterpart. It covers: the write
  and its arguments; a repeat reporting no change with **no** pre-read; an unknown and a foreign journal
  both `JournalNotFoundError` with the read proved owner-scoped; each anchor refused on attach *and* on
  detach with nothing written, plus **an anchor that also holds a link row being detachable**; the
  same-journal case pinned to *creating*; the message naming retargeting for the due anchor and "never
  changes" for the creating one; the plain read used and the locking read not; no status written and no
  contact or timezone touched on any path (`mock_calls`); detach reaching the journal port **zero**
  times; unknown and foreign tasks identical on both calls; the task gate proved to run before the
  journal read; and the vanished-journal mapping in three shapes — mapped, re-raised for another
  constraint, and re-raised for a **duplicate key**, which the bare-column match would have called a
  missing journal.
  The **task and journal** repositories are mocked with `spec=`, which the rest of this domain's unit
  tests do not yet do: several assertions here are `assert_not_awaited()` or `mock_calls == []`, and on a
  bare `AsyncMock` every one of those passes vacuously the moment the port method is renamed. The phase
  leans on exactly such an assertion for "there is no pre-read". The remaining doubles come from
  `conftest.py` unspec'd, which is that file's choice rather than this one's.
- **Unit (19 new, 101 total):** `backend/tests/unit/api/test_task_schemas.py` — the minimal link body, the
  pinned `journals` type and a mismatch rejected, `data.id` required, a non-integer id and three
  out-of-range ids refused, and `role`, `relationship_type`, `status`, `anchor` and an `attributes` member
  each refused at both nesting levels — *"both"* being three tests larger than the first draft, which
  claimed all four at the envelope level and tested one.
- **Unit (22 new, 82 total):** `backend/tests/unit/mcp/domains/test_task_tools_schema.py` — both tools
  registered and requiring exactly `task_id` and `journal_id`; injected collaborators absent; both ids on
  **both tools** bounded to `1..2147483647` in the generated schema (the first draft read only the attach
  tool's); no role field, no `anchor` and no `now` on either; no contact parameter; and the descriptions
  asserted by phrase rather than by keyword — a `"already" in description` proxy survived deleting the
  sentence it was meant to pin, because the parameter description contained the word too. **No
  "has a description" test**, deliberately: the fixture already fails if the tool is unregistered, and a
  length check on a docstring cannot fail. A comment records why, so it is not written again.
- **Unit (2 new, 12 total):** `backend/tests/unit/api/test_task_error_mapping.py` — the 409 and its code,
  and that it does not share a code with `JOURNAL_NOT_FOUND`, whose remedy is different.
- **Integration (30 tests):** `backend/tests/integration/tasks/test_task_intermediate_journal_links_integration.py`
  — both round trips and their repeats against the live composite primary key; several journals
  accumulating; every status with the stored status unmoved; both anchors refused in both directions
  against anchors that are real foreign keys; invariant 6's shared journal; the retarget trail (the
  journal a task was deferred *from* is detachable, the one it was deferred *to* is not, and **a journal
  attached and then retargeted onto keeps its own link removable** — the review regression); the
  specification's permitted delete, where deleting an intermediate journal takes its link and leaves the
  task and both anchors intact, and the detach that follows it; a real second user's journal and a real
  second user's task, with **their** link left in place; the two task rejections compared *with each
  other* rather than each against a freshly-built error; the vanished journal answering 404 against real
  PostgreSQL; and a unit-of-work observation per method. Both are watched at their own write, which the
  contact-link tests could not do for the insert — that one wraps itself in a savepoint, so a nested
  transaction would be open either way.
  **The attach *order* is deliberately not asserted, and a comment records why**, because review found
  the test that claimed it could not fail: `created_at` defaults to `now()`, which is
  `transaction_timestamp()` and therefore identical for every row written in one transaction — and every
  test here runs in the fixture's single transaction. `ORDER BY created_at, journal_id` degenerated to
  `ORDER BY journal_id`, and the journals were created in ascending order, so the assertion held whatever
  the service did. The same fact bounds what the trail can promise in production: two links written in
  one request tie as well, so *"oldest link first"* is a partial order. **Phase 13 owns whatever ordering
  its read model needs to guarantee**, and should not assume this column provides it.
- **Integration (23 new, 136 total):** `backend/tests/integration/api/test_task_endpoints.py` — 204 on each
  call and on each repeat with the row counted; every status; the deleted-journal detach; each rejection
  with its JSON:API `code`; the cross-user journal proved to differ from an absent one only in the id;
  the cross-user task on both verbs; and rejected bodies carrying `role`, `relationship_type` or
  `status`, another resource type, an unknown member beside `data`, a non-integer id, and `2147483648`
  in both the body and the path.
- **Integration (20 new, 103 total):** `backend/tests/integration/mcp/test_task_tools_mcp.py` — the same
  matrix over `tools/call`, including `attached`/`changed` on all four outcomes, every status, no contact
  row written, the anchor refusal naming the role, the anchor refusal proved *not* to read like a missing
  journal, the actionable journal rejection, the indistinguishable cross-user answers on both tools, and
  three role arguments refused by the transport before the service is reached.
- **Mutation checks, run rather than argued — and re-run after review corrected two of the counts.**
  Measured over this phase's unit file plus its three integration files. Removing `@transactional` from
  either method fails **exactly** its own unit-of-work test and nothing else. Removing detach's anchor
  gate fails **10** tests across all three levels (the first draft said "exactly the two detach
  refusals", which was wrong under any scoping and understated the coverage it was advertising).
  Restoring the pre-review gate order — refuse before the delete — fails **exactly** the two new
  regression tests. Swapping the plain read for the locking one fails **12 of the 29** unit tests.
  Removing the vanished-journal mapping fails 2. Loosening the foreign-key match back to the bare column
  fails the duplicate-key test.
  **Added by the local review round, and the most valuable of them: neutering both service methods to
  `return True` must fail every test that claims a link moved.** It now fails 29 of the 30
  service-integration tests — the survivor is the unreachable-task case, which never reaches the write —
  and all six per-status tests across REST and MCP. Before that round it left **14** of them passing.
- **E2E:** none — deferral taken as the phase states. The phase changes no frontend file and ships no
  user-visible surface; ITER18-001's e2e lands in Phase 22.
- **Docs:** `docs/architecture/api-design.md`'s *Task Endpoints* gained the two routes and four
  conventions (the role-named relationship member, the 409 on both verbs, the journal domain's 404, and
  detach not requiring the journal). `domain-architecture.md` gained the journal-role rules, the
  explicit-only rule and its one exception, and why the link methods take no lock. `mcp-setup.md` and
  `mcp-tools.md` deliberately untouched — the tools document themselves.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (882 files) and
  `core_shared` (129); `mypy .` clean over **877** backend files and 127 in `core_shared`; the full
  `tests/unit/` suite (**3,017** tests); and `tests/integration/tasks/`, `tests/integration/api/` and
  `tests/integration/mcp/` together (**1,080** tests). Re-run three times as `main` moved underneath this
  branch: after **Phase 9** (task text and delete) — **3,073** and **1,133**; after **ITER18-003 Phase 1**
  (task created/deleted events), which added a constructor argument every `TaskService` construction in
  this phase's tests had to take — **3,120** and **1,154**; and after **Phase 8** (retarget over REST and
  MCP), whose merge was the only one of the three to need a hand-built resolution — **3,186** and
  **1,219**, all green, over 892 `ruff` and 887 `mypy` files. Also run:
  `tests/integration/core/integrations/test_journal_series_sync_processor.py`, the only *test* consumer
  of the shared `task_seeding` module outside those three directories (`tests/integration/conftest.py`
  imports from it too, and is loaded by every run). Re-run after the review round's fixes.
  No frontend or e2e gates — the phase changes no frontend file and ships no user-visible surface.
- **Two things review could not check, recorded rather than asserted.** *Test-first* (delivery rule 1)
  is unverifiable from a single working tree: the ordering claimed here — service unit tests red on a
  collection error, then the surfaces' unit tests red, then implementation — is not reconstructable
  after the fact from one commit, and future phases that want it verified should commit the red step.
  And **no unauthenticated (401) test exists for these two routes** — but none exists for any route in
  `test_task_endpoints.py`, so it is a file-wide gap this phase inherited rather than one it introduced.
  Worth closing when a phase touches that file's structure rather than its content.

#### Phase 11: Contact Links — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 5.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple · **Overrun recorded
before work started (delivery rule 3): ~330 production → ~1,900 tracked** · **Actual:** **465 production
→ 2,853 tracked** (2,853 insertions, 107 deletions across 22 files). All figures below are
**insertions**, counted the same way rather than mixing conventions — an earlier draft of this entry
summed insertions+deletions per file against an insertions-only total, which the phase's own review
caught. 465 production: service 139, MCP tools 101, controller 82, REST schemas 66, adapter 56,
port 21. 2,127 tests and fixtures; 261 docs.

The ×4 figure is the one calibration **rule 15** was written to correct, and it was written *because*
Phase 5 came in at 5.6× its own production on exactly this shape. This phase has two entry points, so it
pays for two rejection matrices — a shared service is no evidence that both callers reach it — and it
also changes a **port and its adapter**, which rule 13 puts at ×6 on its own. Phases 5 and 6 landed at
2,036 and 2,483 tracked; nothing about this one is smaller than either.

**Splitting was declined, and the cut considered is recorded rather than implied.** The only clean split
is *link now, unlink later*, which ships a surface able to create links the user cannot remove — a breach
of delivery rule 9 and of the specification's *"task text and contact links can be edited at any time, in
any status"*. The second candidate, deferring the batched write, would reopen and rewrite
`create_task`'s link loop in a later PR when the follow-up is assigned **here**. Rule 10 (coherence beats
size) applies. What Phase 6 got wrong was recording its overrun afterwards; this one is recorded before
any code is written.

**The pre-recorded figure undershot again — the fifth phase running — but by the *smallest* margin yet,
and the reason is worth keeping.** 2,853 against the doc's 600 is 4.8×; against this phase's own
production it is **6.1×**, which is rule 15's ×6 almost exactly. That is the first time an advance
estimate in this iteration has landed on its own multiplier, and the difference from Phases 4–6 is that
the production figure was estimated from *what would be written* (a port method, a service pair, two
schemas, two routes, two tools) rather than from a guess at the capability's size. **Suggested refinement
to rule 15:** the ×6 multiplier is reliable; what has been wrong every time is the production estimate it
multiplies. Enumerate the artefacts first, then apply ×6.

**What the review round found, because it is a different list from the previous phases'.** Phases 4–6
were reviewed into *more* tests; this one was reviewed into **fewer**. The findings that mattered were a
parametrised unit test that could not fail (deleted, with a comment recording why it is not there), a
`x in d or y in d` assertion that accepted two outcomes (pinned to one), a justification for the
savepoint that was simply **untrue** — PostgreSQL's `DETAIL` *does* name the vanished key, so the real
reason to re-read is that parsing localised driver prose is fragile — and three recorded numbers that
were wrong, including a per-file production breakdown that summed insertions+deletions against an
insertions-only total. The pattern worth carrying: once a phase's tests are thorough, what review starts
catching is **claims**, in docstrings and in this document, rather than gaps in coverage. Two smaller
items were acted on (an acceptance criterion whose write-up asserted more than its test did — the
anchors are now checked; a redundant assertion) and one was recorded rather than closed (the theoretical
deadlock below).

**What the pull request's automated review found — a real 500, and it was not this phase's.** Every id
column in this schema is a PostgreSQL `INTEGER` and Python's `int` is unbounded, so `2147483648` parsed
cleanly out of a path or a body, reached the repository, and died in asyncpg's *parameter binding*:
`DataError: value out of int32 range`, rendered to the caller as an internal error for an id no row
could ever have. Probed before fixing, it reproduced on **five** routes — including `PATCH /api/tasks/{id}`
(Phase 6) and `create_task`'s `contact_ids` (Phase 5), neither of which this phase added.

The fix is `backend/app/api/common/identifiers.py` (`DatabaseId`, `DatabaseIdPath`, `INT32_MAX`), applied
to **every id the tasks API and the tasks MCP tools accept**, with eight tests pinning the 400. Fixing
only the two new routes was rejected: leaving `PATCH` broken beside a fixed neighbour in the same module
is a worse outcome than fixing both. Extending it further was also rejected — every other domain's
endpoints have the same 500 waiting in them, and that sweep deserves its own review rather than riding
along inside a phase that ships contact links. **Raised as issue #1272**, with the two open questions it
should settle (whether the lower bound is 1 everywhere, and whether a defensive `DataError` handler
belongs in `error_handlers.py` for whatever the sweep misses).

The review's second finding was a docstring claiming a **422** for a non-integer path id. The
application-wide `validation_error_handler` renders every `RequestValidationError` as **400**, so the
docstring described behaviour no client of this application can observe — the same class of wrong claim
the pre-merge review round caught, and worth noting that it recurred immediately after.

**Acceptance Criteria:**

- [x] Link and unlink a contact over REST and MCP in the same PR; linking is idempotent. —
      `POST`/`DELETE /api/tasks/{task_id}/relationships/contacts[/{contact_id}]` and the MCP tools
      `link_task_to_contact` / `unlink_task_from_contact`, both over `TaskService.link_contact` and
      `unlink_contact`. Idempotency is the composite primary key's, not the service's: there is no
      "is it already linked?" read anywhere, so two interleaved links need no lock. **Unlinking is
      idempotent too**, which the criterion does not ask for and `DELETE` requires.
- [x] Links carry **no** relationship type, role or attendance status, and nothing parses contacts out of
      the task text. — the REST body is a bare resource identifier with `extra="forbid"` at both levels,
      the tool schemas offer no such parameter and the transport refuses one, and a task whose text names
      a real contact by the exact string the `contacts` row holds still has no links. That last is a
      criterion about a code path that must *not* exist, so it is asserted where its absence shows.
- [x] Contact links are editable in any status — asserted for all three statuses at all three levels,
      with the stored status unmoved. **The ownership half is inherited, not met.** `contacts` still has
      no owner column, so the enforceable rule remains existence, exactly as Phase 4 recorded; this phase
      changes nothing about that and does not restate the criterion as satisfied. The divergence now also
      lives in `domain-architecture.md`, where the contact-link rules are written down.
- [x] Deleting a contact removes its task links without touching the tasks. — asserted through a link
      **this surface created**, not a hand-inserted row: a service writing somewhere else would pass
      Phase 1's table test and fail this one. The task, its anchors and its other links all survive, and
      the task can still be "unlinked" from the deleted contact without error.
- [x] **Follow-up from Phase 4: batch the link write.** — `add_contact` was *replaced* by
      `add_contacts(task_id, contact_ids, user_id)`, one `FOR KEY SHARE` guard and one multi-row
      `INSERT … ON CONFLICT DO NOTHING RETURNING contact_id`. `create_task` and the single-contact link
      surface both go through it, so there is one way to write a link rather than two. An observing
      repository asserts three contacts cost one call.

**Decisions taken (Phase 11):**

- **The link routes answer 204, not the task.** Phase 5 declined to echo contact links on create,
  because re-deriving the linked set in a controller would be a second definition of what got linked
  sitting beside a read model that does not exist — and it still does not (Phase 13). 204 additionally
  makes the idempotency *invisible*: a repeat of either call is indistinguishable from the first, which
  is the whole of what idempotent means to a client. `POST /api/contacts/{id}/tags` → 204 is the
  existing precedent for a plain-reference link in this repository.
- **The path is `/relationships/contacts`, a member route under `/api/tasks/`.** It follows the
  journal-contact precedent, and it hangs off the task rather than a journal for the reason Phase 6 gave
  for `PATCH /api/tasks/{id}`: a contact link involves no journal at all. There is still no
  `/api/tasks` **collection**.
- **The body is a single resource identifier, not JSON:API's to-many array.** One contact per call keeps
  "was anything created" unambiguous, and matches `TagAssignmentRequest`. Recorded as a knowing
  narrowing of the relationship semantics rather than an oversight. The id is validated as an integer in
  the schema, so a malformed one is a 400 like every other bad field instead of a `ValueError` escaping
  a cast as a 500.
- **Unlinking deliberately does not require the contact to exist, and linking does.** The asymmetry is
  the cascade: `task_contacts.contact_id` is `ON DELETE CASCADE`, so a deleted contact's links are
  already gone, and 404-ing there would fail exactly the call a user reaches for while tidying up. It
  also means the fourth criterion's scenario stays reachable rather than becoming an error path.
- **`add_contact` was replaced rather than joined by `add_contacts`.** Keeping both would leave the
  singular method with one caller and two ways to write one row. `remove_contact` stays singular because
  nothing removes in bulk; the asymmetry is the callers', not the port's taste.
- **The batched insert runs inside a `SAVEPOINT`, and that is load-bearing rather than tidy.** Phase 4
  mapped a contact deleted between the existence check and the write back to `ContactNotFoundError`.
  With one insert per contact the id was whichever one was being written; a batched insert has to work
  it out, and **it does so by re-reading rather than by parsing the error.** PostgreSQL *does* name the
  key in the violation's `DETAIL` — an earlier draft of this entry claimed otherwise and the phase's own
  review caught it — but that is localised prose whose availability depends on the driver, and this is
  the module that already has a bug on record from matching against the wrong rendering of an error
  (Phase 4's `str(error)` case). A second `SELECT` answers the same question from data. **That re-read
  is what the savepoint is for:** PostgreSQL puts the transaction into a failed state on a constraint
  violation, so the lookup would raise before it could answer. **Mutation-checked:** replacing
  `savepoint(transaction)` with a plain block makes the integration test fail with
  `InFailedSQLTransactionError`, which is precisely the 500 the mapping exists to prevent. If the re-read
  finds every contact present the violation is re-raised untouched, because naming an arbitrary id would
  send the caller looking for a contact that exists.
- **The batched insert passes its ids as one array, after review found the obvious form has a ceiling.**
  It began as a multi-row `VALUES` list with a bind parameter per contact — correct until there are
  32,767 of them, which is asyncpg's hard limit on query arguments, past which a wholly valid create
  raises `InterfaceError` and the caller sees a 500. Capping the surface was the tempting fix and the
  wrong one: the specification says a task may reference *any number* of contacts, so the mechanism has
  to mean it rather than the schema quietly deciding otherwise. `unnest` over a single `integer[]` costs
  two parameters whatever *N* is. **Mutation-checked** with a 33,000-contact test that fails on the old
  form with exactly that `InterfaceError`, because a bug with a threshold needs a regression test on the
  far side of it.
- **A deadlock is theoretically reachable through the batch and is recorded rather than closed.**
  `ON CONFLICT DO NOTHING` takes speculative-insert locks in row order, which `unnest` takes from the
  array, so two transactions linking overlapping contact sets to the **same** task in opposite orders
  could deadlock.
  It is unreachable today — the only batched caller is `create_task`, whose task id was assigned a
  statement earlier and cannot be the subject of a concurrent call — and the obvious fix (sorting the
  ids) would break the first-mention-order property `create_task` asserts. Raised by this phase's
  review; a comment marks the spot, and the phase that adds a second batched caller owns the decision.
- **No row lock beyond the guard's existing `FOR KEY SHARE`, and the reason is not "nothing else is
  mutable".** Phase 6 needed `FOR NO KEY UPDATE` because `set_status` reads a status, decides a rule from
  it, and writes the decision back, so an interleaving can lose a *rule*. Linking decides nothing from
  prior state: `ON CONFLICT DO NOTHING` is atomic and two interleaved links have the same outcome in
  either order. The lesson Phase 6 recorded is about read-decide-write sequences, and this is not one.
- **The MCP tools return `linked` and `changed`.** `linked` is the resulting state, `changed` says
  whether a row moved. Both are needed while there is no read tool: without `changed` an agent cannot
  tell a fresh link from a no-op, and without `linked` it would have to infer the state from which tool
  it called. This is the one thing the REST 204 withholds, and an HTTP client can re-derive it by asking
  for the read model when Phase 13 ships.
- **An unknown contact answers the contacts domain's "Contact not found", not the task domain's bare
  "Not found".** The shared MCP handler branches by error class, and `ContactNotFoundError` is reused
  from the contacts domain (Phase 4's decision), so the answer names the contact and its id. That is
  strictly more actionable than the task-shaped answer, and the test asserts it rather than the weaker
  "not an internal error".
- **The ordering is contacts-then-task, and the leak that would matter is absent.** `link_contact`
  proves the contact exists before the repository proves the task is the caller's, so a foreign task
  plus an unknown contact reports the contact. Nothing leaks: `contacts` has no owner in this system, so
  contact existence is not a cross-user fact, and checking the task first would cost an extra round trip
  to change which of two 404s a caller sees.

**Required Test Coverage:** unit — schemas, tool schemas, idempotency. Integration — round-trips, contact
deletion behaviour, cross-user rejection, both surfaces. E2E deferred to Phase 22.

- **Unit (15 tests):** `backend/tests/unit/tasks/test_task_service_contact_links.py` — the batched call
  shape; linking twice reporting no change; an unknown contact rejected with nothing written; unlink
  idempotent and making **no** contact-existence call at all; the journal and settings repositories
  untouched on every path (asserted on `mock_calls`, not on named methods); an unknown and a foreign
  task both `TaskNotFoundError` with identical messages; and the vanished-contact mapping in three
  shapes — mapped, re-raised for another constraint, and re-raised when the recovery read finds nothing
  missing.
  **A parametrised "works in any status" unit test was written and then deleted**, because this phase's
  review was right that it was tautological: neither method reads a status, so the three runs were
  byte-identical and the test would have survived any regression of the rule it named. The rule rests on
  the *absence* of a status read, which `test_no_status_is_read_or_written` asserts directly, and on the
  three real matrices below, each of which seeds every status against a database and checks the stored
  status is unmoved. A comment in the file records why the obvious test is not there, so it is not
  written again.
- **Unit (12 new, 48 total):** `backend/tests/unit/api/test_task_schemas.py` — the minimal link body, the
  pinned `contacts` type and a mismatch rejected, `data.id` required, and `relationship_type`, `role`,
  `status`, `attendance` and an `attributes` member each refused, at both nesting levels.
- **Unit (17 new, 30 total):** `backend/tests/unit/mcp/domains/test_task_tools_schema.py` — both tools
  registered and requiring exactly `task_id` and `contact_id`; injected collaborators absent; no
  relationship field and no journal parameter on either, asserted against the **generated** schema; and
  the link description stating both that a repeat is harmless and that no role is recorded, because a
  model that has seen `link_journal_to_contact` will otherwise reach for one.
- **Unit (3 changed):** `test_task_service_create.py` — the N-contacts-one-call assertion replacing the
  per-contact one, de-duplication surviving the batching, and the vanished-contact mapping through it.
- **Integration (22 tests):** `backend/tests/integration/tasks/test_task_contact_links_integration.py` —
  both round trips and their repeats; several contacts accumulating; every status with the stored status
  unmoved; the contact-deletion cascade through a link this surface made, and the unlink that follows it;
  an unknown contact and a real second user's task on both calls, byte-identically to an absent id, with
  that user's link left in place; **contacts never inferred from the text**; `create_task`'s three
  contacts costing one `add_contacts` call; the vanished contact answering 404 against real PostgreSQL;
  and the two unit-of-work observations. The link one watches the **contact read** rather than the
  insert, because the insert's own savepoint would show a nested transaction either way — the kind of
  false evidence Phase 6's review found in the "read it back afterwards" idiom.
- **Integration (17 new, 51 total):** `backend/tests/integration/api/test_task_endpoints.py` — 204 on
  each call and on each repeat, with the row counted; every status; the contact-deletion case end to end;
  404 `CONTACT_NOT_FOUND` writing nothing; the cross-user pair proved byte-identical on both verbs; and
  five rejected bodies including `relationship_type`, `role`, `status`, another resource type and an
  unknown member beside `data`.
- **Integration (14 new, 36 total):** `backend/tests/integration/mcp/test_task_tools_mcp.py` — the same
  matrix over `tools/call`, including `linked`/`changed` on all four outcomes, every status, no
  intermediate journal row written, the actionable contact rejection, the indistinguishable cross-user
  answer on both tools, and three relationship arguments refused by the transport before the service is
  reached.
- **E2E:** none — deferral taken as the phase states. The phase changes no frontend file and ships no
  user-visible surface; ITER18-001's e2e lands in Phase 22.
- **Docs:** `docs/architecture/api-design.md`'s *Task Endpoints* gained the two routes and four
  conventions (the relationship route and its 204, the single identifier object, unlink not requiring the
  contact, and the two new tools' `linked`/`changed`). `domain-architecture.md` gained the contact-link
  business rules and the batched-write half of the repository contract. `database-design.md` explains the
  batched `ON CONFLICT` and why the savepoint is there. `mcp-setup.md` and `mcp-tools.md` deliberately
  untouched — the tools document themselves.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` (875 files) and
  `core_shared` (129); `mypy .` clean over **870** backend files and 127 in `core_shared` (the
  whole-project run, not the narrower `mypy app tests`, which reports 864 — the review found this entry
  quoting the narrower number as though it were the wider one); the full `tests/unit/` suite
  (2,870 tests); and `tests/integration/tasks/`, `tests/integration/api/` and `tests/integration/mcp/`
  together (969 tests). Re-run after merging Phase 7 from `main` and adding the id bounds: **2,922** and
  **999**, both green. No frontend or e2e gates — the phase changes no frontend file and ships no
  user-visible surface.

#### Phase 12: Read Model and Lapsed Derivation ✅ COMPLETE

**Prerequisites:** Phases 3 and 10.
**Estimated diff:** ~120 production → **~480 tracked** (×4) · **Overrun recorded before work started
(delivery rule 3): ~300 production → ~1,200–1,400 tracked.** Calibration rule 14 applies at full force
and the original figure predates it. This phase's deliverable is a *decision* — is this task lapsed, and
why — whose acceptance criteria read as a matrix, which is exactly the shape that took Phase 3 to ×6.6
against production. Three things beyond the rule itself: the read model is three dataclasses and a pure
assembler, not a boolean; the derivation needs a fact no existing port can answer (whether a journal is
cancelled), so a port method and its adapter come with it; and "done and cancelled tasks are never
lapsed" crossed with two lapse causes and a timezone boundary is a matrix before a single journal is
seeded. · **Actual:** ~643 production → **2,870 tracked** (2,870 insertions, 69 deletions across 20
files: 643 production, 1,924 tests, 303 docs).

**The pre-recorded overrun undershot, and for the opposite reason to Phase 3's.** 2,870 against 480 is
6.0× on the estimate, and 2.2× on the pre-recorded one — but against *production* it is **4.5×**, which is
calibration rule 1's plain ×4, near enough. **The multiplier was right and the production estimate was
half what the work cost.** That is a different failure from Phase 3's, where 123 production lines bought ×6.6, and the
two together sharpen the rules rather than contradicting them. What the 300-line estimate missed was not
test volume: it was that a *shape* is expensive to write down in this codebase. Three frozen dataclasses
whose fields each need a sentence saying why they are there, a pure assembler, an enum, a service, a port
method and its adapter came to 643 lines of which perhaps 260 are executable — the rest is the
documentation convention rule 13 already noticed for port ABCs ("a port ABC costs roughly as much as its
adapter in a codebase that documents every abstract method"), applied to every artefact rather than only
to ports. **Suggested amendment:** when a phase's deliverable is a *vocabulary* — types other phases will
consume rather than logic one phase will run — estimate its production at roughly twice the executable
lines, then apply ×4 as usual. ITER18-004's dashboard projection types are the next phase this catches.

**Acceptance criteria, ticked:**

**Scope boundary taken with Phase 13, recorded here because it moves work between two phases.** This
phase ships the read model for **one** task and a **pure** assembler over already-fetched pieces. The
batched link reads that let *N* tasks be assembled without an N+1 stay in Phase 13, whose own third
criterion is "one query per collection, not per task" — so Phase 13 reuses this assembler under a batch
fetch rather than re-deriving the rule. Splitting it the other way would have put a batch API in a phase
with no list to serve.

- [x] `lapsed` is **derived in the read model, never stored**: a not-done task whose due journal's date has
      passed in the user's timezone (Phase 3's predicate), **or** whose due journal is cancelled
      (`EventState.CANCELLED`). — `derive_lapse_reason(status, due_journal_date, due_journal_cancelled,
      today)` in `core_shared/models/tasks/lapse.py`, called by the assembler on **every** read. No
      column, no migration, no job. The dates arrive resolved by Phase 3's module —
      `journal_date(journal, tz)` against `today_in(tz, now)` — with the timezone taken **once** per
      read through `timezone_for`, which is the batch shape that module was split for.
- [x] The derivation reports **why** a task lapsed — date passed vs due journal cancelled — as structured
      data, so surfaces can word it differently. ITER18-002 Phase 4 depends on this distinction; the UI
      wording itself lives in Phase 16. — `LapseReason.DATE_PASSED` / `DUE_JOURNAL_CANCELLED`, a
      `StrEnum` whose two wire values are pinned by a test, carried on `TaskReadModel.lapse_reason`.
      No pre-worded string reaches a surface.
- [x] Done and cancelled tasks are never lapsed. — The status gate is the rule's first branch, checked
      before either cause rather than folded into them, and asserted at all three levels: the bare rule,
      the assembled model, and against rows read back from PostgreSQL in each terminal status against
      both a passed and a cancelled due journal.
- [x] The read model carries the task with its journals by role and its contacts, in the shape both read
      surfaces (Phase 13) and the dashboard (ITER18-004) consume. — `TaskReadModel` with
      `creating_journal`, `due_journal`, `intermediate_journals` and `contacts`
      (`core_shared/models/tasks/read_model.py`), assembled by `TaskReadService.read_model`.

**Decisions taken (Phase 12):**

- **Cancellation is reported ahead of a passed date.** A not-done task whose due journal is *both*
  cancelled and past reads as `DUE_JOURNAL_CANCELLED`. It is the more specific and more actionable of
  the two — the meeting was called off, rather than merely that time went by — and it is the reason
  ITER18-002 Phase 4 pins end to end. Asserted at the rule *and* against real rows, because a single
  test would let a later reordering of the two branches pass the unit suite.
- **A cancelled *future* due journal still lapses its task.** The specification's cancellation rule
  carries no date condition, and the moment the commitment was pinned to is not going to happen
  whenever it was scheduled for. This is also the case that makes the reason worth reporting at all:
  the date cause demonstrably cannot be what fired.
- **A journal dated exactly today is not lapsed**, mirroring Phase 3's strictly-after `is_future_dated`.
  An inclusive boundary would lapse every task created for a journal earlier the same day, the moment
  it was made, and would leave the read-time and write-time rules disagreeing about one journal.
- **`invited` and `tentative` are not cancellations, and a journal with no calendar-info row is not an
  event.** Treating any non-confirmed state as cancelled would lapse every task due in a meeting the
  user had not yet accepted. The four-state fixture is what makes the cancellation query
  non-vacuous — without it the same test passes against a query matching *any* event journal.
- **Only the due journal decides the lapse.** The creating journal is almost always in the past — that
  is what "the journal the commitment arose in" means — so consulting it would lapse nearly every task
  the day after it was written. A cancelled creating journal is *marked* on its ref and changes no
  verdict, which is ITER18-002 Phase 4's third criterion checked at the layer where it would first go
  wrong.
- **The rule and the read model live in `core_shared/models/tasks/`, taking primitives.** The precedent
  is `BlockingTask` / `blocking_task_from_anchors` in `core_shared/models/journals/task_anchor.py`: a
  pure rule beside its frozen dataclasses, with no journal-domain or backend import. A journal ref
  therefore carries a resolved **`date`**, not an instant — so no surface can re-derive it in the
  browser's zone and disagree with the rule that judged the task, which is the divergence Phase 3
  recorded and this shape closes for tasks.
- **The assembler takes the two anchors as arguments, not as ids to look up.** A read model without its
  due journal could not answer whether the task lapsed, so the signature makes that state
  unrepresentable and leaves "what does a missing journal mean" with the service that did the fetching.
- **A missing anchor raises `JournalNotFoundError`; a missing mention is skipped.** The asymmetry is
  deliberate: losing the due journal makes the verdict a guess, while losing a mention only loses a
  mention, and a task the user can no longer open is worse than one showing one fewer journal. Both
  anchors are `ON DELETE RESTRICT`, so neither branch is reachable today.
- **`TaskReadService` is separate from `TaskService`, not more methods on it.** It writes nothing, so it
  takes no event publisher and opens no unit of work — `OutdoorDashboardService` is the precedent — and
  a caller that only needs to read a task is not handed the ability to change one. It is the only
  consumer of `CalendarInfoRepository` outside the journal domain.
- **Cancellation is read in batch, by the journal domain's own port.** `find_cancelled_journal_ids`
  went on `CalendarInfoRepository` rather than into a new tasks-side read port: "is this journal
  cancelled" is journal knowledge, the port already exists and has exactly one implementation, and a
  new port + adapter pair is a ×6 phase by calibration rule 13. The ids pass as one `integer[]`,
  following Phase 11's batched insert, so the parameter count stays at one whatever *N* is.
- **The read model for *one* task ships here; the batched link reads stay in Phase 13.** Recorded above
  as a scope boundary before work started. The assembler is pure, so Phase 13 reuses it under a batch
  fetch rather than re-deriving the rule.
- **The two link *reads* stopped paying the write path's ownership statement, and a read now costs
  seven statements rather than nine.** `list_intermediate_journal_ids` and `list_contact_ids` each
  opened with the port's separate `SELECT … FOR KEY SHARE` guard, one statement after the task had
  already been read owner-scoped. **This was first recorded as a follow-up for Phase 13 and the
  deferral was wrong**, for a reason worth keeping: the argument was that Phase 13's batched reads
  would absorb the cost, which is true of the read model and false of the other three call sites —
  `TaskService`'s trail wrappers call `list_intermediate_journal_ids` on every create, `PATCH` and
  retarget response, and those never get batched. So the waste would have outlived the phase that
  was supposed to remove it.
  **The fix is a `LEFT JOIN` from `tasks` inside `_list_links`,** which answers in one statement what
  the guard answered in two: driving from `tasks` means an unowned or absent task yields no rows,
  while an owned one with no links yields exactly one row with a null id. The guard *keeps* its
  `FOR KEY SHARE` and keeps guarding all four link **writes**, where the lock is load-bearing — it is
  what stops a concurrent delete turning the promised `TaskNotFoundError` into a raw foreign-key
  violation. A read has no such window, and a lock taken there would block a writer for the length of
  the reading transaction. **Mutation-checked:** turning the join into an inner one fails **20** tests
  (every "no links" case across the repository and the read model), dropping the `user_id` predicate
  fails the **3** cross-user cases, and removing the guard from a write still fails its own **2**. The
  case that carries the most weight is a foreign task with *no* links: one with links would come back
  non-empty and be caught by anything, so only that one shows the predicate is doing the work.
- **The contact display-name formatter was duplicated rather than extracted.** The only other copy is
  inline in `_enrich_journal_data` (`app/api/journals/controllers.py`); lifting it would rewrite a
  shipped endpoint from inside a tasks phase, which is the ITER17-003 P1 mistake calibration rule 8
  exists for. Both produce the same `"Contact {id}"` fallback so a person reads the same on a task as
  on a journal. **Follow-up recorded:** consolidate when a phase has another reason to open that
  controller.
- **`recorded_statements` was *moved*, not copied**, to `backend/tests/integration/statement_recorder.py`.
  Three suites now count round trips, and a second copy of a listener whose correctness is not obvious
  is the kind of duplication that drifts.

**Required Test Coverage:** unit — both lapse causes, across a day boundary in a non-UTC timezone, and
non-application to done/cancelled tasks. Integration — derivation against a real cancelled event journal and
a real past-dated journal. No e2e.

**Delivered: 49 unit tests and 31 integration tests.**

- **Unit (12):** `backend/tests/unit/tasks/test_task_lapse_derivation.py` — the rule at every boundary.
  Yesterday, **today** and tomorrow; a cancelled journal dated in the future and one dated in the past
  (the precedence case); both terminal statuses against both causes, parametrised, plus a done task due
  in the future so the statuses are not only tested on the lapsing side; and the enum's two wire values
  and the fact that there are exactly two, because a third cause is a surface decision rather than a
  quiet addition.
- **Unit (13):** `backend/tests/unit/tasks/test_task_read_model.py` — the assembler. The three roles kept
  apart; invariant 6's shared journal reported under both; the retarget-onto-an-attached-journal shape
  where the due anchor is a mention as well; mention order preserved rather than re-sorted; contacts in
  link order with names and photos; empty tuples rather than `None`; **only the due journal decides the
  lapse**, proved with a passed creating journal and a cancelled *mention* beside it; and `lapsed`
  being exactly "there is a reason", both ways.
- **Unit (24):** `backend/tests/unit/tasks/test_task_read_service.py` — the fetching half over mocked
  ports, keeping its own doubles as `test_task_service_create.py` does. **The timezone cases are the
  centre of the file and each has its UTC control:** Sydney has crossed local midnight while UTC has
  not, so the task has lapsed there and not in UTC; New York has *not* crossed it while UTC has, so the
  task has lapsed in UTC and not there. Either alone would prove only that something lapsed; the pair
  in both directions is what proves the configured zone is the one in use, and neither can be
  satisfied by "fixing" the rule into UTC. Beyond those: one settings read for three journals; one
  journal query for all three roles, de-duplicated when a journal holds two of them; one contact
  lookup; the unknown and foreign task both answering `TaskNotFoundError`; a vanished anchor raising;
  a cancelled *creating* journal marked and inert; `now` omitted reading the real clock rather than
  never lapsing; and the two contact-name fallbacks.
- **Integration (20):** `backend/tests/integration/tasks/test_task_read_model_integration.py` — the
  same rules against real rows. A real past-dated journal and a real **cancelled event journal** (a
  real `calendars` row and `journal_calendar_info`), each with its negative — a `confirmed` event and
  a plain future note journal — because the cancellation test alone would pass against a query that
  treated any event journal as cancelled. Both causes at once. Both terminal statuses against both
  causes. A real Sydney `user_settings` row against the same rows with no settings row at all, giving
  opposite verdicts from one fixed `now`. Titles, mentions in link order and contacts read back from
  their own tables; the shared-journal shape under every role it holds. A real second user's task and
  an absent id answering identically. And **the round-trip count**: seven statements for a task with
  two mentions and two contacts, and still seven with six of each — the doubling is the part that
  matters, since a fixed number alone would pass against a loop that ran a fixed number of times.
- **Integration (7 new):** `backend/tests/integration/tasks/test_task_repository_integration.py` — the
  link reads' own contract, which the separate guard used to cover. Each read returns `[]` for a task
  that has never been linked to anything and raises for a foreign one and for an absent id: the four
  cases one statement now has to separate by itself. Plus one statement per read, counted; the reads
  taking **no** row lock, asserted through `xmax`, so a later "just reuse the guard" tidy-up cannot
  reintroduce one; and the pre-existing lock test moved onto `remove_contact`, which deletes a *child*
  row and so takes no parent lock of its own — an insert stamps `xmax` whether the guard ran or not,
  which would have made that assertion vacuous.
- **Integration (4):** `backend/tests/integration/journal/test_calendar_info_repository_integration.py`
  — `find_cancelled_journal_ids` over a set covering **all four** event states, a note journal with no
  calendar-info row, an id that does not exist, and an empty request proved to issue **no query** at
  all (the common path: most tasks have no mentions).
- **Mutation checks, run rather than argued.** Measured over this phase's three unit files and its
  integration file (73 tests). Neutering `derive_lapse_reason` to `return None` fails **14** across all
  four files. Dropping the status gate fails **11**. Loosening the today boundary from `<` to `<=`
  fails **4**. Reversing the cancellation/date precedence fails **2** — one per level, which is the
  count that made the second one worth adding: before it, the phase's central *decision* was held by a
  single unit test.
- **E2E:** none — deferral taken as the phase states. The phase changes no frontend file and ships no
  user-visible surface; ITER18-001's e2e lands in Phase 22.
- **Docs:** `docs/architecture/domain-architecture.md` gained *Task read model and lapsed derivation* —
  why lapsed is derived and never stored, the four cases as a table, why only the due journal decides
  it, how cancellation is read in batch and why `invited`/`tentative` are not it, the one-read-per-
  collection rule with the seven statements accounted for, and the anchor/mention asymmetry. The Tasks
  Domain entry links to it. Its repository-contract paragraph gained the write/read split — the guard
  is a *write-path lock*, and the reads scope themselves in their own join. `api-design.md`
  deliberately untouched — this phase adds no endpoint.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` and `core_shared`;
  `mypy .` clean over **893** backend files and **129** in `core_shared`; the full `tests/unit/` suite
  (**3,285** tests); and `tests/integration/tasks/`, `tests/integration/journal/`,
  `tests/integration/api/` and `tests/integration/mcp/` together (**1,716** tests). No frontend or e2e
  gates — the phase changes no frontend file.

#### Phase 13: Get and List-by-Journal — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 12.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple · **Actual:** ~1,206
production → **5,463 tracked** (5,463 insertions, 85 deletions across 20 files: 1,206 production,
3,708 tests, 549 docs — the last inflated by this entry, whose review section is a third of it).

**The estimate missed production by ~8×, and the multiplier was right again.** 5,463 against 600 is
9.1×, but against *production* it is **4.5×** — calibration rule 1's plain ×4, for the second phase
running. Phase 12 recorded exactly this shape and proposed an amendment for *vocabulary* phases;
this one shows the amendment is not specific to vocabularies. "Capability triple" was read as
service + REST + MCP over a read model that already existed, which is why 150 looked reasonable.
What it left out is that a triple over a **collection** is not a triple over an entity: the phase
added a new `core_shared` module with its own enum, dataclass and pure rule (217); three port methods
whose ABC docstrings cost as much as the SQL under them (191 for both halves); a second service
method plus the refactor that put the single read on the same assembly (186); and — the part that is
easiest to miss — **a second resource shape** on each surface, because a listing envelope is not a
detail envelope (292 schema lines and 196 MCP lines against 106 in the controllers). **Suggested
amendment, sharpening rule 1 rather than adding to it:** estimate a capability triple's production
from the number of *response shapes* it introduces, not the number of surfaces. One shape over three
surfaces is a triple; two shapes over three surfaces has been twice that here.

**Acceptance criteria, ticked:**

- [x] `GET /api/tasks/{id}` returns the task with its journals (by role) and contacts, including the lapsed
      flag and reason; MCP `get_task` matches. Another user's task 404s on both. — The endpoint answers
      resource type `tasks` with a **superset** of the write responses' attributes (below); `get_task`
      returns the same fields. Both 404s are byte-identical to an absent id apart from the id itself,
      asserted on both surfaces.
- [x] `GET /api/journals/{id}/tasks` returns the journal's tasks **grouped by link role** — due here,
      created here, mentioned here; MCP `list_journal_tasks` matches, with an optional role filter. —
      `group_tasks_by_link_role` in `core_shared/models/tasks/link_role.py`; the filter is offered on
      **both** surfaces rather than only MCP, since the asymmetry would have been the only one on this
      API.
- [x] Nested journals and contacts are fetched in **one query per collection**, not per task — an N+1 here
      is a correctness concern at journal scale. — Seven statements for a journal with two tasks and
      **still seven** with six, asserted against the driver; and at the unit level against the doubles,
      where the per-task link methods are additionally asserted *never awaited*.

**Decisions taken (Phase 13):**

- **A link role is derived, never stored.** No role column, no fourth link table, and no role in the
  query: `due` is the task's due anchor, `created` its creating anchor, `mentioned` its intermediate
  refs — all three already on Phase 12's read model. So the grouping is a pure function over assembled
  models, and the role *filter* is applied there rather than in SQL. Pushing it into the query would
  have been a second definition of "mentioned here" able to drift from this one, and the query would
  still have had to fetch the anchors to answer it.
- **A task holds two roles at once, and both groups list it.** Invariant 6's shared journal and a
  retarget onto an already-mentioned journal are the two shapes; both are asserted at unit and
  integration level. This is what forced the envelope decision below, and `find_tasks_for_journal`
  unions the three link shapes with an `EXISTS` rather than a join precisely so such a task is one row
  and is assembled once.
- **Two envelopes, one answer.** JSON:API forbids the same resource twice in `data`, so REST lists each
  task **once** with every role it holds in `link_roles`, and puts the grouping in `meta.groups` as
  ordered id lists. MCP has no such rule and an agent asked to list "by link role" wants the roles as
  the structure, so the tool nests whole tasks under `groups.due` / `.created` / `.mentioned` and
  repeats a two-role task in both — carrying `link_roles` on each copy so a nested one still says what
  it is, and saying so in the tool description so a counting agent does not report a duplicate as a
  bug. Same data, same ordering, same 404s.
- **The read resource is a superset, not a second type.** `GET` keeps `intermediate_journal_ids`
  beside the resolved `intermediate_journals`, so the "one renderer for the resource" rule the write
  responses were built around survives the read. The same choice on MCP, for the same reason: an agent
  that learned the shape from `create_task` should not need a second one to read the task back.
- **`meta` is a listing-specific model.** The shared `JsonApiMeta` is the paginated one; a journal's
  tasks are bounded by the journal, so borrowing it would have advertised page controls that do not
  exist. Unpaginated by design, like the incomplete-activities review before it.
- **The `self` link arrives, as the write path said it would.** `_to_resource` carried a comment that
  a link that 404s is worse than an absent one and that it "arrives with the read model". It does, on
  every task resource, and the write endpoints' tests were not touched to accommodate it.
- **Ownership costs no extra statement.** The viewed journal joins the same owner-scoped journal fetch
  the read models already need, and the 404 is raised when it comes back absent. So an unknown journal
  and another user's are one answer, while a journal of the caller's with nothing linked to it is a
  200 with three empty groups — the distinction the check exists for. The alternative, a dedicated
  ownership query, would have made the listing cost eight statements to say something the batch
  already knew.
- **The listing's 404 is the journal domain's `Journal not found`**, not the task domain's bare
  `Not found`. What the caller named wrongly was a journal; the tasks are not the problem. The same
  distinction the intermediate-journal tools already carry, and it needed no change to the error
  mapping — both surfaces inherit it.
- **Every linked task is listed, in every status — the dashboard's exclusions are not this surface's.**
  Read as a scope question at the start of the phase and worth recording, because the specification
  states the exclusions (§*Tasks*, "Done and cancelled tasks do not appear. Lapsed tasks do not
  appear.") only a few lines from the display rule. They belong to the **dashboard**: §*Lapsed tasks*
  is explicit that lapsed tasks "remain visible on every journal they are linked to … clearly marked",
  and §*Where tasks appear* asks a journal for "the tasks it is linked to", unqualified. So the lapse
  is a marker on the row here and there is deliberately **no status filter** on either surface — one
  would let an agent rebuild the "everything still outstanding" browser the specification refuses.
  Asserted rather than left to reading: done, cancelled and lapsed tasks are each shown listed.
- **The ordering follow-up Phase 10 handed here, closed with total orders.** Groups are ordered by
  due-journal date then **task id**; a task's mentions and contacts by link `created_at` then **the
  linked id**. Neither tie-break is defensive: in the *due* group every task shares the journal's date,
  so the id is the whole of that group's order, and `created_at` is `transaction_timestamp()` so every
  link written in one request ties. Both are asserted against rows constructed to tie — links attached
  in *descending* id order inside one transaction — rather than against rows that might happen to.
- **The batched link reads return rather than raise for an unowned task**, unlike their singular forms.
  The singular ones answer a caller who named one task and must be told it was wrong; the batch is
  given ids an owner-scoped query produced, so a missing key means "no links", and raising would let
  one concurrently-deleted task fail a whole page. A task with no links is *absent* from the mapping
  rather than present with an empty list, which is also why the batch uses an inner join where the
  singular read needs a `LEFT JOIN` to tell an unowned task from a linkless one.
- **The single read now runs on the batch.** `read_model` is the batch with one task in it, so there
  is one assembly path rather than two that could diverge. Its seven-statement cost is unchanged and
  is re-asserted in the new file as well as the old one, because the refactor is exactly the kind of
  change that could have quietly made it eight.
- **The `role` query parameter answers 400, not 422.** The application renders validation failures
  through its own JSON:API handler, so a bad query parameter reads like a bad body. Found by the test,
  which had assumed FastAPI's bare 422; the endpoint's published docs say 400.

**Settled with ITER18-002 Phase 4 — the cancellation assertions on these surfaces.** This phase
asserts, on both, that a not-done task whose due journal is cancelled comes back lapsed with
`lapse_reason` = `due_journal_cancelled` — not merely lapsed, since a passed-date journal would
satisfy that too. It arranges that with `mark_journal_as_event`, which is the right level for a
phase whose subject is *serialisation*. **The matching assertions after a real cancellation live in
ITER18-002 Phase 4**, which ran in parallel and merged second: `GET /api/tasks/{id}` and
`GET /api/journals/{id}/tasks` after a user's type-data edit, and `get_task` after a sync
cancellation, all in
`tests/integration/tasks/test_journal_cancellation_lapse_integration.py` and
`tests/integration/mcp/test_task_tools_mcp.py`. Nothing is outstanding here.

**Required Test Coverage:** unit — role grouping and serialisation. Integration — both surfaces against real
journals including a cancelled event journal; the cross-user 404; a query-count assertion proving the nested
collections do not N+1. E2E deferred to Phase 22.

**Delivered:** **175** tests — **96** unit and **79** integration. The unit half is three new files
(69) and two extended ones (27); the integration half is one new file (34) and two extended ones (45).

- `tests/unit/tasks/test_task_link_role_grouping.py` (**21**, new) — the pure rule: each role in
  isolation; a task linked in *no* role appearing nowhere; both two-role shapes; `roles_for` in a fixed
  order; ordering by due date, and by id over a **constructed** tie supplied out of order; the unique
  list de-duplicating; the filter keeping a two-role task under either of its roles; three empty groups
  for an empty journal; the three wire values pinned against the specification's own words; and that
  the models handed out are the *same objects* handed in, by identity, so a grouping cannot re-derive a
  lapse the assembler decided.
- `tests/unit/tasks/test_task_read_service_list.py` (**24**, new) — the batch against doubles: one call
  per collection at **2 and 6** tasks; the per-task link methods asserted **never awaited**; no contact
  lookup when nothing references anyone; the batched reads scoped to the acting user; links keyed to
  the task that owns them; a missing mention dropped and a missing anchor still fatal; both lapse
  causes and the status gate through the batch; done and cancelled tasks still listed; Sydney's
  midnight against UTC's; the filter reaching the grouping without narrowing the fetch; and the journal
  404 with its "no second lookup" half.
- `tests/unit/api/test_task_read_serialisation.py` (**24**, new) — the REST rendering: the superset,
  including the trail surviving as ids; the self link; journals by role with title, date and cancelled;
  a date asserted *not* to be a datetime; contacts carrying exactly three fields, so a role or
  attendance cannot creep in; `lapsed` taken from the model rather than recomputed; both reason wire
  values and `null` present rather than omitted; and the listing envelope — once in `data`, both roles
  named, `meta.groups`, an empty journal, and a filtered listing keeping the same shape.
- `tests/unit/mcp/domains/test_task_tools_schema.py` (**+22**) — both tools' contracts: the id bounds,
  the absence of `now`, a date, a `user_id` or a status filter, and what each description must *say* —
  that a task can appear in more than one group, that lapsed and finished tasks are included, that both
  lapse causes exist and that retargeting is the remedy. `_enum_values` grew a branch for an
  `anyOf`-wrapped optional enum, which is how an optional one is generated.
- `tests/unit/api/test_task_endpoint_docs.py` (**+5**) — the two endpoints' published documentation:
  their 404s, the three group names, and the two-role warning. FastAPI publishes these verbatim as the
  OpenAPI descriptions, so they are the contract a generated client reads.
- `tests/integration/tasks/test_task_journal_listing_integration.py` (**34**, new) — against real rows:
  the three roles from three genuinely different link shapes; both two-role shapes; a task linked
  elsewhere absent; the journal 404 for a **real** journal owned by somebody else and for an unknown
  id; another user's task never listed though both users have one; the **cancelled event journal**, a
  confirmed one lapsing nothing, the passed date, and both terminal statuses neither lapsed nor hidden;
  the ordering trio — by date, by id within the *due* group, and the two link tie-breaks over links
  written in one transaction in descending order; the statement counts at 2 and 6 plus the single
  read's seven; the filter for each role; the timezone pair; and the batched repository methods on
  their own terms, including an unowned task's links and an empty id list.
- `tests/integration/api/test_task_endpoints.py` (**+27**) — both endpoints end to end: the full read
  shape, both lapse causes, a done task with an old journal, the self link, the two 404s and the id
  bounds; and for the listing, the grouping, the two-role task **once** in `data` with two roles,
  `meta.groups`, the filter and its rejection, the empty journal, the two 404s, another user's task
  never listed, and the ordering to the wire.
- `tests/integration/mcp/test_task_tools_mcp.py` (**+18**) — `get_task`'s shape including the trail and
  a date rendered in Kiritimati's zone, both lapse causes, and the pair of 404s asserted
  byte-identically; `list_journal_tasks`' nested groups, the two-role task in both, the full read shape
  per row, the filter and its rejection, lapsed and finished tasks listed, the empty journal, the pair
  of 404s and the ordering.

**Mutation checks.** Four mutations were run against the finished suite, each reverted after:
removing the `data` de-duplication fails **2** (one unit, one serialisation); dropping the task-id
tie-break from the group order fails **1** and dropping the linked-id tie-break from the batched link
order fails **2** more, at integration level, which is the pair that proves both halves of the ordering
promise are load-bearing; replacing the batched mention read with a per-task loop fails **8** — six unit
and two statement-count — so an N+1 cannot be reintroduced quietly; and removing the journal-ownership
check fails **6** across all three levels. The first attempt at the de-duplication mutation failed to
fail, because the dict it deleted a guard from still de-duplicated; that is recorded because a mutation
check that passes is only evidence when the mutation is real.

**Acted on from the local review, before the gates were re-run.** Six findings, in descending order
of what they cost:

- **21 tests would never have run in CI.** `test_task_link_role_grouping.py` carried no
  `pytest.mark.unit`, and CI's backend unit job selects by marker (`uv run pytest -m unit`), not by
  path — so the whole pure grouping rule, including both two-role shapes and the ordering tie-break,
  collected locally and would have been silently deselected there. A module-level `pytestmark` fixes
  it. **Worth recording beyond this phase:** the marker selects only **1,326** of the backend's
  **3,422** unit tests, so this is a repo-wide gap rather than a slip in one file — tracked
  separately rather than swept up inside a feature phase.
- **`link_roles` under a `role` filter was described wrongly in three places.** `roles_for` reads
  from the groups it holds, so a filtered listing reports only the filtered role — while the
  controller docstring, `api-design.md` and the MCP helper all promised "every role it holds". The
  *behaviour* is the right one and is kept: roles read from the groups can never contradict
  `meta.groups`, so no client can be told a task belongs to a group the same response reports as
  empty. The three wordings were corrected instead, and `roles_for`'s own docstring now says which
  question it answers and which call answers the other one.
- **A stale docstring the write-up had claimed was fixed.** `_task_to_dict` still said "there is no
  tool that reads a task back". The rewrite had landed in `api-design.md` but not in the docstring it
  was quoting — corrected, and the correction is the reason to state this here rather than quietly.
- **`_list_links_for_tasks` named the wrong operator**, describing `unnest` where the query uses
  `= ANY`. The substantive claim — one array parameter rather than a placeholder per id, so asyncpg's
  32,767-argument limit is unreachable — was right; only the name was wrong.
- **"Seven statements" was stated as a constant and is a ceiling.** The contact-name lookup and both
  batched link reads skip a query they have nothing to ask, so a listing where no task references a
  contact costs six and an empty journal four. Every count test seeds a contact, so what was asserted
  was true; the docs and `_assemble`'s docstring now say ceiling, and say that invariance in the
  *task count* is the load-bearing half.
- **One near-vacuous test.** `lapsed is model.lapsed` could not fail, since `lapsed` is defined as
  "there is a reason" — any implementation deriving it from the reason passes. Replaced with a
  parametrized assertion over all three cases on the **rendered payload**: both keys present, and
  the flag agreeing with the reason. That one fails if a renderer drops either field.

The review also noted that the cancelled-event-journal fixture reached the *listing* only at service
level, the endpoint and tool cases using a passed date. The iteration doc's requirement is satisfied
either way by the `get_task` cases, but the batch is a different code path from the single read and
the cancellation marker is what a user is meant to spot on the row — so one test was added to each
listing surface (**+2**, included in the counts above).

**Acted on from the PR review** (`augment review` on #1285 — which declined the first request as too
large and had to be opted into explicitly). Three findings:

- **The write-up's own review section had been pasted into five unrelated phases.** The edit that
  added it anchored on `**E2E:** none — deferral taken as the phase states.`, a string Phases 3, 4, 8,
  11 and 12 all end with, and a plain string replace hits every occurrence — so five phases gained a
  block about Phase 13's findings, each one also breaking the list item it displaced. Removed, and the
  five list items restored; the doc now differs from the branch point only in the header line and this
  entry, which is the check that should have been run when the block went in. **The lesson is about
  the tool, not the text:** an anchored insert into a long document needs an anchor unique to the
  section, or a count assertion afterwards.
- **The `self` link was root-relative** where every other `links.self` in this API is absolute and
  base-URL prefixed. Not a deliberate divergence — just a path written without checking the
  convention. Now built from the request's base URL like `ContactConverter.to_resource` and
  `JournalConverter`, with `base_url` passed as a **parameter defaulting to empty** so the renderer
  stays a pure function of its arguments and its unit tests still need no request. It applies to the
  write responses too, so all five task routes emit one shape. Recorded in `api-design.md`.
- **A documentation test asserted less than its name claimed.** It was called
  *"says the lapse is derived on every read"* but only checked that the word `lapsed` appeared
  somewhere — which the neighbouring 404 test already implied. Now asserted on the phrases it exists
  to pin, `derived on every read` and `never stored`.

**A second review round found two more, both about the first round's own fixes reaching everywhere they
claimed to:**

- **The absolute `self` link was asserted on the read surfaces but not the write ones**, while the
  claim being made was that *all five* task routes emit one shape. A regression dropping `base_url`
  from `_to_resource` would have left the read tests green. Now driven through create, `PATCH` and
  retarget in one test, and mutation-checked: removing `base_url` from the write renderer fails it.
- **The `link_roles` field description still promised every role unconditionally.** The filtered-narrowing
  caveat had been corrected in the controller docstring, `api-design.md` and the MCP helper, but a
  Pydantic `Field` description is published in the OpenAPI schema — a fourth place a generated client
  reads the contract from, and the one most likely to be read by a machine.

Both are small, and both are the same failure: a correction applied to the places it was noticed
rather than to every place the statement appears.

**Two further rounds found three more, each smaller than the last — and one of them found a real
behaviour, not just wording:**

- **`task.id or 0` made a resource identify itself two ways.** A task without an id would have
  rendered `id="None"` beside a `self` link ending `/api/tasks/0` — a task that cannot exist.
  Replaced with `persisted_task_id`, which raises, matching
  `ContactConverter._validate_entity_id`. **Writing its test found the worse half:** the listing did
  not disagree, it *silently dropped* such a task, because `JournalTaskGroups.tasks` de-duplicates by
  id and skips models without one. A row missing from a journal's tasks is worse than an error — the
  caller cannot tell it was dropped — so the response builder now validates all three groups rather
  than only the de-duplicated set. Unreachable through the service either way, which is the reason to
  fail rather than paper over.
- **Two documentation tests asserted less than their names claimed**, both the same shape as the one
  the first round caught: the journal listing's 404 case checked only that `404` appeared, not
  `yours` — the part that actually documents "unowned and absent are one answer".
- **The `_assemble` docstring named one statement-count skip where `domain-architecture.md` names
  three**, so the floor is four rather than six. Matched, since two descriptions of the same number
  drift.

**Six of the eight PR findings were the same failure**: a statement corrected, or a claim made, in the
place it was noticed rather than in every place it appears — docstring, field description, architecture
doc, test name. Worth carrying forward as a review habit rather than a one-off: when a phase corrects a
sentence that exists in more than one artefact, the correction is not done until it has been grepped
for.

**E2E:** none — deferral taken as the phase states. The phase changes no frontend file and ships no
user-visible surface; ITER18-001's e2e lands in Phase 22.

**Docs:** `api-design.md` gained the two endpoints in the *Task Endpoints* table and eight conventions
they pin — the superset resource, the resolved-date rule, the arriving `self` link, the two envelopes
and why `meta` is listing-specific, the total orders, every-status listing, the no-extra-statement 404,
and that reads open no transaction — plus the two new tools in the MCP list, whose "no tool reads a task
back" clause is now out of date and was rewritten rather than left. `domain-architecture.md` gained
*A journal's tasks, by link role* — role derivation, the two-role shapes, the batched reads and their
deliberate return-rather-than-raise contract, the free ownership check, the total orders and the
every-status rule — and the Tasks Domain entry links to it.

**Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` and `core_shared`;
`mypy .` clean over **897** backend files and **130** in `core_shared`; and the full `tests/unit/`
suite together with `tests/integration/tasks/`, `tests/integration/api/`, `tests/integration/mcp/`
and `tests/integration/journal/` — **5,242** tests, all passing, of which **3,422** are unit. Re-run
in full after the review fixes rather than trusting the pass that preceded them. No frontend or e2e
gates — the phase changes no frontend file.

#### Phase 14: Upcoming-Window Listing — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 12.
**Estimated diff:** ~150 production → **~600 tracked** (×4) — capability triple · **Actual:** 707
production → **3,961 tracked** (3,961 insertions across 21 files: 707 production, 2,951 tests, 303 docs
— the docs figure counting this entry, as Phases 13 and 15 do).

**Acceptance Criteria:**

- [x] A listing of **not-done** tasks whose due journal falls between today and *N* days ahead inclusive,
      default seven, ordered by due-journal date soonest first, anchored on today in the user's timezone.
- [x] Lapsed, done and cancelled tasks are excluded. **The only fixture that makes the lapsed exclusion
      non-vacuous is a not-done task whose due journal is inside the window but `EventState.CANCELLED`** — a
      date-passed lapse cannot fall inside a forward window by construction. That fixture is required.
- [x] MCP `list_upcoming_tasks` with the same default and semantics, in the same PR.
- [x] The response carries task text, due journal id/title/date and linked contacts, in one query per
      collection. This is the query ITER18-004's tasks section consumes, so its shape is settled here.

**Inherited from ITER18-002 Phase 4 — the exclusion assertion this phase owes.** That phase's required
coverage names "the upcoming-window listing (where it must be excluded)", and the listing did not exist
when it ran. The required fixture above is that assertion, and the cancelled journal must be cancelled
**by the sync processor**, not by writing `journal_calendar_info` — a test that seeds the post-condition
of an operation has tested one side of a seam and assumed the other. Reuse
`tests/integration/core/integrations/journal_sync_seeding.py`. Note the interaction with the fixture's
own constraint: a journal inside a forward window is near-future, so the single-instance cancellation
marks it cancelled rather than attempting a delete.

**Required Test Coverage:** unit — window arithmetic and ordering, including a task due exactly on the
boundary day. Integration — both surfaces with tasks inside, outside, on the boundary, done, cancelled and
cancelled-journal-lapsed; window anchoring for a non-UTC user near midnight; no N+1. E2E deferred to
Phase 22.

**Delivered.** `GET /api/tasks/upcoming?days_ahead=7` and MCP `list_upcoming_tasks`, over one pure rule,
one statement and the batched assembly Phase 13 built. **707 production lines against a ~150 estimate**
(4.7×), and **3,961 tracked against ~600** (6.6×), of which 2,951 are tests and 303 docs — so **5.6×
against its own production**.

**Calibration rule 15 predicted this phase by name** and the estimate was not updated: it lists Phase 14
among the REST+MCP pairs still estimated at ×4 and says to take ×6-against-production as the default for
any phase with more than one entry point. 5.6× is that figure. Rule 14 applies on top — the deliverable is
a *decision* ("is this deadline coming up"), meaningful only at its boundaries, and every boundary is a
test. **The lesson is not about this phase but about the ones after it:** a rule that names the phases it
catches is only useful if their estimates are then changed, and these were not. Phases 15–22's estimates
carry the same ×4.

**What the shape settles, since ITER18-004 Phase 13 consumes it:**

- `core_shared/models/tasks/upcoming.py` (new) holds the whole rule, pure: `upcoming_window(today,
  days_ahead)` and `select_upcoming_tasks(models, window)`, returning an `UpcomingTasks` that carries the
  **window beside the tasks** — the shape `group_tasks_by_link_role` uses, and for the same reason: a
  surface renders "the next seven days" too, and an *empty* answer has no rows to derive the window from.
- **The window is computed in the service and never in SQL.** The timezone is resolved once through
  `JournalDateResolver` and shared by the window *and* the assembler — `_assemble` now takes it as a
  parameter, so one request cannot pay for two settings reads or straddle a change to it. A new
  `local_window(first, last, tz)` turns the inclusive date span into instants; `local_day_window` is now
  its single-day case. Pushing the conversion into SQL would put a second definition of "a journal's date"
  in the database, one no unit test could reach.
- **No cap and no pagination**, per ITER18-004 Phase 13's settled choice: `meta.total` equals `len(data)`
  and is named anyway because it is the count the UI's show-more displays. What bounds the collection is
  `days_ahead`, capped at 90 in the **domain rule** as well as on both surfaces, so it cannot be sidestepped
  by reaching the service another way. `api-design.md`'s "there is deliberately no `/api/tasks` collection"
  became false and was rewritten rather than left: there is no *unbounded* one, and both listings are
  bounded by something.
- **The lapse is read, not re-derived.** The statement filters status and dates; the pure rule drops
  anything `lapsed` using the verdict `build_task_read_model` already reached from the batched cancellation
  lookup. So the **cancelled due journal** is the only fixture that makes the check non-vacuous — the
  mutation below confirms it is the *only* failure when the check is deleted.
- **Route ordering is load-bearing.** `/api/tasks/upcoming` is declared above `/api/tasks/{task_id}`, or
  `upcoming` parses as an id and 400s — the footgun `main.py:345` records for `/journals/series`. A test
  asserts the literal route wins, because the failure mode is an endpoint that silently became unreachable.

**Tests: 85 unit and 60 integration**, every unit one of them inside CI's marker selection.

- `tests/unit/tasks/test_task_upcoming_window.py` (**25**, new) — the pure rule: the default and
  `days_ahead=0`, every edge from both sides (today/yesterday, the boundary day/the day after), the three
  exclusions including the cancelled-due-journal one, the date-then-id total order, the bounds rejection,
  and that the answer carries its window when empty.
- `tests/unit/tasks/test_task_read_service_upcoming.py` (**20**, new) — everything the rule cannot see: the
  instants the repository is handed, a Kiritimati (+14) user at an instant whose UTC date is the previous
  day, the timezone resolved once, call counts at **2 and 6** tasks, and the per-task link reads asserted
  *untouched* rather than merely counted.
- `tests/unit/journal/test_journal_date_resolver.py` (**+9**) — `local_window`, the new multi-day
  generalisation the tasks window is built on (`local_day_window` is now its single-day case, asserted
  equal so the two cannot drift). **A seven-day window straddles a DST transition twice a year**, which a
  one-day window never does. The property test — every journal whose local date is in the span has its
  *instant* inside the range, at any hour and in **both folds** — is parametrised over four spans
  including two midnight-transition zones, and is what caught the bug below.
- `tests/unit/api/test_task_read_serialisation.py` (**+7**) and `test_task_endpoint_docs.py` (**+6**) — the
  envelope, and what the endpoint's published description must say. The docs test exists because the
  endpoint's whole contract is one integer with a default: everything that makes the answer meaningful is
  prose, and a client that does not read it will see a task vanish and conclude it was deleted.
- `tests/unit/mcp/domains/test_task_tools_schema.py` (**+17**) — the tool's contract: the default of 7 **in
  the schema** rather than only in the sentence, both bounds, and seven refused parameters (`now`/`today`/
  `date` — the anchor cannot be moved; `user_id` — no impersonation; `status` — the exclusions are the rule;
  `page`/`limit` — the window is the bound).
- `tests/integration/tasks/test_task_upcoming_listing_integration.py` (**30**, new) — against real rows,
  with `now` injected and journals seeded from **fixed instants** wherever the assertion is about an edge, a
  boundary case on a moving clock being a flake waiting for a late-evening run. The boundary day is seeded
  at **23:00** on purpose: a statement using the day's *start* would still pass a morning fixture. Both
  Kiritimati halves; the same-local-day-different-hours case that proves the rule's order wins over the
  query's; statement counts at 2 and 6, and the floor of **two** for an empty window.
- `tests/integration/api/test_task_endpoints.py` (**+19**) and `tests/integration/mcp/test_task_tools_mcp.py`
  (**+11**) — both surfaces end to end, each asserting the cancelled-due-journal task **absent here and
  present with its reason on its journal in the same test**, so "hidden, not lost" is proved rather than
  assumed.

**Mutation checks.** Nine were run, each reverted after. Removing the lapsed exclusion fails **5**, across
all four levels, and the cancelled-due-journal cases are the only ones that fail — the non-vacuousness the
phase demanded, demonstrated rather than asserted. Making the window's far end exclusive fails **6**;
dropping the id tie-break from the pure sort key fails **2**; anchoring the window on UTC fails **3**;
reintroducing an N+1 on the contact read fails **6**; dropping the SQL status filter fails exactly **1** —
the repository-level test, which is why that class exists at all, since the pure rule would otherwise mask
it; dropping owner scoping fails **2**; and carrying the window's first-day offset to its far end fails
**2**, which is the DST case above.

**One attempted mutation was itself a no-op and is recorded because it looked like a passing check.** The
first attempt at the DST mutation replaced the end's `tzinfo` with `start.tzinfo` — which *is* the same
`ZoneInfo`, so nothing changed and every test stayed green. A mutation that passes is only evidence when
the mutation was real, and this one had to be rewritten to carry a fixed `timezone(utcoffset())` before it
meant anything. The same trap Phase 13 recorded with its de-duplication mutation, hit again in a different
shape.

**One mutation found a real gap rather than confirming a test.** Dropping the upper bound from the
statement's `BETWEEN` left *every* test green, because the pure rule filters the window a second time. The
answer stays correct and the query silently becomes "every future task of this user's, resolved" — the
unbounded listing this endpoint exists not to be. A repository-level test was added
(`test_it_fetches_neither_side_of_the_window`), and re-running the mutation now fails exactly that one test
and nothing else. **The lesson generalises:** defence in depth at two layers means a weakened *lower* layer
is invisible from above, so any layer that duplicates a filter needs a test addressed to it directly.

**Acted on from the local review, before the gates were re-run. It found a real bug, in the one place the
phase had argued a bug was impossible.**

- **The window's far end was an hour short in any zone whose clocks go back *at midnight*.**
  `local_window` built it as `combine(last_day, time.max, tz)`, and `ZoneInfo` resolves that ambiguous
  wall time with `fold=0` — the **earlier** of the two passes through 23:59:59.999999. In Santiago,
  Beirut and Asunción the last hour of such a day happens twice, so the window closed an hour before the
  day did. PostgreSQL then compares *instants*, so `BETWEEN` dropped rows that the pure rule's
  `contains()` said were inside — **exactly the SQL-versus-rule disagreement this phase claimed could not
  happen**, and the reason it claimed so (that both are built from the same dates) was true and
  insufficient. The user-visible failure: a Santiago user's task due at 23:30 on 4 April 2026 is absent
  from the dashboard and from `list_upcoming_tasks` for that one day a year, with nothing to say it was
  dropped. Fixed by taking a microsecond off the **following** midnight, which has no ambiguity to
  resolve because the first instant of a day is unique however the clocks moved — done in UTC and
  converted back, since subtracting a `timedelta` from a `ZoneInfo`-aware datetime is wall-clock
  arithmetic and would land straight back on the ambiguous value. **The bug predates this phase** in
  `local_day_window` (the outdoor dashboard has carried it since iteration 16); what this phase did was
  generalise it and put it under a user-visible listing, so it is fixed here for both.
- **The test that was supposed to catch it could not.** The property test compared `window.start <=
  moment <= window.end` with all three carrying the *same* `ZoneInfo` — and Python compares two aware
  datetimes sharing one `tzinfo` by their **naive** values, ignoring the offsets. So it asserted
  wall-clock containment while the thing it existed to protect is an instant comparison, and it was
  parametrised only over Sydney, whose 02:00/03:00 transitions cannot produce the ambiguity anyway. It
  now converts both sides to UTC, probes **both folds** (`combine` only ever yields `fold=0`, so the
  repeated hour was never sampled), and runs over four spans including Santiago and Beirut. Restoring
  the old implementation now fails it in both midnight zones plus two explicit cases — four failures
  where there were none. **The general lesson: a datetime assertion that never converts is not asserting
  what a database will.**
- **"Raised before any query runs, so a rejected request costs no database work" was false.** The
  timezone read happens first — the bound cannot be checked against a window that has not been built.
  The test named `..._before_any_read` did not contradict the claim because it only ever asserted the
  *listing* query. Both were corrected; the test is now `..._before_the_listing_query` and asserts the
  batched reads are untouched too.

The review also confirmed what it could not fault: all four acceptance criteria against the code, every
Required-Test-Coverage item against a named test, the MCP parity claim (nothing reachable on one surface
and not the other), that both pre-existing `_assemble` callers were updated, and every spot-checkable
number in this write-up.

**Acted on from the PR review** (`auggie review` on #1294). One finding, medium severity, and it was
right — a second instance of the *same* failure the local review had already found once:

- **The wall clock was read twice per request, so a listing could disagree with itself at midnight.**
  `today_in(timezone, now)` was called once to build the window and again inside `_assemble` to judge the
  lapse, and with `now=None` — which is every production call — each samples the clock afresh. A request
  crossing local midnight between the two would build the window against day *D* and judge the lapse
  against *D+1*, so a task due on *D* is inside the window the response reports and simultaneously "date
  passed" to the lapse rule: **dropped from a listing that claims to include it**. Fixed structurally
  rather than by passing the same instant down — `_assemble` now takes `today: date` instead of
  `now: datetime | None`, so there is exactly one clock read per request and the two halves cannot
  disagree by construction. All three read paths resolve it once and hand it down.
- **The first test written for it was vacuous, and a mutation caught that.** It stubbed the clock to
  advance a day per call, but seeded the task *mid-window* — where a lapse judged a day late still
  doesn't fire — so reinstating the second read left it green. The task has to be due on the window's
  **first day** for the two verdicts to collide, which meant overriding the shared journal fixture. Now
  the mutation fails it. **Twice in one phase a test was written that could not fail**, and both times a
  mutation was the only thing that noticed; the habit is worth more than either fix.

Worth recording that the local review and the PR review found the *same class* of bug in the same file —
two clock/date reads that can disagree — in two different places. A phase whose subject is "what day is
it" should audit for repeated reads as a matter of course rather than waiting to be told twice.

**E2E:** none — the deferral the phase states. No file under `frontend/` changes and no user-visible surface
ships; ITER18-001's e2e lands in Phase 22 and the dashboard's in ITER18-004 Phase 17.

**Docs:** `api-design.md` gained the endpoint row, a rewritten opening (the "no `/api/tasks` collection"
claim), and ten conventions — route ordering, today-in-the-window versus future-dated, the timezone anchor
and the absent seams, the asymmetric exclusions between the two listings, the lapse applied to the read
model, the uncapped window and what `meta.total` is for, the window travelling in `meta` when empty, and
the row being the read resource without `link_roles`. `domain-architecture.md` gained *The upcoming window*
— the pure rule, the today disagreement, the single timezone resolution, the only-one-exclusion-bites
point, the reused batching with its floor of two, the two different orderings, the bound, and the
midnight-ambiguity rule the review's bug turned into architecture rather than a comment — and the
Tasks Domain entry links to it.

**Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` and `core_shared`;
`mypy` clean over **900** backend files and **131** in `core_shared`; the full `tests/unit/` suite at
**3,568** passing, of which **1,441** are marker-selected. All **85** of this phase's new unit tests are in
that selection, checked per file with `pytest -m unit --collect-only` rather than assumed — Phase 13's
21-tests-that-would-never-run finding is the reason it is checked rather than trusted. (The repo-wide gap
it recorded is untouched and still real: 1,441 of 3,568 is the same proportion as 1,326 of 3,422, so the
marker still misses roughly six unit tests in ten. That remains tracked separately, not swept up here.)
And **1,984** integration tests
across `tests/integration/tasks/`, `api/`, `mcp/`, `journal/` and `core/`, all passing — re-run on the
tree merged with main, since ITER18-002 Phase 4 (cancellation as a lapse reason) landed mid-review and
makes a cancelled journal *really* lapse the tasks due in it, which is precisely the exclusion this
listing rests on. Its own `test_journal_cancellation_lapse_integration.py` is in that count. No frontend
or e2e gates — the phase changes no frontend file.

#### Phase 15: Frontend — Task API Client ✅ COMPLETE

**Prerequisites:** Phase 13.
**Estimated diff:** ~90 production → **~360 tracked** (×4) · **Actual:** ~866 production →
**2,406 tracked** (2,406 insertions, 14 deletions across 7 files: 866 production, 1,326 tests,
207 docs, 7 config — the docs figure counting this entry, as Phase 13's does).

**The estimate missed production by ~9.6×, and this time the multiplier was *low*, not high.** 2,406
against 866 production is **2.8×**, under calibration rule 1's ×4 — a frontend client has one layer to
test, not the service/REST/MCP three a backend phase multiplies over, so its test share is smaller.
What the 90 missed is that "a client file plus types" is two files: `types/tasks.ts` (216) has to
exist before a single hook can be typed, and it mirrors five backend schema shapes rather than one.
The rest is surface count — the phase reads as "the read surfaces and mutations", which sounds like
four calls and is **ten routes**: two reads, four task writes, and two relationship pairs.

**Acceptance criteria, ticked:**

- [x] `frontend/src/lib/api/tasks.ts` + `frontend/src/types/tasks.ts`: `taskKeys`, module-level
      fetchers, two `useQuery` hooks (`useTask`, `useJournalTasks`) and **eight** `useMutation` hooks
      covering every write route — create, update, retarget, delete, contact link/unlink and
      intermediate-journal attach/detach — with the journals client's toasts, `credentials: 'include'`
      and JSON:API envelopes.
- [x] Every mutation routes through `invalidateAfterMutation`. **The criterion names
      `frontend/src/lib/invalidate-after-mutation.ts`; the helper is at
      `frontend/src/lib/api/invalidate-after-mutation.ts`** — recorded rather than silently corrected,
      because the wrong path in a criterion is what sends the next reader looking for a second helper.
      A source-level test asserts the file contains no `invalidateQueries(` call at all, so a later
      edit cannot reintroduce the race by hand.
- [x] `details()`, `journalLists()` and `upcoming()` are **siblings** under `['tasks']`, never nested,
      so a journal's task list and the dashboard's task section invalidate independently. Two tests
      assert it in both directions rather than leaving it to inspection.

**Decisions taken (Phase 15):**

1. **Failures throw `TaskApiError`, not a bare `Error`.** Every other client in `lib/api/` collapses a
   response to `errors[0].detail` and discards the `code` beside it. Two later phases cannot work
   without that code — Phase 18 has to tell `TASK_REOPEN_NOT_ACKNOWLEDGED` from a real failure to
   offer *"reopen it anyway"*, and Phase 20 has to put `TASK_DUE_JOURNAL_NOT_FUTURE` against the
   due-journal field — and the alternative is matching on prose. The error carries `status`, `code`
   and the refusal's `meta`. Scoped to this client; nothing else was retro-fitted.
2. **`useRetargetTask` raises no toast for `TASK_REOPEN_NOT_ACKNOWLEDGED`.** That 409 is the service
   asking whether reopening a completed task was intended — a confirmation gate, not a failure. A red
   toast under the Phase 18 confirmation dialog would tell the user something went wrong when nothing
   has. Every other retarget failure still toasts, which is asserted separately so the exception
   cannot widen by accident.
3. **No `setTimeout` before invalidating.** `useCreateJournal`/`useUpdateJournal`/`useDeleteJournal`
   delay theirs by 150ms; the journal-tag client (#1204) already dropped the timer and explains why in
   its docstring — the write commits in the service layer before the response is sent, so there is no
   read-after-write race to wait out. This follows the newer of the two conventions.
4. **`journalLists()` is invalidated as a prefix, not per journal id.** A retarget changes *two*
   journals' lists — the new due journal and the one being left, which becomes an intermediate link —
   and the journal being left is only knowable from the response. Reconstructing the set per mutation
   would be a second definition of what changed, free to drift from the first; these collections are
   unpaginated and bounded by their journal, and only mounted ones refetch.
5. **A mention link leaves `upcoming()` alone.** That listing selects on the *due* journal, so
   attaching or detaching an intermediate link cannot move a task in or out of a forward date window.
   Asserted as a negative — the test fails if `upcoming()` appears among the invalidated key sets —
   because an over-broad invalidation is invisible in a passing suite otherwise.
6. **No upcoming-window hook.** Phase 14 is not built, so the endpoint would 404. The key namespace is
   reserved anyway, because the third criterion is about the *shape* of the keys and retrofitting a
   sibling namespace later is exactly the change that quietly nests it.
7. **`frontend/.gitignore`'s `types/` rule was anchored to `/types/`.** Unanchored, it matched
   `frontend/src/types/` as well as the `frontend/types/` declaration tree `.design-sync/prepare.mjs`
   emits, so `src/types/tasks.ts` was **silently untracked** — `git add -A` reported six files and
   staged five. The existing modules under `src/types/` are unaffected only because they predate the
   rule, which is why nobody had hit it. `index.d.ts` was anchored with it: same defect, same commit,
   one line away.
8. **Task mutations opt out of the app-wide `retry: 1`.** `lib/providers.tsx` retries every failed
   mutation once, a second later. That is wrong here twice over: **`POST` create is not idempotent**,
   so a request that succeeded on the server but lost its response records the same commitment twice;
   and **a refusal on this surface is often the answer rather than a failure**, so retrying a
   `TASK_REOPEN_NOT_ACKNOWLEDGED` would put Phase 18's confirmation dialog a retry-delay behind the
   click and log a second refusal for every one the user resolves. Found in review — decision 2 was
   written as though the 409 reached `onError` directly, and it does not. The two tests that pin it
   build a client carrying the *app's* mutation defaults rather than the suite's `retry: false`, or
   they would assert nothing.
9. **A deleted task's detail is removed from the cache, not invalidated.** The first version omitted
   the detail key from the delete refresh, reasoning that refetching a deleted task would only 404.
   True, and an argument against *invalidating* rather than for doing nothing: the entry stays fresh
   for the app-wide five-minute `staleTime` and resident for the ten-minute `gcTime`, so a `useTask`
   mounting after the delete would render the deleted task from cache without issuing a request.
   `removeQueries` is the right tool and is not an invalidation, so the no-bare-`invalidateQueries`
   rule is untouched.

**Required Test Coverage:** unit — hook behaviour against a mocked client, and a test pinning that
mutations cancel before invalidating, in that order.

**Delivered:** **52** unit tests, all in `frontend/src/lib/api/__tests__/tasks.test.ts`, following the
`contact-tag-mutations.test.ts` / `tag-management-mutations.test.ts` idiom — mocked `fetch`, mocked
`sonner`, mocked constants, a real `QueryClient`. The ordering requirement is a table-driven
`it.each` over all eight mutation hooks asserting
`lastCallOrder(cancelSpy) < firstCallOrder(invalidateSpy)`, **guarded by an equal-call-count
assertion**: without it a hook using bare `invalidateQueries` would leave `cancelSpy` with no calls,
`Math.max()` of nothing is `-Infinity`, and the ordering assertion would pass vacuously.

**Mutation checks.** Six deliberate breakages across two rounds, each reverted after confirming it was
caught: swapping one refresh helper to `queryClient.invalidateQueries` failed 4 tests; adding
`upcoming()` to the mention-link refresh failed the negative assertion; deleting the retarget's
no-toast branch failed its test; and after the review, dropping the two `NO_RETRY` opt-outs and the
`forgetTask` call failed 3 more. These are the assertions the acceptance criteria and the two review
fixes rest on, so a green suite that could not fail on them would have been worth less than it looked.

**Acted on from the review, before the gates were re-run.** Seven findings; the first two are defects
in the client's behaviour rather than in its presentation.

- **The app-wide `mutations.retry: 1` had been overlooked entirely** — see decision 8. The suite's own
  `QueryClient` sets `retry: false`, so nothing in 46 passing tests could have surfaced it. This is
  the second time this phase that a test's *fixture* was the reason a defect was invisible.
- **`useDeleteTask` left the deleted task's detail cached and fresh** — see decision 9. The docstring
  read as though the case had been considered and closed, which is worse than not mentioning it.
- **`TaskUpdateInput` stated a constraint its type did not encode.** The doc comment said a caller
  must send text or status, while both fields were plain optionals, so `mutate({ taskId })` compiled
  and produced a 400. Now a union of two arms, each requiring one attribute — the three legitimate
  shapes still type-check and the empty one does not.
- **`contact_ids` and its own comment disagreed about `[]`.** The guard tested truthiness and an empty
  array is truthy, so a picker left empty sent `contact_ids: []` beside a comment saying "no contacts
  is the absence of the field". Guarded on length, with a test.
- **Three weak spots in the suite.** A `useJournalTasks` test asserted only that two key factories
  differ — a fact an earlier test already pins exactly — and never rendered the hook; it now proves
  the two listings issue two requests rather than one serving the other from cache. The source check's
  `toMatch(/invalidateAfterMutation\(/)` half was trivially true and was dropped. `useUnlinkTaskContact`
  and `useDetachTaskIntermediateJournal` had no key-set assertions of their own, protected only by
  sharing a helper with their twins; both now have one, including the `upcoming()` negative.
- **Two claims in `frontend-design.md` were wrong.** It said `TaskApiError` carries status/code/meta
  "rather than collapsing the response to its `detail` string" — it does both, `message` *is* the
  detail — and it listed `upcomingWindow` as feeding the dashboard with no note that nothing consumes
  it yet, sending a reader of the architecture doc alone to look for a hook that does not exist.

**Known limit, recorded rather than fixed.** `frontend/src/types/tasks.ts` is a hand transcription of
`backend/app/api/tasks/schemas.py`, and every fixture in the suite is typed *from those types*. So the
read-shape and listing tests assert that a hand-written object survives `response.json()` unchanged,
which any pass-through implementation satisfies: if the backend renamed `lapse_reason`, added a
required attribute or changed `date` to a datetime, this suite would stay green. The transcription was
checked against the schemas by hand and against the three `core_shared` enums value-for-value, and
Phase 22's e2e is the eventual backstop, but **there is no mechanism keeping the two in step** and a
generated client or a contract test is out of scope for a phase this size.

**E2E:** none, and not a deferral of convenience — no component mounts these hooks until Phase 16, so
there is no page for Playwright to drive. ITER18-001's e2e lands in Phase 22, which owns the
`TestDataManager` task helpers and the lapsed-fixture recipe. **Integration:** none either; the phase
adds no Python, and the routes these hooks call already carry their own integration coverage from
Phases 5–13.

**Docs:** `frontend-design.md` gained *Task Query Keys* — the three sibling namespaces in a table,
why the arrangement is a contract rather than a naming choice, the rule that a mutation names only the
namespaces its change can reach (with the mention-link exception as the worked example), `TaskApiError`
and the codes surfaces branch on, and the no-timer rule. `api-design.md` is unchanged: it documents the
backend surface, and no backend file was touched.

**Gates run locally:** `pnpm format` then `pnpm quality:check` — Prettier, ESLint and `tsc --noEmit`
clean, 0 errors (the 112 remaining warnings are pre-existing Playwright-plugin ones in `tests/e2e/`).
The full Jest suite rather than the new file alone, because `lib/constants.ts` is imported app-wide:
**166** suites and **1,810** tests, all passing. Re-run in full after the review fixes rather than
trusting the pass that preceded them. No backend gates and no e2e — no Python file and no rendered
surface changed.

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

#### Phase 2: Delete Guard Surfaces — REST and MCP ✅ COMPLETE

**Prerequisites:** Phase 1.
**Estimated diff:** ~130 production → **~520 tracked** (×4) · **Actual:** ~228 production → **~1105
tracked** across 15 files (production 228 — the payload builder and the `error_meta` hook 55, the two
wirings 29, the published OpenAPI model 80, the `responses=` block and two docstrings 34, package
exports 2, imports and comments 28; tests 826 across four files; docs 51 on top of the iteration doc).

**The production estimate was right until review, and the tests were 3.6× it throughout.** The first
pass came in at 146 against an estimated 130 — as close as rule 13 gets. The remaining 82 is one
review finding: the 409 was declared with a description but **no schema**, so the acceptance
criterion's "discoverable from the OpenAPI document" was not true, and a typed model plus its tests
had to be written (see the decisions below).

What ran over on tests is the same thing Phase 3 recorded, and it is worth sharpening rather than
repeating: **a phase whose deliverable is "two surfaces must agree" pays its test cost per surface,
not per rule.** The payload builder is one function with one behaviour, but proving it arrives needs
the shape asserted at the REST wiring, at the MCP wiring, and then a third time comparing the two —
and the integration halves cannot be shared, because REST resolves `JournalService` from Dishka while
the MCP tool constructs it by hand. Phase 3 hit this and called it "the test count is set by the
number of ways the data can be corrupted". The parity variant is: **for a phase whose acceptance
criteria name more than one surface, multiply the test estimate by the number of surfaces before
applying rule 13's multiplier — and count the contract's published form as one of the surfaces.**

**Acceptance Criteria:**

- [x] `DELETE /api/journals/{id}` returns the structured error (status per open decision 1), naming each
      blocking task and its action journal. — 409 with code `JOURNAL_HAS_ANCHORED_TASKS` and
      `errors[0].meta` carrying `journal_id` plus a `blocking_tasks` list; each blocker gives
      `task_id`, `text`, `status`, `blocking_roles` and the action journal's id **and** title. The
      route declares the 409 in `responses=` with a **typed model**
      (`JournalHasAnchoredTasksErrorResponse`), so the payload is discoverable from the OpenAPI
      schema rather than only from a failing call — which is what Phase 5's dialog will be typed
      against.
- [x] MCP `delete_journal` returns the equivalent in the same PR, so an agent can resolve the blockage
      without the UI. — a new `except JournalHasAnchoredTasksError` branch in
      `mcp_unified_error_handler`, returning the same two keys plus `code`; the tool docstring says
      what comes back and what to do with it.
- [x] The payload is explanatory prose **plus** machine-readable ids — not an opaque constraint message —
      and the ids are enough to build a link without a further lookup. — `detail`/`message` still carry
      Phase 1's sentence unchanged; the ids sit beside it. Tested as a behaviour rather than a shape:
      one integration test reads `action_journal_id` out of the refusal and `GET`s that journal, and
      asserts the title it gets back is the `action_journal_title` the payload promised.

**Decisions taken (Phase 2):**

- **One builder, not one per surface.** `blocking_task_payload` lives in
  `core_shared/core_shared/models/journals/task_anchor.py`, next to the rule that builds a
  `BlockingTask`, and both surfaces call it. The specification asks for "the same failure" over REST
  and MCP; two serialisers agreeing today is a thing to re-test forever, one serialiser is a property
  of the code. Pinned at both levels anyway — a unit test compares the two mappings of one error
  instance, and an integration test refuses the *same seeded journal* over both surfaces and compares
  field for field, because the unit test cannot show that both surfaces are *wired* to the builder.
- **The seam is `DomainError.error_meta()`, not a special case in the handler.** A typed hook on the
  base class returning `None` by default, so `create_domain_error_response` stayed a one-line change
  and no `getattr` sniffing was needed. `exclude_none=True` drops the key for every other error, so
  the other ~40 error responses are byte-for-byte unchanged — asserted directly, on the dumped body.
- **`status` is emitted as `.value`.** `TaskStatus` is a `StrEnum`, so an encoder would have accepted
  the member and nothing would have failed; a caller reading the dict directly should still get a
  plain `str` rather than something that merely compares equal to one. Pinned with `type(...) is str`
  and a `json.dumps` round-trip, which is the assertion that would catch a future non-`StrEnum` field.
- **The MCP branch sits above the `JournalDomainError` catch-all**, which would otherwise flatten the
  refusal back to its message — this is the whole phase, silently undone. Mutation-checked: moving the
  branch below the catch-all fails five tests. Two tests keep it honest in the other direction, that
  `JournalValidationError` still reaches the catch-all and `JournalNotFoundError` still reports as
  missing, so the branch cannot be widened by accident.
- **`mcp-setup.md` gained nothing**, per the repo convention that per-tool MCP documentation lives in
  the docstring. The `delete_journal` docstring now describes the refusal payload field by field.
- **No frontend file and no e2e**, as the phase specifies. The delete-failure dialog and its coverage
  are Phase 5, whose prerequisite this is.
- **A payload nobody can find is not a surface — and both places it is published were, at first,
  untestable prose.** Raised by the phase's own review, and it was the most useful thing it found.
  The 409 `responses=` entry originally carried only a description, so the *OpenAPI document* said
  "this can 409" and nothing about the shape; and the MCP docstring — which by repo convention is the
  only per-tool documentation there is — was nine lines that could be deleted with zero failures.
  Both are now pinned by `tests/unit/journal/test_journal_delete_guard_documentation.py`, and both
  mutation-checked: removing the `model=` fails the schema test, removing the docstring paragraph
  fails three. **The rule worth carrying: when a phase's deliverable is a contract, the document that
  publishes the contract needs a test, or the deliverable is only half shipped.** The typed model is
  hand-written while the body is built by `blocking_task_payload`, so the blocked-delete integration
  test also validates the real 409 body against it — the drift the two-sources arrangement invites is
  closed where it would appear.
- **And publishing the model was not the same as publishing the *contract*.** The PR's automated
  review caught the follow-on mistake: `status` and `code` were declared as `Field("409", ...)` and
  `Field("JOURNAL_HAS_ANCHORED_TASKS", ...)`, which reads like pinning the values and does the
  opposite — a default makes a Pydantic field **optional**, so both landed outside `required` and
  typed as a bare `str`. The document therefore advertised a `code` that a generated client could
  not rely on being present, let alone discriminate on, which is precisely what the model was added
  for. Both are now `Literal`, which makes them required *and* emits a `const`. **The lesson pairs
  with the one above: a published contract needs a test that reads the published form, not the model
  source — the mistake was invisible in the class definition and obvious in the generated schema.**
  The new test asserts both fields are in `required` with the right `const`, and fails if either
  default returns; and because the blocked-delete integration test validates a real body against
  this model, the literals are checked against what the endpoint actually emits rather than merely
  declared.
- **The third finding was in the test, not the code — and the fix is the reusable part.** Review
  round 2 spotted that the MCP docstring documented `code`, `message` and every blocker field but
  **not the top-level `journal_id`** the handler returns. The docstring test was supposed to prevent
  exactly that and did not, because its expected field names were a **hand-written list** — as
  complete as whoever typed it, which is to say not. It now derives them from a real error's
  `error_meta()`, so any field the refusal grows must be documented or the test fails.
  **And tightening it exposed a second, sneakier hole:** the check was a substring search, and
  `journal_id` is a substring of `action_journal_id` — so the missing field looked documented by the
  field that had displaced it, and the naive version of this fix still passed. The test now matches
  each name in its marked-up ` ``field`` ` form, and mutation-checking it by deleting `journal_id`
  from the docstring reports precisely that field. **Carry-forward: a test that enumerates what a
  contract should contain must derive the list from the thing itself, and match on a delimited form
  — a hand-written substring check fails in both directions at once.**
- **The guard's query is still not owner-scoped, and Phase 2 makes that worth restating.** Phase 1
  documented the exemption and it stands: the query substitutes for a foreign-key check, so a row an
  owner filter hid would come back as the raw `IntegrityError`. What Phase 2 adds is *ids* on top of
  Phase 1's task text, so a caller reaching `JournalService.delete_journal` without the ownership
  check would hand out directly addressable references to another user's rows. Nothing reaches it
  that way today — both surfaces check, `TaskService` cannot create a cross-user anchor, and both
  ownership tests still pass — but the protection is conventional rather than structural, which is
  exactly the shape of **issue #1267** (`JournalService` takes no user id at all). Recorded here so
  #1267 is read as covering this too.

**Required Test Coverage:** unit — error-to-response mapping and payload schema. Integration — both
surfaces with several blocking tasks, with a done-only blocker, and with intermediate-only links (succeeds).
No e2e (Phase 5).

**Delivered: 25 unit tests and 8 integration tests.**

- **Unit (17):** `backend/tests/unit/journal/test_journal_delete_guard_surfaces.py`, a new file rather
  than more classes in Phase 1's — that file tests the rule, the error and the guard, and the surfaces
  are a fourth concern with different collaborators. *The payload (6):* all six fields present; each of
  the three statuses as its string value; roles as an ordered list including `["creating", "due"]`; and
  a `json.dumps` round-trip. *The error's hook (3):* journal id and every blocker; order preserved;
  and `JournalNotFoundError` offering nothing. *REST (4):* the meta lands on `errors[0].meta`; the
  prose survives beside it with the 409 and the code; the dumped body still carries the blockers; and
  another domain error gains no `meta` key at all. *MCP (3):* the code, the message and the same
  blockers; `JournalValidationError` still reaching the catch-all; `JournalNotFoundError` still
  reported missing. *Parity (1):* one error, both mappings, equal blocker lists.
- **Unit — documentation (8):** `tests/unit/journal/test_journal_delete_guard_documentation.py`. The
  route's generated OpenAPI declares the 409 *and* a `$ref`'d schema rather than only a description,
  the published model lists exactly the six blocker fields, `status` and `code` are **required with
  a `const`** rather than optional defaults, and the 404 is declared too; the MCP tool's description
  names the code, every payload field, and what to do next. Both halves are the only place the
  contract is published, so both are asserted rather than assumed. The field list is **derived from a
  real error's payload**, not hand-written, and matched on its marked-up form — see the third review
  finding below for why both halves of that matter.
- **Integration (8):** four in `tests/integration/api/test_journal_endpoints.py` — three blockers in
  three roles with three different action journals, asserted as one exact list in id order with the
  journal still standing (and the body validated against the published schema, which is what stops
  the hand-written model drifting from the builder); a done-only blocker reporting `status: "done"`;
  an intermediate-only journal deleting with its link row and leaving both anchors whole; and the
  follow-the-link test above. Four in `tests/integration/mcp/test_journal_tools_integration.py` — the
  same three, plus the cross-surface parity test that refuses one seeded journal over both surfaces
  in one client and compares `blocking_tasks`, `journal_id`, `detail`/`message` and the code.
- **Mutation checks, all four verified rather than assumed.** Removing `meta=domain_error.error_meta()`
  fails three of the four REST integration tests — not the intermediate-only one, correctly, since a
  successful delete has no payload to lose. Moving the MCP branch below the catch-all fails five tests
  across both levels. Removing the 409's `model=` fails the schema test; removing the MCP docstring's
  payload paragraph fails three; returning `status`/`code` to defaulted strings fails the
  discriminator test; and dropping `journal_id` from the docstring fails the field-coverage test by
  name.
- **Two test-quality fixes the review also caught**, both worth naming because each would have passed
  for the wrong reason: an `assert response.status_code in (200, 204)` on the intermediate-only delete
  — a multi-outcome assertion of exactly the kind `CLAUDE.md` forbids, on a route whose status code is
  declared — now asserts `204`; and both intermediate-only tests counted `task_intermediate_journals`
  **globally**, so they would have been satisfied by an unrelated task losing its mention. Both are now
  scoped to the task under test.
- **Gates run locally:** ruff format and lint clean over `backend/` and `core_shared/`; mypy clean
  (864 backend + 94 `core_shared` source files); **2851 unit tests** and **1369 integration tests**
  (`api`, `mcp`, `tasks`, `journal`) passing against Docker PostgreSQL, zero failures. No frontend
  gates and no e2e — no file under `frontend/` changes.
- **Docs:** `docs/architecture/api-design.md` gained a *Structured Error Detail (`errors[].meta`)*
  section under Error Handling Guidelines — the `error_meta()` contract, that it is opt-in, and the
  four conventions (prose alongside not instead, plain JSON only, id *and* label for anything
  linkable). `docs/architecture/domain-architecture.md`'s *The journal delete guard* gained the
  per-surface payload table and the two load-bearing placements.

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

#### Phase 4: Cancellation as a Lapse Reason ✅ COMPLETE

**Prerequisites:** ITER18-001 Phase 12.
**Estimated diff:** ~100 production → **~400 tracked** (×4) · **Actual:** **~16 production** →
**~1,135 tracked** across 7 files (1,135 insertions against 263 deletions: production 16, of which 3
are executable and the rest the docstring explaining the contract; tests 908 — 535 the new
integration file, 192 the extracted harness, 122 re-pointing the sync suite at it against 243 lines
lifted out of it, 59 two unit tests; docs 211, of which 23 architecture and the rest this entry).

**The multiplier is meaningless here and the estimate was wrong in an interesting way: this phase had
almost no production code left to write.** Its four acceptance criteria are all *properties of code
Phases 1–3 already shipped* — the delete guard's cancel-instead-of-delete fallback, and Phase 12's
lapse rule. The ~100-line production estimate was made before any of that existed and quietly assumed
Phase 4 would build the cancellation path; by the time the phase ran, the path was there and the only
thing missing was **proof that its ends meet**. Well over a thousand tracked lines against 16 of
production is not a test-volume overrun, it is what a **seam phase** costs — and the size is set by
the number of independent routes into the seam, which review showed was three rather than the two
the phase first counted.

**Suggested calibration amendment (rule 16).** A phase whose criteria are all "X already does Y"
should be estimated as **tests + harness + docs, with production at or near zero**, and its size
driven by *how many independent routes reach the seam*. Here there are two — the single-instance
cancellation and the series fan-out — and neither is evidence for the other, so the central journey
is written twice. The tell that a phase is this shape: every acceptance criterion can be phrased as
an assertion rather than an instruction. ITER18-003 Phase 10 (a merge re-points anchors and publishes
no task event) is the next phase this catches.

**Acceptance Criteria:**

- [x] Cancelling a journal changes no task links. — asserted from the tables rather than the read
      model, over every link a task can hold: both anchors, `status`, `text`, an intermediate journal
      and a contact. The cancellation writes only `journal_calendar_info` and the external link, so
      there is nothing for it to disturb; the test exists because that is a property of the current
      implementation rather than of the schema.
- [x] A not-done task whose **due** journal is cancelled reads as lapsed with the cancellation reason
      through every read surface — pinned end to end against real journal cancellation rather than a
      constructed read model. — every *act* of cancelling goes through one of the **three** real
      write paths (a user's `PUT` to the EVENT type data, and calendar sync's single-instance and
      whole-series routes), and the verdict is read back through `TaskReadService.read_model` **and
      through all three shipped read surfaces**: `GET /api/tasks/{id}`, `GET /api/journals/{id}/tasks`
      and MCP `get_task`. The one test that seeds an already-cancelled journal is the
      **un**-cancellation test, where that is the starting position rather than the assertion. Only
      the upcoming-window listing is still deferred, because it does not exist yet — see below.
- [x] Cancelling a journal that is a task's **creating** journal changes nothing about the task. —
      the ref is marked `cancelled` and the verdict is unchanged. Also asserted for a **mentioned**
      journal, which the criteria do not name but the rule has the same obligation toward.
- [x] Cancelling a journal that anchors a task is never blocked. — asserted with a not-done, a done
      **and** a cancelled task anchored to the same journal: the event reports success, the journal
      survives, and it ends up cancelled rather than deleted.
- [x] The UI wording for the two lapse reasons ships in ITER18-001 Phase 16; this phase adds no
      frontend code. — no frontend file changed, and no e2e, as stated.

**A deviation that opened and closed inside the phase, which is worth recording as a sequencing
lesson.** The required coverage names `get_task`, `list_journal_tasks` and the upcoming-window
listing. When this phase was written **none of the three existed** — no read route, no read tool, and
`TaskReadService` with no production caller at all — because they are ITER18-001 Phases 13 and 14,
while this phase's own prerequisite is Phase 12. So the seam was pinned one layer down at
`TaskReadService.read_model` and the surface halves were written into Phases 13 and 14.

**Then Phase 13 merged while this PR was in review, and the deviation's justification evaporated.**
`GET /api/tasks/{id}`, `GET /api/journals/{id}/tasks`, `get_task` and `list_journal_tasks` all exist
now. Phase 13 does assert the cancellation lapse on each of them — but against a journal it cancels
by writing `journal_calendar_info` directly, which proves the *serialisation* and assumes the write:
precisely the split this phase exists to close. **So the deviation is closed here rather than left
open**, with three tests that ask the shipped surfaces after a **real** cancellation: `GET
/api/tasks/{id}` and `GET /api/journals/{id}/tasks` after a user's type-data edit, and MCP `get_task`
after a sync cancellation. Only the upcoming-window listing (Phase 14) remains deferred, since it
still does not exist.

**The lesson is about parallel phases, not about this one.** Two phases were in flight against the
same seam from opposite sides, and the one that merged first covered it in the weaker of the two
ways available — not wrongly, but with the arrangement its own subject made natural. A note written
into a phase that is *already being implemented elsewhere* cannot reach it. **Where two phases share
a seam, the assertion belongs to whichever ships last, and that has to be decided when the second
one is planned rather than recorded as a note in the first.**

**Decisions taken (Phase 4):**

- **A "constructed read model" turned out to include the constructed *journal*.** Phase 12 already
  tested `DUE_JOURNAL_CANCELLED` against real rows — but the cancelled row was one the test wrote with
  `mark_journal_as_event(..., EventState.CANCELLED)`. That proves the read half and assumes the write
  half. What this phase adds is the only thing left: that the state a *real* cancellation leaves
  behind is the state the read looks for. **The general form is worth keeping: an integration test
  that seeds the post-condition of the operation it is about has tested one side of a seam and
  asserted the other.**
- **All three cancellation routes are tested, because none is evidence for the others.** A single
  `journal_event.cancelled` and the `journal_event.series_cancelled` fan-out reach
  `_mark_journal_cancelled` through different code — the fan-out decides per instance inside a
  per-item savepoint — and **a user setting the event editor's status to "Cancelled"** reaches the
  column through `JournalWriteService.update_type_data`, sharing nothing with either. The mutation
  checks confirmed each split earns its keep: removing the series fallback fails **exactly one**
  test, removing the single-instance fallback fails **seven**, and stopping the type-data update
  from persisting `event_state` fails **exactly the two** user-path tests and none of the sync ones.
- **The user-facing route was missed on the first pass and added after review — the correction is
  the most valuable thing in this phase.** The phase originally recorded that *no* user-facing
  cancellation existed and that `_mark_journal_cancelled` was the only writer. That was wrong:
  `event_state` is an editable field of the EVENT type data, exposed by `EventTypeEditor` and
  writable over `PUT /api/journals/{id}/types/EVENT/data`, and there was already a shipped test
  asserting that endpoint accepts `"cancelled"`. **The error came from searching for a
  cancel-journal *operation*** — an endpoint, tool or service method with a cancelling name — when
  the capability is a *field on an existing update*. Two independent agent investigations repeated
  the same search and reached the same wrong answer; the PR review, which reads the API schema and
  the editor rather than the call graph, found it immediately. **Carry-forward, and it generalises
  well past this phase: "no capability X exists" is a claim about every way X could be spelled, and
  a name-shaped search cannot establish it. Before recording an absence, look at the surface a user
  touches — the form, the request schema's enum, the editor — because a capability expressed as a
  field will not appear in any search for a verb.** It also cost real coverage, not just accuracy:
  the route a person actually takes was the one route the phase had no test for, and it is the one
  the specification's cancel-rather-than-delete steer points at.
- **A second enum contract, found in review round 2, and it protects against data loss rather than a
  wrong read.** The first pass bound `event_state` from its enum and left the link's `sync_status`
  as a literal, with a docstring asserting that "nothing reads it to decide anything". **That was
  wrong**: `_should_delete_cancelled_instance` checks `link_sync_status == "cancelled"` *first*,
  and it is the idempotency guard that makes cancellation sticky — marking a journal cancelled bumps
  the link's `updated_at`, which erases the edit-protection signal, so without that check a
  redelivered cancellation would **delete** a journal that was deliberately protected on the first
  pass. Both ends now bind `ExternalEventLinkSyncStatus.CANCELLED.value`. **The lesson is about how
  the wrong claim got written: it was reasoned from the field's *name* — "sync status sounds like
  bookkeeping" — rather than from its readers. A literal is safe only if you have looked for every
  comparison against it, and `grep` for the value is the cheap way to do that.** The `'synced'`
  writes elsewhere in the processor are still literals and are genuinely unread by any cancellation
  decision; that remains a tidy-up of its own.
- **The one production change is five lines, and it is the seam's other end.**
  `_mark_journal_cancelled` typed `'cancelled'` into its `UPDATE` while `find_cancelled_journal_ids`
  binds `EventState.CANCELLED.value` — with a comment saying why, that renaming the member must not
  leave a query silently matching nothing. The same hazard pointing the other way is worse: a *write*
  that drifted from the enum leaves every task whose due journal was cancelled quietly un-lapsed,
  with nothing failing. Now bound from the enum on both ends, and the unit test compares them **to
  each other** — reading the value out of the *compiled* query — rather than each to `EventState`,
  which would let both drift together.
- **The phase had no conventional red phase for its integration tests, and the mutation checks are
  the honest substitute.** All nine passed the moment they were written, because the behaviour was
  already correct; that is the expected outcome for a seam phase and not evidence of anything. They
  were mutation-checked **before** moving on rather than at the end, which is the only ordering that
  makes "tests first" mean something when there is no production code to make them pass.
- **The sync harness was extracted rather than copied.** `_processor`, `_sync_event`,
  `_series_cancelled_event`, `_create_calendar`, `_event_state`, `_journal_exists` and
  `_link_recurring_id` moved from `test_journal_series_sync_processor.py` into
  `tests/integration/core/integrations/journal_sync_seeding.py`, taking `user_id`. The
  `recorded_statements` precedent from Phase 12: a second copy of a harness whose correctness is not
  obvious is the kind of duplication that drifts. The sync suite keeps ownership because it owns the
  processor, and the tasks suite imports across — the direction traffic already went, since that file
  already imported `tests.integration.tasks.task_seeding`.
- **The mentioned-journal test seeds its journal *near* future, deliberately.** Nothing anchors a
  mentioned journal, so the delete guard has no reason to refuse and a far-future instance would
  simply be **deleted** — a real behaviour, but a different one. Six hours out puts it in the
  fan-out's "cancel, don't delete" bucket, which is the arrangement the test is actually about.
- **Every journal in the file is ten days out.** The date cause therefore demonstrably cannot be what
  fired, which is what makes "lapsed" mean "cancelled" here without a timezone argument. The
  day-boundary cases belong to the rule and are Phase 12's; repeating them would be testing
  `derive_lapse_reason` a third time.

**Required Test Coverage:** integration — cancel a due journal and observe the lapse with the cancellation
reason through `get_task`, `list_journal_tasks` and the upcoming-window listing (where it must be excluded);
done and cancelled tasks unaffected; cancelling a creating journal is inert; cancellation is never blocked.
No unit work beyond what Phase 12 covers. No e2e (Phase 5).

**Delivered: 15 integration tests and 4 unit tests.**

- **Integration — the shipped read surfaces (3):** added once ITER18-001 Phase 13 merged and made
  them exist. `GET /api/tasks/{id}` and `GET /api/journals/{id}/tasks` after a user's real
  cancellation (in this phase's own file), and MCP `get_task` after a real *sync* cancellation (in
  `tests/integration/mcp/test_task_tools_mcp.py`, beside Phase 13's seeded counterpart so the pair
  reads as one story). Each asserts `lapse_reason` rather than merely `lapsed`, since a passed-date
  journal would satisfy the weaker claim; each journal is a week out, so it cannot.

- **Integration — the user's own route (2):** added after review, in the same file. A task due in a
  confirmed event journal is not lapsed; a real `PUT /api/journals/{id}/types/EVENT/data` through the
  authenticated client sets the status to cancelled; the task reads as lapsed with
  `DUE_JOURNAL_CANCELLED`. And the reverse — setting the status back to *confirmed* un-lapses it,
  which only this path can do and which is the second demonstration that the lapse is derived on
  every read rather than recorded. Mutation-checked by stopping the type-data update from persisting
  `event_state`, which fails **exactly these two** and none of the sync-driven ten.
- **Integration — the sync routes (10):** `backend/tests/integration/tasks/test_journal_cancellation_lapse_integration.py`.
  *The lapse (6):* a not-done task due in a future synced instance is not lapsed, is cancelled, and
  then is — the transition asserted on one set of rows, because the lapse alone would pass against a
  rule that lapsed everything and the control alone against one that lapsed nothing; the series
  fan-out reaching the same verdict by the other route, with `deleted=0, cancelled=1` and the journal
  still standing; the `cancelled` flag landing on the due ref and **not** on the creating or mention
  refs, over three distinct journals; a done and a cancelled task not lapsing, parametrised, with
  their own status asserted untouched; and **the recovery the specification names** — retargeting off
  the cancelled journal un-lapses the task, which is the test that shows the lapse is *derived* rather
  than sticky, since the retarget retains the cancelled journal as a mention and a rule that recorded
  the cancellation against the task would leave it lapsed forever. *Inert cancellations (2):* the
  creating journal and a mentioned journal, each marked on its ref and each changing no verdict. *The
  task itself (2):* every link unchanged, read back from `tasks`, `task_intermediate_journals` and
  `task_contacts`; and a journal anchoring all three task statuses cancelling without being blocked.
- **Unit (4):** `backend/tests/unit/core/integrations/test_journal_outbox_event_processor.py` — the
  event state is bound from `EventState` and not inlined in the SQL, and the value written equals the
  one the compiled cancellation query sends. Both confirmed **red** against the literal before the
  change. Round 2 added the same pair for the link's `sync_status`: the write binds
  `ExternalEventLinkSyncStatus.CANCELLED.value`, and the sticky-cancellation guard is asserted to
  compare against the enum rather than a literal. That last one reads the guard's **source**
  deliberately — the behaviour it protects only appears on a *second* delivery of the same event,
  which the integration suite already covers but which cannot distinguish a matching pair of
  literals from a matching pair of enum references.
- **Mutation checks, run rather than argued.** Neutering `derive_lapse_reason`'s cancellation branch
  fails **3**; making `_mark_journal_cancelled` write `'confirmed'` fails **all** of them, which is
  the check that shows the file is testing the seam rather than the rule; removing the series fallback
  fails **exactly the fan-out test**; removing the single-instance fallback fails **7**; pointing the
  lapse at the *creating* journal's flag fails the **2** tests that use three distinct journals — the
  creating-journal test is the discriminator, and the tests where creating equals due cannot detect
  it, which is why both shapes are present; and letting a cancelled *mention* count toward the lapse
  fails the **2** mention-bearing tests, including the retarget one. Reverting the enum binding fails
  both unit tests.
- **One mutation result had to be thrown away and re-run, and the reason is worth recording.** A
  mutation was applied while a wide integration run was still in flight against the same test
  database, and the two sessions fought: the wide run came back with 3 failures and 41 errors, and the
  mutation named the wrong tests. Both numbers were artefacts. **The integration fixture is a single
  savepoint-bound transaction per test but the *schema* is shared, so two pytest sessions in one
  workspace are not independent** — the same hazard as the recorded workspace-env port collision,
  reached from inside one worktree rather than across two. Mutation checks and suite runs are
  serialised here from now on; the results above are all from clean serial runs.
- **E2E:** none — deferral taken as the phase states. No frontend file changed.
- **Docs:** `docs/architecture/domain-architecture.md`'s *Task read model and lapsed derivation*
  gained *where a cancelled journal comes from* (the single writer, its two routes, and why a due
  journal always takes the delete-guard fallback), the write/read enum contract, and what cancellation
  does **not** touch.
- **Gates run locally:** `ruff format --check` and `ruff check` clean for `backend` and `core_shared`;
  `mypy .` clean over **895** backend files and **129** in `core_shared`; the full `tests/unit/` suite
  (**3,328** tests); and `tests/integration/tasks/`, `tests/integration/core/integrations/`,
  `tests/integration/journal/`, `tests/integration/api/` and `tests/integration/mcp/` — **1,796**
  tests, run in three serial chunks rather than one, for the shared-schema reason above. No frontend
  or e2e gates: the phase changes no frontend file.
- **Reviewed independently against this document and the specification**, with no findings. The
  review verified for itself that the three named read surfaces do not exist, that the deferral notes
  landed in ITER18-001 Phases 13 and 14, that re-pointing the sync suite changed no test's meaning,
  and that no other production code compares `event_state` against a hardcoded string.

#### Phase 5: Frontend — Delete Failure Explanation and E2E

**Prerequisites:** Phases 2–4.
**Estimated diff:** ~150 production → **~600 tracked** (×4)

**Acceptance Criteria:**

- [ ] The journal delete flow surfaces the blocking tasks: each named, each linking to the journal where it
      can be actioned, with working navigation.
- [ ] The dialog continues to steer toward cancelling the journal rather than deleting it.
- [ ] A delete that succeeds is unchanged from today's behaviour.

> **Note from Phase 4 — where the steer actually leads.** Cancelling a journal is a **type-data
> edit**, not an operation of its own: the event editor's *Event Status* select offers "Cancelled"
> and saves through `PUT /api/journals/{id}/types/EVENT/data`. So the steer is sound and this phase
> inherits no gap — but the dialog should point somewhere specific, because "cancel this journal
> instead" is only actionable if the user knows the control is the event editor's status field, and
> it only exists for **EVENT**-typed journals. For a note journal there is no cancelled state at all,
> and the only routes out of a blocked delete are the task actions the blocking-task links already
> lead to. Worth handling both cases in the wording.
>
> **This corrects a finding Phase 4 first recorded here and got wrong** — it claimed no user-facing
> cancellation existed anywhere. Caught by the PR review. The claim came from searching for a
> *cancel-journal operation* — an endpoint, tool or service method — when the capability is a field
> on an existing update, which is exactly the shape that search misses. Two separate agent
> investigations made the same mistake before a reviewer that reads the surface, not the call graph,
> found it in one pass. **Carry-forward: "no capability X exists" is a claim about every way X could
> be spelled, and a search for X-shaped names cannot establish it. Check the surface a user
> touches — the form, the schema's enum, the editor — before recording an absence.**
- [ ] E2E: deleting a journal with a task due in it shows the explanation; following the link reaches a
      journal where the task can be actioned; after cancelling or retargeting the task, the delete succeeds;
      merging a journal that anchors a task succeeds. Deterministic per-test fixtures, built with the
      Phase 22 helpers and their UTC-boundary caveat.

**Required Test Coverage:** unit (RTL) — the failure dialog rendered from the error payload, with one
blocker and with several. E2E as above, on both e2e projects.

#### Phase 6: Lock Order — Retargeting Against Merge

**Prerequisites:** ITER18-001 Phase 7, ITER18-002 Phase 3. Independent of Phases 2, 4 and 5.
**Estimated diff:** ~110 production → **~440 tracked** (×4)

**Why this exists.** Raised by the automated review on ITER18-001 Phase 7's pull request, confirmed
against the two lock sequences, and deferred to here rather than fixed in that phase because the fix
changes the *merge* contract's counterpart and needs a locking read on the journal domain's port — both
of which are this iteration's subject, not that one's.

The two operations acquire the same two kinds of row in **opposite orders**:

| | first | then |
|---|---|---|
| `TaskService.retarget_due_journal` | the **task** row, `FOR NO KEY UPDATE` | the **journal** rows, `FOR KEY SHARE`, via the link insert's and the anchor update's foreign keys |
| `TaskAnchorRepository.repoint_journal_links` and its caller | the **journal** rows, `FOR UPDATE` | the **task** rows, via `UPDATE tasks` |

So retargeting a task while a merge absorbs the journal it is due in deadlocks: PostgreSQL aborts one
side and that caller sees an unhandled database error. It is reachable whenever a merge's source is a
task's current or incoming due journal, which is exactly the pair a retarget touches.

This is **not** the residual deadlock `repoint_journal_links` already documents against task *creation*.
That one cannot be closed by any lock order, because an insert takes its foreign-key locks in
declaration order rather than by id. This one **can** be closed, because the retarget chooses when it
takes each lock — which is why it is a phase rather than a documented acceptance.

**Acceptance Criteria:**

- [ ] `retarget_due_journal` acquires its journal locks **before** the task lock, in the same ascending-id
      order `repoint_journal_links` uses, so the two operations queue instead of deadlocking.
- [ ] The previous due journal — which is not known until the task has been read — is handled without
      reopening the window: state the chosen approach (a non-locking peek followed by a locking read that
      re-verifies, or a locking read on the journal domain's port that covers both journals).
- [ ] The acknowledgement rule and the status the retarget decides from are still read under the row lock;
      the fix must not reintroduce the lost-*decision* hazard ITER18-001 Phase 6 closed.
- [ ] The same-journal no-op still reads no journal and takes no journal lock.
- [ ] `repoint_journal_links`'s lock-order docstring is updated to name retargeting as ordered *with* it
      rather than against it.

**Required Test Coverage:** unit — the order in which the locks are requested, asserted on the calls, so
a refactor cannot silently invert it again; the no-op still touching no journal. Integration — a retarget
overlapping a merge of its due journal completes rather than deadlocking, over two real connections and a
committed fixture, in **both** interleavings. No e2e.

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
2. ~~**Whether task events need typed payload models** in `core_shared/models/outbox_events.py`~~ — ✅
   **settled in Phase 1: no.** That dispatch map exists so integration *workers* can parse **inbound
   sync** payloads (`contact.`, `sync.completed`, `journal_event.*`, `immich_album.`,
   `journal_review.`); every core domain event — `JournalCreated`, `JournalTagAssigned`,
   `ContactCreated` — is absent from it, and no worker consumes task events. Task events therefore
   match the domain-event convention: a plain `dict[str, Any]` payload validated by the tests that
   assert its shape. Adding a model would advertise a consumer that does not exist. See *Decisions
   taken (Phase 1)*.
3. **Whether the contact-activity entry updates on task status change** or records only the link —
   settled in **Phase 5**. The specification asks for "a read-only record alongside their journals", which
   the simpler link-based entry satisfies.

> **Why nine phases for "add some events" — and why it is now ten.** Iteration 17 measured it: two event types plus their
> projection cost ~1440 lines (ITER17-005 Phase 1) and *one* type plus projection cost ~1270
> (Phase 2a), and it recorded the conclusion — *"a future phase adding an event type should budget ~600
> test lines per type up front"*. Tasks need nine event types. Calibration rule 6 therefore caps this
> iteration at two new types per phase, with the projection split from the publishing.
>
> **It became ten during Phase 3.** That phase's local review found a task write nobody had counted: a
> journal **merge** re-points task anchors and intermediate links and publishes nothing task-scoped, so
> the projection this iteration builds would show a merged task's history disagreeing with its own row.
> It is **Phase 10**, added rather than folded into ITER18-002 Phase 3, which is complete and merged.
> *The estimating lesson is the one worth carrying:* "how many event types does the entity need" counted
> the writes on the entity's **own** service and missed the one performed on it by another domain.

#### Phase 1: Events — Task Created and Deleted ✅ COMPLETE

**Prerequisites:** ITER18-001 Phase 9.
**Estimated diff:** ~150 production → **~600 tracked** (×4)
**Revised before work started (delivery rule 3):** ~140 production → **~1,000–1,300 tracked**. The
original figure contradicts the iteration's own calibration rule 6 — *"budget ~600 test lines per
event type up front"*, borne out by ITER17-005 P1 (2 types, ~1440) and P2a (1 type, ~1270) — and this
phase ships **two** types. It also threads provenance through **two** entry points, which rule 15
budgets at roughly one behaviour matrix each. Production is genuinely small: the events module, a
constructor argument, two publish calls, one DI line and four argument lines at the surfaces. The
tests are the phase.
**Actual:** **250 production → ~1,810 tracked** (events module 141, service 71, controller 8, MCP 8,
DI 8 — 1,432 tests and fixtures, ~125 docs of which most is this entry). **Recording the overrun
before work was right, and the revised figure was still low on both halves.** Production came in at
250 against ~140 — the events module alone is 141 lines, because this repo documents *why* rather
than *what* and both classes carry a decision in their docstring. Tests came to 1,432 against a
1,000–1,300 range, i.e. **5.7× production**, in line with rule 15's ×6 default for a phase with more
than one entry point. **The miss the estimate did not see is mechanical:** adding one constructor
argument to `TaskService` touched **nine** service-construction sites across the unit and integration
tests, none of which is interesting and all of which is diff. *Calibration addition:* a phase that
changes a **widely-constructed** collaborator's signature should count its construction sites — a
`grep` for the class name — as part of the estimate, because that cost scales with how well-tested
the class already is and is invisible from the production change.

**Acceptance Criteria:**

- [x] Domain event classes for task created and task deleted, following the journal/contact domain-event
      conventions (`source` provenance, `changed_by`, `occurred_at`, aggregate id). — in
      `backend/app/core/tasks/models/events.py`, mirroring `app/core/journal/models/events.py`
      including its local `DomainEvent` base (see *Decisions taken*). Payload shape is asserted as a
      **whole-key comparison** rather than a set of `in` checks, so a later phase adding a field has
      to do it deliberately, and both payloads are asserted to survive a JSON round trip because that
      is how the projection will actually receive them.
- [x] Each is published through `OutboxEventPublisher` **inside the same unit of work** as its write, so an
      event never exists for a write that rolled back. — asserted against a real database by opening a
      **caller's** unit of work and failing inside it: `@transactional` is re-entrant, so the service
      joins it and neither the `tasks` row nor the `outbox_events` row survives. Both directions are
      covered — a rolled-back create leaves no task and no event, a rolled-back delete leaves the task
      *and* no deletion — plus the cheaper half, that a create refused by an invariant writes neither.
- [x] Provenance is threaded from the caller, so UI, MCP, system and integration origins are
      distinguishable on every event. — `Provenance.UI` from the controller, `Provenance.MCP` from the
      tools, defaulting to `SYSTEM` in the service. Asserted **per surface** against the stored JSON,
      not only at the service: the service's default is a silent success, so an endpoint that forgot
      to say where it was calling from would pass every other test in its file while filing every
      change a person made under "system" in their own history.
- [x] Open decision 2 recorded here. — **settled: no typed payload models.** See the entry above and
      *Decisions taken* below.
- [x] The aggregate id is the task id, consistent with the integer decision taken in ITER18-001 Phase 1.
      — asserted on both event types, including its type, because `field_history.entity_id` is an
      `Integer` and Phase 6 files rows under this value.

**Required Test Coverage:** unit — event construction and payload shape for both types. Integration — each
write leaves exactly one outbox row with the right type, provenance and payload; a rolled-back write leaves
none. No e2e.

**Delivered: 45 unit tests and 21 integration tests.** 23 unit tests for the event classes
(`tests/unit/tasks/test_task_events.py`) and 22 for service publishing and provenance — 13 on
creation, 9 on deletion — across `test_task_service_create.py` and `test_task_service_delete.py`;
15 integration tests in `tests/integration/tasks/test_task_events_integration.py` and 6 surface
tests split between `tests/integration/api/test_task_endpoints.py` and
`tests/integration/mcp/test_task_tools_mcp.py`.

**Decisions taken (Phase 1):**

- **Open decision 2 is settled: task events get no typed payload models.** The dispatch map in
  `core_shared/models/outbox_events.py` exists so integration *workers* can parse **inbound sync**
  payloads — `contact.`, `sync.completed`, `journal_event.*`, `immich_album.`, `journal_review.` —
  and every core domain event is absent from it: `JournalCreated`, `JournalTagAssigned`,
  `ContactCreated`. No worker consumes task events, and the specification's *Tasks and search*
  section says the one consumer that might is to ignore them. A model here would advertise a consumer
  that does not exist. What guards the shape instead is the whole-key unit assertion, which is the
  same guarantee without the implication.
- **`TaskDeleted` is a marker, and `delete_task` still takes no read.** Phase 9 of ITER18-001 recorded
  that this method decides nothing from a read — one owner-scoped statement either removes a row or
  raises — and pinned the absence of a locking read with a test. Carrying the task's text or anchors
  on the event would have needed exactly that read, undoing a decision for the sake of a richer
  history line, so the payload is task id, owner and provenance. `JournalDeleted` carries no title
  either. `user_id` **is** on it, and deliberately: tasks are hard-deleted, so Phase 8's task-scoped
  history read has to answer "is this yours?" for a task with no row left, and this event is the only
  place that answer can come from. That makes this phase's payload choice a load-bearing input to
  Phase 8's discriminator rather than a detail.
- **`TaskCreated` carries no contact ids.** A task may be created with contacts, but whether that
  publishes one event or two is Phase 5's completeness question — the one its criterion phrases as
  "every task write path publishes exactly one event". Smuggling the ids into this payload would have
  answered it here, early and without the tests that decision needs. A unit test pins the absence, so
  Phase 5 finds a deliberate hole rather than an accident.
- **A third local `DomainEvent` base, recorded rather than repeated silently.** The journal and
  contact domains each define an identical copy, and the tasks domain now makes three. Nothing forces
  it — `OutboxEventPublisher` types against the structural `DomainEventProtocol` — and extracting one
  shared base is a genuine improvement. It is not taken here because it would edit three domains in a
  phase whose subject is two event classes, which is precisely the shape calibration rule 7 identifies
  as the expensive kind. The module docstring says so, so the next reader sees a decision rather than
  a copy-paste.
- **`changed_by` is the literal `"ui"` / `"mcp"`, not the acting user's id**, matching every existing
  caller in the journal and contact domains. `user_id` already travels in the payload, so no actor
  information is lost; diverging would make task entries render differently from journal ones in the
  shared feed the activity-history specification asks for.
- **The events are published *last*, after the links.** `create_task` publishes after
  `_link_contacts` rather than straight after the save, following `JournalTagService`'s ordering: the
  event announces a create that finished. A unit test proves the ordering by breaking the link write
  and asserting nothing was published — the kind of claim a comment cannot make.
- **Search isolation is inherited, not asserted here.** `SearchIndexerConsumer` matches
  `_SEARCH_EVENT_TYPES` **exactly** and lists no task type, so `TaskCreated` and `TaskDeleted` are
  acknowledged and ignored the moment they reach the stream. That is true by construction from this
  phase onward; Phase 7 owns pinning it with a test, and this entry records that the property holds in
  the interim rather than leaving it unstated while events are already flowing.
- **The integration tests were mutation-checked before being trusted.** They were written after the
  publishing code rather than before it — the unit tests drove that — so each publish call was removed
  in turn to confirm the suite actually fails without it (8 failures without the create, 5 without the
  delete). A test written green is worth what it can be shown to catch, and "assert nothing was
  published" tests in particular pass just as happily against a service that publishes nothing at all.
- **`DomainEvent.transaction` is inert, and the tests now say so.** The field is part of
  `DomainEventProtocol` and every domain event carries it, but `OutboxEventPublisher` never reads it —
  it inserts on the connection it was constructed with. Three unit tests originally justified
  asserting it with *"same connection as the write, so the two commit or roll back together"*, which
  describes a causal chain that does not exist: they would pass with the publisher bound to a wholly
  separate connection. They now assert protocol conformance and say where the real evidence is. The
  atomicity comes from DI handing the publisher and the repositories the same request connection, and
  it is asserted against a live one.
- **Review found two integration assertions that could not fail**, both since fixed. `occurred_at is
  not None` is guaranteed by a `NOT NULL` column; it now brackets the call and asserts the stored
  timestamp falls inside it, which is what distinguishes the event's clock from projection time.
  And the "no other domain is disturbed" test compared only the count of *foreign* outbox rows, so it
  passed with all task publishing removed — it now asserts the task's own row appeared as well. This
  is the second time in this phase that a test written after its code proved to be worth less than it
  looked; the lesson is not "mutation-check the ones you suspect" but that a green-on-arrival test has
  no evidence behind it until something has been shown to break it.

#### Phase 2: Events — Text Updated and Status Changed ✅ COMPLETE

**Prerequisites:** Phase 1, ITER18-001 Phase 6.
**Estimated diff:** ~140 production → **~560 tracked** (×4)
**Revised before work started (delivery rule 3):** ~130 production → **~950–1,250 tracked**. The ×4 is
the figure Phase 1's own entry concluded was low, and this phase also threads provenance through **two**
entry points, which rule 15 budgets at roughly one behaviour matrix each. It was revised *down* from
Phase 1's actual on the production side, because there is no new module, no DI line and no new
construction site — the events file and the publisher both already exist.
**Actual:** **132 production → 1,366 tracked** (events module 71, service 66, controller 2, MCP 4 —
1,366 test lines, ~130 docs of which most is this entry). **Both halves of the revised estimate held**,
which is the first time in this iteration that has happened: production landed at 132 against ~130, and
tests at 1,366 against a 950–1,250 range — 10% over the top of it, at **×10.3 of production**. The
ratio looks alarming and is not: production is small precisely *because* the shape was already there,
so the ratio measures the denominator shrinking rather than the tests bloating. *Calibration addition:*
a phase that adds a **variant of an existing shape** rather than a new one should estimate its tests
from the **behaviour count** — here, the ways a write can move zero, one or two fields, times three
provenance origins — and its production from the diff alone, because the two stop tracking each other.

**Acceptance Criteria:**

- [x] Event classes and publishing for text updated and status changed. — **one class,
      `TaskUpdated`, carrying `changed_fields`; the plural in this criterion was not followed and the
      divergence is recorded below.** Published from `TaskService.update_task`, which owns both fields,
      and reached from `set_status` by delegation.
- [x] Status-change events carry old and new status in the `changed_fields` shape the history projection
      expects — `[old, new]` after the JSON round trip through Redis. — asserted **twice**: in memory,
      and by reading the payload back out of `outbox_events` in Postgres. The stored form is the one
      that matters, and the assertion is written the way `_rows_from_changed_fields` reads it —
      `isinstance(change, list)`, `len(change) == 2`, then `change[0]` / `change[1]` — because a payload
      shaped any other way does not raise in that helper, it silently projects **no rows at all**.
- [x] Same-unit-of-work publishing and provenance threading as Phase 1. — rollback asserted against a
      real database for both fields, by failing inside a **caller's** unit of work; provenance asserted
      per surface (`ui` from the `PATCH`, `mcp` from both tools) rather than only at the service, whose
      `SYSTEM` default is a silent success.

**Required Test Coverage:** unit — payload shape per type, including the positional `changed_fields` form.
Integration — outbox rows per operation; rollback leaves none. No e2e.

**Delivered: 45 unit tests and 22 integration tests.** 15 unit tests for the event class
(`tests/unit/tasks/test_task_events.py`) and 30 for service publishing and provenance — 15 on the text
path, 15 on the status path — across `test_task_service_update_text.py` and
`test_task_service_set_status.py`; 15 integration tests in
`tests/integration/tasks/test_task_events_integration.py` and 7 surface tests split between
`tests/integration/api/test_task_endpoints.py` and `tests/integration/mcp/test_task_tools_mcp.py`.
No e2e, per this entry and because nothing is user-visible until Phases 6 and 9.

**Decisions taken (Phase 2):**

- **One `TaskUpdated` event, not one type per field — a deliberate divergence from this entry's
  wording.** "Event *classes* … for text updated and status changed" reads as two types, and two types
  would mean a single `PATCH` that rewords a task *and* completes it publishes **two events for one
  write**. That is not a shape this system uses anywhere: `JournalUpdated`, `ContactUpdated`,
  `RouteUpdated` and `GearItemUpdated` are each one event carrying `changed_fields`, and
  `HistoryService._rows_from_changed_fields` already fans that dict out into **one `field_history` row
  per field** — so a user still reads a distinct "text" line and a distinct "status" line, which is the
  whole of what per-field event types would have bought. The alternative invents a per-field event
  convention for tasks alone. **Phase 6 should read this**: its criterion asks for "handlers for
  created, deleted, text updated and status changed", and text-updated and status-changed are one
  handler over the existing generic helper.
- **The payload names only what actually moved.** A caller resending the text a task already has puts no
  `text` key in `changed_fields`, because both surfaces send whole resources and "the field the caller
  mentioned" is not "the field that changed". This is what keeps **Phase 5's completeness criterion**
  — *every task write path publishes exactly one event* — true for this path with no exception
  attached: one write, one event, and a no-op is not a write.
- **`changed_fields` is built as the decisions are made, not by diffing before and after.** The
  branch that decides a text differs is the same branch that records the pair; recovering that from a
  before/after comparison afterwards would be a second implementation of the same rule, free to
  disagree with the first. The old values cost nothing, because the locking read `update_task` already
  performs is the only place they still exist once the row is saved.
- **`set_status` forwards provenance rather than defaulting it.** It publishes nothing itself, so a
  delegation that dropped the two arguments would still change the status, still publish an event, and
  still pass every other test in its file — while filing an AI agent's decision to cancel somebody's
  commitment under "system" in their own history. Pinned by a unit test that fails on exactly that
  mutation, and end to end through the MCP tool.
- **Status is serialised as `TaskStatus.value` at the point the pair is built.** Not a style choice:
  `OutboxEventPublisher` calls `json.dumps` on the payload, which refuses an enum member — so an enum
  here would take the task's own write down with it, inside the user's request.
- **The mutation check found nothing wrong and is recorded anyway.** Phase 1's lesson was that a
  green-on-arrival test has no evidence behind it, so each half was broken in turn: removing the publish
  call fails **35** tests across unit and integration; dropping `source`/`changed_by` at the `PATCH` and
  at both MCP tools fails **exactly the four** provenance tests and nothing else; dropping the
  forwarding inside `set_status` fails **two**. The middle result is the useful one — it says the
  surface tests are testing the surfaces rather than the service behind them.
- **The quality gates found a real leak that the phase created, in a *test* helper.** `committed_task`
  commits rows for real — the concurrency tests need two connections to see one row, which the savepoint
  fixture cannot give them — and swept `tasks` and `journals` afterwards but not `outbox_events`, which
  has no `user_id` to sweep by. That was harmless while `set_status` published nothing. It stopped being
  harmless the moment this phase made it publish: the race tests began committing `TaskUpdated` rows that
  survived into every later test reading the outbox unfiltered, and four of **Phase 1's** tests started
  failing in a combined run while passing file-by-file. The cleanup now deletes the task's own events by
  `aggregate_id`. *Worth recording because the failure had no connection to the code under test* — the
  suites that broke touched neither `update_task` nor its event — and because the same trap is waiting
  for any later phase that makes an already-committed path start publishing.
- **Merging ITER18-001 Phase 8 mid-review put provenance behind a new hop.** That phase landed four
  `*_with_trail` wrappers and repointed the surfaces at them, so the endpoint and both MCP tools no
  longer call `update_task` and `set_status` directly. Git merged the two changes cleanly and produced
  code that could not typecheck — provenance arguments passed to wrappers that did not accept them —
  which **CI caught and the local gates did not**, because the local run predated the merge. The fix is
  the one `create_task_with_trail` had already chosen for itself, in a docstring written before this
  phase existed: forward `source` and `changed_by` rather than swallow them. `retarget_due_journal_with_trail`
  is deliberately left without them, because Phase 3 is what gives a retarget an event to carry them on —
  and **Phase 3 duly added them**, so all four wrappers now forward provenance.
  *The lesson is about the failure mode, not the merge:* a wrapper is the ideal place to lose provenance,
  because doing so is a **silent success** — the task still changes, an event is still published, and the
  only symptom is a person's edit and an assistant's edit becoming indistinguishable in the user's own
  history. Two behavioural tests now pin the forwarding through both wrappers, and were mutation-checked
  against a wrapper that *accepts* both arguments and forwards neither — the exact shape a signature-only
  test would wave through.

#### Phase 3: Events — Due Journal Retargeted ✅ COMPLETE

**Prerequisites:** Phase 1, ITER18-001 Phase 8.
**Estimated diff:** ~140 production → **~560 tracked** (×4)
**Revised before work started (delivery rule 3):** ~110–130 production → **~900–1,200 tracked**. The ×4
is the figure Phases 1 and 2 both overran, and calibration rule 6 budgets ~600 test lines for a single
new event type before the provenance matrices are counted. Production is revised *down* from Phase 1's
actual, for the reason Phase 2's was: no new module, no DI line and no new construction site — one class
in an existing file, one publish call, and four argument lines across the service wrapper and the two
surfaces. Tests are the phase, and they inherit the fixtures Phases 1–2 built (`task_events`,
`committed_task`, `mock_event_publisher`, `published_events`) rather than building their own.

**Shape chosen for criterion 2 (recorded before work started):** **one event carrying the auto-link in
its payload**, not two. A retarget is one write in one unit of work, and two events would announce two
things where one happened; Phase 5's completeness criterion — *every task write path publishes exactly
one event* — would need an exception carved out for this path alone. The payload follows
`TaskUpdated`'s `changed_fields` convention so Phase 7's handler is the existing
`_rows_from_changed_fields` plus a marker row:

```text
{
  "task_id", "user_id",
  "changed_fields": {
      "due_journal_id": (old, new),
      "status":         (old, "not_done"),   # only when the retarget reopened the task
  },
  "auto_linked_journal_id": int,   # the previous due journal, retained as intermediate
  "auto_link_created": bool,       # False when it was already an intermediate link
  "source", "changed_by",
}
```

`auto_link_created` is not redundant with the journal id. `add_intermediate_journal` is idempotent, and
a journal can be both the due anchor and an intermediate link — `attach_intermediate_journal`'s docstring
records that retargeting produces that shape and that nothing cleans it up — so a task retargeted
A→B→A→C finds A already linked. Without the flag, Phase 7 would write "linked journal A" into history a
second time for a link that already existed. **The ordering contract Phase 4 inherits** is the write
order this method already has: the intermediate link first, then the anchor move.

**Actual:** **162 production → 1,580 tests** (events module 97, service 61, controller 2, MCP 2 —
1,580 test lines, plus ~190 docs of which most is this entry). **Production overran the revised range by
~25% and the tests by ~32%.** Both figures include the local review's fixes, which is where a third of
the production overrun came from; the pre-review figures were 141 and 1,513.

The production miss is one place: the event class is 97 lines against a "one class in an existing file"
budget, because it is the first task event that *computes* part of its payload — the reopen rule — and
the rule, the two auto-link keys and the corrected `StrEnum` note each carry their reasoning.

The test miss is the reverse of Phase 2's lesson rather than a repeat of it. This phase adds a **variant
of an existing shape**, so the estimate was made from behaviour count as Phase 2 recommended — and the
count itself was short. It counted the ways a retarget can *succeed* and not the **five** ways it can
decline (no-op, unknown task, unreachable journal, past-dated journal, unacknowledged reopen), each of
which needs its own silence test at the unit level *and* against a real outbox, where the earlier phases
had one or two apiece. *Calibration addition:* count an operation's **refusal paths** alongside its
success paths when estimating a phase that gives it an event. Silence is as much a behaviour as
publication and costs the same per case, and a retarget — which validates a journal, a date, ownership
and an acknowledgement — has more of them than any other write in this domain.

**Acceptance Criteria:**

- [x] Event class and publishing for the due-journal retarget, carrying old and new due journal. —
      `TaskDueJournalRetargeted` in `backend/app/core/tasks/models/events.py`, published from
      `TaskService.retarget_due_journal` **after** the save, carrying the pair as
      `changed_fields["due_journal_id"] = (old, new)` in the positional form
      `_rows_from_changed_fields` indexes. The old value comes from the locking read the method already
      performs — the only place it still exists once the row is saved.
- [x] A retarget publishes both the retarget and the automatic intermediate link in a deterministic
      order; state which shape is chosen. — **one event carrying the auto-link in its payload**, as
      recorded above before work started. Ordering is deterministic by construction while there is one
      event, and the write order this method already has — link first, then anchor — is the contract
      Phase 4 inherits, recorded in the event's docstring rather than only here. The trail is asserted
      end to end: two deferrals read back in order, with each event's "from" being the previous one's
      "to".
- [x] A retarget that also reopens a done task makes the status change visible in the event stream. —
      `changed_fields["status"] = (old, "not_done")`, and **only when the status actually moved**, so an
      ordinary deferral does not write "not done → not done" into the user's history. Asserted for
      *done* and for *cancelled*, at the event, at the service, against the stored JSON, and at both
      surfaces.
- [x] Same-unit-of-work publishing and provenance threading, as Phases 1–2. — rollback asserted against
      a real database by failing inside a **caller's** unit of work, checking all three writes go
      together: the anchor stays, the auto-link is absent and no event survives. Provenance is threaded
      through `retarget_due_journal_with_trail` — the fourth wrapper, and the one ITER18-001 Phase 8
      deliberately left without it — and asserted **per surface** against the stored row.

**Required Test Coverage:** unit — payload including the old/new pair and the reopen case. Integration —
outbox rows and their ordering. No e2e.

**Delivered: 41 unit tests and 25 integration tests.** 19 unit tests for the event class
(`tests/unit/tasks/test_task_events.py`, 38 → 57) and 20 for service publishing, ordering, reopens,
silence and provenance across four new classes in `test_task_service_retarget.py` (52 → 72), plus 2 in
`test_task_service_intermediate_journals.py` for the wrapper (21 → 23); 21 integration tests in
`tests/integration/tasks/test_task_events_integration.py` — six new classes plus one case added to the
existing `TestNoOtherDomainIsDisturbed` (30 → 51) — and 4 surface tests split between
`tests/integration/api/test_task_endpoints.py` and `tests/integration/mcp/test_task_tools_mcp.py`.
**No e2e**, per this entry and because nothing is user-visible until Phases 6 and 9 — a retarget looks
exactly the same on screen as it did before this phase.

**Documentation.** `docs/architecture/domain-architecture.md` listed the tasks domain's events as
"`TaskCreated` and `TaskDeleted`" and said text-updated, status-changed and due-journal-retargeted
"arrive in later phases". That went stale when **Phase 2** shipped `TaskUpdated` and was missed then; it
is corrected here for both phases, and the entry now describes the one-event-per-write shape and the
auto-link keys. *Two lessons:* a phase adding an event type has a documentation obligation this iteration
did not write down until Phase 6's consumer-table criterion — and the search that concluded "no
architecture document names an event type" was a **false negative** taken at face value, which is how
the miss survived the plan as well as Phase 2.

**Decisions taken (Phase 3):**

- **One event, not two — and the auto-link travels in its payload.** Open by the entry's own wording,
  settled before work started and repeated here because it is the decision Phase 4 has to read. Two
  events would announce two things where one write happened, and **Phase 5's completeness criterion** —
  *every task write path publishes exactly one event* — would need an exception carved out for this path
  alone. The auto-link is therefore two payload keys, `auto_linked_journal_id` and `auto_link_created`,
  which Phase 4 removes deliberately when it gives the link its own type.
  **The exception is deferred, not avoided, and the first draft of this entry overstated it.** Phase 4's
  second criterion already requires the retarget-derived link to publish *"the same event type as a
  manual attach"*, so a retarget will publish two events as soon as that phase lands, and the
  completeness rule will need restating then. What this phase actually buys is that the exception
  arrives with the event that justifies it rather than a phase early, with a payload key standing in for
  a type nobody consumes yet. Phase 4's entry has been amended in place to carry the removal, the
  ordering and the completeness restatement — the same thing Phase 2 did to Phase 6, rather than leaving
  the next phase to rediscover it.
- **`auto_link_created` exists because the idempotent add already answers the question.** Nothing ever
  unlinks, so a journal can be both the due anchor and an intermediate link, and a task retargeted
  A→B→A→C finds A already attached the second time it leaves it. `add_intermediate_journal` returns
  which happened and the phase before this one discarded that answer; keeping it is the difference
  between Phase 7 writing "linked A" once and writing it twice. Pinned by a unit test and by an
  integration test that performs the actual A→B→A→C sequence rather than mocking the repository's reply.
- **The event builds its own `changed_fields`, unlike `TaskUpdated`.** That event is *handed* a dict
  because its caller decides field by field what moved. Retargeting decides nothing of the sort — it
  always lands the task not done — so whether that is a *change* follows from the status it started in,
  and putting the rule in the event keeps one definition of it. This is the same shape `TaskCreated`
  has, so it is a choice between two conventions the module already contains rather than a new one.
- **`retarget_due_journal_with_trail` gains provenance, closing ITER18-001 Phase 8's deliberate gap.**
  That phase left the retarget wrapper without `source`/`changed_by` and said why: retargeting published
  nothing, so there was nothing to carry provenance *for*. The parametrised wrapper test that recorded
  the exclusion is now four names rather than three, and the paragraph explaining the absence is gone
  rather than left to read as still true.
- **The mutation check found nothing wrong in the production code and two problems in the tests.**
  Removing the publish call fails **32** tests across unit and integration; making the wrapper accept
  both provenance arguments and forward neither — the exact shape a signature-only test waves through —
  fails **exactly 5** (the wrapper's own behavioural test, two endpoint, two MCP); dropping
  `source`/`changed_by` at both surfaces fails **exactly 4**, the surface tests and nothing else, which
  is the useful result: it says those tests are testing the surfaces rather than the service behind them.
  Hard-coding `auto_link_created=True` fails **exactly 2**, one unit and one integration, so the flag is
  pinned behaviourally rather than only in the payload comparison. The two that initially failed to fail
  — dropping `.value` from the status pair, and swapping the two writes — are the `StrEnum` and ordering
  findings below; both now have a test that catches them.
- **The local review found a false claim this domain has been repeating since Phase 2, and it is now
  corrected in three places.** `TaskStatus` is a **`StrEnum`**, so `json.dumps` serialises the member to
  `"done"` unchanged — the comments in `update_task`, in `TaskUpdated`'s docstring and (initially) in
  this phase's event asserting that an enum "would take the task's own write down with it" were simply
  wrong. Worse, it made a test vacuous: `isinstance(change[0], str)` is true of a `StrEnum` member, and
  the whole-key payload comparison cannot catch one either, because a `StrEnum` compares equal to its
  value. Removing `.value` from the new event left the entire unit suite green. `.value` is still right
  — the payload is a wire format, and a member in it hands an in-process subscriber a domain type where
  a reader coming back through Redis gets a bare string — so the fix was to state *that* reason and to
  assert `type(...) is str`, which does fail against the member. **The lesson is about inherited
  reasoning:** the claim was copied forward twice because it was plausible and already written down, and
  the test that was supposed to guard it had been written to match the wrong explanation.
- **The ordering criterion needed a test, not a docstring.** Both writes are in one transaction, so
  nothing observable depends on the link preceding the anchor move — which is exactly why a refactor
  could have swapped them and handed Phase 4 a different contract than the one it is told to inherit.
  Moving `add_intermediate_journal` after `_save` left every test green until
  `test_the_link_is_written_before_the_anchor_moves` was added. *Worth recording generally:* a contract
  a phase declares **for a later phase** has no natural test, because nothing in the current phase
  consumes it — and is therefore the kind most likely to be documented and unpinned.
- **A journal merge moves a task's anchors and publishes nothing — now Phase 10.**
  `SqlTaskAnchorRepository.repoint_journal_links` rewrites both anchor columns and the intermediate link
  rows when journals are merged (ITER18-002 Phase 3), and the merge's own events are journal-aggregated,
  so no affected task's history mentions it. After Phase 7 a merged task's `field_history` would read
  `due_journal_id: A → B` while the row says C, and older rows would name absorbed journal ids. That is
  correctly *not* a retarget and correctly outside this phase — it is another domain's write path, which
  rule 7 keeps out — so it was **added as a new phase rather than fixed here or folded back into
  ITER18-002 Phase 3**, which is complete and merged. See *Phase 10* for the gap in full, its two open
  decisions, and why it is the one phase in this iteration that has to touch two domains.
  **Worth recording as an estimating lesson:** the "tasks need nine event types" count that shaped this
  iteration enumerated the writes on `TaskService` and missed the one another domain performs on tasks.
  Phase 5's completeness test should be written against the write paths, not against the service's
  method list, or it will pass while this gap is open.
- **Phase 2's `committed_task` trap did not fire, because Phase 2 had already fixed it.** This phase made
  another committed path start publishing — the retarget concurrency test in
  `test_task_service_retarget_integration.py` uses that helper — which is precisely the shape that broke
  four of Phase 1's tests when `set_status` began publishing. The cleanup Phase 2 added, deleting the
  task's own events by `aggregate_id`, covered it with no change needed here. Recorded because it is the
  first time a lesson from an earlier phase in this iteration paid for itself, and because the same trap
  is still waiting for Phases 4 and 5.

#### Phase 4: Events — Journal Linked and Unlinked ✅ COMPLETE

**Prerequisites:** Phase 3, ITER18-001 Phase 10.
**Estimated diff:** ~130 production → **~520 tracked** (×4)
**Actual:** **252 production → 1,759 tests** (events module 189, service 101, controller 4, MCP 4 —
figures include the docstrings each carries, plus ~30 docs outside this entry). **Production ran to
~1.9× the estimate and tests to ~3.4× it**, i.e. the ×4 multiplier was low for the fifth phase
running — the same finding Phases 1–3 each recorded, and the estimate was left unrevised here
against delivery rule 3, which is the process miss worth naming.

Where production went is not the two new classes: it is that this phase is the first to touch
**three** write paths — attach, detach and retarget — and each of the two link-publishing sites
carries the reason it publishes *conditionally*, which is the phase's whole subject. The
`origin` enum is a fourth documented decision. *Calibration addition to Phase 2's:* estimate a
phase that gives an existing operation an event from the number of **write paths that reach the
new type**, not the number of types. Two types cost ~190 lines here; the third publisher cost as
much again in service code and half the test suite.

**Acceptance Criteria:**

- [x] Event classes and publishing for intermediate journal linked and unlinked. —
      `TaskJournalLinked` and `TaskJournalUnlinked` in `backend/app/core/tasks/models/events.py`,
      published from `attach_intermediate_journal` and `detach_intermediate_journal` **only when the
      repository reports a row moved**. Whole-key payload assertions on both, as on the other four
      types, plus a JSON round trip.
- [x] The automatic link created by a retarget publishes the same event type as a manual attach, with
      provenance distinguishing system-derived from user-initiated. **This phase therefore removes the
      two keys Phase 3 put in the retarget payload** — `auto_linked_journal_id` and `auto_link_created`
      — because the fact they carry becomes an event of its own. `auto_link_created` is the one to think
      about: the add is idempotent and a retarget only ever adds a link, never removes one, so a task
      retargeted A→B→A→C leaves A a second time when A is still an intermediate link from the first
      departure. (Links are removable — by `detach_intermediate_journal`, by a merge, by a journal
      delete cascading — but none of those is a retarget.) Publishing a "linked" event for that would
      write the link into history twice, so **the derived event is published only when a row was
      actually written**, which is the same question Phase 3's boolean answers. — done, and both keys
      are gone; **but the distinction is carried by a new payload key, `origin`, not by provenance,
      and that divergence is recorded below.** The A→B→A→C sequence is performed against a real
      database and asserted as the *absence* of a third link row.
- [x] The two events a retarget now publishes go out in a **deterministic order, the link before the
      retarget**, matching the order `TaskService.retarget_due_journal` performs the writes in. Phase 3
      pinned that write order with a unit test precisely so this phase has something to inherit rather
      than a docstring to trust. — inherited, and each event is published **directly behind its own
      write** rather than beside the other's publish call, so the order follows from the code's shape.
      Asserted at the service *and* over the stored rows in `(occurred_at, id)` order, which is the
      order the relay hands them to the stream.
- [x] Same-unit-of-work publishing and provenance threading. — rollback asserted against a real
      database for both attach and detach, by failing inside a **caller's** unit of work: the link row
      and the outbox row go together in both directions. Provenance is threaded through both REST
      endpoints and both MCP tools, which had none before this phase, and asserted per surface against
      the stored row.
- [x] **Phase 5's completeness criterion is amended by this phase, not by Phase 5.** — done; see
      Phase 5's entry, which now reads *"every task write path publishes at least one event, and a
      retarget publishes exactly two"*.

**Required Test Coverage:** unit — payloads and the provenance distinction. Integration — outbox rows for
manual attach/detach and for the retarget-derived link, and their ordering relative to the retarget
event. No e2e.

**Delivered: 53 unit tests and 17 integration tests.** 27 unit tests for the two event classes
(`tests/unit/tasks/test_task_events.py`, 57 → 84), 19 for attach/detach publishing and silence
(`test_task_service_intermediate_journal_links.py`, 29 → 48) and 7 for the retarget-derived link
(`test_task_service_retarget.py`, 51 → 58); 13 integration tests in
`tests/integration/tasks/test_task_events_integration.py` (50 → 63) and 4 surface tests split
between `tests/integration/api/test_task_endpoints.py` and
`tests/integration/mcp/test_task_tools_mcp.py`. **No e2e**, and the absence is a checked fact rather
than an assumption: `grep -rn "intermediate-journals" frontend/src` returns nothing, so no UI reaches
these endpoints and nothing on screen changes. Phase 9 builds the surface that makes any of this
visible.

**Documentation.** `docs/architecture/domain-architecture.md` — the tasks event list, and the
paragraph describing the auto-link payload keys this phase deletes, which now describes the two
events a retarget publishes and how `origin` and `source` split the question between them.

**Decisions taken (Phase 4):**

- **The criterion's "with provenance" was not followed, and this is the divergence.** The derived
  link carries the provenance of the **user action that caused it** — `ui` when a person retargeted
  in the browser, `mcp` when an assistant did — and names its cause in a new payload key,
  `origin: "manual" | "retarget"`. Provenance answers *who acted*; a retarget is something the user
  did, and the retained link is a consequence of their action rather than a background job.
  Stamping it `system` would have one action produce two events disagreeing about who performed it,
  and would tell a person reading their own history that half of what they did was not theirs.
  `SYSTEM` stays what it has always been here: a write no person triggered, such as an integration
  sync. Two tests hold the line — one asserting the derived link carries the caller's actor, one
  asserting the **pair agree** — and the second is the one that catches a "fix" applied to the
  retarget event instead. Same shape as Phase 2's divergence from *"event classes"* plural.
- **`origin` is not `auto_link_created` under another name.** That key answered *"was a row
  written?"*, which this phase answers by publishing an event or not publishing one — the fact
  moved from a payload key to the existence of a row, where a consumer can act on it without
  parsing. `origin` answers *"why does this link exist?"*, which nothing else on the event carries
  and which no other key could be derived from once both causes publish the same type.
- **`origin` has no default, deliberately.** Every other optional argument on these events defaults
  to the safest reading; there is no safe default here, because whichever value were chosen the
  *other* caller would silently publish a lie about why the link exists. A unit test asserts the
  `TypeError`.
- **`TaskJournalUnlinked` carries no `origin`.** An unlink has exactly one cause today — a user
  asking for it — because the other two things that remove a link publish nothing at all: a journal
  **merge** collapsing redundant links (Phase 10) and a journal **delete** cascading, which removes
  the row without anyone acting on the task. A key with one possible value would advertise a case
  that does not exist. Pinned by a whole-key payload assertion rather than left implicit.
- **`event_id` names the journal as well as the task**, unlike the other four types. They are
  *about* the task, so two of a kind are separated by the clock; two links are not, because one task
  can gain several journals — and Phase 6 writes history rows `ON CONFLICT DO NOTHING` over
  `event_id`, so a same-microsecond collision would silently drop one link from a user's history as
  a redelivery of the other. Unreachable today (no write path publishes two link events in one unit
  of work) and cheap to make impossible.
- **Each event is published behind its own write, which is what makes the ordering structural.** The
  alternative — both publishes adjacent after the save — passes the same ordering test today and
  leaves the order resting on two statements a refactor can swap. The consequence is recorded rather
  than smoothed over: a retarget whose `_save` fails has *already* published the link event, and the
  test that used to assert "nothing was published" now asserts exactly `["TaskJournalLinked"]` and
  says why — the link's own write finished, both rows ride the connection the failure rolls back, and
  what the test is really about is that the **anchor** event never precedes the anchor write.
- **Mutation-checked, eleven mutations, all caught.** Removing each of the three publish calls fails
  6, 7 and 10 tests; publishing unconditionally — ignoring the repository's "did a row move?" —
  fails **exactly one** test each for attach and for retarget, which is the pair of silence tests
  doing their job; stamping the derived link `system` fails 4; forcing `origin=manual` fails exactly
  1; swapping the two retarget publishes fails 7 across unit and integration. Dropping
  `source`/`changed_by` at each of the four surfaces fails **exactly the one surface test for it**,
  which is the useful result: it says those tests exercise the surface rather than the service behind
  it. *The harness itself needed a correction worth recording:* the first ordering mutation anchored
  on `"        return saved\n"` and matched the wrong method, failing 82 tests — a mutation that
  fails everything proves nothing, and the number was the only signal that it had not tested what it
  claimed.
- **Phase 2's `committed_task` trap did not fire again**, for the third phase running. The cleanup it
  added — deleting a task's events by `aggregate_id` — covers the new types without change, because
  it matches on the `Task%` prefix rather than an enumerated list. Recorded because Phase 3 predicted
  this phase would meet it.

#### Phase 5: Events — Contact Linked and Unlinked ✅ COMPLETE

**Prerequisites:** Phase 1, ITER18-001 Phase 11.
**Estimated diff:** ~130 production → **~520 tracked** (×4)
**Revised before work started (delivery rule 3):** **~80–110 production → ~700–1,000 tracked**.
Production is revised **down**, which no earlier phase in this group did, and the reason is the shape
chosen below: contact membership joins `TaskCreated` and `TaskUpdated` rather than getting two event
classes of its own, so this phase adds **no new type**. Calibration rule 6's ~600 test lines per type
— the figure that drove the overruns in Phases 1–4, every one of which shipped new classes — does not
apply. What is left is two publish sites, one payload key, one widened docstring and four provenance
arguments. Tests are revised **up** against the ×4, because what remains is the behaviour count Phase 2
recommended estimating from: link and unlink, each against a row that moved, one that did not and a
refusal, times three provenance origins, times four surfaces that pass none today — plus the
completeness test, which is new machinery rather than a variant of an existing assertion.

**Shape chosen for criterion 1 (recorded before work started):** **no new event types. Contact
membership is a field of the task, so it travels in the field vocabulary** — `contact_ids` on
`TaskCreated`, and `changed_fields={"contact:{id}": (None, id)}` / `{(id, None)}` on `TaskUpdated`
for a later link or unlink.

The criterion says *"Event **classes** … for contact linked and unlinked"*, so this is a divergence,
and it is the same one Phase 2 made from *"Event classes … for text updated and status changed"*. The
first draft of this phase's plan did add two classes, and review caught what that produced: a create
with contacts announcing them as a **field** of the task and a link a minute later announcing the same
fact as an **aggregate-level event of its own**. It is one or the other. Reading it as a field costs no
information — `HistoryService._rows_from_changed_fields` fans a `changed_fields` dict into one
`field_history` row per key, so the user still reads a distinct line per person — and it means **Phase 7
needs no contact-link handler at all**, because Phase 6's `TaskUpdated` handler already covers it. That
entry should be amended when this lands, the way Phase 4 amended this one's completeness rule.

**Why this is not what Phase 4 did for journal links**, which *did* get their own types: a journal link
has structure to carry. It has an `origin`, because two different writes cause it, and it is half of the
ordered pair a retarget publishes. A contact link has neither. The specification calls it *"a plain
reference"* with no relationship type, role or attendance status, and it has exactly one cause — a user
asking for it — because a create announces its own contacts and a contact delete cascades without
anybody acting on the task. There is nothing a dedicated type would carry that `changed_fields` does
not. The keys are `contact:{id}` rather than a shared `"contacts"`, following the collection prefixes
`journal_write_service.py` already uses (`plan:doc`, `abseil:pitch`), because Phase 6 writes history
`ON CONFLICT (event_id, entity_type, entity_id, field_name) DO NOTHING` and a shared field name would
collapse two people into one row.

**This also settles the hole Phase 1 left.** `TaskCreated` gains `contact_ids` — the ids for which a
link row was actually written, in order. Phase 4's amended rule forces a create to publish exactly one
event; with contacts as a field, that event should name them, or a task created with Alice and later
unlinked from her puts an "unlinked" line in the user's history with no "linked" line before it.

**Actual:** **226 production insertions (201 net) → 2,082 test lines** (events module 116, service 102,
controller 4, MCP 4 — figures include the docstrings each carries; 1,363 lines added to five existing
test files and a 719-line new one, plus ~150 docs of which most is this entry). **Both halves of the
revised estimate overran — production by ~2×, tests by ~2×** — and the two misses have different
causes, neither of which is the one the earlier phases recorded.

Production is not the publishing. The behaviour is two `if` statements and a shared six-line helper;
what ran to 226 lines is **prose**, because this phase's whole content is a *decision* rather than a
mechanism, and this repo documents why rather than what. The module docstring had to explain why
contact membership is a field, `TaskUpdated`'s had to be widened from two kinds of change to three,
`contact_field_name` carries the dedup argument for its own existence, and `TaskCreated`'s explains
why its new argument has no default. *Calibration addition:* a phase whose deliverable is a
**convention** rather than a component should budget its production line count from the number of
places that convention has to be explained, not from the number of statements that implement it.
Rule 7's "expensive shape" is about editing many domains; this is its cousin — editing one domain's
vocabulary.

The test miss is one file. The completeness test came to **719 lines against a budget of "new
machinery"** with no number attached, which is the estimating error rather than the writing: an
inventory of eleven write paths needs eleven arrangements and eleven actions, and the port-coverage
guard needs its own tests because it is itself a mechanism that can be wrong. It is ~35% of the
phase's test lines and covers a rule the previous four phases each *stated* and none *checked*.

**Acceptance Criteria:**

- [x] Event classes and publishing for contact linked and unlinked. — **no new classes, and that is
      this phase's recorded divergence.** Contact membership is a field of the task, so it travels
      in `TaskUpdated`'s `changed_fields` as `{"contact:{id}": (None, id)}` for a link and
      `{(id, None)}` for an unlink, published from `TaskService.link_contact` and `unlink_contact`
      **only when the repository reports a row moved**. See the shape recorded above and *Decisions
      taken* below. Whole-key payload assertions on both directions, plus a JSON round trip, plus
      the stored form read back out of `outbox_events`.
- [x] Same-unit-of-work publishing and provenance threading. — rollback asserted against a real
      database in **both directions** by failing inside a **caller's** unit of work: a rolled-back
      link leaves neither the `task_contacts` row nor the event, and a rolled-back unlink leaves the
      row *and* no event. Provenance is threaded through both REST endpoints and both MCP tools,
      which had none before this phase, and asserted per surface against the stored row.
- [x] With this phase the specification's full event set is published. — every fact the
      specification names is now announced, and the completeness inventory names them all. The two
      things outside it are unchanged: a retarget publishes two, and the journal merge re-point
      publishes nothing, which is **Phase 10** and is now asserted **positively** rather than merely
      absent.
- [x] The completeness rule, as Phase 4 restated it. — `TestEveryWritePathPublishes` runs each of
      **eleven** write paths against a real outbox and compares the facts it published; a companion
      class checks that no path but the retarget published more than one, per path and against what
      was **actually** published rather than against a declared list.

**Required Test Coverage:** unit — payloads. Integration — outbox rows per operation; a completeness test
asserting every task write path publishes at least one event, with the retarget's two named as the one
exception. **Write the completeness test against the write paths rather than against `TaskService`'s
method list** — the merge re-point (Phase 10) is a task write performed from the journal domain, and a
test enumerating service methods would pass while that gap is open, which is how it went unnoticed until
ITER18-003 Phase 3's review. It is legitimate for this phase's test to record the merge as a **known,
named exclusion**; it is not legitimate for it to be invisible. No e2e.

**Delivered: 34 unit tests and 69 integration tests.** 14 unit tests in
`tests/unit/tasks/test_task_events.py` (7 in a new `TestTaskUpdatedCarriesContactMembership`, 4 on
`TaskCreated`'s new `contact_ids`, 3 round-trip cases), 17 in
`test_task_service_contact_links.py` across three new classes — announcement, silence and provenance
— and 3 in `test_task_service_create.py`, one of which replaces the test that pinned the absence
Phase 1 left. 23 integration tests added to `tests/integration/tasks/test_task_events_integration.py`
(63 → 86), **42 in the new
`tests/integration/tasks/test_task_event_completeness_integration.py`**, and 4 surface tests split
between `tests/integration/api/test_task_endpoints.py` and
`tests/integration/mcp/test_task_tools_mcp.py`.

**No e2e**, and the absence is a checked fact rather than an assumption, as Phase 4 established:
`grep -rn "relationships/contacts" frontend/src` returns nothing and no task API client exists, so
no UI reaches these endpoints and nothing on screen changes. Phase 9 builds the surface.

**Documentation.** `docs/architecture/domain-architecture.md` — the `TaskUpdated` paragraph now
covers three kinds of change rather than two, with the `contact:{id}` key and the reason it names the
contact; a new paragraph records why contact links get no type of their own while journal links do;
and the completeness rule and its single named exclusion are described where a reader meets the event
list rather than only in a test file.

**Decisions taken (Phase 5):**

- **No new event types, which diverges from criterion 1's "event classes" — the second time this
  iteration has made that divergence, and the first time review caught the alternative first.** The
  original plan for this phase *did* add `TaskContactLinked` and `TaskContactUnlinked`, alongside
  putting `contact_ids` on `TaskCreated`. Review rejected it on a point neither the plan nor the
  criterion had noticed: that combination makes contact membership a **field** of the task when the
  task is created and an **aggregate-level event of its own** a minute later. It is one or the
  other. Reading it as a field loses nothing — `_rows_from_changed_fields` fans a `changed_fields`
  dict out into one `field_history` row per key, so the user still reads a line per person — and it
  removes two classes, two handlers and a vocabulary. *The lesson is about where the inconsistency
  was visible:* both halves were individually defensible and the plan argued each on its own merits;
  only reading them side by side showed they disagreed. A plan that settles a modelling question in
  one section and applies a different answer in another will not fail any test.
- **Why journal links keep their own types and contact links do not.** Not inconsistency by
  another name: a journal link has structure to carry — an `origin`, because two writes cause the
  same fact, and a place in the ordered pair a retarget publishes. A contact link has neither. The
  specification calls it *"a plain reference"* with no relationship type, role or attendance status,
  and it has one cause, because a create announces its own contacts and a contact delete cascades
  without anyone acting on the task. The test that states this directly is
  `test_the_payload_says_nothing_about_a_role_or_a_relationship`, so the next person to consider
  adding a role key meets the sentence rather than a diff.
- **The key names the contact — `contact:{id}` — rather than a shared `"contacts"` field**, and it
  is built by `contact_field_name()` rather than an f-string at the call sites. Phase 6 writes
  history `ON CONFLICT (event_id, entity_type, entity_id, field_name) DO NOTHING`, so two people
  under one field name would collide on all four columns and one would be discarded as a redelivery
  of the other — a person silently missing from a task's history. The function exists because the
  projection will have to *recognise* the format that the service *builds*, and a format living in
  two places is one that can drift. Mutation-checked: collapsing it to `"contacts"` fails three
  tests.
- **`TaskCreated` gains `contact_ids`, and it has no default.** This settles the hole Phase 1 left
  deliberately. Phase 4's amended rule forces a create to publish exactly one event, and with
  contacts as a field that event should name them — otherwise a task created with Sarah and later
  unlinked from her puts a "removed Sarah" line in the history with no "added Sarah" line before it.
  The argument is **required** for the reason `TaskJournalLinked.origin` is: there is no safe
  default, because `[]` is right for the ordinary create and a lie for the one that named people,
  and the failure would be silent. The value is `_link_contacts`' return — the ids a row was written
  for — not the request's list; the two coincide on a create, which is exactly why taking the
  written set costs nothing.
- **Phase 7 loses a handler and Phase 6 gains work, and both entries are amended below** — the way
  Phase 4 amended this one's completeness rule. Phase 7's criterion asks for handlers for
  *"retarget, journal linked/unlinked and contact linked/unlinked"*; contact links now need **none**,
  because Phase 6's `TaskUpdated` handler covers them over the existing `_rows_from_changed_fields`.
  What moved rather than vanished is on Phase 6: its `TaskUpdated` handler inherits the
  `contact:{id}` keys for free but owes them a test, and its **`TaskCreated` handler owes real
  work** — `contact_ids` is a list rather than an `(old, new)` pair, so the generic helper cannot
  fan it out and the handler must emit a row per contact itself. Missing that would recreate exactly
  the asymmetry this phase's payload decision exists to prevent: a task created with somebody
  showing no addition, and a later unlink showing a removal with nothing before it. *Recorded here
  as well as there because the risk is that a later phase reads only its own entry.*
- **The completeness test is anchored to the repository ports, not to `TaskService`.** Every
  mutating method on `TaskRepository` and `TaskAnchorRepository` must be classified — reached by a
  covered path, listed as a read, or named as an exclusion — so a new port method fails the suite
  until somebody says which it is. Reads are **listed** rather than inferred from the name, so a
  method called `find_and_touch` cannot classify itself as harmless, and a second test checks the
  reverse direction so a rename leaves a stale entry rather than a silent hole. The merge re-point is
  the one exclusion, and it is asserted **positively**: the test performs a real re-point, checks the
  task's due anchor actually moved, and checks its history does not know. That will fail when Phase
  10 fixes it, which a comment would not have.
- **The mutation check found a test that could not fail, and the fix reshaped the file.** Eleven
  mutations were run. Ten behaved: removing the link publish fails 20 tests and the unlink publish
  12; publishing unconditionally fails **exactly the two silence tests** each; reversing the pair
  fails 4; dropping `contact_ids` fails 3; collapsing the field name fails 3; and dropping
  `source`/`changed_by` at each of the four surfaces fails **exactly the one surface test for it** —
  the useful result, because it says those tests exercise the surface rather than the service behind
  it. The eleventh finding was in the harness's subject: `test_no_path_is_silent` compared *every*
  event a task had ever published, and almost every scenario has to create a task before it can act
  on one — so "this path published something" was true of ten paths the moment `create_task` worked.
  Removing a publish call left it green. `WritePath` was split into `seed` and `act` with the facts
  recorded between them, so `expects` is now the **operation's own** output; after the change the
  same mutation fails it. *This is the third phase running in which a test written after its code
  proved to be worth less than it looked, and the first in which the weak test was in the new
  machinery rather than in what it tested.*
- **A separate file for the completeness test**, rather than a class in
  `test_task_events_integration.py` as the plan said. That file asks "what did *this* operation
  publish?" one operation at a time and is 2,000 lines; this one asks "is anything unaccounted for?"
  across all of them, and the inventory is its subject. Burying it is how it would stop being read.

#### Phase 6: History Projection — Lifecycle Events ✅ COMPLETE

**Prerequisites:** Phases 1–2.
**Estimated diff:** ~150 production → **~600 tracked** (×4), plus the amendment below — **~150
production → ~750 tracked**.

**Actual:** **168 production insertions (154 net) → ~1,025 test lines** (342 in
`test_history_service.py`, 68 in the consumer's unit test, 21 in the repository's, 5 in the
completeness inventory, and two new files of 462 and 106). **Production landed on the revised
estimate; tests overran it by ~37%.** The production figure is the useful result: three handlers
came to ~100 lines of which the behaviour is about fifteen, and the rest is why — which is Phase 5's
calibration addition holding for a second phase running (*a phase whose deliverable is a convention
budgets its line count from the number of places that convention has to be explained*). The test
overrun has two named causes rather than an estimating error: the end-to-end file bought a
**seventh** test the criteria did not ask for — a retarget being filtered out rather than
dead-lettered, which is the only positive statement anywhere that Phase 7's gap is a decision — and
two unrelated defects each arrived with tests of their own (see *Decisions taken*). Subtracting both,
the phase came in at ~800.

**Acceptance Criteria:**

- [x] `HistoryService._HANDLERS` gains handlers for created, deleted, text updated and status changed,
      mapping each to `field_history` rows under a task entity type, with marker field names consistent
      with the journal and contact conventions. **That is three handlers, not four:** Phase 2 shipped
      text and status as one `TaskUpdated` carrying `changed_fields`, so both are covered by a single
      handler over the existing `_rows_from_changed_fields`, which already produces one row per changed
      field. See *Decisions taken (Phase 2)*.
      **Delivered as three handlers on a `"task"` entity type**, keyed on the task id, with the
      **journal** marker convention (`__created__` carrying the text, `__deleted__` carrying
      nothing) rather than the contact one — see *Decisions taken* for why the two conventions
      exist and which a task belongs to.
- [x] **Both of those handlers inherited work from Phase 5, which this criterion predates.** That
      phase made contact membership a *field* of the task rather than an event type, so:
      **(a)** the `TaskUpdated` handler now also receives `contact:{id}` keys, and
      `_rows_from_changed_fields` projects them with no change — an id in `old_value`/`new_value` and
      the absent side `None`, the shape `JournalTagAssigned` already produces. What is owed is a
      **test** that a link and an unlink each land one row, under distinct field names, the right way
      round; and **(b)** `TaskCreated` now carries `contact_ids`, which is a *list*, not a
      `(old, new)` pair, so the generic helper cannot fan it out — the create handler has to emit one
      marker row per contact itself, under the same `contact_field_name()` the service builds, or a
      task created with people will show none of them in its history while a later unlink shows a
      removal with no matching addition. That is the exact asymmetry Phase 5's payload decision
      existed to prevent, and it is this phase that has to finish it.
      **Add ~1 handler-branch of production and ~150 test lines to this phase's estimate for the two.**
      **Both delivered**, and the estimate was right about their shape: (a) cost no production at
      all, and (b) cost the loop and its explanation. The create fans `contact_ids` out through the
      **same `contact_field_name()` the service builds with**, imported rather than re-spelt, so the
      format cannot drift between the two halves that have to agree about it.
- [x] `HistoryProjectionConsumer` subscribes to the task event patterns; writes stay idempotent
      (`ON CONFLICT DO NOTHING` on `(event_id, entity_type, entity_id, field_name)`), so stream redelivery
      is safe. — three types, not six: the retarget and journal-link types are **deliberately
      unsubscribed** until Phase 7, asserted in both directions (no subscribed type without a
      handler, no deferred type with one) and end to end. Idempotency is asserted by replaying the
      **whole stream** through the consumer, which is what a restart or an `XAUTOCLAIM` does.
- [x] Row `created_at` comes from `event.occurred_at`, not projection time. — **and it did not,
      before this phase.** Asserting it found a live defect in the shared projection; see *Decisions
      taken*.
- [x] If ITER18-001 Phase 1 chose a UUID primary key, this phase also migrates `field_history.entity_id`
      off `Integer` — a shared table — and its estimate rises accordingly. With the integer default, no
      migration is needed. — **`tasks.id` is `sa.Integer` (migration `0105`), so no migration.**
- [x] The consumer table in `docs/architecture/integration-architecture.md` is updated.

**Required Test Coverage:** unit — projected rows per event type and that an unknown type projects to none.
Integration — publish → relay → projection per type, asserting idempotency on redelivery. No e2e.

**Delivered: 19 unit tests and 7 integration tests.** 17 unit tests in
`tests/unit/history/test_history_service.py` across `TestTaskCreated`, `TestTaskUpdated`,
`TestTaskDeleted` and `TestTaskEventsThisPhaseDoesNotProject`, 2 in
`test_field_history_repository.py`, and 4 rewritten or added in the consumer's unit test. The
integration file is new: `tests/integration/infrastructure/events/test_task_history_projection_e2e.py`,
mirroring the journal one over a real `TaskService`.

**No e2e**, and as in Phases 4 and 5 the absence is checked rather than assumed: no UI reaches
these endpoints and none renders task history. Phase 9 builds the surface.

**Documentation.** `docs/architecture/integration-architecture.md` — the consumer table row names
tasks and records which three types are subscribed and why the other three are not.
`docs/architecture/domain-architecture.md` — the paragraph that used to say *"no consumer group
subscribes to a task event"* now describes where task events land in history, and keeps the
statement for the consumers where it is still true (permanently, for the search indexer).

**Decisions taken (Phase 6):**

- **The journal marker convention, not the contact one.** Journals write `__created__`/`__deleted__`
  and contacts write `field_name="status"` with `"created"`/`"deleted"` as the value — two
  conventions in one table, and this phase had to pick. A task follows the journal: both are
  top-level aggregates keyed by their own integer id, while the contact shape exists because contact
  history spreads across a family of sub-entity rows (`contact_method`, `contact_note`, …) that need
  a *per-row* status. A task has no sub-entities. `__created__` carries the task's **text** as the
  journal's carries its title, so the first line of a task's history says what the task was.
- **The create marker does not itemise the payload — contacts are the one exception, and the reason
  is asymmetry rather than importance.** `TaskCreated` also carries the status and both anchors, and
  none of them is projected. A later status move and a later retarget each publish a self-describing
  `(old, new)` pair, so neither needs an opening value to read correctly; a contact **unlink**
  publishes `(id, None)`, which reads as a removal with nothing before it unless the create named the
  person. That is the whole test for whether a field belongs in a create marker, and it is worth
  stating because "the payload has it, so project it" would have produced three more rows per task
  and one of them (the due journal) would then disagree with the retarget rows above it.
- **Asserting `created_at` found a real defect, which is why the criterion is worth having.**
  `outbox_events.occurred_at` is a `timestamp` **without** time zone, so the offset is already gone
  when the relay serialises the row; the projection then bound that naive value into
  `field_history.created_at`, a `timestamptz`, and PostgreSQL resolved it against the *database
  session's* timezone — **ten hours** on the workspace this was written in. Every history row this
  system has written since ITER12 carries that shift wherever the session is not UTC, journals and
  contacts included, and nothing caught it because every existing assertion compares a row against
  another value that travelled the same path. The fix is one branch in
  `SqlFieldHistoryRepository._coerce_created_at` — a naive value is read as UTC, which is what every
  producer in this system stamps — rather than a migration of the outbox column, because the
  ambiguity only matters at the one place a naive value meets a `timestamptz`. *The lesson is about
  the assertion, not the bug:* a test comparing a projected timestamp to the source it was derived
  from is only meaningful if one of the two is anchored in UTC, which is the same trap as comparing
  wall clocks.
- **A pre-existing red test on the base branch, fixed here.** ITER18-001 Phase 14 added
  `TaskRepository.find_upcoming_tasks` on a branch parallel to the one that added Phase 5's port
  inventory, so the merge into `main` left it neither listed as a read nor covered by a write path
  and `test_every_port_method_is_a_read_or_a_classified_write` failing. It is classified as a read.
  This is the guard doing exactly what Phase 5 built it for — *a new port method fails the suite
  until somebody says which kind it is* — and the failure mode worth recording is that the two
  branches were individually green.
- **The relay/project/replay helpers moved to a shared `projection_harness.py`** rather than being
  copied into the new file. Both end-to-end tests drive the same three-step chain, and a second copy
  is a second place for "how the projection is exercised" to drift from the consumer it is
  exercising. The journal file lost ~120 lines and gained an import; one of its tests had inlined
  the engine patch a fourth time and now uses the helper too.
- **Mutation-checked, four ways.** Reversing the create's contact direction fails 2 tests;
  collapsing `contact:{id}` to a shared `"contacts"` field fails 3 — including the one that exists
  to say *why* the key names the contact, since the two rows collide on all four dedup columns;
  dropping the event-time stamp fails 7 across three domains; and unsubscribing the task types fails
  9, which is the "both halves move together" claim tested rather than asserted.

#### Phase 7: History Projection — Retarget and Link Events, and Search Isolation

**Prerequisites:** Phases 3–6.
**Estimated diff:** ~140 production → **~560 tracked** (×4)

**Acceptance Criteria:**

- [ ] Handlers for retarget and journal linked/unlinked, producing rows that read as a trail (which
      journal, in which role, when). **That is two handlers, not four, and the contact half is gone
      entirely — amended by Phase 5, which delivered it.** This criterion originally read "…and
      contact linked/unlinked". Phase 5 made contact membership a **field** of the task rather than
      an event type of its own: a link publishes `TaskUpdated` carrying
      `changed_fields = {"contact:{id}": (None, id)}`, so Phase 6's `TaskUpdated` handler already
      covers it over the existing `_rows_from_changed_fields`. What this phase still owes the contact
      case is a **test**, not a handler — that a link and an unlink project one `field_history` row
      each, under distinct field names, in the right direction. See *Decisions taken (Phase 5)*.
      **Amended by Phase 6, which delivered that too:** the contact case is tested at both levels
      there (`TestTaskUpdated` for the mapping, `test_a_link_and_an_unlink_project_the_pair_opposite_ways_round`
      end to end), so this phase owes it nothing at all. What Phase 6 leaves behind for this one is
      **three assertions that must be deleted or inverted rather than merely satisfied**:
      `TestTaskEventsThisPhaseDoesNotProject`, `test_the_retarget_and_link_events_are_not_subscribed_yet`
      and `test_no_handler_exists_for_an_unsubscribed_task_type` all state the gap positively, and
      `test_a_retarget_is_filtered_out_rather_than_dead_lettered` asserts it end to end. They are
      written to fail the moment a handler and its subscription arrive, which is the point.
- [ ] The **search indexer ignores task events**: no tasks index, no task document, no task event
      dead-lettering in the `search-indexer` group, and global search never returns a task. This holds by
      construction because the consumer only sees subscribed patterns — this phase **pins it with a test**
      so a future pattern change cannot silently start indexing tasks.
- [ ] With this phase every published task event has a projection; none is written and then unread.
      **Phase 10 adds a type after this one**, so it carries its own handler rather than relying on this
      criterion having closed the set permanently — and this phase should assert the invariant in a form
      that *fails* for an unhandled task type, so the next one to arrive cannot land unprojected.

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

#### Phase 10: Events — Anchors Re-pointed by a Journal Merge

**Prerequisites:** Phases 4 and 7, ITER18-002 Phase 3 (complete).
**Estimated diff:** ~200 production → **~1,000–1,400 tracked** — above the 500-line standard and flagged
under delivery rule 3, for the reasons under *Why this is its own phase* below.

**Added during Phase 3**, whose local review surfaced it. It is a new phase rather than an amendment to
ITER18-002 Phase 3 because that phase is complete and merged: a shipped phase's record is not edited to
absorb work found later, and rule 9 means the merge must keep working exactly as it does until this
lands.

**The gap.** `JournalMergeService.merge_journals` opens with
`task_anchor_repo.repoint_journal_links(source, target)`
(`backend/app/core/journal/services/journal_merge_service.py:143`), which is four set operations over
the task tables: it collapses duplicate intermediate links, re-points the surviving ones,
re-points **both anchors** — `creating_journal_id` as well as `due_journal_id` — and drops the links a
moved anchor has made redundant. **None of it publishes anything task-scoped.** The merge does publish,
but `JournalUpdated` on the survivor and `JournalDeleted` on the absorbed journal, both aggregated under
a *journal* id, so Phase 7's projection files them against the journal entity and the affected tasks'
own histories never mention the change.

Three consequences, none of them visible until Phases 6–7 make task history readable:

- A merged task's `field_history` reads `due_journal_id: A → B` from an earlier retarget while the row
  says C, and nothing in between explains the jump.
- Rows written before the merge name **absorbed journal ids**, which no longer resolve to a journal.
- Deleted intermediate links leave no "unlinked" row, so a task's trail loses a journal it really did
  pass through with no record of the loss. Phase 4's event type is the one that should have covered it.

It also touches the **one field the specification calls immutable** — *"the creating journal is set once
and never changes"*. A merge is the sole legitimate exception, which is exactly the kind of exception a
history exists to record.

**Acceptance Criteria:**

- [ ] A journal merge publishes a task-scoped event **per affected task**, aggregated under the task id,
      recording which anchors moved, which intermediate links moved, and which were dropped as duplicate
      or redundant. A merge touching no task publishes nothing.
- [ ] The event is **not** `TaskDueJournalRetargeted`. A merge is not a retarget: it does not force the
      status to *not done*, it can move the **creating** anchor, and it can *delete* links. Reusing that
      type would make a user's history claim they deferred a task they never touched.
- [ ] Published **inside the merge's existing unit of work**, so a merge that fails leaves no task event,
      and the events go out in a deterministic order relative to the merge's own `JournalUpdated` and
      `JournalDeleted`.
- [ ] Provenance reaches the event from the merge's caller, so a merge performed in the UI and one
      performed over MCP are distinguishable on the affected tasks. **`JournalMergeService.merge_journals`
      does not currently take `source`/`changed_by`** — threading them through it and both merge surfaces
      is part of this phase, and is the larger half of its production cost.
- [ ] `HistoryService` projects the event into `field_history` under the task entity type, reusing the
      handlers Phases 6–7 built rather than adding a parallel shape. A row whose value names an absorbed
      journal is left as it is: rewriting history to point at the survivor would be editing the record of
      what happened.
- [ ] Whichever design is chosen for open decision 4, **the journal domain does not construct task
      events.**

**Why this is its own phase, and why it is oversized.** It is the only phase in this iteration that must
touch **two domains** — the thing calibration rule 7 singles out as the expensive kind, having measured
ITER17-004 P2's 5.8× overrun on exactly that shape. It is unavoidable here: the write lives in the journal
domain's merge and the event belongs to the task domain. What the phase *can* do is keep the seam to one
call, which is what open decision 4 is about. The estimate is raised accordingly rather than written down
to 500 and discovered later, per delivery rule 3.

**Open decisions:**

4. **Where the event is published from.** Either (a) `repoint_journal_links` returns what it moved and a
   **task-domain** service method publishes, with `JournalMergeService` calling that method instead of the
   repository — one new seam, and task events stay authored by the task domain; or (b) the merge service
   publishes directly from a returned summary, which is fewer moving parts but puts one domain's service
   in charge of another's events. (a) matches the ports-and-adapters stance the domain architecture
   document takes and is the default unless (b) turns out materially smaller.
5. **One event per affected task, or one event carrying every affected task.** Per-task is the shape
   `field_history` wants — `entity_id` is a task id, and Phase 6 aggregates under it — but a merge
   absorbing a heavily-linked journal would publish a row per task in one unit of work. Per-task is the
   default; if a batch shape is chosen instead, the projection has to fan it out and that cost moves to
   Phase 7's handler.

**Required Test Coverage:** unit — the payload for each way a merge can move a task (due anchor only,
creating anchor only, both, intermediate link moved, duplicate collapsed, redundant link dropped), and
that a merge affecting no task produces none. Integration — merge → outbox rows per affected task with
the right provenance; publish → relay → projection with idempotency on redelivery; a merge that fails
leaves no task event; the `search-indexer` group still ignores the new type. **E2E:** none — this is a
record of something the merge already does, and the merge's own e2e coverage does not change.

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
