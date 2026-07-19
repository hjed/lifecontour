# Journal System Specification

## Overview

The Journal System is the second core domain of the Personal Management System 2, alongside Contacts. It provides a flexible, extensible system for recording events, activities, notes, and experiences with rich metadata, hierarchical organization, and integration with external services.

## Core Principles

1. **Flexibility**: Journals can represent many things - events, activities, notes, mood ratings, travel plans
2. **Extensibility**: Type system allows adding new journal types and features without breaking existing functionality
3. **Integration**: Seamless integration with external services (Strava, Immich, Google Calendar)
4. **Hierarchy**: Support for parent-child relationships (e.g., trip containing daily entries)
5. **AI-First**: All functionality available via both REST API and MCP tools

## Domain Model

### Core Entities

#### Journal (Base Entity)

The base journal entity represents any recorded entry in the system.

**Required Fields:**
- `id` (UUID, primary key)
- `user_id` (FK to users, hardcoded for single user currently)
- `title` (string, max 500 chars)
- `content` (markdown text)
- `event_date_range` (start_date, end_date as UTC timestamps)
- `created_at` (timestamp)
- `updated_at` (timestamp)

**Optional Fields:**
- `parent_id` (FK to journals, for hierarchical structure)
- `order` (integer, for ordering siblings)

**Constraints:**
- Maximum nesting depth: 5 levels
- Strict tree structure (single parent only)
- `event_date_range.start` must be before or equal to `event_date_range.end`
- `event_date_range` can be in the future (for planned events)
- Title required, content required
- Journals can have zero or more types

**Child Ordering:**
- Children ordered by: 1) event_date_range.start, 2) order field (user-defined)

#### Journal Types

Journals can have multiple types, each adding specific fields and functionality. Types are detected by the presence of corresponding data tables.

**Type System Architecture:**
- Each type has a corresponding `journal_{type}_data` table
- A journal has a type if a row exists in that type's data table
- Type-specific data tables contain required and optional fields
- Some types have dependencies (automatically added when parent type is added)

**Base Types:**

1. **NOTE**
   - No additional data table (uses only base journal fields)
   - For simple text notes and observations

2. **EVENT**
   - Has calendar information
   - Can be synced to Google Calendar
   - Table: `journal_calendar_info`

3. **MOOD_RATING**
   - Tracks mood and energy levels
   - Table: `journal_mood_data`

4. **PLAN**
   - Event planning with document links
   - Table: `journal_plan_data`

5. **TRAVEL**
   - Travel itineraries with flights, accommodations, transportation
   - Table: `journal_travel_data`

6. **PHOTO_ALBUM**
   - Links to external photo album (Immich)
   - Table: `journal_photo_album_data`

**Activity Types:**

7. **FITNESS**
   - Base type for fitness activities
   - Includes heart rate, distance, elevation, GPX tracks
   - Table: `journal_fitness_data`

8. **OUTDOOR_ACTIVITY**
   - Extends FITNESS
   - Outdoor-specific activity data
   - Table: `journal_outdoor_activity_data`
   - Dependencies: Requires FITNESS (automatically added)

9. **BUSHWALKING**
   - Extends OUTDOOR_ACTIVITY
   - Australian bushwalking-specific data
   - Table: `journal_bushwalking_data`
   - Dependencies: Requires OUTDOOR_ACTIVITY, FITNESS (automatically added)

10. **ABSEILING_TRIP**
    - Extends OUTDOOR_ACTIVITY
    - Abseiling/rappelling trip data
    - Individual abseils are child journals
    - Table: `journal_abseiling_data`
    - Dependencies: Requires OUTDOOR_ACTIVITY, FITNESS (automatically added)

11. **CANYONING**
    - Extends OUTDOOR_ACTIVITY
    - Combines bushwalking and abseiling
    - Table: `journal_canyoning_data`
    - Dependencies: Requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS (automatically added)

12. **CLIMBING**
    - Extends OUTDOOR_ACTIVITY
    - Rock climbing activities
    - Table: `journal_climbing_data`
    - Dependencies: Requires OUTDOOR_ACTIVITY, FITNESS (automatically added)

13. **KAYAKING**
    - Extends OUTDOOR_ACTIVITY
    - Kayaking/paddling activities
    - Table: `journal_kayaking_data`
    - Dependencies: Requires OUTDOOR_ACTIVITY, FITNESS (automatically added)

14. **CROSS_COUNTRY_SKIING**
    - Extends OUTDOOR_ACTIVITY and BUSHWALKING
    - Cross-country skiing activities
    - Table: `journal_skiing_data`
    - Dependencies: Requires BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS (automatically added)

15. **JOGGING**
    - Extends FITNESS
    - Running/jogging activities
    - Table: `journal_jogging_data`
    - Dependencies: Requires FITNESS (automatically added)

