# Domain Architecture - Personal CRM & Journal System

This document provides detailed information about the domain-driven architecture, component design, and project structure.

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
  - Calendar views
  - Photo associations with links to Immich
  - Analytics and insights
  - Contact Editor

### 2. API Adapters (Driving Adapters)

#### MCP Server Adapter
- **Framework**: `@modelcontextprotocol/sdk` with Streamable HTTP Transport
- **Architecture Role**: Driving adapter that calls into domain use cases
- **Transport**: HTTP-based for web-compatible AI client integration
- **Responsibilities**:
  - Tool registration and execution via MCP SDK
  - Resource management and caching
  - HTTP-based authentication and session management
  - Request/response formatting per MCP specification
  - Dependency injection into domain services
  - Connection management for multiple AI clients

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
  - Photo & album association rules

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
  - Association management
- **SqlPersonMatchRepository**: Implements PersonMatchRepository port
  - Person match storage against immich's api
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

## Project Structure

### Domain-Driven Architecture with Integration Sub-Domains
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

## Key Architectural Principles

1. **Domain Isolation**: Each domain is self-contained with its own entities, services, and adapters
2. **Dependency Inversion**: Domains define ports (interfaces), adapters implement them
3. **Single Responsibility**: Each adapter has a single, well-defined responsibility
4. **Cross-Domain Operations**: Handled explicitly in the sync domain
5. **API Separation**: REST and MCP adapters are separate from domain logic

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Database Design](./database-design.md) - Detailed database schema and data layer
- [Technology Stack](./technology-stack.md) - Technology choices and implementation details
- [Deployment Guide](./deployment-guide.md) - Infrastructure and deployment configuration
