# Journals Product Specification

## Overview

This document defines the target product behaviour for the next major improvement to Journals. It is a product specification rather than a technical design. It describes the intended user experience across the web interface, sync behaviour, merge behaviour, hierarchy, list navigation, and AI-facing workflows.

This specification builds on the current product rather than replacing it. The journal domain model, journal types, parent-child structure, calendar integration foundations, search infrastructure, and MCP support already exist in part. The work described here refines and completes those capabilities into a coherent journaling experience.

This specification also includes the intended product behaviour currently represented in iteration 7 calendar work, even though the iteration 7 task breakdown should later be rewritten to better reflect the current implementation state.

## Reference and Alignment

This specification evolves and refines behaviour described in the following existing documents:

- `docs/journal-system-specification.md`
- `docs/tasks/iteration-7-calendar-integration.md`
- `docs/design/iter4-008-journal-ui-design.md`
- `docs/architecture.md`
- `docs/architecture/domain-architecture.md`
- `docs/architecture/integration-architecture.md`
- `docs/architecture/frontend-design.md`
- `docs/product-specifications/contacts-product-specification.md`

Where older journaling documents assume narrower behaviour, especially around single-calendar event linkage, this specification should be treated as the product-level refinement of those earlier assumptions.

## Product Goals

The Journals experience should help the user:

1. Maintain a single trustworthy record of events, activities, trips, plans, and notes.
2. Keep event journals aligned with external calendars without allowing external systems to take control of the journal domain.
3. Detect and resolve duplicate or overlapping journals so integrations such as Google Calendar and future Strava import remain usable.
4. Understand and navigate journal hierarchy naturally, especially for trips and activity sub-entries.
5. Browse journals in a way that works equally well for past and future time-based entries.
6. Use the same core capabilities through the web UI and through AI agents via MCP.

## Product Principles

1. **AI-first:** Any meaningful journal capability available in the UI should also be available to AI agents through MCP.
2. **Build on existing behaviour:** The product should evolve current journal, sync, hierarchy, search, and list behaviour rather than restart it.
3. **Journal is primary:** The journal remains the canonical record. External calendars are linked systems, not the source of truth for the domain.
4. **Safe sync over clever sync:** Sync should be reliable, reviewable, and conservative, especially where an external system only supports one-way behaviour.
5. **Merge is core:** Merge is required to make sync and future external imports practical.
6. **Hierarchy should be visible and useful:** Parent-child structure should be easy to understand in the list, detail, and navigation experience.
7. **Time navigation should centre on the present:** The default journal browsing experience should be anchored around the current day, not a flat card grid.
8. **Parallel but aligned with contacts:** This stream should progress independently of the contacts improvements while reusing shared principles where appropriate.

## Scope Priority

This specification describes the full target behaviour, even if delivery happens in phases.

Priority order:

1. Google Calendar bidirectional sync refinement, including multi-calendar linking and sync review
2. Journal merge and merge-candidate review flow
3. Journal hierarchy creation and display improvements
4. Journal list redesign around current-day navigation and bidirectional infinite scroll
5. AI-generated daily summaries and day-level stats
6. Broader calendar views and event-management affordances from iteration 7

## Current Product Context

The current product already has a strong journaling foundation: a flexible journal type model, EVENT journals with calendar-related data, parent-child journal structure in the domain model, journal detail support for child journals, list and detail UI foundations, merge concepts in the journal spec, planned Google Calendar bidirectional sync in iteration 7, and MCP journaling capabilities in the original journal system specification.

However, these capabilities are still incomplete from a product perspective. The main gaps are around multi-calendar sync behaviour, merge as a first-class workflow, hierarchy visibility, time-oriented list navigation, and explicit UI/MCP parity for advanced journal workflows.

## In Scope

This specification covers:

- Google Calendar bidirectional sync for EVENT journals
- multi-calendar linkage from one journal to multiple external events
- sync states, sync review, and conflict handling
- journal merge behaviour and merge UI
- merge-candidate detection and review workflows
- hierarchy creation and hierarchy display
- journal list redesign around the current day
- lightweight empty-day handling and date jumping
- AI daily summaries and day-level statistics
- calendar views and sync-facing UI from iteration 7
- MCP parity for the above behaviours

