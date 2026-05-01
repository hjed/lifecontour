# Integration Architecture - Personal Management System

This document defines the architecture for external service integrations including Google Contacts, Immich, Strava, Firefly III, and communication platforms.


## Overview

The integration architecture uses an **Isolated Worker Architecture** pattern that provides dependency isolation while maintaining operational simplicity for self-hosted deployment.

### Core Principles

- **Dependency Isolation**: Each integration has isolated dependencies to prevent conflicts
- **Process Isolation**: Background workers can crash/restart independently
- **Domain Separation**: Integrations are cleanly separated from core business logic
- **Operational Simplicity**: Minimal additional infrastructure (just Redis)
- **AI-Friendly**: Each integration is self-contained and focused

## Architecture Pattern

### Integration Domain Structure

```
app/core/integrations/
├── shared/
│   ├── __init__.py
│   ├── base_models.py      # Common sync patterns (SyncMetadata, ExternalReference)
│   ├── base_service.py     # Common integration logic
│   ├── task_queue.py       # ARQ setup and configuration
│   └── exceptions.py       # Integration-specific exceptions
├── google/
│   ├── __init__.py
│   ├── models.py           # Google-specific sync metadata
│   ├── service.py          # Business logic for Google Contacts sync
│   ├── api_client.py       # Google API wrapper
│   ├── tasks.py            # ARQ task definitions
│   └── README.md           # Integration-specific documentation
├── immich/
│   ├── __init__.py
│   ├── models.py           # Immich-specific models
│   ├── service.py          # Photo and album sync logic
│   ├── api_client.py       # Immich API wrapper
│   ├── tasks.py            # Background sync tasks
│   └── README.md
├── strava/
│   ├── __init__.py
│   ├── models.py           # Activity sync metadata
│   ├── service.py          # Activity to journal entry logic
│   ├── api_client.py       # Strava API wrapper
│   ├── tasks.py            # Activity sync tasks
│   └── README.md
└── firefly_iii/
    ├── __init__.py
    ├── models.py           # Transaction sync metadata
    ├── service.py          # Transaction linking logic
    ├── api_client.py       # Firefly III API wrapper
    ├── tasks.py            # Transaction sync tasks
    └── README.md
```

### Worker Process Structure

```
integration_workers/
├── google/
│   ├── requirements.txt    # Google-specific dependencies
│   ├── worker.py          # ARQ worker process
│   └── Dockerfile         # Optional: for container isolation
├── immich/
│   ├── requirements.txt   # Immich-specific dependencies
│   └── worker.py
├── strava/
│   ├── requirements.txt   # Strava-specific dependencies
│   └── worker.py
└── firefly_iii/
    ├── requirements.txt   # Firefly III-specific dependencies
    └── worker.py
```

## Shared Code Strategy

### Core Shared Package

**Critical Implementation Detail**: All workers and the main application share code through a dedicated `core_shared` Python package.

#### Package Structure
```
core_shared/
├── pyproject.toml          # Minimal dependencies (SQLAlchemy, Pydantic)
├── core_shared/
│   ├── __init__.py
│   ├── models/             # SQLAlchemy models
│   │   ├── __init__.py
│   │   ├── contact.py      # Contact, ContactMethod, etc.
│   │   ├── sync_metadata.py # SyncMetadata, ExternalReference
│   │   └── base.py         # Base model classes
│   ├── database/           # Database session management
│   │   ├── __init__.py
│   │   ├── engine.py       # Engine and session factory
│   │   └── connection.py   # Connection pooling patterns
│   └── exceptions/         # Shared exception classes
│       ├── __init__.py
│       └── integration.py  # Integration-specific exceptions
```

#### Installation Pattern
- **Main App**: `pip install -e ../core_shared` in `pyproject.toml`
- **Workers**: `pip install -e ../core_shared` in `requirements.txt`
- **Docker**: Copy and install shared package in all containers

#### Benefits
- **Explicit Boundaries**: Only intentionally shared code is accessible
- **Dependency Safety**: Shared package declares its own minimal dependencies
- **Version Control**: Changes to shared models are explicit and testable
- **Import Safety**: Prevents accidental imports of core services

### Database Connection Management

#### Session-Per-Task Pattern
**Critical for Worker Efficiency**: Each worker uses connection pooling with session-per-task.

```python
# In core_shared/database/engine.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def create_session_factory(database_url: str):
    engine = create_engine(database_url, pool_size=5, max_overflow=10)
    return sessionmaker(bind=engine)

# In worker.py
from core_shared.database import create_session_factory

session_factory = create_session_factory(DATABASE_URL)

async def sync_task(external_id: str):
    with session_factory() as session:
        # All database operations use this session
        # Session automatically returned to pool on exit
        pass
```

## Core Components

### 1. Shared Models (core_shared package)

The `core_shared` package contains SQLAlchemy models and utilities used across the main application and integration workers.

#### SyncMetadata
Tracks synchronization state between external systems and internal entities:

```python
from core_shared import SyncMetadata, SyncStatus

class SyncMetadata(Base):
    internal_id: int               # FK to internal entity
    integration_source: str        # 'google', 'immich', etc.
    external_id: str              # External system's ID
    last_synced_at: datetime
    version_hash: str             # SHA-256 hash for change detection
    sync_status: str              # SUCCESS, FAILED, IN_PROGRESS, PENDING
    error_message: Optional[str]  # Last error if failed
    retry_count: int              # Number of retry attempts
```

#### ExternalReference
Tracks references between internal entities and external system entities:

