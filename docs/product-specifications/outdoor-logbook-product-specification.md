# Outdoor Logbook Product Specification

## Overview

This document defines the target product behaviour for expanding the outdoor activity journal system into a full outdoor logbook. It is a product specification rather than a technical design.

This specification builds on the existing outdoor activity type hierarchy (FITNESS → OUTDOOR_ACTIVITY → BUSHWALKING/ABSEILING_TRIP/CANYONING/CLIMBING/KAYAKING/CROSS_COUNTRY_SKIING) and the Route entity. It adds structured abseil pitch tracking, activity templates, new activity types, supporting journal types for training and planning, gear maintenance tracking, and a PDF logbook export.

This specification assumes iteration 7 (Journals Product Alignment, Calendar Sync & Time Navigation) is complete before this work begins.

## Reference and Alignment

This specification evolves and refines behaviour described in:

- `docs/journal-system-specification.md`
- `docs/product-specifications/journals-product-specification.md`
- `docs/tasks/iteration-4.5-fitness-activity-types.md`

Where earlier documents assume narrower outdoor activity behaviour, this specification should be treated as the product-level refinement.

## Product Goals

The outdoor logbook should help the user:

1. Record outdoor activities with structured, type-appropriate detail.
2. Track abseil pitches with anchor and setup information across canyoning, caving, and climbing.
3. Reuse canyon, cave, and climb definitions as templates that pre-populate pitch data.
4. Log training sessions, planning meetings, and gear maintenance alongside field activities.
5. Export a comprehensive PDF logbook with yearly summaries and statistics.
6. Access all outdoor logbook capabilities through both the web UI and MCP.

## Product Principles

1. **Subtypes define the activity:** The activity type is determined by which journal subtypes are present, not by a free-text field.
2. **Structured over free-text:** Abseil pitches, anchor types, and maintenance types use constrained values for reliable statistics and export.
3. **Templates reduce data entry:** Reusable canyon/cave/climb templates pre-populate pitch data while remaining editable per trip.
4. **Everything exports:** All outdoor activity data, including training and gear maintenance, appears in the PDF logbook.
5. **AI-first:** All capabilities available in the UI must also be available through MCP.

## In Scope

- Removing `activity_type` from OUTDOOR_ACTIVITY data
- Structured abseil pitch data model replacing the child journal approach
- Activity templates for canyoning, caving, and climbing
- Modified types: CLIMBING (gains ABSEILING_TRIP dependency), KAYAKING (gains white water fields)
- New activity types: CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING
- New supporting types: OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE
- Gear items as a supporting entity
- PDF logbook export with yearly summaries
- MCP parity for all new capabilities

## Out of Scope

- SnipeIT gear sync (future work, but data model should be compatible)
- Gear usage tracking linked to activity journals (future work)
- Route/GPX changes (the existing Route entity is unaffected)
- Replacing the journal type system or dependency resolution
- Automated PDF generation (export is user-initiated)

---

## Type System Refinements

### Remove activity_type from OUTDOOR_ACTIVITY

The `activity_type` free-text field on `journal_outdoor_activity_data` must be removed. The activity type is now fully determined by the presence of subtype data tables (BUSHWALKING, CANYONING, CAVING, etc.).

This is a destructive schema change. A migration must drop the column. No data migration is needed as there are no standalone OUTDOOR_ACTIVITY journals that rely on this field.

The remaining OUTDOOR_ACTIVITY fields (`weather_conditions`, `role`, `in_leadership_role`, `participant_notes`) are inherited by all outdoor activity subtypes and remain unchanged.

### Abseil Pitch Data Model

The existing journal-system-specification described individual abseils as child journals. This was never implemented. Instead, abseil pitches are stored as a structured list within the abseiling data.

#### Pitch fields

Each abseil pitch has:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| pitch_number | integer | yes | Sequence/problem number for ordering |
| height | integer (metres) | no | Drop height of this pitch |
| anchor_location | enum | no | TR (top right), TL (top left), Centre |
| anchor_type | enum | no | See anchor type values below |
| did_rescue | boolean | no | Whether a rescue was performed on this pitch |
| did_setup | boolean | no | Whether the user set up the anchor on this pitch |

#### Anchor type values

- chains
- double bolt
- single bolt
- sling on tree
- sling on log
- sling on boulder
- sling on bollard
- artificial removable

#### Trip-level abseiling fields

The existing `number_of_abseils` and `total_length` fields remain. Two new aggregate fields are added:

| Field | Type | Description |
|-------|------|-------------|
| number_of_setups | integer, nullable | Total number of pitches where the user set up the anchor |
| number_of_rescues | integer, nullable | Total number of pitches where a rescue was performed |

