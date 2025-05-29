# Personal CRM & Journal System - Architecture

## System Overview

The Personal CRM & Journal System is a TypeScript/Node.js application designed to centralize personal relationship management and journaling with intelligent AI integration through the MCP (Model Context Protocol).

### Core Objectives
- **Unified Personal Data**: Centralize contacts, calendar events, journal entries, and photos
- **AI Integration**: Provide rich context to AI assistants through MCP protocol
- **Multi-Interface**: Support both programmatic (MCP) and human (web) interfaces
- **Privacy-First**: Local SQLite storage with controlled external integrations
- **Standard Protocols**: JSON API for REST, CardDAV/CalDAV for interoperability
- **Smart Album Integration**: Link Immich albums to journal entries and events
- **Name-Based Matching**: Link contacts to Immich people by name or manual confirmation
- **Standardized Integrations**: Integration sub-domains with clear boundaries
- **Agile Development**: Feature-complete iterations delivering incremental value
- **Proxy-Ready**: Support deployment behind nginx reverse proxy

## High-Level Architecture (Domain-Driven with Integration Sub-Domains)

```
                    ┌─────────────────────────────────────┐
                    │           Client Interfaces         │
                    │  ┌─────────────┐ ┌─────────────────┐ │
                    │  │MCP Protocol │ │  Web Interface  │ │
                    │  │(AI Clients) │ │ (React/Next.js) │ │
                    │  └─────────────┘ └─────────────────┘ │
                    └─────────────────┬───────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                  API Adapters                │
              │  ┌─────────────────┐ │ ┌─────────────────────┐ │
              │  │   MCP Server    │ │ │   REST API Server   │ │
              │  │   Adapter       │ │ │     Adapter         │ │
              │  │                 │ │ │   (Nginx Proxy      │ │
              │  │                 │ │ │    Compatible)      │ │
              │  └─────────────────┘ │ └─────────────────────┘ │
              └─────────────────────┬┴─────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                     Core Domain Layer                           │
    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐  │
    │  │  Contacts   │ │  Calendar   │ │   Journal   │ │  Photos   │  │
    │  │   Domain    │ │   Domain    │ │   Domain    │ │  Domain   │  │
    │  │             │ │             │ │             │ │           │  │
    │  │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │┌────────┐ │  │
    │  │ │Business │ │ │ │Business │ │ │ │Business │ │ ││Business│ │  │
    │  │ │ Logic   │ │ │ │ Logic   │ │ │ │ Logic   │ │ ││ Logic  │ │  │
    │  │ │+ Tags   │ │ │ │+ Albums │ │ │ │+ Albums │ │ ││+ Albums│ │  │
    │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │└────────┘ │  │
    │  │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │┌────────┐ │  │
    │  │ │Adapters │ │ │ │Adapters │ │ │ │Adapters │ │ ││Adapters│ │  │
    │  │ │(SQL,etc)│ │ │ │(SQL,etc)│ │ │ │(SQL,etc)│ │ ││(SQL,etc)││ │
    │  │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │└────────┘ │  │
    │  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘  │
    └─────────────────────────────────────────────────────────────────┘
                                    │
    ┌─────────────────────────────────────────────────────────────────┐
    │                  Integration Sub-Domains                        │
    │  ┌─────────────────┐              ┌─────────────────────────────┐ │
    │  │     Google      │              │          Immich             │ │
    │  │   Integration   │              │       Integration           │ │
    │  │                 │              │                             │ │
    │  │ ┌─────────────┐ │              │ ┌─────────────────────────┐ │ │
    │  │ │Sync Logic   │ │              │ │Album & Person Logic     │ │ │
    │  │ │Tag Sync     │ │              │ │Name-Based Matching      │ │ │
    │  │ │Contact Sync │ │              │ │Auto Contact Linking     │ │ │
    │  │ │Calendar Sync│ │              │ │Journal/Event Albums     │ │ │
    │  │ └─────────────┘ │              │ └─────────────────────────┘ │ │
    │  │ ┌─────────────┐ │              │ ┌─────────────────────────┐ │ │
    │  │ │Adapters     │ │              │ │Adapters                 │ │ │
    │  │ │Google APIs  │ │              │ │Immich Client            │ │ │
    │  │ │Sync State   │ │              │ │Sync State               │ │ │
    │  │ └─────────────┘ │              │ └─────────────────────────┘ │ │
    │  └─────────────────┘              └─────────────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
                                    │
                    ┌─────────────────────────────────────┐
                    │         Infrastructure              │
                    │  ┌─────────────────────────────────┐ │
                    │  │        SQLite Database          │ │
                    │  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌────┐ │ │
                    │  │  │Core │ │Sync │ │Tags │ │Alb.│ │ │
                    │  │  │Data │ │State│ │     │ │    │ │ │
                    │  │  └─────┘ └─────┘ └─────┘ └────┘ │ │
                    │  └─────────────────────────────────┘ │
                    └─────────────────────────────────────┘
```