```python
from core_shared import ExternalReference

class ExternalReference(Base):
    internal_entity_type: str     # 'contact', 'journal_entry', etc.
    internal_entity_id: int       # ID of internal entity
    external_system: str          # 'google', 'immich', etc.
    external_entity_type: str     # 'person', 'photo', 'album', etc.
    external_entity_id: str       # External system's ID
    reference_data: Optional[str] # Additional metadata as JSON
```

#### ExternalReference
Links internal entities to external resources:

```python
class ExternalReference(BaseModel):
    entity_id: UUID               # Internal entity ID
    entity_type: str             # 'contact', 'photo', 'journal_entry'
    integration_source: str      # Source system
    external_id: str            # External resource ID
    external_url: Optional[str] # Direct link to external resource
    metadata: dict              # Integration-specific metadata
```

### 2. Task Queue System

**Technology**: ARQ (asyncio-based, Redis-backed)
**Infrastructure**: Single Redis container

#### Task Types
- **Sync Tasks**: Periodic synchronization with external services
- **Webhook Tasks**: Process incoming webhooks from external services
- **Cleanup Tasks**: Maintenance and cleanup operations

#### Task Scheduling

Integration workers support three types of task scheduling:

##### 1. Periodic Scheduling (Automated Syncs)
Uses ARQ's `cron_jobs` feature for automatic, scheduled synchronization:

```python
from arq.cron import cron

class GoogleWorkerSettings:
    functions = [sync_google_contacts, push_local_contacts_to_google]

    # Periodic sync configuration
    cron_jobs = [
        # Sync every 6 hours at :00 minutes
        cron(sync_google_contacts, hour={0, 6, 12, 18}, minute=0),

        # Alternative: Daily sync at 2 AM
        # cron(sync_google_contacts, hour=2, minute=0),

        # Alternative: Hourly sync
        # cron(sync_google_contacts, minute=0),
    ]

    # ... other settings ...
```

**Configuration Options:**
- `minute`: 0-59 or set of minutes (e.g., `{0, 15, 30, 45}`)
- `hour`: 0-23 or set of hours (e.g., `{0, 6, 12, 18}`)
- `day`: 1-31 or set of days
- `month`: 1-12 or set of months
- `weekday`: 0-6 (Monday=0) or set of weekdays

**Environment-Based Configuration:**
```python
# In worker settings
import os

class WorkerSettings(BaseSettings):
    sync_interval_hours: int = Field(
        default=6,
        description="Hours between automatic syncs"
    )

class GoogleWorkerSettings:
    # Generate cron schedule from environment variable
    cron_jobs = [
        cron(
            sync_google_contacts,
            hour=set(range(0, 24, settings.sync_interval_hours)),
            minute=0
        )
    ] if os.getenv('ENABLE_PERIODIC_SYNC', 'false').lower() == 'true' else []
```

##### 2. Event-Driven Scheduling
Triggered by domain events from the main application:

```python
# In main application - triggered by user actions
async def on_contact_updated(contact_id: UUID):
    """Push local contact changes to Google."""
    await task_queue.enqueue_job(
        'push_local_contacts_to_google',
        contact_id=contact_id
    )
```

##### 3. Manual Scheduling
User-initiated sync operations via API endpoints:

```python
# In API controller
@router.post("/integrations/google/contacts/sync")
async def trigger_sync(
    user: SessionUser,
    task_queue_service: TaskQueueService
):
    """Manually trigger Google Contacts sync."""
    job_id = await task_queue_service.enqueue_google_sync(
        google_account_email=user.email,
        user_id=user.id,
        sync_type="smart"
    )
    # JSON:API response (camelCase attributes)
    return {
        "data": {
            "id": job_id,
            "type": "sync-job",
            "attributes": {"status": "queued", "syncType": "smart"},
        }
    }
```

### 3. Integration Services

Each integration implements a common interface:

```python
class BaseIntegrationService(Protocol):
    async def authenticate(self) -> bool
    async def sync_data(self, user_id: UUID) -> SyncResult
    async def handle_webhook(self, payload: dict) -> None
    async def get_sync_status(self, user_id: UUID) -> SyncStatus
```

## Worker Design Patterns

### Mandatory Idempotency

**Critical Requirement**: Every worker task MUST be idempotent to handle retries safely.

#### Idempotency Pattern
```python
async def sync_external_entity(external_id: str, integration_source: str):
    with session_factory() as session:
        # 1. Check if work is already done
        existing = session.query(SyncMetadata).filter_by(
            integration_source=integration_source,
            external_id=external_id
        ).first()

        # 2. Calculate current version hash
        current_hash = calculate_version_hash(external_data)

        # 3. Skip if already synced with same version
        if existing and existing.version_hash == current_hash:
            logger.info(f"Skipping {external_id}, already synced")
            return

        # 4. Perform sync work
        # ... sync logic here ...

        # 5. Update sync metadata
        if existing:
            existing.version_hash = current_hash
            existing.last_synced_at = datetime.utcnow()
        else:
            session.add(SyncMetadata(...))
        session.commit()
```

### Dead Letter Queue (DLQ) Strategy

**Critical for Operational Safety**: Handle persistent task failures without blocking the queue.

#### ARQ Configuration
```python
# In worker.py
from arq import create_pool
from arq.connections import RedisSettings

async def startup(ctx):
    ctx['redis'] = await create_pool(RedisSettings())

async def shutdown(ctx):
    await ctx['redis'].close()

class WorkerSettings:
    functions = [sync_task]
    on_startup = startup
    on_shutdown = shutdown

    # DLQ Configuration
    max_tries = 5                    # Retry failed tasks 5 times
    retry_delay = 60                 # Wait 60 seconds between retries
    keep_result = 3600               # Keep results for 1 hour

    # Failed tasks go to DLQ after max_tries
    job_timeout = 300                # 5 minute timeout per task
```

