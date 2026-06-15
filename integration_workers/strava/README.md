# Strava Integration Worker

ARQ-based worker that processes Strava webhook events and activity sync tasks for
the Personal Management System, and launches a Redis Streams consumer for domain
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
    ]
    on_startup = _on_startup        # build_worker_lifecycle(log_consumer_errors=True)
    on_shutdown = _on_shutdown
    redis_settings = redis_settings_from_url(settings.redis_url)
    queue_name = STRAVA_ARQ_QUEUE_NAME

    # Documented overrides (everything else inherits the shared defaults):
    max_tries = 20                  # many retries to span Strava's daily-limit reset
    max_jobs = 5                    # cap concurrency below arq's default of 10

    cron_jobs = generate_cron_jobs(
        periodic_sync_all_strava_accounts,
        enable_periodic_sync=settings.enable_periodic_sync,
        sync_interval_hours=settings.sync_interval_hours,
    )
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
uv run pytest tests/unit/ -v

# Run integration tests (requires Redis and PostgreSQL)
uv run pytest tests/integration/ -v

# Linting / formatting
uv run ruff check .
uv run ruff format --check .

# Type checking
uv run mypy .
```