## Component Details

### 1. Client Interfaces

#### MCP Protocol Interface
- **Purpose**: Provide AI assistants with structured access to personal data
- **Implementation**: Custom MCP server with defined tools and resources
- **Key Features**:
  - Contact search and management tools
  - Journal entry creation and retrieval
  - Calendar event access
  - Photo association and search
  - Relationship analysis and insights

#### Web Interface
- **Technology**: React with Next.js or Vite
- **Purpose**: Human-friendly interface for data management
- **Key Features**:
  - Contact management dashboard
  - Rich text journal editor
  - Calendar integration views
  - Photo gallery and associations
  - Analytics and insights

### 2. API Adapters (Driving Adapters)

#### MCP Server Adapter
- **Framework**: Custom implementation following MCP specification
- **Architecture Role**: Driving adapter that calls into domain use cases
- **Responsibilities**:
  - Tool registration and execution
  - Resource management
  - Authentication and authorization
  - Request/response formatting
  - Dependency injection into domain services

#### REST API Server Adapter
- **Framework**: Express.js or Fastify
- **Standard**: JSON API specification compliance
- **Architecture Role**: Driving adapter that calls into domain use cases
- **Responsibilities**:
  - HTTP request handling
  - JSON API response formatting
  - Authentication middleware
  - Input validation and sanitization
  - Rate limiting
  - Error handling per JSON API spec
  - Dependency injection into domain services

### 3. Domain Layer (Hexagonal Core)

#### Domain Structure
Each domain follows the same internal structure:
```
domain/
├── entities/          # Domain entities (Contact, Event, etc.)
├── value-objects/     # Value objects (Email, PhoneNumber, etc.)
├── services/          # Domain services (business logic)
├── events/           # Domain events
└── ports/            # Interfaces for external dependencies
```

#### Contacts Domain
- **Entities**: Contact, ContactInteraction
- **Value Objects**: Email, PhoneNumber, Address
- **Domain Services**: ContactDuplicationService, RelationshipService
- **Ports**: ContactRepository, GoogleContactsService, ContactEventPublisher
- **Business Rules**:
  - Contact uniqueness validation
  - Relationship mapping logic
  - Interaction tracking rules
  - Privacy and consent management

#### Calendar Domain
- **Entities**: Event, Reminder
- **Value Objects**: DateTime, Duration, Location
- **Domain Services**: ConflictDetectionService, MeetingPreparationService
- **Ports**: EventRepository, GoogleCalendarService, EventEventPublisher
- **Business Rules**:
  - Event conflict detection
  - Recurring event logic
  - Time zone handling
  - Meeting preparation workflows

#### Journal Domain
- **Entities**: JournalEntry, Tag
- **Value Objects**: Mood, Sentiment
- **Domain Services**: SentimentAnalysisService, TaggingService
- **Ports**: JournalRepository, SentimentAnalysisService, JournalEventPublisher
- **Business Rules**:
  - Entry privacy controls
  - Mood tracking logic
  - Tag categorization
  - Search and filtering rules

#### Photos Domain
- **Entities**: Photo, ImmichPerson, PersonMatch
- **Value Objects**: ConfidenceScore, MatchMethod
- **Domain Services**: PersonMatchingService, PhotoAssociationService
- **Ports**: PhotoRepository, ImmichService, PersonMatchRepository
- **Business Rules**:
  - Person matching algorithms
  - Confidence scoring logic
  - Photo association rules
  - Privacy and consent for facial recognition