#### DLQ Monitoring
- Failed tasks after max_tries are moved to `arq:dlq` queue
- Monitor DLQ depth for operational alerts
- Manual inspection and reprocessing of poison pill tasks
- Prevents single bad task from blocking entire integration

## Integration Patterns

### 1. Two-Way Sync (Google Contacts)

**Challenge**: Conflict resolution and data consistency
**Solution**: Last-write-wins with version hashing

**Process**:
1. Fetch all contacts from Google
2. Compare version hashes with stored metadata
3. Determine which side has newer data
4. Update the stale side and record new hash
5. Handle conflicts with user-defined rules

### 2. External Data References (Immich)

**Challenge**: Large binary data should stay external
**Solution**: Store references, not copies

**Process**:
1. Poll Immich for new photos/albums
2. Create Photo entities with external references
3. Link faces to contacts via person matching
4. Store thumbnails and metadata locally

### 3. One-Way Import (Strava, Firefly III)

**Challenge**: Transform external data to internal entities
**Solution**: ETL pattern with deduplication

**Process**:
1. Fetch new data from external service
2. Transform to internal domain entities
3. Check for duplicates using external references
4. Create/update internal entities
5. Record sync metadata

**Journal Integration Example**: Strava activities are imported as journal entries with FITNESS + OUTDOOR_ACTIVITY types. See [Journal System Specification](../journal-system-specification.md) for merge behavior and conflict resolution patterns.

### 4. Bi-Directional Sync (Google Calendar)

**Challenge**: Keep two systems in sync with conflict resolution
**Solution**: Last-write-wins with change tracking

**Process**:
1. Poll external service for changes
2. Compare with local change tracking
3. Determine which side has newer data
4. Update stale side
5. Record sync metadata

**Journal Integration Example**: Calendar events sync bi-directionally with journal EVENT type entries. See [Journal System Specification](../journal-system-specification.md) for sync behavior and attendee handling.

## Deployment Architecture

### Development Environment
- **Mandatory**: Docker Compose with full worker isolation
- **Rationale**: Maintains dependency isolation and dev/prod parity
- **Components**: FastAPI web server, Redis, PostgreSQL, worker containers
- **Shared Code**: `core_shared` package mounted in all containers

### Production (Self-Hosted)
- FastAPI web server (core app only)
- Separate worker processes per integration
- Redis for task queue
- PostgreSQL for data storage
- Docker Compose orchestration

### Docker Compose Structure

```yaml
version: '3.8'
services:
  app:
    build: .
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/personal_management
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./core_shared:/app/core_shared:ro
    depends_on: [db, redis]

  google-worker:
    build: ./integration_workers/google
    env_file: ./integration_workers/google/.env
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/personal_management
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./core_shared:/app/core_shared:ro
    depends_on: [db, redis]
    restart: unless-stopped

  immich-worker:
    build: ./integration_workers/immich
    env_file: ./integration_workers/immich/.env
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/personal_management
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./core_shared:/app/core_shared:ro
    depends_on: [db, redis]
    restart: unless-stopped

  strava-worker:
    build: ./integration_workers/strava
    env_file: ./integration_workers/strava/.env
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/personal_management
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./core_shared:/app/core_shared:ro
    depends_on: [db, redis]
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

  db:
    image: postgres:18-alpine
    environment:
      - POSTGRES_DB=personal_management
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  redis_data:
  postgres_data:
```

## Configuration and Secrets Management

### Worker Configuration Pattern

**Critical for Security**: Each worker has isolated configuration and secrets.

#### Docker Compose Configuration
```yaml
version: '3.8'
services:
  app:
    build: .
    environment:
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://redis:6379
    depends_on: [db, redis]

  google-worker:
    build: ./integration_workers/google
    env_file: ./integration_workers/google/.env
    environment:
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://redis:6379
    depends_on: [db, redis]

  immich-worker:
    build: ./integration_workers/immich
    env_file: ./integration_workers/immich/.env
    environment:
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://redis:6379
    depends_on: [db, redis]
```

#### Worker-Specific Environment Files
```bash
# integration_workers/google/.env
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# integration_workers/immich/.env
IMMICH_BASE_URL=http://your-immich-instance
IMMICH_API_KEY=your-immich-api-key

# integration_workers/strava/.env
STRAVA_CLIENT_ID=your-strava-client-id
STRAVA_CLIENT_SECRET=your-strava-client-secret
```

#### Worker Configuration Loading
```python
# In worker.py
import os
from pydantic import BaseSettings

class GoogleWorkerSettings(BaseSettings):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    database_url: str
    redis_url: str

    class Config:
        env_file = ".env"

settings = GoogleWorkerSettings()
```

## Security Considerations

### Credential Management
- OAuth tokens stored encrypted in database
- API keys in environment variables per worker
- Automatic token refresh handling
- Credential isolation per integration
- No shared secrets between integrations

### Data Privacy
- External data references only (no copies of sensitive data)
- User consent required for each integration
- Granular permission controls
- Audit logging for all external API calls

## Production Resilience Patterns

### Mandatory Idempotency Implementation

**Critical Requirement**: Every worker operation MUST be idempotent to handle message redelivery safely.

