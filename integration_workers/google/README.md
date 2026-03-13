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

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *required* | PostgreSQL connection string |
| `REDIS_URL` | *required* | Redis connection string for ARQ |
| `GOOGLE_CLIENT_ID` | *required* | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | *required* | Google OAuth client secret |
| `ENCRYPTION_KEY` | *required* | Key for encrypting OAuth tokens |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `WORKER_ID` | `google-worker` | Unique worker identifier |
| `MAX_CONCURRENT_JOBS` | `5` | Maximum concurrent ARQ jobs |
| `ENABLE_PERIODIC_SYNC` | `false` | Enable automatic periodic syncing |
| `SYNC_INTERVAL_HOURS` | `6` | Hours between periodic syncs |

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

The worker provides three ARQ tasks:

### 1. `sync_google_contacts`

Syncs contacts from Google to local database.

**Parameters**:
- `google_account_email` (str): Google account email
- `user_id` (int): User ID in local database
- `sync_type` (str): Sync strategy (`full`, `incremental`, or `smart`)

**Example**:
```python
await redis.enqueue_job(
    "sync_google_contacts",
    "user@example.com",
    123,
    "smart"
)
```

### 2. `push_local_contacts_to_google`

Pushes locally created/updated contacts to Google.

**Parameters**:
- `google_account_email` (str): Google account email
- `user_id` (int): User ID in local database

### 3. `periodic_sync_all_accounts`

Internal task called by ARQ cron jobs. Queries all active Google integrations and enqueues sync tasks.

**Note**: This task is automatically triggered by cron when `ENABLE_PERIODIC_SYNC=true`. Do not call manually.

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
# Run unit tests
pytest tests/unit/ -v

# Run integration tests (requires Redis and PostgreSQL)
pytest tests/integration/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Linting
ruff check .
ruff format .

# Type checking
mypy .
```

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

