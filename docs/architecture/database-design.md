# Database Design - Personal CRM & Journal System

This document outlines the database approach and initial schema for the Personal CRM & Journal System. The design will evolve through agile iterations as features are implemented.

## PostgreSQL Database Approach

### Design Philosophy
- **Iterative Schema Development**: Start with core tables, expand as features are built
- **PostgreSQL Features**: Leverage JSON columns, full-text search, and advanced indexing
- **Explicit SQL**: Use SQLAlchemy Core with readable SQL queries
- **Migration-Driven**: Schema changes through Alembic migrations

### Initial Core Tables (Iteration 1)

#### Contacts Table
```sql
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    notes TEXT,
    tags JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Basic Indexing (Iteration 1)
```sql
-- Essential indexes for contact operations
CREATE INDEX idx_contacts_name ON contacts USING gin(to_tsvector('english', name));
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_tags ON contacts USING gin(tags);
CREATE INDEX idx_contacts_created_at ON contacts(created_at);
```

## Future Tables (Later Iterations)

### Calendar and Events (Iteration 2)
```sql
-- To be implemented when calendar features are added
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    location TEXT,
    attendees JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Journal System (Iteration 3)
```sql
-- To be implemented when journal features are added
CREATE TABLE journal_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255),
    content TEXT NOT NULL,
    mood INTEGER CHECK (mood >= 1 AND mood <= 10),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Photo Integration (Iteration 4)
```sql
-- To be implemented when Immich integration is added
CREATE TABLE photo_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    immich_id VARCHAR(255) UNIQUE NOT NULL,
    filename VARCHAR(255) NOT NULL,
    taken_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### External Integration Tables (Later Iterations)

#### Google Sync State (When Google Integration Added)
```sql
-- To be implemented when Google sync features are added
CREATE TABLE google_sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL,
    local_id UUID NOT NULL,
    google_id VARCHAR(255) NOT NULL,
    etag VARCHAR(255),
    last_synced TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sync_status VARCHAR(20) DEFAULT 'synced',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(entity_type, local_id)
);
```

#### Contact Interactions (When Interaction Tracking Added)
```sql
-- To be implemented when interaction tracking is added
CREATE TABLE contact_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contact_id UUID NOT NULL REFERENCES contacts(id),
    interaction_type VARCHAR(50) NOT NULL,
    description TEXT,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## PostgreSQL Features and Patterns

### JSON Column Usage
```sql
-- Flexible metadata storage
UPDATE contacts SET tags = tags || '["work"]'::jsonb WHERE id = ?;

-- Query JSON data
SELECT * FROM contacts WHERE tags @> '["family"]';

-- Extract JSON values
SELECT name, tags->>'work' as work_info FROM contacts;
```

### Full-Text Search (PostgreSQL)
```sql
-- Add search vector column (when needed)
ALTER TABLE contacts ADD COLUMN search_vector tsvector;

-- Update search vector
UPDATE contacts SET search_vector =
    to_tsvector('english', coalesce(name,'') || ' ' || coalesce(email,'') || ' ' || coalesce(notes,''));

-- Create GIN index for fast search
CREATE INDEX idx_contacts_search ON contacts USING gin(search_vector);

-- Search query
SELECT * FROM contacts
WHERE search_vector @@ plainto_tsquery('english', 'john smith');
```

### Advanced Indexing (Added as Needed)
```sql
-- Partial indexes for active records
CREATE INDEX idx_contacts_active ON contacts(created_at) WHERE updated_at > NOW() - INTERVAL '1 year';

-- Composite indexes for common queries
CREATE INDEX idx_contacts_name_email ON contacts(name, email);

-- JSON indexes for tag queries
CREATE INDEX idx_contacts_tags_gin ON contacts USING gin(tags);
```

## Migration Strategy

### Alembic Migration Approach
```python
# Example migration for contacts table
"""Create contacts table

Revision ID: 001_create_contacts
Revises:
Create Date: 2024-01-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    op.create_table('contacts',
        sa.Column('id', postgresql.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.VARCHAR(length=255), nullable=False),
        sa.Column('email', sa.VARCHAR(length=255), nullable=True),
        sa.Column('phone', sa.VARCHAR(length=50), nullable=True),
        sa.Column('notes', sa.TEXT(), nullable=True),
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create basic indexes
    op.create_index('idx_contacts_name', 'contacts', [sa.text('to_tsvector(\'english\', name)')], postgresql_using='gin')
    op.create_index('idx_contacts_email', 'contacts', ['email'])
    op.create_index('idx_contacts_tags', 'contacts', ['tags'], postgresql_using='gin')

def downgrade():
    op.drop_table('contacts')
```

### Iterative Schema Evolution
- **Iteration 1**: Basic contacts table with essential fields
- **Iteration 2**: Add calendar/events tables when calendar features implemented
- **Iteration 3**: Add journal tables when journal features implemented
- **Iteration 4**: Add photo/Immich integration tables when photo features implemented
- **Future**: Add additional tables as features are developed

## Data Layer Implementation

### Repository Pattern (Python)
Each domain implements repositories following the Repository pattern:

```python
# Abstract repository interface
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

class ContactRepository(ABC):
    @abstractmethod
    async def find_by_id(self, contact_id: UUID) -> Optional[Contact]:
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Optional[Contact]:
        pass

    @abstractmethod
    async def search(self, query: str) -> List[Contact]:
        pass

    @abstractmethod
    async def save(self, contact: Contact) -> Contact:
        pass

    @abstractmethod
    async def delete(self, contact_id: UUID) -> None:
        pass
```

### SQLAlchemy Core Implementation
```python
# Example repository implementation
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

class PostgreSQLContactRepository(ContactRepository):
    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    async def find_by_id(self, contact_id: UUID) -> Optional[Contact]:
        query = text("SELECT * FROM contacts WHERE id = :id")
        result = await self.conn.execute(query, {"id": contact_id})
        row = result.fetchone()
        return Contact.from_row(row) if row else None

    async def search(self, query: str) -> List[Contact]:
        search_query = text("""
            SELECT * FROM contacts
            WHERE search_vector @@ plainto_tsquery('english', :query)
            ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query)) DESC
        """)
        result = await self.conn.execute(search_query, {"query": query})
        return [Contact.from_row(row) for row in result.fetchall()]
```

## Performance Considerations

### Query Optimization (PostgreSQL)
- Use parameterized queries for security and performance
- Implement query result caching where appropriate
- Leverage PostgreSQL-specific features (JSONB, full-text search)
- Use EXPLAIN ANALYZE for performance analysis
- Add indexes incrementally based on actual usage patterns

### Connection Management
- Use asyncpg connection pooling for concurrent access
- Proper async connection lifecycle management
- Timeout and retry strategies for external integrations
- Connection health monitoring in application health checks

### Data Growth Strategy
- Start simple with single table approach
- Add partitioning when data volume requires it
- Implement archival strategies as needed
- Monitor query performance and add indexes incrementally

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - How domains interact with the database
- [Technology Stack](./technology-stack.md) - ORM and database technology choices
- [Security & Performance](./security-performance.md) - Database security and optimization
