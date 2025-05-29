# Database Design - Personal CRM & Journal System

This document details the database schema, data relationships, and data layer implementation for the Personal CRM & Journal System.

## SQLite Database Schema

### Core Data Tables

#### Contacts Table
```sql
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    company TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);
```

#### Tags Table
```sql
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Contact Tags Relationship
```sql
CREATE TABLE contact_tags (
    contact_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (contact_id, tag_id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);
```

#### Events Table
```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    location TEXT,
    attendees TEXT, -- JSON array
    linked_album_id TEXT, -- Reference to Immich album
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);
```

#### Journal Entries Table
```sql
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    content TEXT NOT NULL,
    mood INTEGER, -- 1-10 scale
    related_contacts TEXT, -- JSON array of contact IDs
    related_events TEXT, -- JSON array of event IDs
    linked_album_id TEXT, -- Reference to Immich album
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE
);
```

### Photo and Album Tables

#### Photos Table (Metadata Only)
```sql
CREATE TABLE photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    immich_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    taken_at DATETIME,
    related_contacts TEXT, -- JSON array of contact IDs
    related_events TEXT, -- JSON array of event IDs
    tags TEXT, -- JSON array
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Albums Table (From Immich)
```sql
CREATE TABLE albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    immich_album_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    thumbnail_path TEXT,
    photo_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Immich Persons Table (Name-Based Only)
```sql
CREATE TABLE immich_persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    immich_person_id TEXT UNIQUE NOT NULL,
    name TEXT,
    thumbnail_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

#### Person to Contact Matching Table
```sql
CREATE TABLE person_contact_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    immich_person_id INTEGER NOT NULL,
    contact_id INTEGER NOT NULL,
    match_method TEXT NOT NULL, -- 'manual', 'name'
    confidence_score REAL, -- 0.0 to 1.0 for name matching
    verified BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (immich_person_id) REFERENCES immich_persons(id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    UNIQUE(immich_person_id, contact_id)
);
```

### Integration and Sync Tables

#### Google Integration Sync State
```sql
CREATE TABLE google_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'contact', 'event', 'tag'
    local_id TEXT NOT NULL,
    google_id TEXT NOT NULL,
    etag TEXT,
    last_synced DATETIME DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'synced', -- 'synced', 'pending', 'error'
    UNIQUE(entity_type, local_id)
);
```

#### Immich Integration Sync State
```sql
CREATE TABLE immich_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'album', 'person', 'photo'
    local_id TEXT NOT NULL,
    immich_id TEXT NOT NULL,
    last_synced DATETIME DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'synced', -- 'synced', 'pending', 'error'
    UNIQUE(entity_type, local_id)
);
```

#### Contact Interactions Table
```sql
CREATE TABLE contact_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL,
    interaction_type TEXT NOT NULL, -- email, call, meeting, etc.
    description TEXT,
    occurred_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (contact_id) REFERENCES contacts(id)
);
```

## Indexing Strategy

### Performance Indexes
```sql
-- Contact search optimization
CREATE INDEX idx_contacts_name ON contacts(name);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_phone ON contacts(phone);
CREATE INDEX idx_contacts_company ON contacts(company);

-- Event time-based queries
CREATE INDEX idx_events_start_time ON events(start_time);
CREATE INDEX idx_events_end_time ON events(end_time);
CREATE INDEX idx_events_date_range ON events(start_time, end_time);

-- Journal entry search
CREATE INDEX idx_journal_created_at ON journal_entries(created_at);
CREATE INDEX idx_journal_mood ON journal_entries(mood);

-- Photo metadata search
CREATE INDEX idx_photos_taken_at ON photos(taken_at);
CREATE INDEX idx_photos_immich_id ON photos(immich_id);

-- Sync state queries
CREATE INDEX idx_google_sync_entity_type ON google_sync_state(entity_type);
CREATE INDEX idx_google_sync_status ON google_sync_state(sync_status);
CREATE INDEX idx_immich_sync_entity_type ON immich_sync_state(entity_type);
CREATE INDEX idx_immich_sync_status ON immich_sync_state(sync_status);

-- Contact interactions
CREATE INDEX idx_interactions_contact_id ON contact_interactions(contact_id);
CREATE INDEX idx_interactions_occurred_at ON contact_interactions(occurred_at);
CREATE INDEX idx_interactions_type ON contact_interactions(interaction_type);
```

### Full-Text Search Indexes
```sql
-- Journal content search
CREATE VIRTUAL TABLE journal_fts USING fts5(
    title, content,
    content='journal_entries',
    content_rowid='id'
);

-- Contact search
CREATE VIRTUAL TABLE contacts_fts USING fts5(
    name, email, company, notes,
    content='contacts',
    content_rowid='id'
);
```

## Data Relationships

### Entity Relationships
- **Contacts** ↔ **Tags**: Many-to-many through `contact_tags`
- **Contacts** ↔ **Interactions**: One-to-many
- **Contacts** ↔ **Immich Persons**: Many-to-many through `person_contact_matches`
- **Events** → **Albums**: One-to-one via `linked_album_id`
- **Journal Entries** → **Albums**: One-to-one via `linked_album_id`
- **Photos** ↔ **Contacts**: Many-to-many via JSON arrays
- **Photos** ↔ **Events**: Many-to-many via JSON arrays

### JSON Field Structures

#### Event Attendees
```json
[
  {
    "email": "john@example.com",
    "name": "John Doe",
    "response": "accepted"
  }
]
```

#### Related Contacts/Events Arrays
```json
[123, 456, 789]  // Array of entity IDs
```

#### Photo Tags
```json
["family", "vacation", "birthday"]
```

## Data Layer Implementation

### Repository Pattern
Each domain implements repositories following the Repository pattern:

```typescript
interface ContactRepository {
  findById(id: number): Promise<Contact | null>;
  findByEmail(email: string): Promise<Contact | null>;
  search(query: string): Promise<Contact[]>;
  save(contact: Contact): Promise<Contact>;
  delete(id: number): Promise<void>;
}
```

### Transaction Management
- Use SQLite transactions for multi-table operations
- Implement transaction coordination for cross-domain operations
- Rollback strategies for failed operations

### Migration Strategy
- Version-controlled database migrations
- Forward and backward migration support
- Data preservation during schema changes
- Automated migration testing

## Performance Considerations

### Query Optimization
- Use prepared statements for repeated queries
- Implement query result caching where appropriate
- Optimize JOIN operations with proper indexing
- Use EXPLAIN QUERY PLAN for performance analysis

### Connection Management
- Connection pooling for concurrent access
- Proper connection lifecycle management
- Timeout and retry strategies
- Connection health monitoring

### Data Archival
- Soft delete strategy with `is_deleted` flags
- Periodic cleanup of old sync state records
- Archive old journal entries and interactions
- Maintain referential integrity during archival

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Domain Architecture](./domain-architecture.md) - How domains interact with the database
- [Technology Stack](./technology-stack.md) - ORM and database technology choices
- [Security & Performance](./security-performance.md) - Database security and optimization