**Type Dependency Rules:**
- Enforced at application layer (service layer validation)
- When a type is added, all dependent types are automatically added
- Type-specific data rows created with NULL values for optional fields
- Dependencies are transitive (CANYONING → BUSHWALKING → OUTDOOR_ACTIVITY → FITNESS)

### Contact Relationships

Journals can reference contacts in multiple ways via a unified relationship table.

**Relationship Types:**

1. **PARTICIPANT** - Contact attended/participated in the event
2. **INVITEE** - Contact was invited to the event
3. **MENTION** - Contact is mentioned in the journal content (manually tagged)
4. **ABOUT** - Journal is specifically about this contact

**Structure:**
```
journal_contact_relationships table:
- journal_id (FK to journals)
- contact_id (FK to contacts)
- relationship_type (enum: PARTICIPANT, INVITEE, MENTION, ABOUT)
- created_at
- Primary key: (journal_id, contact_id, relationship_type)
```

**Cardinality:**
- Multiple participants per journal
- Multiple invitees per journal
- Multiple mentions per journal
- Multiple "about" contacts per journal
- Same contact can have multiple relationship types to same journal

### Tags

Journals use a separate tag system from contacts but with the same hierarchical structure.

**Structure:**
```
journal_tags table:
- id (UUID)
- name (string)
- parent_id (FK to journal_tags, nullable)
- color (string, hex color)
- description (text, nullable)
- created_at
- updated_at

journal_tag_assignments table:
- journal_id (FK to journals)
- tag_id (FK to journal_tags)
- created_at
- Primary key: (journal_id, tag_id)
```

**Features:**
- Hierarchical tags (parent-child relationships)
- Multiple tags per journal
- Tag-based filtering and search

### Calendars

Journals can be associated with calendars for organization and Google Calendar sync.

**Structure:**
```
calendars table:
- id (UUID)
- user_id (FK to users)
- name (string)
- description (text, nullable)
- color (string, hex color)
- is_synced_to_google (boolean, default false)
- google_calendar_id (string, nullable)
- created_at
- updated_at
```

**Features:**
- Multiple calendars per user (Personal, Work, Family, etc.)
- Optional Google Calendar sync per calendar
- If journal.calendar_id references a synced calendar, journal is synced to Google Calendar

## Type-Specific Data Models

### Calendar Info (EVENT type)

```
journal_calendar_info table:
- journal_id (FK to journals, primary key)
- calendar_id (FK to calendars)
- start_time (time, nullable for all-day events)
- end_time (time, nullable for all-day events)
- is_all_day (boolean, default false)
- location (string, nullable)
- sync_invitees (boolean, default: true if imported from calendar, false otherwise)
- created_at
- updated_at
```

**Notes:**
- `calendar_id` associates journal with a calendar (required for EVENT type)
- `event_date_range` on base journal provides the date
- Times stored separately for flexibility
- All times stored as UTC, displayed in user's timezone
- Recurrences are separate journal entries
- Location is optional free-text field
- If calendar.is_synced_to_google = true, journal synced to Google Calendar

### Mood Data (MOOD_RATING type)

```
journal_mood_data table:
- journal_id (FK to journals, primary key)
- mood_value (integer, 1-10 scale, nullable)
- mood_label (string, nullable, e.g., "happy", "anxious", "calm")
- energy_level (integer, 1-10 scale, nullable)
- created_at
- updated_at
```

**Notes:**
- Both numeric scale (1-10) and optional mood label
- Energy level uses same 1-10 scale
- All fields optional (can track just mood or just energy)
- Notes about mood go in journal.content field

### Plan Data (PLAN type)

```
journal_plan_data table:
- journal_id (FK to journals, primary key)
- created_at
- updated_at

journal_plan_documents table:
- id (UUID)
- journal_id (FK to journal_plan_data)
- url (string)
- title (string)
- description (text, nullable)
- order (integer)
- created_at
```

**Notes:**
- Document links only (external URLs)
- Plans typically children of event journals
- Future: may add checklist items, status tracking

### Travel Data (TRAVEL type)

```
journal_travel_data table:
- journal_id (FK to journals, primary key)
- created_at
- updated_at

journal_travel_flights table:
- id (UUID)
- journal_id (FK to journal_travel_data)
- flight_number (string)
- airline (string, nullable)
- departure_airport (string)
- arrival_airport (string)
- departure_time (timestamp)
- arrival_time (timestamp)
- booking_reference (string, nullable)
- seat_number (string, nullable)
- confirmation_number (string, nullable)
- order (integer)
- created_at

journal_travel_accommodations table:
- id (UUID)
- journal_id (FK to journal_travel_data)
- name (string)
- address (text, nullable)
- check_in_date (date)
- check_out_date (date)
- booking_reference (string, nullable)
- confirmation_number (string, nullable)
- order (integer)
- created_at

journal_travel_transportation table:
- id (UUID)
- journal_id (FK to journal_travel_data)
- type (string, e.g., "car_rental", "train", "bus")
- details (text)
- booking_reference (string, nullable)
- order (integer)
- created_at
```

