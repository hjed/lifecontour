# Entity Ownership Product Specification

## Overview

This document defines the target behaviour for **ownership** of user data: every entity a user
creates or syncs belongs to exactly one user, and nothing a user can reach — through the web UI,
the REST API, MCP tools, search, or an integration — is another user's. It is a product
specification rather than a technical design.

The system was built for one person and has been deployed only that way. Journals, tasks,
calendars, gear items, templates, series and the integration credential tables already carry a
`user_id` and filter on it. **Contacts do not**, and neither do the lookup tables that hang off
contacts and journals (contact tags, custom date types, journal tags) nor the integration link
store (`sync_metadata`). Several code paths also *assume* a single user: outbound integration
pushes fan a contact out to every connected account, background consumers read "the" timezone,
and contact search has no owner filter.

Three iterations have already run into this and recorded it rather than fixed it: contact merge
(iteration 13) and tasks (iteration 18, phase 4) both note that "a linked contact must belong to
the acting user" cannot be enforced because contacts have no owner, and the home dashboard's
contact reads are documented as diverging from the rule that every dashboard port takes a
`user_id`. This specification is the fix those notes point at.

Because no multi-user deployment exists, **migration is unambiguous**: every existing row is
assigned to the one real user present, using the same owner derivation migration `0106` already
established. Going forward, ownership is enforced at write time and read time everywhere.

## Reference and Alignment

This specification evolves and refines behaviour described in:

- `docs/architecture/database-design.md` — the contacts, tags and `field_history` tables, and the
  transaction-management rules writes must follow
- `docs/architecture/domain-architecture.md` — the journals and tasks ownership patterns this
  specification generalises, and the recorded "contacts have no owner" divergences
- `docs/architecture/api-design.md` — the "404, never 403" rule for another user's entity
- `docs/architecture/integration-architecture.md` — the outbox/Redis Streams event flow, the inbound
  consumer, and the Snipe-IT rule that an event without a `user_id` is skipped rather than fanned out
- `docs/product-specifications/contacts-product-specification.md` — the contacts product this
  specification hardens
- `docs/tasks/iteration-13-contact-merge.md`, `docs/tasks/iteration-18-home-dashboard-and-tasks.md`
  (phase 4) — the divergences this specification resolves
- Migration `0106_reassign_synthetic_owner_rows.py` — the owner-derivation precedent reused here

Where earlier documents or implementations state that contacts are single-user, this specification
takes precedence.

## Product Goals

The ownership work should:

1. Make **every user-created or user-synced entity owned by exactly one user**, with the owner
   stored on the row and enforced by the database, not inferred.
2. Guarantee that **no surface leaks across users**: REST, MCP, search, history, dashboards, and
   integration workers all answer only with the acting user's data.
3. Make **integrations per-user**: a contact synced from one user's Google account is that user's
   contact, is pushed only to that user's connected accounts, and is reconciled only against that
   user's existing contacts.
4. **Migrate the existing single-user data safely and automatically**, assigning every unowned row
   to the site's one real user, and refusing loudly if that user cannot be determined.
5. Leave the system in a state where **a second user could sign in tomorrow** and see an empty,
   isolated workspace — without any further schema work.

## Product Principles

1. **One owner, stored on the row.** Ownership is a `user_id` column on the aggregate root, never
   derived at read time from a join through another entity. Child rows (contact methods, addresses,
   notes, important dates, tag assignments, relationship rows) inherit ownership through their
   parent's foreign key exactly as journal child tables do today.
2. **Filter in SQL, at the aggregate.** Every repository method that reads or lists an aggregate
   takes the acting user's id and filters on it in the query. Child-row methods keyed by the parent
   id stay unscoped; the service proves the parent belongs to the user first. This is the tasks
   contract (`TaskRepository`: "every method takes the acting user's id") and the journals
   `find_by_id_for_user` pattern applied uniformly.
3. **Another user's entity is indistinguishable from a missing one.** Reads answer 404 and writes
   change nothing; nothing in an error body says "exists but not yours". Cross-entity links
   (journal ↔ contact, task ↔ contact, contact ↔ contact, athlete ↔ contact) treat a foreign
   contact as not found.
