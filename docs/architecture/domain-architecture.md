# Domain Architecture - Personal CRM & Journal System

This document provides detailed information about the domain-driven architecture, component design, project structure, and implementation patterns.

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
- **Framework**: FastAPI with Python
- **Standard**: JSON API specification compliance
- **Architecture Role**: Driving adapter that calls into domain use cases
- **Authentication**: Session-based authentication with Starlette SessionMiddleware
- **Responsibilities**:
  - HTTP request handling with automatic OpenAPI documentation
  - JSON API response formatting
  - Session-based authentication middleware
  - Input validation with Pydantic models
  - Rate limiting and CORS configuration
  - Error handling per JSON API spec
  - Service factory functions for dependency injection

### 3. Domain Layer (Hexagonal Core)

#### Domain Structure
Each domain follows the same internal structure:
```
domain/
├── models/           # Domain models
├── events/           # Domain events
|── adpters/          # Interfaces for external dependencies
|   ├── sql/              # Database adapters
|   ├── http/             # External API adapters
|   ├── events/           # Event publishing adapters
|   └── cache/            # Caching adapters (optional)
```

#### Contacts Domain
- **Entities**: Contact, Tag, ContactMethod, ContactNote, ContactAddress
- **Value Objects**: Email, PhoneNumber, Address, TagName, CountryCode
- **Domain Services**: ContactValidationService, TagHierarchyService, ContactHistoryService, AddressValidationService
- **Ports**: ContactRepository, TagRepository, ContactHistoryRepository, ContactEventPublisher
- **Business Rules**:
  - Contact name validation (first_name required)
  - Email uniqueness validation
  - Tag naming constraints (alphanumeric, -, _, & only)
  - Maximum 25 tags per contact
  - Primary contact method enforcement (one primary per type)
  - Primary address enforcement (one primary per contact)
  - Address validation (street_line_1 and country_code required)
  - Country code validation (ISO 3166-1 alpha-2 format)
  - Contact history tracking for all changes
- **Domain Events**: ContactCreated, ContactUpdated, ContactDeleted, TagAssigned, TagRemoved, ContactMethodAdded, ContactNoteAdded, ContactAddressAdded

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
See [Journal System Specification](../journal-system-specification.md) for comprehensive domain design including:
- **Entities**: Journal (base), 15 journal types with type-specific data tables
- **Value Objects**: DateRange, Route, TypeDependencies
- **Domain Services**: JournalService, TypeManagementService, MergeService
- **Ports**: JournalRepository, RouteRepository, IntegrationWorkerInterface
- **Business Rules**:
  - Type system with automatic dependency resolution
  - Hierarchical organization (max 5 levels)
  - Contact relationship management (4 types)
  - Integration conflict resolution
  - Route tracking and reuse

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
Each domain has its own adapters that implement external infrastructure needs:
```
domain/adapters/
├── sql/              # Database adapters
├── http/             # External API adapters
├── events/           # Event publishing adapters
└── cache/            # Caching adapters (optional)
```

#### Contacts Domain Adapters
- **SqlContactRepository**: Implements ContactRepository port
  - SQLAlchemy Core with explicit SQL queries for type safety
  - Handles complex joins for contact methods, notes, and tags
  - Connection pooling and transaction management
  - Query optimization with proper indexing
  - OpenTelemetry instrumentation for database spans
- **SqlTagRepository**: Implements TagRepository port
  - Hierarchical tag management with parent-child relationships
  - Tag uniqueness enforcement and validation
  - Efficient queries for tag trees and contact associations
- **SqlContactHistoryRepository**: Implements ContactHistoryRepository port
  - Change tracking for all contact-related entities
  - Audit trail with field-level change detection
  - Integration with domain events for automatic history recording

- **OutboxEventPublisher**: Implements ContactEventPublisher port
  - Transactional outbox pattern for reliable event publishing
  - Event serialization to PostgreSQL outbox table
  - Integration with contact history for audit trails
- **SearchIndexer**: Handles MeiliSearch indexing
  - Event-driven indexing via outbox pattern
  - Background processing every 10 seconds
  - Search index management and optimization
  - Target <50ms search response times

#### Calendar Domain Adapters
- **SqlEventRepository**: Implements EventRepository port
  - Drizzle ORM with optimized queries for time-based data
  - Recurring event handling with proper indexing
  - Time zone management and conversion
  - OpenTelemetry spans for complex queries

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


#### Cross-Domain Adapters (Sync Domain)
- **TransactionCoordinator**: Manages distributed transactions
  - PostgreSQL transaction coordination
  - Rollback strategies
  - Consistency guarantees
- **EventBus**: Handles domain event distribution
  - In-memory event bus (simple implementation)
  - Event ordering and delivery guarantees
  - Error handling and retry logic

## Implementation Patterns

### Domain Layer Guidelines (Ports & Adapters)

- **Domain Entities**: Pure Python classes with business logic, no framework dependencies
- **Domain Components**: Business logic that doesn't belong to a single entity
- **Adapters**: Classes supply the domains infrastructure needs such as sql repositories
- **Value Objects**: Immutable objects representing domain concepts
- **Domain Events**: Pure Python classes representing business events
- **Domain Enums**: Python enums for fixed domain values with type safety
### Application Layer Guidelines