**Notes:**
- Supports multiple flights, accommodations, transportation per trip
- Order field for sorting within each category
- Future: may add visa info, travel insurance, emergency contacts

### Photo Album Data (PHOTO_ALBUM type)

```
journal_photo_album_data table:
- journal_id (FK to journals, primary key)
- immich_album_id (string, Immich album identifier)
- created_at
- updated_at
```

**Notes:**
- Links journal to external Immich photo album
- One album per journal
- Photos fetched from Immich API on-demand (no local caching)
- Photos displayed inline in journal view
- Future: Auto-create albums based on event date range

### Fitness Data (FITNESS type)

```
journal_fitness_data table:
- journal_id (FK to journals, primary key)
- heart_rate_avg (integer, bpm, nullable)
- heart_rate_max (integer, bpm, nullable)
- distance (integer, meters, nullable)
- elevation_gain (integer, meters, nullable)
- elevation_loss (integer, meters, nullable)
- duration (integer, seconds, nullable)
- calories (integer, nullable)
- gpx_track_data (text, nullable, GPX XML format)
- strava_activity_id (string, nullable, external reference)
- created_at
- updated_at
```

**Notes:**
- Parent type for all fitness activities
- GPX track data stored inline as XML text
- Strava activity ID for linking back to Strava
- All fields optional (not all activities have all metrics)
- GPX data can be imported from Strava or uploaded by user

### Outdoor Activity Data (OUTDOOR_ACTIVITY type)

```
journal_outdoor_activity_data table:
- journal_id (FK to journals, primary key)
- weather_conditions (text, nullable)
- role (string, nullable, e.g., "leader", "participant", "spectator")
- in_leadership_role (boolean, nullable)
- participant_notes (text, nullable)
- created_at
- updated_at
```

**Notes:**
- Extends FITNESS (requires journal_fitness_data row)
- Generic outdoor activity fields shared by all outdoor activity types
- Activity type is determined by the presence of subtype-specific data tables (e.g., bushwalking, abseiling, canyoning)
- in_leadership_role indicates if user was leading/guiding the group
- participant_notes for recording notes about participants (such as names of participants that are not contacts)
- Specific activity types add their own tables with activity-specific fields

### Bushwalking Data (BUSHWALKING type)

```
journal_bushwalking_data table:
- journal_id (FK to journals, primary key)
- route_id (FK to routes, nullable)
- track_grading (string, nullable, Australian Track Grading System)
- created_at
- updated_at
```

**Notes:**
- route_id references the routes table for reusable track names
- Australian Track Grading: Grade 1-5 system
- Extends OUTDOOR_ACTIVITY and FITNESS
- Leadership role and participant notes stored in journal_outdoor_activity_data

### Abseiling Data (ABSEILING_TRIP type)

```
journal_abseiling_data table:
- journal_id (FK to journals, primary key)
- number_of_abseils (integer, nullable)
- total_length (integer, meters, nullable)
- number_of_setups (integer, nullable)
- number_of_rescues (integer, nullable)
- created_at
- updated_at
```

**Notes:**
- Individual abseil pitches are stored as structured rows in the `abseil_pitches` table (see below)
- Aggregate fields (`number_of_abseils`, `total_length`, `number_of_setups`, `number_of_rescues`) can be auto-calculated from pitches or set manually
- Extends OUTDOOR_ACTIVITY and FITNESS

### Abseil Pitches (child of ABSEILING_TRIP)

```
abseil_pitches table:
- id (integer, auto-increment, primary key)
- journal_id (FK to journal_abseiling_data)
- pitch_number (integer, required, positive)
- height (integer, nullable, metres)
- anchor_location (string, nullable, constrained to: TR, TL, Centre)
- anchor_type (string, nullable, constrained to: chains, double bolt, single bolt, sling on tree, sling on log, sling on boulder, sling on bollard, artificial removable)
- did_rescue (boolean, nullable)
- did_setup (boolean, nullable)
- created_at
- updated_at
```

**Notes:**
- Pitches belong to a specific abseiling journal entry
- Anchor location represents the position of the anchor relative to the abseil line: TR (top right), TL (top left), Centre
- Anchor type values are constrained to common outdoor anchoring methods
- `did_rescue` and `did_setup` flags support aggregate counting for logbook statistics

### Canyoning Data (CANYONING type)

