# MCP Tools Documentation

This document describes the MCP (Model Context Protocol) tools available in the Personal Management System for AI integration.

## Overview

The MCP server provides AI access to personal management data through standardized tools. All tools return AI-friendly JSON responses with contextual summaries optimized for AI analysis and decision making.

## Contact Management Tools

### get_contact

Retrieves detailed contact information by ID.

**Parameters:**
- `contact_id` (integer): The unique identifier of the contact

**Returns:**
AI-friendly contact information including:
- Basic contact details (name, email, phone)
- Associated tags for categorization
- Contextual summary for AI understanding

**Example:**
```json
{
  "id": "123",
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "tags": ["friend", "work"],
  "summary": "John Doe is a contact tagged as: friend, work. Notes: Great colleague and friend. Primary email: john@example.com. Primary phone: +1234567890."
}
```

### search_contacts

Searches contacts using MeiliSearch with full-text search, highlighting, and filtering.

**Parameters:**
- `query` (string): Search query for contacts
- `limit` (integer, optional): Maximum number of results (1-50, default: 20)
- `tags` (array of strings, optional): Filter by tags

**Returns:**
AI-friendly search results including:
- Matching contacts with highlighting
- Search metadata and processing time
- Available tags for further filtering
- Contextual summary for AI understanding

**Example:**
```json
{
  "results": [
    {
      "id": "123",
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1234567890",
      "tags": ["friend", "work"],
      "highlighted": {
        "first_name": "<mark>John</mark>",
        "last_name": "Doe"
      },
      "summary": "John Doe is a contact tagged as: friend, work. Email: john@example.com. Phone: +1234567890. Found through search highlighting."
    }
  ],
  "query": "john",
  "total_hits": 1,
  "processing_time_ms": 15,
  "available_tags": ["friend", "work", "family"],
  "summary": "Found 1 contacts matching 'john'. Search completed in 15ms. Available tags for filtering: friend, work, family."
}
```

### global_search

Performs global search across all entity types (currently contacts, with future support for journal entries, calendar events, etc.).

**Parameters:**
- `query` (string): Global search query across all entities
- `limit` (integer, optional): Maximum number of results (1-50, default: 20)
- `entity_types` (array of strings, optional): Entity types to search (e.g., 'contact')

**Returns:**
Unified search results across entity types with metadata and context.

### create_contact

Creates a new contact with validation and AI-friendly confirmation.

**Parameters:**
- `contact_data` (string): JSON string containing contact information with fields:
  - `first_name` (required): Contact's first name
  - `last_name` (optional): Contact's last name
  - `middle_name` (optional): Contact's middle name
  - `nick_name` (optional): Contact's nickname
  - `email` (optional): Primary email address
  - `phone` (optional): Primary phone number
  - `tags` (optional): List of tags to assign
  - `notes` (optional): Initial notes about the contact

**Returns:**
AI-friendly contact creation confirmation with created contact details and validation results.

**Example:**
```json
{
  "first_name": "Jane",
  "last_name": "Smith",
  "email": "jane@example.com",
  "phone": "+1987654321",
  "tags": ["colleague"],
  "notes": "New team member"
}
```

### update_contact

Updates an existing contact with validation and AI-friendly confirmation.

**Parameters:**
- `contact_data` (string): JSON string containing contact update information with fields:
  - `contact_id` (required): ID of the contact to update
  - `first_name` (optional): Updated first name
  - `last_name` (optional): Updated last name
  - `middle_name` (optional): Updated middle name
  - `nick_name` (optional): Updated nickname
  - `email` (optional): Updated primary email address
  - `phone` (optional): Updated primary phone number
  - `tags` (optional): Updated tags (replaces existing tags)
  - `notes` (optional): Additional notes to add

**Returns:**
AI-friendly contact update confirmation with updated contact details and validation results.

**Example:**
```json
{
  "contact_id": 123,
  "first_name": "Jane",
  "last_name": "Smith-Johnson",
  "email": "jane.smith.johnson@example.com",
  "phone": "+1987654321",
  "tags": ["colleague", "manager"],
  "notes": "Promoted to manager"
}
```

**Note:** This tool uses a replacement strategy for contact methods, addresses, notes, and tags. All existing items in these categories are replaced with the provided ones.

### list_contacts

Lists contacts with pagination and AI-friendly formatting.

**Parameters:**
- `page` (integer, optional): Page number (starting from 1, default: 1)
- `limit` (integer, optional): Contacts per page (1-50, default: 20)

**Returns:**
Paginated contact list with summaries, pagination metadata, and overall context.