#### Sync Domain (Cross-Domain Operations)
- **Purpose**: Handle operations that span multiple domains
- **Components**: TransactionCoordinator, EventBus, CrossDomainUseCases
- **Responsibilities**:
  - Coordinate multi-domain transactions
  - Publish and handle domain events
  - Manage eventual consistency
  - Handle complex workflows (e.g., Google sync that affects both contacts and calendar)

### 4. Adapter Layer (Driven Adapters)

#### Adapter Structure
Each domain has its own adapters that implement the ports defined by the domain:
```
domain/adapters/
├── sql/              # Database adapters
├── http/             # External API adapters
├── events/           # Event publishing adapters
└── cache/            # Caching adapters (optional)
```

#### Contacts Domain Adapters
- **SqlContactRepository**: Implements ContactRepository port
  - Drizzle ORM or Prisma for type-safe database operations
  - Connection pooling and transaction management
  - Query optimization with proper indexing
  - OpenTelemetry instrumentation for database spans
- **GoogleContactsAdapter**: Implements GoogleContactsService port
  - Official `googleapis` library with People API v1
  - OAuth 2.0 authentication with token refresh
  - Incremental sync with conflict resolution
  - Built-in rate limiting and retry logic
  - OpenTelemetry spans for external API calls
- **ContactEventPublisher**: Implements ContactEventPublisher port
  - Domain event publishing with correlation IDs
  - Event serialization and structured logging

#### Calendar Domain Adapters
- **SqlEventRepository**: Implements EventRepository port
  - Drizzle ORM with optimized queries for time-based data
  - Recurring event handling with proper indexing
  - Time zone management and conversion
  - OpenTelemetry spans for complex queries
- **GoogleCalendarAdapter**: Implements GoogleCalendarService port
  - Official `googleapis` library with Calendar API v3
  - OAuth 2.0 authentication with scope management
  - Real-time sync with webhook support
  - Multi-calendar support with batch operations
  - Conflict resolution strategies with proper error handling
  - OpenTelemetry tracing for sync operations
- **EventEventPublisher**: Implements EventEventPublisher port
  - Calendar event publishing with structured metadata
  - Cross-domain integration events

#### Journal Domain Adapters
- **SqlJournalRepository**: Implements JournalRepository port
  - Journal entry persistence
  - Full-text search capabilities
  - Tag management
- **JournalEventPublisher**: Implements JournalEventPublisher port
  - Journal event publishing
  - Mood tracking events

#### Photos Domain Adapters
- **SqlPhotoRepository**: Implements PhotoRepository port
  - Photo metadata storage
  - Association management
- **SqlPersonMatchRepository**: Implements PersonMatchRepository port
  - Person match storage
  - Confidence score tracking
- **ImmichHttpAdapter**: Implements ImmichService port
  - API key or session-based authentication
  - Photo metadata, thumbnails, search
  - Person recognition data retrieval
  - Privacy controls and permissions
  - Lazy loading and caching

#### Cross-Domain Adapters (Sync Domain)
- **TransactionCoordinator**: Manages distributed transactions
  - SQLite transaction coordination
  - Rollback strategies
  - Consistency guarantees
- **EventBus**: Handles domain event distribution
  - In-memory event bus (simple implementation)
  - Event ordering and delivery guarantees
  - Error handling and retry logic

### 5. Project Structure

