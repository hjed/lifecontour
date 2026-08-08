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
- **Domain Services**: ContactValidationService, TagHierarchyService, ContactHistoryService, AddressValidationService
- **Ports**: ContactRepository, TagRepository, ContactHistoryRepository, ContactEventPublisher
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
  request scope by `TaskProvider` (`backend/app/infrastructure/di/tasks.py`); and
  `TaskAnchorRepository` in the same module, implemented by `SqlTaskAnchorRepository`
  (`backend/app/core/tasks/adapters/sql/task_anchor_repository.py`) — see
  *[The journal delete guard](#the-journal-delete-guard)* below
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
  link operations reach the owner through the task they belong to, and that check takes
  `FOR KEY SHARE` so a concurrent delete cannot turn the promised `TaskNotFoundError` into a raw
  foreign-key violation. The repository is responsible for persistence and task ownership only; every
  other invariant is the service layer's.
  **Contact links are written in batch.** `add_contacts(task_id, contact_ids, user_id)` takes the
  ownership guard once and inserts every link in one statement, returning the ids for which a row was
  actually created. The singular `add_contact` it replaced made the guard the expensive half — *N*
  contacts cost *2N* statements — and the batch is what `TaskService.create_task` and the
  single-contact link surface both use. `remove_contact` stays singular: nothing removes in bulk.
- **Domain Events**: `TaskCreated` and `TaskDeleted`
  (`backend/app/core/tasks/models/events.py`), published by `TaskService` through
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
  The remaining event types the specification names — text updated, status changed, due journal
  retargeted, journal and contact linked/unlinked — and the history projection that consumes all of
  them arrive in later phases of
  [iteration 18](../tasks/iteration-18-home-dashboard-and-tasks.md). Until then **no consumer group
  subscribes to a task event**: `SearchIndexerConsumer` and `HistoryProjectionConsumer` match event
  types exactly and list none, `InboundEventConsumer`'s patterns are all prefixes of other domains,
  and `SummaryConsumer` is contact-scoped. `StreamConsumer` acknowledges an unmatched event
  immediately, so a task event is discarded rather than left pending, and nothing dead-letters. For
  search this is permanent — the specification's *Tasks and search* requires that tasks never be
  indexed and that the indexer ignore their events rather than fail on them.

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
domain can import, and the home dashboard's agenda reads journals rather than tasks. **Standing
duplication to collapse:** `OutdoorDashboardService._window` / `._user_timezone` and
`compute_search_window` (`app/core/integrations/immich/album_creation_service.py`) predate this module
and should be migrated onto it; that migration was deliberately kept out of the phase that introduced it.

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
