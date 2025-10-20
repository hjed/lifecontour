# Iteration 7: Google Calendar Integration

**Status:** 🟡 PLANNED
**Dependencies:** Iteration 4 (Journal Core with EVENT type)
**Goal:** Integrate Google Calendar with bidirectional sync and advanced calendar features

## Overview

This iteration implements Google Calendar integration following the [journal system specification](../journal-system-specification.md#google-calendar-integration) and [integration architecture](../architecture/integration-architecture.md):

**Core Features:**
- Google Calendar API integration (extends existing Google Contacts integration)
- Bidirectional calendar synchronization (Journal ↔ Google Calendar)
- EVENT journal sync to Google Calendar
- Calendar views (month, week, day, agenda)
- Meeting preparation with contact context
- Calendar analytics and scheduling insights
- ARQ worker for background sync following isolated worker architecture

**Integration Behavior:**
- **Sync Direction:** Bidirectional (Journal ↔ Google Calendar)
- **Sync Trigger:** If `journal.calendar_id` references a calendar with `is_synced_to_google = true`
- **Sync Data:** title, event_date_range, start_time, end_time, location
- **Invitees:** If `sync_invitees = true`, sync invitees as calendar attendees
- **Recurrences:** Each occurrence is a separate journal entry

**Note:** There is no separate calendar domain - EVENT journals serve as calendar events.

## Prerequisites

- Iteration 4 completed (EVENT journal type with calendar support)
- Google integration architecture established (from Iteration 2)
- Dishka dependency injection and ARQ workers operational
- MeiliSearch indexing for EVENT journals

## Tasks

### ITER7-001: Google Calendar API Extension 🟡 PLANNED
**Description:** Extend existing Google integration for Calendar API v3
**Strategy:** Single task for API foundation
**Specification Reference:** [Google Calendar Integration](../journal-system-specification.md#google-calendar-integration)

**PR Size:** ~6 files (Google API client extension, calendar models, tests)

**Acceptance Criteria:**
- [ ] Extend `GoogleAPIClient` in `integration_workers/google_contacts/` for Calendar API v3:
  - List calendars
  - Get calendar details
  - List events (with pagination)
  - Get event details
  - Create event
  - Update event
  - Delete event
  - Watch calendar for changes (webhook setup)
- [ ] Define Pydantic models for Google Calendar API responses:
  - `GoogleCalendar` (id, summary, description, timezone, color)
  - `GoogleEvent` (id, summary, description, start, end, location, attendees, recurrence)
- [ ] Implement `GoogleCalendarTransformer`:
  - Map Google Calendar events to EVENT journals
  - Map EVENT journals to Google Calendar events
  - Handle timezone conversion (Google → UTC → User timezone)
  - Transform attendees to contact relationships (INVITEE type)
  - Handle recurrence rules (each occurrence as separate journal)
- [ ] Add Google Calendar scopes to OAuth flow
- [ ] Write integration tests for Calendar API client
- [ ] Document Google Calendar API integration in code comments

**Google Calendar Scopes:**
- `https://www.googleapis.com/auth/calendar.readonly` (read events)
- `https://www.googleapis.com/auth/calendar.events` (read/write events)

### ITER7-002: Calendar-to-Journal Sync 🟡 PLANNED
**Description:** Implement bidirectional sync between Google Calendar and EVENT journals
**Strategy:** Single task for sync logic
**Specification Reference:** [Sync Behavior](../journal-system-specification.md#google-calendar-integration)

**PR Size:** ~7 files (sync service, conflict resolution, tests)

**Acceptance Criteria:**
- [ ] Create `GoogleCalendarSyncService` in `integration_workers/google_contacts/`:
  - `sync_calendar_to_journals(calendar_id)` - Import Google Calendar events as EVENT journals
  - `sync_journal_to_calendar(journal_id)` - Export EVENT journal to Google Calendar
  - `bidirectional_sync()` - Sync changes in both directions
  - Conflict resolution using ETags (last-write-wins with user confirmation)
- [ ] Implement sync logic:
  - If `calendar.is_synced_to_google = true`, sync EVENT journals to Google Calendar
  - If `sync_invitees = true`, sync INVITEE relationships as calendar attendees
  - Handle recurrences (each occurrence as separate journal entry)
  - Detect and resolve conflicts (Google vs Journal changes)
- [ ] Add sync state tracking:
  - `google_event_id` in `journal_calendar_info` table
  - `last_synced_at` timestamp
  - `sync_status` (synced, pending, conflict, error)
- [ ] Implement conflict resolution:
  - Detect conflicts using ETags
  - Prompt user for resolution (Google vs Journal)
  - Apply user choice and update both systems
- [ ] Add change events for sync operations
- [ ] Write unit tests for sync logic
- [ ] Write integration tests for bidirectional sync
- [ ] Document sync algorithm in code comments

**Sync Behavior:**
- Journal → Google: When EVENT journal with synced calendar is created/updated
- Google → Journal: When Google Calendar event is created/updated (via webhook)
- Conflict: When both systems have changes since last sync
- Resolution: User chooses which version to keep

### ITER7-003: Calendar UI Components 🟡 PLANNED
**Description:** Build calendar views and event management UI
**Strategy:** Single task for calendar UI
**Specification Reference:** [Calendar View Component](../journal-system-specification.md#calendar-view-component)

**PR Size:** ~8 files (calendar views, event forms, components, tests)

**Acceptance Criteria:**
- [ ] Create `CalendarView` component in `frontend/src/components/journals/`:
  - Month view (grid layout with events)
  - Week view (timeline with events)
  - Day view (detailed timeline)
  - Agenda view (list of upcoming events)
  - Color-coding by calendar (primary) or tag (secondary)
  - Type icons for visual identification
  - Click to view/edit event (inline editing)
  - Drag-and-drop date changes
  - Today button and navigation
- [ ] Create `EventForm` component (extends journal form):
  - Calendar selector (with sync toggle)
  - Date/time picker with timezone support
  - All-day event toggle
  - Location field
  - Invitee management (sync toggle)
  - Recurrence pattern selector (future enhancement)
- [ ] Integrate calendar views into journal UI:
  - Add calendar view tab to journal list
  - Filter integration (types, contacts, tags, calendar)
  - Quick event creation from calendar view
- [ ] Implement Google Calendar sync UI:
  - Sync status indicator
  - Manual sync trigger
  - Conflict resolution dialog
- [ ] Write Jest unit tests for components
- [ ] Write React Testing Library tests for user interactions
- [ ] Document calendar UI patterns in code comments

**Calendar View Features:**
- Multiple view modes (month, week, day, agenda)
- Color-coded events by calendar
- Drag-and-drop rescheduling
- Inline event editing
- Quick event creation
- Filter integration

### ITER7-004: Calendar ARQ Worker 🟡 PLANNED
**Description:** Implement background sync worker for Google Calendar
**Strategy:** Single task for ARQ worker
**Specification Reference:** [Integration Architecture](../architecture/integration-architecture.md)

**PR Size:** ~5 files (ARQ task, worker setup, webhook handling, tests)

**Acceptance Criteria:**
- [ ] Create ARQ task `sync_google_calendar(ctx, user_id, calendar_id)` in `integration_workers/google_contacts/worker.py`:
  - Use Dishka DI for service injection
  - Idempotent operation (safe for redelivery)
  - Bidirectional sync (Google ↔ Journal)
  - Conflict detection and resolution
  - Error handling with retry logic (exponential backoff)
  - Dead letter queue for failed syncs
- [ ] Implement webhook handling for real-time sync:
  - Google Calendar push notifications
  - Webhook endpoint for calendar change events
  - Trigger sync on calendar changes
  - Verify webhook authenticity
- [ ] Add worker monitoring:
  - Sync status tracking (in_progress, completed, failed)
  - Sync duration metrics
  - Event count metrics
  - Conflict count metrics
  - Error logging with context
- [ ] Update worker Dockerfile with Calendar API dependencies
- [ ] Write integration tests for ARQ worker and webhook handling
- [ ] Document worker deployment and webhook setup in code comments

**Webhook Flow:**
1. User enables Google Calendar sync
2. System registers webhook with Google Calendar API
3. Google sends push notification on calendar changes
4. Webhook endpoint receives notification
5. ARQ task triggered for sync
6. Bidirectional sync with conflict resolution

### ITER7-005: Advanced Calendar Features 🟡 PLANNED
**Description:** Implement meeting preparation and calendar analytics
**Strategy:** Single task for advanced features
**Specification Reference:** [Advanced Features](../journal-system-specification.md#google-calendar-integration)

**PR Size:** ~6 files (meeting prep, analytics, AI features, tests)

**Acceptance Criteria:**
- [ ] Create `MeetingPreparation` component:
  - Attendee context (recent journals, contact info)
  - Recent interaction history
  - Meeting agenda templates
  - Pre-meeting briefing generation
  - Post-meeting follow-up tracking
- [ ] Implement calendar analytics:
  - Time spent in meetings by type
  - Meeting frequency by contact
  - Calendar utilization (busy vs free time)
  - Meeting effectiveness scoring
  - Scheduling pattern analysis
- [ ] Add MCP tools for meeting assistance:
  - `prepare_meeting(event_id)` - Generate meeting preparation briefing
  - `find_meeting_time(attendees, duration)` - Find optimal meeting time
  - `analyze_schedule(date_range)` - Schedule analysis and insights
  - `get_meeting_context(event_id)` - Get attendee context and history
- [ ] Implement smart scheduling features:
  - Conflict detection and resolution
  - Optimal time suggestions
  - Time blocking recommendations
- [ ] Write unit tests for analytics and meeting prep
- [ ] Write integration tests for MCP tools
- [ ] Document advanced features in code comments

**Meeting Preparation Features:**
- Attendee context from contacts and journals
- Recent interaction history
- Meeting agenda templates
- Pre-meeting briefing
- Post-meeting follow-up

## Architecture Notes

**No Separate Calendar Domain:**
- EVENT journals serve as calendar events
- No separate calendar entity or domain
- Calendar metadata stored in `calendars` table (name, color, sync settings)
- EVENT type journals reference calendar via `calendar_id`

**Bidirectional Sync:**
- Journal → Google: When EVENT journal with synced calendar is created/updated
- Google → Journal: When Google Calendar event is created/updated (via webhook)
- Conflict resolution using ETags (last-write-wins with user confirmation)
- Change tracking with source attribution ('google' vs 'manual')

**Webhook Architecture:**
- Google Calendar push notifications for real-time sync
- Webhook endpoint validates authenticity
- ARQ task triggered for background sync
- Idempotent operations for safe redelivery

**Timezone Handling:**
- All dates stored in UTC in database
- User timezone preference for display
- Google Calendar timezone conversion
- All-day event handling

**Recurrence Handling:**
- Each occurrence is a separate journal entry
- Parent-child relationships for recurring events
- Future enhancement: Recurrence pattern support

**Integration with Existing Features:**
- Extends Google Contacts integration (same worker)
- Uses existing journal UI with calendar views
- MeiliSearch indexing for EVENT journals
- Contact relationships for invitees

## Testing Strategy

**Unit Tests:**
- Google Calendar API data transformation
- Timezone conversion logic
- Conflict detection and resolution
- Sync state management

**Integration Tests:**
- Bidirectional sync with mock Google API
- Webhook handling and verification
- ARQ worker with Dishka DI
- Calendar views with EVENT journals

**E2E Tests (Playwright):**
- Enable Google Calendar sync
- Create EVENT journal and verify sync to Google
- Update Google Calendar event and verify sync to journal
- Resolve sync conflict
- View calendar in different modes (month, week, day, agenda)

## Success Criteria

- ✅ Google Calendar API integration (extends existing Google integration)
- ✅ Bidirectional sync (Journal ↔ Google Calendar)
- ✅ EVENT journal sync to Google Calendar
- ✅ Calendar views (month, week, day, agenda)
- ✅ Webhook support for real-time sync
- ✅ Conflict resolution with user confirmation
- ✅ Meeting preparation with contact context
- ✅ Calendar analytics and insights
- ✅ MCP tools for meeting assistance
- ✅ ARQ worker following isolated worker architecture
- ✅ All tests passing (unit, integration, e2e)
- ✅ System in working state after each PR

## Next Steps

**Immediate:** Iteration 8 (Advanced Features)
- Cross-domain analytics and insights
- Advanced search and filtering
- Data export and portability
- Performance optimization

**Future Enhancements:**
- Recurrence pattern support (RRULE)
- Multiple Google accounts per user
- Calendar sharing and collaboration
- Meeting effectiveness scoring
