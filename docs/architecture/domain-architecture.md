# Domain Architecture - Personal CRM & Journal System

This document provides detailed information about the domain-driven architecture, component design, project structure, and implementation patterns.

## Component Details

### 1. Client Interfaces

#### MCP Protocol Interface
- **Purpose**: Provide AI assistants with structured access to personal data
- **Implementation**: Custom MCP server with defined tools and resources
- **Key Features**:
  - Contact search and management tools
  - Journal entry creation and retrieval
  - Calendar event access
  - Photo association and search
  - Relationship analysis and insights

#### Web Interface
- **Technology**: React with Next.js or Vite
- **Purpose**: Human-friendly interface for data management
- **Key Features**:
  - Contact management dashboard
  - Rich text journal editor
  - Calendar views
  - Photo associations with links to Immich
  - Analytics and insights
  - Contact Editor

### 2. API Adapters (Driving Adapters)

#### MCP Server Adapter
- **Framework**: `@modelcontextprotocol/sdk` with Streamable HTTP Transport
- **Architecture Role**: Driving adapter that calls into domain use cases
- **Transport**: HTTP-based for web-compatible AI client integration
- **Responsibilities**:
  - Tool registration and execution via MCP SDK
  - Resource management and caching
  - HTTP-based authentication and session management
  - Request/response formatting per MCP specification
  - Dependency injection into domain services
  - Connection management for multiple AI clients

#### REST API Server Adapter
- **Framework**: FastAPI with Python
- **Standard**: JSON API specification compliance
- **Architecture Role**: Driving adapter that calls into domain use cases
- **Authentication**: Session-based authentication with Starlette SessionMiddleware
- **Responsibilities**:
  - HTTP request handling with automatic OpenAPI documentation
  - JSON API response formatting
  - Session-based authentication middleware
  - Input validation with Pydantic models
  - Rate limiting and CORS configuration
  - Error handling per JSON API spec
  - Service factory functions for dependency injection

### 3. Domain Layer (Hexagonal Core)

#### Domain Structure
Each domain follows the same internal structure:
```
domain/
├── models/           # Domain models
├── events/           # Domain events
|── adpters/          # Interfaces for external dependencies
|   ├── sql/              # Database adapters
|   ├── http/             # External API adapters
|   ├── events/           # Event publishing adapters
|   └── cache/            # Caching adapters (optional)
```

