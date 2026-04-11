# Iteration 7.1: Journal-Contact Link Enhancements

**Status:** 🟢 IN PROGRESS (ITER7.1-001 Phase 1 complete)
**Dependencies:** Iteration 4 (journal-contact relationship model), Iteration 7 (calendar sync, attendee/invitee sync), Iteration 2.5 (ContactAvatar component)
**Goal:** Enrich journal-contact links with per-attendee status and role, add contact avatar visibility, and enable click-through navigation from journals to contacts.

## Overview

Journal-contact relationships currently store only the relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT) and the contact's name. This iteration adds two optional metadata fields to the relationship — **attendee status** and **event role** — and improves the UI with contact avatars and clickable navigation.

The attendee status field tracks each contact's RSVP/attendance state and syncs with Google Calendar's `responseStatus`. The role field captures event roles like Organiser (synced from Google) and Facilitator/Helper (manual-only). Both fields apply only to PARTICIPANT and INVITEE relationship types.

### Current Baseline

- `JournalContactRelationship` (domain entity) has: `journal_id`, `contact_id`, `relationship_type`, `created_at`.
- `journal_contact_relationships` table has a composite PK of `(journal_id, contact_id, relationship_type)`.
- `JournalContactRelationshipSchema` (API) returns: `id` (contact ID), `name`, `relationship_type`.
- `JournalContactBadge` renders contact badges with name and relationship type, with add/remove editing.
- `ContactAvatar` component already exists with `sm`/`md`/`lg` sizes and initials fallback.
- Google Calendar attendee sync already resolves attendee emails to contact IDs and creates INVITEE relationships.
- `GoogleEventAttendee` model has `email` and `response_status` (`needsAction`, `declined`, `tentative`, `accepted`).
- The journal `event_state` on `CalendarInfo` tracks the **user's own** participation state — the new per-contact status is a separate, per-attendee concept.

## Delivery Rules

These rules apply to every task below:

1. **Tests first:** write the failing tests for the slice before implementation.
2. **Green main:** do not merge a task unless relevant tests, linting, and type checks are passing.
3. **Reviewable PRs:** keep each PR to roughly `<= 10` files where practical; split tasks into smaller slices if needed.
4. **No hacks:** do not bypass domain validation or introduce temporary parallel data paths.
5. **MCP parity:** if status or role is meaningful in the UI, expose the same data through MCP.
6. **Record follow-up work here:** if a prerequisite or deferred enhancement is discovered mid-task, update this document.
7. **Every phase is shippable:** no phase may rely on a later phase to restore broken behaviour.

## Phase Completion Requirements

Every phase below must meet the same completion bar before merge:

- `main` remains green at the end of the phase.
- The phase includes explicit **unit, integration, and e2e coverage**.
- The e2e layer must be deterministic and fixture-driven.
- Linting, type checking, and the narrowest reliable test targets for the slice must pass.

## Sequencing Strategy

1. **Task 1** adds the status and role columns and domain model changes — everything else depends on this.
2. **Task 2** wires Google Calendar sync for both fields — depends on Task 1.
3. **Task 3** adds the background job for post-event status transition — depends on Task 1, can run in parallel with Task 2.
4. **Task 4** handles all UI enhancements (avatars, click-through, status/role display) — depends on Task 1, can start after Task 1 Phase 2.

## Dependency and Parallelisation Notes

- **Task 1** must land before **Tasks 2, 3, and 4**.
- **Task 2** and **Task 3** can run in parallel after **Task 1**.
- **Task 4** can start after **Task 1 Phase 2** (API contracts), and should incorporate Task 2/3 data once those land.
- No hard dependency on ITER7-006 (day-grouped list) — the journal list avatar display uses the existing list component and can adapt to the day-grouped layout later.

## Task Breakdown

### ITER7.1-001: Attendee Status and Role Data Model

**Objective:** Add `status` and `role` as optional fields to the journal-contact relationship at every layer: domain entity, database, API, MCP, and frontend types.
**Strategy:** Split into 2 phases so schema changes land before API/frontend contract changes.

