# ITER1-002 Implementation Decisions

This document captures all the architectural and implementation decisions made for ITER1-002: Contacts Domain Core.

## Database Schema Decisions

### Primary Keys
- **Decision**: Use auto-incrementing integers (`SERIAL PRIMARY KEY`) instead of UUIDs
- **Rationale**: Simpler for AI assistants to work with, better performance for joins

### Contact Table Structure
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

### Contact Methods (Separate Table)
- **Decision**: Separate table for phone and email with primary designation
- **Structure**: `contact_methods` table with `method_type`, `value`, `label`, `is_primary`
- **Constraint**: Only one primary method per type per contact
- **Method Types**: 'email', 'phone' (addresses handled separately)

### Contact Addresses (Structured International Format)
- **Decision**: Separate table with structured international address format
- **Structure**: `contact_addresses` table with international address components
- **Fields**: street_line_1 (required), street_line_2, locality, region, postal_code, country_code (required)
- **Standards**: ISO 3166-1 alpha-2 country codes for international compatibility
- **Constraint**: Only one primary address per contact

### Tags Implementation
- **Decision**: Separate normalized tables (tags, contact_tags) instead of JSONB
- **Rationale**: Better for tag management, analytics, and hierarchical structure
- **Features**: Parent-child relationships, color coding, unique names

### Contact Notes
- **Decision**: Separate table with timestamps for future-proofing
- **Structure**: `contact_notes` table linked to contacts
- **Future**: Ready for linking to events/journals without schema changes

### Contact History
- **Decision**: Universal history table for all contact-related changes
- **Structure**: Tracks entity_type, entity_id, action, field changes
- **Integration**: Aligned with domain events for consistency

## Business Rules

### Contact Validation
- `first_name` is required (minimum 1 character)
- Email addresses must be valid format and unique across all contacts
- Phone numbers accept any format (international support)
- Names allow any characters (international names)

### Tag Validation
- Tag names: alphanumeric characters, hyphens (-), underscores (_), and ampersands (&) only
- Tag names must be unique
- Maximum 25 tags per contact
- Tags support hierarchical structure (parent-child relationships)

### Contact Methods
- Each contact can have multiple emails and phones
- Only one primary method per type per contact
- Method types: 'email', 'phone'

### Contact Addresses
- Each contact can have multiple addresses
- Only one primary address per contact
- Address validation: street_line_1 and country_code required
- Country code must be valid ISO 3166-1 alpha-2 format
- International address format supports global use cases

## Domain Architecture

### Entities
- **Contact**: Core entity with name fields
- **Tag**: Hierarchical tags with validation
- **ContactMethod**: Email and phone with primary designation
- **ContactAddress**: Structured international addresses with primary designation
- **ContactNote**: Timestamped notes for future integration

### Value Objects
- **Email**: Email validation and formatting
- **PhoneNumber**: International phone number handling
- **Address**: Structured international address with validation
- **CountryCode**: ISO 3166-1 alpha-2 country code validation
- **TagName**: Tag name validation and constraints

### Domain Services
- **ContactValidationService**: Business rule validation
- **TagHierarchyService**: Tag parent-child management
- **ContactHistoryService**: Change tracking and audit
- **AddressValidationService**: International address validation

### Repository Interfaces
- **ContactRepository**: CRUD operations with complex joins
- **TagRepository**: Tag management with hierarchy support
- **ContactHistoryRepository**: Change tracking and audit trails

## Error Handling

### Custom Exceptions
All exceptions include HTTP status codes and AI-friendly messages:

- `ContactNotFoundError` (404)
- `DuplicateEmailError` (409)
- `InvalidTagNameError` (400)
- `TooManyTagsError` (400)
- `ContactValidationError` (400)

### Transaction Management
- Contact modifications are transactional
- Tag existence is separate from contact-tag assignments
- History recording is part of the transaction

## Domain Events

Events aligned with history table for consistency:
- `ContactCreated`
- `ContactUpdated`
- `ContactDeleted`
- `TagAssigned`
- `TagRemoved`
- `ContactMethodAdded`
- `ContactAddressAdded`
- `ContactNoteAdded`

## Testing Strategy

### Unit Tests
- No database dependencies
- Mock repository interfaces
- Focus on business logic validation
- Test domain events and history tracking

### Test Data
- **Development seed data**: Sample contacts for manual testing
- **E2E test data**: Separate dataset for automated testing
- **Edge cases**: Empty fields, special characters, validation limits

## Implementation Notes

### SQLAlchemy Core Patterns
- Use explicit SQL with `text()` for readability
- Complex joins for loading full contact aggregates
- Parameterized queries for security
- Proper indexing for performance

### Connection Management
- **Decision**: Repositories receive AsyncConnection as constructor parameter
- **Rationale**: More future-proof for managing transactions across multiple repositories
- **Transaction Management**: Handled at domain/business layer, not repository layer
- **Repository Pattern**: Repositories use provided connection, don't manage their own

### Dependency Injection
- **Pattern**: Constructor injection with typed interfaces
- **Repositories**: `__init__(self, connection: AsyncConnection)`
- **Services**: `__init__(self, contact_repo: ContactRepository, tag_repo: TagRepository)`
- **Container**: Simple factory pattern, avoid complex DI frameworks
- **Type Safety**: All dependencies typed with interfaces for AI clarity

## Migration Strategy

Single Alembic migration creating all tables:
- `001_create_contacts_domain`
- Creates all 6 tables with proper constraints
- Includes all indexes for performance
- Proper foreign key relationships and cascades

## Future Considerations

### Ready for Integration
- Contact notes table ready for event/journal linking
- History table supports all entity types
- Domain events ready for cross-domain operations

### Google Sync Preparation
- Email uniqueness supports sync conflict resolution
- History tracking supports sync state management
- Tag structure ready for Google contact groups mapping
