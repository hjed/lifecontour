# Strava Integration Worker

ARQ-based worker that processes Strava webhook events and activity sync tasks for
Lifecontour, and launches a Redis Streams consumer for domain
event fan-out.

## Configuration

Settings live in [`strava_settings.py`](strava_settings.py) as `StravaSettings`,
which subclasses the shared `core_shared.BaseWorkerSettings`. The common worker
surface — database/Redis connection, ARQ queue/stream identity, logging,
periodic-sync cadence and the OpenTelemetry block — is declared once in the base
and inherited here; only the Strava-specific fields below are declared locally.
Secrets (`DATABASE_URL`, `STRAVA_CLIENT_SECRET`, `ENCRYPTION_KEY`) are
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

**Strava-specific (declared in `StravaSettings`)**:

| Variable | Default | Description |
|----------|---------|-------------|
| `STRAVA_CLIENT_ID` | *required* | Strava API client ID |
| `STRAVA_CLIENT_SECRET` | *required* | Strava API client secret (`SecretStr`) |
| `ENCRYPTION_KEY` | *required* | Key for encrypting OAuth tokens (`SecretStr`) |
| `WORKER_ID` | `strava-worker` | Unique worker identifier (overrides base default) |

See [`.env.example`](.env.example) for a copy-paste starting point.

### ARQ Worker Settings

The ARQ `StravaWorkerSettings` (in [`worker.py`](worker.py)) is built from the
shared toolkit in `core_shared` (ITER14-002): operational defaults, the
`build_worker_lifecycle` startup/shutdown factory, the `generate_cron_jobs`
helper, and `redis_settings_from_url`. It declares only its functions list, its
consumer wiring, and documented overrides:

```python
class StravaWorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    functions = [
        process_strava_webhook_event,
        sync_strava_activities,
        sync_strava_activity_batch,
        periodic_sync_all_strava_accounts,
        reconcile_in_progress_parents,  # shared fan-out reconciler (ITER14-003)
        func(backfill_strava_elapsed_durations, timeout=3600),  # one-off
    ]
    # build_worker_lifecycle(log_consumer_errors=True), then enqueue the
    # duration backfill (see below)
    on_startup = _on_startup_with_backfill
    on_shutdown = _on_shutdown
    redis_settings = redis_settings_from_url(settings.redis_url)
    queue_name = STRAVA_ARQ_QUEUE_NAME

    # Documented overrides (everything else inherits the shared defaults):
    max_tries = 20  # many retries to span Strava's daily-limit reset
    max_jobs = 5  # cap concurrency below arq's default of 10

    cron_jobs = [
        *generate_cron_jobs(
            periodic_sync_all_strava_accounts,
            enable_periodic_sync=settings.enable_periodic_sync,
            sync_interval_hours=settings.sync_interval_hours,
        ),
        # Always on: finalises non-blocking IN_PROGRESS fan-out parents.
        *generate_reconciliation_cron(reconcile_in_progress_parents),
    ]
```

`job_timeout`, `keep_result`, and the retry backoff match the
`SharedARQWorkerSettings` baseline — which equals arq's own constructor defaults,
so they apply unchanged. Note: arq's `get_kwargs` reads only the leaf class's
attributes, so an *inherited* default is invisible to arq and falls back to arq's
own. This matters for `health_check_interval`: the shared baseline is `30`, but
arq's default is `3600`, so this worker (which does not redeclare it) runs at
`3600` — the shared `30` applies only to workers that declare it on the leaf. The
per-worker `startup`/`shutdown`, the `_on_consumer_task_done` callback, and the
inline cron block were removed.

## Non-Blocking Sync Flow & Status Semantics

Activity import is a **non-blocking fan-out** (ITER14-003). The orchestrator no
longer holds a worker slot waiting on its children:

1. `sync_strava_activities` first owns its parent `sync_jobs` row (its own
   `job_id` — a backend-triggered sync commits this row before queueing the job;
   the periodic sync does not, so Strava creates it idempotently when missing) and commits it as `running` **before draining**, so the dashboard
   shows an in-flight sync even if the drain defers on a rate limit. It then
   drains the activity-page generator, persists one linked child row per page
   (`parent_job_id` → orchestrator), sets the parent's `expected_children` to the
   authoritative persisted-child count, marks the parent **`IN_PROGRESS`** and
   **returns immediately**. Child rows are committed *before* the children are
   dispatched, so each child's row already exists when it runs. A fan-out with
   zero pages is marked `COMPLETED` directly. The persist step is idempotent
   across ARQ retries (deterministic child ids, skip-if-exists), so a re-run never
   raises a duplicate-key error.
2. Each `sync_strava_activity_batch` processes its page (each activity in its own
   transaction via the outbox), then on success marks its own row `COMPLETED` and
   atomically increments the parent's `completed_children`. On a **final**-attempt
   failure it marks its row `FAILED` and increments `failed_children`; a transient
   failure — including a rate-limit `Retry` deferral — just propagates so ARQ
   retries without touching counters.
