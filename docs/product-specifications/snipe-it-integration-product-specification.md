# Snipe-IT Integration Product Specification

## Overview

This document defines the target product behaviour for the Snipe-IT integration. It is a product specification rather than a technical design.

The Snipe-IT integration connects the personal management system with a self-hosted Snipe-IT instance to provide comprehensive gear and asset management. It leverages the existing integration architecture (event bus, outbox pattern) and the outdoor logbook's gear management capabilities.

## Product Goals

1. Establish a bidirectional synchronization of gear items, treating Snipe-IT as the source of truth.
2. Enable seamless tracking of asset maintenance via the `GEAR_MAINTENANCE` journal type.
3. Facilitate automated gear checkouts in Snipe-IT when gear is used during recorded activities (via the new `GEAR_USAGE` journal type).
4. Integrate into the generic integrations dashboard seamlessly alongside Google and Strava.

## Product Principles

1. **Snipe-IT is the Source of Truth**: For gear items and maintenance records, Snipe-IT is the canonical record.
2. **Standard Integration Patterns**: Use the existing Redis Streams event bus and outbox pattern.
3. **Pluggable Integration UI**: The integration follows the generic integrations dashboard pattern.

---

## Part 1: Authentication & Configuration

Unlike Google or Strava which rely on fixed API endpoints, Snipe-IT is a self-hosted platform.

### Connection Setup

1. **Base URL Configuration**: The user must provide their Snipe-IT instance's Base URL during the setup flow on the integrations dashboard.
2. **OAuth Authentication**: The integration uses Snipe-IT's OAuth 2.0 (Passport) authentication. Once the Base URL is provided, the user is redirected to their Snipe-IT instance to authorize the application.
3. **User Mapping**: Because Snipe-IT checkouts require a specific user context, the system will prompt the user during setup to configure which Snipe-IT user they map to. This ensures all checkouts are assigned correctly.

---

## Part 2: Gear Items Sync (Two-Way)

Snipe-IT "Assets" map directly to the system's `gear_items` entity.

### Sync Rules

- **Snipe-IT is the Source of Truth**: New assets created in Snipe-IT sync to the personal management system as new gear items.
- **Two-Way Edits**: Any edits made to a mapped gear item in the personal management system will sync back to Snipe-IT, and vice versa.
- **Field Mapping**: Only the existing fields on the `gear_items` table are supported. No new fields will be added to accommodate Snipe-IT specific data.
- **Sync Mechanisms**:
  - The system relies on **Snipe-IT Webhooks** for real-time updates.
  - A **Periodic Sync** acts as a backup (similar to the Strava integration) to catch missed webhook events.

---

## Part 3: Asset Maintenance Sync (Two-Way)

Snipe-IT allows logging maintenance on assets. These map to the `GEAR_MAINTENANCE` journal type.

### Sync Rules

- **Mapping**: One Snipe-IT maintenance record equals one `GEAR_MAINTENANCE` journal entry.
- **Two-Way Sync**:
  - Creating a maintenance record in Snipe-IT creates a journal.
  - Creating a `GEAR_MAINTENANCE` journal in the personal management system creates a maintenance record in Snipe-IT.
  - Edits in either system are synchronized.
- **Deduplication**: Uses the `SyncMetadata` table to map the internal journal ID to the external Snipe-IT maintenance ID.

---

## Part 4: Gear Usage & Checkouts

A new journal type `GEAR_USAGE` will be introduced. This type can be added to travel, trip, or outdoor activity journals to record gear being utilized.

### Sync Rules

