# Core Shared Package

Shared models and utilities for Lifecontour integrations.

## Overview

The `core_shared` package contains SQLAlchemy models, database utilities, and common patterns used across the main Lifecontour application and integration workers. This package enables:

- **Shared Data Models**: Common SQLAlchemy models for sync metadata and external references
- **Database Utilities**: Connection management and engine configuration
- **Integration Patterns**: Standardized approaches for external system integration
- **Worker Isolation**: Shared code that can be used in isolated worker processes

## Architecture

The package follows the isolated worker architecture pattern where:

1. **Main Application**: Uses shared models for integration state tracking
2. **Integration Workers**: Use shared models and utilities for sync operations
3. **Shared Database**: All components use the same database schema
4. **Consistent Patterns**: Common approaches across all integrations

## Models

### SyncMetadata

Tracks synchronization state between external systems and internal entities:

```python
from core_shared import SyncMetadata, SyncStatus

# Track sync state for a contact
sync_record = SyncMetadata(
    internal_id=123,
    integration_source="google",
    external_id="person/abc123",
    last_synced_at=datetime.utcnow(),
    version_hash="sha256_hash_of_data",
    sync_status=SyncStatus.SUCCESS.value,
)
```

### ExternalReference

Tracks references between internal entities and external system entities:

```python
from core_shared import ExternalReference

# Link internal contact to external photo
reference = ExternalReference(
    internal_entity_type="contact",
    internal_entity_id=123,
    external_system="immich",
    external_entity_type="person",
    external_entity_id="person_uuid_456",
)
```

### PendingEntityMapping

Tracks unresolved sync conflicts when name-based matching produces multiple candidate contacts:

```python
from core_shared import PendingEntityMapping

# Created automatically during people sync when ambiguous matches found
# Resolved via conflict resolution UI or MCP tools
```

## Utilities

### ContactNameMatcher

Shared name-matching utility for integrations that link external entities to local contacts (used by Immich and Strava):

```python
from core_shared import ContactNameMatcher
from core_shared.models.contacts.entities import Contact

# Parse a full name string into first/last name
first, last = ContactNameMatcher.parse_name("John Michael Smith")
# → ("John Michael", "Smith")

# Find contacts matching a name (case-insensitive, middle initial, abbreviated)
matches = ContactNameMatcher.find_matches("John S", contacts)
```

Supports:
- **Exact match** (case-insensitive)
- **Middle initial variants** ("John A Smith" ↔ "John Smith")
- **Abbreviated last name** ("John S" matches "John Smith")

## Database Utilities

### Connection Management

```python
from core_shared import get_database_url, create_engine_from_env

# Get database URL from environment
url = get_database_url()

# Create engine with optimized settings
engine = create_engine_from_env(pool_size=5, max_overflow=10)
```

## Installation

The package is designed to be installed in editable mode during development:

```bash
# Install in main application
cd backend
uv pip install -e ../core_shared

# Install in worker environment
cd integration_workers/google
uv pip install -e ../../core_shared
```

## Development

### Running Tests

```bash
cd core_shared
uv run pytest
```

### Linting

```bash
cd core_shared
uv run ruff check .
uv run ruff format .
uv run mypy .
```

### Adding New Models

1. Create model file in `core_shared/models/`
2. Add model to `core_shared/models/__init__.py`
3. Add model to main `core_shared/__init__.py`
4. Create database migration in main application
5. Add tests for the new model

## Integration with Main Application

The main application includes this package and uses the shared models:

```python
# In backend application
from core_shared import SyncMetadata, ExternalReference

# Use in repositories, services, etc.
```

## Integration with Workers

Workers install this package and use it for sync operations:

```python
# In worker process
from core_shared import SyncMetadata, create_engine_from_env

# Create database connection
engine = create_engine_from_env()

# Track sync state
# ... worker logic
```

## Version Compatibility

- **Python**: 3.11+
- **SQLAlchemy**: 2.0+
- **PostgreSQL**: 12+

## Contributing

1. Follow the existing code style and patterns
2. Add tests for new functionality
3. Update documentation for API changes
4. Ensure compatibility with both main app and workers
