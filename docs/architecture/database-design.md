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
    id SERIAL PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100),
    middle_name VARCHAR(100),
    nick_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Contact Methods Table
```sql
CREATE TABLE contact_methods (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    method_type VARCHAR(20) NOT NULL CHECK (method_type IN ('email', 'phone')),
    value TEXT NOT NULL,
    label VARCHAR(50), -- e.g., 'work', 'home', 'mobile'
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(contact_id, method_type, is_primary) WHERE is_primary = TRUE
);
```

**Note:** In the application layer, `method_type` is represented as a Python enum (`MethodType.EMAIL`, `MethodType.PHONE`) for type safety, but stored as strings in the database.

#### Contact Addresses Table
```sql
CREATE TABLE contact_addresses (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    label VARCHAR(50), -- e.g., 'home', 'work', 'billing'
    street_line_1 VARCHAR(255) NOT NULL,
    street_line_2 VARCHAR(255),
    locality VARCHAR(100), -- city/town
    region VARCHAR(100), -- state/province/region
    postal_code VARCHAR(20),
    country_code VARCHAR(2) NOT NULL, -- ISO 3166-1 alpha-2
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(contact_id, is_primary) WHERE is_primary = TRUE
);
```

#### Contact Notes Table
```sql
CREATE TABLE contact_notes (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Tags Table
```sql
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
    color VARCHAR(7), -- Hex color code
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT tag_name_format CHECK (name ~ '^[a-zA-Z0-9_&-]+$')
);
```

#### Contact Tags Junction Table
```sql
CREATE TABLE contact_tags (
    id SERIAL PRIMARY KEY,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(contact_id, tag_id)
);
```

#### Contact History Table
```sql
CREATE TABLE contact_history (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL, -- 'contact', 'contact_method', 'contact_note', 'contact_tag'
    entity_id INTEGER NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('created', 'updated', 'deleted')),
    field_name VARCHAR(100), -- specific field that changed (for updates)
    old_value TEXT,
    new_value TEXT,
    changed_by VARCHAR(100), -- user identifier (for future auth)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Event Outbox Table (Transactional Event Publishing)
```sql
CREATE TABLE event_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) NOT NULL UNIQUE,
    event_type VARCHAR(100) NOT NULL,
    aggregate_id INTEGER NOT NULL,
    aggregate_type VARCHAR(50) NOT NULL, -- 'contact', 'journal', 'calendar', etc.
    event_data JSONB NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE NULL,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT NULL,
    correlation_id VARCHAR(255) NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Note:** The outbox table stores domain events from all domains (contacts, journal, calendar, etc.) for transactional publishing to MeiliSearch and other external systems.

#### Basic Indexing (Iteration 1)
```sql
-- Essential indexes for contact operations
CREATE INDEX idx_contacts_first_name ON contacts USING gin(to_tsvector('english', first_name));
CREATE INDEX idx_contacts_last_name ON contacts USING gin(to_tsvector('english', last_name));
CREATE INDEX idx_contacts_full_name ON contacts USING gin(to_tsvector('english',
    COALESCE(first_name, '') || ' ' || COALESCE(last_name, '') || ' ' || COALESCE(nick_name, '')));

-- Contact methods indexes
CREATE INDEX idx_contact_methods_contact_id ON contact_methods(contact_id);
CREATE INDEX idx_contact_methods_type ON contact_methods(method_type);
CREATE INDEX idx_contact_methods_value ON contact_methods(value);
CREATE INDEX idx_contact_methods_primary ON contact_methods(contact_id, method_type) WHERE is_primary = TRUE;

-- Contact addresses indexes
CREATE INDEX idx_contact_addresses_contact_id ON contact_addresses(contact_id);
CREATE INDEX idx_contact_addresses_country ON contact_addresses(country_code);
CREATE INDEX idx_contact_addresses_locality ON contact_addresses(locality);
CREATE INDEX idx_contact_addresses_primary ON contact_addresses(contact_id) WHERE is_primary = TRUE;

-- Contact notes indexes
CREATE INDEX idx_contact_notes_contact_id ON contact_notes(contact_id);
CREATE INDEX idx_contact_notes_content ON contact_notes USING gin(to_tsvector('english', content));

-- Tags indexes
CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_tags_parent_id ON tags(parent_id);

