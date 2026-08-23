# Database Design - Personal CRM & Journal System

This document outlines the database approach and initial schema for the Personal CRM & Journal System. The design will evolve through agile iterations as features are implemented.

## PostgreSQL Database Approach

### Design Philosophy
- **Iterative Schema Development**: Start with core tables, expand as features are built
- **PostgreSQL Features**: Leverage JSON columns, full-text search, and advanced indexing
- **Explicit SQL**: Use SQLAlchemy Core with readable SQL queries
- **Migration-Driven**: Schema changes through Alembic migrations

### Initial Core Tables (Iteration 1)

#### Contacts Table
```sql
CREATE TABLE contacts (
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100),
    middle_name VARCHAR(100),
    nick_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Contact Methods Table
```sql
CREATE TABLE contact_methods (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    method_type VARCHAR(20) NOT NULL CHECK (method_type IN ('email', 'phone')),
    value TEXT NOT NULL,
    label VARCHAR(50), -- e.g., 'work', 'home', 'mobile'
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(contact_id, method_type, is_primary) WHERE is_primary = TRUE
);
```

**Note:** In the application layer, `method_type` is represented as a Python enum (`MethodType.EMAIL`, `MethodType.PHONE`) for type safety, but stored as strings in the database.

#### Contact Addresses Table
```sql
CREATE TABLE contact_addresses (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    label VARCHAR(50), -- e.g., 'home', 'work', 'billing'
    street_line_1 VARCHAR(255) NOT NULL,
    street_line_2 VARCHAR(255),
    locality VARCHAR(100), -- city/town
    region VARCHAR(100), -- state/province/region
    postal_code VARCHAR(20),
    country_code VARCHAR(2) NOT NULL, -- ISO 3166-1 alpha-2
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(contact_id, is_primary) WHERE is_primary = TRUE
);
```

#### Contact Notes Table
```sql
CREATE TABLE contact_notes (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Tags Table
```sql
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
    color VARCHAR(7), -- Hex color code
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT tag_name_format CHECK (name ~ '^[a-zA-Z0-9_&-]+$')
);
```

#### Contact Tags Junction Table
```sql
CREATE TABLE contact_tags (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(contact_id, tag_id)
);
```

#### Field History Table (shared, entity-agnostic)

Field-level activity history is recorded in a single entity-agnostic `field_history`
table shared by both the contacts and journals domains (introduced as
`contact_field_history` and generalised/renamed to `field_history` in migration
`0087` — see [Iteration 12](../tasks/iteration-12-activity-history.md)). Every row
records a single field change to some entity, identified by an
`(entity_type, entity_id)` pair, with provenance (`source`) and an optional
originating `event_id`.

```sql
CREATE TABLE field_history (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL, -- 'contact', 'contact_method', 'journal', 'route', 'gear_item', 'task', ...
    entity_id INTEGER NOT NULL,
    field_name VARCHAR(100) NOT NULL, -- field that changed; marker fields for create/delete/type changes
    old_value TEXT,
    new_value TEXT,
    changed_by VARCHAR(100), -- user/agent identifier
    source VARCHAR(50) NOT NULL DEFAULT 'system', -- Provenance: ui, mcp, google_contacts, google_calendar, strava, immich, summary_regeneration, system
    event_id VARCHAR, -- originating domain event id; NULL for the synchronous contact dual-write
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- set from event.occurred_at by the projection
    user_id VARCHAR(50) -- owner of the entity; TASK ROWS ONLY (migration 0107)
);

-- Idempotency for the event-driven history projection: re-delivered events never
-- duplicate rows. NULL event_ids are treated as distinct by PostgreSQL, so the
-- synchronous contact dual-write (event_id = NULL) is never deduplicated.
CREATE UNIQUE INDEX ux_field_history_event_dedup
    ON field_history (event_id, entity_type, entity_id, field_name);

-- Added with user_id (0107): the owner lookup and the 'task' aggregation
-- predicate both filter on this pair, as do the journal and contact aggregate
-- reads, which previously had no index for it.
CREATE INDEX idx_field_history_entity ON field_history (entity_type, entity_id);
```

**`user_id` is deliberately half-populated, and the reason is deletion.** Every
history read authorises the same way — load the aggregate, compare `user_id` —
and that works for journals and contacts because neither is ever hard-deleted.
**A task is.** `TaskService.delete_task` removes the row while the `TaskDeleted`
event projects a `__deleted__` marker, so a task-scoped read has to answer *"is
this yours?"* with nothing left to load. The owner therefore rides on the row,
stamped by the projection from the event payload (every task event carries
`user_id`) rather than from the `tasks` table, which may already be gone when
the projection runs. Journal and contact rows carry NULL here and need nothing:
stamping them would imply a check nothing performs. `HistoryService._owner_for`
derives it from the entity type in one place, so a future task event type cannot
land with unowned rows. Not to be confused with `changed_by`, which records who
*acted* — an assistant editing your task writes `changed_by = 'mcp'` on a row
that is still yours.

Historic rows are repaired by `TaskHistoryBackfill`, which runs once at
application start. It fills `user_id` on task rows written before the column
existed **and** re-projects task events the `history-projection` group
acknowledged before its patterns matched them (ITER18-003 Phases 6–7 widened
those patterns, but a consumer group sees each message only once, so events
published before the deploy are never redelivered). Both halves read
`outbox_events`, which retains every event forever. It is idempotent and bounded
by an anti-join, so a repaired database pays one indexed query per start.

Reads are aggregated per root entity via a pluggable aggregation strategy
(`HistoryAggregationStrategy`): the `contact` strategy resolves the contact plus all
its related sub-entities; a `journal` strategy is added in ITER12-002 and a
`task` strategy in ITER18-003 Phase 8. The `task` predicate deliberately does
**not** join to `tasks` — that join would silently empty a deleted task's feed,
which is the one thing this surface exists to serve.

On contact merge (ITER13-004), `FieldHistoryRepository.repoint_entity_history` moves the
source contact's top-level (`entity_type='contact'`) rows onto the survivor so the unified
record carries both contacts' audit trail. It is a single copy-then-delete statement that
respects `ux_field_history_event_dedup` via `ON CONFLICT DO NOTHING`, preserving each row's
`event_id` / `created_at` / `source` / `changed_by`. Sub-entity rows are untouched — they
keep their own ids (already re-pointed by ITER13-001), so the `contact` aggregation strategy
already resolves them to the survivor.

`field_name` also encodes changes to a journal's **sub-rows**, so they group under the
parent journal (`entity_type='journal'`, `entity_id=<journal id>`) without a join and
survive sub-row deletion. The convention is `<prefix>:<key>:<field>`, where the key is a
short, stable surrogate kept within the `VARCHAR(100)` column:

- `route:<route_id>:<field>` / `gear:<gear_item_id>:<field>` — route/gear edits (ITER12-002 P1/2)
- `plan:doc:<document_id>:<field>` — PLAN document edits (document ids are preserved across
  updates by matching on `url`; ITER12-002 P4)
- `abseil:pitch:<pitch_number>:<field>` — ABSEILING per-pitch edits (ITER12-002 P4)

Marker fields (`__created__`, `__deleted__`, `types`) record create/delete/type changes.

#### Event Outbox Table (Transactional Event Publishing)
```sql
CREATE TABLE event_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) NOT NULL UNIQUE,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id INTEGER NOT NULL,
    aggregate_type VARCHAR(50) NOT NULL, -- 'contact', 'journal', 'calendar', etc.
    event_data JSONB NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE NULL,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT NULL,
    correlation_id VARCHAR(255) NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Note:** The outbox table stores domain events from all domains (contacts, journal, calendar, etc.) for transactional publishing to MeiliSearch and other external systems.

#### Basic Indexing (Iteration 1)
```sql
-- Essential indexes for contact operations
CREATE INDEX idx_contacts_first_name ON contacts USING gin(to_tsvector('english', first_name));
CREATE INDEX idx_contacts_last_name ON contacts USING gin(to_tsvector('english', last_name));
CREATE INDEX idx_contacts_full_name ON contacts USING gin(to_tsvector('english',
    COALESCE(first_name, '') || ' ' || COALESCE(last_name, '') || ' ' || COALESCE(nick_name, '')));

-- Contact methods indexes
CREATE INDEX idx_contact_methods_contact_id ON contact_methods(contact_id);
CREATE INDEX idx_contact_methods_type ON contact_methods(method_type);
CREATE INDEX idx_contact_methods_value ON contact_methods(value);
CREATE INDEX idx_contact_methods_primary ON contact_methods(contact_id, method_type) WHERE is_primary = TRUE;

-- Contact addresses indexes
CREATE INDEX idx_contact_addresses_contact_id ON contact_addresses(contact_id);
CREATE INDEX idx_contact_addresses_country ON contact_addresses(country_code);
CREATE INDEX idx_contact_addresses_locality ON contact_addresses(locality);
CREATE INDEX idx_contact_addresses_primary ON contact_addresses(contact_id) WHERE is_primary = TRUE;

-- Contact notes indexes
CREATE INDEX idx_contact_notes_contact_id ON contact_notes(contact_id);
CREATE INDEX idx_contact_notes_content ON contact_notes USING gin(to_tsvector('english', content));

-- Tags indexes
CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_tags_parent_id ON tags(parent_id);

-- Contact tags indexes
CREATE INDEX idx_contact_tags_contact_id ON contact_tags(contact_id);
CREATE INDEX idx_contact_tags_tag_id ON contact_tags(tag_id);

-- Field history indexes
CREATE INDEX idx_field_history_field_name ON field_history(field_name);
CREATE INDEX idx_field_history_created_at ON field_history(created_at);
-- Unique idempotency index (see Field History Table above)
-- CREATE UNIQUE INDEX ux_field_history_event_dedup ON field_history(event_id, entity_type, entity_id, field_name);

-- Event outbox indexes
CREATE INDEX idx_event_outbox_unprocessed ON event_outbox(processed_at) WHERE processed_at IS NULL;
CREATE INDEX idx_event_outbox_aggregate ON event_outbox(aggregate_type, aggregate_id);
CREATE INDEX idx_event_outbox_occurred_at ON event_outbox(occurred_at);
CREATE INDEX idx_event_outbox_retry_count ON event_outbox(retry_count) WHERE processed_at IS NULL;
```

## Future Tables (Later Iterations)

### Calendar and Events (Iteration 2)
```sql
-- To be implemented when calendar features are added
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    location TEXT,
    attendees JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Journal System (Iteration 3+)
See [Journal System Specification](../journal-system-specification.md) for complete database schema including:
- Base `journals` table with title, content, event_date_range, parent_id, order
- Type-specific data tables (15 types):
  - Base types: `journal_calendar_info`, `journal_mood_data`, `journal_plan_data`, `journal_travel_data`, `journal_photo_album_data`
  - Activity types: `journal_fitness_data`, `journal_outdoor_activity_data`, `journal_bushwalking_data`, `journal_abseiling_data`, `journal_canyoning_data`, `journal_climbing_data`, `journal_kayaking_data`, `journal_skiing_data`, `journal_jogging_data`
- Supporting tables: `routes`, `journal_tags`, `journal_contacts`, `journal_events`
- Proper foreign key constraints and indexes for search/filtering
- Template system: `activity_templates` (UUID pk, user-owned, `template_type` ∈ {`abseiling`, `canyoning`, `caving`, `climbing`} enforced by `ck_activity_templates_type`, type-specific columns for canyoning/caving/climbing; an `abseiling` template uses only the common fields — name, region, description, standard pitches), `template_pitches` (FK to activity_templates, cascade delete, unique template_id+pitch_number)
- Gear item tracking: `gear_items` (UUID pk, user-owned, name required, model/serial_number/purchase_date/manufacturer optional, timestamps, indexed by user_id and name)

#### Consolidated abseiling template reference (ITER16-001)

Abseiling-derived activities (CANYONING, CLIMBING, CAVING, and plain ABSEILING_TRIP) carry a durable reference to the template they were based on. Because all three subtypes depend on ABSEILING_TRIP, every abseiling-derived journal already has a `journal_abseiling_data` row, so the reference is consolidated there:

- `journal_abseiling_data.template_id` — nullable UUID FK → `activity_templates.id`, `ON DELETE SET NULL`. Single source of truth for the "based on: \<template\>" reference (preserved across pitch edits).
- **Phase 1 (additive, migration `0094`)**: the column is added and **backfilled** from the existing per-subtype `template_id` columns on `journal_canyoning_data` / `journal_climbing_data` / `journal_caving_data`. Those columns are **left in place** for now (both coexist). The abseiling repository reads/writes the new column; the journal write-service is wired in Phase 2.
- **Phase 4 (PDF)**: the logbook PDF export resolves the template name from `journal_abseiling_data.template_id` (rendered as "based on: \<template\>"), so it appears for every abseiling-derived type — including plain ABSEILING_TRIP — and is unaffected by the Phase 5 column drop.
- **Phase 5 (cleanup, migration `0097`)**: **done** — with all reads/writes on `journal_abseiling_data.template_id`, the now-retired per-subtype `template_id` columns (and their FKs) were **dropped** from `journal_canyoning_data` / `journal_climbing_data` / `journal_caving_data`. `journal_abseiling_data.template_id` is now the sole template reference across all abseiling-derived types. (The migration's downgrade re-adds the columns and re-backfills them from the consolidated column, so the round-trip is reversible.)

#### Outdoor activity review dismissals (ITER16-002)

The Incomplete Outdoor Activities Review lets a user dismiss a whole outdoor activity journal from the
review (e.g. a genuine solo trip with no participants). Dismissals are stored in their own
journal-scoped table, **separate from the merge `journal_review_items` queue** (which holds pairwise
merge candidates — a different concept):

- `outdoor_activity_dismissals` — `id` (serial pk), `journal_id` (int, FK → `journals.id`,
  `ON DELETE CASCADE`), `user_id` (varchar), `provenance` (varchar; where the dismiss came from — `ui`,
  `mcp`, … per the shared activity-history `Provenance`), `created_at` / `updated_at`. A
  `UNIQUE(user_id, journal_id)` constraint means one dismissal per user per journal; its leftmost
  `user_id` prefix also serves per-user lookups (`list_dismissed_journal_ids`), so no separate index
  is needed.
- **Presence = dismissed.** A row's existence means the journal is excluded from the review regardless
  of which incompleteness rules it matches. Dismiss is an idempotent upsert (`ON CONFLICT (user_id,
  journal_id) DO UPDATE` refreshes provenance/`updated_at`); un-dismiss is an idempotent hard delete.
- Introduced additively by migration `0098` (create/drop round-trip); not yet consumed by the review
  projection at this phase.

#### Gear checkout state — the "checked out" definition (ITER16-003)

The outdoor dashboard's "gear currently checked out" widget derives checkout state from existing
tables — no new state is stored. A gear item is **currently checked out** when a `GEAR_USAGE`
journal references it (`journal_gear_usage_data.gear_item_id`) such that:

1. **The resolved checkout window contains now** — `COALESCE(checkout_date,
   journals.event_date_range_start) <= now() < COALESCE(checkin_date, journals.event_date_range_end)`.
   The `checkout_date`/`checkin_date` columns are optional *buffer overrides* (pack the day before,
   return the day after); they are **never written back** by the Snipe-IT worker, so `checkin_date IS
   NULL` does **not** mean "still out" — the window falls back to the journal's event range. This is
   the same `COALESCE` resolution the Snipe-IT check-in sweep uses. The checkout bound is inclusive
   and the check-in bound exclusive (at the resolved check-in instant the sweep returns the asset).
2. **Snipe-IT hasn't already recorded the return** — no `sync_metadata` row with
   `integration_source = 'snipeit_checkin'`, `internal_uuid = journal_id::text` and
   `sync_status = 'success'`. This keeps the dashboard consistent with an early return recorded in
   Snipe-IT while still working when the Snipe-IT integration isn't connected (rule 1 alone then
   decides).

Scope: **all** of the user's open gear checkouts count, regardless of what kind of journal the
`GEAR_USAGE` entry is attached to (gear state is physical — hiding a checkout made for a travel
journal would misreport what's out). One entry per gear item: when several open usages reference the
same item, the earliest active checkout wins (that's when it left), ordered longest-out first.

The rule lives in `core_shared.models.journals.outdoor_dashboard.is_currently_checked_out` (pure,
unit-tested); `SqlOutdoorDashboardRepository.list_gear_checkout_facts` resolves the window bounds in
SQL and applies only a cheap already-ended bound (`resolved check-in > now`).

#### Tasks — journal-anchored commitments (ITER18-001)

A task is a short plain-text commitment anchored to exactly **two** journals: the *creating*
journal where it arose, and the *due* journal where it matters. See the
[Home Dashboard & Tasks specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#tasks).
Introduced by migration `0105` (create/drop round-trip).

- `tasks` — `id` (serial pk), `user_id` (varchar 50), `text` (TEXT), `status` (varchar 20, default
  `'not_done'`), `creating_journal_id` / `due_journal_id` (int, FK → `journals.id`), `created_at` /
  `updated_at`. Indexed by `user_id` and by each anchor.
- `task_intermediate_journals` — `task_id` (FK → `tasks.id`), `journal_id` (FK → `journals.id`),
  `created_at`; `PRIMARY KEY (task_id, journal_id)`, indexed by `journal_id`. Journals where the
  task was discussed, revisited, or previously due.
- `task_contacts` — `task_id` (FK → `tasks.id`), `contact_id` (FK → `contacts.id`), `created_at`;
  `PRIMARY KEY (task_id, contact_id)`, indexed by `contact_id`. A **plain reference** — no
  relationship type, role or attendance status, unlike `journal_contact_relationships`.

**Both anchors are `NOT NULL`.** This is core invariants 1–3 expressed in the schema: a task can
never exist with only one anchor at any point in its life. Nothing forbids the two columns holding
the same journal (invariant 6). The remaining invariants — the due journal must exist, be owned by
the acting user, and be future-dated *at the moment it is set* — need journal data and the user's
timezone, so they live in the service layer where REST and MCP both inherit them.

**Foreign-key directions carry the *Journal Anchor Integrity* rules:**

| From | To | Action | Why |
|---|---|---|---|
| `tasks.creating_journal_id` / `due_journal_id` | `journals.id` | **`RESTRICT`** | Deleting a journal that anchors a task is *blocked*, not cascaded. The explanatory failure that names the blocking tasks arrives with ITER18-002; until then the database refuses on its own rather than silently destroying tasks. **Merge is the exception** — it re-points the anchors onto the survivor first, so it is never blocked (see below). |
| `task_intermediate_journals.journal_id` | `journals.id` | `CASCADE` | Deleting a journal that is only an intermediate link is permitted; the link goes and the task is unaffected. |
| `task_contacts.contact_id` | `contacts.id` | `CASCADE` | Deleting a contact drops its task links without touching tasks. |
| both link tables' `task_id` | `tasks.id` | `CASCADE` | Deleting a task takes its links with it. |

**A journal merge re-points task links rather than being blocked by them** (ITER18-002 Phase 3).
Merge is core to making calendar sync usable, so unlike delete it is never refused. `JournalMergeService`
calls `TaskAnchorRepository.repoint_journal_links(source_journal_id=…, target_journal_id=…)` as its
second-to-last step, **before** it deletes the absorbed journal — the `RESTRICT` anchors would
otherwise refuse the delete, and the `CASCADE` intermediate links would be destroyed rather than
moved. The repository runs four statements whose order is the design:

1. delete the source-side intermediate link where the task already holds one for the target, so the
   re-point cannot violate `PRIMARY KEY (task_id, journal_id)` — `ON CONFLICT` is unavailable on an
   `UPDATE`, the same lesson `JournalTagRepository.merge_into` records;
2. re-point the surviving intermediate links;
3. re-point both anchors in one `UPDATE`, leaving `status` and `text` alone — a survivor that becomes
   both the creating *and* the due journal of a task is a permitted outcome;
4. drop the intermediate link that has become redundant with one of the task's own anchors, which
   must run after step 3 because it reads the anchors that step has just moved.

Before the affected tasks are read, **both** journals are taken `FOR UPDATE`, in ascending id order. The
re-point is therefore the merge's *first* write: the ordering only prevents two merges from deadlocking
if nothing in the transaction has already locked one of the pair, and `journal_repo.save(target)` would. The absorbed journal, because inserting a
task takes `FOR KEY SHARE` on each anchor journal to hold its own foreign key and `FOR UPDATE` is the
weakest mode conflicting with it — otherwise a concurrent `create_task` could anchor to the absorbed
journal after the re-point and before the delete, and `RESTRICT` would block the merge. The survivor,
because two merges absorbing different journals into the same target could both clear the de-duplication
step before either wrote its `(task_id, target)` link, colliding on the composite primary key.

It sits on `TaskAnchorRepository` — the port the delete guard uses — rather than on `TaskRepository`, so
the journal domain can move task links without also being able to change a task's text, status or
contacts. Like everything on that port it is **journal-scoped rather than owner-scoped**: it is data
integrity for a journal about to be deleted, and a row skipped by an owner filter would fail the merge.
The merge has already established that both journals share an owner.

The link tables' **composite primary keys** are what make link adds idempotent at the repository
level — a retry cannot create a duplicate row. `SqlTaskRepository` cashes that in with
`INSERT … ON CONFLICT (task_id, <linked id>) DO NOTHING RETURNING task_id`, so a repeated add is a
no-op that reports "no change" rather than an integrity error. The link tables carry no `user_id` of
their own, so every link operation first proves the task belongs to the acting user; owner scoping
therefore holds across the link tables as well as `tasks` itself.

Contact links are inserted **in batch**, with the same
`ON CONFLICT (task_id, contact_id) DO NOTHING RETURNING contact_id`, so *N* contacts cost one
ownership guard and one statement instead of *2N*. The ids arrive as a single `integer[]` and are
`unnest`ed rather than expanded into a multi-row `VALUES` list: one bind parameter per contact is
correct until there are 32,767 of them, which is asyncpg's hard limit on query arguments, and the
specification says a task may reference *any number* of contacts. Two parameters whatever *N* is. When a contact is deleted between the service's
existence check and that insert, the foreign key catches it and the caller must still get the
promised 404 — so the service re-reads the ids it was given to find out which one went, rather than
parsing the id out of the violation's `DETAIL` text (PostgreSQL does put it there, but it is
localised prose and driver-dependent, and this domain already has a bug on record from matching the
wrong rendering of an error). **That recovery read is why the insert runs inside a `SAVEPOINT`**:
PostgreSQL puts the transaction into a failed state on a constraint violation, so the lookup would
raise `InFailedSQLTransactionError` before it could answer and a promised 404 would surface as a 500.

`ck_tasks_status CHECK (status IN ('not_done', 'done', 'cancelled'))` mirrors the three-value
`TaskStatus` domain enum (`core_shared.models.tasks.TaskStatus`) exactly; a migration test asserts
every enum member is accepted and nothing else is, so the column and the enum cannot drift apart.
There is deliberately no in-progress, blocked or deferred state — deferring a task is expressed by
retargeting it onto a later journal.

**Primary key is `Integer`, not UUID**, despite the newer journal-tag and activity-template tables
being UUID-keyed. The specification makes tasks full domain-event citizens whose events project
into field history, and `DomainEvent.aggregate_id` is typed `int`
(`core_shared/core_shared/stream_client.py`) while `field_history.entity_id` is `Integer`
(`app/infrastructure/contacts/contact_tables.py`) — a UUID task id could not be an event aggregate
id or a history entity id without migrating a table shared with contacts and journals. Integer also
matches the `journals.id` and `contacts.id` every task foreign key points at.

Following the journal domain's convention, these tables have **no SQLAlchemy `Table` object**: the
migration is the schema's source of truth and repositories use raw SQL. (Note the unrelated
`app/infrastructure/tasks/` package, which holds ARQ background jobs, not domain tasks.)

### Photo Integration (Iteration 4)
```sql
-- To be implemented when Immich integration is added
CREATE TABLE photo_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    immich_id VARCHAR(255) UNIQUE NOT NULL,
    filename VARCHAR(255) NOT NULL,
    taken_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### External Integration Tables (Later Iterations)

#### Google Sync State (When Google Integration Added)
```sql
-- To be implemented when Google sync features are added
CREATE TABLE google_sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL,
    local_id UUID NOT NULL,
    google_id VARCHAR(255) NOT NULL,
    etag VARCHAR(255),
    last_synced TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sync_status VARCHAR(20) DEFAULT 'synced',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(entity_type, local_id)
);
```

#### Contact Interactions (When Interaction Tracking Added)
```sql
-- To be implemented when interaction tracking is added
CREATE TABLE contact_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    interaction_type VARCHAR(50) NOT NULL,
    description TEXT,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Sync Jobs — Fan-Out Hierarchy (ITER14-003)

The `sync_jobs` table tracks integration sync-job history. To support **non-blocking
fan-outs** (orchestrator jobs that dispatch child batch jobs and return immediately
instead of blocking on `asyncio.gather`), the table carries a parent↔child hierarchy
and an additional status. Model: `core_shared/core_shared/models/sync_job.py`;
repository: `core_shared/core_shared/repositories/sync_job_repository.py`.

**`status` value `in_progress`** — added to the `ck_sync_jobs_status` check
constraint (alongside `queued`, `running`, `completed`, `failed`, `cancelled`). It
marks a parent (orchestrator) job whose children have been **dispatched and are still
running**. It is distinct from `running` (a job actively executing on a worker):
`in_progress` specifically means "fan-out dispatched, awaiting children". A parent is
finalised to `completed`/`failed` by the periodic reconciliation job (ITER14-003
Phase 2).

**Hierarchy columns on `sync_jobs`:**

| Column | Type | Notes |
|---|---|---|
| `parent_job_id` | `VARCHAR(255)` NULL | Self-referencing FK → `sync_jobs.job_id` (`ON DELETE CASCADE`), indexed. Links a child batch job to its orchestrator; `NULL` for top-level jobs. |
| `expected_children` | `INTEGER NOT NULL DEFAULT 0` | Number of child jobs the orchestrator dispatched. |
| `completed_children` | `INTEGER NOT NULL DEFAULT 0` | Children that completed successfully; incremented atomically (`SET completed_children = completed_children + 1`). |
| `failed_children` | `INTEGER NOT NULL DEFAULT 0` | Children that failed; incremented atomically. |

The counters are a **fast path** only — reconciliation aggregates the actual child
rows (`SyncJobRepository.aggregate_children`) as the authoritative completion check,
so a missed counter increment cannot strand a parent. Children are persisted as their
own `sync_jobs` rows (replacing the previous synthetic, non-persisted batch IDs).

Migration: `backend/app/migrations/versions/0088_add_sync_job_fanout_hierarchy.py`
(additive; existing rows backfill counters to `0` and keep `parent_job_id` NULL).

## MeiliSearch Integration

### Search Engine Architecture
MeiliSearch runs as a separate Docker container and provides fast, typo-tolerant search across all entities. Data is synchronized from PostgreSQL using the transactional outbox pattern.

### Search Indexes Structure
```javascript
// Contacts Index (contacts_index)
{
  "id": 1,
  "first_name": "John",
  "last_name": "Smith",
  "full_name": "John Smith",
  "email": "john.smith@example.com",
  "phone": "+61 400 123 456",
  "tags": ["work", "client"],
  "notes_content": "Important client for project X",
  "entity_type": "contact",
  "created_at": "2024-01-01T10:00:00Z",
  "updated_at": "2024-01-01T10:00:00Z"
}

// Global Search Index (global_search_index)
{
  "id": "contact_1",
  "title": "John Smith",
  "content": "john.smith@example.com +61 400 123 456 Important client",
  "entity_type": "contact",
  "entity_id": 1,
  "tags": ["work", "client"],
  "created_at": "2024-01-01T10:00:00Z"
}
```

### Event-Driven Synchronization
1. **Domain Event**: Contact created/updated/deleted
2. **Outbox Storage**: Event stored in `event_outbox` table within same transaction
3. **Background Processing**: FastAPI background task polls outbox every 10 seconds
4. **MeiliSearch Update**: Index updated based on event type
5. **Mark Processed**: Event marked as processed in outbox

### Search Configuration
```python
# MeiliSearch index settings
CONTACT_INDEX_SETTINGS = {
    "searchableAttributes": [
        "first_name",
        "last_name",
        "full_name",
        "email",
        "phone",
        "notes_content"
    ],
    "filterableAttributes": [
        "tags",
        "entity_type",
        "created_at"
    ],
    "sortableAttributes": [
        "created_at",
        "updated_at",
        "last_name"
    ]
}
```

## PostgreSQL Features and Patterns

### JSON Column Usage
```sql
-- Flexible metadata storage
UPDATE contacts SET tags = tags || '["work"]'::jsonb WHERE id = ?;

-- Query JSON data
SELECT * FROM contacts WHERE tags @> '["family"]';

-- Extract JSON values
SELECT name, tags->>'work' as work_info FROM contacts;
```

### Full-Text Search (PostgreSQL)
```sql
-- Add search vector column (when needed)
ALTER TABLE contacts ADD COLUMN search_vector tsvector;

-- Update search vector
UPDATE contacts SET search_vector =
    to_tsvector('english', coalesce(name,'') || ' ' || coalesce(email,'') || ' ' || coalesce(notes,''));

-- Create GIN index for fast search
CREATE INDEX idx_contacts_search ON contacts USING gin(search_vector);

-- Search query
SELECT * FROM contacts
WHERE search_vector @@ plainto_tsquery('english', 'john smith');
```

### Advanced Indexing (Added as Needed)
```sql
-- Partial indexes for active records
CREATE INDEX idx_contacts_active ON contacts(created_at) WHERE updated_at > NOW() - INTERVAL '1 year';

-- Composite indexes for common queries
CREATE INDEX idx_contacts_name_email ON contacts(name, email);

-- JSON indexes for tag queries
CREATE INDEX idx_contacts_tags_gin ON contacts USING gin(tags);
```

## Migration Strategy

### Alembic Migration Approach
```python
# Example migration for contacts domain tables
"""Create contacts domain tables

Revision ID: 001_create_contacts_domain
Revises:
Create Date: 2024-01-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Create contacts table
    op.create_table('contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.VARCHAR(length=100), nullable=False),
        sa.Column('last_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('middle_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('nick_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create tags table
    op.create_table('tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.VARCHAR(length=100), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('color', sa.VARCHAR(length=7), nullable=True),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['tags.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.CheckConstraint("name ~ '^[a-zA-Z0-9_&-]+$'", name='tag_name_format')
    )

    # Create contact_methods table
    op.create_table('contact_methods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('method_type', sa.VARCHAR(length=20), nullable=False),
        sa.Column('value', sa.TEXT(), nullable=False),
        sa.Column('label', sa.VARCHAR(length=50), nullable=True),
        sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("method_type IN ('email', 'phone')", name='valid_method_type'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create contact_addresses table
    op.create_table('contact_addresses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.VARCHAR(length=50), nullable=True),
        sa.Column('street_line_1', sa.VARCHAR(length=255), nullable=False),
        sa.Column('street_line_2', sa.VARCHAR(length=255), nullable=True),
        sa.Column('locality', sa.VARCHAR(length=100), nullable=True),
        sa.Column('region', sa.VARCHAR(length=100), nullable=True),
        sa.Column('postal_code', sa.VARCHAR(length=20), nullable=True),
        sa.Column('country_code', sa.VARCHAR(length=2), nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create unique constraint for primary methods
    op.create_index('idx_contact_methods_unique_primary', 'contact_methods',
                   ['contact_id', 'method_type'], unique=True,
                   postgresql_where=sa.text('is_primary = true'))

    # Create unique constraint for primary addresses
    op.create_index('idx_contact_addresses_unique_primary', 'contact_addresses',
                   ['contact_id'], unique=True,
                   postgresql_where=sa.text('is_primary = true'))

    # Create contact_notes table
    op.create_table('contact_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.TEXT(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create contact_tags junction table
    op.create_table('contact_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contact_id', 'tag_id')
    )

    # Create contact_history table
    op.create_table('contact_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.VARCHAR(length=50), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.VARCHAR(length=20), nullable=False),
        sa.Column('field_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('old_value', sa.TEXT(), nullable=True),
        sa.Column('new_value', sa.TEXT(), nullable=True),
        sa.Column('changed_by', sa.VARCHAR(length=100), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("action IN ('created', 'updated', 'deleted')", name='valid_action'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create all indexes (see database design document for complete list)
    # Contact indexes
    op.create_index('idx_contacts_first_name', 'contacts',
                   [sa.text("to_tsvector('english', first_name)")], postgresql_using='gin')
    op.create_index('idx_contacts_last_name', 'contacts',
                   [sa.text("to_tsvector('english', last_name)")], postgresql_using='gin')

def downgrade():
    op.drop_table('contact_history')
    op.drop_table('contact_tags')
    op.drop_table('contact_notes')
    op.drop_table('contact_addresses')
    op.drop_table('contact_methods')
    op.drop_table('tags')
    op.drop_table('contacts')
```

### Iterative Schema Evolution
- **Iteration 1**: Basic contacts table with essential fields
- **Iteration 2**: Add calendar/events tables when calendar features implemented
- **Iteration 3**: Add journal tables when journal features implemented
- **Iteration 4**: Add photo/Immich integration tables when photo features implemented
- **Future**: Add additional tables as features are developed

## Data Layer Implementation

### Repository Pattern (Python)
Each domain implements repositories following the Repository pattern:

```python
# Abstract repository interfaces
from abc import ABC, abstractmethod
from typing import List, Optional

class ContactRepository(ABC):
    @abstractmethod
    async def find_by_id(self, contact_id: int) -> Optional[Contact]:
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Optional[Contact]:
        pass

    @abstractmethod
    async def search(self, query: str) -> List[Contact]:
        pass

    @abstractmethod
    async def save(self, contact: Contact) -> Contact:
        pass

    @abstractmethod
    async def delete(self, contact_id: int) -> None:
        pass

    @abstractmethod
    async def get_contacts_by_tag(self, tag_id: int) -> List[Contact]:
        pass

class TagRepository(ABC):
    @abstractmethod
    async def find_by_id(self, tag_id: int) -> Optional[Tag]:
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> Optional[Tag]:
        pass

    @abstractmethod
    async def get_all(self) -> List[Tag]:
        pass

    @abstractmethod
    async def get_children(self, parent_id: int) -> List[Tag]:
        pass

    @abstractmethod
    async def save(self, tag: Tag) -> Tag:
        pass

    @abstractmethod
    async def delete(self, tag_id: int) -> None:
        pass

class ContactHistoryRepository(ABC):
    @abstractmethod
    async def get_contact_history(self, contact_id: int) -> List[ContactHistoryEntry]:
        pass

    @abstractmethod
    async def record_change(self, entry: ContactHistoryEntry) -> ContactHistoryEntry:
        pass
```

### SQLAlchemy Core Implementation

- **Connection Injection**: Repositories receive AsyncConnection in constructor
- **Explicit Queries**: Use SQLAlchemy text() with parameterized queries
- **Complex Joins**: Handle contact aggregates with LEFT JOINs for methods, notes, tags
- **Transaction Management**: Handled at service layer, repositories use provided connection
- **Type Safety**: Return domain models, not database rows

_See [Domain Architecture](./domain-architecture.md) for detailed repository patterns and examples._

### Transaction Management & Commit Timing

The request-scoped `AsyncConnection` runs in **commit-as-you-go** mode
(`engine.connect()` in `app/infrastructure/di/database.py`), *not* `engine.begin()`.
This matters because FastAPI/Dishka run `yield`-dependency teardown **after** the
HTTP response has been sent — so committing at teardown lets a client's immediate
follow-up request read pre-commit state (the read-after-write race, issue #945).
Writes are therefore committed **before the response is sent**.

**Rules:**

- **Writes** are an explicit unit of work in the **service layer**, via
  `app/infrastructure/unit_of_work.py`:
  - `@transactional` on a service write method, or `async with unit_of_work(connection):`
    around the write. Commits on success, rolls back on error, and is
    **re-entrant** (nested units join the outer one; only the outermost commits).
    Re-entrancy is tracked with a depth counter on `connection.info`, not
    `in_transaction()`, because a prior read autobegins a transaction.
  - `savepoint(connection)` (a SAVEPOINT) for batch loops that roll back one item
    and continue.
- **Reads** use no transaction helper. Their autobegun transaction is rolled back
  when the connection closes (a harmless no-op).
- **A read whose value decides a write must lock the row it read** — a locking
  read (`SELECT … FOR NO KEY UPDATE`, e.g. `TaskRepository.find_by_id_for_update`)
  inside the unit of work, not the plain finder. Without it two overlapping
  requests both read the old state, both conclude their change is allowed, and
  the later write wins: the rule the check exists to enforce is bypassed by
  timing rather than by request. This is not only about losing a *field* — a
  read-decide-write sequence can lose a *rule* even when the row has exactly one
  mutable column. Prefer `FOR NO KEY UPDATE` over `FOR UPDATE` so foreign-key
  checks from child inserts (`FOR KEY SHARE`) are not made to queue behind it.
  Ordinary reads that only display or return a row take no lock — a lock nobody
  needs is a lock somebody else waits on.
- **Controllers never open transactions** — that is a smell; transaction
  boundaries belong in the service layer.
- **MCP tools** are controller-equivalent and must **not** open transactions:
  a write tool calls a `@transactional` service that owns the commit (the mounted
  MCP sub-app has no commit middleware, so the *service* — never the tool — is
  the commit boundary).
- **No commit backstop:** the connection provider never commits at teardown.
  Every write path — REST handlers (via services) and MCP tools — commits
  explicitly in the service layer before the response. On normal exit the
  connection closes and any still-open transaction (typically read-only, but
  also an uncommitted write if a path forgot its `unit_of_work`) is rolled back;
  on error the provider rolls back. A write that forgets its `unit_of_work` is
  therefore *not* silently committed — it is discarded, which surfaces the bug
  rather than hiding it. (Historically a `CommitOnResponseMiddleware` plus a
  teardown-commit net covered un-migrated endpoints during the #945 migration;
  both were removed once all write paths used explicit units of work.)

The transactional outbox (`event_outbox`) is written on the **same** connection
as the business data, so the same commit publishes events atomically with the
write.

## Performance Considerations

### Query Optimization (PostgreSQL)
- Use parameterized queries for security and performance
- Implement query result caching where appropriate
- Leverage PostgreSQL-specific features (JSONB, full-text search)
- Use EXPLAIN ANALYZE for performance analysis
- Add indexes incrementally based on actual usage patterns

### Connection Management
- Use asyncpg connection pooling for concurrent access
- Proper async connection lifecycle management
- Timeout and retry strategies for external integrations
- Connection health monitoring in application health checks

### Data Growth Strategy
- Start simple with single table approach
- Add partitioning when data volume requires it
- Implement archival strategies as needed
- Monitor query performance and add indexes incrementally

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - How domains interact with the database
- [Technology Stack](./technology-stack.md) - ORM and database technology choices
- [Security & Performance](./security-performance.md) - Database security and optimization