- **Use Cases**: Orchestrate domain operations, no business logic
- **Application Services**: Coordinate between domain and infrastructure
- **Command/Query Objects**: Simple data structures for input/output
- **Dependency Injection**: Inject ports (interfaces), not concrete implementations
- **Transaction Management**: Handle database transactions at this layer

### Infrastructure Layer Guidelines (Adapters)

- **Repository Adapters**: Implement domain-defined repository ports
- **API Adapters**: Implement external service ports (Google, Immich)
- **Database Adapters**: Use SQLAlchemy Core, implement repository interfaces
- **Framework Integration**: Pydantic models for FastAPI, not domain
- **Dependency Direction**: Infrastructure depends on domain ports, never reverse
- **Error Translation**: Convert infrastructure errors to domain exceptions

### Domain Enum Patterns

#### Enum Definition Guidelines

- **String Values**: Use string values for database compatibility
- **Descriptive Names**: Use clear, descriptive enum member names
- **String Conversion**: Implement `__str__()` method to return enum value
- **Domain Location**: Define enums in the same module as related entities

#### Example Enum Implementation

```python
from enum import Enum

class MethodType(Enum):
    """Enumeration for contact method types."""

    EMAIL = "email"
    PHONE = "phone"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
```

#### Repository Conversion Patterns

- **Writing to Database**: Convert enum to string using `.value` property
- **Reading from Database**: Convert string to enum using `EnumType(string_value)`
- **Error Handling**: Handle invalid enum values gracefully

#### Entity Validation Patterns

```python
def __post_init__(self) -> None:
    """Validate entity with enum."""
    if not isinstance(self.method_type, MethodType):
        raise ValueError(f"Invalid method type: {self.method_type}")

    # Type-safe business logic
    if self.method_type == MethodType.EMAIL:
        Email(self.value)  # Validate email format
    elif self.method_type == MethodType.PHONE:
        PhoneNumber(self.value)  # Validate phone format
```

### Validation Strategy (Layered)

- **Domain Layer**: Business rule validation in entities/domain services
- **Application Layer**: Use case validation and authorization
- **Infrastructure Layer**: Pydantic models for API input/output validation
- **Database Layer**: Database constraints as final safety net

### Integration Architecture

This system uses an **Isolated Worker Architecture** to manage integrations with external services. This pattern isolates each integration's dependencies and process space, preventing them from impacting the core application.

All integration logic, patterns, and implementation details are defined in the dedicated **[Integration Architecture document](./integration-architecture.md)**. This core domain remains decoupled from the specifics of any external service.

### Application Service Guidelines

- Keep application services focused on orchestration
- Validate input using Pydantic models
- Implement business rule validation
- Use database transactions for consistency
- Add comprehensive logging for operations
- Handle errors gracefully with meaningful messages
- Keep services stateless and testable

### Error Handling Guidelines

- Create custom exception classes for domain errors
- Use meaningful error messages for debugging
- Include context information in error messages
- Log errors with appropriate severity levels
- Handle exceptions at appropriate boundaries
- Return user-friendly error responses from APIs
- Use standard HTTP status codes for API errors

### Logging Guidelines

- Use Python standard library logging
- Include structured logging with context
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Include correlation IDs for request tracing
- Log business operations for audit trails
- Avoid logging sensitive information
- Use consistent log message formats

### Journal Review Stores (two distinct concepts)

The journal domain has **two separate review stores** that must not be conflated:

- **Merge review queue** (`journal_review_items` + `ReviewItemService`): pairwise *merge candidates* —
  suggestions that two journals may be duplicates, awaiting user resolve/dismiss/auto-merge.
- **Outdoor-activity review dismissals** (`outdoor_activity_dismissals` +
  `OutdoorActivityDismissalService`): whole-entry, journal-scoped dismissals for the Incomplete
  Outdoor Activities Review (ITER16-002). A dismissal excludes an outdoor activity journal from the
  incomplete list regardless of which rules it matches; it is reversible and records `provenance`
  (UI/MCP) per the activity-history convention. The dismissal service owns its commit via
  `@transactional`, following the standard service-layer transaction pattern. This store is
  deliberately **not** the merge queue — dismissing an incomplete-review entry has nothing to do with
  merge candidates.

## Key Architectural Principles

1. **Domain Isolation**: Each domain is self-contained with its own entities, services, and adapters
2. **Dependency Inversion**: Domains define ports (interfaces), adapters implement them
3. **Single Responsibility**: Each adapter has a single, well-defined responsibility
4. **Cross-Domain Operations**: Handled explicitly in the sync domain
5. **API Separation**: REST and MCP adapters are separate from domain logic

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and navigation
- [Database Design](./database-design.md) - Detailed database schema and data layer
- [API Design](./api-design.md) - REST and MCP API implementation patterns
- [Frontend Design](./frontend-design.md) - Component patterns and UI guidelines
- [Testing Strategy](./testing-strategy.md) - Comprehensive testing patterns
- [Technology Stack](./technology-stack.md) - Technology choices and implementation details
- [Deployment Guide](./deployment-guide.md) - Infrastructure and deployment configuration