3. The shared **reconciliation cron** (`reconcile_in_progress_parents`, run every
   5 minutes) scans `IN_PROGRESS` parents and finalises each against its **child
   rows** (the authoritative source — counters are only a fast path): all children
   succeeded → `COMPLETED`; any failed/cancelled → `FAILED` with a summary; a
   parent whose children stop progressing within
   `reconciliation_stale_after_seconds` is treated as stuck and marked `FAILED`.
   Strava **widens this window to 6 hours** (the shared default is 30 min)
   because a rate-limited batch can be deferred by up to ~1 hour per attempt — a
   30-minute window would fail a parent whose children are still legitimately
   retrying. It stays env-overridable via `RECONCILIATION_STALE_AFTER_SECONDS`,
   and activity data is imported idempotently via the outbox regardless of the
   parent's final status.

`IN_PROGRESS` therefore means "fan-out dispatched, awaiting children", distinct
from `RUNNING` ("actively executing on a worker"); the integrations dashboard
renders it as an active (non-terminal) state. The reconciler being authoritative
over child rows means a missed counter increment can never strand a parent. See
`docs/architecture/integration-architecture.md` for the generic lifecycle and
`core_shared/core_shared/sync_reconciliation.py` for the reconciler. The
worker-agnostic fan-out steps (`persist_fanout_children`, `record_child_terminal`,
`is_final_attempt`) are shared in `core_shared/core_shared/fanout.py`; only the
Strava-specific parent-row ownership and per-batch session wrappers live here.

A batch that raises records its child row `FAILED` (with the error) on that same
attempt — including missing auth or a sync service that cannot be built — since
arq retries a job only on `Retry` or cancellation. Only a rate limit raises
`Retry`, and only until the final attempt (`STRAVA_MAX_TRIES`, which the batch
passes to `is_final_attempt` because arq does not put `max_tries` in the job
context); on that attempt it records the failure instead, because arq drops a
`Retry` raised then without running the job again.

## Activity Duration

An activity's fitness `duration` is Strava's `elapsed_time` in seconds — how long
the activity took, stops included, the same span as the journal's event date
range. It used to be `moving_time`.

### One-off elapsed-time backfill

Durations synced before that change are corrected by
`backfill_strava_elapsed_durations` (in [`duration_backfill.py`](duration_backfill.py)).
Worker startup enqueues it for every user in `user_strava_auth` whose Redis
marker `strava:backfill:elapsed_duration:v1:{user_id}` is unset; the job sets
the marker when it succeeds.

The job lists all of the athlete's activities (200 per page), waiting out the
15-minute rate limit in place. A daily limit defers the whole job; nothing is
written until every page is listed. It then emits
`journal_event.fitness_duration_corrected` outbox events, each carrying the
duration the sync wrote (`expected_durations`) and the one to store instead
(`corrected_duration`):

- a journal's total moving time across its linked activities → their total
  elapsed time (a journal holds several after an additive merge);
- for a merged journal, also each activity's moving time → its elapsed time,
  as a webhook update of one merged activity re-saved that activity alone.

The backend applies each as a compare-and-set, so a duration the user has
edited (it matches no expected value) is left alone. A journal with an activity
no longer on Strava, or merged with a manual or non-Strava journal, matches
nothing and is left as it is.

To run it again, delete the user's marker key and restart the worker (startup
clears arq's retained result for the job so it can be enqueued again). An
already-corrected duration matches no expected value, so a rerun changes
nothing.

## Stream Consumer

`StravaWorkerStreamConsumer` (in [`stream_consumer_tasks.py`](stream_consumer_tasks.py))
consumes domain events from the `pms:domain-events` Redis stream using the
`strava-worker` consumer group. It declares a **declarative route table** (a list
of `core_shared.EventRoute`) instead of overriding `_handle_event`; the shared
`StreamConsumer` runs the `XREADGROUP`/ack/retry loop, dispatches each matched
event to its handler, and immediately acks unmatched events. The route table is
the single source of truth for the worker's consumed-event set:

| Event-type pattern | Handler |
|---|---|
| `strava.` (prefix — all `strava.*` events) | `_handle_strava_event` |

The `strava.` route is a **prefix match**, so every `strava.*` domain event is
dispatched to `_handle_strava_event` (currently a placeholder that logs; activity
processing lands in a later iteration). A handler that raises leaves its event
unacknowledged so the base class retries it via the pending-entries path. See
[Stream-Consumer Route Registration](../../docs/architecture/integration-architecture.md)
for the shared convention.

## Running the Worker

```bash
# Start with Docker Compose
docker compose --profile dev up strava-worker

# View logs
docker compose logs -f strava-worker
```

## Testing

```bash
# Run unit tests
uv run pytest -c ../../pytest.ini --rootdir . tests/unit/ -v

# Run integration tests (requires Redis and PostgreSQL)
uv run pytest -c ../../pytest.ini --rootdir . tests/integration/ -v

# Linting / formatting
uv run ruff check .
uv run ruff format --check .

# Type checking
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