## Out of Scope

This specification does not include:

- Microsoft Outlook sync implementation
- iCal or CalDAV sync implementation
- reminders syncing
- calendar colour syncing
- syncing PARTICIPANT relationships to external attendees
- replacing the journal type system
- rebuilding the journal domain from scratch
- editable AI-generated summaries
- hard delivery dependencies on the contacts stream

The product should, however, remain compatible with future Outlook and iCal support.

## Google Calendar Sync for Event Journals

### Product model

An EVENT journal represents the single canonical record of the event.

An EVENT journal may be linked to one or more internal calendars, and those calendars may each be linked to an external calendar such as Google Calendar. As a result, a single journal may correspond to multiple external calendar events.

### Required behaviour

- EVENT journals must support syncing to and from Google Calendar.
- One journal may be linked to multiple calendars.
- Each linked calendar may produce its own external event link.
- Local journal changes should be reflected to all linked calendars where bidirectional sync is supported.
- Changes made externally in one linked calendar should update the journal and then propagate to the other linked calendars where appropriate.
- Some calendar integrations may only support one-way sync. In those cases, externally sourced updates must not override manual journal edits.
- EVENT journals should continue to require at least one calendar.
- Recurrences must be treated as separate journals, not as a single recurring journal object.

### Fields that sync bidirectionally

The following EVENT fields should sync bidirectionally where supported:

- title
- description or content
- start date and time
- end date and time
- all-day flag
- timezone
- location
- invitees or attendees
- event status, including cancelled
- recurrence handling at the occurrence level

The following are explicitly not in scope for bidirectional sync in this phase:

- reminders
- calendar colour

### Invitees and participants

Invitees and participants are not the same thing.

- **Invitees** may sync to external attendees.
- **Participants** must remain local journal relationships and must not be synced outward as attendees.

### Matching and import behaviour

When a new external Google Calendar event appears:

- the system should first check whether it is already linked
- if not already linked, the system should attempt to match it to an existing journal using:
  - similar title, using AI assistance
  - same start date
  - similar end time or duration
- if a strong match is found, the event should be surfaced as a merge or link candidate
- if no strong match is found, the system should create a new EVENT journal
- if the system is unsure, it should prefer creating the event journal and surfacing a review suggestion rather than silently merging

The system may also surface additional likely matches based on nearby or overlapping events, but these should remain review suggestions rather than silent auto-merges.

### Existing events across multiple calendars

The product must support these common cases:

- an event was created in one synced calendar and later added to another
- an event was created in the journal system and pushed to multiple calendars
- two independently existing events in separate calendars are later found to represent the same real-world event

In the third case, the user must be able to resolve the situation through the merge and review flow, with the surviving journal retaining the relevant remote references.

### Conflict resolution

The default rule is latest write wins, using external version markers such as ETags wherever possible rather than attempting expensive full-diff conflict logic by default.

However:

- when a conflict affects meaningful data and cannot be safely resolved automatically, the system should surface it for user review
- merge and review tooling should allow the user to resolve conflicting values explicitly
- one-way synced sources must not overwrite manual edits merely because the external system changed

### Delete and cancel behaviour

Deletion should become uncommon for event journals. A cancelled state is preferred over destructive deletion.

Required behaviour:

- if an external calendar event is deleted, the linked journal should be marked cancelled and the external link should be removed
- the journal must not be deleted automatically
- if a journal is deleted intentionally, linked external events should be deleted remotely
- where possible, product flows should encourage cancellation rather than deletion for event journals

### Sync visibility and controls

Users must be able to:

- see sync state for an EVENT journal
- see whether a journal is linked to one or multiple calendars
- see whether a linked external event is synced, pending, conflicted, cancelled, or errored
- trigger a manual sync
- review and resolve conflicts
- understand when a journal has review suggestions related to external matches

This visibility should appear in the journal details experience and, in lighter form, in list views.

