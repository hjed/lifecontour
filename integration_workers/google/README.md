# Google Contacts Integration Worker

ARQ-based worker for syncing contacts between Lifecontour and Google Contacts.

## Features

- **Two-way sync**: Sync contacts from Google to local database and push local changes to Google
- **Periodic sync**: Automatically sync contacts at configurable intervals
- **Smart sync**: Intelligent sync strategy that chooses between full and incremental sync
- **Retry logic**: Exponential backoff with jitter for failed operations
- **Outbox pattern**: Reliable event processing for contact changes

## Architecture

The worker uses ARQ (Async Redis Queue) for task processing and supports:

- **Manual sync**: Triggered via API calls to the main application
- **Periodic sync**: Automatic syncing using ARQ cron jobs
- **Event-driven**: Processes outbox events for reliable data synchronization

### Sync Flow

**Inbound (Google → Local)**:
1. Worker fetches contacts from Google People API
2. Creates `OutboxEvent` records for each contact
3. Main app's `OutboxProcessor` processes events every 10 seconds
4. `OutboxEventProcessor` transforms Google Person data to Contact entities
5. Domain services create/update local contacts

**Outbound (Local → Google)** — two paths, both pushing the contact's whole
current state:

1. **Event-driven (the normal path).** A contact domain event arrives on the
   stream and `process_contact_event` pushes that contact immediately. See
   [Stream Consumer](#stream-consumer) for the events this covers.
2. **Reconciliation (the safety net).** `sync_google_contacts` calls
   `_push_pending_local_contacts` **before** it pulls, pushing every contact
   that is new locally or whose `updated_at` is newer than its
   `sync_metadata.last_synced_at`. This repairs anything the event path missed —
   a worker restart, a trimmed stream — and, because it runs in the same job as
   the pull, guarantees the pull cannot overwrite an edit that has not reached
   Google yet. Splitting the two into separate ARQ jobs would lose that ordering.

Both paths update `sync_metadata` with the Google resource name and the ETag
Google returns, which is what makes the following pull a no-op for that contact
rather than a re-apply of Google's older copy.

A failing push is logged and the pull still runs. Ordinarily a failed push
leaves Google's ETag unchanged, so the inbound idempotency check skips that
contact and the local edit survives to be pushed next cycle. The exception is a
genuine two-sided conflict — the contact was also edited in Google and the
push's conflict retry failed too — where the pull applies Google's copy.

A linked contact that no longer exists in Google (the update returns 404,
surfaced as `GoogleContactNotFoundError`) is **recreated**: a push only happens
when there are local edits, so both paths create a new Google person from the
local contact and re-point the existing `sync_metadata` link at the new
resource name in place, so its `reference_data` (the backend's `synced_tags`)
survives (`_update_or_recreate_contact_in_google`). The cron path counts it as
created.

Both push paths take a per-contact advisory lock (`_lock_contact_for_push`)
before reading the contact's sync link, and the cron path commits per contact.
Without it the stream handler and the cron could both see a new contact as
unlinked and both create it, leaving two Google contacts for one local contact.

`push_local_contacts_to_google` remains as a standalone ARQ task over the same
helper, for pushing an account on demand without a pull.

### Recurrences split under a new id

A "this and following" edit sometimes gives the rest of a recurrence an
`<old>_R<time>` id, which `recurrence.root_recurring_event_id` folds into the
old series. Sometimes Google starts the rest under an **unrelated** id. In one
sync that reads as each upcoming instance of the old recurrence arriving
cancelled, alongside new instances nobody has journalled.

Before the event loop, `split_adoption.find_split_pairing` pairs them:
- the old half must be cancelled in the batch and linked here, not outbound-only
  and not already over;
- the new half must be a live instance of a different recurrence with no link
  yet;
- the two must share a local day (in the user's zone) and a title, trimmed and
  ignoring case, and each must be the only candidate for that day and title.

The new instance is then sent as an update of the old journal, carrying
`split_adopted_from` (the old recurrence's series key), and the old instance's
cancellation is dropped. The backend re-points the journal, keeps its title and
notes, and folds the new recurrence into the old series. A batch without both
halves costs no extra query.

Halves that arrive in different syncs are not paired here. The cancellations
apply the backend's keep-next rule instead.

### What the outbound journal push declines to do

`_process_journal_upsert_event` pushes an EVENT journal to Google Calendar. Two
things stop it, each returning `{"status": "ignored", …}` rather than raising —
a raise leaves the stream message unacknowledged and redelivers it until it
dead-letters, which is the wrong answer for both.

| `reason` | When | Why |
|---|---|---|
| `inbound_sync_echo` | The journal event's `source` is `google_calendar`, i.e. the Google inbound sync is what applied it | The inbound sync writes the journal *and* its external event link in one transaction, so the push would PATCH the very event the journal was built from. Nothing to send, and Google rejects it outright for the event types it derives. |
| `event_type_not_modifiable` | Google answered the write with a 400 `eventTypeRestriction` | The event is one Google owns and derives — a birthday from Contacts, an event from Gmail — and accepts almost no change ([event types](https://developers.google.com/workspace/calendar/api/guides/event-types)). A permanent rejection: no retry and no reshaped payload makes it land. The journal keeps the local edit and the link is left `sync_status = 'errored'`, which is where the divergence from Google shows. |

The echo guard reads the event's provenance, not the journal's origin: a user's
own edit to a journal that arrived from Google still carries `source = ui` and
still reaches Google.

### Stream Consumer

`GoogleWorkerStreamConsumer` (in [`stream_consumer_tasks.py`](stream_consumer_tasks.py))
consumes domain events from the `pms:domain-events` Redis stream using the
`google-worker` consumer group. It declares a **declarative route table** (a list
of `core_shared.EventRoute`) instead of overriding `_handle_event`; the shared
`StreamConsumer` runs the `XREADGROUP`/ack/retry loop, dispatches each matched
event to its handler, and immediately acks unmatched events. The route table is
the single source of truth for the worker's consumed-event set:

| Event type | Handler |
|---|---|
| `JournalCreated`, `JournalUpdated`, `JournalDeleted` | `process_journal_event` |
| `TagUpdated`, `TagDeleted` | `process_tag_event` |
| every event in `CONTACT_PUSH_EVENT_TYPES` (see below) | `process_contact_event` |

The contact half of that table is **derived from**
`core_shared.models.contacts.event_types.CONTACT_PUSH_EVENT_TYPES` rather than
listed here, because a hand-maintained list fell behind the contacts domain
(LOCAL-177): only the four aggregate-level events were routed, so adding a tag,
adding or removing an email address, and every important-date edit were read off
the stream, acknowledged and dropped. That registry currently covers:

- `ContactCreated`, `ContactUpdated`, `ContactDeleted`, `ContactMerged`
- `TagAssigned`, `TagRemoved` — contact-group membership
- `ContactMethodAdded`, `ContactMethodDeleted` — emails and phone numbers
- `ContactAddressAdded`, `ContactAddressDeleted` — postal addresses
- `ContactNoteAdded` — biographies
- `ImportantDateAdded`, `ImportantDateUpdated`, `ImportantDateDeleted` —
  birthdays and events

Every one of them pushes the contact's **whole current state**, so the event only
has to identify which contact changed. Events carrying the inbound sync's
provenance (`source == "google_contacts"`) are skipped, so applying Google's data
locally does not write it straight back to Google.

Tags are pushed as contact-group memberships. The handler resolves the contact's
tag names to group resource names per Google account (creating any group a tag
still needs) via `_resolve_group_mapping_for_tags`, which the cron push shares.
The payload always carries the **reserved** groups from `GOOGLE_RESERVED_GROUPS`
alongside the tag groups: `updatePersonFields=memberships` replaces the
membership list rather than merging into it, so a payload without
`contactGroups/myContacts` would drop the contact out of the user's contacts
altogether. For the same reason `contactGroups/starred` is written back from
`is_favourite` (the field inbound sync reads it into): omitting it would unstar
every favourite on any edit.

A tag finds its group by the **tag path** the group's display name becomes, not
by the display name itself. Inbound sanitises each `/`-separated segment
(`group_naming.py`): "Family Friends" becomes the tag `Family-Friends`, and
"Family/Extended" becomes `Family` with the child `Extended`. The push keys the
groups the same way (`_build_reverse_group_mapping`), matching case-insensitively,
so a renamed-by-sanitising tag keeps its membership and no duplicate group is
created (#1821). Some details:

- A group is also keyed by its display name when that is a valid tag path, so
  a group the push created for the tag `A--B` (which sanitises to `A-B`) is
  found again. A group named exactly like a tag beats one that only sanitises
  to it ("Family-Friends" over "Family Friends").
- Reserved groups and `starred` are never a tag's group.
- A tag that is only the parent of another of the contact's tags (`Family` beside
  `Family/Extended`) gets no group created for it (`_tags_needing_groups`):
  the next pull derives it from the child again.
- A group whose name sanitises to nothing (e.g. `家族`) has no tag, so a push
  still drops its membership (#1835).

Tag events (`TagUpdated`, `TagDeleted`) find the group to rename or delete the
same way.

The nickname is two-way. Inbound sync imports the primary Google nickname (or
the first one), and the push always sends `nicknames`: a nickname cleared locally
goes as an empty list, so Google drops it too and the next pull does not bring it
back. The import changes only the fields in `GOOGLE_CONTACT_SYNC_SCOPE`
(`transformer.py`); see "Contact sync scope" in
`docs/architecture/integration-architecture.md`. A full sync re-applies every
person, even one whose etag is unchanged (`force_apply`), so a field the scope
newly claims reaches every contact.

An update push **merges into** the person rather than replacing it (#1732).
`updatePersonFields` replaces each named field wholesale, but the local model
cannot represent everything Google holds, so `_update_or_recreate_contact_in_google`
reads the person first and `person_merge.merge_with_current_person` keeps what
the local contact does not own. The local contact owns exactly what inbound sync
imports, and the merge asks the import's own per-entry functions
(`import_email`, `import_address`, `import_birthday`, … in `transformer.py`), so
the two cannot drift apart (#1788). Every pushed field has a policy in
`person_merge.FIELD_POLICIES`, and `tests/unit/test_push_field_ownership.py`
fails when a pushed field has none:

| Field | Local contact owns | Kept from Google |
|---|---|---|
| `names` | given, family and middle name | honorific prefix/suffix, phonetic names |
| `nicknames` | the one inbound reads (primary, else first) | every other nickname, beside a pushed one; clearing the nickname clears them all, or the next pull would import a survivor |
| `emailAddresses`, `phoneNumbers` | the entries inbound imports that are in the synced base | entries it rejects (invalid values), and entries added in Google since the base |
| `addresses` | the entries inbound imports that are in the synced base, including a countryless one the last applied pull gave a country (a recognised AU/US/CA region as its code) | entries it rejects: no street, no country and none recorded, or an AU/US/CA region naming no state, province or territory in the country it is imported with — reported on the event as `skipped_addresses` for the user to review (#1820); and entries added in Google since the base |
| `birthdays` | a birthday with a usable date | a text-only birthday, or one added or edited in Google since the base while the local one is unchanged: the field leaves the update mask, so Google keeps it |
| `events` | `anniversary` events | every other event (custom, untyped) |
| `organizations` | name and title of the org inbound reads (first current, else first) | that org's other parts (department, type…) and every other org |
| `biographies`, `memberships` | everything | nothing (memberships: see #1821) |

Parts of an owned entry the local model cannot hold (an address's type, a
phone's formatting) are still replaced (#1823).

**Synced base (#1861).** Importable is not the same as held: an email added in
Google after the last pull is importable, but the contact has never seen it.
So the emails, phones, addresses and birthdays merge **three ways** against the
synced base — the keys (`synced_entries.py`) of the entries the last sync
agreed both sides held, recorded on the link (see the integration architecture
doc). A key covers only the imported value: an email's address, an address's
parts (both street lines as one) in the country it was imported with, a
birthday's date. A phone carries a key per spelling - its E.164 form and its
digits as typed - since the push sends a number as typed and Google answers
with it canonical; two entries are one when any key matches.

- An entry Google gained since the base is **kept**, and the link is marked
  `pending_import`, so the next pull imports it despite the push's own etag.
- An entry in the base the contact no longer holds was deleted locally: it is
  **dropped**.
- An entry in the base Google no longer holds was deleted or edited there: the
  unchanged local copy is **not pushed back** over it, and the next pull
  removes or updates it locally.
- An entry both sides hold is sent once.

The pull sends the base it read on the contact event; every push records the
base Google's response holds (less what it kept), because Google reformats
values such as phone numbers. A link with no base yet uses the etag: a person
unchanged since the last sync is its own base, and a changed one keeps every
entry until a pull records a base.

**Address country (#1820).** The local model requires a country, but Google
often holds addresses without a `countryCode`. Inbound gives such an address
the country of the contact's **primary** phone, else the one all its other
phones agree on, else the syncing user's **default country**
(`user_settings.default_country`, set in Settings). Only international (`+`)
numbers count, and only ISO 3166-1 countries (`address_country.py`). With
none of them the address is not imported, and Google keeps it.

The contact event carries that fallback (`address_fallback_country`), and the
backend records it on the link's `reference_data` when it **applies** the
event. A push merges with the **recorded** fallback, not what it would infer
now, so it owns exactly the countryless addresses the last applied pull
imported:

- an imported one is sent back **with** its `countryCode`, writing a country
  Google never had, and the countryless original is not kept beside it; a
  local delete or edit of it reaches Google;
- one no applied pull imported — the phone or a default changed since, or the
  person has not been re-pulled since this shipped — is kept, never deleted.

An inferred address that duplicates one Google also holds with a country
(left by pushes before #1820) is dropped on import, and the push then removes
the countryless twin from Google. Migration `0139` forces one full sync so
existing contacts are re-pulled, and saving the default country clears that
user's contacts sync token with the save (then queues a sync, best-effort), so
their next sync is a full one. The backend normalises an AU/US/CA region to its
code ("New South Wales" -> "NSW") and validates no postcode, so a typed region
or a wrongly inferred country never fails the contact.

The owned entry is chosen exactly as the import chooses it, and values from a
linked profile (rather than the contact) are never copied into the contact. The
merge only touches fields the payload already names, so the update mask is
unchanged, and the update goes out against the etag of the version it merged
with. If Google changes in between, the client's conflict retry merges again
into the person it refetches (`update_contact(..., rebase=...)`) rather than
resending the older merge. A 404 on that read takes the same recreate path as one on the update.
Each update push therefore costs one People API read as well as the write.
`biographies` is not merged: a Google contact holds a single biography, so all
local notes are pushed joined into it.

Because an incomplete group mapping would strip memberships, outbound code lists
groups with the strict `_fetch_contact_group_mapping`, which raises on any failed
page. On the contact event path that leaves the stream event unacknowledged for
retry, and a tag event reports it as `partial_success`; the inbound sync keeps the tolerant `_build_contact_group_mapping`, where a
missing group only costs a tag on import.

Each handler builds a minimal ARQ-compatible context (`session_factory` +
`job_id`) and calls the existing worker function directly, bypassing ARQ enqueue.
A handler that raises leaves its event unacknowledged so the base class retries
it via the pending-entries path. See
[Stream-Consumer Route Registration](../../docs/architecture/integration-architecture.md)
for the shared convention.

## Configuration

Settings live in [`google_settings.py`](google_settings.py) as `GoogleSettings`,
which subclasses the shared `core_shared.BaseWorkerSettings`. The common worker
surface — database/Redis connection, ARQ queue/stream identity, logging,
periodic-sync cadence and the OpenTelemetry block — is declared once in the base
and inherited here; only the Google-specific fields below are declared locally.
Secrets (`DATABASE_URL`, `GOOGLE_CLIENT_SECRET`, `ENCRYPTION_KEY`) are
`SecretStr` so they stay out of logs and tracebacks.

### Environment Variables

**Inherited from `BaseWorkerSettings`** (see `core_shared/core_shared/worker_settings.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *required* | PostgreSQL connection string (`SecretStr`) |
| `REDIS_URL` | `redis://redis:6379` | Redis connection string for ARQ + event stream |
| `STREAM_NAME` | `pms:domain-events` | Shared domain-events Redis stream |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ENABLE_PERIODIC_SYNC` | `false` | Enable automatic periodic syncing |
| `SYNC_INTERVAL_HOURS` | `6` | Hours between periodic syncs |
| `ENABLE_TELEMETRY` | `false` | Enable OpenTelemetry export |
| `OTEL_*` | `""` | OpenTelemetry exporter/resource configuration |

**Google-specific (declared in `GoogleSettings`)**:

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_CLIENT_ID` | *required* | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | *required* | Google OAuth client secret (`SecretStr`) |
| `ENCRYPTION_KEY` | *required* | Key for encrypting OAuth tokens (`SecretStr`) |
| `WORKER_ID` | `google-worker` | Unique worker identifier (overrides base default) |
| `MAX_CONCURRENT_JOBS` | `5` | Maximum concurrent ARQ jobs |
| `GOOGLE_RESERVED_GROUPS` | `["myContacts"]` | Google groups to ignore during sync |
| `WEBHOOK_BASE_URL` | `""` | Public HTTPS URL for webhook callbacks; push notifications are disabled while unset |
| `WEBHOOK_RENEWAL_THRESHOLD_HOURS` | `48` | How far ahead of a watch channel's expiry to re-register it |

### ARQ Worker Settings

The ARQ `GoogleWorkerSettings` (in [`worker.py`](worker.py)) is built from the
shared toolkit in `core_shared` (ITER14-002): operational defaults, the
`build_worker_lifecycle` startup/shutdown factory, the `generate_cron_jobs`
helper, and `redis_settings_from_url`. It declares only its functions list, its
consumer wiring, and documented overrides:

```python
class GoogleWorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    functions = [
        sync_google_contacts,
        push_local_contacts_to_google,
        sync_calendar_events,
        setup_calendar_webhook,
        renew_calendar_webhooks,
        periodic_sync_all_accounts,
    ]
    on_startup = _on_startup  # build_worker_lifecycle(close_session_factory=True)
    on_shutdown = _on_shutdown
    redis_settings = redis_settings_from_url(settings.redis_url)
    queue_name = ARQ_QUEUE_NAME

    # Documented overrides (everything else inherits the shared defaults):
    job_timeout = 600  # 10 min — large accounts page slowly
    max_jobs = settings.max_concurrent_jobs

    cron_jobs = generate_cron_jobs(
        periodic_sync_all_accounts,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )
```

`keep_result`, `max_tries`, and the retry backoff match the `SharedARQWorkerSettings`
baseline — which equals arq's own constructor defaults, so they apply unchanged.
Note: arq's `get_kwargs` reads only the leaf class's attributes, so an *inherited*
default is invisible to arq and falls back to arq's own. This matters for
`health_check_interval`: the shared baseline is `30`, but arq's default is `3600`,
so this worker (which does not redeclare it) runs at `3600` — the shared `30`
applies only to workers that declare it on the leaf. The per-worker
`startup`/`shutdown`, the local `retry_delay_func`, and the inline cron block were
removed.

### Periodic Sync Configuration

Periodic sync is **disabled by default** for safety. To enable:

```yaml
# docker-compose.yml
environment:
  ENABLE_PERIODIC_SYNC: "true"
  SYNC_INTERVAL_HOURS: "6"  # Sync every 6 hours
```

**Sync Interval Examples**:
- `1` - Hourly sync (every hour at :00)
- `6` - Every 6 hours (00:00, 06:00, 12:00, 18:00)
- `12` - Twice daily (00:00, 12:00)
- `24` - Daily (00:00)

**How Periodic Sync Works**:
1. ARQ cron job triggers `periodic_sync_all_accounts` at configured intervals
2. Function queries database for all active Google integrations
3. Enqueues individual `sync_google_contacts` tasks for each account
4. Each account syncs independently using "smart" sync strategy

### Sync Types

The worker supports three sync strategies:

- **`full`**: Fetch all contacts from Google (ignores sync tokens)
- **`incremental`**: Fetch only changes since last sync (uses sync tokens)
- **`smart`**: Automatically chooses between full and incremental based on sync state

Periodic syncs always use **`smart`** strategy for efficiency.

## Running the Worker

### Development

```bash
# Start with Docker Compose
docker compose --profile dev up google-worker

# View logs
docker compose logs -f google-worker

# Run tests
docker compose exec google-worker pytest tests/unit/ -v
```

### Production

```bash
# Enable periodic sync in production
export ENABLE_PERIODIC_SYNC=true
export SYNC_INTERVAL_HOURS=6

# Start worker
docker compose --profile prod up -d google-worker
```

## Tasks

The worker provides these ARQ tasks:

### 1. `sync_google_contacts`

Syncs contacts from Google to local database.

**Parameters**:
- `google_account_email` (str): Google account email
- `user_id` (int): User ID in local database
- `sync_type` (str): Sync strategy (`full`, `incremental`, or `smart`)

**Example**:
```python
await redis.enqueue_job("sync_google_contacts", "user@example.com", 123, "smart")
```

### 2. `push_local_contacts_to_google`

Pushes locally created/updated contacts to Google.

**Parameters**:
- `google_account_email` (str): Google account email
- `user_id` (int): User ID in local database

### 3. `setup_calendar_webhook`

Registers a Google Calendar push notification channel for one calendar and
persists its metadata in `calendar_sync_tokens`. Any previous channel for that
calendar is stopped first.

**Parameters**:
- `google_account_email` (str): Google account email
- `user_id` (str | int): User ID in local database
- `google_calendar_id` (str): The Google Calendar to watch

### 4. `renew_calendar_webhooks`

Internal task called by ARQ cron. Finds synced calendars whose watch channel is
lapsing and enqueues a `setup_calendar_webhook` job for each. See
[Calendar push channels](#calendar-push-channels).

**Note**: Triggered by cron every 6 hours. Do not call manually.

### 5. `periodic_sync_all_accounts`

Internal task called by ARQ cron jobs. Queries all active Google integrations and enqueues sync tasks.

**Note**: This task is automatically triggered by cron when `ENABLE_PERIODIC_SYNC=true`. Do not call manually.

## Calendar push channels

Inbound calendar changes reach the app two ways: the periodic sync above, and
Google Calendar push notifications. Push is the low-latency path, and it depends
on a *watch channel* registered per calendar.

Channels are not permanent. `watch_events` requests a 7-day TTL, and once that
elapses Google discards the channel and stops delivering notifications — without
telling us. Left alone, push-driven sync therefore dies about weekly.

The lifecycle:

1. **Register** — `setup_calendar_webhook` calls `events().watch()` and stores
   `channel_id`, `channel_resource_id` and `channel_expiration` in
   `calendar_sync_tokens`.
2. **Notify** — Google POSTs to `/api/integrations/google/calendar/webhook`,
   which matches the channel against that table and enqueues a smart calendar
   sync.
3. **Renew** — `renew_calendar_webhooks` runs on a cron every 6 hours and
   re-registers any synced calendar whose channel expires within
   `WEBHOOK_RENEWAL_THRESHOLD_HOURS` (48 by default), is missing, or has no
   recorded expiry. With a 7-day TTL each channel is renewed roughly every 5
   days, leaving several sweeps of margin.

Two properties are worth knowing when reading this code:

- **Renewal is independent of `ENABLE_PERIODIC_SYNC`.** Push notifications
  matter most when periodic sync is off, so gating renewal on that flag would
  disable it exactly where it is load-bearing.
- **Stopping a channel is idempotent.** `GoogleAPIClient.stop_channel` treats
  404 and 410 as success, because a channel Google has already forgotten is
  already in the state the call exists to produce. `setup_calendar_webhook`
  also skips the stop entirely when the stored expiry has passed.
- **Setup is serialised per calendar.** Registering a channel is read-then-write
  across two Google calls, so `setup_calendar_webhook` takes a transaction-scoped
  advisory lock on (user, calendar) first. The account is deliberately not part
  of the key: renewal and manual re-registration can resolve different accounts
  for the same calendar, and keying on it would hand them separate locks.
  Renewal jobs additionally carry a job id keyed to the calendar, so ARQ rejects
  a duplicate rather than dispatching a second setup that would race the first.
- **The account is chosen from the existing channel.** A calendar records no
  Google account of its own, so renewal reuses the account its current channel
  was registered under, falling back to a deterministically chosen connected
  account only when there is no usable channel.

`setup_calendar_webhook` signals retryability the way the rest of the workers
do — by whether it raises. A refusal no retry can change (a calendar this
account may not watch, one Google no longer knows, a disconnected account) is
logged and returned, so the job succeeds and the next sweep tries again in six
hours. Anything that might pass next time — a quota 403, a 5xx, a database
blip — raises, so ARQ retries it in seconds rather than leaving a channel to
lapse inside its renewal window.

Everything here no-ops when `WEBHOOK_BASE_URL` is unset, leaving periodic sync
as the only inbound path.

## Monitoring

The worker uses structured logging (JSON format) for easy parsing and monitoring.

**Key log fields**:
- `event`: Event type (e.g., "sync_started", "sync_completed")
- `job_id`: ARQ job ID
- `google_account_email`: Account being synced
- `user_id`: User ID
- `contacts_fetched`: Number of contacts fetched
- `duration_seconds`: Operation duration

**Periodic sync logs**:
- "Starting periodic sync for all Google accounts"
- "Found active Google accounts for periodic sync" (with `accounts_count`)
- "Enqueued periodic sync job" (with `job_id`, `google_account_email`, `user_id`)
- "Periodic sync scheduling complete" (with `accounts_found`, `jobs_enqueued`, `errors_count`)

## Testing

```bash
# Run unit tests (shared pytest config at the repo root)
pytest -c ../../pytest.ini --rootdir . tests/unit/ -v

# Run integration tests (requires Redis and PostgreSQL)
pytest -c ../../pytest.ini --rootdir . tests/integration/ -v

# Linting
ruff check .
ruff format .

# Type checking (shared mypy config at the repo root)
mypy --config-file ../../mypy.ini .
```

### Shared test fixtures

Common test scaffolding is shared via `core_shared.testing` (ITER14-005). The top-level
`tests/conftest.py` registers the unit-fixture plugin
(`pytest_plugins = ["core_shared.testing"]`), making `mock_redis`, `worker_settings`,
`session_factory_mock`, and `arq_ctx` (plus the `make_*` helpers) available to unit tests. The DB
fixtures (`async_engine`, `async_connection`, `db_session`, `apply_migrations`) are imported into
`tests/integration/conftest.py` from `core_shared.testing.integration`; only this worker's
environment preamble remains there. See
[testing-strategy.md](../../docs/architecture/testing-strategy.md) for details.

## Troubleshooting

### Worker not syncing periodically

1. Check `ENABLE_PERIODIC_SYNC` is set to `true`
2. Verify worker logs show "Periodic sync enabled" on startup
3. Check for active Google integrations in `user_google_auth` table

### Sync failures

1. Check worker logs for error details
2. Verify Google OAuth credentials are valid
3. Check database connectivity
4. Verify Redis is accessible

### High memory usage

1. Reduce `MAX_CONCURRENT_JOBS` to limit parallel processing
2. Increase `SYNC_INTERVAL_HOURS` to reduce sync frequency
3. Monitor contact count per account

## Development

### Adding New Features

1. Write tests first (see `tests/unit/` for examples)
2. Implement feature in `worker.py`
3. Run tests and linting
4. Update documentation

### Code Quality

- Follow PEP 8 style guide
- Use type hints for all functions
- Write docstrings for public functions
- Maintain test coverage above 80%

## License

`AGPL-3.0-or-later`, see the repository [`LICENSE`](../../LICENSE).

