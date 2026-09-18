# API Design - Personal CRM & Journal System

This document provides comprehensive API design patterns for both REST and MCP interfaces.

## FastAPI REST API Guidelines (Infrastructure Layer)

### Controller Structure (Adapters)

- **Controllers are Adapters**: Convert HTTP requests to application commands
- **Dependency Injection**: Inject application use cases, not domain entities
- **Pydantic Models**: Use for HTTP input/output validation only
- **Error Translation**: Convert domain exceptions to HTTP responses
- **No Business Logic**: Controllers only handle HTTP concerns
- **JSON API Compliance**: Follow specification for response format

### Proper Layering

- **HTTP Layer**: FastAPI controllers, Pydantic models, HTTP status codes
- **Application Layer**: Use case classes injected into controllers
- **Domain Layer**: Pure Python, no HTTP/FastAPI dependencies
- **Infrastructure Layer**: Database adapters, external API clients

## Input Validation Guidelines

### Pydantic Model Patterns

- Use `BaseModel` for all request/response models
- Add `@validator` decorators for custom validation
- Use `Optional` for nullable fields
- Include clear error messages in validators
- Use `EmailStr` for email validation
- Set sensible defaults for optional fields

## CORS and Proxy Guidelines

### FastAPI CORS Setup

- Use `CORSMiddleware` for cross-origin requests
- Configure allowed origins from environment variables
- Enable credentials for authenticated requests
- Set appropriate headers for nginx proxy compatibility
- Allow common development origins (localhost)

## MCP (Model Context Protocol) Guidelines

### FastMCP 4 Implementation