## Journal Merge

Merge is a core workflow for journaling, not a rare maintenance action. It is required to make Google Calendar sync and future Strava integration practically usable.

### Product model

A merge always has:

- one surviving journal
- one source journal that is absorbed
- one resulting unified journal record

The surviving journal retains the consolidated identity and relationships.

### Required behaviour

- The user must be able to merge two journals.
- The surviving journal must preserve:
  - all relevant base journal fields
  - all non-duplicate tags
  - all non-duplicate contact relationships
  - child journals
  - external references
  - sync links
  - audit and history relevance
- Duplicates should collapse rather than being duplicated on the merged journal.
- Remote references from both journals must be preserved where they still represent the same real-world entity.

### Type-aware merge behaviour

If the two journals do not share overlapping types:

- the surviving journal should simply gain the missing type data where valid

If the two journals share overlapping types:

- the user should be shown merge resolution UI
- the system should provide auto-merge suggestions

### Auto-merge rules

The default auto-merge behaviour should be:

- prefer non-empty over empty
- otherwise ask when both sides have meaningful values
- when comparing a calendar-derived EVENT journal and a manually created non-event journal, treat the manual non-event journal as more important
- preserve the richer local journal meaning rather than flattening it into calendar-only data

### Merge candidate detection

The system should actively suggest likely merge candidates based on:

- title similarity, using AI assistance
- same start date
- similar end time or duration
- overlapping or nearby times
- imported or synced provenance
- relevant type combinations such as EVENT and OUTDOOR_ACTIVITY

The system should surface these suggestions in:

- a dedicated **Needs Review** queue
- the journal detail view
- list view indicators

## Needs Review Queue

A dedicated review queue is required.

It should bring together cases where the user likely needs to act, including:

- likely merge candidates
- unresolved sync conflicts
- possible duplicate event journals
- externally matched but unconfirmed items

### Required behaviour

- The queue must be visible from the journaling experience.
- Each item should clearly explain why it needs review.
- Each item should allow the user to open the relevant journal or review screen directly.
- Journals with pending review should show an indicator in the main list.
- The journal detail page should expose related review suggestions inline.

## Journal Hierarchy

The original journal specification already treats hierarchy as part of the model. This work makes it a first-class product behaviour.

### Required behaviour

- Users must be able to create sub-journals from the parent journal detail page.
- Users must be able to create a journal with a parent selected from the create form.
- Users must be able to create a child journal from a context menu on the detail view.
- Parent journals must display child journals on the detail page.
- Child journals must show parent breadcrumbs.
- The journal list must display child journals nested under their parents.

### Hierarchy display behaviour

In list views:

- hierarchy should be expanded by default to a depth of 3 around the current date
- journals further away from the current focus should be more collapsed
- hierarchy should feel navigable without turning the list into a permanently expanded tree

This should work especially well for examples such as trips containing day entries, abseiling trips containing individual abseils, and plans attached to broader event journals.

### Ordering and structural rules

Existing structural rules still apply:

- strict tree structure
- single parent
- maximum depth from the journal spec
- no cycles

This specification does not require advanced hierarchy editing such as drag-and-drop reparenting unless later prioritised.

## Journal List Experience

The current flat card grid is not sufficient for a journal system containing both past and future event-heavy entries. The main Journals page should become a time-oriented browsing experience anchored on the present.

### Default list model

The primary journaling view should:

- open centred on the current day
- support infinite scrolling in both directions
- group journals by day
- support both past and future navigation
- show hierarchy within each day grouping

### Initial loading behaviour

Initial loading should fetch:

- the previous 2 days of journals
- the next 4 days of journals

Further scrolling should continue extending in either direction.

### Day groups

Each day group should support:

- date heading
- journal entries for that day
- lightweight empty-day rendering when there are no journals
- optional AI daily summary when there are multiple journals
- lightweight key stats where useful

Empty days should still appear, but should be lighter and less visually heavy than populated days.

### Future empty periods

Future weeks with no journals should not dominate the interface.

Required behaviour:

