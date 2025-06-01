# ITER1-003: Contacts REST API with Search - Architecture Decisions

## Overview

ITER1-003 implements the REST API layer for contacts management with MeiliSearch integration using an event-driven architecture. This iteration builds on the solid domain foundation from ITER1-002 and adds the API and search infrastructure.

## Key Architectural Decisions

### 1. Authentication Strategy

**Decision**: Session-based authentication using Starlette SessionMiddleware

**Rationale**:
- Simple and lightweight for personal management system
- Built into FastAPI/Starlette, no additional dependencies
- Supports both frontend and manual API usage
- Can be upgraded to OAuth2 in ITER2 when Google integration is added

**Implementation**:
- Starlette SessionMiddleware for session management
- Session-based login/logout endpoints
- Simple username/password authentication for MVP
- Session validation dependency for protected endpoints

### 2. MeiliSearch Integration Architecture

**Decision**: Event-driven indexing via transactional outbox pattern (Option C)

**Rationale**:
- Maintains domain purity and separation of concerns
- Ensures data consistency between PostgreSQL and MeiliSearch
- Supports eventual consistency model
- Enables future multi-search backend support
- Aligns with existing domain events architecture

**Components**:
```
Domain Events → Outbox Table → Background Processor → MeiliSearch
```

### 3. Transactional Outbox Pattern

**Design**:
- **Outbox Table**: Store events in same transaction as domain changes
- **Event Serialization**: JSON with event type, aggregate ID, and data
- **Background Processor**: FastAPI background task every 10 seconds
- **Processing Strategy**: Mark events as processed, don't delete immediately

**Schema**:
```sql
CREATE TABLE outbox_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(255) UNIQUE NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id INTEGER NOT NULL,
    event_data JSONB NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    processed_at TIMESTAMP NULL,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 4. Search Architecture

**Scope**: Contacts only for ITER1-003, designed for future expansion

**Endpoints**:
- `/api/contacts/search` - Contact-specific search
- `/api/search` - Global search (contacts only in this iteration)

**Performance Target**: <50ms response times

**Error Handling**: MeiliSearch failures cause search endpoints to fail (no graceful degradation)

**Features**:
- Full-text search with typo tolerance
- Search result highlighting
- Faceted search (tags, locations)
- Pagination and sorting

### 5. Dependency Injection Strategy

**Decision**: Continue with FastAPI's built-in `Depends` system

**Rationale**:
- FastAPI's DI is powerful and well-integrated
- No additional dependencies required
- Sufficient for current complexity
- Can upgrade to dependency-injector library later if needed

**Enhancement**: Create service factory functions for cleaner dependency management

### 6. API Architecture

**Structure**:
```
app/api/
├── dependencies.py           # Shared dependencies and factories
├── auth/
│   ├── controllers.py        # Authentication endpoints
│   └── dependencies.py       # Auth-specific dependencies
├── contacts/
│   ├── controllers.py        # Contact CRUD and management
│   ├── schemas.py           # Pydantic models
│   └── dependencies.py      # Contact-specific dependencies
└── search/
    ├── controllers.py        # Search endpoints
    └── schemas.py           # Search request/response models
```

**Design Principles**:
- JSON API compliance where applicable
- Comprehensive input validation with Pydantic
- Proper HTTP status codes and error handling
- OpenAPI documentation generation

### 7. Background Task Architecture

**Decision**: FastAPI BackgroundTasks for outbox processing

**Rationale**:
- Simple implementation for single-instance deployment
- No additional dependencies
- Sufficient for MVP requirements
- Can upgrade to APScheduler or Celery later if needed

**Implementation**:
- Background task started during application lifespan
- Processes outbox events every 10 seconds
- Handles retries and error logging
- Updates MeiliSearch indices based on domain events

### 8. Infrastructure Components

**New Components**:
```
app/infrastructure/
├── search/
│   ├── meilisearch_client.py    # MeiliSearch connection and config
│   ├── search_indexer.py        # Event-driven indexing logic
│   └── search_service.py        # Search operations and queries
├── events/
│   ├── outbox_repository.py     # Outbox table operations
│   ├── outbox_processor.py      # Background event processing
│   └── event_publisher.py       # Outbox event publisher implementation
└── auth/
    ├── session_manager.py       # Session management utilities
    └── auth_service.py          # Authentication logic
```

## Event Flow Architecture

### Contact Creation Flow
```
1. API Request → ContactController
2. ContactController → ContactService.create_contact()
3. ContactService → ContactRepository.save() + OutboxEventPublisher.publish()
4. Transaction commits (contact saved + event in outbox)
5. Background task processes outbox → MeiliSearch indexing
```

### Search Flow
```
1. Search Request → SearchController
2. SearchController → SearchService.search_contacts()
3. SearchService → MeiliSearch query
4. Results returned with highlighting and facets
```

## Configuration

**Environment Variables**:
- `MEILISEARCH_URL`: MeiliSearch server URL
- `MEILISEARCH_API_KEY`: MeiliSearch API key
- `SESSION_SECRET_KEY`: Secret for session encryption
- `SEARCH_INDEX_PREFIX`: Prefix for search indices (default: "pms_")

**MeiliSearch Indices**:
- `pms_contacts`: Contact search index
- Future: `pms_journal`, `pms_calendar`, etc.

## Performance Considerations

- **Search Response Time**: Target <50ms
- **Indexing Latency**: Eventual consistency, typically <10 seconds
- **Background Processing**: Every 10 seconds, configurable
- **Connection Pooling**: Reuse MeiliSearch client connections
- **Batch Processing**: Process multiple outbox events in single batch

## Security Considerations

- **Session Security**: Secure session cookies with proper flags
- **Input Validation**: Comprehensive Pydantic validation
- **Search Injection**: Parameterized MeiliSearch queries
- **Rate Limiting**: Consider adding in future iterations

## Testing Strategy

- **Unit Tests**: Domain logic remains isolated
- **Integration Tests**: API endpoints with test database and MeiliSearch
- **Search Tests**: Verify indexing and search functionality
- **Authentication Tests**: Session management and protected endpoints

## Future Considerations

- **Multi-tenant Support**: Design allows for tenant-specific indices
- **Advanced Search**: Semantic search, AI-powered suggestions
- **Real-time Updates**: WebSocket support for live search updates
- **Caching**: Redis caching layer for frequent searches
- **Monitoring**: Search analytics and performance monitoring
