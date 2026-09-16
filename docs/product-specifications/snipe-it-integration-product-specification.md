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
    - Configure Snipe-IT's **General** (Slack-compatible) webhook with the URL shown in the integration settings (`/api/integrations/snipeit/webhook`).
    - Snipe-IT sends Slack-format messages and only on checkout, checkin, acceptance and audit. Each message that links an asset (`<base>/hardware/<id>`) triggers a sync of that asset; the settings-page test message and non-asset notifications are acknowledged and ignored.
  - A **Periodic Sync** acts as a backup (similar to the Strava integration) to catch missed webhook events, and is the only path for asset creation, edits and maintenance changes, which Snipe-IT does not send as webhooks.
- **Text Encoding**: Snipe-IT HTML-escapes text in API responses but stores what it is sent, so asset names, models, manufacturers, serials and asset tags are decoded once on import and sent unescaped.

---

## Part 3: Asset Maintenance Sync (Two-Way)

Snipe-IT allows logging maintenance on assets. These map to the `GEAR_MAINTENANCE` journal type.

### Sync Rules

- **Mapping**: One Snipe-IT maintenance record equals one `GEAR_MAINTENANCE` journal entry.
- **Two-Way Sync**:
  - Creating a maintenance record in Snipe-IT creates a journal.
  - Creating a `GEAR_MAINTENANCE` journal in the personal management system creates a maintenance record in Snipe-IT.
  - Edits to a journal created in the personal management system are pushed to its Snipe-IT record.
  - Edits to a journal imported from Snipe-IT are pushed to the record it was imported from (`snipeit_maint:{id}` on its external event link), even when an earlier echo left a copy of that record in Snipe-IT.
- **Maintenance Types**: Every Snipe-IT maintenance kind has its own `GEAR_MAINTENANCE` type, so a record's kind survives import and push unchanged. Snipe-IT (up to 8.4) stores the kind as the free-text `asset_maintenance_type`.

  | Snipe-IT | Journal `maintenance_type` |
  |---|---|
  | Maintenance | routine maintenance |
  | Repair | repairing gear |
  | PAT Test | routine inspection |
  | Upgrade | upgrading gear |
  | Calibration | calibration |
  | Software Support | software support |
  | Hardware Support | hardware support |
  | Configuration Change | configuration change |

  - `retiring gear` has no Snipe-IT kind and is sent as `Maintenance`. A re-import keeps `retiring gear` while the record is still `Maintenance`; any other kind replaces it.
  - An unknown or missing kind imports as `routine maintenance`.
  - Imports synced under the earlier, lossy mapping are re-synced and corrected by the next full maintenance sync.
- **Local-Only Fields**: Snipe-IT has no activity types or retirement reason, so a re-import leaves a journal's `activity_types` and `retirement_reason` untouched.
- **Deduplication**: Uses the `SyncMetadata` table to map the internal journal ID to the external Snipe-IT maintenance ID.
  - **Retries**: A push claims the record it creates before posting it. The journal's claim row (`snipeit_maintenance_claim`) holds the asset, title and start date sent, and is replaced by the record's own row once that is written. An attempt that fails after posting keeps its claim, marked failed: Snipe-IT may have created the record even though the response was lost.
  - A push that finds its journal's claim still pending, and touched in the last five minutes, is retried later rather than posting a second record. A claim left by a worker that crashed is retaken after that.
  - Before posting, the asset's Snipe-IT maintenances are searched for a record with the same title (HTML-decoded) and start date. Both the values being sent now and those an earlier failed attempt sent are checked, so a journal edited between attempts still finds its record. The first match no other journal holds is linked instead of posting a new record, and is not modified. A record entered by hand with the same title and date is linked the same way.
  - A record is held when a sync row names it: another journal's record, or an import, which belongs to its imported journal. It is also held when it matches a claim of another of the user's journals, since that journal's failed attempt may have created it.
  - The search reads the first 500 records per asset. When the maintenance list cannot be read (403/404), the record is posted without linking.
- **Loop Prevention**: A record must never travel back to the system it came from.
  - A journal imported from Snipe-IT (linked to the synthetic Snipe-IT maintenance calendar) is never created in Snipe-IT again.
  - A journal update the inbound sync applied (`changed_by` is `snipeit_maintenance`) is not pushed; only a user's edit is.
  - A push of the record's own state changes nothing when it is next imported, so no journal update follows it.
  - A Snipe-IT record created from a journal is skipped by the inbound sync rather than imported as a second journal.
- **Dates**: Snipe-IT maintenance dates are calendar dates. An import stores each as the instant of local midnight in the user's configured timezone (UTC when none is set), the zone every push reads dates in (see Part 4), so a round trip never moves a date.
  - The zone is part of an import's version hash, so changing the user's timezone re-anchors imported dates at the next full maintenance sync. Until then a push reads them in the new zone, like every other date sent to Snipe-IT.