- **Outbound Only**: `GEAR_USAGE` journals sync **to** Snipe-IT as a "Checkout" to the mapped user. We do not sync inbound "Checkin" data **from** Snipe-IT.
- **Return Behavior**: The personal management system actively **checks the asset back in** to Snipe-IT when the usage period ends — Snipe-IT does not auto-return assets at `expected_checkin`, so the asset would otherwise stay checked out indefinitely. A check-in is triggered when any of the following occur:
  - The usage period ends — a periodic sweep checks in assets whose resolved check-in date has passed.
  - The `GEAR_USAGE` journal is deleted (the asset is returned).
  - The `GEAR_USAGE` journal is updated such that the usage period is now in the past.
  - On creation, if the check-in date is already in the past, the checkout and check-in are recorded immediately.

  Check-ins are idempotent (tracked via `SyncMetadata`), so an already-returned asset is never checked in twice.
- **Historical Dates**: Checkouts and check-ins are recorded in Snipe-IT on the dates the gear was actually used, so past usage (e.g. an imported logbook) shows real return dates.
  - `checkout_at`, `expected_checkin` and the check-in's `checkin_at` are the journal's **local** calendar dates, read in the event's timezone when it has one, otherwise the user's timezone, otherwise UTC. Journal dates are stored as the UTC instant of a local midnight, so taking their UTC date would land a day early east of UTC.
  - `checkin_at` is sent only once the check-in date has passed in every timezone (it is before today at UTC−12). Snipe-IT's server timezone is unknown, so a more recent return is stamped at the server's time rather than risk sending a date the server reads as the future. A check-in caused by deleting the journal is always stamped at server time.
  - The dates sent are recorded on the checkout and check-in `SyncMetadata` rows (`reference_data`).
- **Date Changes**: Snipe-IT cannot edit or delete its activity log, so updating a `GEAR_USAGE` journal only adds history that is missing:
  - If the checkout date changes after the asset was checked in, a new checkout and check-in are recorded on the new dates. The earlier pair stays in Snipe-IT.
  - A check-in that has not happened yet uses the updated check-in date.
  - An update that arrives while another worker is recording the same journal's checkout or check-in is retried once that finishes, so a newer date is never dropped. A lock left by a worker that crashed is retaken after five minutes, and the event is still being retried at that point.
  - Not re-recorded: a change to only the check-in date of an already checked-in journal; a checkout recorded before dates were stored; and a checkout whose check-in failed terminally (403/404), since the asset may still be checked out.
  - A checkout date changed while the asset is still checked out is re-recorded once the asset is checked in, whether by that update, a later one or the periodic sweep. Snipe-IT refuses to check out an asset that is already out, so the corrected pair follows the return.
- **Existing Snipe-IT History**: History already in Snipe-IT (for example checkouts entered by hand before a logbook import) is linked rather than recorded twice.
  - Before recording a checkout, the asset's Snipe-IT activity log is searched for a checkout to the mapped user on the same date (Snipe-IT's server date). A match is linked on the checkout `SyncMetadata` row (`snipeit_log_id`) and nothing is posted.
  - When the checkout was linked, a check-in on the journal's check-in date that was logged after that checkout is linked the same way; otherwise the check-in is posted.
  - A log entry already linked to another journal is never reused, so two journals using the same asset on the same day each get their own record.
  - The search reads the newest 500 entries per asset and action type.
- **Buffer Dates**:
  - Users can specify a separate start and end date for the gear checkout to allow for buffer (e.g., packing the day before).
  - **Default**: The buffer dates explicitly default to the journal's event dates if not modified by the user.
  - This UI element is conditionally enabled only when the Snipe-IT integration is connected.

---

## Part 5: UI & Dashboard Integration

### Generic Integrations Dashboard

Snipe-IT will be added to the generic integrations dashboard API (`GET /api/integrations`).

- **Capabilities**: `gear_sync`, `maintenance_sync`, `checkout_sync`.
- **Settings Modal**: The Snipe-IT panel will include a settings modal to configure:
  - Instance Base URL.
  - Mapped Snipe-IT User ID.

### Journal Details & External Links

Like Google Calendar and Strava, journals linked to Snipe-IT maintenance or checkouts will display external system links on the detail page, directing the user to the specific asset or maintenance record in their Snipe-IT instance.
