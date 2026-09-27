# Snipe-IT Integration Worker

ARQ-based worker for syncing Snipe-IT assets and maintenance records with the
Personal Management System (bidirectional gear sync, maintenance-as-journal
import, and gear checkout sync).

## Architecture

The worker uses ARQ (Async Redis Queue) for task processing and supports manual
sync (triggered via the main application), a scheduled periodic sync (when
enabled, see below), webhook-driven updates, and a domain-events stream
consumer.

Per-user Snipe-IT credentials (API key + base URL) are stored **encrypted in the
database** (`user_snipe_it_auth`), not in environment variables; the worker
decrypts them at runtime using `ENCRYPTION_KEY`.

### Stream Consumer

`SnipeItWorkerStreamConsumer` (in [`stream_consumer_tasks.py`](stream_consumer_tasks.py))
consumes domain events from the `pms:domain-events` Redis stream using the
`snipeit-worker` consumer group. It declares a **declarative route table** (a list
of `core_shared.EventRoute`) instead of overriding `_handle_event`; the shared
`StreamConsumer` runs the `XREADGROUP`/ack/retry loop, dispatches each matched
event to its handler, and immediately acks unmatched events. The route table is
the single source of truth for the worker's consumed-event set:

| Event type | Handler | Behaviour |
|---|---|---|
| `GearItemUpdated` | `_handle_gear_item_updated` | pushes local gear changes to Snipe-IT |
| `JournalCreated`, `JournalUpdated` | `_handle_journal_maintenance_event` | syncs gear-maintenance / gear-usage journals; an edit to a maintenance journal imported from Snipe-IT updates the record it came from, and an update the inbound sync applied (`changed_by` `snipeit_maintenance`) is skipped |
| `snipeit.webhook_received` | `_handle_webhook_received` | syncs the webhook's asset (`item.id`). The backend translates Snipe-IT's Slack-format notifications into `{action, item: {id}}` and publishes only those that link an asset |

A handler that raises leaves its event unacknowledged so the base class retries
it via the pending-entries path. A gear-usage journal is reconciled on create as
well as on update, so a redelivered create finishes a (journal, asset) pair
whose check-in failed after its checkout was recorded. See
[Stream-Consumer Route Registration](../../docs/architecture/integration-architecture.md)
for the shared convention.

## Configuration

Settings live in [`snipeit_settings.py`](snipeit_settings.py) as
`SnipeItWorkerSettings`, which subclasses the shared
`core_shared.BaseWorkerSettings`. The common worker surface — database/Redis
connection, ARQ queue/stream identity, logging, periodic-sync cadence and the
OpenTelemetry block — is declared once in the base and inherited here; only the
Snipe-IT-specific fields below are declared locally. Secrets (`DATABASE_URL`,
`ENCRYPTION_KEY`) are `SecretStr` so they stay out of logs and tracebacks; call
sites read the raw value via `.get_secret_value()`.

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