4. **Events name their owner.** Every domain event about an owned aggregate carries `user_id` in
   its payload (as journal and task events already do), and every integration sync event carries the
   `user_id` of the sync job that produced it. A consumer that needs an owner and receives an event
   without one rejects that event rather than guessing.
5. **Integrations are per-user end to end.** Credentials are already per-user; the entities they
   produce, the link rows that tie them to external ids, the outbound pushes, and the dedup and
   reconciliation lookups must all be scoped to the same user.
6. **No runtime single-user fallbacks.** Helpers that return "the" user's setting (for example the
   sole stored timezone) are replaced by lookups keyed on the owner of the thing being processed.
7. **The wire contract does not expose ownership.** JSON:API resources and MCP result schemas do
   not gain a `user_id` attribute; ownership is enforced server-side, as it is for journals.
8. **MCP parity.** Every rule above applies identically to MCP tools, which resolve the acting user
   from the OAuth token.

## Scope

### In Scope

- Adding an owner to: **contacts** (and, through it, all `contact_*` child tables), **contact
  tags** (`tags`), **custom date types**, **journal tags**, and the integration link store
  **`sync_metadata`**.
- Per-user uniqueness where names are unique today: contact tag names, custom date type names,
  journal tag names.
- Owner-scoped reads and writes across the contacts domain: repositories, services, REST
  controllers, MCP tools, the contacts search index and global search, contact history, dashboard
  contact reads (upcoming important dates, contact importance), the contact summary generator.
- Ownership rules on every cross-entity link that involves a contact: journal participants, task
  contacts, contact relationships, contact merge, Strava athlete mappings, contact suggestions, Immich
  person conflicts.
- Integration logic: worker-published contact sync events carry the owner; the inbound consumer
  creates contacts for that owner and reconciles only within it; outbound pushes go only to the
  owner's connected accounts; worker reads of contacts are per-user; link-store lookups are per-user;
  background consumers resolve the owner's timezone instead of a single-user default.
- A data migration per table assigning every existing row to the site's one real user.
- Test infrastructure: a shared way to seed owned contacts, and cross-user isolation tests for every
  contact and tag endpoint and tool, following `test_journal_ownership.py`.

### Out of Scope

- **A `users` table or user administration.** Identity remains the OAuth subject string
  (`VARCHAR(50)`), with no foreign key, exactly as every existing `user_id` column works.
- **Sharing or collaboration** between users. An entity has one owner; there is no read grant.
- **Changing the JSON:API or MCP result shapes.** No new attributes are exposed.
- **Frontend changes**, beyond keeping the existing suites green. The UI already sends the session
  cookie; scoping is server-side.
- **Backfilling `field_history.user_id` for contact rows.** History reads for contacts authorise by
  loading the contact for the reader, as journals do; the rows themselves stay unstamped.
- **Re-deriving ownership of `outbox_events`.** The event log keeps no owner column; new events
  carry the owner in their payload.
- **Regenerable per-user caches** (`journal_daily_summaries`) — already scoped.

---

## Part 1: Ownership Audit

Established by reviewing the schema, repositories, services, controllers, MCP tools, search
indexer and all four workers during spec planning.

### Tables without an owner

| Table | Today | Target |
|-------|-------|--------|
| `contacts` | No `user_id`; every read and write is global | `user_id VARCHAR(50) NOT NULL`, indexed; the primary target |
| `contact_methods`, `contact_addresses`, `contact_notes`, `contact_important_dates`, `contact_summaries`, `contact_relationships`, `contact_tags`, `contact_edit_event` | Reach a contact through `contact_id` | Unchanged; owned through the contact |
| `tags` (contact tags) | No `user_id`; `UNIQUE(name)` is global | `user_id NOT NULL`; `UNIQUE(user_id, name)` |
| `custom_date_types` | No `user_id`; `UNIQUE(name)` is global | `user_id NOT NULL`; `UNIQUE(user_id, name)` |
| `journal_tags` | No `user_id`; `UNIQUE(name)` is global | `user_id NOT NULL`; `UNIQUE(user_id, name)` |
| `sync_metadata` | No `user_id`; `UNIQUE(integration_source, external_id)` is global | `user_id NOT NULL`; `UNIQUE(user_id, integration_source, external_id)` |