- collapse empty future weeks
- provide a clear affordance to expand or jump to a future date
- provide a quick way to add a journal on a selected future date

### Date jumping

A date jump interaction is required. A side-panel or overlay-style date jump is appropriate for this phase. The key product requirement is that users can efficiently jump to a date instead of scrolling long distances.

### List-level indicators

The list should surface, in lightweight form:

- sync status
- needs-review state
- hierarchy depth or context
- cancellation state where relevant

## Calendar Views and Event Management

Iteration 7 included broader calendar UI work, and that product intent should remain in scope.

### Required behaviour

The journaling experience should support alternate calendar views for EVENT journals, including:

- month view
- week view
- day view
- agenda view

These views should support:

- viewing journals on their event dates
- colour-coding by calendar where relevant
- opening a journal for editing
- quick event creation
- date navigation
- integration with filters

Where feasible and coherent with the journal model, the event-management UX may later include drag-and-drop rescheduling and inline editing, as already anticipated in iteration 7.

### Sync-related calendar UI

The calendar-facing UI should also include:

- sync status indicators
- manual sync trigger
- conflict resolution entry points

## AI Daily Summary and Key Stats

The journaling experience should help the user quickly understand a day when there are multiple journals.

### Required behaviour

- A short natural-language summary may be shown for a day with multiple journals.
- The summary should be grounded in the day's actual journal content and metadata.
- The summary should be read-only.
- The summary should be generated on demand and cached.
- The system should avoid generating summaries for days that do not have enough substance.

### Output expectations

The day summary should be:

- short
- practical
- descriptive rather than speculative
- accompanied by lightweight key stats where useful

Examples of useful day-level stats include journal count, event count, activity count, contacts involved, and key activity metrics where relevant.

### Tone and safety

- AI summaries should be useful but cautious.
- They should avoid unsupported inference.
- They should not silently rewrite the journal record.

## MCP and AI-Agent Parity

There must be no meaningful UI-only journaling behaviour.

### Required behaviour

MCP must support the ability to:

- create and update journals with parent-child structure
- create child journals
- retrieve a journal with hierarchy context
- browse journals around a date anchor
- retrieve grouped journal windows suitable for day-based workflows
- link and unlink event journals to calendars
- view sync state and review-needed state
- trigger or request sync actions
- obtain merge candidates
- review likely matches
- merge journals with explicit resolution choices where needed
- retrieve daily summaries and day-level stats

MCP does not need to mirror every UI interaction one-for-one, but it must support the same core capabilities, potentially through fewer, more powerful tools.

## Alignment with Contacts and Shared Product Principles

This work should remain aligned with the contacts stream, but not blocked by it.

### Shared principles

The journaling product should reuse and align with the same broader principles already established for contacts:

- UI and MCP parity
- conservative AI summaries
- reliable sync visibility and provenance
- search as a cross-domain experience
- nested and hierarchical organisation where it improves clarity
- infinite-scroll patterns where they improve usability

### Dependency stance

There are no hard delivery dependencies on the contacts product stream.

However:

- shared UI patterns should be reused where sensible
- global search expectations should remain aligned
- provenance and review states should feel conceptually consistent across domains

## Success Criteria

This work will be successful when the user can:

1. treat a journal as the primary record even when it syncs with multiple calendars
2. rely on sync without losing important manual edits
3. resolve duplicate and overlapping journals through a clear merge and review flow
4. navigate trips, events, and sub-journals naturally through list nesting, breadcrumbs, and detail pages
5. browse journals around the current day with useful forward and backward navigation
6. access the same meaningful journaling capabilities through AI tools and MCP

## Delivery Notes

This specification defines target product behaviour. Delivery may be phased, but phases should preserve coherence.

Examples:

- bidirectional sync without visible sync status or review surfaces would be incomplete
- merge candidate detection without an actual review workflow would be incomplete
- hierarchy in the model without hierarchy in the list and breadcrumb UI would be incomplete
- AI summaries in the UI without MCP access would be incomplete

The implementation task breakdown can be rewritten later, but the product intent above should remain stable.