```
journal_canyoning_data table:
- journal_id (FK to journals, primary key)
- route_id (FK to routes, nullable)
- french_grade (string, nullable)
- water_guage_name (string, nullable)
- water_guage_level (integer, nullable)
- is_vertical (boolean, nullable)
- is_night_canyon (boolean, nullable)
- is_white_water (boolean, nullable)
- created_at
- updated_at
```

**Notes:**
- route_id references the routes table for reusable canyon names
- Combines bushwalking and abseiling
- French grading system for canyons (e.g v3a2IV**)
- Requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS types
- Leadership role and participant notes stored in journal_outdoor_activity_data

### Climbing Data (CLIMBING type)

```
journal_climbing_data table:
- journal_id (FK to journals, primary key)
- route_id (FK to routes, nullable)
- climbing_type (enum, nullable, e.g., "sport", "trad", "bouldering")
- grade (integer, nullable)
- length (integer, meters, nullable)
- created_at
- updated_at
```

**Notes:**
- route_id references the routes table for reusable climb names
- Extends OUTDOOR_ACTIVITY and FITNESS

### Kayaking Data (KAYAKING type)

```
journal_kayaking_data table:
- journal_id (FK to journals, primary key)
- route_id (FK to routes, nullable)
- water_type (string, nullable, e.g., "river", "sea", "lake")
- created_at
- updated_at
```

**Notes:**
- route_id references the routes table for reusable waterway names
- Extends OUTDOOR_ACTIVITY and FITNESS
- Future: may add water conditions, rapids grade, etc.

### Cross-Country Skiing Data (CROSS_COUNTRY_SKIING type)

```
journal_skiing_data table:
- journal_id (FK to journals, primary key)
- route_id (FK to routes, nullable)
- snow_conditions (text, nullable)
- created_at
- updated_at
```

**Notes:**
- route_id references the routes table for reusable trail names
- Extends BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS
- Future: may add trail difficulty, equipment details

### Jogging Data (JOGGING type)

```
journal_jogging_data table:
- journal_id (FK to journals, primary key)
- route_id (FK to routes, nullable)
- pace (integer, seconds per km, nullable)
- created_at
- updated_at
```

**Notes:**
- route_id references the routes table for reusable running routes
- Extends FITNESS (not OUTDOOR_ACTIVITY)
- For running/jogging activities
- Future: may add splits, intervals, etc.

## Integration Specifications

**Architecture Reference**: Journal integrations follow the **Isolated Worker Architecture** pattern defined in [Integration Architecture](./architecture/integration-architecture.md). This ensures:
- Dependency isolation for each integration
- Message-based communication via ARQ task queue
- Idempotent operations for safe message redelivery
- Conflict resolution with user confirmation
- Full audit trail via change events

**Change Tracking**: Similar to contacts, all journal changes are recorded with source attribution (manual, strava, google_calendar, api, mcp) enabling:
- Full audit trail of modifications
- Integration conflict detection and resolution
- Analytics on journal usage patterns
- Support for future integrations (Garmin, Apple Health, etc.)

### Strava Integration

**Import Behavior:**
1. Strava activities automatically create journal entries
2. Created as FITNESS + OUTDOOR_ACTIVITY types (based on activity type)
3. Fitness data populated from Strava metrics
4. GPX track imported if available
5. `strava_activity_id` stored in fitness data for reference

**Merge Behavior:**
1. When Strava activity matches existing journal (by date range + activity type)
2. System prompts user for confirmation
3. User chooses which data to keep for each field (Strava vs manual)
4. Generic merge function handles conflict resolution
5. Strava reference maintained after merge

**Sync Direction:**
- One-way: Strava → Journal (read-only)
- No write-back to Strava

### Immich Integration

**Album Linking:**
1. Journal can reference one Immich album via `immich_album_id`
2. Photos fetched from Immich API on-demand (no local caching)
3. Photos displayed inline in journal view
4. Future: Auto-create albums based on event date range

**Display:**
- Fetch album metadata and photo list from Immich API
- Display thumbnails in journal view
- Link to full-size images in Immich

### Google Calendar Integration

**Sync Behavior:**
1. If `journal.calendar_id` references a calendar with `is_synced_to_google = true`
2. Journal automatically synced to Google Calendar
3. Sync includes: title, event_date_range, start_time, end_time, location
4. If `sync_invitees = true`, sync invitees as calendar attendees

**Sync Direction:**
- Bi-directional: Journal ↔ Google Calendar
- Changes in either system reflected in the other
- Recurrences: Each occurrence is a separate journal entry

**Import Behavior:**
1. Google Calendar events can be imported as journals
2. Created as EVENT type with calendar_info
3. `sync_invitees` defaults to true for imported events
4. Attendees imported as INVITEE relationships

## Search and Filtering

### MeiliSearch Integration

