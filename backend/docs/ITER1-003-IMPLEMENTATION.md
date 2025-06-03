# ITER1-003 Implementation: MeiliSearch and Outbox Pattern

## Overview

This document describes the implementation of MeiliSearch integration and the transactional outbox pattern for ITER1-003. The implementation provides reliable search functionality with event-driven indexing.

## Architecture

### Components Implemented

1. **Outbox Pattern Infrastructure**
   - `OutboxEventPublisher`: Implements `ContactEventPublisher` interface
   - `OutboxRepository`: Manages outbox events in the database
   - `OutboxProcessor`: Background task for processing events
   - `outbox_events` table: Stores events for reliable processing

2. **MeiliSearch Integration**
   - `MeiliSearchClient`: Connection and configuration management
   - `SearchIndexer`: Processes domain events and updates search indices
   - `SearchService`: High-level search operations
   - Contact indexing with full-text search capabilities

3. **API Layer**
   - Search endpoints for contacts and global search
   - Health check endpoints for monitoring
   - Proper error handling and response formatting

4. **Background Processing**
   - Outbox processor runs every 10 seconds
   - Automatic retry mechanism for failed events
   - Graceful degradation when MeiliSearch is unavailable

## Database Schema

### outbox_events Table

```sql
CREATE TABLE outbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id INTEGER NOT NULL,
    event_data TEXT NOT NULL,  -- JSON
    occurred_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);

-- Indexes for performance
CREATE UNIQUE INDEX ix_outbox_events_event_id ON outbox_events (event_id);
CREATE INDEX ix_outbox_events_event_type ON outbox_events (event_type);
CREATE INDEX ix_outbox_events_aggregate_id ON outbox_events (aggregate_id);
CREATE INDEX ix_outbox_events_processed_at ON outbox_events (processed_at);
```

## Configuration

### Environment Variables

```bash
# MeiliSearch Configuration
MEILISEARCH_URL=http://meilisearch:7700
MEILISEARCH_API_KEY=personal_management_search_key
SEARCH_INDEX_PREFIX=pms_

# Session Management
SESSION_SECRET_KEY=personal_management_session_secret_key_change_in_production
```

### Docker Compose

Added MeiliSearch service:

```yaml
meilisearch:
  image: getmeili/meilisearch:v1.2
  container_name: personal-management-search
  environment:
    - MEILI_MASTER_KEY=personal_management_search_key
    - MEILI_ENV=development
    - MEILI_LOG_LEVEL=INFO
  volumes:
    - meilisearch_data:/meili_data
  ports:
    - "7700:7700"
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:7700/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s
```

## API Endpoints

### Search Endpoints

- `GET /api/search/contacts` - Search contacts with filters and pagination
- `GET /api/search/global` - Global search across all entity types
- `GET /api/search/suggestions` - Get search suggestions for autocomplete
- `GET /api/search/health` - Search system health check

### Example Usage

```bash
# Search contacts
curl "http://localhost:8000/api/search/contacts?q=john&limit=10"

# Global search
curl "http://localhost:8000/api/search/global?q=meeting&entity_types=contact"

# Health check
curl "http://localhost:8000/api/search/health"
```

## Event Flow

1. **Domain Event Creation**: Contact operations create domain events
2. **Outbox Publishing**: Events are stored in `outbox_events` table within the same transaction
3. **Background Processing**: Outbox processor retrieves unprocessed events every 10 seconds
4. **Search Indexing**: Events are processed and sent to MeiliSearch for indexing
5. **Event Completion**: Successfully processed events are marked as processed

## Error Handling

### Retry Mechanism

- Failed events are retried up to 3 times
- Retry count is incremented for each failure
- Events exceeding max retries are logged but not processed further

### Graceful Degradation

- Search endpoints return 503 when MeiliSearch is unavailable
- Background processor continues running even if MeiliSearch is down
- Health endpoints provide detailed status information

## Testing

### Unit Tests

- `test_outbox_event_publisher.py`: Tests event publishing to outbox
- `test_outbox_repository.py`: Tests outbox data operations
- `test_search_indexer.py`: Tests MeiliSearch indexing logic
- `test_search_service.py`: Tests search service operations
- `test_outbox_processor.py`: Tests background processing

### Integration Tests

- `test_outbox_integration.py`: End-to-end outbox flow testing
- `test_meilisearch_integration.py`: Real MeiliSearch integration tests

### Running Tests

```bash
# Unit tests
python -m pytest tests/unit/infrastructure/ -v

# Integration tests (requires MeiliSearch)
python -m pytest tests/integration/infrastructure/ -v -m integration

# All tests
python -m pytest tests/ -v
```

## Performance Considerations

### Search Performance

- Target response time: <50ms for search queries
- MeiliSearch indices are optimized for contact search patterns
- Proper field configuration for searchable, filterable, and sortable attributes

### Background Processing

- Batch processing of outbox events (50 events per cycle)
- Configurable processing interval (default: 10 seconds)
- Efficient database queries with proper indexing

## Monitoring

### Health Checks

- Database connectivity
- MeiliSearch availability
- Outbox processing status
- Failed events tracking

### Metrics

- Search response times
- Outbox processing latency
- Failed event counts
- Index document counts

## Future Enhancements

1. **Additional Entity Types**: Extend indexing to journal entries, calendar events
2. **Advanced Search Features**: Faceted search, autocomplete, typo tolerance
3. **Search Analytics**: Query logging, popular searches, performance metrics
4. **Bulk Operations**: Batch indexing for large data imports
5. **Search Personalization**: User-specific search ranking and preferences

## Dependencies Added

```toml
dependencies = [
    # ... existing dependencies
    "meilisearch>=0.31.0",
    "itsdangerous>=2.1.0",
    "asyncpg>=0.29.0",
]
```

## Files Created/Modified

### New Files

- `app/infrastructure/events/outbox_table.py`
- `app/infrastructure/events/outbox_event_publisher.py`
- `app/infrastructure/events/outbox_repository.py`
- `app/infrastructure/events/outbox_processor.py`
- `app/infrastructure/search/meilisearch_client.py`
- `app/infrastructure/search/search_indexer.py`
- `app/infrastructure/search/search_service.py`
- `app/api/search/controllers.py`
- `app/api/search/schemas.py`
- `app/api/dependencies.py`
- `app/infrastructure/database_metadata.py`

### Modified Files

- `app/main.py`: Added search routes and background tasks
- `app/infrastructure/config.py`: Added MeiliSearch and session configuration
- `app/infrastructure/database.py`: Added async engine support
- `docker-compose.yml`: Added MeiliSearch service
- `pyproject.toml`: Added new dependencies

## Conclusion

The implementation successfully provides:

1. ✅ Reliable event publishing via transactional outbox pattern
2. ✅ MeiliSearch integration with proper error handling
3. ✅ Background processing with retry mechanism
4. ✅ Search API endpoints with proper response formatting
5. ✅ Comprehensive testing suite
6. ✅ Health monitoring and status endpoints
7. ✅ Graceful degradation when external services are unavailable

The system is ready for production deployment and can be extended to support additional entity types and search features as needed.