#### Idempotency Strategy
```python
async def sync_external_entity(external_id: str, integration_source: str):
    """
    Idempotent sync operation using SyncMetadata for state tracking.
    Safe to retry - will not create duplicates or corrupt data.
    """
    with session_factory() as session:
        # 1. Begin transaction for atomic operation
        with session.begin():
            # 2. Check existing sync state
            sync_metadata = session.query(SyncMetadata).filter_by(
                integration_source=integration_source,
                external_id=external_id
            ).with_for_update().first()  # Lock for concurrent safety

            # 3. Fetch current external data
            external_data = await fetch_external_data(external_id)
            current_hash = calculate_version_hash(external_data)

            # 4. Skip if already processed with same version
            if sync_metadata and sync_metadata.version_hash == current_hash:
                logger.info(f"Skipping {external_id}, already synced",
                           extra={"external_id": external_id, "version_hash": current_hash})
                return SyncResult.ALREADY_SYNCED

            # 5. Perform sync work (create/update internal entities)
            try:
                internal_entity = await sync_to_internal_model(external_data)

                # 6. Update sync metadata atomically
                if sync_metadata:
                    sync_metadata.version_hash = current_hash
                    sync_metadata.last_synced_at = datetime.utcnow()
                    sync_metadata.sync_status = SyncStatus.SUCCESS
                    sync_metadata.error_message = None
                else:
                    session.add(SyncMetadata(
                        integration_source=integration_source,
                        external_id=external_id,
                        internal_id=internal_entity.id,
                        version_hash=current_hash,
                        last_synced_at=datetime.utcnow(),
                        sync_status=SyncStatus.SUCCESS
                    ))

                return SyncResult.SUCCESS

            except Exception as e:
                # 7. Record failure in sync metadata
                if sync_metadata:
                    sync_metadata.sync_status = SyncStatus.FAILED
                    sync_metadata.error_message = str(e)
                else:
                    session.add(SyncMetadata(
                        integration_source=integration_source,
                        external_id=external_id,
                        sync_status=SyncStatus.FAILED,
                        error_message=str(e),
                        last_synced_at=datetime.utcnow()
                    ))
                raise  # Re-raise for ARQ retry handling
```

### Retry and Dead Letter Queue Strategy

#### ARQ Retry Configuration
```python
# In worker.py
from arq import create_pool
from arq.connections import RedisSettings
import asyncio

class WorkerSettings:
    functions = [sync_google_contacts, sync_contact_batch]

    # Retry Strategy
    max_tries = 5                    # Total attempts (1 initial + 4 retries)
    retry_delay = 60                 # Base delay between retries (seconds)

    # Exponential backoff with jitter
    def retry_delay_func(retry_count: int) -> float:
        """
        Exponential backoff: 60s, 120s, 240s, 480s
        With jitter to prevent thundering herd
        """
        import random
        base_delay = 60 * (2 ** retry_count)
        jitter = random.uniform(0.8, 1.2)  # ±20% jitter
        return min(base_delay * jitter, 900)  # Cap at 15 minutes

    # Job lifecycle
    job_timeout = 600                # 10 minute timeout per job
    keep_result = 3600               # Keep results for 1 hour

    # Health check
    health_check_interval = 30       # Health check every 30 seconds
```

#### Dead Letter Queue Monitoring
```python
# In monitoring/dlq_monitor.py
async def monitor_dlq():
    """
    Monitor dead letter queue and alert on poison pill messages.
    Run as separate monitoring process.
    """
    redis = await create_pool(RedisSettings())

    while True:
        # Check DLQ depth
        dlq_length = await redis.llen('arq:dlq')

        if dlq_length > 10:  # Alert threshold
            await send_alert(f"DLQ has {dlq_length} failed jobs")

            # Log failed job details for analysis
            failed_jobs = await redis.lrange('arq:dlq', 0, 5)
            for job in failed_jobs:
                logger.error("DLQ job analysis needed",
                           extra={"job_data": job, "dlq_length": dlq_length})

        await asyncio.sleep(300)  # Check every 5 minutes
```

### Transactional Outbox Pattern

**Critical for Data Consistency**: Ensures atomic database updates and event publishing.

#### Implementation Pattern
```python
# In core_shared/models/outbox.py
class OutboxEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    event_type: str                  # 'contact.created', 'sync.completed'
    aggregate_id: UUID               # ID of the entity that changed
    event_data: dict                 # JSON payload
    created_at: datetime = Field(default_factory=datetime.utcnow)
    relayed_at: Optional[datetime] = None  # Set when published to Redis Stream
    retry_count: int = 0

# In integration service
async def sync_contact_with_outbox(contact_data: dict):
    """
    Sync contact and publish event atomically using outbox pattern.
    """
    with session_factory() as session:
        with session.begin():
            # 1. Update contact in database
            contact = await update_contact(session, contact_data)

            # 2. Add event to outbox in SAME transaction
            outbox_event = OutboxEvent(
                event_type='contact.synced',
                aggregate_id=contact.id,
                event_data={
                    'contact_id': str(contact.id),
                    'integration_source': 'google',
                    'sync_timestamp': datetime.utcnow().isoformat()
                }
            )
            session.add(outbox_event)

            # 3. Both operations commit together or fail together
            # No risk of database update without event or vice versa
```

#### Outbox Relay
```python
# In app/infrastructure/events/outbox_relay.py
async def run_outbox_relay_loop():
    """
    Reliable event relay that publishes outbox events to a Redis Stream.
    Runs as a FastAPI lifespan background task.
    """
    while True:
        async with engine.begin() as conn:
            # Get unrelayed events
            events = await repository.get_unrelayed_events()

            for event in events:
                try:
                    # Publish to Redis Stream (pms:domain-events)
                    await stream_client.publish(event)

                    # Mark as relayed
                    await repository.mark_as_relayed(event.event_id)

                except Exception as e:
                    logger.error("Failed to relay event",
                               event_id=event.event_id, error=str(e))

        await asyncio.sleep(10)  # Poll every 10 seconds
```

