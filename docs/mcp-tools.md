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

## Future Enhancements

- Journal entry management tools
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