#### Auto-calculation behaviour

When abseil pitches are present:

- `number_of_abseils` defaults to the count of pitches
- `total_length` defaults to the sum of pitch heights (where specified)
- `number_of_setups` defaults to the count of pitches where `did_setup` is true
- `number_of_rescues` defaults to the count of pitches where `did_rescue` is true

The user may manually override any of these totals. If pitches are not specified, the totals are entered manually as they are today.

#### Storage expectations

The average trip has approximately 5 pitches. The maximum could reach 60 but rarely exceeds 20. The storage and UI approach should be optimised for the common case of 5–20 pitches.

### Activity Templates

Templates represent reusable canyon, cave, or climb definitions. They are user-owned entities, separate from Routes (which track GPS data). Templates are searchable by name and pre-populate pitch data when selected.

#### Template entity fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | auto | Unique identifier |
| name | string | yes | Searchable name (e.g. "Claustral Canyon") |
| template_type | enum | yes | canyoning, caving, climbing |
| pitches | list | no | Standard abseil pitches for this location |
| region | string | no | Geographic region |
| description | string | no | Free-text description |

#### Type-specific template fields

**Canyoning templates** additionally have:

- `french_grade` (string, French canyon grading format)
- `canyon_type` (string, e.g. "vertical", "aquatic", "mixed")
- `water_gauge_name` (string)

**Caving templates** additionally have:

- `is_vertical` (boolean)
- `is_horizontal` (boolean)

**Climbing templates** additionally have:

- `climbing_type` (string: sport, trad, bouldering)
- `grade` (integer)
- `length` (integer, metres)

#### Template behaviour

- When the user selects a template during journal creation or editing, the template's standard pitches are copied into the journal's pitch data as editable defaults.
- The template reference is stored on the journal's type-specific data (e.g. `template_id` on canyoning data).
- Editing pitches on a journal does not modify the template.
- Templates can be created and edited independently of journals.
- Templates can also be created inline during journal creation.

---

## Modified Existing Types

### CLIMBING

**Change:** CLIMBING gains ABSEILING_TRIP as a type dependency.

Updated dependency chain: CLIMBING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]

This means every climbing journal automatically has abseiling data (with nullable fields). Climbing pitches are counted the same as abseil pitches. For climbing types that do not involve abseiling (e.g. bouldering), the abseiling data fields remain null.

A `template_id` field (FK to climbing templates) is added to `journal_climbing_data`.

### KAYAKING

**Change:** KAYAKING gains white water tracking fields.

New fields on `journal_kayaking_data`:

| Field | Type | Description |
|-------|------|-------------|
| is_white_water | boolean, nullable | Whether this is a white water kayaking session |
| rapids_grade | string, nullable | International Scale of River Difficulty (Grade I–VI) |

---

## New Activity Types

All new outdoor activity types extend OUTDOOR_ACTIVITY and FITNESS, inheriting `weather_conditions`, `role`, `in_leadership_role`, and `participant_notes`.

### CAVING

Caving activities involving underground exploration with optional abseiling.

**Dependencies:** CAVING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]

**Type-specific fields:**

| Field | Type | Description |
|-------|------|-------------|
| template_id | UUID, nullable | FK to caving template |
| is_vertical | boolean, nullable | Whether the cave is primarily vertical |
| is_horizontal | boolean, nullable | Whether the cave is primarily horizontal |

### CANOEING

Canoeing activities on waterways.

**Dependencies:** CANOEING → [OUTDOOR_ACTIVITY, FITNESS]

**Type-specific fields:**

| Field | Type | Description |
|-------|------|-------------|
| water_type | string, nullable | Type of water body (river, lake, sea) |

### SNORKELLING

Snorkelling activities.

**Dependencies:** SNORKELLING → [OUTDOOR_ACTIVITY, FITNESS]

**Type-specific fields:**

Minimal for initial release. Type-specific data table created with `journal_id` only (plus timestamps). Additional fields may be added in future iterations.

### DIVING

Diving activities.

**Dependencies:** DIVING → [OUTDOOR_ACTIVITY, FITNESS]

**Type-specific fields:**

Minimal for initial release. Type-specific data table created with `journal_id` only (plus timestamps). Additional fields may be added in future iterations.

### DOWNHILL_SKIING

Downhill skiing activities.

**Dependencies:** DOWNHILL_SKIING → [OUTDOOR_ACTIVITY, FITNESS]

**Type-specific fields:**

Minimal for initial release. Type-specific data table created with `journal_id` only (plus timestamps). Additional fields may be added in future iterations.

---

## New Supporting Types

### OUTDOOR_TRAINING

Training sessions related to outdoor activities.