### Redis Stream Consumer Architecture

The `OutboxRelay` publishes events to a Redis Stream (`pms:domain-events`) and independent
consumers handle all event processing. Each consumer group processes independently, providing
failure isolation. Events that exceed `max_delivery_count` are routed to a `dead_letter_events`
table via the `DeadLetterConsumerMixin`.

#### Consumer Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ OutboxRelay (FastAPI lifespan task)                                │
│   - Polls outbox_events WHERE relayed_at IS NULL                  │
│   - XADD to pms:domain-events stream                             │
│   - Marks rows as relayed                                         │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ Redis Stream (pms:domain-events)
                           │
      ┌──────────┬─────────┼──────────┬────────────────────┐
      │          │         │          │                    │
      ▼          ▼         ▼          ▼                    ▼
┌──────────┐ ┌────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────┐
│ search-  │ │summary-│ │ inbound- │ │ google-      │ │ (future) │
│ indexer  │ │generat-│ │ processor│ │ worker       │ │ Phase 4  │
│ consumer │ │or      │ │ consumer │ │ consumer     │ │ cleanup  │
│ group    │ │consumer│ │ group    │ │ group        │ │          │
│          │ │group   │ │          │ │              │ │          │
│ Handles: │ │Handles:│ │ Handles: │ │ Handles:     │ │          │
│ •Contact*│ │•Contact│ │•contact.*│ │•JournalC/U/D │ │          │
│ •Journal*│ │ Summary│ │•journal_ │ │•TagUpdated   │ │          │
│ •Tag*    │ │ Refresh│ │ event.*  │ │•TagDeleted   │ │          │
│ •Import- │ │ Request│ │•journal_ │ │              │ │          │
│  antDate*│ │        │ │ review.* │ │ → ARQ broad- │ │          │
│          │ │        │ │          │ │   cast to    │ │          │
│          │ │        │ │          │ │   Google     │ │          │
│          │ │        │ │          │ │   worker     │ │          │
└──────────┘ └────────┘ └──────────┘ └──────────────┘ └──────────┘
```

#### Key Components

| Component | Module | Consumer Group | Responsibility |
|-----------|--------|----------------|----------------|
| `SearchIndexerConsumer` | `app.infrastructure.events.search_indexer_consumer` | `search-indexer` | MeiliSearch indexing + daily summary invalidation |
| `SummaryConsumer` | `app.infrastructure.events.summary_consumer` | `summary-generator` | AI contact summary generation + post-generation index update |
| `InboundEventConsumer` | `app.infrastructure.events.inbound_event_consumer` | `inbound-processor` | Contact sync, journal sync, match detection from Google |
| `GoogleWorkerStreamConsumer` | `integration_workers/google` | `google-worker` | Journal/tag event processing for Google Calendar sync |
| `StreamConsumer` (base) | `core_shared.stream_client` | — | XREADGROUP loop, event filtering, XACK |
| `stream_event_to_outbox_event` | `app.infrastructure.events.stream_event_adapter` | — | Converts `StreamEvent` → `OutboxEvent` for reuse of existing processors |
| `DeadLetterConsumerMixin` | `app.infrastructure.events.dead_letter_consumer_mixin` | — | Persists permanently failed events to `dead_letter_events` table |

### Inbound Sync Flow (Pulling Data from External Systems)

**Critical Architecture Pattern**: The outbox pattern is used for BOTH outbound events (local → external) AND inbound sync processing (external → local).

#### Two-Way Sync Architecture

The system supports bidirectional synchronization:

1. **Outbound Sync** (Local Changes → External Systems)
   - User updates contact in local database
   - Domain event triggers worker task
   - Worker pushes changes to external API (e.g., Google Contacts)

2. **Inbound Sync** (External Systems → Local Database)
   - Worker pulls data from external API (periodic, manual, or webhook-triggered)
   - Worker creates OutboxEvent records for each external entity
   - OutboxRelay publishes events to the Redis Stream
   - InboundEventConsumer processes events via its consumer group
   - Domain services create/update local entities

#### Inbound Sync Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Integration Worker (Isolated Process)                              │
│                                                                     │
│  1. Periodic/Manual Trigger                                        │
│     ↓                                                               │
│  2. sync_google_contacts(ctx, email, sync_type)                   │
│     ↓                                                               │
│  3. Fetch contacts from Google API                                 │
│     ↓                                                               │
│  4. For each contact:                                              │
│     - Create OutboxEvent with event_type='contact.created'         │
│     - Store Google Person data in event_data                       │
│     - Commit to database                                           │
│                                                                     │
│  ⚠️  Worker does NOT directly create/update Contact entities       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
                    OutboxEvent Table
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│ Main Application (FastAPI Process)                                 │
│                                                                     │
│  5. OutboxRelay publishes events to Redis Stream                    │
│     ↓                                                               │
│  6. InboundEventConsumer picks up contact.* events                  │
│     ↓                                                               │
│  7. JournalOutboxEventProcessor.process_event(event)                │
│     ↓                                                               │
│  8. Transform Google Person → Contact entity                        │
│     (using GoogleContactTransformer)                               │
│     ↓                                                               │
│  9. Create/Update Contact via ContactService                        │
│     ↓                                                               │
│ 10. ACK the stream message                                          │
└─────────────────────────────────────────────────────────────────────┘
```