- **Framework**: Use FastMCP 4 (PrefectHQ/fastmcp, built on the MCP Python SDK v2) instead of the SDK directly
- **Documentation**: Reference https://gofastmcp.com/llms.txt for AI-optimized patterns
- **Integration**: Follow https://gofastmcp.com/deployment/asgi.md for FastAPI integration
- **Protocol eras**: The endpoint serves the sessionless `2026-07-28` protocol and the older session handshake side by side (see [MCP Setup → Protocol Versions](../mcp-setup.md#protocol-versions)). Tools must not depend on session state or server-initiated requests (sampling, elicitation, roots) — the sessionless era has neither
- **SDK field names**: MCP protocol models use snake_case Python fields (`input_schema`, `read_only_hint`); the camelCase names are only their wire aliases. The test suite turns fastmcp's camelCase compatibility bridge off, so a camelCase attribute read fails

### Tool Structure

- Use `@mcp.tool` decorator on async functions
- Define clear function names and docstrings
- Use Pydantic `Field` with `Annotated` for parameter descriptions
- Don't rely on `StrictBool` or other `Strict*` types: fastmcp validates arguments with `strict=False`, which overrides them, so `"true"` arrives as `True`. For a boolean that confirms an action, use `JsonBool` from `app/mcp/shared/arguments.py`, which refuses anything but a JSON `true`/`false`
- Return JSON strings for structured data
- Include comprehensive error handling with try/catch blocks
- Provide AI-friendly responses with context and summaries
- Declare behaviour annotations — see below; a tool without them fails CI

### Tool Annotations (required)

Every tool must tell a client how it behaves, via the four MCP hints
`readOnlyHint`, `destructiveHint`, `idempotentHint` and `openWorldHint`. They
are what a client uses to decide whether a call needs confirmation, whether a
retry is safe, and whether it reaches outside this system. All four are
optional to FastMCP and default to *unset*, which a client has to read as
"assume the worst" — so declaring them is not optional here.

Rather than repeat four booleans per tool, cite one of the presets in
`app/mcp/shared/annotations.py`:

| Preset | readOnly | destructive | idempotent | openWorld | Use for |
|---|---|---|---|---|---|
| `READ_ONLY` | ✅ | ❌ | ✅ | ❌ | reads of our own data |
| `READ_ONLY_EXTERNAL` | ✅ | ❌ | ✅ | ✅ | reads answered by a third party |
| `ADDITIVE_WRITE` | ❌ | ❌ | ❌ | ❌ | creates and toggles — a second call adds again |
| `IDEMPOTENT_WRITE` | ❌ | ❌ | ✅ | ❌ | updates and links — a second call changes nothing |
| `DESTRUCTIVE_WRITE` | ❌ | ✅ | ✅ | ❌ | deletes, merges, unlinks |
| `EXTERNAL_ADDITIVE_WRITE` | ❌ | ❌ | ❌ | ✅ | writes that land in a third-party system |

Pick by what the tool *does*, not what it is called: `toggle_contact_favourite`
is an `ADDITIVE_WRITE`, despite the innocuous name, because a second call undoes
the first. If nothing fits, build a fresh set with `mcp_tool_annotations()`,
whose four arguments are all required.

**AI generation counts as reading.** A tool that produces an AI summary —
`get_daily_summary` today — calls a model and caches what comes back, but is
annotated `READ_ONLY_EXTERNAL`, not as a write. The hints describe the world the
*caller* reasons about, and the cache is not part of it: asking for a summary
gets a summary, and asking again gets the same one. Annotating it as a write
would make a client confirm before what the user experiences as a read. It stays
open-world, because a model is still involved.

Apply the preset with whichever registration pattern the domain uses:

```python
# Module-level tool registered via mcp.add_tool() — journals, series, tasks
@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_task_text", "task")
async def update_task_text(...) -> str: ...

# Closure registered inside register_*_tools() — contacts, integrations
@mcp.tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_contact_tag", "tag")
async def delete_contact_tag(...) -> str: ...
```

`tests/unit/mcp/test_tool_annotations.py` enforces this against the assembled
server, so it covers both patterns. Adding a tool that removes data also means
adding it to that test's `DESTRUCTIVE_TOOLS` list — deliberately manual, so a
destructive tool cannot be introduced without someone saying so.

### Domain-Based Organization

- Organize tools by domain: `app/mcp/domains/{domain}/tools.py`
- Split a domain that outgrows one module into a `tools/` package with one module per area, each with its own `register_{area}_tools(mcp)` that `register_{domain}_tools` calls. The journal domain works this way: `app/mcp/domains/journals/tools/` has `journals.py`, `journal_entries.py`, `search.py`, `activities.py`, `calendars.py` and so on, with helpers more than one area needs in `_shared.py`
- Keep tools as adapters: argument parsing and validation, a call to a service or repository in `app/core`, and the response. SQL and domain rules belong in `app/core`, where the REST controllers can reach them too, not in the tool module
- Separate schemas: `app/mcp/domains/{domain}/schemas.py`
- Register domain tools in main server: `register_{domain}_tools(mcp)`
- Allow future domain expansion (journal, calendar, photos)

### Response Format

- Return JSON strings with structured, AI-friendly data
- Include contextual summaries for AI understanding
- Provide clear error messages with helpful context
- Use consistent field naming across all tools
- Add metadata like IDs, tags, and relationship information

### Authentication Integration

- Share OAuth session authentication with REST API
- Use `SessionAuthMiddleware` for MCP endpoint protection
- Validate session data: `id`, `email`, `name`, `provider`
- Provide user context to tools via request state

### Server Configuration

- Mount MCP server as sub-application in FastAPI
- Use configurable mount path (default: `/mcp-server`)
- Enable/disable via `MCP_ENABLED` environment variable
- Include in application health checks
- Use Streamable HTTP transport for web compatibility

## Conditional Writes (`ETag` / `If-Match`)

The critical update paths support optimistic concurrency, so a second writer
cannot silently overwrite a first writer's edit. It is **opt-in**: a client that
states no precondition writes exactly as it always has.

### The version token

An entity-tag is a truncated SHA-256 of `"<type>:<id>:<updated_at>"`, computed
by `resource_etag()` in `core_shared/core_shared/etag.py`. There is no version
column — every write already bumps `updated_at`. The type and id are folded in
because `now()` is the *transaction* timestamp: rows written together share an
`updated_at` to the microsecond, and a tag over the timestamp alone would
collide across them.

### REST

| Route | Behaviour |
|---|---|
| `GET /api/journals/{id}`, `GET /api/contacts/{id}` | Return an `ETag` response header |
| `PUT`/`PATCH /api/journals/{id}`, `PUT /api/contacts/{id}` | Honour `If-Match`, and stamp the new `ETag` on the 200 |

`If-Match` semantics: absent means write unconditionally; `*` means the resource
need only exist; a list matches if any tag does. Weak tags (`W/"..."`) compare
equal to strong ones, because every tag this system mints is strong and a weak
one can only be a strong tag that a compressing proxy weakened in transit. An
**empty** `If-Match` matches nothing and is refused — the caller asked for a
guarded write, and answering 200 to a guarantee that was never checked is worse.

A failed precondition is `412 Precondition Failed` with code
`PRECONDITION_FAILED` and a `meta.current_etag` to retry with, published in the
OpenAPI schema as `PreconditionFailedErrorResponse`. Nothing is written.

`ETag` is **not** a CORS-safelisted response header, so the CORS middleware
exposes it explicitly (`expose_headers=["ETag"]` in `backend/app/main.py`).
Without that, browser JavaScript at an allowed origin could not read the tag and
so could not send it back in `If-Match`. The `If-Match` *request* header needs
no entry of its own — `allow_headers=["*"]` already covers it. The deployed
frontend reaches the API through the same-origin Next.js `/api` proxy and is
unaffected either way; this is for the origins that call the API directly.

`If-None-Match` / `304 Not Modified` on reads is deliberately **not** supported:
this is conflict detection, not caching.

### MCP

Tools have no headers, so the same token travels as data: reads report
`version`, and `update_journal_entry` / `update_contact` accept
`expected_version`. A conflict comes back as an error payload with
`code: PRECONDITION_FAILED` and `current_version` — named to match
`expected_version` rather than REST's `ETag` — so a model can re-read, re-apply
and retry rather than treating it as a server fault.

### Where the check lives

In the **service layer**, never the controller, so both surfaces share one
implementation (`enforce_etag_precondition`, `backend/app/shared/preconditions.py`).
Controllers pass the caller's precondition through untouched.

The comparison reads the row with `SELECT updated_at ... FOR UPDATE` inside the
write's unit of work. An unlocked read would leave a lost-update window under
READ COMMITTED — two callers can both see the version they expected before
either writes — so the lock is what turns the check into a guarantee. It also
runs **before anything is written**, including the find-or-create of tag rows,
so a refusal leaves nothing behind.

### The tag covers the whole aggregate

A read of a journal returns more than the `journals` row: its types,
type-specific data, tags and contact relationships all appear in the
representation the tag is minted from. A write to any of those child tables
therefore **touches the parent row** (`touch_journal`,
`backend/app/core/journal/adapters/sql/journal_touch.py`), so the tag moves with
anything a client would see.

Without that, a conditional write would be accepted despite a concurrent change
it was meant to catch — and the MCP composite update *replaces* types, tags and
relationships under the caller's precondition, so the change would be clobbered
rather than merely missed.

`now()` is the transaction timestamp, so touching a journal the same transaction
already wrote costs nothing and lands on the same value. **When adding a new
write path for journal child data, touch the parent** or that path becomes a
hole in the guarantee — including bulk rewrites no caller names journal-by-journal,
like merging or deleting a tag, which touch every journal holding it *before* the
assignments stop pointing there.

**Where the aggregate stops.** The tag tracks the journal's own rows and its
*child* rows — types, type-specific data, tag assignments, contact
relationships — whenever they are written by the application's own write paths,
whether a user or an MCP client drove them.

It deliberately does **not** track two things.

*Referenced entities a read merely embeds.* Renaming or recolouring a journal
tag changes the tag resource, not the journals carrying it, and bumping every
one of them would turn a single rename into a mass update. A client that needs
to detect that has the tag's own resource to watch. Assignment changes are a
different matter and are tracked, because they change which tags a journal has.

*Changes applied by an inbound integration sync* — Google Calendar writing
`journal_calendar_info`, or Immich writing the album link that carries a
journal's `PHOTO_ALBUM` type. This one is a genuine trade-off rather than a
definitional line, and it goes this way because **`journals.updated_at` is also
the merge-protection signal**: both integrations decide whether the user edited
a journal since the last sync by comparing it against the link's anchor
(`_has_local_edits`, `_merge_fields_with_protection`), and Immich deliberately
holds the anchor back while a journal is protected. Writing `updated_at` from
inside a sync mixes "the user changed this" with "the sync changed this" and
moves one side of that comparison from within the sync itself — risking silent
loss of a user's edits, which is a far worse failure than the missed detection
it would buy.

The cost is stated plainly: a conditional write will **not** notice a
concurrent inbound sync. Fixing that properly means giving merge protection its
own column so `updated_at` is free to be purely a version, which is a migration
and a change to both integrations — worth doing, but not here.

**Lock ordering matters.** A conditional write takes the journal's lock first
and then writes child rows. A child write that touched the parent afterwards
would take the same two locks in the opposite order, and PostgreSQL would break
the resulting cycle by aborting one transaction with a deadlock — which
`@transactional` does not retry. So every child-write path takes the parent lock
**up front** (`lock_journal`, or the touch itself where it is unconditional),
and all writers queue instead of deadlocking.

## Error Handling Guidelines

### JSON API Error Format

- Use `errors` array with structured error objects
- Include `status`, `title`, and `detail` fields
- Add `source` pointer for validation errors
- Map HTTP status codes to appropriate error types
- Log unexpected errors for debugging

### Structured Error Detail (`errors[].meta`)

Most refusals are fully expressed by their prose — a caller told "journal 4 not
found" has everything it can act on. A few are not: a refusal that names *other*
rows the caller now has to go and deal with leaves it parsing English for ids.

Those errors override `DomainError.error_meta()` (`core_shared/core_shared/exceptions.py`),
returning a dict of plain JSON types. `create_domain_error_response` renders it
as the JSON:API error object's `meta`, and the MCP tool decorator renders the
same dict as the failure payload's context — **one builder, two surfaces**, so a
refusal cannot describe itself differently depending on who asked.

Conventions:

- **Opt-in.** The base implementation returns `None`, which `exclude_none=True`
  drops, so an error that adds nothing keeps exactly the body it has today.
- **Alongside the prose, never instead of it.** `detail` still carries the
  explanation a person reads; `meta` is what a client builds links from.
- **Plain JSON only.** Neither surface applies an encoder that knows about enums
  or dataclasses, so the conversion happens in the builder rather than twice.
- **Both an id and a label** for anything the caller is expected to link to, so
  it can render the link and follow it without a second request.

Two errors use it today, for the two different reasons a refusal outgrows its
prose.

`JournalHasAnchoredTasksError` names **other rows the caller must deal with**:
`DELETE /api/journals/{id}` answers 409 with code `JOURNAL_HAS_ANCHORED_TASKS`
and a `meta.blocking_tasks` list giving each blocking task's id, text, status
and blocking roles, plus the id and title of the journal it can be actioned
from.

`TaskValidationError` names **the field the refusal is about**: every task
write can answer 400 with code `TASK_VALIDATION_ERROR` and `meta.field`. The
name is in the message too — these read `"{field}: ..."` — but a form deciding
which input to mark from an English prefix breaks silently the first time the
wording changes. One code covering several fields is what makes this necessary:
a refusal a client can place from the code alone (`TASK_DUE_JOURNAL_NOT_FUTURE`,
`TASK_JOURNAL_IS_ANCHOR`) needs no meta and has none.

### FastAPI Exception Handling

- Create custom exception handlers for common errors
- Use `HTTPException` for API errors
- Return JSON API compliant error responses
- Handle Pydantic validation errors gracefully
- Provide meaningful error messages for users

## Pagination Guidelines

### JSON API Pagination

- Use `page` and `limit` query parameters
- Include `meta` object with total count and page info
- Provide `links` object with navigation URLs
- Calculate `offset` from page and limit
- Handle edge cases (empty results, invalid pages)
- Use generic types for reusable pagination responses

### Implementation Pattern

- Create reusable pagination models with Pydantic
- Build pagination links dynamically from base URL
- Return both data and metadata in responses
- Use consistent parameter names across endpoints
- Validate page and limit parameters

## Incomplete Outdoor Activities Review Endpoints

The incomplete outdoor activities review (outdoor logbook) is exposed as a
journal sub-resource projection keyed by journal id:

| Verb + path | Purpose | Status |
|---|---|---|
| `GET /api/journals/incomplete-outdoor-activities` | List flagged journals with per-entry `reasons` (`no_attributes`, `missing_template`, `no_participants`), `subtypes`, `event_date_range`, and `dismissed`. Only activities that have already started are listed (one beginning after end-of-today in the user's timezone is a plan, not a gap). `?include_dismissed=true` also returns dismissed journals (flagged `dismissed: true`) so the UI can offer un-dismiss; by default they are excluded | 200 |
| `POST /api/journals/incomplete-outdoor-activities/{journal_id}/dismiss` | Dismiss a journal from the review (provenance recorded as `ui`) | 200; 404 unknown/not-owned |
| `POST /api/journals/incomplete-outdoor-activities/{journal_id}/undismiss` | Restore a journal to the review | 200 (idempotent no-op with `was_dismissed: false` when never dismissed); 404 unknown/not-owned |

Conventions this surface pins down:

- **Action-verb POSTs** mirror the existing `POST /review-items/{id}/dismiss`
  precedent rather than introducing a second style (e.g. `DELETE .../dismissal`).
- **Idempotent undismiss:** 404 is reserved for "journal doesn't exist or isn't
  yours" (checked before the write, so unknown ids never surface as FK errors);
  un-dismissing a never-dismissed journal is a 200 no-op, observable via the
  `was_dismissed` attribute.
- **Unpaginated by design:** the review is a bounded advisory list computed by
  rule evaluation over a single facts query; repo-level limit/offset does not
  apply. The Pagination Guidelines above apply to stored collections, not this
  projection.
- **Transactions:** the controllers pass the request-scoped `AsyncConnection`
  into the `@transactional` dismissal service, which owns the commit —
  controllers never open transactions.

## Outdoor Dashboard Endpoint

The outdoor logbook dashboard is a read-only aggregate over the user's outdoor
activity journals, exposed as a **singleton JSON:API resource**:

| Verb + path | Purpose | Status |
|---|---|---|
| `GET /api/journals/outdoor-dashboard` | The four dashboard sections in one call: `upcoming_activities` (next 30 days, soonest first, capped at 10, outdoor + `OUTDOOR_PLANNING`), `checked_out_gear` (open checkouts, longest out first), `activity_totals` (counts by journal type over rolling 30/365-day windows), and `templates_done` (unique templates referenced by abseiling activities, grouped by template type with per-template done-counts and `template_id` for linking) | 200 |

Conventions this surface pins down:

- **Singleton resource:** resource type `outdoor-dashboards` with the resource
  id set to the user's id (the daily-summary precedent for aggregates that are
  projections keyed by user, not stored entities).
- **Server-side "now":** the endpoint takes no date parameters — the upcoming
  and totals windows are anchored on "today" in the user's configured timezone
  (UTC fallback), matching the dashboard service's anchoring rules.
- **Read-only:** no transaction is opened anywhere on this path; the controller
  awaits the four service reads sequentially on the request-scoped connection.
- The matching MCP tool is `get_outdoor_dashboard` (documented in its
  docstring, per the MCP documentation convention).

## Home Dashboard Endpoint

The home page is a read-only aggregate over the user's day — the daily summary,
today's agenda, tasks due this week and upcoming contact dates — exposed as a
**singleton JSON:API resource**:

| Verb + path | Purpose | Status |
|---|---|---|
| `GET /api/home-dashboard` | The four dashboard sections in one call: `summary`, `agenda`, `tasks` and `upcoming_dates`, each in a status envelope. No date parameters; every window is anchored on today in the user's timezone, reported in `meta.anchor` | 200 (always, including when a section could not be read); 401 unauthenticated |

Conventions this surface pins down, several of them the specification's rulings
rather than this API's taste:

- **Singleton resource:** type `home-dashboards`, id set to the user's id.
  JSON:API has no singleton concept and requires an `id` on every resource
  object, so a projection keyed by user has exactly one honest id. Same
  reasoning as `outdoor-dashboards` and the daily summary.
- **A top-level `/api/home-dashboard`, not `/api/journals/…`.** The outdoor
  dashboard is journal-scoped; this one reads across journals, tasks, contacts
  and the summary. Named `home-dashboard` rather than `dashboard` so the path,
  the resource type and `HomeDashboardService` name the same thing.
- **Per-section status is *in* `data`, because it cannot be anywhere else.** The
  specification requires a document's top level to hold "at least one of `data`,
  `errors`, `meta`" and forbids `data` and `errors` from coexisting, so "three
  sections and a failure in the fourth" has no representation as an error
  document. Each section is therefore
  `{ "status": "ready" | "unavailable", "data": … }`:
  - `ready` — the section was read. An **empty** payload is a real answer
    ("nothing scheduled today") and renders as one line, not an error.
  - `unavailable` — it could not be read, and `data` is `null` so an empty day
    and a failed read can never be confused.

  The response stays **200**: the request succeeded, and the client renders the
  sections it has. Nested objects inside `attributes` are explicitly allowed
  ("attributes can hold any valid JSON value, including complex objects").
- **The anchor travels in `meta`, not `attributes`:**
  `meta.anchor = { "date": "…", "timezone": "…" }`. `attributes` is information
  about the resource; which day was read, and in whose zone, is information about
  how the answer was computed — the same call `GET /api/tasks/upcoming` makes
  with `meta.window`, and present even when every section is empty. A
  purpose-built meta model is used rather than the shared `JsonApiMeta`, whose
  fields are the pagination ones a singleton does not have. Clients should label
  the page from `meta.anchor.date` rather than re-deriving "today" in the
  browser's zone, which can differ from the configured one.
- **The `summary` section is a pure read of today's daily summary.** It returns
  the same `journal_daily_summaries` row `GET /api/journals/daily-summary/{date}`
  serves, read through `JournalDailySummaryRepository` rather than
  `DailySummaryService.get_or_generate` — that path commits a row and then calls
  an AI model, and a dashboard load must not write. (`GET
  /api/journals/daily-summary/{date}` itself, and MCP `get_daily_summary`,
  regenerate today's summary on read when it was not generated today in the
  user's timezone; that rule is the service's, so neither surface has logic of
  its own for it.) Which of the five stored statuses the page can show is the
  section's own decision:

  | Stored status | Section `status` | `data.state` |
  |---|---|---|
  | no row (including AI not configured) | `unavailable` | — |
  | `failed` | `unavailable` | — |
  | `disabled` (a past or future day below the two-journal threshold; today is always eligible) | `unavailable` | — |
  | `pending` | `ready` | `generating` |
  | `generating` | `ready` | `generating` |
  | `generated`, generated today in the user's timezone | `ready` | `generated` |
  | `generated`, but not generated today (stale) | `ready` | `generating` |

  A summary section has no *empty* state — it is not a list — so `unavailable`
  covers both "could not be read" and "there is none today", which the page
  renders as one quiet line either way. `pending` folds into `generating`
  because to a reader waiting for words, queued and in-flight are the same
  condition, and a **stale** generated row folds the same way: the
  specification's freshness rule says today's summary must have been generated
  today in the user's timezone, so yesterday evening's prose is withheld this
  morning rather than served. The dashboard judges that from the row's
  `generated_at` and never writes — so **nothing on this path moves a journal
  daily summary out of `generating`**: only the daily-summary endpoints (and the
  MCP tool) generate, and this one does not call them. The dashboard's client
  closes that gap itself (ITER18-005 Phase 8): once per mount of the card
  and anchor day, when the first settled read of today has no prose, the summary
  card calls `GET /api/journals/daily-summary/{date}` — the read that regenerates
  a missing, invalidated or stale summary — and reads this endpoint back when
  that answer carries a row.
  It reads and never forces, and a later read of the same day (a task tick's
  refetch, say) never triggers it again, so a summary is not regenerated
  underneath a reader acting on the page. Any other client that renders
  `generating` needs the same read, or the regeneration action.
  The payload is
  `{state, summary_text, journal_count, event_count, contact_count,
  mood_average}`: `summary_text` comes from the entity's `get_display_text`, so
  it is `null` unless the summary is generated and prose from a superseded
  generation never reaches a client. The four counters are the row's own and are
  carried in both states; `mood_average` is out of ten and `null` on a day
  nothing was rated. The section is **read-only** — no links, no action fields.
  Regeneration is `POST /api/journals/daily-summary/{date}/regenerate`, and the
  date it needs is `meta.anchor.date`, which is present even when the section is
  not.
- **The `agenda` section is the user's local day, read in one query — with
  tomorrow beneath it, read the same way.** Its payload is
  `{entries: [...], tomorrow: {date, entries: [...]}}`, and an **empty list is a
  real answer** — nothing is scheduled today — which is why the section stays
  `ready` rather than reporting `unavailable`. An entry is
  `{journal_id, title, is_all_day, starts_at, ends_at, start_time, end_time,
  timezone, location, calendar_color, is_cancelled, tags[], participants[]}`.

  | Rule | What it means on the wire |
  |---|---|
  | Which journals | Journals with a `journal_calendar_info` row — the EVENT type — belonging to the acting user. A journal without one is a note about the day, not something on it. |
  | Which day | `local_day_window(anchor, tz)`: local midnight to the final microsecond of the local day. A large-offset zone's day spans two UTC dates, and the whole of it is returned. |
  | Overlap, not containment (timed events) | Matched on `event_date_range_end >= start AND event_date_range_start <= end`, so a multi-day trip running through today is on today's agenda. |
  | All-day events are matched by **date** | They happen on a date and have no meaningful instants, and the two writers disagree about which instant means that date — the Google worker stores midnight UTC with no event timezone, the app stores midnight in the browser's zone and records it. So the bounds are read back in the zone they were written in, `AT TIME ZONE COALESCE(jci.timezone, 'UTC')`, and compared as dates against `meta.anchor.date`. Matching them by instant put every synced holiday a day early for users west of UTC. |
  | Order | Every all-day entry first, then timed ones ascending by `starts_at`, ties broken on `journal_id`. Applied in the service, not in SQL. |
  | Two time representations | `starts_at`/`ends_at` are the journal's stored instants — the ordering key, and the only way to see that an entry began before today. `start_time`/`end_time` are the calendar info's clock values, `null` for an all-day event. |
  | …and the zone they are in | `timezone` is the IANA zone `start_time`/`end_time` are expressed in — the **event's**, not the reader's, since migration 0045 derives them `AT TIME ZONE jci.timezone`. Render the clock values against it rather than against `meta.anchor.timezone`; `null` means UTC. Without it a 09:00 New York meeting on a Sydney reader's agenda reads as a morning event that sorts into their evening. The journals API sends the same field beside the same two values. |
  | Cancellation | Returned **flagged**, never filtered: the specification requires a cancelled event to be shown clearly marked, and a surface cannot mark an entry it was never sent. |
  | Participants | Contacts linked as `PARTICIPANT` **or** `INVITEE` — both ways of being at an event, and the type the Google worker writes synced attendees as. `MENTION` and `ABOUT` are people the journal is about and are not attendees. |
  | Tomorrow | `tomorrow` is **always present on a ready agenda** and rides in this payload rather than behind a second request, so the page stays one round trip. It is a *day*, `{date, entries}`: `date` is the local day after `meta.anchor.date`, in the anchor's zone — label the disclosure from it, not from the browser's clock — and `entries` are in exactly today's form and order, so one renderer serves both. It is the same query run for the next local day (all-day events matched against that date, timed ones by overlap), which is why a multi-day event running through tonight is on **both** lists. The collapsed count is `entries.length`; the list is not capped, so no separate count is sent. Cancelled entries are flagged there as here, and they count. |

  Tags and participants are aggregated in `LATERAL` sub-selects so each day is
  **one statement whatever it holds** — two for the section; an integration test
  counts them for both days, because an N+1 is functionally invisible.
- **The `tasks` section reuses the upcoming-window listing; it has no query of
  its own.** Its payload is `{window: {start_date, end_date, days_ahead}, total,
  tasks: [...]}` — the same three-part shape the upcoming dates carry, over the
  same `UpcomingWindow` — and an **empty list is a real answer**: nothing is due
  this week, which the card renders as a good outcome rather than an error. A row
  is `{task_id, text, due_journal: {id, title, date}, days_away, contacts: [...]}`,
  and a contact is `{contact_id, name, photo_url}`.

  | Rule | What it means on the wire |
  |---|---|
  | Which tasks | Exactly what `GET /api/tasks/upcoming` returns for the default window: not-done tasks whose due journal falls between today and seven days ahead, both ends inclusive. One listing serves the endpoint, MCP `list_upcoming_tasks`, the daily summary's inputs and this section, so four surfaces cannot disagree about what is coming up. |
  | Which window | Today to seven days ahead, anchored on `meta.anchor.date`. The same `UpcomingWindow` the `upcoming_dates` section is built from — the specification requires the two evidence columns to cover the same week, and one window type is what makes that structural rather than coincidental. |
  | What is absent | Done, cancelled and **lapsed** tasks — and there is no overdue list, counter or badge anywhere on this page. Inside a *forward* window the only lapse that can bite is a **cancelled due journal**; a date-passed one is behind the window by construction. The excluded task is still on its own journals, where a lapsed task is meant to be found again: hidden here, not lost. |
  | The relative chip | `days_away` counts from the window's first day, `0` meaning today, and the window's first day *is* `meta.anchor.date` — so the chip's `Today` and the page's own header cannot disagree. Sent rather than derived, because subtracting dates in the browser's zone can land a day out near midnight. |
  | The due journal | Nested, not flattened: `id` and `title` for the "Due in *journal*" link, and `date` already resolved in the user's zone. No `cancelled` flag, because a cancelled due journal lapses its task and a lapsed task is not here. |
  | What a row does *not* carry | No `status`, `lapsed`, `lapse_reason`, creating journal or intermediate journals. The first three are constant for every row this section can hold — those are its entry conditions — and a constant on the wire invites a surface to branch on it; the journals are material no dashboard row draws. The single read and the journal listing carry all of them, and this is deliberately less than `TaskReadResource` rather than a subset that drifted. |
  | The cap | **None on the server.** The whole window travels with `total`, and the card renders five of it, so the show-more reveals the remainder without a second request and can name a count larger than the rows on screen. `total` equals `tasks.length` and is named because that is what the show-more displays. |
  | Round trips | The listing's own — one statement for the tasks and a batched read per link collection — invariant in the number of tasks. An integration test counts the whole request at one task and at six. |

  The section is handed the zone and the instant the projection already
  resolved, so the page reads `user_settings` **once** for all four sections and
  every window is as at one moment. `TaskReadService` takes no `today`: it
  derives the day from that pair, which is the pair the anchor came from.

- **The `upcoming_dates` section is the same seven days the tasks cover, ranked
  by inferred contact importance.** Its payload is
  `{window: {start_date, end_date, days_ahead}, total, dates: [...]}`, and an
  **empty list is a real answer** — nothing is coming up — which is why the
  section stays `ready`. A row is
  `{contact_id, contact_name, photo_url, date_type, custom_date_type_name,
  occurs_on, days_away, years, observed_for_leap_day}`.

  | Rule | What it means on the wire |
  |---|---|
  | Which dates | Every `contact_important_dates` row whose stored month and day fall in the window once resolved. **Every `date_type` participates** — precision alone decides whether a date recurs, so a `year`-precision row never appears whatever its type, and no type filter exists to disagree with that rule. |
  | Which window | Today to seven days ahead, **both ends inclusive**, anchored on `meta.anchor.date`. Literally the same `UpcomingWindow` the tasks section and `GET /api/tasks/upcoming` are built from, so the two evidence columns cannot disagree about which week it is. |
  | Resolved, not stored | `occurs_on` is the day the date falls on **this** time round — a birthday recorded in 1991 comes back on this year's day — and `days_away` counts from the window's first day, `0` meaning today. Both are sent rather than left to be derived: subtracting dates in the browser's zone can disagree with the day the server windowed on. |
  | The derived count | `years` is the age or anniversary count where the precision allows one, and **`null` where it does not** — the date was recorded without a year, or with a year *after* the occurrence, and a negative age is not an age. `0` is a real count. A surface renders the bare type when it is null (**W31**). |
  | 29 February | Observed on **28 February** in a year that has no 29th, with `observed_for_leap_day` set so the substitution is visible rather than looking like a quietly different date. Dropping the date instead would hide a birthday in three years out of four from a section whose only job is to give notice. |
  | Order | Occurrence date ascending, then **contact importance descending**, then contact and date row for stability. Importance breaks ties *within* a day and never reorders the days. |
  | What importance is | The favourite flag, then the recent journal count, then the recent activity count — `CONTACT_IMPORTANCE_ORDER`, the same signals and precedence the MeiliSearch contact ranking rules derive from, read through `ContactImportanceRepository` rather than out of the index, so the section still ranks with search down. |
  | …and what is *not* on the wire | Those signals are **deliberately absent** from the payload. The specification requires importance to stay inferred and unconfigured: there is no field for a user to set and none for a surface to show, and publishing the numbers would invite one. |
  | The cap | **None on the server.** The whole window travels with `total`, and the card renders three of it (ITER18-004 open decision 3), so a show-more reveals the remainder without a second request and can name a count larger than the rows on screen. `total` equals `dates.length` and is named because that is what the show-more displays. |

  Two statements: one candidate query, one batched importance read — and one for
  an empty window, since the signals read short-circuits on an empty batch. The
  recurrence is **not** in SQL: the database is asked only which stored
  `(month, day)` pairs could land in the window, passed as two parallel integer
  arrays through a multi-argument `unnest`, and `resolve_occurrence` decides what
  actually does. The candidate pairs include `(2, 29)` whenever the window covers
  a 28 February that is not itself a leap day, or a leap-day birthday would never
  be fetched to be observed.
- **Sections embed denormalised refs; there is no compound document.**
  `relationships` + `included` is the specification's way to serve related
  resources in one round trip, and it was the live alternative here. It cannot
  carry a section's `status` (a relationship's `data` is resource identifiers
  only), and it has nowhere for the per-context material sections hold — all-day
  ordering, a relative due chip, a resolved occurrence date and its days-away —
  which belongs to no referenced resource. So sections embed journal, task and
  contact refs in their attributes, as `TaskReadAttributes` already does.
- **Read-only:** no transaction is opened on this path. Each section is read
  inside its own `savepoint(connection)` so a failed query rolls back to the
  savepoint instead of aborting the transaction and taking the remaining
  sections down with it; the sections are read sequentially because a request
  holds a single `AsyncConnection`.
- **No *composite* MCP tool, deliberately.** An agent composes the same view from
  the daily-summary tool, journal browsing, the task listing tools
  (`list_upcoming_tasks`) and the contacts tools
  (`list_upcoming_important_dates`), so nothing on this surface is UI-only.
  Recorded in the service and endpoint docstrings. The per-section tools are not
  an exception to this: each is a capability in its own right, and each landed in
  the same phase as the section it mirrors.
- Member names are snake_case, as everywhere else in this API; JSON:API's
  camelCase preference is on its non-normative Recommendations page.

## Outdoor Logbook Basemap Tiles (Outbound)

The outdoor-logbook PDF renders each activity's GPX track over a basemap. Basemap
tiles are fetched through a **swappable tile-source port** (`TileSource` in
`app/core/journal/models/tile_source.py`) so the concrete source can change without
the renderer changing.

The default adapter, `OsmTileSource`
(`app/core/journal/adapters/http/osm_tile_source.py`), fetches **OpenStreetMap
standard tiles** — the same source the in-app `GPXTrackMap.tsx` uses. Because PDF
export is a **batch** operation that may render many tracks at once, the adapter is
batch-safe per OSM's tile-usage policy:

- **On-disk cache** keyed by `z/x/y`, so a tile shared across entries or zoom levels
  is fetched only once (cache dir: `LOGBOOK_TILE_CACHE_DIR`).
- **Throttle** pacing network fetches to ≈2 tiles/second
  (`LOGBOOK_TILE_THROTTLE_PER_SECOND`); cache hits skip the throttle.
- **Valid User-Agent** on every request (`LOGBOOK_TILE_USER_AGENT`), as OSM requires.
- **Clean failure:** any HTTP/connection failure raises the typed `TileFetchError`
  and leaves the cache untouched, so the renderer can fall back to a plain background
  rather than failing the export.

Swappability: a keyed topo provider can be substituted later by pointing
`LOGBOOK_TILE_BASE_URL` at another `{z}/{x}/{y}` endpoint or providing an alternative
`TileSource` implementation in the `JournalProvider` DI binding. The tile source is
registered at **APP scope** so its cache and throttle are shared across the whole
export batch and across requests.

### Composing the map image

`GpxMapRenderer` (`app/core/journal/services/gpx_map_renderer.py`, also APP scope)
turns an entry's GPX routes into the PNG the PDF embeds. Because tile fetching is
asynchronous while `LogbookPdfRenderer` is synchronous, the images are composed
first and handed to `render(data, map_images=…)` as a mapping keyed by journal id —
an entry absent from that mapping simply gets no map:

```python
export_data = await data_service.get_logbook_data(...)
map_images = await map_renderer.build_map_images(export_data.entries)
pdf_bytes = renderer.render(export_data, map_images=map_images)
```

- **One map per entry.** All of an entry's routes are drawn on a single image whose
  bounding box fits every track, plus padding. Child activities get their own maps.
- **Bounded tile cost.** `utils/slippy_map.py` picks the closest zoom (capped at 17)
  whose tile grid still contains the whole track, within **2×2 tiles**, so one map
  costs at most **4** tile fetches however long the track is. There is deliberately
  no separate per-export budget: with the ≈2 tiles/second throttle, a cold-cache
  export costs roughly 2 s per mapped entry (≈100 s for 50 of them), and the
  on-disk cache removes that cost for tiles shared between entries or repeat
  exports.
- **Attribution is drawn onto the image**, bottom-right, on a light plate so it
  stays legible over dark map detail. It comes from the port's `attribution`
  property, so swapping the provider swaps the credit.
- **Degrade, never fail.** A tile that cannot be fetched, cannot be decoded, or
  arrives at the wrong size discards the whole basemap and the track is plotted on
  a plain background instead — half a basemap reads as a rendering bug, and a
  wrongly-sized tile is worse than none: the grid is laid out on 256px offsets, so
  a substituted provider's 512px retina tiles would leave the basemap misaligned
  against the track drawn over it. Fetching stops at the first failure rather than
  hammering a struggling tile server. A route whose GPX cannot be parsed is skipped,
  as are individual non-finite coordinates (a `lat="nan"` parses happily and only
  fails at the tile-index conversion, while `inf` fails inside gpxpy's own maths —
  both as a bare `ValueError`); an entry whose every route fails simply has no map.

Test stacks never fetch real tiles: `.env.test` points `LOGBOOK_TILE_BASE_URL` at a
dead address, which fails fast with a connection error and takes the plain-background
fallback. So an E2E run that exports a journal with a GPX route still succeeds without
the suite becoming a live OpenStreetMap client. Backend unit and integration tests stub
the `TileSource` outright and never reach the adapter at all.

Known limitation: a track crossing the ±180° antimeridian yields a bounding box
that spans the world, so the zoom clamps to its minimum and the map renders as a
world view with the track drawn across it. It still exports — nothing fails — and
the in-app Leaflet map has the same behaviour, so this is left as-is rather than
special-cased.

Ordering note: `SqlLogbookExportRepository` loads route GPX ordered by
`created_at, name, id`. The name tiebreak is load bearing — `created_at` defaults to
the *transaction* timestamp, so routes saved in one request tie on it, and falling
through to the random `uuid` primary key would order them differently on every
export.

## Task Endpoints

Tasks are commitments anchored to two journals — the one a task arose in and the
future-dated one it is due in — so creation hangs off the journal path rather
than a top-level collection. There is deliberately **no unbounded `/api/tasks`
collection**: no endpoint lists *all* tasks, because no screen does. A task's own
member routes under `/api/tasks/` exist for operations that involve no journal at
all. There are exactly two listings, and each is bounded by something: a
*journal's* tasks, bounded by the journal, and the *upcoming window*, bounded by
a capped span of days. Neither can be widened into a task browser.

| Verb + path | Purpose | Status |
|---|---|---|
| `POST /api/journals/{journal_id}/tasks` | Create a task in the journal it arose from. Body attributes: `text`, `due_journal_id`, optional `contact_ids` | 201; 400 empty text, unknown attribute, or a due journal that is not future-dated; 404 either journal anchor unknown/not-owned, or an unknown contact |
| `GET /api/tasks/{task_id}` | Read one task whole: its journals **by role** (each with title, date and whether it is a cancelled event), its contacts, and `lapsed` with `lapse_reason` | 200; 400 an out-of-range id; 404 task unknown/not-owned |
| `GET /api/journals/{journal_id}/tasks` | The journal's tasks, **grouped by link role** — due here, created here, mentioned here. Optional `?role=due\|created\|mentioned` | 200 (a journal with no tasks answers three empty groups); 400 an out-of-range id or an unknown `role`; 404 journal unknown/not-owned |
| `GET /api/tasks/upcoming` | Not-done tasks due between **today and `?days_ahead=` days ahead** (default 7, both ends inclusive), anchored on today in your timezone. Done, cancelled and lapsed tasks excluded | 200 (an empty window is a 200 with `data: []`, never a 404); 400 `days_ahead` below 0 or above 90 |
| `PATCH /api/tasks/{task_id}` | Change a task's text, its status, or both. Body attributes: `text`, `status` (`not_done`, `done`, `cancelled`) — both optional, at least one required | 200; 400 unknown status, blank text, unknown attribute, a body naming no change, or a body `id` disagreeing with the path; 404 task unknown/not-owned; 409 a refused transition |
| `POST /api/tasks/{task_id}/retarget` | Move a task onto a new due journal, keeping the old one as an intermediate link. Body type `task-retarget`, attributes: `due_journal_id`, optional `acknowledge_reopen` | 200; 400 a due journal that is not future-dated, an unknown attribute, another resource type, or an out-of-range id; 404 task or new due journal unknown/not-owned; 409 a *done* task reopened without acknowledgement |
| `DELETE /api/tasks/{task_id}` | Delete a task and its link rows permanently. The exception — cancelling is the ordinary action | 204 (no body); 404 task unknown/not-owned, including a repeat delete |
| `GET /api/tasks/{task_id}/history` | The task's field-level change history, paginated and most recent first, each entry carrying its provenance and actor. Query params: `page` (default 1), `limit` (default 20, max 100) | 200 (a task with nothing projected yet answers `data: []`, **including a task created moments ago**); 400 an out-of-range id or a `limit` above 100; 404 task unknown/not-owned |
| `POST /api/tasks/{task_id}/relationships/contacts` | Link a contact. Body: a resource identifier, `{"data": {"type": "contacts", "id": "5"}}` | 204; 400 unknown field, a relationship attribute, another resource type, or a non-integer id; 404 task unknown/not-owned or contact unknown |
| `DELETE /api/tasks/{task_id}/relationships/contacts/{contact_id}` | Remove a contact link | 204; 404 task unknown/not-owned |
| `POST /api/tasks/{task_id}/relationships/intermediate-journals` | Attach an intermediate journal. Body: a resource identifier, `{"data": {"type": "journals", "id": "9"}}` | 204; 400 unknown field, a role attribute, another resource type, or a non-integer id; 404 task or journal unknown/not-owned; 409 the journal is already the creating or due journal |
| `DELETE /api/tasks/{task_id}/relationships/intermediate-journals/{journal_id}` | Remove an intermediate-journal link | 204; 404 task unknown/not-owned; 409 the journal is the creating or due journal *and* holds no intermediate link |

Conventions this surface pins down:

- **The path journal is the creating anchor**, never a body field, so a client
  cannot anchor a task to a journal it did not come from. The request schema has
  no `creating_journal_id`.
- **No bare date, and no implicit journal creation.** A task is due *in a
  journal*, so `due_journal_id` must name one that already exists. Offering a
  date would make the surface create journals as a side effect.
- **Unknown attributes are rejected** (`extra="forbid"`). The service's `now`
  parameter is a test seam for the future-dated invariant; a request able to set
  it would make that invariant opt-out, so its absence is enforced rather than
  assumed.
- **404 for an unreachable anchor, in the error mapping rather than the
  controller.** A due journal that does not exist and one belonging to somebody
  else raise the same `TaskAnchorJournalNotFoundError` with a byte-identical
  message, so a rejected create cannot be used to probe for another user's
  journals. The payload's `code` and `detail` name *which* anchor failed, which
  is what disambiguates a body-field 404 from a path-journal one. Because the
  answer lives in the mapping, the MCP tool inherits it unchanged.
- **Transactions:** the controller passes the request-scoped `AsyncConnection`
  into the `@transactional` service method, which owns the commit. The controller
  opens none and catches no domain error.
- **An update or a delete reaches the task by its own id, not through a
  journal.** Marking a task done or cancelled requires no journal and creates no
  journal link; rewording one infers no link either; and the due journal is not
  re-read on any of these paths — which is what keeps a *lapsed* task (one whose
  due journal has passed) both completable and editable. Routing them through a
  journal would imply a relationship the operations do not have.
- **409 for a refused transition.** Only two are refused, both leaving
  *cancelled*: a cancelled task is reopened by retargeting it onto a new future
  journal, which returns it to not done. The body is well formed and the status
  it names is real, so what it conflicts with is the task's state — and the
  `detail` names retargeting rather than merely refusing.
- **A `PATCH` body must carry `data.id`, and it must match the path.** JSON:API
  identifies the resource in the body as well as in the URL; preferring one
  silently would let a client change a task it believes it is not touching. This
  is the one check the controller makes itself, because it is an envelope
  concern with no domain rule and no MCP counterpart behind it.
- **A `PATCH` must name at least one change, and both attributes are otherwise
  optional.** JSON:API sends the attributes that changed, so a client rewording a
  task sends no `status` and one completing it sends no `text`. A body naming
  neither is refused with 400: down in the service that is simply nothing to do,
  but out here it is a client that built a request wrong, and answering 200 would
  tell it an edit it thinks it made was applied. This also settles explicit
  `null` — text is required on a task, so `{"text": null}` cannot mean "remove
  it" and is read as "not sent".
- **Text and status arriving together are one change, not two.** They are applied
  by a single `TaskService.update_task` under one locking read and one write, so
  a request can never be half-applied. `set_status` delegates to the same method
  rather than reimplementing the transition matrix.
- **204 and no body for a delete**, matching every other delete in this codebase:
  there is no resource left to return. The task's intermediate-journal and
  contact links go with it by cascade; the journals and contacts themselves are
  untouched, including both anchors — deleting the task is the supported way to
  unblock a journal deletion a task was holding up, not a reason to lose the
  journal too. A repeat delete answers 404 rather than 204, because reporting
  success for a task that was not there would tell a client a commitment is gone
  when it may still be on a journal.
- **Delete is the exception and both surfaces say so.** The specification keeps
  hard deletion for genuine mistakes and puts cancelling in its place otherwise,
  mirroring the journals specification's stance on event journals. Nothing in the
  transport can enforce a preference, so it is carried by what the endpoint and
  the tool *say* — and for the MCP tool that is load-bearing rather than
  decorative, since the description is the only steer a model gets when choosing
  between them.
- **A contact link is a relationship route, and it answers 204.** The link
  carries no relationship type, no role and no attendance status — the
  specification calls it a plain reference — so there is no resource to return
  and nothing to put in an `attributes` member. 204 is also what keeps the
  operation's *idempotency invisible*: linking a contact that is already linked,
  or unlinking one that is not, answers exactly as the first call did. Returning
  the task instead would mean re-deriving its linked set in the controller,
  which would be a second definition of what got linked sitting beside a read
  model that does not exist yet.
- **The link body is a single resource identifier, not a to-many array.** JSON:API
  models a to-many relationship update as an array; this surface takes one
  contact per call, because that keeps "was anything created" unambiguous and
  matches the shape `POST /api/contacts/{id}/tags` already uses. Recorded as a
  knowing narrowing rather than an oversight. Unknown members are forbidden at
  both nesting levels and the `contacts` type is pinned, as on the other task
  request models.
- **Unlinking does not require the contact to still exist.** `task_contacts`
  cascades from the contact side, so a deleted contact's links are already gone;
  404-ing there would fail exactly the call a user reaches for while tidying up.
  Task ownership is still enforced, so another user's task answers 404 on both
  verbs, byte-identically to an absent one.
- **Ids are bounded to what the column can hold.** Every id column here is a
  PostgreSQL `INTEGER`, and Python's `int` is not, so `2147483648` used to parse
  cleanly, reach the repository and die in asyncpg's *parameter binding* — a 500
  for an id no row could ever have. `app/api/common/identifiers.py` bounds them
  to `1..2147483647` on every id the tasks API and its MCP tools accept, path
  and body alike, so the answer is the 400 the client deserves. The lower bound
  is `1` because serial columns start there: 404 would suggest the row might
  have existed once. **Other domains' endpoints are still unbounded** — issue
  #1272 tracks the sweep, which is deliberately not done inside a feature phase.
- **A retarget is an action sub-resource, not a field on the `PATCH`.**
  `POST /api/tasks/{id}/retarget` follows `POST /api/journals/{id}/merge`. A
  retarget is not a field assignment: it forces the status to *not done* and
  writes an intermediate link row, so a `PATCH` body able to carry a `status`
  beside a `due_journal_id` would have two answers and no rule for choosing
  between them — and that `PATCH` now genuinely carries two fields, so the
  collision is concrete rather than hypothetical. JSON:API's canonical to-one
  relationship route
  (`PATCH .../relationships/due-journal`) was considered and rejected: a
  relationship endpoint's 200 must return the *relationship*, and this operation
  has to return the task. The body's `type` names the **operation**
  (`task-retarget`) and carries no `id`, because it is an instruction rather
  than the task's own attributes; the path already says which task.
- **The reopen acknowledgement is a body attribute, defaulting to false.** Not a
  query parameter and not a header: it is part of what the caller is asking for,
  it must be *refused* if misspelled — `extra="forbid"` cannot guard a query
  string — and MCP has no concept of either. Its refusal is **409 with its own
  code**, `TASK_REOPEN_NOT_ACKNOWLEDGED`, rather than a validation error: the
  body is well formed and the journal it names is a real, future, owned one, so
  what it conflicts with is the state the task is in. The distinct code is what
  lets a surface offer *"reopen it anyway"*; one that could only see a generic
  failure would have nothing but "invalid" to show.
- **Every task response carries the same attributes, including
  `intermediate_journal_ids`.** The trail is on create, `PATCH` and retarget
  alike, so a client can write one renderer for the resource: a `PATCH` on a
  previously-retargeted task answering `[]` would be wrong rather than merely
  terse. It is an *attribute* rather than a `relationships` member because the
  resource already exposes `creating_journal_id` and `due_journal_id` as
  attributes — one convention, not two — and it is read through the service
  rather than in the controller, since controllers resolve services and never
  repositories.
- **The read resource is a superset of the written one, not a second type.**
  `GET` answers type `tasks` with every attribute the write routes return —
  `intermediate_journal_ids` included — plus the resolved `creating_journal`,
  `due_journal` and `intermediate_journals`, the `contacts`, and `lapsed` with
  `lapse_reason`. Replacing the id list with the objects would break the one
  renderer the rule above exists to make possible. `lapsed` is taken from the
  read model rather than recomputed from the reason, so the flag and the reason
  cannot disagree; the reason is structured rather than pre-worded, because "the
  day went by" and "the meeting was called off" ask the user for different
  things and the wording is the UI's.
- **A journal reference carries a resolved `date`, never an instant.** The lapse
  verdict was reached in the acting user's timezone, so sending a timestamp
  would let a browser re-derive the day in its own zone and disagree with the
  verdict it was sent alongside.
- **The `self` link arrives with the read, and it is absolute.** The write
  responses deliberately emitted none while `GET /api/tasks/{id}` did not exist —
  a `PATCH` target is not a `GET` target, and a link that 404s is worse than an
  absent one. Now that the route exists, every task resource carries one, built
  from the request's base URL exactly as `ContactConverter.to_resource`,
  `JournalConverter` and `create_pagination_links` build theirs. The base URL is
  a **parameter with an empty default** rather than something the renderer reads
  from a request, which keeps `to_task_read_resource` a pure function of its
  arguments — testable without a request — while the controller supplies
  `get_request_base_url(request)`. A relative `self` would have given a client
  resolving links uniformly two different shapes from the same API.
- **A journal's listing groups by link role, and a task can hold two roles.**
  One journal can be a task's creating *and* due anchor (invariant 6), and
  retargeting onto a journal the task already mentioned leaves that mention
  beside the new due anchor. JSON:API forbids the same resource appearing twice
  in `data`, so each task appears **once** carrying in `link_roles` every role it
  holds *among the groups returned*, with the grouping itself as ordered id lists
  in `meta.groups`. Under a `role` filter the two narrow together, so
  `link_roles` can never name a group the same response reports as empty; the
  unfiltered call is the one that answers "every role this task holds here".
  The matching MCP tool has no such rule and nests whole tasks under the three
  roles instead — the same data, the same ordering, the same 404s, a different
  envelope. `meta` is a listing-specific model rather than the shared paginated
  one: a journal's tasks are bounded by the journal, so advertising page
  controls that do not exist would be worse than having none.
- **Ordering is a total order the surface promises.** Rows come back by due-journal
  date ascending, then by task id. The tie-break is not defensive: every task in
  the *due* group shares the journal and therefore its date, so id order is the
  whole of that group's order. The same reasoning applies inside a task —
  `intermediate_journals` and `contacts` are ordered by link `created_at` then by
  the linked id, because `created_at` is `transaction_timestamp()` and every link
  written in one request ties on it.
- **Every linked task is listed, in every status.** Done, cancelled and lapsed
  tasks all appear on a journal: the specification keeps lapsed tasks "visible on
  every journal they are linked to", which is how a user finds one again, and a
  done task's link to the journal it arose in is part of the record. The
  dashboard's tasks section is the surface that hides them, and there is
  deliberately no status filter here — one would reconstruct the
  "everything outstanding" browser the specification refuses.
- **The listing's 404 is the journal domain's**, and it costs no extra query:
  the journal is resolved through the same owner-scoped fetch the read models
  already need. An unknown journal and another user's are the same answer, while
  a journal of the caller's with nothing linked to it is a 200 with three empty
  groups — the distinction that check buys.
- **Reads open no transaction.** All three read controllers await
  `TaskReadService`, which carries no `@transactional`, takes no lock and
  publishes no event: a read that opened a unit of work would hold a transaction
  for the length of a page render.
- **`/api/tasks/upcoming` is registered before `/api/tasks/{task_id}`, and the
  order is load-bearing.** FastAPI matches in registration order, so the member
  route would otherwise claim `upcoming` as an id and answer 400 — the same
  footgun `main.py` records for `/journals/series`. An integration test asserts
  the literal route wins, because the failure mode is a working endpoint that
  silently became unreachable.
- **The upcoming window includes today, and the future-dated invariant does
  not.** The two rules disagree about today deliberately: a journal must be
  strictly future-dated to *become* a deadline, while a deadline landing today
  is exactly what a dashboard exists to surface. Both ends of the window are
  inclusive, so a task due on the last day is in it.
- **The window is anchored on today in the acting user's timezone**, resolved
  once per request from their settings, and turned into instants before it
  reaches SQL. No timezone conversion happens in the database: a journal's date
  is defined in `JournalDateResolver`, and a second definition in a query could
  drift from it. There is no way for a caller to move the anchor — no `now`, no
  `date`, no `today` parameter on either surface — since one would let a client
  ask what next month will look like as though it were now.
- **The upcoming listing excludes done, cancelled and lapsed tasks; a journal's
  listing excludes nothing.** That difference is the product's, not an
  inconsistency: the dashboard shows what is outstanding, and a journal is where
  a lapsed task is meant to be found again. Inside a *forward* window only one
  lapse cause can occur — a **cancelled due journal** — because a passed date is
  behind the window by construction, which is why that fixture is the only one
  that makes the exclusion non-vacuous and is required at every test level.
- **The lapse exclusion is applied to the assembled read model, not in SQL.**
  The statement filters status and the date window; cancellation is known from
  the batched lookup the assembler already makes, so the exclusion reads the
  verdict rather than recomputing it. One definition of *lapsed*, in the read
  model, where the endpoint, the tool and the journal listing all get it from.
- **The whole window is returned: no cap, no pagination.** `meta.total` equals
  `len(data)`, and it is named anyway because it is the count a capped UI's
  *show more* displays — the dashboard applies its five-item cap client-side, so
  revealing the rest costs no second request. `meta` is a listing-specific model
  rather than the shared paginated one, for the reason the journal listing's is:
  advertising page controls that do not exist is worse than having none. What
  bounds the collection instead is `days_ahead`, capped at 90 on both surfaces
  *and* in the domain rule, so the cap cannot be bypassed by reaching the service
  another way.
- **The window travels in `meta`, including when the answer is empty.** No row
  carries it, so a client with no rows could not otherwise say *what* was empty —
  and "nothing due between today and next Tuesday" is the empty state the
  specification asks for, not "nothing due".
- **The rows are the same `TaskReadResource` the single read returns**, so a
  dashboard renders one with the renderer it already has. `link_roles` is absent
  and deliberately so: that field answers "how is this task linked to the journal
  being listed", and in a window the question has no meaning.
- **A journal relationship is named for the role it holds, not for the resource
  it points at.** A task has three journal relationships — creating, due and
  intermediate — and only the last is a row in a link table, so the route is
  `/relationships/intermediate-journals`. Calling it `/journals` would promise a
  route that can set an anchor, which the service refuses. The body's resource
  `type` is still `journals`, because the relationship's name lives in the path
  and the type names what the identifier points at. This is the first kebab-case
  relationship member in this API; every earlier one happened to be a single
  word.
- **An anchor journal is 409, on both verbs.** A journal that is already the
  task's creating or due journal cannot be attached — it is linked in a role an
  intermediate link cannot express — and its anchor *role* cannot be detached.
  One rule, so one error (`TASK_JOURNAL_IS_ANCHOR`), whose `detail` names *which*
  anchor and how that anchor is really changed: the creating journal never
  changes and the due journal is changed by retargeting. Detaching answers
  explicitly rather than succeeding silently, because a bare 204 would read as
  "it was not attached". **The detach refusal applies only when there is no link
  row**: a journal can legitimately be both an anchor and an intermediate link —
  attach it, then retarget onto it — and refusing there would leave a link the
  client created with no way to remove it.
- **An unreachable journal answers the journal domain's `JOURNAL_NOT_FOUND`**,
  not `TASK_ANCHOR_JOURNAL_NOT_FOUND`. An intermediate journal is not an anchor,
  and that error's message describes a rule this call is not about. Ownership is
  enforced by the owner-scoped read, so another user's journal and an absent one
  produce bodies that differ **only in the id the caller supplied** — the same
  hedge the anchor 404 above carries, and the reason a rejection here cannot be
  used to probe for other users' journals.
- **The history read answers for a task that no longer exists, and that is what
  shapes it.** Every other history endpoint authorises by loading the aggregate
  and comparing `user_id` — `GET /api/journals/{id}/history` does exactly that.
  A task is **hard-deleted**, so a task-scoped read has nothing to load, and the
  `__deleted__` marker its deletion projects would otherwise sit on a surface
  nobody could ever be authorised to read. Ownership is therefore carried on the
  history rows (`field_history.user_id`, stamped by the projection from the
  event payload) and resolved by `TaskHistoryService`: **the rows answer first**,
  and the live `tasks` row is only a fallback for the window before the
  projection has caught up. Both callers — this endpoint and `get_task_history`
  — go through that one resolution rather than checking ownership themselves, so
  they cannot disagree about whose history it is.
- **"Not projected yet" is not "does not exist".** Projection is asynchronous, so
  a task created a moment ago has no history rows. That answers `200` with an
  empty list; answering 404 would tell a user their new task is missing, and go
  on saying so until a background process they cannot see caught up. The two
  cases are distinguished by the fallback above, not by a timer.
- **A history read is task-scoped and has no collection beside it.** The
  specification's *Where tasks appear* allows exactly two working surfaces, and
  a record of the past is not a third one: there is no `/api/tasks/history`, no
  filter, and no way to reach a task through this route that you did not already
  have the id of.
- **`GET /api/contacts/{contact_id}/history` also answers with task rows**
  (ITER18-003 Phase 9). A task linked to a person surfaces on their activity
  history as a read-only record of the link: an entry with
  `entity_type: "task"`, `entity_id` the task's id, `field_name` `contact:{id}`
  and the `source` / `changed_by` the link was made with. Four things about it
  are contractual. It records **the link, plus the task's deletion** — a task's
  text, status and retarget rows stay on the task's own history, because a
  contact page is not a place to work through commitments, but a hard delete is
  the end of the thing the record points at rather than progress on it. It
  **survives the task being unlinked or deleted**, because the aggregate reaches
  those rows by field name rather than through `task_contacts`. Each such entry
  carries **`entity_label`**, the task's name, because both of the row's own
  values are the contact's id and a task has no route of its own to link to; it
  is resolved from `field_history` (so a deleted task is still named), and is
  `null` on every row that names itself and on a task whose history has not been
  projected yet. And it adds **no new authorisation surface**: the rows are
  reached through a contact the caller can already read, and the endpoint's
  shape, pagination and JSON:API resource type are unchanged.
  Contact history has no MCP tool of its own; the count inside
  `get_contact(include_history=true)` includes these records, and an agent
  reading the task's side uses `get_task_history`.
- **Detaching does not require the journal to still exist**, the same asymmetry
  the contact link carries and for the same reason:
  `task_intermediate_journals` cascades from the journal side, and the
  specification permits deleting a journal that is only an intermediate link.
- The matching MCP tools are `create_task`, `set_task_status`, `retarget_task`,
  `update_task_text`, `delete_task`, `link_task_to_contact`,
  `unlink_task_from_contact`, `attach_intermediate_journal_to_task`,
  `detach_intermediate_journal_from_task`, `get_task`, `list_journal_tasks`,
  `list_upcoming_tasks` and `get_task_history`
  (documented in their docstrings and
  parameter schemas, per the MCP documentation convention). `update_task_text`
  offers no `status` parameter and `set_task_status` no `text`: a model gets one
  tool per intent, so it never has to reason about what leaving a field out will
  do — the combined write exists for the `PATCH` body that genuinely carries
  both. The four link tools return the resulting state — `linked` or `attached` —
  beside `changed` (whether a row moved), which is the one thing the 204
  withholds and an agent may want. The trail is on every task-returning answer,
  which mattered more over MCP than over HTTP while nothing read a task back —
  `get_task` now does, and it keeps `intermediate_journal_ids` beside the
  resolved journals for the same reason the endpoint does: an agent that learned
  the shape from `create_task` should not have to learn a second one to read the
  same task back. `list_upcoming_tasks` returns the same window, total and
  ordering the endpoint does, in the same read shape per row; its description
  carries what the one-integer schema cannot say, and in particular **names
  `list_journal_tasks` as where an excluded task is still found**, because an
  agent that reported "you have nothing due" to a user holding three
  cancelled-meeting commitments would be confidently wrong in a way the user
  could not check.
  `get_task_history` is the one read tool that answers for an id `get_task`
  reports as **not found** — a deleted task keeps its history — and its
  description says so, because an agent that does not know it will not think to
  ask when a user wonders what became of something. The description also carries
  what the three-integer schema cannot: that the entries are most recent first,
  that projection lags the change so an agent's own edit may not be there yet
  (and that this is not a failed write), what the non-literal field names mean
  (`__created__`, `__deleted__`, `journal:{id}`, `contact:{id}`), and that this
  is a record rather than a way to browse tasks.

## Authentication Guidelines

### Session-Based Authentication

- Use Starlette SessionMiddleware for session management
- Store session data securely with proper encryption
- Implement session timeout and renewal
- Handle concurrent sessions appropriately
- Provide clear authentication error responses

### Security Considerations

- Use HTTPS in production environments
- Implement proper CSRF protection
- Validate all input parameters
- Log authentication events for audit trails
- Handle rate limiting for authentication endpoints

## API Documentation

### OpenAPI Integration

- Use FastAPI's automatic OpenAPI generation
- Provide clear descriptions for all endpoints
- Include example requests and responses
- Document error responses and status codes
- Use tags to organize endpoints by domain

### Documentation Best Practices

- Write clear, concise endpoint descriptions
- Include parameter validation rules
- Provide realistic example data
- Document authentication requirements
- Keep documentation up-to-date with code changes

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and API principles
- [AI Guidelines](../ai-guidelines.md) - API development standards and guidelines
- [Technology Stack](./technology-stack.md) - API technology choices and frameworks
- [Domain Architecture](./domain-architecture.md) - Domain layer patterns and business logic
- [Testing Strategy](./testing-strategy.md) - API testing patterns and validation
- [Frontend Design](./frontend-design.md) - Frontend API integration patterns
- [Security & Performance](./security-performance.md) - API security considerations
- [Deployment Guide](./deployment-guide.md) - API deployment and configuration