**Relevant documents:**
- [Database Design — Migration Strategy](../architecture/database-design.md#migration-strategy)
- [Domain Architecture — Contacts Domain](../architecture/domain-architecture.md#contacts-domain)
- [API Design — Input Validation Guidelines](../architecture/api-design.md#input-validation-guidelines)
- [Testing Strategy — Three-Tier Testing Strategy](../architecture/testing-strategy.md#three-tier-testing-strategy)

#### Phase 1: Database Schema, Domain Entity, and Enum Definitions

**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [x] Add `AttendeeStatus` enum with values: `ATTENDING`, `ATTENDED`, `MAYBE`, `NO_REPLY`, `DECLINED`.
- [x] Add `ContactEventRole` enum with values: `ORGANISER`, `FACILITATOR_HELPER`.
- [x] Add nullable `status` (`VARCHAR(20)`) and `role` (`VARCHAR(20)`) columns to `journal_contact_relationships` table via Alembic migration.
- [x] Add CHECK constraints limiting `status` and `role` to valid enum values.
- [x] Update `JournalContactRelationship` domain entity with optional `status: AttendeeStatus | None` and `role: ContactEventRole | None` fields.
- [x] Domain validation: `status` and `role` are only permitted when `relationship_type` is `PARTICIPANT` or `INVITEE`. Setting them on `MENTION` or `ABOUT` relationships raises a validation error.
- [x] Update `SqlJournalContactRelationshipRepository` to read/write the new columns.
- [x] Existing relationships without status/role continue to work (NULL values are valid).

**Required Test Coverage:**
- **Unit:** ✅ enum validation, domain entity validation (status/role only on PARTICIPANT/INVITEE), rejection on MENTION/ABOUT.
- **Integration:** ✅ repository read/write tests with and without status/role values, CHECK constraint enforcement.
- **E2E:** deferred to Phase 2 — no user-visible surface changes yet.

#### Phase 2: API, MCP, and Frontend Type Contracts

**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] `JournalContactRelationshipSchema` (REST API) includes optional `status` and `role` fields.
- [ ] `JournalContactRelationshipAddAttributes` accepts optional `status` and `role` when adding contacts to journals.
- [ ] MCP `ContactRelationshipSchema` includes `status` and `role`.
- [ ] Frontend `JournalContactRelationship` TypeScript interface includes optional `status` and `role` fields.
- [ ] Frontend `AttendeeStatus` and `ContactEventRole` enums are defined in `types/journals.ts`.
- [ ] Journal converter populates status/role from domain entity to API response.
- [ ] Existing journal retrieval and contact-add flows remain backward-compatible (status/role default to null).

**Required Test Coverage:**
- **Unit:** API schema serialization with status/role present and absent, frontend type compilation.
- **Integration:** REST and MCP endpoint tests for journal retrieval and contact-add with status/role.
- **E2E:** add a contact to a journal with a status via the API and verify it appears in the journal detail response.

---

### ITER7.1-002: Google Calendar Attendee Status and Role Sync

**Objective:** Sync attendee `responseStatus` and `organizer` flag from Google Calendar into the journal-contact relationship status and role fields.
**Strategy:** Single phase — the transformer and outbox processor already handle attendee-to-contact resolution; this extends them with status/role mapping.

**Relevant documents:**
- [Integration Architecture — Inbound Sync Flow](../architecture/integration-architecture.md#inbound-sync-flow-pulling-data-from-external-systems)
- [Journals Product Specification — Google Calendar Sync](../product-specifications/journals-product-specification.md#google-calendar-sync-for-event-journals)

#### Phase 1: Transformer and Outbox Processor Extension

**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] `GoogleEventTransformer` maps attendee `responseStatus` to `AttendeeStatus`:
  - `accepted` → `ATTENDING`
  - `needsAction` → `NO_REPLY`
  - `tentative` → `MAYBE`
  - `declined` → `DECLINED`
  - absent/null → `NO_REPLY`
- [ ] `GoogleEventTransformer` maps attendee `organizer: true` to `ContactEventRole.ORGANISER`.
- [ ] Outbox event payload includes status and role for each resolved attendee contact.
- [ ] `JournalOutboxEventProcessor` persists status and role when creating/updating INVITEE relationships.
- [ ] Inbound sync updates existing relationships' status/role when Google attendee state changes (e.g., `needsAction` → `accepted`).
- [ ] Non-attendee contact relationships (PARTICIPANT from local, MENTION, ABOUT) are not affected by inbound sync.

**Required Test Coverage:**
- **Unit:** responseStatus-to-AttendeeStatus mapping (all 5 cases), organizer-to-role mapping, payload shaping with mixed attendee states.
- **Integration:** end-to-end inbound sync scenario: Google event with attendees → outbox → processor → verify status/role persisted on journal-contact relationships.
- **E2E:** deferred — the sync flow is backend-only; UI verification deferred to Task 4.

---

### ITER7.1-003: Post-Event Attended Status Transition

**Objective:** Automatically transition `ATTENDING` → `ATTENDED` for contacts on events that have passed, while allowing manual user overrides.
**Strategy:** Single phase — a periodic background job plus a manual API endpoint.

**Relevant documents:**
- [Integration Architecture — Event-Driven Scheduling](../architecture/integration-architecture.md#2-event-driven-scheduling)

#### Phase 1: Background Job and Manual Override

**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] A periodic background task (ARQ job or similar) identifies journal-contact relationships where:
  - `status = ATTENDING`
  - The journal's `event_date_range.end` is in the past
  - Transitions them to `ATTENDED`.
- [ ] The job is idempotent — re-running does not corrupt already-transitioned or manually-overridden statuses.
- [ ] The job only transitions `ATTENDING` → `ATTENDED`; other statuses (`MAYBE`, `NO_REPLY`, `DECLINED`) are not auto-transitioned.
- [ ] Users can manually set any valid status on a contact link via the existing add/update contact relationship API (including overriding `ATTENDED` back to another value if the attendance record was wrong).
- [ ] The job runs at a reasonable interval (e.g., hourly or daily) and processes events in bounded batches.
- [ ] Job execution is observable through standard logging.

**Required Test Coverage:**
- **Unit:** transition eligibility logic (only ATTENDING on past events), idempotency, batch boundary handling.
- **Integration:** real-database test: create journal with past event date and ATTENDING contacts → run job → verify ATTENDED. Verify MAYBE/DECLINED contacts are untouched.
- **E2E:** deferred — the background job has no direct UI entry point; manual override is covered by the API test.

---

### ITER7.1-004: UI Enhancements — Avatars, Click-Through, and Status/Role Display

**Objective:** Improve the journal-contact UI with contact avatars, clickable navigation to contact detail pages, and visible status/role information.
**Strategy:** Split into 2 phases so avatar and navigation work lands before status/role display polish.

**Relevant documents:**
- [Frontend Design — Component Architecture](../architecture/frontend-design.md#component-architecture)
- [Frontend Design — Accessibility Guidelines](../architecture/frontend-design.md#accessibility-guidelines)
- [Testing Strategy — Frontend Testing with React Testing Library](../architecture/testing-strategy.md#frontend-testing-with-react-testing-library)
- [Testing Strategy — End-to-End Testing with Playwright](../architecture/testing-strategy.md#end-to-end-testing-with-playwright)

#### Phase 1: Contact Avatars and Click-Through Navigation

**PR Size:** ~5-7 files

**Acceptance Criteria:**
- [ ] `JournalContactBadge` renders a small `ContactAvatar` (size `sm`) alongside each contact name.
  - Avatar data (first name, last name, image URL) should be included in the journal contact relationship API response or fetched efficiently.
- [ ] Contact names/badges in `JournalDetailView` are clickable links navigating to `/contacts/{id}`.
- [ ] Journal list view (`JournalList` / day-grouped list items) shows an abbreviated avatar stack:
  - Display the first 3 contact avatars in an overlapping/stacked layout.
  - Show a `+N` overflow indicator when a journal has more than 3 linked contacts.
- [ ] Avatars use the existing `ContactAvatar` component with initials fallback.
- [ ] Accessibility: avatar links have appropriate `aria-label` attributes, clickable elements are keyboard-navigable.
- [ ] The contact detail page link works correctly from both the journal detail view and the journal list view.

**Required Test Coverage:**
- **Unit:** avatar stack rendering with 0, 1, 3, and 5+ contacts; overflow indicator logic; link href generation.
- **Integration:** component tests for `JournalContactBadge` with avatar and click-through behaviour.
- **E2E:** open a journal detail, click a contact name, and verify navigation to the correct contact detail page. Verify avatar visibility on the journal list.

#### Phase 2: Status and Role Display in Journal UI

**PR Size:** ~4-6 files

**Acceptance Criteria:**
- [ ] `JournalContactBadge` displays the contact's status as a compact indicator (e.g., icon or coloured dot) alongside the name:
  - `ATTENDING` / `ATTENDED`: green indicator
  - `MAYBE`: amber/yellow indicator
  - `NO_REPLY`: grey/neutral indicator
  - `DECLINED`: red/strikethrough indicator
- [ ] Status indicator has a tooltip showing the full status label.
- [ ] Role is displayed as a subtle label or badge when present (e.g., "Organiser" tag on the badge).
- [ ] Status and role are visible in the journal detail view; the list view shows only avatars (no per-contact status) to keep the list compact.
- [ ] Users can edit a contact's status and role through the existing contact relationship editing flow (popover or inline controls).
- [ ] Accessibility: status indicators have screen-reader-accessible labels, role badges are properly labelled.

**Required Test Coverage:**
- **Unit:** status indicator rendering for all 5 statuses, role badge rendering, tooltip content.
- **Integration:** component tests for editing status/role through the contact badge UI.
- **E2E:** add a contact with a specific status to a journal, verify the status indicator renders correctly, edit the status, and verify the update.

## Data Model Summary

### Schema Changes

```sql
-- Add to journal_contact_relationships table
ALTER TABLE journal_contact_relationships
  ADD COLUMN status VARCHAR(20) NULL,
  ADD COLUMN role VARCHAR(20) NULL;

-- Check constraints
ALTER TABLE journal_contact_relationships
  ADD CONSTRAINT ck_journal_contact_relationships_status
    CHECK (status IN ('ATTENDING', 'ATTENDED', 'MAYBE', 'NO_REPLY', 'DECLINED')),
  ADD CONSTRAINT ck_journal_contact_relationships_role
    CHECK (role IN ('ORGANISER', 'FACILITATOR_HELPER'));
```

### Enum Definitions

```python
class AttendeeStatus(StrEnum):
    ATTENDING = "ATTENDING"
    ATTENDED = "ATTENDED"
    MAYBE = "MAYBE"
    NO_REPLY = "NO_REPLY"
    DECLINED = "DECLINED"

class ContactEventRole(StrEnum):
    ORGANISER = "ORGANISER"
    FACILITATOR_HELPER = "FACILITATOR_HELPER"
```

### Google Calendar Mapping

| Google `responseStatus` | `AttendeeStatus` |
|--------------------------|------------------|
| `accepted`               | `ATTENDING`      |
| `needsAction`            | `NO_REPLY`       |
| `tentative`              | `MAYBE`          |
| `declined`               | `DECLINED`       |
| absent / null            | `NO_REPLY`       |

| Google attendee field    | `ContactEventRole` |
|--------------------------|---------------------|
| `organizer: true`        | `ORGANISER`         |

### Avatar Data Requirements

The journal contact relationship API response needs to be extended to include avatar-relevant contact data:

```json
{
  "id": "42",
  "name": "John Doe",
  "relationship_type": "PARTICIPANT",
  "status": "ATTENDING",
  "role": "ORGANISER",
  "first_name": "John",
  "last_name": "Doe"
}
```

The `first_name` and `last_name` fields enable the `ContactAvatar` component to generate initials. If contact images are later supported, an `image_url` field can be added without breaking the contract.

## Known Follow-up Work

- **Outbound status sync:** Writing local status changes back to Google Calendar attendee `responseStatus` is out of scope for this iteration. Only inbound sync is supported.
- **Contact image URLs:** The `ContactAvatar` component supports images but the contact model does not yet store image URLs. Avatar display will use initials-only fallback until image support is added.
- **Day-grouped list adaptation:** When ITER7-006 Phase 2 lands the day-grouped journal list, the avatar stack rendering may need minor layout adjustments. This should be a follow-up within that task.
- **Bulk status editing:** Editing status/role for multiple contacts at once (e.g., "mark all as Attended") is deferred.

## Definition of Done for the Iteration

This iteration is complete when:

- Journal-contact relationships can store and display per-contact attendee status and event role
- Google Calendar attendee `responseStatus` and `organizer` flag sync into the relationship fields
- A background job transitions `ATTENDING → ATTENDED` for past events
- Journal contact badges show small avatars with initials fallback
- Journal list items show abbreviated stacked contact avatars
- Contact names on journals are clickable links to the contact detail page
- All completed phases keep `main` green with tests, linting, and type checks passing