Every other table either carries `user_id` already (journals, tasks, calendars, gear items,
templates, series, review items, dismissals, daily summaries, sync jobs, athlete mappings, suggestion
ignores, pending entity mappings, all `user_*_auth` and settings tables) or reaches one through a
parent that does (all `journal_*` data tables, routes, task link tables, template pitches).

### Logic that assumes a single user

| Where | Assumption | Target |
|-------|------------|--------|
| Contact repositories, services, REST controllers, MCP tools | Reads and writes take no user; the session user is required only for authentication | Every aggregate read/write takes the acting user and filters in SQL |
| Contacts search index and global search | Documents carry no `user_id`; queries do not filter on one | Documents carry `user_id`; it is filterable; every query filters |
| Backend contact domain events (`ContactCreated`, `ContactUpdated`, `ContactDeleted`, `ContactMerged`) | No `user_id` in the payload | Payload carries the owner |
| Worker contact sync events (`contact.created` / `contact.updated` from Google and Immich) | No `user_id`; the inbound consumer cannot know who the contact is for | Payload carries the sync job's `user_id`; the consumer rejects events without one |
| Inbound consumer email reconciliation and tag get-or-create | Match any contact / any tag in the system | Match only the owner's contacts and tags |
| Google outbound (`process_contact_event`, `find_contacts_to_push`) | Pushes every contact to every `user_google_auth` row; reads all contacts | Pushes only to the owner's Google accounts; reads the owner's contacts |
| Immich outbound (`process_contact_event`) and name-match auto-link | Uses the event's `user_id` when present, otherwise falls back to every `user_immich_auth` row ("single-user by design"); `_fetch_user_contacts` matches against all contacts despite its name | Owner's Immich account only, and an event without an owner is rejected; matches within the owner's contacts |
| `sync_metadata` lookups (`find_by_external_id`, `find_and_lock`) | Global by `(source, external_id)` | Scoped by owner |
| Inbound consumer and summary consumer timezone | `get_default_timezone()` — "the sole stored timezone" | The owner's timezone, from the event's or entity's `user_id` |
| Cross-entity links: journal participants, task contacts, relationships, merge, athlete mappings, suggestion accept, Immich conflict resolution | Check existence only (recorded divergences) | Check ownership; a foreign contact is not found |
| Contact history read | No authorisation on the aggregate | Load the contact for the reader first; 404 otherwise |
| Contact summary generation | Falls back to the single stored timezone | Uses the contact owner's timezone |
| Test-only `DELETE /api/contacts/test/cleanup` | Deletes all contacts | Deletes the acting user's contacts |

---

## Part 2: Owned Contacts

### Target Behaviour

- A contact has exactly one owner, set when it is created and never changed. Creation through the
  REST API or MCP sets the acting user; creation through the inbound consumer sets the `user_id`
  carried by the sync event; creation from a contact suggestion, an Immich person conflict or a Strava
  athlete mapping sets the acting user.
- Every contact read (get, list, filter, favourites, by-tag, count, search, history, avatar, upcoming
  dates, importance, summary) returns only the acting user's contacts. A contact id belonging to another
  user answers 404 on every by-id endpoint and tool, and every write against it changes nothing.
- Child-row operations (methods, addresses, notes, important dates, tags on a contact, relationships)
  first prove the parent contact belongs to the acting user, then proceed unscoped on the child rows,
  as journal child operations do.
- A contact merge requires both contacts to belong to the acting user; a contact relationship
  requires both ends to (the `to_user` flag continues to mean "related to the contact's owner").
- Contact events carry the owner so the search indexer, history projection and workers can act
  per-user without a second lookup.

### Migration