**Indexed Fields:**
- title (searchable, high weight)
- content (searchable, medium weight)
- event_date_range (filterable, sortable)
- types (filterable, derived from data table presence)
- contact_ids (filterable, from relationships)
- tag_ids (filterable)
- calendar_id (filterable)
- location (searchable, from calendar_info)
- parent_id (filterable)

**Search Capabilities:**
- Full-text search across title and content
- Filter by type(s) - multiple types supported
- Filter by date range
- Filter by contacts (any relationship type)
- Filter by tags
- Filter by calendar
- Filter by parent/child relationships
- Sort by date, relevance, title

**Indexing Strategy:**
- Event-driven indexing via transactional outbox pattern
- Index updates on journal create/update/delete
- Index updates on type data changes
- Index updates on relationship changes

### Filter Requirements

**Date Filtering:**
- Date range (start and end)
- Relative dates (today, this week, this month, this year)
- Future vs past events

**Type Filtering:**
- Single type or multiple types (OR logic)
- Type hierarchy (e.g., filter by FITNESS includes all child types)

**Contact Filtering:**
- By relationship type (participants, invitees, mentions, about)
- By specific contact(s)
- Journals where contact appears in any relationship

**Tag Filtering:**
- By specific tag(s)
- Include child tags (hierarchical)

**Calendar Filtering:**
- By specific calendar(s)
- Unassigned (no calendar)

**Hierarchy Filtering:**
- Top-level only (no parent)
- Children of specific parent
- All descendants of parent (recursive)

## Display Requirements

### Contact Page Display

**Requirements:**
1. Show all journals where contact appears (any relationship type)
2. Group by relationship type (sections for Participant, Invitee, About, Mention)
3. Show parent journals with children grouped underneath
4. Sort by event_date_range (most recent first)
5. Display journal type badges
6. Show excerpt of content (first 200 chars)
7. Link to full journal view

### Date-Based Journal Views

**List View (Priority 1):**
- Grouped by date (day, week, or month grouping)
- Show title, types, contacts, excerpt
- Expandable to show full content
- Filter sidebar with all filter options
- Sort options: date (asc/desc), title, created_at

**Calendar View (Priority 2):**
- Month/week/day views
- Journals displayed on event_date_range
- Color-coded by calendar or type
- Click to view/edit journal
- Drag-and-drop to change dates

**PDF Export:**
- Export filtered journal list to PDF
- Include: title, date, content, contacts, photos
- Formatted for printing
- Date range and filters shown in header

### Journal Detail View

**Display:**
1. Title and content (rendered markdown)
2. Event date range and time
3. Type badges (all types)
4. Contact relationships (grouped by type)
5. Tags
6. Calendar assignment
7. Parent journal link (if child)
8. Child journals list (if parent)
9. Immich photos (inline gallery)
10. Type-specific data (expandable sections)
11. Edit/delete actions
12. Created/updated timestamps

**Child Journals:**
- Listed in order (by event_date_range, then order field)
- Show as cards with title, date, excerpt
- Expandable to show full content
- Link to child detail view

## API Specifications

### REST API Endpoints

**Core CRUD:**

```
GET /api/journals
- List journals with filtering and pagination
- Query params: type, date_range, contact_id, tag_id, calendar_id, parent_id, search
- Returns: paginated list with embedded type data and relationships
- Includes child count for parent journals

POST /api/journals
- Create new journal
- Body: base journal fields + type data + relationships
- Automatically adds dependent types
- Returns: created journal with all data

GET /api/journals/{id}
- Get single journal with all data
- Includes: base fields, all type data, relationships, tags, children
- Returns: full journal resource

PUT /api/journals/{id}
- Update journal (full replacement)
- Body: complete journal data
- Handles type additions/removals
- Returns: updated journal

PATCH /api/journals/{id}
- Partial update
- Body: fields to update
- Returns: updated journal

DELETE /api/journals/{id}
- Delete journal
- Cascade deletes: type data, relationships, tags
- Orphans children (sets parent_id to null) or deletes based on param
- Returns: 204 No Content
```

**Type Management:**

```
POST /api/journals/{id}/types
- Add type(s) to journal
- Body: { types: ["CANYONING"] }
- Automatically adds dependencies
- Creates type data rows with null values
- Returns: updated journal with new types

DELETE /api/journals/{id}/types/{type}
- Remove type from journal
- Deletes type data row
- Validates no dependent types remain
- Returns: updated journal

PUT /api/journals/{id}/types/{type}/data
- Update type-specific data
- Body: type-specific fields
- Returns: updated type data
```

**Relationship Management:**

```
POST /api/journals/{id}/contacts
- Add contact relationship
- Body: { contact_id, relationship_type }
- Returns: created relationship

DELETE /api/journals/{id}/contacts/{contact_id}
- Remove all relationships with contact
- Query param: relationship_type (optional, to remove specific type)
- Returns: 204 No Content

GET /api/contacts/{id}/journals
- Get all journals for contact
- Query params: relationship_type, date_range
- Returns: paginated journal list
```