**Dependencies:** OUTDOOR_TRAINING → [OUTDOOR_ACTIVITY, FITNESS]

**Type-specific fields:**

| Field | Type | Description |
|-------|------|-------------|
| focus_areas | list of strings | Outdoor activity types this training covers, drawn from the outdoor activity subtype enum plus a free-text "other" option |

The focus areas list uses the same set of outdoor activity subtypes used by OUTDOOR_PLANNING (see below). When the user selects "other", a free-text value can be entered.

Trainer/instructor information is captured through the existing journal contact PARTICIPANT relationship.

### OUTDOOR_PLANNING

Planning meetings, discussions, and coordination sessions related to outdoor activities.

**Dependencies:** OUTDOOR_PLANNING → [EVENT]

This type extends EVENT (not OUTDOOR_ACTIVITY). It uses the existing EVENT time fields (start_time, end_time, calendar_id, location) for meeting scheduling. The OUTDOOR_ACTIVITY fields (weather, role, leadership, participant_notes) are not inherited as they do not apply to planning meetings.

Meeting attendees are captured through the existing journal contact PARTICIPANT relationship.

**Type-specific fields:**

| Field | Type | Description |
|-------|------|-------------|
| topics | text | Free-text description of meeting topics |
| activity_types | list of strings | Which outdoor activity subtypes this meeting relates to |

The `activity_types` field uses the same outdoor activity subtype enum as OUTDOOR_TRAINING focus areas:

BUSHWALKING, ABSEILING_TRIP, CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING, OUTDOOR_TRAINING

### GEAR_MAINTENANCE

Gear inspection, maintenance, repair, and retirement records.

**Dependencies:** GEAR_MAINTENANCE → [] (no type dependencies, standalone journal type)

This type does not extend OUTDOOR_ACTIVITY or FITNESS. It uses base journal fields (title, content, date) plus its own type-specific data.

**Type-specific fields:**

| Field | Type | Description |
|-------|------|-------------|
| gear_item_id | UUID | FK to gear item entity |
| maintenance_type | enum | See maintenance type values below |
| activity_types | list of strings | Outdoor activity types this gear relates to (same enum as OUTDOOR_PLANNING) |
| retirement_reason | string, nullable | Reason for retirement (required when maintenance_type is "retiring") |

**Maintenance type values:**

- retiring gear
- repairing gear
- routine inspection
- routine maintenance
- upgrading gear
- calibration
- software support
- hardware support
- configuration change

The last five, with repairing gear, routine inspection and routine maintenance, correspond one-to-one to Snipe-IT's maintenance kinds (see the [Snipe-IT integration specification](snipe-it-integration-product-specification.md)); retiring gear has no Snipe-IT equivalent.

Users should be able to select or create a gear item inline when creating or editing a GEAR_MAINTENANCE journal.

---

## Gear Items

Gear items are a supporting entity, similar to activity templates. They are user-owned and not a first-class domain entity. In future, they will sync from SnipeIT.

**Gear item fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | UUID | auto | Unique identifier |
| name | string | yes | Gear item name |
| model | string | no | Model name/number |
| serial_number | string | no | Serial number |
| purchase_date | date | no | Date of purchase |
| manufacturer | string | no | Manufacturer name |
| created_at | timestamp | auto | Creation timestamp |
| updated_at | timestamp | auto | Last update timestamp |

**Future compatibility notes:**

- SnipeIT sync will import/update gear items (name, model, serial number, manufacturer, asset tag)
- SnipeIT sync will also import maintenance records and usage records linked to journals
- Gear items may become linkable to specific activity journals (e.g. "used rope X on this trip")

These future capabilities are out of scope for this specification but the data model should remain compatible.

---

## PDF Logbook Export

A PDF export produces a comprehensive outdoor logbook document covering all outdoor activities in chronological order.

### Export scope

The export includes all journals that have any of the following types:

- All OUTDOOR_ACTIVITY subtypes (BUSHWALKING, CANYONING, CAVING, CLIMBING, KAYAKING, CANOEING, SNORKELLING, DIVING, CROSS_COUNTRY_SKIING, DOWNHILL_SKIING, ABSEILING_TRIP)
- OUTDOOR_TRAINING
- OUTDOOR_PLANNING
- GEAR_MAINTENANCE

### Ordering and hierarchy

Journals are ordered chronologically by the date of their topmost parent journal. The full parent-child hierarchy is reflected in the export (e.g. Trip → Day → Activity → Sub-activity).

### Content per journal entry

Each journal entry in the export includes:

- Title, date, and content
- All type-specific data (outdoor activity fields, abseil pitches, grades, etc.)
- Fitness data where available (distance, elevation, duration, heart rate)
- Contact relationships (participants and invitees)
- Template reference name where applicable

