# Google Contacts Integration Worker

ARQ-based worker for syncing contacts between the Personal Management System and Google Contacts.

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

**Outbound (Local → Google)**:
1. Worker detects locally created/updated contacts
2. Pushes changes to Google People API
3. Updates sync metadata with Google resource names and ETags

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
| `ContactCreated`, `ContactUpdated`, `ContactDeleted`, `ContactMerged` | `process_contact_event` |

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

AGPL-3.0