**Example:**
```json
{
  "contacts": [
    {
      "id": "123",
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1234567890",
      "tags": ["friend", "work"],
      "summary": "John Doe is a contact tagged as: friend, work. Email: john@example.com. Phone: +1234567890."
    }
  ],
  "total_count": 1,
  "page": 1,
  "limit": 20,
  "summary": "Retrieved 1 contacts from page 1 of 1. Total contacts in system: 1. Tags represented: friend, work."
}
```

## Error Handling

All tools include comprehensive error handling with AI-friendly error messages:

```json
{
  "error": "Contact not found",
  "contact_id": 999,
  "message": "No contact exists with ID: 999"
}
```

## Authentication

All MCP tools require valid session authentication. The MCP server integrates with the existing OAuth2 authentication system.

## Journal Management Tools

### create_journal_entry

Creates a new journal entry with types, type-specific data, relationships, and tags.

**Parameters:**
- `journal_data` (string): JSON string containing journal creation data with fields:
  - `title` (required): Journal entry title
  - `content` (required): Journal content in markdown format
  - `event_date_range` (required): Object with `start` and `end` datetime fields
  - `types` (optional): Array of journal types (for example NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM, FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING, ABSEILING_TRIP, CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING)
  - `type_data` (optional): Object with type-specific data (e.g., `{"EVENT": {"calendar_id": "uuid"}}`)
  - `contact_relationships` (optional): Array of contact relationships (e.g., `[{"contact_id": 123, "relationship_type": "PARTICIPANT"}]`)
  - `tags` (optional): Array of tag names
  - `parent_id` (optional): Parent journal ID for hierarchical organization

**Returns:**
AI-friendly journal information including:
- Journal details (title, content, date range)
- Types and type-specific data
- Contact relationships
- Tags
- Contextual summary for AI understanding

**Example:**
```json
{
  "id": 456,
  "title": "Team Meeting Notes",
  "content": "Discussed Q1 goals and project timelines...",
  "summary": "Journal: Team Meeting Notes. Types: NOTE, EVENT. Tags: work, meeting. 2 contact(s). Calendar: Work Calendar.",
  "event_date_range": {
    "start": "2024-01-15T10:00:00Z",
    "end": "2024-01-15T11:00:00Z"
  },
  "types": ["NOTE", "EVENT"],
  "type_data": {
    "EVENT": {
      "calendar_id": "abc-123"
    }
  },
  "contacts": [
    {
      "id": 123,
      "name": "John Doe",
      "relationship_type": "PARTICIPANT"
    }
  ],
  "tags": ["work", "meeting"],
  "calendar": {
    "id": "abc-123",
    "name": "Work Calendar",
    "color": "#4285F4"
  },
  "created_at": "2024-01-15T09:00:00Z",
  "updated_at": "2024-01-15T09:00:00Z"
}
```

### update_journal_entry

Updates an existing journal entry with partial data.

**Parameters:**
- `journal_id` (integer): The unique identifier of the journal to update
- `journal_data` (string): JSON string with journal update data (partial fields):
  - `title` (optional): Updated title
  - `content` (optional): Updated content
  - `event_date_range` (optional): Updated date range
  - `types` (optional): Replace all types
  - `type_data` (optional): Update type-specific data
  - `contact_relationships` (optional): Replace all contact relationships
  - `tags` (optional): Replace all tags

**Returns:**
AI-friendly updated journal information with contextual summary.

### get_journal

Retrieves detailed journal information by ID.

**Parameters:**
- `journal_id` (integer): The unique identifier of the journal
- `include_children` (boolean, optional): Include child journals in the response (default: false)

**Returns:**
AI-friendly journal information including:
- Journal details (title, content, date range)
- Types and type-specific data
- Contact relationships
- Tags
- Optional child journals
- Contextual summary for AI understanding

**Example:**
```json
{
  "id": 456,
  "title": "Team Meeting Notes",
  "content": "Discussed Q1 goals and project timelines...",
  "summary": "Journal: Team Meeting Notes. Types: NOTE, EVENT. Tags: work, meeting. 2 contact(s). 3 child journal(s).",
  "event_date_range": {
    "start": "2024-01-15T10:00:00Z",
    "end": "2024-01-15T11:00:00Z"
  },
  "types": ["NOTE", "EVENT"],
  "contacts": [
    {
      "id": 123,
      "name": "John Doe",
      "relationship_type": "PARTICIPANT"
    }
  ],
  "tags": ["work", "meeting"],
  "children": [
    {
      "id": 457,
      "title": "Action Items",
      "summary": "Child journal: Action Items"
    }
  ]
}
```

### search_journals

Searches journals with filtering options.

**Parameters:**
- `query` (string, optional): Search query for full-text search
- `types` (string, optional): Comma-separated list of journal or activity types to filter by
- `limit` (integer, optional): Maximum number of results (default: 20)