#### Domain-Driven Architecture with Integration Sub-Domains
```
src/
├── api/                          # API Adapters (Driving)
│   ├── rest/                     # REST API adapters (nginx proxy compatible)
│   │   ├── contacts/             # Contact REST endpoints
│   │   ├── calendar/             # Calendar REST endpoints
│   │   ├── journal/              # Journal REST endpoints
│   │   ├── photos/               # Photos REST endpoints
│   │   └── shared/               # Shared REST utilities, proxy config
│   └── mcp/                      # MCP adapters
│       ├── contacts/             # Contact MCP tools
│       ├── calendar/             # Calendar MCP tools
│       ├── journal/              # Journal MCP tools
│       ├── photos/               # Photos MCP tools
│       └── server.ts             # MCP server setup
├── contacts/                     # Contacts Core Domain
│   ├── domain/                   # Domain layer
│   │   ├── entities/             # Contact, ContactInteraction, Tag
│   │   ├── value-objects/        # Email, PhoneNumber, Address
│   │   ├── services/             # ContactDuplicationService, TagService
│   │   └── events/               # ContactCreated, TagAssigned, etc.
│   ├── adapters/                 # All external dependencies
│   │   ├── sql/                  # SqlContactRepository, SqlTagRepository
│   │   └── events/               # ContactEventPublisher
│   └── application/              # Use cases and application services
│       ├── use-cases/            # CreateContact, AssignTag, etc.
│       └── ContactApplicationService.ts
├── calendar/                     # Calendar Core Domain
│   ├── domain/
│   │   ├── entities/             # Event, Reminder, Album (reference)
│   │   ├── value-objects/        # DateTime, Duration, Location
│   │   ├── services/             # ConflictDetectionService, AlbumLinkService
│   │   └── events/               # EventCreated, AlbumLinked, etc.
│   ├── adapters/
│   │   ├── sql/                  # SqlEventRepository
│   │   └── events/               # EventEventPublisher
│   └── application/
│       ├── use-cases/            # CreateEvent, LinkToAlbum, etc.
│       └── CalendarApplicationService.ts
├── journal/                      # Journal Core Domain
│   ├── domain/
│   │   ├── entities/             # JournalEntry, Album (reference)
│   │   ├── value-objects/        # Mood, Sentiment
│   │   ├── services/             # SentimentAnalysisService, AlbumLinkService
│   │   └── events/               # JournalEntryCreated, AlbumLinked, etc.
│   ├── adapters/
│   │   ├── sql/                  # SqlJournalRepository
│   │   └── events/               # JournalEventPublisher
│   └── application/
│       ├── use-cases/            # CreateJournalEntry, LinkToAlbum, etc.
│       └── JournalApplicationService.ts
├── photos/                       # Photos Core Domain
│   ├── domain/
│   │   ├── entities/             # Photo, Album, Person
│   │   ├── value-objects/        # AlbumId, PersonName
│   │   ├── services/             # AlbumService, PersonService
│   │   └── events/               # AlbumCreated, PersonLinked, etc.
│   ├── adapters/
│   │   ├── sql/                  # SqlPhotoRepository, SqlAlbumRepository
│   │   └── events/               # PhotoEventPublisher
│   └── application/
│       ├── use-cases/            # CreateAlbum, LinkPerson, etc.
│       └── PhotoApplicationService.ts
├── google-integration/           # Google Integration Sub-Domain
│   ├── domain/
│   │   ├── entities/             # GoogleSyncState, GoogleContact, GoogleEvent
│   │   ├── services/             # GoogleSyncService, TagSyncService
│   │   └── events/               # GoogleSyncCompleted, TagSynced, etc.
│   ├── adapters/
│   │   ├── google-api/           # GoogleContactsClient, GoogleCalendarClient
│   │   ├── sql/                  # GoogleSyncStateRepository
│   │   └── events/               # GoogleEventPublisher
│   └── application/
│       ├── use-cases/            # SyncGoogleContacts, SyncTags, etc.
│       └── GoogleIntegrationService.ts
├── immich-integration/           # Immich Integration Sub-Domain
│   ├── domain/
│   │   ├── entities/             # ImmichAlbum, ImmichPerson, PersonMatch
│   │   ├── services/             # NameMatchingService, AlbumSyncService
│   │   └── events/               # AlbumSynced, PersonMatched, etc.
│   ├── adapters/
│   │   ├── immich-api/           # ImmichClient
│   │   ├── sql/                  # ImmichSyncStateRepository
│   │   └── events/               # ImmichEventPublisher
│   └── application/
│       ├── use-cases/            # SyncAlbums, MatchPersonsByName, etc.
│       └── ImmichIntegrationService.ts
└── shared/                       # Shared Infrastructure
    ├── database/                 # Database connection, migrations
    ├── events/                   # Event infrastructure
    ├── types/                    # Shared types and interfaces
    ├── utils/                    # Utility functions
    ├── config/                   # Configuration management
    └── proxy/                    # Nginx proxy utilities and middleware
```