**Tag Management:**

```
GET /api/journals/tags
- List all journal tags
- Returns: tags with name, color, description, parent_id

POST /api/journals/tags
- Create a journal tag
- Body: { name, color?, description?, parent_id? }
- Returns: created tag

PATCH /api/journals/tags/{tag_id}
- Update a journal tag
- Body: any of { name, color, description, parent_id }
- Omitted attributes are unchanged
- parent_id is the only field where null is meaningful: an explicit null moves
  the tag to the root of the hierarchy
- An explicit null for name, color, or description is rejected with a 400 —
  these fields cannot be cleared, only set to a new value. Omit a field to
  leave it as it is
- Validates name uniqueness (case-insensitive), hex colour format, and
  rejects a parent that would make the tag its own ancestor
- Returns: updated tag

DELETE /api/journals/tags/{tag_id}
- Delete a journal tag
- Returns: 204 No Content
```

**Search:**

```
GET /api/journals/search
- MeiliSearch-powered search
- Query params: q (query), filters (JSON), sort, page, page_size
- Returns: paginated search results with highlights
```

**Analytics:**

```
GET /api/journals/stats
- Journal statistics
- Query params: date_range, type
- Returns: counts by type, date distribution, etc.

GET /api/journals/mood-trends
- Mood analytics over time
- Query params: date_range
- Returns: mood/energy trends, averages, patterns
```

**Merge:**

```
POST /api/journals/merge
- Merge two journals
- Body: { source_id, target_id, field_preferences: {...} }
- field_preferences: for each conflicting field, choose source or target
- Returns: merged journal
```

### MCP Tools

**Core Operations:**

```python
create_journal_entry(
    title: str,
    content: str,
    event_date_range: dict,  # {start: datetime, end: datetime}
    types: list[str] = [],
    type_data: dict = {},  # Type-specific data keyed by type (includes calendar_id for EVENT, immich_album_id for PHOTO_ALBUM)
    contact_relationships: list[dict] = [],  # [{contact_id, relationship_type}]
    tags: list[str] = [],
    parent_id: str = None
) -> JournalResponse
```
- Creates journal with all associated data
- Automatically adds dependent types
- Type-specific data includes calendar_id (for EVENT) and immich_album_id (for PHOTO_ALBUM)
- Returns AI-optimized response with summary

```python
update_journal_entry(
    journal_id: str,
    title: str = None,
    content: str = None,
    event_date_range: dict = None,
    types: list[str] = None,  # Replaces all types
    type_data: dict = None,  # Updates type-specific data (includes calendar_id for EVENT, immich_album_id for PHOTO_ALBUM)
    contact_relationships: list[dict] = None,  # Replaces all relationships
    tags: list[str] = None  # Replaces all tags
) -> JournalResponse
```
- Updates journal fields
- Handles type additions/removals with dependencies
- Type-specific data includes calendar_id (for EVENT) and immich_album_id (for PHOTO_ALBUM)
- Returns updated journal

```python
get_journal(
    journal_id: str,
    include_children: bool = True
) -> JournalResponse
```
- Retrieves journal with all data
- Optionally includes child journals
- Returns AI-optimized response

```python
search_journals(
    query: str = None,
    types: list[str] = None,
    date_range: dict = None,
    contact_id: str = None,
    relationship_type: str = None,
    tags: list[str] = None,
    calendar_id: str = None,
    parent_id: str = None,
    limit: int = 20
) -> list[JournalResponse]
```
- Searches journals with filters
- Returns AI-optimized summaries
- Includes relevance scores for text search

```python
delete_journal(
    journal_id: str,
    delete_children: bool = False
) -> dict
```
- Deletes journal and associated data
- Optionally deletes children or orphans them
- Returns confirmation

**Contact Integration:**

```python
get_contact_journals(
    contact_id: str,
    relationship_type: str = None,
    date_range: dict = None,
    limit: int = 20
) -> list[JournalResponse]
```
- Gets all journals for a contact
- Filters by relationship type if specified
- Returns AI-optimized summaries

```python
link_journal_to_contact(
    journal_id: str,
    contact_id: str,
    relationship_type: str
) -> dict
```
- Creates contact relationship
- Validates relationship type
- Returns confirmation

**Analytics:**

```python
analyze_mood_trends(
    date_range: dict = None,
    granularity: str = "week"  # day, week, month
) -> dict
```
- Analyzes mood and energy patterns
- Returns trends, averages, insights
- AI-optimized for natural language summary

```python
get_activity_stats(
    activity_type: str = None,
    date_range: dict = None
) -> dict
```
- Statistics for fitness activities
- Total distance, elevation, duration, etc.
- Grouped by activity type
- AI-optimized summary

