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