### Summary pages

The export includes summary pages for **each calendar year** covered by the export:

| Summary metric | Breakdown |
|----------------|-----------|
| Activities in a leadership role | Per activity type, per calendar year |
| Total metres of abseiling | Per calendar year |
| Total number of abseils | Per calendar year |
| Total number of activities | Per activity type, per calendar year |
| Number of setups | Per calendar year |
| Number of rescues | Per calendar year |

### Participant index

The export includes an index of contacts who appear as PARTICIPANT or INVITEE across more than three journal entries within the export scope. The index lists the contact name and the number of appearances.

### Export behaviour

- Export is initiated by the user in the UI (not MCP).
- Export is on-demand, not automated.
- The user may apply filters (date range, activity types) before exporting.
- The PDF is generated and downloaded.

---

## MCP and AI-Agent Parity

All outdoor logbook capabilities available in the UI must also be available through MCP, following the existing generic `create_journal_entry` / `update_journal_entry` pattern with type-specific data.

### Required MCP capabilities

- Create and update journals with all new types and type-specific data
- Create and manage abseil pitches as part of abseiling data
- Create, search, list, and update activity templates
- Create, list, and update gear items
- Create GEAR_MAINTENANCE journals with gear item references
- Create OUTDOOR_TRAINING journals with focus areas
- Create OUTDOOR_PLANNING journals with topics and activity types
- Retrieve template details including standard pitches
- Retrieve gear item details

### Approach

New types are handled through the existing generic journal MCP tools. No new per-type tools are created. Template and gear item management may require dedicated tools or be handled as sub-resources of the journal tools.

---

## Updated Type Dependency Summary

For reference, the complete type dependency map after this specification:

```
# Base types (no dependencies)
NOTE → []
EVENT → []
MOOD_RATING → []
PLAN → []
TRAVEL → []
PHOTO_ALBUM → []
FITNESS → []
GEAR_MAINTENANCE → []

# Fitness subtypes
JOGGING → [FITNESS]
OUTDOOR_ACTIVITY → [FITNESS]

# Outdoor activity subtypes
BUSHWALKING → [OUTDOOR_ACTIVITY, FITNESS]
ABSEILING_TRIP → [OUTDOOR_ACTIVITY, FITNESS]
KAYAKING → [OUTDOOR_ACTIVITY, FITNESS]
CANOEING → [OUTDOOR_ACTIVITY, FITNESS]
SNORKELLING → [OUTDOOR_ACTIVITY, FITNESS]
DIVING → [OUTDOOR_ACTIVITY, FITNESS]
DOWNHILL_SKIING → [OUTDOOR_ACTIVITY, FITNESS]
OUTDOOR_TRAINING → [OUTDOOR_ACTIVITY, FITNESS]

# Compound outdoor types
CLIMBING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
CAVING → [ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
CANYONING → [BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, FITNESS]
CROSS_COUNTRY_SKIING → [BUSHWALKING, OUTDOOR_ACTIVITY, FITNESS]

# Event-based types
OUTDOOR_PLANNING → [EVENT]
```

---

## Success Criteria

This work will be successful when the user can:

1. Record outdoor activities without manually specifying an activity type string — subtypes define the activity.
2. Track abseil pitches with anchor details and see auto-calculated totals for abseils, length, setups, and rescues.
3. Create and reuse canyon, cave, and climb templates that pre-populate pitch data.
4. Log caving, canoeing, snorkelling, diving, and downhill skiing activities with appropriate type-specific fields.
5. Record outdoor training sessions with focus areas and planning meetings with topics.
6. Track gear maintenance including inspections, repairs, and retirements with linked gear items.
7. Export a PDF logbook with full hierarchy, yearly summary statistics, and participant index.
8. Access all of the above through MCP as well as the web UI.

## Delivery Notes

This specification defines target product behaviour. Delivery should be phased to preserve coherence.

Suggested phasing:

1. **Foundation:** Remove activity_type, abseil pitch data model, template entity, modified CLIMBING and KAYAKING types
2. **New activity types:** CAVING, CANOEING, SNORKELLING, DIVING, DOWNHILL_SKIING
3. **Supporting types:** OUTDOOR_TRAINING, OUTDOOR_PLANNING, GEAR_MAINTENANCE, gear items
4. **PDF export:** Logbook export with summaries and participant index
5. **MCP parity:** Ensure all capabilities are accessible through MCP tools

Each phase should deliver working, testable functionality with full UI and API support before moving to the next. Incomplete phases (e.g. templates without pitch pre-population, or gear maintenance without gear item creation) would be incomplete from a product perspective.