**AI Assistance:**

```python
summarize_period(
    date_range: dict,
    focus: str = None  # "activities", "mood", "social", "all"
) -> str
```
- Summarizes journals for a time period
- Natural language summary
- Highlights key events, patterns, insights

**Merge Operations:**

```python
merge_journals(
    source_id: str,
    target_id: str,
    field_preferences: dict  # {field_name: "source" | "target"}
) -> JournalResponse
```
- Merges two journals (for Strava import conflicts)
- User specifies which data to keep for each field
- Returns merged journal

```python
suggest_merge_candidates(
    journal_id: str
) -> list[dict]
```
- Finds potential duplicate journals
- Based on date range, type, contacts
- Returns candidates with similarity scores

### MCP Response Format

**JournalResponse:**
```python
{
    "id": "uuid",
    "title": "string",
    "content": "markdown",
    "summary": "AI-friendly summary of journal",  # Generated for AI consumption
    "event_date_range": {
        "start": "datetime",
        "end": "datetime"
    },
    "types": ["TYPE1", "TYPE2"],
    "type_data": {
        "TYPE1": {...},  # Type-specific data
        "TYPE2": {...}
    },
    "contacts": [
        {
            "id": "uuid",
            "name": "string",
            "relationship_type": "PARTICIPANT"
        }
    ],
    "tags": ["tag1", "tag2"],
    "calendar": {
        "id": "uuid",
        "name": "string"
    },
    "parent": {
        "id": "uuid",
        "title": "string"
    },
    "children": [
        {
            "id": "uuid",
            "title": "string",
            "summary": "string"
        }
    ],
    "immich_album": {  # Only present if PHOTO_ALBUM type
        "id": "string",
        "photo_count": 10
    },
    "created_at": "datetime",
    "updated_at": "datetime"
}
```

**Notes:**
- Summary field generated for AI-friendly context
- Embedded related data to reduce API calls
- Children included as summaries (not full content)
- Type data organized by type for clarity
- calendar_id included in type_data.EVENT if EVENT type present
- immich_album_id included in type_data.PHOTO_ALBUM if PHOTO_ALBUM type present

## Frontend Components

### Journal List Component

**Features:**
- Filterable list with sidebar filters
- Date grouping (day/week/month)
- Type icons for visual identification
- Color-coding by calendar (primary) or tag (secondary)
- Contact chips
- Expandable content preview
- Infinite scroll pagination
- Quick actions (edit, delete, duplicate)

**Filters:**
- Date range picker
- Type multi-select
- Contact autocomplete
- Tag multi-select
- Calendar select
- Parent/child toggle

**Display:**
- Calendar color bar on left edge
- Type icons next to title
- Tag badges with tag colors

### Journal Detail Component

**Features:**
- Inline editing (similar to contact detail page)
- Markdown content rendering with live preview
- Type-specific data sections (collapsible, inline editable)
- Contact relationship display (grouped by type, inline editable)
- Tag chips (clickable to filter, inline editable)
- Calendar badge (color-coded, inline editable)
- Type icons for visual identification
- Parent breadcrumb
- Child journal cards
- Immich photo gallery (inline)
- GPX track display using Google Maps API
- Delete confirmation

### Journal Form Component

**Features:**
- Title and content fields (markdown editor)
- Date range picker with time
- Type selector with dependency handling
- Type-specific field forms (conditional rendering)
- Contact relationship builder
- Tag selector (hierarchical)
- Calendar selector
- Parent journal selector
- Immich album picker
- Validation and error handling
- Auto-save draft

### Calendar View Component

**Features:**
- Month/week/day views
- Journal cards on dates
- Color-coding by calendar (primary) or tag (secondary)
- Type icons for visual identification
- Click to view/edit (inline editing)
- Drag-and-drop date changes
- Filter integration
- Today button and navigation

### Contact Journal Section

**Features:**
- Embedded in contact detail page
- Grouped by relationship type
- Collapsible sections
- Link to full journal view
- Quick add journal button (pre-fills contact)

### Mood Trends Component

**Features:**
- Line chart of mood/energy over time
- Date range selector
- Granularity toggle (day/week/month)
- Average lines
- Hover tooltips with journal links
- Export to image

### Activity Stats Component

**Features:**
- Summary cards (total distance, elevation, time)
- Activity type breakdown (pie chart)
- Timeline chart
- Personal records
- Comparison to previous periods
- Export to PDF

## Testing Strategy

### Unit Tests

**Domain Layer:**
- Journal entity validation
- Type dependency resolution
- Contact relationship validation
- Tag hierarchy validation
- Date range validation

**Service Layer:**
- Journal creation with types
- Type addition/removal with dependencies
- Merge logic
- Search query building
- Analytics calculations

