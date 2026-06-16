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
    ]
    on_startup = _on_startup        # build_worker_lifecycle(close_session_factory=False,
    on_shutdown = _on_shutdown      #                        log_consumer_errors=True)
    redis_settings = redis_settings_from_url(settings.redis_url)
    queue_name = IMMICH_ARQ_QUEUE_NAME

    # Documented override (everything else inherits the shared defaults):
    health_check_interval = 30      # see note below

    cron_jobs = generate_cron_jobs(
        periodic_sync_all_immich_accounts,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )
```

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
uv run pytest tests/unit/ -v

# Integration tests (requires Redis and PostgreSQL)
uv run pytest tests/integration/ -v

# Linting and type checking
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```

## License

AGPL-3.0