A migration adds `contacts.user_id`, assigns every existing row to the site's one real user, then
makes the column `NOT NULL` and indexes it. The owner is derived exactly as migration `0106` does:
the single distinct `user_id` across the owner-bearing tables that is not a synthetic identity
(`debug-client`, `dev-user`). A database whose only owner is a synthetic identity (local dev, CI,
e2e) assigns rows to that identity. A database with no contacts does nothing. A database with more
than one real owner **refuses** and names them, unless the operator passes the owner explicitly
(`alembic -x contacts_owner=<user_id>`), matching the `-x` precedent of migration `0092`.

### Outcome

Contacts behave like journals: owned, filtered in SQL, invisible across users, with a wire contract
that does not change.

---

## Part 3: Owned Lookup Tables

### Contact tags, custom date types, journal tags

- Each table gains `user_id NOT NULL` and its global `UNIQUE(name)` becomes `UNIQUE(user_id, name)`.
  Two users may each have a `family` tag; hierarchy (`parent_id`) may only link tags of one owner.
- Listing, tree, search, create, update, delete and merge operations take the acting user and filter
  in SQL. Assigning a tag to a contact or journal requires the tag and the entity to share an owner.
- Inbound Google group sync creates or matches tags **within the owner's tags**; the outbound tag
  push reads a contact's tags through the contact, which is already owner-bound.
- The same migration approach as Part 2 assigns existing rows to the one real user.

### Outcome

Tag and date-type namespaces are per-user, so a second user's organisation cannot collide with or
reveal the first user's.

---

## Part 4: Ownership Across Entities

Every place that links a contact to something else enforces that the contact belongs to the acting
user, resolving the divergences recorded in iterations 13 and 18:

| Link | Rule |
|------|------|
| Journal participant / invitee / mention / about | The contact's owner equals the journal's owner; otherwise the contact is not found |
| Task contacts (`TaskService._resolve_contacts`, the "single place the rule lands") | The contact's owner equals the task's owner |
| Contact relationship (`from` / `to`) | Both contacts belong to the acting user |
| Contact merge | Survivor and source belong to the acting user |
| Strava athlete mapping → contact | The contact belongs to the mapping's user |
| Contact suggestion accept (existing target) and Immich person conflict resolution (candidate) | The target contact belongs to the acting user |
| Contact history | The contact is loaded for the reader first; task rows on a contact's history are named for the reader as today |
| Dashboard reads (upcoming important dates, contact importance) | Take `user_id` like every other dashboard port |

### Outcome

The three "if contacts ever gain ownership, this is where the rule lands" notes become the rule.

---

## Part 5: Search

- Contact search documents carry `user_id`; it is a filterable attribute of the contacts index, and
  a required one that startup verifies (as `JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES` does for
  journals).
- Every contact search — the contacts search endpoint, global search, MCP `search_contacts` and
  `global_search`, search suggestions — filters on the acting user before any other filter.
- Existing documents predate the field, so the deployment that ships this reindexes contacts (the
  existing reindex endpoint / `ReindexService`). Until then an owner-filtered query returns nothing,
  which is the safe direction.

---

## Part 6: Integrations

### Sync events name the owner

`ContactSyncEventData` gains `user_id`. The Google and Immich workers stamp the sync job's
`user_id` on every `contact.created` / `contact.updated` event they publish. The inbound consumer
creates the contact for that owner, reconciles by email only within that owner's contacts, and
resolves tags only within that owner's tags. An event without a `user_id` is a permanent processing
failure, never a guess (the Snipe-IT webhook rule).

### Outbound pushes go to the owner only