**Snipe-IT-specific (declared in `SnipeItWorkerSettings`)**:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENCRYPTION_KEY` | `""` | Fernet key for decrypting stored Snipe-IT API keys (`SecretStr`) |
| `WORKER_ID` | `snipeit-worker` | Unique worker identifier (overrides base default) |
| `QUEUE_NAME` | `arq:snipeit` | ARQ queue name (overrides base default) |
| `OTEL_SERVICE_NAME` | `snipeit-worker` | OpenTelemetry service name (overrides base default) |

### Periodic Sync Configuration

Periodic sync is **disabled by default**. The worker inherits
`ENABLE_PERIODIC_SYNC`/`SYNC_INTERVAL_HOURS` from `BaseWorkerSettings`; enable it
by setting `ENABLE_PERIODIC_SYNC=true` and a `SYNC_INTERVAL_HOURS` cadence. Two
cron jobs then run every `SYNC_INTERVAL_HOURS`-th hour, half an hour apart so
their Snipe-IT traffic does not compete for the rate limit:

- `periodic_sync_all_snipeit_accounts` (at `:30`) — for every user with Snipe-IT settings
  and working auth (`needs_reauth = FALSE`), enqueues `sync_snipeit_assets` and
  `sync_snipeit_maintenances` with sync type `smart`, writing a `sync_jobs` row
  for each before queueing it (a job arq refuses has its row failed). Snipe-IT sends no webhooks for asset creation, asset edits or
  maintenance records, so this is the only way those changes arrive without a
  manual sync. Neither orchestrator honours `smart` yet (#1560), so each run is a
  full re-import; unchanged assets and maintenance records are skipped by
  version hash. The asset and maintenance syncs run concurrently, so a
  maintenance record on an asset new in this run can be skipped as "gear item
  not yet synced"; it is imported by the next run (#1563).
  Once the maintenance listing has run to the end, the sync rows of records it
  did not return are reconciled (`reconcile_deleted_maintenances`): each record
  is looked up, and the row of one Snipe-IT no longer has is deleted, except the
  push row of a live journal a user wrote. A listing that fails part-way
  reconciles nothing, and a smart sync that stops listing everything (#1560)
  must skip this step too.
- `periodic_checkin_all_snipeit_accounts` (at `:00`) — finishes the gear usage pushes left
  unfinished. `fetch_unsynced_gear_usage` selects each (journal, asset) pair
  whose checkout failed (unless terminal, `error_message` starting `Terminal:`),
  is pending past the five-minute in-flight lock, or succeeded with no check-in
  once the usage period has ended (or the journal no longer lists the item).
  Only pairs a push was attempted for are selected, so old journals are not
  backfilled. Each pair is reconciled, oldest first per asset; after a failure
  the asset's later pairs wait for the next run (they would fail "not
  available"), a user still rate limited is left for the next run, and at most
  `SWEEP_MAX_PAIRS` (40) pairs per user are handled per run.

### Rate Limiting

Snipe-IT throttles each API key (120 requests a minute by default) and answers
a request over it with a 429. The worker keeps one limiter per API key on each
Snipe-IT instance for the whole process (`rate_limiter_for`), so for each user
the stream consumer, the check-in sweep and the batch jobs all spend one budget,
and users sharing an instance do not spend each other's:

- The stream consumer and the check-in sweep **wait** for a slot when it is
  spent, so a burst of events slows to Snipe-IT's pace instead of failing.
- The batch jobs **raise** `SnipeItRateLimitError` instead and defer themselves
  (below).
- A 429 that still arrives is retried twice by the client, after Snipe-IT's
  `Retry-After` or 2s then 4s, never waiting more than 30s. A 429 is safe to
  resend, even for a POST, because the throttle rejects it before the controller
  runs. Timeouts and 5xx responses are not retried there, since a POST may have
  landed.

### Sync Jobs and Fan-Out

Both orchestrators (`sync_snipeit_assets`, `sync_snipeit_maintenances`) use the
shared non-blocking fan-out (see
[Integration Architecture](../../docs/architecture/integration-architecture.md#non-blocking-fan-outs-and-reconciliation)),
so their `sync_jobs` row ends `completed` or `failed`, whether it came from a
manual sync or the periodic one:

1. The orchestrator marks its row `running`. Missing settings or credentials,
   or any other error before it has fanned out, fail it.
2. It lists every batch before dispatching any, so a listing that fails
   part-way fails the row and dispatches nothing. The maintenance sync then
   reconciles deleted records (above); if that fails, nothing is dispatched.
3. It writes a `queued` child row per batch (`parent_job_id`) and moves to
   `in_progress`, or straight to `completed` when there is nothing to sync.
   If queueing a batch fails, that batch and every one after it are failed.
4. Each batch job marks its own row `completed`, or `failed` when any record
   in it failed to sync ("2 of 50 assets failed to sync"), the user is not
   configured, or the batch raised. One failed record therefore fails the
   whole sync. A rate-limited batch (asset or maintenance) is retried by arq
   (`Retry`, deferred by the `Retry-After` delay) and only fails on its final
   attempt. Each deferral is capped at the staleness window's share per
   attempt (1800s / 5 tries), because a deferred batch does not move its
   parent's `updated_at` and the reconciler would otherwise fail the parent as
   stuck before the batch runs again.
5. `reconcile_in_progress_parents` runs every five minutes, periodic sync or
   not, and finalises each `in_progress` row from its child rows.

Batch job ids include the orchestrator's own job id
(`snipeit_sync_batch:<user>:<job_id>:<n>`, from 1), because arq refuses an id
whose result it still keeps (`keep_result`, one hour). The id is also the
child's `sync_jobs` row id.

### ARQ Worker Settings

The ARQ `WorkerSettings` (in [`worker.py`](worker.py)) is built from the shared
toolkit in `core_shared` (ITER14-002): operational defaults, the
`build_worker_lifecycle` startup/shutdown factory, and `redis_settings_from_url`.
It declares only its functions list, its consumer wiring, its cron schedule (see
[Periodic Sync Configuration](#periodic-sync-configuration)), and documented
overrides:

```python
class WorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    functions = [
        sync_snipeit_assets,
        sync_snipeit_asset_batch,
        sync_snipeit_maintenances,
        sync_snipeit_maintenance_batch,
        periodic_checkin_all_snipeit_accounts,
        periodic_sync_all_snipeit_accounts,
        reconcile_in_progress_parents,
    ]
    # The first two are empty unless ENABLE_PERIODIC_SYNC=true
    cron_jobs = [
        *generate_cron_jobs(periodic_sync_all_snipeit_accounts, ...),
        *generate_cron_jobs(periodic_checkin_all_snipeit_accounts, ...),
        *generate_reconciliation_cron(reconcile_in_progress_parents),
    ]
    # Both from build_worker_lifecycle(
    #     close_session_factory=False, log_consumer_errors=True
    # )
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    redis_settings = redis_settings_from_url(settings.redis_url)
    queue_name = SNIPEIT_ARQ_QUEUE_NAME

    # Documented override (everything else inherits the shared defaults):
    health_check_interval = 30  # see note below
```

`job_timeout`, `keep_result`, and the retry backoff match the
`SharedARQWorkerSettings` baseline — which equals arq's own constructor defaults,
so they apply unchanged. Note: arq's `get_kwargs` reads only the leaf class's
attributes, so an *inherited* default is invisible to arq and falls back to arq's
own. This matters for `health_check_interval`: the shared baseline is `30` but
arq's default is `3600`, so this worker redeclares `30` on the leaf to preserve
its pre-migration 30s health-check ping. The duplicated `_parse_redis_url` and
the per-worker `startup`/`shutdown` were removed.

## Testing

```bash
# Unit tests
uv run pytest -c ../../pytest.ini --rootdir . tests/unit/ -v

# Integration tests (requires Redis and PostgreSQL)
uv run pytest -c ../../pytest.ini --rootdir . tests/integration/ -v

# Linting and type checking
uv run ruff check .
uv run ruff format --check .
uv run mypy --config-file ../../mypy.ini .
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

## License

`AGPL-3.0-or-later`, see the repository [`LICENSE`](../../LICENSE).