-- Contact tags indexes
CREATE INDEX idx_contact_tags_contact_id ON contact_tags(contact_id);
CREATE INDEX idx_contact_tags_tag_id ON contact_tags(tag_id);

-- History indexes
CREATE INDEX idx_contact_history_entity ON contact_history(entity_type, entity_id);
CREATE INDEX idx_contact_history_created_at ON contact_history(created_at);

-- Event outbox indexes
CREATE INDEX idx_event_outbox_unprocessed ON event_outbox(processed_at) WHERE processed_at IS NULL;
CREATE INDEX idx_event_outbox_aggregate ON event_outbox(aggregate_type, aggregate_id);
CREATE INDEX idx_event_outbox_occurred_at ON event_outbox(occurred_at);
CREATE INDEX idx_event_outbox_retry_count ON event_outbox(retry_count) WHERE processed_at IS NULL;
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

### Journal System (Iteration 3+)
See [Journal System Specification](../journal-system-specification.md) for complete database schema including:
- Base `journals` table with title, content, event_date_range, parent_id, order
- Type-specific data tables (15 types):
  - Base types: `journal_calendar_info`, `journal_mood_data`, `journal_plan_data`, `journal_travel_data`, `journal_photo_album_data`
  - Activity types: `journal_fitness_data`, `journal_outdoor_activity_data`, `journal_bushwalking_data`, `journal_abseiling_data`, `journal_canyoning_data`, `journal_climbing_data`, `journal_kayaking_data`, `journal_skiing_data`, `journal_jogging_data`
- Supporting tables: `routes`, `journal_tags`, `journal_contacts`, `journal_events`
- Proper foreign key constraints and indexes for search/filtering
- Template system: `activity_templates` (UUID pk, user-owned, type-specific columns for canyoning/caving/climbing), `template_pitches` (FK to activity_templates, cascade delete, unique template_id+pitch_number)

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

## MeiliSearch Integration

### Search Engine Architecture
MeiliSearch runs as a separate Docker container and provides fast, typo-tolerant search across all entities. Data is synchronized from PostgreSQL using the transactional outbox pattern.

### Search Indexes Structure
```javascript
// Contacts Index (contacts_index)
{
  "id": 1,
  "first_name": "John",
  "last_name": "Smith",
  "full_name": "John Smith",
  "email": "john.smith@example.com",
  "phone": "+61 400 123 456",
  "tags": ["work", "client"],
  "notes_content": "Important client for project X",
  "entity_type": "contact",
  "created_at": "2024-01-01T10:00:00Z",
  "updated_at": "2024-01-01T10:00:00Z"
}

// Global Search Index (global_search_index)
{
  "id": "contact_1",
  "title": "John Smith",
  "content": "john.smith@example.com +61 400 123 456 Important client",
  "entity_type": "contact",
  "entity_id": 1,
  "tags": ["work", "client"],
  "created_at": "2024-01-01T10:00:00Z"
}
```

### Event-Driven Synchronization
1. **Domain Event**: Contact created/updated/deleted
2. **Outbox Storage**: Event stored in `event_outbox` table within same transaction
3. **Background Processing**: FastAPI background task polls outbox every 10 seconds
4. **MeiliSearch Update**: Index updated based on event type
5. **Mark Processed**: Event marked as processed in outbox