#### Implementation: Worker Side (Inbound Sync)

```python
# In integration_workers/google/worker.py

async def sync_google_contacts(
    ctx: dict[str, Any],
    google_account_email: str,
    sync_type: str = "smart"
) -> dict[str, Any]:
    """
    Pull contacts from Google and create OutboxEvents for processing.

    This task:
    1. Fetches contacts from Google API
    2. Creates OutboxEvent records (NOT Contact entities directly)
    3. Returns sync metrics

    The actual Contact creation happens in the main app via InboundEventConsumer.
    """
    logger.info("Starting Google Contacts sync", email=google_account_email)

    # Get database session from worker context
    session = ctx['session']

    # Fetch contacts from Google API
    google_client = await get_google_client(session, google_account_email)
    contacts = await google_client.fetch_contacts()

    # Create OutboxEvent for each contact
    for person in contacts:
        outbox_event = OutboxEvent(
            event_type='contact.created',  # or 'contact.updated'
            aggregate_id=None,  # Will be set when Contact is created
            event_data={
                'google_account_email': google_account_email,
                'person_data': person.to_dict(),  # Full Google Person object
                'integration_source': 'google',
                'external_id': person.resource_name
            },
            retry_count=0,
            max_retries=3
        )
        session.add(outbox_event)

    session.commit()

    logger.info(
        "Created outbox events for Google contacts",
        count=len(contacts),
        email=google_account_email
    )

    return {
        'status': 'success',
        'contacts_fetched': len(contacts),
        'events_created': len(contacts)
    }
```

#### Implementation: Main App Side (Event Processing)

```python
# In backend/app/infrastructure/events/outbox_processor.py

class OutboxProcessor:
    """Processes outbox events in the main application."""

    async def process_events(self) -> None:
        """Process unprocessed events from outbox table."""
        async with engine.begin() as conn:
            repository = OutboxRepository(conn)
            events = await repository.get_unprocessed_events(limit=50)

            for event in events:
                try:
                    # Route contact.* events to OutboxEventProcessor
                    if event.event_type.startswith("contact."):
                        await self._process_contact_event(event, conn)
                    else:
                        # Other events (search indexing, etc.)
                        await search_indexer.process_event(event)

                    # Mark as processed
                    await repository.mark_as_processed(event.event_id)

                except Exception as e:
                    logger.error("Failed to process event", event_id=event.event_id)
                    await repository.increment_retry_count(event.event_id)

# In backend/app/core/integrations/outbox_event_processor.py

class OutboxEventProcessor:
    """Processes contact sync events from integration workers."""

    def __init__(
        self,
        contact_service: ContactService,
        transformer: GoogleContactTransformer,
        db_connection: AsyncConnection
    ):
        self.contact_service = contact_service
        self.transformer = transformer
        self.db_connection = db_connection

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """Process a single outbox event."""
        if event.event_type == "contact.created":
            return await self._process_contact_created(event)
        elif event.event_type == "contact.updated":
            return await self._process_contact_updated(event)
        else:
            raise OutboxEventProcessingError(f"Unknown event type: {event.event_type}")

    async def _process_contact_created(self, event: OutboxEvent) -> dict[str, Any]:
        """Transform Google Person data and create local Contact."""
        # Extract Google Person data from event
        person_data = event.event_data['person_data']
        google_account_email = event.event_data['google_account_email']
        external_id = event.event_data['external_id']

        # Transform Google Person to Contact entity
        contact_data = self.transformer.transform_person(person_data)

        # Create Contact via domain service
        contact = await self.contact_service.create_contact(
            user_id=user_id,
            contact_data=contact_data,
            db_connection=self.db_connection
        )

        # Create sync metadata
        await self._create_sync_metadata(
            contact_id=contact.id,
            external_id=external_id,
            integration_source='google',
            version_hash=calculate_hash(person_data)
        )

        logger.info(
            "Created contact from Google sync",
            contact_id=contact.id,
            external_id=external_id
        )

        return {'contact_id': str(contact.id), 'status': 'created'}
```

#### Why This Architecture?

**Separation of Concerns:**
- Workers focus on external API communication and data fetching
- Main app handles domain logic, validation, and entity creation
- Clear boundary between integration layer and domain layer

**Reliability:**
- OutboxEvent provides transactional guarantee
- If worker crashes after creating events, they're still processed
- If main app crashes, events remain in outbox for retry

**Dependency Isolation:**
- Workers don't need domain service dependencies
- Main app doesn't need external API client dependencies
- Each can be deployed/scaled independently

**Testability:**
- Worker tests focus on API integration
- Domain tests focus on business logic
- Event processing can be tested independently

## Observability and Monitoring

### Structured Logging with Context Propagation

**Critical for Debugging**: All services must use structured logging with correlation IDs.

#### Logging Configuration
```python
# In core_shared/logging/config.py
import structlog
import uuid
from contextvars import ContextVar

# Context variables for request tracing
trace_id_var: ContextVar[str] = ContextVar('trace_id', default='')
job_id_var: ContextVar[str] = ContextVar('job_id', default='')
worker_id_var: ContextVar[str] = ContextVar('worker_id', default='')

def configure_logging():
    """
    Configure structured logging for all services.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_trace_context,
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def add_trace_context(logger, method_name, event_dict):
    """Add tracing context to every log entry."""
    event_dict['trace_id'] = trace_id_var.get()
    event_dict['job_id'] = job_id_var.get()
    event_dict['worker_id'] = worker_id_var.get()
    return event_dict

# Usage in worker
async def sync_task(external_id: str):
    job_id = str(uuid.uuid4())
    job_id_var.set(job_id)
    worker_id_var.set('google-worker')

    logger = structlog.get_logger()
    logger.info("Starting sync task", external_id=external_id)
    # All subsequent logs will include job_id and worker_id
```