- **Text Encoding**: Snipe-IT HTML-escapes text in API responses but stores what it is sent, so titles and notes are decoded once on import and sent unescaped.

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
  - Snipe-IT stores dates and times without a timezone, in its server's zone, and its API does not say which zone that is. Every date and time sent to Snipe-IT is therefore read in the **user's configured timezone** (UTC when unset), even for an event recorded in another zone. One zone keeps a checkout's time and the date its log entry is matched on (see Existing Snipe-IT History) on the same day. Journal dates are stored as the UTC instant of a local midnight, so taking their UTC date would land a day early east of UTC.
  - `checkout_at` is the local date **and time** of the checkout (`YYYY-MM-DD HH:MM:SS`); Snipe-IT keeps it as the asset's last checkout and the checkout log's date. `expected_checkin` and the check-in's `checkin_at` are local calendar dates.
  - Snipe-IT's check-in API only accepts a date: it adds its own current time to `checkin_at`, and only dates the check-in's log entry with it. The asset's own last check-in is always set to the moment the check-in is posted, and a checkout sets its last checkout to `checkout_at` even when that is older than the asset's real last use.
  - **Asset dates are restored**: before checking an asset out, the asset's last checkout and last check-in are read and kept on the checkout `SyncMetadata` row (`asset_dates_before`). After the check-in is posted, both are set (`PATCH /hardware/{id}`) to the later of that kept value and the usage's own checkout and check-in time, so importing an older trip never makes an asset look less recently used.
    - The dates are kept before the checkout is posted, so a checkout whose response was lost, and is linked when retried, still restores them. A checkout re-recorded on the same asset (its date changed, or retried) keeps the dates read before its first attempt; one moved to another asset reads that asset's.
    - A checkout recorded before dates were kept, or linked to history the worker did not post, is restored against the asset's dates read just before the check-in. Such a linked checkout's last checkout is left as Snipe-IT has it.
    - Restoring is best-effort: the check-in is already recorded, so a failed read or update leaves only these dates wrong. A check-in caused by deleting the journal leaves them as Snipe-IT set them.
  - `checkin_at` is sent only once the check-in date has passed in every timezone (it is before today at UTC−12). Snipe-IT's server timezone is unknown, so a more recent return is stamped at the server's time rather than risk sending a date the server reads as the future. A check-in caused by deleting the journal is always stamped at server time.
  - The dates sent are recorded, as dates, on the checkout and check-in `SyncMetadata` rows (`reference_data`). Changing only the time of a checkout on the same day is therefore not re-recorded.
- **Date Changes**: Snipe-IT cannot edit or delete its activity log, so updating a `GEAR_USAGE` journal only adds history that is missing:
  - If the checkout date changes after the asset was checked in, a new checkout and check-in are recorded on the new dates. The earlier pair stays in Snipe-IT.
  - A check-in that has not happened yet uses the updated check-in date.
  - An update that arrives while another worker is recording the same journal's checkout or check-in is retried once that finishes, so a newer date is never dropped. A lock left by a worker that crashed is retaken after five minutes, and the event is still being retried at that point.
  - Not re-recorded: a change to only the check-in date of an already checked-in journal; a checkout recorded before dates were stored; and a checkout whose check-in failed terminally (403/404), since the asset may still be checked out.
  - A checkout date changed while the asset is still checked out is re-recorded once the asset is checked in, whether by that update, a later one or the periodic sweep. Snipe-IT refuses to check out an asset that is already out, so the corrected pair follows the return.
- **Existing Snipe-IT History**: History already in Snipe-IT (for example checkouts entered by hand before a logbook import) is linked rather than recorded twice.
  - Before recording a checkout, the asset's Snipe-IT activity log is searched for a checkout to the mapped user on the same date (Snipe-IT's server date). A match is linked on the checkout `SyncMetadata` row (`snipeit_log_id`) and nothing is posted.
  - When the checkout was linked, a check-in on the journal's check-in date that was logged after that checkout is linked the same way; otherwise the check-in is posted.
  - A log entry already linked to another of the user's journals is never reused, so two journals using the same asset on the same day each get their own record. Other users' links are ignored: log ids are only unique within a Snipe-IT instance.
  - The search reads the newest 500 entries per asset and action type.
  - A match is claimed on the journal's sync row before anything is recorded, under a per-asset lock, so journals processed at the same time cannot both link one entry.
  - Linking is best-effort: if the activity report cannot be read (the API key lacks permission, the Snipe-IT version has no report, or the response is unexpected), the history is recorded as usual.
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