**Returns:**
AI-friendly search results including:
- List of matching journals with excerpts
- Resolved journal types for each result, including activity types
- Search metadata (total hits, processing time)
- Contextual summary for AI understanding

**Notes:**
- `query` and `types` filters can be combined
- Activity searches can use types such as `fitness`, `jogging`, `bushwalking`, `kayaking`, `canyoning`, `climbing`, and `cross_country_skiing`

**Example:**
```json
{
  "results": [
    {
      "id": 456,
      "title": "Team Meeting Notes",
      "content_excerpt": "Discussed Q1 goals and project timelines...",
      "event_date_range": {
        "start": "2024-01-15T10:00:00Z",
        "end": "2024-01-15T11:00:00Z"
      },
      "types": ["NOTE", "EVENT"],
      "tags": ["work", "meeting"],
      "summary": "Journal: Team Meeting Notes. Types: NOTE, EVENT. Tags: work, meeting."
    }
  ],
  "query": "meeting",
  "total_hits": 1,
  "processing_time_ms": 12,
  "summary": "Found 1 journal(s)"
}
```

### search_activities

Searches fitness and outdoor activity journals with activity-specific filtering.

**Parameters:**
- `query` (string, optional): Search query for journal title/content
- `activity_type` (string, optional): Effective activity type filter such as `fitness`, `jogging`, `bushwalking`, `kayaking`, `canyoning`, `climbing`, or `cross_country_skiing`
- `start_date` (string, optional): ISO date/datetime lower bound for the journal event range
- `end_date` (string, optional): ISO date/datetime upper bound for the journal event range
- `limit` (integer, optional): Maximum number of results (default: 20)

**Returns:**
- Journal search results limited to activity journals
- Resolved effective activity type summaries for each result
- Total hit count for the matched activity set

### get_activity_stats

Aggregates activity totals, per-type breakdowns, and personal records.

**Parameters:**
- `activity_type` (string, optional): Restrict analytics to one effective activity type
- `start_date` (string, optional): ISO date/datetime lower bound for the journal event range
- `end_date` (string, optional): ISO date/datetime upper bound for the journal event range

**Returns:**
- `overall_totals` for distance, duration, elevation gain, and calories
- `activity_types` breakdown grouped by effective activity type
- `personal_records` such as longest distance, longest duration, highest elevation gain, and most calories
- Summary metadata describing the analysed activity set

### analyze_activity_trends

Builds time-bucketed activity analytics for trend analysis.

**Parameters:**
- `interval` (string): One of `day`, `week`, `month`, or `year`
- `activity_type` (string, optional): Restrict analytics to one effective activity type
- `start_date` (string, optional): ISO date/datetime lower bound for the journal event range
- `end_date` (string, optional): ISO date/datetime upper bound for the journal event range

**Returns:**
- Ordered trend buckets with activity counts
- Total distance, duration, and elevation gain per bucket
- Total analysed activity count and contextual summary

### get_route_history

Returns the history of activity journals associated with a route.

**Parameters:**
- `route_id` (string): Route UUID

**Returns:**
- Route summary metadata
- `usage_count` for all matching journals
- Distinct activity types that used the route
- Activity entries ordered newest-first with date range, distance, and duration

### delete_journal

Deletes a journal entry.

**Parameters:**
- `journal_id` (integer): The unique identifier of the journal to delete
- `delete_children` (boolean, optional): Delete child journals as well (default: false)

**Returns:**
Deletion confirmation with summary.

### get_contact_journals

Retrieves journals associated with a contact.

**Parameters:**
- `contact_id` (integer): The unique identifier of the contact
- `limit` (integer, optional): Maximum number of results (default: 20)

**Returns:**
AI-friendly journal summaries for the specified contact.

### link_journal_to_contact

Links a journal to a contact with a specific relationship type.

**Parameters:**
- `journal_id` (integer): The unique identifier of the journal
- `contact_id` (integer): The unique identifier of the contact
- `relationship_type` (string): Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)

**Returns:**
Relationship creation confirmation with summary.

**Example:**
```json
{
  "journal_id": 456,
  "contact_id": 123,
  "relationship_type": "PARTICIPANT",
  "linked": true,
  "summary": "Successfully linked journal 456 to contact 123 as PARTICIPANT"
}
```

## Future Enhancements

- Calendar event management tools
- Photo album and person linking tools
- Advanced analytics and insights tools
- OpenTelemetry instrumentation for monitoring

## Technical Implementation

- Built using FastMCP v2 for optimal AI integration
- Domain-based architecture for clean separation of concerns
- AI-optimized response formats with contextual summaries
- Comprehensive error handling and logging
- Unit and integration test coverage