`ContactCreated` / `ContactUpdated` / `ContactDeleted` / `ContactMerged` carry the owner. The Google
and Immich workers push the change only to that user's connected account(s) — never to every
connected account — and an event that names no owner is rejected rather than fanned out (the Immich
worker already prefers the event's `user_id`; its fallback to every account is what goes). Periodic "find contacts to push" reads are per-user, and the Immich name-match
auto-link considers only the owner's contacts.

### The link store is per-user

`sync_metadata` gains `user_id NOT NULL` and its unique key becomes
`(user_id, integration_source, external_id)`. Existing rows are backfilled from the owning entity
(`internal_entity_type` → `contacts.user_id` / `journals.user_id` / `gear_items.user_id`), falling
back to the single-owner derivation for rows that cannot be resolved. Every lookup —
`find_by_external_id`, `find_and_lock`, the MCP `get_contact_by_external_id` and
`get_journal_by_external_id` tools, and every worker upsert — is keyed by owner. This is what stops
two users' Snipe-IT instances (whose asset ids overlap) or two Google accounts from claiming each
other's rows.

### No single-user fallbacks

`get_default_timezone()` is removed; the per-user `get_timezone(user_id)` remains the one timezone
lookup. The inbound consumer's title-similarity assessor and the summary consumer resolve the
timezone of the owner named by the event or the contact.

### Outcome

A contact synced by user A exists for user A, links to A's external ids, is pushed to A's accounts,
and is never matched against B's data.

---

## Success Criteria

This work will be successful when:

1. `contacts`, `tags`, `custom_date_types`, `journal_tags` and `sync_metadata` each carry
   `user_id NOT NULL`, and every existing row has been assigned to the site's one real user by a
   migration that refuses ambiguous ownership.
2. Name uniqueness for contact tags, custom date types and journal tags is per-user.
3. Every contact and tag repository method that reads an aggregate takes `user_id` and filters in
   SQL; every REST endpoint and MCP tool for contacts and tags answers 404 for another user's entity
   and leaves it unchanged, proven by cross-user isolation tests modelled on
   `test_journal_ownership.py` for REST and its MCP counterpart.
4. Contact search and global search return only the acting user's contacts.
5. Every cross-entity link involving a contact (Part 4) treats a foreign contact as not found, and
   the divergence notes in iterations 13 and 18 and in `domain-architecture.md` are replaced by the
   enforced rule.
6. Worker-published contact sync events and backend contact domain events carry `user_id`; the
   inbound consumer scopes creation, reconciliation and tag resolution to it; outbound pushes reach
   only the owner's accounts; `sync_metadata` lookups are per-user.
7. No `get_default_timezone()` or "single-user by design" path remains in the backend or workers.
8. All existing backend, worker, frontend and e2e suites stay green; the frontend and the JSON:API /
   MCP result shapes are unchanged.

## Delivery Notes

This specification defines target behaviour. Delivery should be phased so `main` stays green and
deployable after every PR (≤ 500 changed lines each), following the expand → migrate → contract
discipline of iteration 15 where a change spans workers and the backend.

### Suggested Phasing

1. **Test seeding.** Consolidate the tests' raw `INSERT INTO contacts` statements (54 files) onto
   shared seeding helpers, so the schema change lands in one place.
2. **Owner on the entity and on sync events (core_shared + workers).** Add `user_id` to the shared
   `Contact` entity and serialisation, and to `ContactSyncEventData`; workers stamp the sync job's
   user. Additive; the backend ignores it until the next phase.
3. **Owned contacts — schema and writers.** Migration with backfill; every backend creation path
   stamps the acting user; the inbound consumer uses the event's owner; contact events carry the
   owner. Reads still unscoped.
4. **Owned contacts — reads.** Repository, service, REST controllers scoped; cross-user REST
   isolation tests.
5. **MCP parity** for contacts, then **search** (documents, filterable attribute, every query,
   reindex).
6. **Lookup tables:** contact tags, custom date types, journal tags — one phase each.
7. **Ownership across entities** (Part 4), split between core links (journals, tasks, relationships,
   merge) and integration-adjacent links (athlete mapping, suggestions, Immich conflicts, history).
8. **Integrations:** outbound pushes to the owner only and per-user worker reads; then the
   per-user link store (expand, backfill and all writers first; then the contract and the unique
   key swap); then removal of the timezone fallbacks.
9. **Closure:** architecture documents updated, divergence notes resolved, grep gates for
   unscoped methods and single-user helpers.

Phases 2 and 3 must deploy together or workers-first: a backend that requires `user_id` on sync
events must never run against a worker that does not send it.