#### Contacts Domain
- **Entities**: Contact, Tag, ContactMethod, ContactNote, ContactAddress
- **Value Objects**: Email, PhoneNumber, Address, TagName, CountryCode
- **Domain Services**: ContactValidationService, TagHierarchyService, ContactHistoryService, AddressValidationService, UpcomingImportantDatesService
  (see *[Upcoming important dates](#upcoming-important-dates)*)
- **Ports**: ContactRepository, TagRepository, ContactHistoryRepository, ContactEventPublisher, ContactImportanceRepository, UpcomingImportantDateRepository
- **Business Rules**:
  - Contact name validation (first_name required)
  - Email uniqueness validation
  - Tag naming constraints (alphanumeric, -, _, & only)
  - Maximum 25 tags per contact
  - Primary contact method enforcement (one primary per type)
  - Primary address enforcement (one primary per contact)
  - Address validation (street_line_1 and country_code required)
  - Country code validation (ISO 3166-1 alpha-2 format)
  - Contact history tracking for all changes
- **Domain Events**: ContactCreated, ContactUpdated, ContactDeleted, TagAssigned, TagRemoved, ContactMethodAdded, ContactNoteAdded, ContactAddressAdded

#### Calendar Domain
- **Entities**: Event, Reminder
- **Value Objects**: DateTime, Duration, Location
- **Domain Services**: ConflictDetectionService, MeetingPreparationService
- **Ports**: EventRepository, GoogleCalendarService, EventEventPublisher
- **Business Rules**:
  - Event conflict detection
  - Recurring event logic
  - Time zone handling
  - Meeting preparation workflows

#### Journal Domain
See [Journal System Specification](../journal-system-specification.md) for comprehensive domain design including:
- **Entities**: Journal (base), 15 journal types with type-specific data tables
- **Value Objects**: DateRange, Route, TypeDependencies
- **Domain Services**: JournalService, TypeManagementService, MergeService, JournalDateResolver
  (see *[Journal date resolution (user-local)](#journal-date-resolution-user-local)*)
- **Ports**: JournalRepository, RouteRepository, IntegrationWorkerInterface
- **Business Rules**:
  - Type system with automatic dependency resolution
  - Hierarchical organization (max 5 levels)
  - Contact relationship management (4 types)
  - Integration conflict resolution
  - Route tracking and reuse

#### Tasks Domain
See [Home Dashboard & Tasks Specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#tasks)
for the behaviour contract. A task is a short plain-text commitment anchored to exactly two journals —
the *creating* journal where it arose and the *due* journal where it matters.
- **Entities**: `Task` (`core_shared/core_shared/models/tasks/entities.py`)
- **Domain Enums**: `TaskStatus` — not done (default), done, cancelled
  (`core_shared/core_shared/models/tasks/task_status.py`)
- **Business Rules**:
  - Both journal anchors are mandatory and can never be absent at any point in a task's life; the
    entity validates their presence, and the schema enforces it (see
    [Database Design](database-design.md))
  - The creating and due journals may be the same journal
  - Validation is split by what each layer can know: the entity checks the owner, the text and the
    presence of both anchors; whether the due journal exists, is owned by the acting user and is
    future-dated **at the moment it is set** needs journal data and the user's timezone, so it is
    enforced in the service layer where REST and MCP both inherit it
  - *Lapsed* is derived, never stored — a not-done task whose due journal has passed or been cancelled
  - **Contact links are a plain reference.** They carry no relationship type, no role and no
    attendance status — unlike journal-contact relationships, which carry all three — and nothing
    parses contacts out of the task text. They are editable in **any** status, so no status is read
    or written when one is added or removed, and both operations are idempotent. The enforceable
    half of "the contact must be the acting user's" is **existence**: `contacts` has no owner column
    in this system, a divergence recorded in
    [iteration 18](../tasks/iteration-18-home-dashboard-and-tasks.md) and inherited here rather than
    faked. Unlinking deliberately does *not* require the contact to still exist, because
    `task_contacts` cascades from the contact side and the row is already gone
  - **A journal's role decides which rules reach it.** Only *intermediate* journals are rows in
    `task_intermediate_journals`; the creating and due journals are columns on the task. So the
    intermediate-link surface can neither add an anchor nor remove an anchor *role*, and both
    attempts raise `TaskJournalIsAnchorError` (409) naming which anchor it was — an explicit refusal
    rather than a silent no-op, because "there was no row to remove" would read to a caller as "it
    was not attached". Attaching is otherwise idempotent (the composite primary key's, with no
    read-then-add), requires the journal to exist and be the acting user's (answered with the
    journal domain's own `JournalNotFoundError`, since an intermediate journal is not an anchor),
    and is editable in any status. Detaching does *not* require the journal to still exist, on the
    contact link's cascade reasoning
  - **A journal can hold an anchor role *and* an intermediate link at once, and the detach refusal
    is conditioned on that.** Retargeting keeps the previous due journal as an intermediate link and
    never unlinks, so attaching a journal and then retargeting onto it leaves both. Detach therefore
    deletes first and refuses only when nothing was removed: refusing on the anchor alone would make
    a link the user created permanently unremovable, contradicting the specification's "intermediate
    links can be removed". The anchor column is never touched either way
  - **Intermediate links are explicit only, with exactly one exception.** Nothing infers a link
    from where a user happened to be when they edited a task; the sole automatic link is
    `retarget_due_journal` retaining the previous due journal, which is what keeps a repeatedly
    deferred task's trail visible. A link created either way is an ordinary one the user may remove
  - **The link methods read the task without a lock**, unlike `set_status` and
    `retarget_due_journal`, which decide a rule from the status they read and write that decision
    back. The only state that can move under a link call is a concurrent retarget making the
    journal an anchor, and a journal that is both the due anchor and an intermediate link is a
    shape retargeting produces legitimately, so a lock would narrow a window onto a supported
    outcome — and would deepen the merge lock-order inversion ITER18-002 Phase 6 exists to remove
- **Ports**: `TaskRepository` (`backend/app/core/tasks/models/repositories.py`), implemented by
  `SqlTaskRepository` (`backend/app/core/tasks/adapters/sql/task_repository.py`) and provided at
  request scope by `TaskProvider` (`backend/app/infrastructure/di/tasks.py`);
  `TaskAnchorRepository` in the same module, implemented by `SqlTaskAnchorRepository`
  (`backend/app/core/tasks/adapters/sql/task_anchor_repository.py`) — see
  *[The journal delete guard](#the-journal-delete-guard)* below; and `TaskContactRepository`,
  implemented by `SqlTaskContactRepository`
  (`backend/app/core/tasks/adapters/sql/task_contact_repository.py`) and provided by
  `ContactProvider` — see *[A contact merge carries the task's
  people](#a-contact-merge-carries-the-tasks-people)* below.
  **The two extra ports exist for the same reason and it is not symmetry.** `TaskRepository` is
  owner-scoped by contract, and each of the other two hands a *different domain* the narrow
  capability its own data integrity needs — moving journal links, moving contact links — without
  handing it the ability to change a task's text, status or existence. Neither is owner-scoped,
  because each stands in for what a foreign key would otherwise do; `TaskContactRepository` could
  not be in any case, since `contacts` has no `user_id` column
- **Read model**: `TaskReadModel` and the *lapsed* derivation — see
  *[Task read model and lapsed derivation](#task-read-model-and-lapsed-derivation)* below — and the
  link-role grouping a journal's task list is built on, see
  *[A journal's tasks, by link role](#a-journals-tasks-by-link-role)*; the per-page count behind the
  journal list's indicator, see
  *[The journal list's tasks-due indicator](#the-journal-lists-tasks-due-indicator)*; and the
  forward-window rule the home dashboard's tasks section is built on, see
  *[The upcoming window](#the-upcoming-window)*.
- **Domain Services**: `TaskService`
  (`backend/app/core/tasks/services/task_service.py`), provided at request scope by `TaskProvider`.
  It is where the specification's *core invariants* are enforced, so REST and MCP both inherit them
  rather than each re-implementing them — see *[Task creation invariants](#task-creation-invariants)*
  below. The date semantics the future-dated invariant is judged against are **not** the tasks
  domain's: they live in `JournalDateResolver` (journal domain — see
  *[Journal date resolution (user-local)](#journal-date-resolution-user-local)*), which `TaskService`
  consumes rather than re-derives. Its mutation surface is `create_task`, `update_task` (the text, the
  status, or both, under **one** locking read and one write so a `PATCH` carrying both can never be
  half-applied), `set_status` (a thin delegation to `update_task`, kept as a named intent for the MCP
  tool) and `delete_task`
- **Repository contract**: **owner scoping is part of the port, not an implementation detail.** Every
  method takes the acting user's id and every statement filters on it, so a task belonging to
  somebody else is indistinguishable from one that never existed: `find_by_id` returns `None` and
  every other method raises `TaskNotFoundError`. The link tables carry no `user_id` of their own, so
  link operations reach the owner through the task they belong to — but the **writes** and the
  **reads** do that differently, and the difference is a lock rather than a filter. A link write
  runs a separate `SELECT … FOR KEY SHARE` on the task first, so a concurrent delete cannot turn the
  promised `TaskNotFoundError` into a raw foreign-key violation. A link **read** has no such window —
  it writes nothing — so it scopes itself inside its own statement with a `LEFT JOIN` from `tasks`:
  no rows means the task is absent or not the caller's, one row with a null id means it is theirs
  with no links. That distinction is the only thing the separate guard bought a read, and paying a
  round trip for it cost every task-returning response an extra statement, because the journal trail
  on a create, `PATCH` or retarget answer is one of these reads. The repository is responsible for
  persistence and task ownership only; every other invariant is the service layer's.
  **Contact links are written in batch.** `add_contacts(task_id, contact_ids, user_id)` takes the
  ownership guard once and inserts every link in one statement, returning the ids for which a row was
  actually created. The singular `add_contact` it replaced made the guard the expensive half — *N*
  contacts cost *2N* statements — and the batch is what `TaskService.create_task` and the
  single-contact link surface both use. `remove_contact` stays singular: nothing removes in bulk.
- **Domain Events**: `TaskCreated`, `TaskUpdated`, `TaskDueJournalRetargeted`, `TaskJournalLinked`,
  `TaskJournalUnlinked`, `TaskJournalLinksRepointed` and `TaskDeleted`
  (`backend/app/core/tasks/models/events.py`), published by `TaskService` — and, for the last of
  them, by `TaskJournalMergeService` — through
  `OutboxEventPublisher` **inside the same unit of work as the write**, so an event can never exist
  for a write that rolled back and a rejected write publishes nothing — the activity-history
  specification's *integrity by construction*. Each carries `source` (`Provenance`) and `changed_by`,
  threaded from the caller: `Provenance.UI` from the REST controller, `Provenance.MCP` from the MCP
  tools, defaulting to `SYSTEM` so a caller that says nothing is never mistaken for a user. The
  aggregate id is the **task id**.
  `TaskDeleted` is deliberately a marker — task id, owner and provenance, no text or anchors —
  because `delete_task` reads nothing before deleting and enriching the payload would have bought
  exactly that read; it carries `user_id` because once the row is hard-deleted there is nothing else
  left to scope its history by. The payloads are plain dictionaries rather than models in
  `core_shared/models/outbox_events.py`: that dispatch map is for **inbound integration-sync**
  payloads, and no core domain event appears in it.
  **A task's text, status and contact changes share one event** — `TaskUpdated`, carrying
  `changed_fields` in the `{field: (old, new)}` shape `JournalUpdated` and `ContactUpdated` use —
  rather than one type per field, because a single `PATCH` may move both text and status and that is
  one write in one unit of work; `HistoryService._rows_from_changed_fields` fans the dict out into
  one `field_history` row per field, so a reader still gets a distinct line each.
  **Contact membership is a field of the task, so it uses that same vocabulary.** Linking a contact
  publishes `changed_fields = {"contact:{id}": (None, id)}` and unlinking publishes the pair the
  other way round; a create announces the people it linked as `contact_ids` on `TaskCreated`. The
  direction is positional and nothing else carries it, because `_rows_from_changed_fields` reads
  `change[0]` as the old value and never looks at the key. The key names the **contact**, following
  the collection prefixes `journal_write_service` uses for nested rows (`plan:doc`,
  `abseil:pitch`), because history rows are written `ON CONFLICT (event_id, entity_type, entity_id,
  field_name) DO NOTHING` and a shared `contacts` field would let one person be discarded as a
  redelivery of another. `contact_field_name()` in the events module owns that format so the
  service and the projection cannot disagree about it.
  **Contact links get no event type of their own, and journal links do** — an asymmetry that is
  deliberate rather than an oversight. A journal link has structure to carry: `TaskJournalLinked`
  has an `origin`, because two different writes cause the same fact, and it is half of the ordered
  pair a retarget publishes. A contact link has neither. The specification calls it *"a plain
  reference"* carrying no relationship type, role or attendance status, and it has exactly one
  cause — somebody asking for it — since a create announces its own contacts and a contact delete
  cascades without anyone acting on the task. There is nothing a dedicated type would carry that a
  `changed_fields` entry does not.
  **A retarget publishes two events, and is the only task write that publishes more than one.**
  `TaskDueJournalRetargeted` carries the due-journal pair and the reopen (only when the retarget
  actually moved the status, since retargeting always lands a task *not done*); the **automatic
  intermediate link** it retains — the previous due journal — is a `TaskJournalLinked` of its own,
  the same type a manual attach publishes. The order is **the link first, then the anchor move**,
  which holds by construction because each event is published directly behind the write it
  announces rather than beside the other's publish call.
  **Both link events are published only when a row actually moved.** `add_intermediate_journal` is
  idempotent and a retarget only ever adds a link — never removes one — so a task returning to a
  journal it has already left finds it still attached and announces nothing; likewise a repeat
  attach, a detach of a link that is not there, and every refusal. (Links are removable, by
  `detach_intermediate_journal`, by a merge collapsing redundant ones, and by a journal delete
  cascading; the first publishes `TaskJournalUnlinked`, the second is part of the merge's own
  `TaskJournalLinksRepointed`, and only the cascade still publishes nothing.)
  **`TaskJournalLinked` carries an `origin`** (`manual` or `retarget`) because two writes produce
  the same fact. That is deliberately *not* the same question as provenance: `source` records who
  acted, and a retarget is something the **user** did, so a link derived from one performed in the
  browser is `ui` — the same actor as the retarget event beside it — rather than `system`, which is
  reserved for writes no person triggered. `TaskJournalUnlinked` carries no `origin`: a user asking for the
  link to go is its only cause, since the merge that also removes links announces itself as
  `TaskJournalLinksRepointed` instead, and a key with a single possible value would advertise a case
  that does not exist.
  **A journal merge publishes `TaskJournalLinksRepointed`, one per task it moved.** A merge is never
  blocked by a task, so before the absorbed journal is deleted every link a task holds on it moves
  onto the survivor — both anchors included. That makes a merge the **one legitimate exception** to
  *"the creating journal is set once and never changes"*, which is exactly the kind of exception a
  history exists to record. The payload is `changed_fields`, so the projection reuses
  `_project_task_updated`: the anchors carry `(absorbed, survivor)` pairs under
  `creating_journal_id` / `due_journal_id`, and each intermediate link is a `journal:{id}` row in
  the direction it moved — the same key a manual attach and detach land under, so a journal a merge
  took away and one a person detached read as the same kind of line. The facts are **net effect**
  rather than statement-by-statement: a link that moved is a departure plus an arrival, while one
  collapsed as a duplicate, or moved and then dropped as redundant with an anchor, is the departure
  alone, because neither *gained* the task a link on the survivor. The two leave the task in
  different states — a collapse keeps the survivor's link the task already had, a drop leaves none —
  and produce one summary because history records the change, which is the same for both, rather
  than the state, which differs only by where each task started.
  **It is deliberately not `TaskDueJournalRetargeted`**: a merge forces no status, can move the
  creating anchor, and can delete links, so reusing that type would tell a user they deferred a task
  they never touched. Rows written *before* a merge that name the absorbed journal are left exactly
  as they are — rewriting them to name the survivor would be editing the record of what happened.
  **The journal domain does not construct task events.** `JournalMergeService` holds
  `TaskJournalMergeService` (`backend/app/core/tasks/services/task_journal_merge_service.py`) rather
  than `TaskAnchorRepository`: the repository reports what it moved per task, and the tasks domain
  turns that into events. `TaskAnchorRepository.repoint_journal_links` therefore returns
  `list[TaskJournalRepointing]` instead of `None`, since two of its four statements are deletes and
  the anchor roles are overwritten by the re-point itself, so no caller can reconstruct the answer
  afterwards. **Every fact in a summary comes from a statement's `RETURNING`, never from the read
  that chose the tasks**: the merge's locks hold the two *journals*, so a task can be deleted or its
  link detached in between, and a task the statements passed over is not reported at all. Trusting
  that snapshot would write a change into the history of a task that no longer exists — or fail the
  merge on a task, which the specification says can never happen. Provenance is threaded through `merge_journals` from all three merge surfaces — the
  REST merge endpoint (`ui`), the `merge_journals` MCP tool (`mcp`) and the review-queue auto-merge
  endpoint (`ui`, because *auto* describes how the pairs were chosen, not who chose to merge them).
  The re-point is **step 0** of the merge for a locking reason, which also means these events precede
  the merge's own `JournalUpdated` and `JournalDeleted` in the outbox.
  **Every write path publishes at least one event, and only a retarget publishes two.** That rule is
  pinned by `tests/integration/tasks/test_task_event_completeness_integration.py`, which runs each
  path against a real outbox and compares the facts it published. The inventory is anchored to the
  **repository ports** rather than to `TaskService`'s method list, so a write performed on a task
  from another domain cannot escape it — and that is not hypothetical: the merge re-point sat in
  that file as a **named exclusion** for several phases, asserted positively rather than left
  implicit, until the phase that gave it an event. The exclusion list is now empty, and a test
  asserts that it stays empty.
  **The history projection reads every task event.** `HistoryProjectionConsumer` subscribes to all
  six types, and `HistoryService` maps each to `field_history`
  rows under `entity_type='task'`, keyed on the **task id** — an integer, so task history shares the
  table's `entity_id` column with no migration, unlike routes and gear whose UUID ids are why those
  are filed under their journal. A create writes a `__created__` marker carrying the task's text and
  a delete writes a `__deleted__` marker, the journal convention rather than the contact one, because
  a task is a top-level aggregate rather than a family of sub-entity rows. A `TaskUpdated` needs no
  special handling at all: the shared `changed_fields` fan-out gives one row per field, which is a
  reword, a status move and a person each reading as their own line.
  **The create also fans out `contact_ids` itself**, one marker row per person under the same
  `contact:{id}` key a later link publishes. That list is not an `(old, new)` pair, so the generic
  helper cannot do it — and without it a task created with somebody would show none of them while a
  later unlink showed a removal with no matching addition. Row `created_at` comes from
  `event.occurred_at`, so history records when the change happened rather than when the consumer got
  to it, and writes are idempotent on `(event_id, entity_type, entity_id, field_name)`, so stream
  redelivery is safe.
  **The retarget shares `TaskUpdated`'s handler rather than having one of its own.** Its payload is
  the same `changed_fields` shape, chosen for exactly that reason: the pair projects as a
  `due_journal_id` row naming both journals, plus a `status` row on the deferrals that reopened the
  task. A second handler would be two places for "how a task field change becomes a row" to disagree.
  **The two link events project a `journal:{id}` row**, `(None, id)` for a link and the reverse for
  an unlink — the same shape `contact:{id}` keys and `JournalTagAssigned` produce, and the key names
  the journal for the same dedup reason contact keys name the contact. `journal_field_name()` in the
  events module owns that format. **`origin` is deliberately not projected**: `field_history` has no
  column for it, so it could only live in the field name, and a link and the unlink that later
  removes it must share a name to read as a pair — an unlink has no origin to spell. What history
  carries instead is the *role*: `due_journal_id` is the anchor, `journal:{id}` is an intermediate
  link.
  **Nothing a task write announces goes unread.** The subscription list and `HistoryService._HANDLERS`
  are asserted against each other in both directions and against the event classes in the events
  module, so a type published without a handler — or a handler without a subscription — fails the
  suite rather than silently losing a line from somebody's history. The one task write that publishes
  nothing at all is the named merge exclusion above.
  **No other consumer group subscribes to a task event**: `InboundEventConsumer`'s
  patterns are all prefixes of other domains, and `SummaryConsumer` is contact-scoped. For
  `SearchIndexerConsumer` this is **permanent** — the specification's *Tasks and search* requires that
  tasks never be indexed and that the indexer ignore their events rather than fail on them, and it
  holds twice over: no task type is in its pattern list, and `SearchIndexer.process_event` branches on
  `Contact`/`Journal` and skips everything else. `StreamConsumer` acknowledges an unmatched event
  immediately, so a task event is discarded rather than left pending, and nothing dead-letters. Both
  halves are pinned by tests, because a guarantee that holds by construction is one a pattern-list
  change can quietly remove.
  **A task's history is readable, and the deleted case is what shapes the read.** `TaskHistoryService`
  mirrors `JournalHistoryService` — a paginated read through the registered `"task"` aggregation
  strategy, served by `GET /api/tasks/{id}/history` and the `get_task_history` MCP tool — with one
  addition. Every other history read authorises by loading the aggregate and comparing `user_id`,
  which a **hard-deleted** task has nothing to satisfy: the `__deleted__` marker would be written to
  a surface nobody could be authorised to read. Ownership therefore rides on the rows
  (`field_history.user_id`, stamped from the event payload) and **the rows answer first**, with the
  live `tasks` row only as a fallback for the window before the projection catches up — which is why
  a task created moments ago answers an empty history rather than a 404. The check lives in the
  service rather than in its two callers, so the endpoint and the tool cannot disagree about whose
  history it is. The `"task"` predicate does not join to `tasks` for the same reason the fallback is
  second: that join would empty a deleted task's feed. Events the projection group acknowledged
  before its patterns matched them are recovered by `TaskHistoryBackfill` at application start,
  through the same `HistoryService` the consumer uses rather than a second mapping in SQL.

#### Photos Domain
- **Entities**: Photo, ImmichPerson, PersonMatch
- **Value Objects**: ConfidenceScore, MatchMethod
- **Domain Services**: PersonMatchingService, PhotoAssociationService
- **Ports**: PhotoRepository, ImmichService, PersonMatchRepository
- **Business Rules**:
  - Person matching algorithms
  - Confidence scoring logic
  - Photo & album association rules

#### Sync Domain (Cross-Domain Operations)
- **Purpose**: Handle operations that span multiple domains
- **Components**: TransactionCoordinator, EventBus, CrossDomainUseCases
- **Responsibilities**:
  - Coordinate multi-domain transactions
  - Publish and handle domain events
  - Manage eventual consistency
  - Handle complex workflows (e.g., Google sync that affects both contacts and calendar)

### 4. Adapter Layer (Driven Adapters)

#### Adapter Structure
Each domain has its own adapters that implement external infrastructure needs:
```
domain/adapters/
├── sql/              # Database adapters
├── http/             # External API adapters
├── events/           # Event publishing adapters
└── cache/            # Caching adapters (optional)
```

#### Contacts Domain Adapters
- **SqlContactRepository**: Implements ContactRepository port
  - SQLAlchemy Core with explicit SQL queries for type safety
  - Handles complex joins for contact methods, notes, and tags
  - Connection pooling and transaction management
  - Query optimization with proper indexing
  - OpenTelemetry instrumentation for database spans
- **SqlTagRepository**: Implements TagRepository port
  - Hierarchical tag management with parent-child relationships
  - Tag uniqueness enforcement and validation
  - Efficient queries for tag trees and contact associations
- **SqlContactHistoryRepository**: Implements ContactHistoryRepository port
  - Change tracking for all contact-related entities
  - Audit trail with field-level change detection
  - Integration with domain events for automatic history recording

- **OutboxEventPublisher**: Implements ContactEventPublisher port
  - Transactional outbox pattern for reliable event publishing
  - Event serialization to PostgreSQL outbox table
  - Integration with contact history for audit trails
- **SearchIndexer**: Handles MeiliSearch indexing
  - Event-driven indexing via outbox pattern
  - Background processing every 10 seconds
  - Search index management and optimization
  - Target <50ms search response times

#### Calendar Domain Adapters
- **SqlEventRepository**: Implements EventRepository port
  - Drizzle ORM with optimized queries for time-based data
  - Recurring event handling with proper indexing
  - Time zone management and conversion
  - OpenTelemetry spans for complex queries

- **EventEventPublisher**: Implements EventEventPublisher port
  - Calendar event publishing with structured metadata
  - Cross-domain integration events

#### Journal Domain Adapters
- **SqlJournalRepository**: Implements JournalRepository port
  - Journal entry persistence
  - Full-text search capabilities
  - Tag management
- **JournalEventPublisher**: Implements JournalEventPublisher port
  - Journal event publishing
  - Mood tracking events

#### Photos Domain Adapters
- **SqlPhotoRepository**: Implements PhotoRepository port
  - Association management
- **SqlPersonMatchRepository**: Implements PersonMatchRepository port
  - Person match storage against immich's api
  - Confidence score tracking


#### Cross-Domain Adapters (Sync Domain)
- **TransactionCoordinator**: Manages distributed transactions
  - PostgreSQL transaction coordination
  - Rollback strategies
  - Consistency guarantees
- **EventBus**: Handles domain event distribution
  - In-memory event bus (simple implementation)
  - Event ordering and delivery guarantees
  - Error handling and retry logic

## Implementation Patterns

### Domain Layer Guidelines (Ports & Adapters)

- **Domain Entities**: Pure Python classes with business logic, no framework dependencies
- **Domain Components**: Business logic that doesn't belong to a single entity
- **Adapters**: Classes supply the domains infrastructure needs such as sql repositories
- **Value Objects**: Immutable objects representing domain concepts
- **Domain Events**: Pure Python classes representing business events
- **Domain Enums**: Python enums for fixed domain values with type safety
### Application Layer Guidelines

- **Use Cases**: Orchestrate domain operations, no business logic
- **Application Services**: Coordinate between domain and infrastructure
- **Command/Query Objects**: Simple data structures for input/output
- **Dependency Injection**: Inject ports (interfaces), not concrete implementations
- **Transaction Management**: Handle database transactions at this layer

### Infrastructure Layer Guidelines (Adapters)

- **Repository Adapters**: Implement domain-defined repository ports
- **API Adapters**: Implement external service ports (Google, Immich)
- **Database Adapters**: Use SQLAlchemy Core, implement repository interfaces
- **Framework Integration**: Pydantic models for FastAPI, not domain
- **Dependency Direction**: Infrastructure depends on domain ports, never reverse
- **Error Translation**: Convert infrastructure errors to domain exceptions

### Domain Enum Patterns

#### Enum Definition Guidelines

- **String Values**: Use string values for database compatibility
- **Descriptive Names**: Use clear, descriptive enum member names
- **String Conversion**: Implement `__str__()` method to return enum value
- **Domain Location**: Define enums in the same module as related entities

#### Example Enum Implementation

```python
from enum import Enum

class MethodType(Enum):
    """Enumeration for contact method types."""

    EMAIL = "email"
    PHONE = "phone"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
```

#### Repository Conversion Patterns

- **Writing to Database**: Convert enum to string using `.value` property
- **Reading from Database**: Convert string to enum using `EnumType(string_value)`
- **Error Handling**: Handle invalid enum values gracefully

#### Entity Validation Patterns

```python
def __post_init__(self) -> None:
    """Validate entity with enum."""
    if not isinstance(self.method_type, MethodType):
        raise ValueError(f"Invalid method type: {self.method_type}")

    # Type-safe business logic
    if self.method_type == MethodType.EMAIL:
        Email(self.value)  # Validate email format
    elif self.method_type == MethodType.PHONE:
        PhoneNumber(self.value)  # Validate phone format
```

### Validation Strategy (Layered)

- **Domain Layer**: Business rule validation in entities/domain services
- **Application Layer**: Use case validation and authorization
- **Infrastructure Layer**: Pydantic models for API input/output validation
- **Database Layer**: Database constraints as final safety net

### Integration Architecture

This system uses an **Isolated Worker Architecture** to manage integrations with external services. This pattern isolates each integration's dependencies and process space, preventing them from impacting the core application.

All integration logic, patterns, and implementation details are defined in the dedicated **[Integration Architecture document](./integration-architecture.md)**. This core domain remains decoupled from the specifics of any external service.

### Application Service Guidelines

- Keep application services focused on orchestration
- Validate input using Pydantic models
- Implement business rule validation
- Use database transactions for consistency
- Add comprehensive logging for operations
- Handle errors gracefully with meaningful messages
- Keep services stateless and testable

### Error Handling Guidelines

- Create custom exception classes for domain errors
- Use meaningful error messages for debugging
- Include context information in error messages
- Log errors with appropriate severity levels
- Handle exceptions at appropriate boundaries
- Return user-friendly error responses from APIs
- Use standard HTTP status codes for API errors

### Logging Guidelines

- Use Python standard library logging
- Include structured logging with context
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Include correlation IDs for request tracing
- Log business operations for audit trails
- Avoid logging sensitive information
- Use consistent log message formats

### Journal Review Stores (two distinct concepts)

The journal domain has **two separate review stores** that must not be conflated:

- **Merge review queue** (`journal_review_items` + `ReviewItemService`): pairwise *merge candidates* —
  suggestions that two journals may be duplicates, awaiting user resolve/dismiss/auto-merge.
- **Outdoor-activity review dismissals** (`outdoor_activity_dismissals` +
  `OutdoorActivityDismissalService`): whole-entry, journal-scoped dismissals for the Incomplete
  Outdoor Activities Review (ITER16-002). A dismissal excludes an outdoor activity journal from the
  incomplete list regardless of which rules it matches; it is reversible and records `provenance`
  (UI/MCP) per the activity-history convention. The dismissal service owns its commit via
  `@transactional`, following the standard service-layer transaction pattern. This store is
  deliberately **not** the merge queue — dismissing an incomplete-review entry has nothing to do with
  merge candidates.

### Journal date resolution (user-local)

**How a date range is stored.** `journals.event_date_range_start/end` hold the UTC **instant of local
midnight**, and the end is the last day *inclusive* — so 5 September in Sydney is `2026-09-04T14:00Z`, and
a single-day event has `start == end`. The zone that instant is anchored in is
`journal_calendar_info.timezone`, and a row that records none is read as **UTC** — that is what
`event_date_in_timezone` (`core_shared/models/journals/calendar_info.py`) and `google_event_times` (the
Google worker's `event_transformer.py`) do, and what the agenda query's
`AT TIME ZONE COALESCE(tz.name, 'UTC')` does. Neither function can see user settings; the user's
configured zone is substituted by a **caller**, and only in one place — the Google outbound push, for an
all-day row with no zone (`_process_journal_upsert_event` in `worker.py`). Taking `.date()` of the instant
in UTC where a zone *is* recorded is a day early for any zone ahead of UTC, which is what LOCAL-137
reported.

Everything that writes a range follows this: `JournalCreateForm` and `InlineEditDateRange` both send
`localMidnight(...).toISOString()` (`frontend/src/lib/date-utils.ts`), and since #1385 the inbound Google
sync stores an imported all-day event at local midnight in the user's zone and records that zone.
Migration **0109** moved the all-day rows imported *before* that — which sat at UTC midnight with no zone,
and pushed back to Google a day early for a user west of UTC — onto the same convention.

**`localMidnight` is midnight in the *browser's* zone, not the event's.** For a journal whose recorded
zone differs from the browser's — a user travelling, or an event imported from a foreign-zone calendar —
editing the range writes an instant anchored in the browser's zone, which can read back a calendar day
out. This is the same browser-versus-configured-zone divergence the journal list has (below): the picker
*displays* browser-local dates too, so writing in the event's zone while displaying in the browser's would
only move the inconsistency. Closing it means moving the display, the picker and the write onto one zone
together — tracked as **issue #1401**, alongside the client-side timezone work recorded as ITER18-004
Phase 3. It is not a regression: the `setUTCHours(0, …)` this replaced landed a day out in that case too,
and the convention fix corrected the ordinary same-zone case.

Clock times are a separate matter: `journal_calendar_info.start_time/end_time` are local to whatever zone
the row records, so they must never be re-anchored in a zone the row does not state. With no zone, the
stored instants are the truth.

A journal's **date** is the local date of its `event_date_range.start` in the acting user's **configured**
timezone, and it is the date the tasks model judges its future-dated invariant against. It is *intended*
to be the date the journal list groups it under; that equality does not hold unconditionally today, and
the gap is described below. A multi-day journal is dated by the day it *starts*: a trip that began
yesterday and runs until tomorrow is **past**, however much of it is still ahead. "Today" is likewise the
user's local date, resolved through `UserSettingsRepository.get_timezone` + `resolve_timezone`,
**never** UTC-today.

`backend/app/core/journal/services/journal_date_resolver.py` holds this in two layers:

- **Pure functions** taking a `ZoneInfo` — `local_date`, `journal_date`, `today_in`, `is_future_dated`
  (strictly after today: a journal starting later the same local day is not future-dated) and
  `local_day_window` (a local day as an instant range, for windowed journal queries).
- **`JournalDateResolver`**, a read-only async wrapper that supplies the timezone from
  `UserSettingsRepository`. A caller resolving many journals should take `timezone_for` **once** and use
  the pure functions, rather than paying a settings read per journal.

**The journal list does not currently use this timezone.** `groupJournalsByDay`
(`frontend/src/lib/journal-grouping.ts`) buckets journals with `format(parseISO(start), 'yyyy-MM-dd')`,
which renders in the **browser's** timezone. The two agree whenever the browser matches the configured
timezone, and disagree when the user is travelling or has configured a different one — so a journal can be
listed under one day while a server-side rule judges it by another. The configured timezone is the correct
anchor for server-side rules (it is the one the specifications are written in, and the server cannot see
the browser's); aligning the list is a frontend change, recorded as a follow-up in ITER18-001 Phase 3.

`now` is injectable throughout so day boundaries are testable either side of local midnight. Services
that expose an `anchor: date | None` parameter (the outdoor dashboard, and the home dashboard to come)
keep that signature and obtain the anchor from `JournalDateResolver.today`.

Day boundaries are built from the **date** with `datetime.combine(day, time.min/max, tz)`, not by zeroing
the components of some instant that falls inside the day. `ZoneInfo` resolves each end's offset from its
own local wall time either way — so a day whose clocks change is the 23 or 25 hours it really is — but
building from the date keeps the result independent of which instant you started from, `fold` included.

It lives in the journal domain, not settings or tasks: `app/core/settings` must stay a leaf that any
domain can import, and the home dashboard's agenda reads journals rather than tasks.
`OutdoorDashboardService` has been migrated onto it — `local_window` for its boundaries and
`JournalDateResolver.timezone_for` for the zone — by the phase that gave the agenda the same windowing,
which also fixed the repeated-hour case its private copy had. **Standing duplication to collapse:**
`compute_search_window` (`app/core/integrations/immich/album_creation_service.py`) predates this module
and should be migrated onto it too.

### Important-date occurrence resolution (recurrence)

A contact's important date is stored as loose components — `year`, `month`, `day`, any of which may be
absent — rather than as a date. `core_shared/models/contacts/important_date_occurrence.py` turns one of
those rows into the **occurrence** falling inside a window of days: `resolve_occurrence(important_date,
first_day=…, last_day=…)` returns an `ImportantDateOccurrence` or `None`. It is pure and I/O-free, so the
home dashboard's upcoming-dates section and the daily summary's inputs resolve recurrence the same way
rather than twice.

**Precision decides whether a date recurs, and it is the only thing that does:**

| `DatePrecision` | Occurrence | Derived `years` |
|---|---|---|
| `YEAR` | none — no month or day to place it | — |
| `DAY_MONTH` | the month and day, in some year | `None` |
| `FULL` | the month and day, in some year | years since the stored year |

**No `date_type` is excluded** (ITER18-004 open decision 4). `year` precision yields nothing whatever the
type, so a type filter would be a second rule overlapping the first; `custom` types are user-named, and a
`first_met` recorded to the day is a real anniversary. `years` travels as a bare count because the wording
belongs to the surface — "turns 35" for a birthday against "34 years" for an anniversary.

Four rules carry the arithmetic:

- **Both window ends are inclusive**, so a date occurring *today* is in the window — the point of a
  section that exists to give notice. Every year the window touches is a candidate, which is what lets a
  window running from December into January find a January date; a window longer than a year resolves to
  the **earliest** occurrence in it.
- **29 February is observed on 28 February** in a year that does not have one, flagged as
  `observed_for_leap_day`. Dropping it would hide the date in three years out of four; 1 March would move
  it into a month the user did not record. The flag keeps the substitution inspectable.
- **A stored year *after* the occurrence yields `years = None`**, not a negative age — the recurrence is
  real and is still returned, only the derived count is not. `0` is a real count, being what the year a
  date was first recorded makes.
- **Nothing raises over data, and there is more malformed data possible than one might expect.** A row
  whose month and day are not a real date is storable today (the day is range-checked 1–31 with no month
  cross-check), and so is one whose **year is not a calendar year at all** — unlike the month and the
  day, the year is range-checked *nowhere*: not in `ImportantDate.__post_init__`, not in
  `ImportantDateAttributes`, and not in a column constraint. `year=0` therefore reaches the resolver, and
  is treated as no year to count from rather than reported as "turns 2026". A surface resolving a page of
  contacts must degrade on such rows rather than fail on them or repeat nonsense from them. A **reversed
  window** does raise `ValueError`, because that is a caller bug rather than a question with an empty
  answer.

**The window is dates, not instants, and that is what keeps the module pure.** It reads no clock and takes
no `ZoneInfo`: a day window is only meaningful once anchored in the acting user's configured timezone, and
that anchoring belongs to the caller — the same split *Journal date resolution* makes above. Ordering is
also not here: the dashboard ranks these by date ascending then **contact importance** descending, and
importance is a separate read the model cannot see.

### Task creation invariants

The [tasks specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#core-invariants)
calls its core invariants *absolute* and requires them at **every** entry point, MCP included. They are
therefore enforced in `TaskService` (`backend/app/core/tasks/services/task_service.py`), not in a
controller: REST and MCP are thin callers, so neither can drift from the other or forget a rule.

Validation is split by what each layer can know, and each rule sits at the lowest layer that can decide it:

| Rule | Enforced by | Because |
|---|---|---|
| Non-empty text; both anchor ids present and positive | `Task.__post_init__` | Needs nothing but the entity |
| The task belongs to the acting user | `TaskRepository` (owner-scoped port) | A property of every statement, not of one method |
| Both anchors **exist** and are the user's | `TaskService` | Needs journal data |
| The due journal is **future-dated** | `TaskService`, via `JournalDateResolver` | Needs journal data *and* the user's timezone |
| Referenced contacts exist | `TaskService` | Needs the contact domain |

Three things about the service half are load-bearing:

- **Ownership is enforced by the query, not by a comparison.** Both anchors are resolved in one
  `JournalRepository.find_by_ids_for_user` call, so another user's journal is simply absent from the
  result. Existence and ownership therefore fail as the *same* error, and it says nothing about
  ownership — the same stance the task repository's port documents, and it means a rejected create
  cannot be used to probe for another user's journals. One call also covers both anchors, so the
  creating == due case costs no extra round trip.
- **The future-dated check is a write-time rule.** It runs when a due journal is set — on creation, and
  on retargeting later — and never again. Nothing re-validates it on read, which is precisely what makes
  a **lapsed** task (one whose due journal has since passed) reachable rather than unloadable.
- **The timezone is read once per call** and handed to the module's pure predicate, rather than calling
  the resolver's per-journal wrapper — the shape batch callers need, and the reason the resolver splits
  that way.

**Contacts have no owner in this system.** The `contacts` table carries no `user_id`
(`app/infrastructure/contacts/contact_tables.py`), so "the linked contact must belong to the acting
user" is not enforceable at the data layer; the service enforces contact **existence** instead. Recorded
as a divergence in [iteration 18](../tasks/iteration-18-home-dashboard-and-tasks.md), matching the same
finding in iteration 13's contact merge. If contacts ever gain ownership, `TaskService._resolve_contacts`
is the single place the rule lands.

### Task read model and lapsed derivation

Every surface that *reads* a task hands out the same shape: the task, its journals **by role**, its
contacts, and whether it has lapsed and why. The
[specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#where-tasks-appear)
asks each of those surfaces for "the task text, its status, its linked contacts, and — for lapsed
tasks — a clear lapsed marker", so the shape is defined once rather than per controller.

**Lapsed is derived on every read and never stored.** A task is lapsed when it is still *not done*
and either its due journal's date has **passed** in the acting user's timezone or that journal is a
**cancelled** event. A stored flag would need something to notice midnight passing in every user's
zone and would be wrong until it next ran, for a property that costs one date comparison. This is
also why the future-dated invariant is only a *write-time* rule: nothing re-validates it on read,
which is exactly what keeps a lapsed task loadable.

The pieces:

- **`LapseReason`** (`core_shared/models/tasks/lapse.py`) — `DATE_PASSED` or
  `DUE_JOURNAL_CANCELLED`, with `derive_lapse_reason(status, due_journal_date,
  due_journal_cancelled, today)` beside it. Pure, and it takes **dates rather than journals or a
  timezone**, so a caller deriving this for many tasks resolves the timezone once. The *reason* is
  returned rather than a boolean because "the day went by" and "the meeting was cancelled" ask the
  user for different things; the wording is the UI's, and ITER18-002 Phase 4 pins the cancellation
  path end to end.
- **`TaskReadModel`, `TaskJournalRef`, `TaskContactRef`** (`core_shared/models/tasks/read_model.py`),
  built by the pure `build_task_read_model(...)`. A journal ref carries a resolved **`date`**, not an
  instant, so no surface can re-derive it in the browser's zone and disagree with the rule that
  judged the task. `TaskReadModel.lapsed` is defined as "there is a reason" rather than computed a
  second way.
- **`TaskReadService`** (`backend/app/core/tasks/services/task_read_service.py`), request-scoped
  from `TaskProvider`. It is **read-only** — no `@transactional`, no lock, no domain event — because
  a read that opened a unit of work would hold a transaction for the length of a page render.

Four rules the derivation applies, each a deliberate reading of the specification:

| Case | Answer | Why |
|---|---|---|
| Cancelled **and** past | `DUE_JOURNAL_CANCELLED` | The more specific and more actionable of the two |
| Cancelled but still **future**-dated | `DUE_JOURNAL_CANCELLED` | The cancellation rule carries no date condition |
| Due **today** | not lapsed | Mirrors `is_future_dated`'s strictly-after, so the read-time and write-time rules agree about the same journal |
| Task **done** or **cancelled** | not lapsed | A commitment that was met or called off cannot then be let slide |

Only the **due** journal decides it. The creating journal is almost always in the past — that is what
"the journal the commitment arose in" means — so consulting it would lapse nearly every task the day
after it was written.

**Cancellation is read in batch.** A journal is cancelled when its `journal_calendar_info.event_state`
is `EventState.CANCELLED`; `invited` and `tentative` are not cancellations, and a journal with no
calendar-info row at all is simply not an event. `CalendarInfoRepository.find_cancelled_journal_ids`
answers that for a whole set in one statement, because the per-journal `find_by_journal_id` would be
an N+1 the moment a journal's task list is rendered. It performs no ownership check: callers reach it
with ids an owner-scoped query has already filtered.

**Where a cancelled journal comes from.** Three production paths write `EventState.CANCELLED`. The
user's path shares nothing with the other two; the two sync routes differ in how they *decide*, then
converge on the same write:

- **A person.** The event editor's *Event Status* select offers "Cancelled", saved through
  `PUT /api/journals/{id}/types/EVENT/data` — `event_state` is an ordinary editable field of the
  EVENT type data, so cancelling is a type-data edit rather than an operation of its own. This is the
  path the specification's "cancel rather than delete" steer points at, and it is reversible: setting
  the status back to *confirmed* un-lapses the tasks, because the lapse is derived on every read.
- **Calendar sync, one instance** — `journal_event.cancelled`.
- **Calendar sync, a whole series** — the `journal_event.series_cancelled` fan-out.

Both sync routes prefer to *delete* an untouched far-future instance and fall back to
`JournalOutboxEventProcessor._mark_journal_cancelled` when the
[delete guard](#the-journal-delete-guard) refuses — which for a task's due journal is the ordinary
path rather than an edge of it: a due journal is future-dated by invariant, so it is always a
deletion candidate and always anchored.

That makes the write and the read **one contract**, and both ends bind `EventState.CANCELLED.value`
rather than typing the string. A literal that drifted on the write side would leave every task whose
due journal was cancelled quietly un-lapsed, with no query failing — which is why the two are
compared against each other in a unit test rather than each against the enum.

**Cancelling a journal changes nothing about a task.** Not its status, not its text, and none of its
links — the anchors and the intermediate and contact rows are untouched, because the cancellation
writes only to `journal_calendar_info` and the external link. The task stays on every journal it was
on and simply reads as lapsed, which is the specification's stance: cancellation is the escape hatch
the delete guard steers users toward, so it must never be refused for a journal that anchors a task
whatever that task's status. Pinned end to end in
`tests/integration/tasks/test_journal_cancellation_lapse_integration.py`, which drives both real
cancellation routes rather than writing the calendar-info row itself.

**One read per collection**, for the same reason: the read model's assembler is a *pure function over
pieces already fetched*, so a list surface can load *N* tasks' journals in one query and call it once
per task. The single-task path costs a fixed **seven** statements regardless of how many journals or
contacts a task has — the task, its mentions, its contact links, the timezone, the journals for all
three roles together, the cancellation lookup, and the contact names. One per thing that has to be
known, and nothing repeated.

A missing **anchor** journal raises `JournalNotFoundError` rather than being papered over: the due
journal is what the rule reads, so losing it would make the verdict a guess. A missing **mention** is
skipped, because a task the user cannot open is worse than one showing one fewer journal. Both
anchors are `ON DELETE RESTRICT`, so neither branch is reachable in practice.

### A journal's tasks, by link role

`TaskReadService.read_models_for_journal` answers the surface a journal's detail view needs: every
task linked to a journal, grouped as the
[specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#where-tasks-appear)
asks — due here, created here, mentioned here.

**A role is derived, never stored.** There is no role column and no fourth link table:
`group_tasks_by_link_role` (`core_shared/models/tasks/link_role.py`) reads `due` from the task's due
anchor, `created` from its creating anchor and `mentioned` from its intermediate refs — all three
already on the read model. Storing the role would be a second copy of the anchors that could disagree
with them, and filtering by role in SQL would be a second definition of "mentioned here". So the
filter is applied to the grouping, not to the query.

**A task can hold two roles at once.** Invariant 6 lets one journal be both anchors, and retargeting
onto a journal the task already mentioned leaves the intermediate row beside the new due anchor. Both
groups list it, and `JournalTaskGroups.tasks` de-duplicates for the transport that needs each
resource once.

**The batched reads are what keep this off an N+1.** `find_tasks_for_journal` unions the three link
shapes with an `EXISTS` rather than a join, so a two-role task is one row;
`list_intermediate_journal_ids_for_tasks` and `list_contact_ids_for_tasks` read *N* tasks' links in
one statement each, over a single `integer[]` rather than a placeholder per id. They scope themselves
through a join back to `tasks` — the link tables carry no `user_id` — and, unlike their singular
forms, **return rather than raise** for a task that is absent or not the caller's: those are given
ids an owner-scoped query produced, so a missing key means "no links" and raising would let one
deleted task fail a whole page. A task with no links is absent from the mapping rather than present
with an empty list. The whole listing costs the same statements the single read does, **whatever the
task count** — seven where any task references a contact, six where none does, and four for a journal
with no tasks at all, since the contact-name lookup and the two batched link reads each skip a query
they have nothing to ask. Invariance in the task count is the claim that matters and the one the tests
pin, at two and six. The single read is now literally the batch with one task in it.

**Ownership costs no extra statement.** The viewed journal joins the same owner-scoped journal fetch
the read models already need. An unknown journal and another user's are the same absence and the same
`JournalNotFoundError`; a journal of the caller's with nothing linked to it is a 200 with three empty
groups.

**Ordering is total, and that is the point.** Groups are ordered by due-journal date then task id;
a task's mentions and contacts by link `created_at` then the linked id. Phase 10 recorded that
`created_at` defaults to `transaction_timestamp()`, so links written in one request tie — an order
stopping there would let the same read answer differently between runs. In the *due* group every task
shares the journal's date, so the id is not a last-resort tie-break but the whole of that group's
order.

**Every linked task is listed, in every status** — done, cancelled and lapsed included. A journal is
where a lapsed task is meant to be found again, so the lapse is a marker on the row rather than a
filter; the dashboard's tasks section is the surface that excludes them.

### The journal list's tasks-due indicator

`TaskReadService.due_task_counts` answers one question for a whole page of journals: how many live
commitments is each of them waiting on. It is what `GET /api/journals` renders as
`tasks_due_count`, and the
[specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#where-tasks-appear)
asks for it as a "lightweight indicator that a journal has tasks due in it, consistent with the
other list-level indicators".

**A count, not a boolean.** `COUNT(*) … GROUP BY` returns the number for the same price as the
existence check, and it is the number the user is weighing when they scan a list — one commitment
against five. It also makes the surface assertable in a way a flag is not: a task holding two roles
in one journal must be counted **once**, which a boolean could never show.

**The lapse rule collapses here, and that is what makes it cheap.** Everywhere else the verdict needs
a task's due journal fetched alongside it; on the listing the due journal **is** the row journal,
already loaded. So "would a not-done task due here be lapsed?" is a question about the journal, asked
once per row through `derive_lapse_reason` rather than re-derived. Nothing about lapsing is written
in SQL — the same stance `find_upcoming_tasks` takes, and for the stronger reason here that the
journal list is the busiest read in the product and a second definition of *lapsed* on it would drift
first.

**Three statements when something is due, one when nothing is, and neither grows with the page.**

| Step | Statement | Skipped when |
|---|---|---|
| `TaskRepository.count_not_done_tasks_by_due_journal` | ids as one `integer[]`, `GROUP BY due_journal_id` | the page is empty |
| `JournalDateResolver.timezone_for` | the user's configured zone, read once | nothing is due |
| `CalendarInfoRepository.find_cancelled_journal_ids` | narrowed to the ids that *have* counts | nothing is due |

The short-circuit is the important one: most journals hold no tasks, so the ordinary page pays
exactly the single query the acceptance criterion asks for, and the cancellation lookup is never
asked about rows that could not change the answer.

**Only the due anchor counts.** A journal a task was created in, or merely mentions, is not waiting
on it — so neither `creating_journal_id` nor `task_intermediate_journals` is consulted, and a task
holding two roles in one journal needs no de-duplication to be counted once.

**The count is owner-scoped and the joins elsewhere in that repository are not.** Nothing in the
schema compares a task's owner with its anchor journals' owner, so without the predicate one user's
commitments could count towards another's indicator. The methods that stand in for foreign-key checks
(`TaskAnchorRepository`) must see every row; a user-facing listing must see only one user's.

**Journals with nothing due are absent from the mapping**, not present with a zero — the convention
the batched link reads already follow — and the controller reads through `.get(journal_id, 0)`. The
journals controller injects `TaskReadService`, never `TaskService`: it needs to know how many
commitments a journal is waiting on, and must not be handed the ability to change one to find out.

**No MCP surface.** Delivery rule 5 is about capabilities, and this adds none an agent lacks —
`list_journal_tasks` already returns a journal's tasks grouped by role, which is strictly more than a
count. The sibling list-level indicator `has_pending_reviews` is REST-only for the same reason, and
MCP's list analogue `browse_journals_by_date_window` anchors its window on `datetime.now(UTC)` rather
than the configured zone, so a timezone-derived lapse verdict on that payload would disagree with
itself about what day it is. That is a defect worth fixing on its own terms.

### Upcoming important dates

`UpcomingImportantDatesService.upcoming_dates` answers "whose birthdays and anniversaries are coming
up": the [specification's](../product-specifications/home-dashboard-and-tasks-product-specification.md)
upcoming-dates section, over **the same seven days** the tasks section covers. Three callers share it —
the home dashboard's section, the MCP tool `list_upcoming_important_dates`, and the daily summary's
current-day inputs — which is why it lives in the contacts domain rather than in the dashboard's.

**The recurrence is a rule, not a column, so it does not go into SQL.** A stored important date is a
month and a day, sometimes with a year, so "does it fall in the next seven days" cannot be a `BETWEEN`.
What the database is asked instead is the narrow question it can answer cheaply: **which stored
`(month, day)` pairs could land in this window** — at most 91, and eight for the week the dashboard
shows. `resolve_occurrence` (`core_shared/models/contacts/important_date_occurrence.py`) then decides
which of those actually do, in which year, and what count of years they make. Putting any of that in
the statement would be a second definition of a rule that has 56 unit tests, in a place none of them
could reach.

**The candidate set is not simply the window's days, and the exception is the leap day.** A row stored
as 29 February is *observed* on **28 February** in a year that has no 29th, so its occurrence date and
its stored pair are different. A filter built from the literal pairs the window spells would never
fetch the row — and a leap-day birthday would be absent from the section in three years out of four,
**silently**, because a row that is never fetched cannot be reported as dropped. `window_month_days`
adds `(2, 29)` exactly when the window covers a 28 February that is not itself a leap day. Nothing
broader is needed: a real 29 February is already one of the window's own days, and every other
unplaceable pair (30 February, 31 April) yields no occurrence at all.

**The pairs reach the statement as two parallel integer arrays**, joined through a multi-argument
`unnest`. Not a literal `IN (VALUES …)` list, which would build a different statement for every window
length; and not two independent `= ANY` filters on month and day, which would match 3 August for a
window covering 14 September — the pair must be matched as a pair.

**Two statements, and one for a quiet week.** The candidate query is one; Phase 10's batched
`ContactImportanceRepository.for_contacts` is the other, and it short-circuits without a round trip on
an empty batch. The signals batch is keyed off the **candidates** rather than the survivors, which
keeps the recurrence rule to a single pass — the two sets are provably the same set, since a row only
becomes a candidate by matching a day the window covers.

**Ordering is date ascending then contact importance descending, in one pass.**
`ContactImportance.ranking_key` negates its signals for exactly this, so
`(occurs_on, *ranking_key, contact_id, date_id)` sorts ascending throughout rather than needing a
second sort or a `reverse` that would flip the date too. Importance breaks ties *within* a day and
never reorders the days. The trailing pair is load-bearing rather than defensive: a week routinely
holds two dates on one day, two contacts with identical signals are ordinary, and without it the same
request could answer in a different order between runs — which a user sees as the list shuffling
itself.

**Importance is inferred, and it stays off the wire.** The signals are the favourite flag, the recent
journal count and the recent activity count, in that precedence — `CONTACT_IMPORTANCE_ORDER`, which the
MeiliSearch contact ranking rules also derive from, so a contact who ranks highly in search ranks
highly here and the section still ranks with search down. The specification requires importance to
remain unconfigured; no surface publishes the numbers, and a test pins the exact field set of a row so
one cannot start to.

**Whose today is the caller's when the caller knows.** The service takes `today` and resolves its own
only when nobody supplies one, so the dashboard — which resolves a single anchor for all four
sections — causes no second settings read and cannot land this section on a different day from the
agenda beside it. This is the structural form of ITER18-001 Phase 14's bug, which read the clock twice
and could build a window against one day while judging its rows against the next.

**The summary's assembler is the third caller, and it supplies both.** `DailySummaryInputAssembler`
gathers this for the **current day only** — the guard the agenda and the week's tasks already have,
so a past-day summary costs no extra round trip — and hands down `today` *and* `now`. The two pin
different things and a caller needs both: `today` fixes the day and, because it is supplied, the
service resolves none of its own, so the request makes no second `user_settings` statement to disagree
with the first; `now` is what the importance signals measure their thirty-day recency back from, which
`today` says nothing about. Supplying one and not the other leaves half the answer sampling its own
clock — the defect this read's own review found twice. There is no timezone to pass, unlike the tasks
listing: `today` **is** the resolved answer, so nothing is left for a zone to decide.
`None` and an empty answer stay distinct all the way into the prompt: not gathered versus gathered and
quiet, and only the second is a fact about the user's week.

**Not scoped by user.** `contacts` has no owner column in this schema and every other contacts
repository is likewise unscoped, so this port diverges from the dashboard ports' rule that every method
takes a `user_id` — recorded rather than left silent. When contacts gain an owner, this read, the
importance read and their callers are one change.

**Uncapped, like the tasks window.** The whole window travels with its total and the card applies the
cap (three), so a show-more costs no second request. `days_ahead` is bounded at 90 by the shared
window, in the domain as well as on each surface.

### The upcoming window

`TaskReadService.read_models_for_upcoming_window` answers the other half of "where tasks appear": the
[specification's](../product-specifications/home-dashboard-and-tasks-product-specification.md#tasks)
dashboard section — not-done tasks whose due journal falls between **today and seven days ahead,
inclusive**, soonest first. It is the only task listing that reaches across journals, and it is the
query ITER18-004's tasks section consumes, which is why its shape is settled here rather than there.

**The window is arithmetic, and it is pure.** `upcoming_window` and `select_upcoming_tasks`
(`core_shared/models/tasks/upcoming.py`) take a date the caller resolved and the models the caller
assembled, and hold the whole rule: where the window starts and ends, which tasks it drops, and what
order the survivors come back in.

**One window type, two domains, two error vocabularies.** `UpcomingWindow`, `upcoming_window` and the
bound live in `core_shared/models/date_window.py`, not in the tasks domain that first needed them.
ITER18-004's upcoming-dates section covers "the next seven days, **matching the tasks window**", so
these are not two similar spans but one span two sections must agree on — a second definition would be
two rules that happen to agree today. What each domain keeps is the **translation**: the shared module
raises a neutral `DateWindowError`, `tasks/upcoming.py` converts it to `TaskValidationError` and the
contacts side to `ContactValidationError`, because a re-export could not do that — `except
TaskValidationError` does not catch a `DateWindowError`, and a contacts endpoint answering with a task
error would be nonsense. Every existing import goes through the `core_shared.models.tasks` package
`__init__`, so the promotion moved no call site and the tasks window's tests passed unedited, which is
what makes it a refactor rather than a claim. `select_upcoming_tasks` returns an `UpcomingTasks` carrying the
window beside the tasks — the same shape `group_tasks_by_link_role` returns its `journal_id` in, and
for the same reason: a surface renders "the next seven days" as well as the rows, and an **empty**
answer has no rows to derive the window from.

**Today is in the window, and the future-dated invariant excludes it.** The two rules disagree about
today deliberately, and conflating them is the likely mistake: `is_future_dated` asks whether a
journal may *become* a deadline, and this asks whether a deadline is coming up. A task written
yesterday for today is exactly what the dashboard is for.

**Whose today is decided once, in the service, and never in SQL.** The timezone is resolved through
`JournalDateResolver.timezone_for` and shared by the window *and* the assembler — `_assemble` takes it
as a parameter rather than looking it up, so one request cannot straddle a settings change or pay for
two reads. `local_window` then turns the inclusive date span into local midnight on the first day
through the final microsecond of the last, and those instants are what the query compares against
`journals.event_date_range_start`. Pushing the conversion into SQL would put a second definition of
"a journal's date" in the database, one no unit test could reach.

**A day's last instant is derived from the next day's midnight, and that is not a stylistic choice.**
In a zone whose clocks go back *at* midnight — Santiago, Beirut, Asunción — the local wall time
`23:59:59.999999` names two different instants, and `ZoneInfo` resolves the ambiguity to the earlier
one. A window built from it closes an hour before the day does, and since SQL compares instants while
the pure rule compares dates, the two disagree: a real journal inside the window is dropped by the
query and nothing reports it. The following midnight has no such ambiguity, because the first instant
of a day is unique however the clocks moved. Found by review after the phase had argued that
disagreement was impossible.

**Three exclusions, and only one of them can actually bite.** The statement filters *status*, so done
and cancelled tasks never arrive. The pure rule then drops anything `lapsed`, reading the verdict
`build_task_read_model` derived rather than recomputing it — and inside a *forward* window a
date-passed lapse is impossible by construction, since the window starts today. So the **cancelled due
journal** is the only fixture that makes the lapse check non-vacuous, and it is required at every test
level: remove the check and that one case is the only failure. The excluded task is not lost — it stays
on every journal it is linked to, marked and retargetable, which is the pair the specification promises.

**The batched reads are the journal listing's, reused whole.** `find_upcoming_tasks` is one statement —
an inner join to `journals` on the due anchor, which is `NOT NULL` and `ON DELETE RESTRICT` so it can
neither drop nor duplicate a task — and everything after it is `_assemble`. The listing therefore costs
the same seven statements a journal's does, invariant in the task count, with a floor of **two** for an
empty window, where every batch below has no ids to ask about.

**Ordering is total, and the pure rule owns it.** By due-journal *date* then task id, matching the
journal listing exactly so the same tasks read the same way on both surfaces. The query orders too, by
the raw timestamp, which is not the same key: two journals on one local day at different hours tie in
the rule and do not in the query. The rule's order is the one that reaches a client.

**Bounded, not paginated.** `days_ahead` is capped at 90 in the domain rule as well as on both
surfaces, so the cap cannot be sidestepped by reaching the service another way, and the whole window is
returned uncapped within it — ITER18-004 settles that the dashboard's five-item cap is the UI's, so its
*show more* costs no second request. There is deliberately no unbounded task listing anywhere in this
product, and this is the endpoint that would most easily become one.

**Its second caller is the daily summary, and that settled where the DI edge goes.**
`DailySummaryInputAssembler` gathers the current day's forward-looking input by calling this listing rather
than querying tasks itself, so the summary and the dashboard's tasks section cannot disagree about what the
user has coming up. The read itself stays where it is — these are task rows, and the summary is a caller,
not an owner, which is the mirror of the argument that moved the *agenda* read into the journal domain. What
moved instead is the provider edge: `JournalProvider` consumes `TaskReadService` from `TaskProvider`.

That reverses a stance recorded in two DI docstrings, and the condition attached to it is why. Those
factories build tasks-domain objects by hand so that a container registering one provider need not register
the other, on the stated grounds that *"it needs nothing but the connection, so there is no graph cost"* —
and both still need nothing but the connection, so both stay. `TaskReadService` needs five collaborators
from three domains, so hand-building it would mean reaching around the container for two other domains'
adapters and would produce a second instance beside the one `TaskProvider` already provides. **A provider
reaching around the container for another domain's adapter is usually a boundary complaining; needing to do
it twice for one object is the boundary saying the edge belongs in the graph.** Providers may require each
other in both directions — Dishka validates a graph of *types*, and that graph stays acyclic because
everything the tasks domain reaches for is a journal port and none of it reaches back.

**A caller of this listing must hand it both halves of "which day is it" — the instant and the zone.**
`read_models_for_upcoming_window` defaults `now` to the wall clock and `timezone` to a `user_settings`
read, which is right for a surface that asks nothing else and wrong for a caller that has already asked.
The summary's assembler has asked both: it decides whether the day it is summarising is today before it
calls at all. Leaving either to default gives that request two readings — of the clock, which can straddle
local midnight, and of the settings row, which is a **second statement** under READ COMMITTED and so can
see a timezone change the first did not. The second is the one that took a review to spot, because the
first cut argued the two reads could not disagree on the grounds that they hit the same row in the same
request: true of the row, false of the reads. One reading per request, passed down, is the rule — the same
one the service applies internally when `_assemble` takes `today` and `timezone` as parameters rather than
looking them up. The three sibling reads still resolve their own, because every caller of those resolves
no timezone of its own and so has nothing to disagree with.

### The past-day resolution read

`TaskReadService.read_models_due_in_journals` answers the question the daily summary asks about a day
that has already happened: *what was due in these journals, and what became of each of it?* It is the
fourth task listing and, unlike the three above it, applies **no exclusions at all**.

**The absent status filter is the method.** `find_upcoming_tasks` and `count_not_done_tasks_by_due_journal`
both filter `status = NOT_DONE`, because a finished commitment is neither upcoming nor live. Here a
finished commitment is the answer — *done* and *cancelled* are two of the three resolutions a past day can
report — so `TaskRepository.find_tasks_due_in_journals` is a **sibling** query rather than a widening of
either. Widening one would falsify a contract its own callers depend on, and the single most likely way to
write this query wrong is to copy its neighbour's `WHERE` clause whole; a mutation check pins that.

**The status is current and is never reconstructed.** Nothing replays `field_history` to rebuild what was
true at the end of the day being summarised. The consequence is deliberate: a past-day summary regenerated
after a lapsed task was finally completed describes it as **done**. That is the honest answer to "what
became of this" and, more decisively, it is what the user already sees on the journal — a summary
insisting the commitment was still outstanding would be the surface contradicting the product. It is
stated in the port, the read service, the input field and the prompt, and the prompt tells the *model* so
too, because a model reading "done" beside a past date and not told otherwise will narrate the user
finishing it on the day.

**The day arrives as journal ids, not as a date window** — the one place this listing's shape differs from
the upcoming window's, and the reason is which journals a day *has*. `DailySummaryInputAssembler` selects
them by **overlap** (`event_date_range_end >= day_start AND event_date_range_start <= day_end`), so a
three-day trip that began on Sunday is one of Tuesday's journals and the summary describes it as such. A
window over `journals.event_date_range_start`, which is what `find_upcoming_tasks` takes, would answer for
a quietly different set than the prompt goes on to name. Passing the ids also makes the empty day free: the
listing short-circuits before any query, so the assembler's guard stays purely about *which day it is*.

**Only the due anchor qualifies**, as on the journal listing's counter. A journal a task was created in or
merely mentions did not have it due, and the creating anchor is nearly always in the past — a read
consulting it would attribute half a user's commitments to whatever day they were first written down. A
task retargeted off the day is absent for the same reason, and retargeting is exactly what leaves the old
due journal behind as an *intermediate* link, which is the shape that would catch a read consulting the
wrong table.

**Everything else is `_assemble`, reused whole**: the batched journal, cancellation and contact reads, the
lapse derivation and the one-read-per-collection guarantee. The lapse is not an exclusion here but part of
the answer — *how* an unfinished commitment lapsed is what the summary reports, and the two causes are
worded apart because "the day went by" and "the meeting was called off" ask the user for different things.
Ordering is the query's — due-journal start, then task id, the day's own sequence — and is not re-sorted
in the service, because a second ordering could disagree with the first.

**Its guard and the upcoming window's are exclusive**, which is what keeps a task out of two sections of
one prompt: `summary_date < today` reaches this listing, `summary_date == today` reaches that one, and a
future day reaches neither. Both halves of "which day is it" are injectable here from the start rather
than added by review, for the reason the paragraph above gives.

### The journal delete guard

A task can never exist without both of its journal anchors, so the
[specification](../product-specifications/home-dashboard-and-tasks-product-specification.md#deletion)
**blocks** deleting a journal that is any task's creating or due journal — whatever that task's status,
because a done task's link to the journal it was created in is part of the record. Deleting a journal a
task merely *mentions* stays permitted; the intermediate link row cascades away with the journal.

The database already refuses these deletes on its own (both anchors are `ON DELETE RESTRICT`). The guard
exists because a constraint name is not something a user or an agent can act on:
`JournalService.delete_journal` calls `TaskAnchorRepository.find_tasks_anchored_to_journal` and raises
`JournalHasAnchoredTasksError` (409, matching the journal domain's `RouteInUseError`) naming each
blocking task and the journal it can be actioned from.

Four decisions are worth knowing before changing it:

- **The rule is pure and lives in the journal domain**
  (`core_shared/core_shared/models/journals/task_anchor.py`). Which roles block, and which anchor
  supplies the *action journal* — the due journal, or the creating journal when the due journal is the
  one being deleted — are decided there, not in SQL, so both are unit-testable. Keeping `BlockingTask`
  in the journal package also keeps `core_shared.models.tasks` free of any journal import, so the task
  read models still to come cannot create a cycle between two eagerly re-exporting packages.
- **The query is not owner-scoped**, uniquely among task reads. It stands in for a foreign-key check, so
  a row it filtered away would return as the raw `IntegrityError` the guard replaces. The delete path is
  itself unscoped, so nothing new is exposed.
- **`task_anchor_repo` is a required keyword-only argument** to `JournalService`, not another optional
  collaborator: an absent guard would let a delete leave the model in a state the specification says is
  impossible. Keyword-only so existing positional construction sites still compile while the type checker
  names every one that must supply it.
- **`SqlTaskAnchorRepository` is provided by `JournalProvider`**, not `TaskProvider`, even though the
  port and adapter belong to the tasks domain. Dishka validates the whole graph at construction, so
  taking the dependency the other way would force every container registering one provider to register
  the other. The adapter needs only the connection, so `JournalProvider` stays self-sufficient.

**The refusal reaches both surfaces as data, from one builder.** The specification requires the same
failure over REST and MCP, "so an agent can resolve them without going through the UI" — which means
ids rather than a sentence to parse. `JournalHasAnchoredTasksError` therefore overrides
`DomainError.error_meta()` (see [API Design → Structured Error
Detail](api-design.md#structured-error-detail-errorsmeta)), serialising each blocker through
`blocking_task_payload` in `task_anchor.py`:

| Surface | Where it lands |
|---|---|
| `DELETE /api/journals/{id}` | 409, JSON:API `errors[0].meta` — `journal_id` plus `blocking_tasks` |
| MCP `delete_journal` | tool payload with `code: "JOURNAL_HAS_ANCHORED_TASKS"` and the same two keys |

Each blocker carries `task_id`, `text`, `status`, `blocking_roles` (`creating` and/or `due`) and the
`action_journal_id` **and** `action_journal_title` — id *and* title, so a client renders the link and
follows it without a second request. The prose message stays in `detail`/`message` alongside it: the
payload is for the client, the sentence is for the person.

Two placements are load-bearing and each has a test that fails without it. The serialiser is
**one function** rather than one per surface, because two surfaces disagreeing about the same failure
is the failure mode worth designing out; and the MCP decorator's `except JournalHasAnchoredTasksError`
sits **above** its `JournalDomainError` catch-all, which would otherwise flatten the refusal back to
its message.

The guard is check-then-act, so `delete_journal` also wraps the delete **in a SAVEPOINT**: an
`IntegrityError` re-runs the guard and raises the same explanatory error for a task inserted in the
window, and re-raises untouched when the re-check comes back empty, so an unrelated constraint is never
reported as a task conflict. The savepoint is load-bearing rather than defensive — a failed statement
poisons its transaction, so without it PostgreSQL would refuse the re-read and the caller would get an
aborted transaction instead of an explanation.

`JournalOutboxEventProcessor` catches the error when a cancelled calendar series would delete a
far-future instance — exactly the profile of a task's due journal — and marks the instance cancelled
instead. Cancellation is the escape hatch the guard steers users toward, and a user's commitment outranks
a sync tidy-up.

Journal **merge** is deliberately not guarded: it deletes the absorbed journal through
`JournalRepository.delete` directly, and blocking it would break the calendar-sync workflows the journals
specification depends on. Re-pointing task links through a merge is ITER18-002 Phase 3.

### A contact merge carries the task's people

A contact merge had the *opposite* failure to the journal delete guard's, and it is the more
instructive one because nothing failed. `task_contacts.contact_id` is `ON DELETE CASCADE` — right for
deleting a contact, silently wrong for merging one — and `ContactMergeService.merge_contacts` ends by
deleting the absorbed contact. So a merge destroyed every task link that person held: a task that
referenced them ended up referencing nobody, with no error anywhere. It survived thirty-one phases
across two iterations (ITER18-006 Phase 1 closes it).

**The general lesson, which outlives this fix: a merge is a list of tables, and every new table
referencing the merged entity is a line somebody has to remember to add.** `task_contacts` arrived two
iterations after the rest of that list. Nothing in the schema, the tests or the type checker notices
the omission, because a cascade is not an error.

The shape mirrors the journal merge's re-point exactly, one layer at a time:

- `ContactMergeService` calls `TaskContactMergeService.repoint_contact_links(...)` — step **0**, its
  first write, and inside the merge's existing unit of work, so a failed merge leaves the links as
  they were. The contacts domain does not construct task events, for the reason the journal domain
  does not.
- `TaskContactRepository.repoint_contact_links` (`SqlTaskContactRepository`) runs **two** statements,
  and the order is the design: delete the absorbed contact's link where the task already holds the
  survivor's, so the re-point cannot violate `PRIMARY KEY (task_id, contact_id)` — `ON CONFLICT`
  cannot rescue an `UPDATE` — then re-point what is left. Both carry `RETURNING`, joined back to
  `tasks` for the owner id the event needs and the merge never read.
- Both contacts are taken `FOR UPDATE` in **ascending id order** first. Inserting a task link takes
  `FOR KEY SHARE` on the contact row to hold its own foreign key, and `FOR UPDATE` is the weakest mode
  conflicting with it: without the lock a concurrent `link_contact` could attach to the absorbed
  contact after the re-point and before the delete, and the cascade would take that link — the same
  defect through a narrower window. Ascending id rather than source-then-survivor so two merges of the
  same pair in opposite directions queue instead of deadlocking.
  **The sort is worthless without the step-0 placement**, which is the half worth remembering: every
  other re-point in the merge writes the survivor's id into a table referencing `contacts`, taking
  `FOR KEY SHARE` on the survivor's row to validate the foreign key. Run after them, two merges into
  one survivor would both hold `KEY SHARE` and both ask for `FOR UPDATE` — a deadlock rather than a
  queue. This is why the journal re-point is also the first write in `merge_journals`.
- The port returns `list[TaskContactRepointing]` in task-id order, and `TaskContactMergeService`
  publishes one **`TaskUpdated`** per summary. The pair of facts is asymmetric: every reported task
  lost the absorbed contact's link, so that departure is implicit, and what varies is whether it
  *gained* the survivor's — it did not when it already had one and the duplicate was collapsed.

**It reuses `TaskUpdated` where the journal merge got its own type**, and the difference is what each
merge changes. A journal merge moves *anchors*, which no other write does, and can delete links; a
contact merge only changes which people a task references, which is exactly what a link and an unlink
already change — so its rows land under the same `contact:{id}` keys, and a merge's removal reads as
the same kind of line as a person's. The cost is real and stated in the event's docstring: the payload
does not say *which* merge moved the task, where `TaskJournalLinksRepointed` names both journals.

`SqlTaskContactRepository` is provided by **`ContactProvider`**, not `TaskProvider`, for the reason
`SqlTaskAnchorRepository` is provided by `JournalProvider`: Dishka validates the whole graph at
construction, and taking the dependency the other way would force every container registering one
provider to register the other.

**The records those links had already written move too** (ITER18-006 Phase 2), and they need a
second statement because they are addressed by a different column.
`FieldHistoryRepository.repoint_entity_history` finds a contact's own rows by `entity_id`; a
person's record of a task is an `entity_type='task'` row that names them only in its field name, so
`repoint_contact_task_history` matches `contact:{absorbed}` and rewrites it to `contact:{survivor}`.
It is called from the merge beside the other history re-point, and lives on the history port rather
than a tasks one because that domain already owns the read half — the contact aggregation predicate
selects a person's task records by that same field name.

**Leaving them would have been the destructive choice.** `field_history` has no foreign key to
`contacts`, so a merge does not delete these rows, it strands them: nothing raises, and no query can
reach them again once the id in their field name is gone. That is the failure mode this whole
sub-iteration is about — the link half was a cascade nobody saw, and the history half is a row
nobody can read — and it is why the merge specification's *non-destructive history* is satisfied by
rewriting rather than by leaving well alone.

**One row is deliberately left where the projection puts it.** The `TaskUpdated` above names the
absorbed contact leaving, and is projected *after* the merge commits, so no statement inside the
merge can reach it. It stays: a task's own history reads every field name filed against it, so that
row is the task's record of who it used to reference, and moving it onto the survivor would render
as a removal beside the arrival from the same merge. The rewrite therefore runs inside the merge
transaction and the later row is out of its scope by design, not by omission.

### Incomplete Outdoor Activities Review (read projection)

The incomplete review is a **pure read projection** over existing tables — no new journal state, no
"incomplete" column. It is composed of three parts:

- **Facts repository** (`IncompleteOutdoorActivityRepository` port +
  `SqlIncompleteOutdoorActivityRepository` adapter): one user-scoped query anchored on
  `journal_outdoor_activity_data`, LEFT JOINing each outdoor subtype table (1:1 on `journal_id`, so no
  fan-out) plus PARTICIPANT and abseil-pitch counts, returning per-journal `OutdoorActivityFacts`.
- **Pure rule evaluator** (`evaluate_incompleteness` in
  `core_shared/core_shared/models/journals/incomplete_outdoor_activity.py`): applies the three product
  rules — *no attributes set* (a present subtype row whose own fillable fields are all unset; fields
  are derived from the subtype dataclasses via `fillable_fields`, so fieldless subtypes are exempt by
  construction and a subtype gaining a column self-maintains), *missing template*
  (`abseiling_data.template_id IS NULL`), and *no participants* (non-bushwalking-only journals with
  zero PARTICIPANT contacts). Rules live in Python, not SQL, so they are unit-testable without a
  database.
- **Read service** (`IncompleteOutdoorActivityService`): fetches facts, filters out journals in the
  dismissal store above (`list_dismissed_journal_ids`), evaluates the rules, and returns entries
  newest-first. Read-only — no `@transactional`, controllers/MCP consume it directly (exposure ships
  in the ITER16-002 REST/MCP phase).

A guard test (`backend/tests/unit/journal/test_incomplete_projection_registry.py`) keeps the
registry, the facts dataclass, and the generated SQL SELECT list aligned with the subtype models.

## Key Architectural Principles

1. **Domain Isolation**: Each domain is self-contained with its own entities, services, and adapters
2. **Dependency Inversion**: Domains define ports (interfaces), adapters implement them
3. **Single Responsibility**: Each adapter has a single, well-defined responsibility
4. **Cross-Domain Operations**: Handled explicitly in the sync domain
5. **API Separation**: REST and MCP adapters are separate from domain logic

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Database Design](./database-design.md) - Detailed database schema and data layer
- [API Design](./api-design.md) - REST and MCP API implementation patterns
- [Frontend Design](./frontend-design.md) - Component patterns and UI guidelines
- [Testing Strategy](./testing-strategy.md) - Comprehensive testing patterns
- [Technology Stack](./technology-stack.md) - Technology choices and implementation details
- [Deployment Guide](./deployment-guide.md) - Infrastructure and deployment configuration