#### Key Architectural Principles
1. **Domain Isolation**: Each domain is self-contained with its own entities, services, and adapters
2. **Dependency Inversion**: Domains define ports (interfaces), adapters implement them
3. **Single Responsibility**: Each adapter has a single, well-defined responsibility
4. **Cross-Domain Operations**: Handled explicitly in the sync domain
5. **API Separation**: REST and MCP adapters are separate from domain logic

### 6. Data Layer

#### SQLite Database Schema

```sql
-- Contacts table
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

-- Tags table
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Contact tags many-to-many relationship
CREATE TABLE contact_tags (
    contact_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (contact_id, tag_id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);

-- Events table
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

-- Journal entries table
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

-- Photos table (metadata only)
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

-- Albums table (from Immich)
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

-- Immich persons table (name-based only)
CREATE TABLE immich_persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    immich_person_id TEXT UNIQUE NOT NULL,
    name TEXT,
    thumbnail_path TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Person to contact matching table (name-based and manual only)
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

-- Google integration sync state
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

-- Immich integration sync state
CREATE TABLE immich_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'album', 'person', 'photo'
    local_id TEXT NOT NULL,
    immich_id TEXT NOT NULL,
    last_synced DATETIME DEFAULT CURRENT_TIMESTAMP,
    sync_status TEXT DEFAULT 'synced', -- 'synced', 'pending', 'error'
    UNIQUE(entity_type, local_id)
);

-- Contact interactions table
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

## Technology Stack

### Backend
- **Runtime**: Node.js 18+
- **Language**: TypeScript 5+ with strict mode
- **Database**: SQLite with Drizzle ORM or Prisma
- **Web Framework**: Express.js or Fastify
- **API Standard**: JSON API specification
- **API Documentation**: tsoa or @nestjs/swagger for automatic OpenAPI generation
- **Authentication**: OAuth 2.0 (Google), JWT for sessions
- **Validation**: Zod for runtime validation and schema generation
- **Logging**: Winston with structured logging
- **Observability**: OpenTelemetry for tracing, metrics, and correlation
- **Testing**: Jest with TypeScript support and coverage reporting
- **Code Quality**: ESLint with strict rules, Prettier, and architectural linting

### Frontend
- **Framework**: React 18+ with Next.js or Vite
- **Language**: TypeScript
- **Styling**: Tailwind CSS or Styled Components
- **State Management**: Zustand or Redux Toolkit
- **Forms**: React Hook Form
- **UI Components**: Radix UI or Chakra UI

### External APIs & Libraries
- **Google APIs**: Official `googleapis` npm package with TypeScript support
- **Google Calendar API**: v3 via googleapis
- **Google Contacts API**: People API v1 via googleapis
- **Immich API**: Official SDK or typed HTTP client
- **MCP Protocol**: Latest specification
- **Database ORM**: Drizzle ORM (lightweight) or Prisma (feature-rich)
- **HTTP Client**: Axios with interceptors for observability
- **Observability**: OpenTelemetry auto-instrumentation packages

## Security Considerations

### Authentication & Authorization
- OAuth 2.0 for Google services
- JWT tokens for session management
- API key authentication for MCP
- Role-based access control

### Data Protection
- Encryption at rest for sensitive data
- HTTPS for all communications
- Input validation and sanitization
- SQL injection prevention
- XSS protection

### Privacy
- Local data storage (SQLite)
- Minimal data collection
- User consent for external syncing
- Data export/deletion capabilities
- GDPR compliance features

## Performance Considerations

### Database Optimization
- Proper indexing strategy
- Query optimization
- Connection pooling
- Prepared statements

### Caching Strategy
- In-memory caching for frequently accessed data
- Redis for distributed caching (if needed)
- HTTP caching headers
- Image thumbnail caching

### Scalability
- Horizontal scaling capability
- Database sharding considerations
- CDN for static assets
- Load balancing for multiple instances

## Deployment Architecture

### Development Environment
- Local SQLite database
- Environment-based configuration
- Hot reloading for development
- Mock external services for testing
- Docker Compose for consistent development setup

### Production Environment
- **Reverse Proxy**: Nginx proxy handling SSL termination and load balancing
- **Containerized Deployment**: Docker containers with multi-stage builds
- **Orchestration**: Docker Compose or Kubernetes
- **Database**: SQLite with persistent volume mounts
- **Configuration**: Environment variables and secrets management
- **Health Checks**: Built-in health endpoints accessible through proxy
- **Monitoring**: Prometheus metrics and log aggregation
- **Backup**: Automated SQLite backup to external storage
- **CI/CD**: GitHub Actions or similar for automated deployment

### Nginx Proxy Integration
- **Proxy Headers**: Application trusts X-Forwarded-For, X-Forwarded-Proto headers
- **Real Client IPs**: Logging and rate limiting use actual client IPs
- **CORS Configuration**: Proper handling of preflight requests through proxy
- **Health Checks**: /health endpoint accessible through proxy path
- **WebSocket Support**: If needed for real-time features
- **SSL Termination**: Nginx handles SSL, app receives HTTP
- **Static Assets**: Nginx can serve static files directly
- **Rate Limiting**: Can be implemented at both nginx and app level

### Docker Configuration

#### Multi-Stage Dockerfile
```dockerfile
# Build stage
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