### Key Metrics (Golden Signals)

#### Metrics Collection
```python
# In core_shared/metrics/collector.py
from prometheus_client import Counter, Histogram, Gauge

# Job processing metrics
job_duration = Histogram(
    'worker_job_duration_seconds',
    'Time spent processing jobs',
    ['worker_type', 'job_type', 'status']
)

job_total = Counter(
    'worker_jobs_total',
    'Total number of jobs processed',
    ['worker_type', 'job_type', 'status']
)

queue_depth = Gauge(
    'worker_queue_depth',
    'Number of jobs waiting in queue',
    ['worker_type']
)

# Usage in worker
@job_duration.labels(worker_type='google', job_type='sync', status='success').time()
async def sync_contact(contact_id: str):
    try:
        # ... sync logic ...
        job_total.labels(worker_type='google', job_type='sync', status='success').inc()
    except Exception:
        job_total.labels(worker_type='google', job_type='sync', status='error').inc()
        raise
```

## Operational Readiness

### Graceful Shutdown Pattern

**Critical for Data Integrity**: Workers must complete in-flight jobs before termination.

#### Implementation
```python
# In worker.py
import signal
import asyncio
from typing import Optional

class GracefulWorker:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.current_job: Optional[str] = None

    async def setup_signal_handlers(self):
        """Setup graceful shutdown on SIGTERM/SIGINT."""
        loop = asyncio.get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self.shutdown())
            )

    async def shutdown(self):
        """Graceful shutdown - finish current job, reject new ones."""
        logger.info("Shutdown signal received, finishing current job")
        self.shutdown_event.set()

        # Wait for current job to complete (max 5 minutes)
        if self.current_job:
            logger.info(f"Waiting for job {self.current_job} to complete")
            await asyncio.sleep(0.1)  # Allow job to finish naturally

        logger.info("Worker shutdown complete")

    async def process_job(self, job_data):
        """Process job with shutdown awareness."""
        if self.shutdown_event.is_set():
            logger.info("Rejecting new job due to shutdown")
            raise Exception("Worker shutting down")

        self.current_job = job_data.get('job_id')
        try:
            # ... actual job processing ...
            pass
        finally:
            self.current_job = None

# Docker configuration for graceful shutdown
# In Dockerfile:
# STOPSIGNAL SIGTERM
#
# In docker-compose.yml:
# stop_grace_period: 300s  # 5 minutes for jobs to complete
```

### Configuration and Secrets Management

#### Secure Configuration Pattern
```python
# In worker configuration
from pydantic import BaseSettings, SecretStr
import boto3

class WorkerSettings(BaseSettings):
    # Database connection
    database_url: SecretStr
    redis_url: str

    # Integration-specific secrets
    google_client_id: str
    google_client_secret: SecretStr

    # Operational settings
    worker_id: str = "google-worker"
    log_level: str = "INFO"
    max_concurrent_jobs: int = 5

    class Config:
        env_file = ".env"

    @classmethod
    def from_secrets_manager(cls, secret_name: str):
        """Load configuration from AWS Secrets Manager."""
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=secret_name)
        secrets = json.loads(response['SecretValue'])
        return cls(**secrets)

# Usage
settings = WorkerSettings.from_secrets_manager("prod/google-worker")
```

#### Docker Secrets Integration
```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  google-worker:
    image: personal-mgmt/google-worker:latest
    secrets:
      - google_client_secret
      - database_password
    environment:
      - GOOGLE_CLIENT_ID=your-client-id
      - GOOGLE_CLIENT_SECRET_FILE=/run/secrets/google_client_secret
      - DATABASE_PASSWORD_FILE=/run/secrets/database_password
    deploy:
      restart_policy:
        condition: on-failure
        delay: 30s
        max_attempts: 3

secrets:
  google_client_secret:
    external: true
  database_password:
    external: true
```

### Long-Running Job Management

#### Progress Tracking Pattern
```python
# In core_shared/models/job_progress.py
class JobProgress(BaseModel):
    job_id: UUID
    worker_type: str
    status: JobStatus  # PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    progress_percent: int = 0
    current_step: str = ""
    total_items: Optional[int] = None
    processed_items: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

# In worker implementation
async def sync_all_contacts(job_id: UUID):
    """Long-running sync with progress tracking."""
    progress = JobProgress(
        job_id=job_id,
        worker_type='google',
        status=JobStatus.RUNNING,
        current_step='Fetching contact list'
    )
    await update_job_progress(progress)

    try:
        # Get total count
        total_contacts = await get_total_contact_count()
        progress.total_items = total_contacts
        progress.current_step = 'Syncing contacts'
        await update_job_progress(progress)

        # Process in batches with progress updates
        for i, contact_batch in enumerate(get_contact_batches()):
            if await is_job_cancelled(job_id):
                progress.status = JobStatus.CANCELLED
                await update_job_progress(progress)
                return

            await sync_contact_batch(contact_batch)

            # Update progress every batch
            progress.processed_items = (i + 1) * BATCH_SIZE
            progress.progress_percent = min(
                int((progress.processed_items / total_contacts) * 100),
                100
            )
            await update_job_progress(progress)

        progress.status = JobStatus.COMPLETED
        progress.completed_at = datetime.utcnow()
        await update_job_progress(progress)

    except Exception as e:
        progress.status = JobStatus.FAILED
        progress.error_message = str(e)
        progress.completed_at = datetime.utcnow()
        await update_job_progress(progress)
        raise
```

