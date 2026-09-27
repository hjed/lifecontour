# Immich Integration Worker

ARQ-based worker for syncing Immich people/albums with the Personal Management
System (two-way contact sync, album-as-journal import, and outbound contact
edits).

## Architecture

The worker uses ARQ (Async Redis Queue) for task processing and supports manual
sync (triggered via the main application), periodic sync (ARQ cron jobs), and a
domain-events stream consumer for outbound contact/journal changes.

Per-user Immich credentials (API key + server URL) are stored **encrypted in the
database** (`user_immich_auth`), not in environment variables; the worker
decrypts them at runtime using `ENCRYPTION_KEY`.

### Stream Consumer

`ImmichWorkerStreamConsumer` (in [`stream_consumer_tasks.py`](stream_consumer_tasks.py))
consumes domain events from the `pms:domain-events` Redis stream using the
`immich-worker` consumer group. It declares a **declarative route table** (a list
of `core_shared.EventRoute`) instead of overriding `_handle_event`; the shared
`StreamConsumer` runs the `XREADGROUP`/ack/retry loop, dispatches each matched
event to its handler, and immediately acks unmatched events. The route table is
the single source of truth for the worker's consumed-event set:

| Event type | Handler | Payload handling |
|---|---|---|
| `ContactCreated`, `ContactUpdated`, `ContactBirthdayChanged` | `process_contact_event` | injects `contact_id` from the event's `aggregate_id` |
| `ContactMerged` | `process_contact_event` | forwards the raw payload unchanged (survivor/source pair via `external_collisions`) |

A handler that raises leaves its event unacknowledged so the base class retries
it via the pending-entries path. See
[Stream-Consumer Route Registration](../../docs/architecture/integration-architecture.md)
for the shared convention.

## Configuration

Settings live in [`immich_settings.py`](immich_settings.py) as
`ImmichWorkerSettings`, which subclasses the shared
`core_shared.BaseWorkerSettings`. The common worker surface — database/Redis
connection, ARQ queue/stream identity, logging, periodic-sync cadence and the
OpenTelemetry block — is declared once in the base and inherited here; only the
Immich-specific fields below are declared locally. Secrets (`DATABASE_URL`,
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

**Immich-specific (declared in `ImmichWorkerSettings`)**:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENCRYPTION_KEY` | `""` | Fernet key for decrypting stored Immich API keys (`SecretStr`) |
| `WORKER_ID` | `immich-worker` | Unique worker identifier (overrides base default) |
| `QUEUE_NAME` | `arq:immich` | ARQ queue name (overrides base default) |
| `OTEL_SERVICE_NAME` | `immich-worker` | OpenTelemetry service name (overrides base default) |

### Periodic Sync Configuration

Periodic sync is **disabled by default**. Enable it by setting
`ENABLE_PERIODIC_SYNC=true` and an `SYNC_INTERVAL_HOURS` cadence (both inherited
from `BaseWorkerSettings`).

### ARQ Worker Settings

The ARQ `WorkerSettings` (in [`worker.py`](worker.py)) is built from the shared
toolkit in `core_shared` (ITER14-002): operational defaults, the
`build_worker_lifecycle` startup/shutdown factory, the `generate_cron_jobs`
helper, and `redis_settings_from_url`. It declares only its functions list, its
consumer wiring, and documented overrides:

```python
class WorkerSettings(SharedARQWorkerSettings, WorkerSettingsBase):
    functions = [
        sync_immich_people,
        sync_immich_people_batch,
        sync_immich_albums,
        sync_immich_album_batch,
        periodic_sync_all_immich_accounts,
        process_contact_event,
        reconcile_in_progress_parents,  # shared fan-out reconciler (ITER14-003)
    ]
    # Both from build_worker_lifecycle(
    #     close_session_factory=False, log_consumer_errors=True
    # )
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    redis_settings = redis_settings_from_url(settings.redis_url)
    queue_name = IMMICH_ARQ_QUEUE_NAME

    # Documented override (everything else inherits the shared defaults):
    health_check_interval = 30  # see note below

    cron_jobs = [
        *generate_cron_jobs(
            periodic_sync_all_immich_accounts,
            enable_periodic_sync=settings.enable_periodic_sync,
            sync_interval_hours=settings.sync_interval_hours,
        ),
        # Always on: finalises non-blocking IN_PROGRESS fan-out parents.
        *generate_reconciliation_cron(reconcile_in_progress_parents),
    ]
```

## Non-Blocking Sync Flow & Status Semantics

The album and people syncs are **non-blocking fan-outs** (ITER14-003). An
orchestrator no longer holds a worker slot waiting on its children:

1. `sync_immich_albums` / `sync_immich_people` list their batches, persist one
   linked child `sync_jobs` row per batch (`parent_job_id` → orchestrator), set
   the parent's `expected_children`, mark the parent **`IN_PROGRESS`** and
   **return immediately** (no `asyncio.gather`). Child rows are committed *before*
   the children are dispatched, so each child's row already exists when it runs.
   A fan-out with zero batches is marked `COMPLETED` directly.
2. Each child batch (`sync_immich_album_batch` / `sync_immich_people_batch`) does
   its work, then on success marks its own row `COMPLETED` and atomically
   increments the parent's `completed_children`. On a **final**-attempt failure it
   marks its row `FAILED` and increments `failed_children`; a transient
   (non-final) failure just re-raises so ARQ retries without touching counters.
3. The shared **reconciliation cron** (`reconcile_in_progress_parents`, run every
   5 minutes) scans `IN_PROGRESS` parents and finalises each against its **child
   rows** (the authoritative source — counters are only a fast path): all children
   succeeded → `COMPLETED`; any failed/cancelled → `FAILED` with a summary; a
   parent whose children stop progressing within
   `reconciliation_stale_after_seconds` (default 30 min) is treated as stuck and
   marked `FAILED`.

`IN_PROGRESS` therefore means "fan-out dispatched, awaiting children", distinct
from `RUNNING` ("actively executing on a worker"). The reconciler being
authoritative over child rows means a missed counter increment can never strand a
parent. See `docs/architecture/integration-architecture.md` for the generic
lifecycle and `core_shared/core_shared/sync_reconciliation.py` for the reconciler.
The worker-agnostic fan-out steps (`persist_fanout_children`,
`record_child_terminal`, `is_final_attempt`) are shared in
`core_shared/core_shared/fanout.py`.

`job_timeout`, `keep_result`, and the retry backoff match the
`SharedARQWorkerSettings` baseline — which equals arq's own constructor defaults,
so they apply unchanged. Note: arq's `get_kwargs` reads only the leaf class's
attributes, so an *inherited* default is invisible to arq and falls back to arq's
own. This matters for `health_check_interval`: the shared baseline is `30` but
arq's default is `3600`, so this worker redeclares `30` on the leaf to preserve
its pre-migration 30s health-check ping. The duplicated `_parse_redis_url`, the
`_generate_cron_jobs` helper, and the per-worker `startup`/`shutdown` were
removed.

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