**Repository Layer:**
- CRUD operations
- Complex queries (filters, joins)
- Type detection logic
- Hierarchy queries

### Integration Tests

**API Endpoints:**
- Full CRUD workflows
- Type management
- Relationship management
- Search and filtering
- Merge operations
- Error handling

**MCP Tools:**
- All tool operations
- Response format validation
- Error handling
- AI-friendly summaries

**External Integrations:**
- Strava import and merge
- Immich album fetching
- Google Calendar sync (bidirectional)
- MeiliSearch indexing

### E2E Tests (Playwright)

**User Workflows:**
- Create journal with multiple types
- Add contacts and tags
- Create parent-child hierarchy
- Search and filter journals
- View on contact page
- Calendar view interactions
- Import from Strava
- Link Immich album
- Export to PDF
- Merge duplicate journals

## Validation Rules Summary

**Base Journal:**
- Title: required, max 500 chars
- Content: required, markdown format
- event_date_range: required, start <= end, can be future
- parent_id: must exist, max depth 5, no cycles

**Types:**
- Can have zero or more types
- Dependencies automatically added
- Cannot remove type if dependent types exist
- Type-specific data validated per type schema
- EVENT type requires calendar_id in journal_calendar_info
- PHOTO_ALBUM type requires immich_album_id in journal_photo_album_data

**Contact Relationships:**
- contact_id must exist
- relationship_type must be valid enum
- No duplicate (journal_id, contact_id, relationship_type)

**Tags:**
- tag_id must exist
- No duplicate (journal_id, tag_id)

**Hierarchy:**
- Max depth: 5 levels
- No cycles (parent cannot be descendant)
- Children ordered by event_date_range, then order field

**Calendar Sync:**
- If calendar.is_synced_to_google, journal synced to Google Calendar
- sync_invitees only applies if calendar synced
- Requires calendar_info data (EVENT type)

## Security Considerations

**Authorization:**
- All journals belong to a user (user_id)
- Users can only access their own journals
- Future: shared journals with specific contacts

**Data Privacy:**
- All journals private by default
- No public access
- Calendar sync respects privacy settings
- Strava import only with user authorization

**Input Validation:**
- Sanitize markdown content (prevent XSS)
- Validate all foreign keys
- Validate enum values
- Validate date ranges
- Validate type dependencies

**External Integrations:**
- OAuth for Strava, Google Calendar
- API keys for Immich
- Rate limiting on external API calls
- Error handling for integration failures

## Performance Considerations

**Database:**
- Index on event_date_range for date queries
- Index on parent_id for hierarchy queries
- Index on calendar_id for calendar queries
- Composite index on (journal_id, type) for type detection
- Pagination for large result sets

**Search:**
- MeiliSearch for fast full-text search
- Async indexing via outbox pattern
- Cached search results (short TTL)

**External APIs:**
- Cache Immich photo metadata (short TTL)
- Batch Strava imports
- Queue Google Calendar syncs
- Retry logic for failed API calls

**Frontend:**
- Infinite scroll for journal lists
- Lazy load child journals
- Lazy load Immich photos
- Debounce search input
- Optimistic UI updates

## Future Enhancements

**Phase 9+:**
1. Shared journals with specific contacts
2. Journal templates (recurring journal types)
3. Automatic mention extraction from text
4. Voice-to-text journal entry
5. Photo-based journal creation (from Immich)
6. AI-generated journal summaries
7. Habit tracking integration
8. Goal tracking integration
9. Journal reminders and prompts
10. Rich media embeds (videos, audio)
11. Collaborative journals (multiple authors)
12. Journal export formats (Markdown, JSON, Day One)
13. Advanced analytics (sentiment analysis, topic modeling)
14. Integration with more fitness platforms (Garmin, Apple Health)
15. Location-based journal suggestions
16. Weather data integration
17. Journal streaks and gamification
18. Custom journal types (user-defined)
19. Journal versioning and history
20. Advanced search (semantic search, AI-powered)

## Appendix

### GPX Storage Recommendations

- Store GPX data as TEXT column in PostgreSQL
- Validate GPX XML format on import
- Extract key metrics (distance, elevation) for indexing
- Consider compression for large tracks (>1MB)
- Provide GPX download endpoint for export

### Markdown Rendering

- Use marked.js or similar for rendering
- Sanitize HTML output (prevent XSS)
- Support GitHub Flavored Markdown
- Enable syntax highlighting for code blocks
- Support tables, task lists, emoji

### Date/Time Handling

- Store all dates/times as UTC in database
- Display in user's timezone (browser timezone)
- Use ISO 8601 format for API responses
- Support all-day events (no time component)
- Handle timezone changes gracefully

---

**Document Version:** 1.0
**Last Updated:** 2025-10-19
**Status:** Draft - Ready for Review


