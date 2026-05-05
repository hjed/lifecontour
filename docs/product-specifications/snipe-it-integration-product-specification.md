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

- **Outbound Only**: `GEAR_USAGE` journals sync **to** Snipe-IT as a "Checkout" to the mapped user.
- **Return Behavior**: We do not sync "Checkin" data back from Snipe-IT. The personal management system assumes items return to their **default location** in Snipe-IT when the usage period ends.
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