# Runtime stage
FROM node:18-alpine AS runtime
WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY . .
RUN npm run build

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

EXPOSE 3000
CMD ["npm", "start"]
```

#### Docker Compose Structure
- **Development**: `docker-compose.yml` with hot reloading and development tools
- **Production**: `docker-compose.prod.yml` with optimized settings and monitoring
- **Services**: Application, database volume, reverse proxy (optional)
- **Networks**: Isolated network for service communication
- **Volumes**: Persistent storage for SQLite database and logs

#### Container Features
- **Multi-architecture support**: AMD64 and ARM64 builds
- **Security**: Non-root user, minimal attack surface
- **Performance**: Optimized layer caching and minimal image size
- **Observability**: Structured logging and metrics endpoints

## Observability & Monitoring

### OpenTelemetry Integration
- **Automatic Instrumentation**: HTTP requests, database queries, external API calls
- **Custom Spans**: Domain operations, business workflows, cross-domain transactions
- **Trace Correlation**: Request flow through all architectural layers
- **Metrics Collection**: Business metrics, performance metrics, error rates
- **Export Targets**: Jaeger (tracing), Prometheus (metrics), structured logs

### Tracing Flow Through Architecture
```
HTTP Request → API Adapter → Application Service → Domain Service → Repository Adapter
     ↓              ↓              ↓               ↓              ↓
  Trace ID    Use Case Span   Business Span   Domain Span   Database Span
```

### Logging Strategy
- **Structured Logging**: JSON format with correlation IDs
- **Log Levels**: error, warn, info, debug with appropriate filtering
- **Correlation**: Trace IDs linking logs across all components
- **Context**: Domain context, user context, operation context
- **Performance**: Query execution times, external API latency

### Metrics Collection
- **API Metrics**: Response times, error rates, request counts per endpoint
- **Business Metrics**: Contacts created, sync operations, journal entries
- **Domain Metrics**: Cross-domain operations, event processing rates
- **Infrastructure Metrics**: Database performance, memory usage, connection pools
- **External Service Metrics**: Google API call rates, Immich response times

### Health Checks & Monitoring
- **Application Health**: /health endpoint with detailed component status
- **Database Health**: Connection status, query performance, disk usage
- **External Service Health**: Google API availability, Immich connectivity
- **Domain Health**: Sync status, event processing lag, error rates
- **Alerting**: Critical error thresholds, performance degradation alerts

## Future Considerations

### Extensibility
- Plugin architecture for new integrations
- Custom field support
- Webhook system for external notifications
- API versioning strategy

### Protocol Extensions
- **CardDAV Server**: Contact synchronization with standard clients
- **CalDAV Server**: Calendar synchronization with standard clients
- **vCard/iCal Support**: Standard format conversion and compatibility
- **WebDAV Foundation**: Base protocol for CardDAV/CalDAV implementation

### Home Automation Integration
- **Home Assistant**: Custom component for automation
- **Presence Detection**: Contact-based presence sensors
- **Calendar Automation**: Event-triggered smart home actions

### Advanced Features
- Machine learning for relationship insights
- Natural language processing for journal analysis
- Advanced search with full-text indexing
- Mobile application support
- Multi-user support with data isolation
- Facial recognition improvements
- Contact relationship mapping
- Automated contact categorization
