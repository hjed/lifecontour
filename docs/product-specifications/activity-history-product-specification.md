# Activity History Product Specification

## Overview

This document defines the target product behaviour for a **unified activity history** capability that spans Contacts and Journals. It is a product specification rather than a technical design. It describes the intended user experience for understanding *what changed, when, and from where* across the entities they care about.

This specification builds on the current product rather than replacing it. Contacts already have a field-level activity feed with provenance (see the Activity Feed section of the [Contacts Product Specification](./contacts-product-specification.md)). Journals have no history today. The work described here generalises the existing contact history into a single coherent system and extends it to Journals of every type.

## Product Goals

Activity history should help the user:

1. Trust the record — see a faithful, complete trail of meaningful changes to a contact or journal.
2. Understand *where* a change came from (the web UI, an AI assistant via MCP, or an external sync such as Google or Immich).
3. Review change history in the same place they view the entity, without leaving the page.
4. Rely on the same history capability across Contacts and Journals, including all journal types.

## Product Principles

1. **Integrity by construction:** History must be a faithful reflection of what actually changed. It should be impossible for a change to occur without its history being recorded, and impossible for history to record a change that did not occur. History is derived from the same domain events that already drive search and sync, so the two can never drift apart.
2. **Build on existing behaviour:** Extend the current contact activity feed rather than build a parallel system. Contacts and Journals share one history model, one API shape, and one UI component.
3. **Meaningful changes only:** History records changes that actually altered the entity. Operations that touch the entity without changing it (for example, an export, or a sync that found nothing new) must not appear as activity.
4. **Provenance is first-class:** Every entry carries a clear, compact indication of its origin.
5. **AI-first parity:** History available in the UI is also available to AI agents through MCP.

## Scope

### In scope

- Field-level change history for **Journals** of all types (NOTE, EVENT, MOOD_RATING, PLAN, TRAVEL, PHOTO_ALBUM, all fitness and outdoor activity types, supporting types, routes, and gear items).
- A unified history model and activity-feed experience shared by Contacts and Journals.
- Provenance for every entry (UI, MCP/AI, system, and each external integration source).
- Migration of the existing **contact** history onto the same event-driven foundation, removing the current dual-write.
- A journal history API endpoint and MCP parity.

### Out of scope

- Point-in-time restore / "undo to this version" (history is a read-only audit trail).
- History filtering and search UI (the initial experience does not require filtering, matching the contacts activity feed today).
- Cross-entity global history views.

## Activity History Behaviour

### What is recorded

- Every meaningful create, update, and delete of a contact or journal, and of their related sub-entities (contact methods, addresses, notes, tags, relationships, important dates, summaries; journal type-specific data, routes, and gear items).
- Each recorded change captures the field that changed, the previous value, the new value, when it happened, who or what made it, and its provenance.
- Changes that do not alter the entity must not produce history entries.

### Where it appears

- **Journals:** an activity history section at the **bottom of the journal detail/edit screen**, mirroring the contact activity feed.
- **Contacts:** the existing activity feed location is unchanged.
- Both surfaces use the same component, layout, provenance icons, and pagination behaviour.

### Provenance

Every entry shows its origin with a compact icon and hover text. Supported sources include:

- **Web interface** — changes made by the user in the UI.
- **AI assistant (MCP)** — changes made by an AI agent.
- **System** — automated internal changes.
- **External integrations** — Google Contacts, Google Calendar, Strava, Immich, and any future integration source.
- **AI summary regeneration** — shown in an abbreviated, collapsible form (contacts), consistent with current behaviour.

### Timeliness and ordering

- History reflects the time a change actually occurred, ordered most-recent-first, regardless of any processing delay.
- History is updated reliably after a change. A brief delay between a change and its appearance in the feed is acceptable; a missing or duplicated entry is not.

### Pagination

- History loads in pages with a "Load More" affordance, matching the contacts activity feed.

## MCP and AI-Agent Parity

- AI agents must be able to retrieve a journal's history through MCP, with the same field-level detail and provenance available in the UI.
- Changes made by AI agents must themselves be recorded with AI/MCP provenance.

## Success Criteria

This work is successful when the user can:

1. Open any journal — of any type — and see a complete, ordered history of meaningful changes at the bottom of the screen.
2. See, for every contact and journal change, where it came from.
3. Trust that the history matches reality, because it is derived from the same events that drive the rest of the system.
4. Retrieve journal history through AI tools and MCP, matching the web experience.

## Delivery Notes

This specification defines target product behaviour. Delivery is phased in [Iteration 12: Activity History](../tasks/iteration-12-activity-history.md). Phases should preserve coherence: journal history without provenance, or a journal history API without a UI surface, would be incomplete from a product perspective. The migration of contacts onto the shared event-driven foundation must not change the user-visible contact activity feed.