#### Job Cancellation Support
```python
# API endpoint for job cancellation
@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: UUID):
    """Cancel a running integration job."""
    await mark_job_cancelled(job_id)
    return {"message": "Job cancellation requested"}

# Worker checks for cancellation
async def sync_contact_batch(contacts):
    for contact in contacts:
        # Check for cancellation before each contact
        if await is_job_cancelled(current_job_id):
            logger.info("Job cancelled, stopping sync")
            return

        await sync_single_contact(contact)
```

## Pluggable Integration Registry

### Overview

The **Integration Registry** provides a unified API for listing all registered integrations and their current status. Instead of individual status endpoints per integration (e.g. `/api/integrations/google/contacts/status`), the registry aggregates information from all providers into a single response.

### Architecture

```
┌─────────────────────────────┐
│  GET /api/integrations      │
│  (IntegrationsController)   │
└───────┬─────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ IntegrationRegistryService  │  ← Aggregates results from all providers
│                             │     Error-isolating: one provider failure
│                             │     does not affect others
└───────┬─────────────────────┘
        │  list[IntegrationProvider]
        ├────────────────────────┐
        ▼                        ▼
┌──────────────────┐   ┌──────────────────┐
│ GoogleIntegration │   │ StravaIntegration │  (future)
│    Provider       │   │    Provider       │
└──────────────────┘   └──────────────────┘
```

### Provider Protocol

Every integration must implement the `IntegrationProvider` protocol:

```python
class IntegrationProvider(Protocol):
    async def get_integration_info(
        self, user_id: str, connection: AsyncConnection
    ) -> IntegrationInfo:
        ...
```

`IntegrationInfo` is a frozen dataclass containing:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique integration identifier (e.g. `"google"`) |
| `name` | `str` | Human-readable name |
| `status` | `IntegrationStatus` | `connected`, `disconnected`, `error`, `token_expired` |
| `capabilities` | `list[IntegrationCapability]` | `contacts_sync`, `calendar_sync`, `activity_import` |
| `sync_summary` | `SyncSummary` | `last_sync_time`, `sync_count`, `error_count` |
| `needs_reauth` | `bool` | Token expired or revoked |
| `needs_reconsent` | `bool` | Missing required OAuth scopes |

### DI Registration

Providers are registered as a `list[IntegrationProvider]` via Dishka. The registry service receives this list at construction time:

```python
# In app/infrastructure/di/integrations.py
@provide(scope=Scope.APP)
def provide_integration_registry_service(
    google_provider: GoogleIntegrationProvider,
) -> IntegrationRegistryService:
    return IntegrationRegistryService(providers=[google_provider])
```

### Error Isolation

If a provider raises an exception, the registry returns an error entry for that integration and continues querying remaining providers:

```python
IntegrationInfo(
    id=integration_id,
    name=integration_id.title(),
    status=IntegrationStatus.ERROR,
)
```

### REST API: `GET /api/integrations`

Returns a JSON API response listing all registered integrations:

```json
{
  "data": [
    {
      "id": "google",
      "type": "integration",
      "attributes": {
        "status": "connected",
        "capabilities": ["contacts_sync", "calendar_sync"],
        "sync_summary": {
          "last_sync_time": "2024-01-15T10:30:00",
          "sync_count": 42,
          "error_count": 0
        },
        "needs_reauth": false,
        "needs_reconsent": false
      }
    }
  ]
}
```

### MCP Tool: `list_integrations`

The same data is exposed via the MCP `list_integrations` tool in `app/mcp/domains/integrations/tools.py`. It returns both structured JSON data and an AI-friendly `summary` field (e.g. `"1/1 integrations connected"`).

### Adding a New Integration Provider

1. Create a class implementing `IntegrationProvider` (e.g. `StravaIntegrationProvider`)
2. Register it in the Dishka DI container (`app/infrastructure/di/integrations.py`)
3. Add it to the `providers` list in `provide_integration_registry_service`
4. The REST and MCP endpoints automatically include the new integration

## Future Considerations

### Advanced Scalability Patterns
- **Queue-Based Autoscaling**: Scale workers based on queue depth using KEDA
- **Resource Isolation**: Dedicated worker pools for different job types (fast vs. slow)
- **Intelligent Load Balancing**: Route jobs based on worker capacity and job characteristics
- **Horizontal Sharding**: Partition large datasets across multiple worker instances
- **Caching Layers**: Redis-based caching for frequently accessed external data

### Advanced Operational Safety
- **API-Level Rate Limiting**: Protect system from runaway clients and DoS attacks
- **Poison Pill Handling**: Check-in/check-out mechanism to prevent crash loops
- **Canary Deployments**: Gradual rollout of worker updates with automatic rollback
- **Circuit Breaker Pattern**: Fail fast when external services are unavailable
- **Bulkhead Isolation**: Isolate failures to prevent cascade effects

### Additional Integrations
- Communication platforms (Signal, WhatsApp)
- Email providers (Zoho Mail, Gmail)
- Calendar systems (CalDAV)
- Financial services beyond Firefly III
- Social media platforms (Twitter, LinkedIn)
- Productivity tools (Notion, Obsidian)

### Advanced Features
- Real-time sync via webhooks and Server-Sent Events
- Conflict resolution UI with merge strategies
- Integration health dashboard with predictive analytics
- Data export/import tools with format conversion
- Multi-tenant support for shared hosting
- AI-powered data enrichment and deduplication
- Cross-integration data correlation and insights