### Search Configuration
```python
# MeiliSearch index settings
CONTACT_INDEX_SETTINGS = {
    "searchableAttributes": [
        "first_name",
        "last_name",
        "full_name",
        "email",
        "phone",
        "notes_content"
    ],
    "filterableAttributes": [
        "tags",
        "entity_type",
        "created_at"
    ],
    "sortableAttributes": [
        "created_at",
        "updated_at",
        "last_name"
    ]
}
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
# Example migration for contacts domain tables
"""Create contacts domain tables

Revision ID: 001_create_contacts_domain
Revises:
Create Date: 2024-01-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # Create contacts table
    op.create_table('contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.VARCHAR(length=100), nullable=False),
        sa.Column('last_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('middle_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('nick_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create tags table
    op.create_table('tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.VARCHAR(length=100), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('color', sa.VARCHAR(length=7), nullable=True),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['tags.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.CheckConstraint("name ~ '^[a-zA-Z0-9_&-]+$'", name='tag_name_format')
    )

    # Create contact_methods table
    op.create_table('contact_methods',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('method_type', sa.VARCHAR(length=20), nullable=False),
        sa.Column('value', sa.TEXT(), nullable=False),
        sa.Column('label', sa.VARCHAR(length=50), nullable=True),
        sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("method_type IN ('email', 'phone')", name='valid_method_type'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create contact_addresses table
    op.create_table('contact_addresses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.VARCHAR(length=50), nullable=True),
        sa.Column('street_line_1', sa.VARCHAR(length=255), nullable=False),
        sa.Column('street_line_2', sa.VARCHAR(length=255), nullable=True),
        sa.Column('locality', sa.VARCHAR(length=100), nullable=True),
        sa.Column('region', sa.VARCHAR(length=100), nullable=True),
        sa.Column('postal_code', sa.VARCHAR(length=20), nullable=True),
        sa.Column('country_code', sa.VARCHAR(length=2), nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create unique constraint for primary methods
    op.create_index('idx_contact_methods_unique_primary', 'contact_methods',
                   ['contact_id', 'method_type'], unique=True,
                   postgresql_where=sa.text('is_primary = true'))

    # Create unique constraint for primary addresses
    op.create_index('idx_contact_addresses_unique_primary', 'contact_addresses',
                   ['contact_id'], unique=True,
                   postgresql_where=sa.text('is_primary = true'))

    # Create contact_notes table
    op.create_table('contact_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.TEXT(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create contact_tags junction table
    op.create_table('contact_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('contact_id', 'tag_id')
    )

    # Create contact_history table
    op.create_table('contact_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('entity_type', sa.VARCHAR(length=50), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.VARCHAR(length=20), nullable=False),
        sa.Column('field_name', sa.VARCHAR(length=100), nullable=True),
        sa.Column('old_value', sa.TEXT(), nullable=True),
        sa.Column('new_value', sa.TEXT(), nullable=True),
        sa.Column('changed_by', sa.VARCHAR(length=100), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("action IN ('created', 'updated', 'deleted')", name='valid_action'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create all indexes (see database design document for complete list)
    # Contact indexes
    op.create_index('idx_contacts_first_name', 'contacts',
                   [sa.text("to_tsvector('english', first_name)")], postgresql_using='gin')
    op.create_index('idx_contacts_last_name', 'contacts',
                   [sa.text("to_tsvector('english', last_name)")], postgresql_using='gin')

def downgrade():
    op.drop_table('contact_history')
    op.drop_table('contact_tags')
    op.drop_table('contact_notes')
    op.drop_table('contact_addresses')
    op.drop_table('contact_methods')
    op.drop_table('tags')
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
# Abstract repository interfaces
from abc import ABC, abstractmethod
from typing import List, Optional

class ContactRepository(ABC):
    @abstractmethod
    async def find_by_id(self, contact_id: int) -> Optional[Contact]:
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
    async def delete(self, contact_id: int) -> None:
        pass

    @abstractmethod
    async def get_contacts_by_tag(self, tag_id: int) -> List[Contact]:
        pass

class TagRepository(ABC):
    @abstractmethod
    async def find_by_id(self, tag_id: int) -> Optional[Tag]:
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> Optional[Tag]:
        pass

    @abstractmethod
    async def get_all(self) -> List[Tag]:
        pass

    @abstractmethod
    async def get_children(self, parent_id: int) -> List[Tag]:
        pass

    @abstractmethod
    async def save(self, tag: Tag) -> Tag:
        pass

    @abstractmethod
    async def delete(self, tag_id: int) -> None:
        pass

class ContactHistoryRepository(ABC):
    @abstractmethod
    async def get_contact_history(self, contact_id: int) -> List[ContactHistoryEntry]:
        pass

    @abstractmethod
    async def record_change(self, entry: ContactHistoryEntry) -> ContactHistoryEntry:
        pass
```

### SQLAlchemy Core Implementation

- **Connection Injection**: Repositories receive AsyncConnection in constructor
- **Explicit Queries**: Use SQLAlchemy text() with parameterized queries
- **Complex Joins**: Handle contact aggregates with LEFT JOINs for methods, notes, tags
- **Transaction Management**: Handled at service layer, repositories use provided connection
- **Type Safety**: Return domain models, not database rows

_See [Domain Architecture](./domain-architecture.md) for detailed repository patterns and examples._

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
