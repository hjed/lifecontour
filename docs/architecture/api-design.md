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

### FastMCP v2 Implementation

- **Framework**: Use FastMCP v2 (jlowin/fastmcp) instead of official MCP SDK
- **Documentation**: Reference https://gofastmcp.com/llms.txt for AI-optimized patterns
- **Integration**: Follow https://gofastmcp.com/deployment/asgi.md for FastAPI integration

### Tool Structure

- Use `@mcp.tool` decorator on async functions
- Define clear function names and docstrings
- Use Pydantic `Field` with `Annotated` for parameter descriptions
- Return JSON strings for structured data
- Include comprehensive error handling with try/catch blocks
- Provide AI-friendly responses with context and summaries

### Domain-Based Organization

- Organize tools by domain: `app/mcp/domains/{domain}/tools.py`
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

`JournalHasAnchoredTasksError` is the current example: `DELETE
/api/journals/{id}` answers 409 with code `JOURNAL_HAS_ANCHORED_TASKS` and a
`meta.blocking_tasks` list giving each blocking task's id, text, status and
blocking roles, plus the id and title of the journal it can be actioned from.

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
- **Detaching does not require the journal to still exist**, the same asymmetry
  the contact link carries and for the same reason:
  `task_intermediate_journals` cascades from the journal side, and the
  specification permits deleting a journal that is only an intermediate link.
- The matching MCP tools are `create_task`, `set_task_status`, `retarget_task`,
  `update_task_text`, `delete_task`, `link_task_to_contact`,
  `unlink_task_from_contact`, `attach_intermediate_journal_to_task`,
  `detach_intermediate_journal_from_task`, `get_task`, `list_journal_tasks` and
  `list_upcoming_tasks`
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
