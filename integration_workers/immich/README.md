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
