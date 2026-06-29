# Outdoor Logbook Improvements Product Specification

## Overview

This document defines the target product behaviour for a second wave of improvements to the
outdoor activity logbook. It is a product specification rather than a technical design.

It builds directly on the [Outdoor Logbook Product Specification](./outdoor-logbook-product-specification.md),
which established the outdoor activity type hierarchy
(FITNESS → OUTDOOR_ACTIVITY → BUSHWALKING / ABSEILING_TRIP / CANYONING / CLIMBING / KAYAKING /
CROSS_COUNTRY_SKIING / CAVING / CANOEING / SNORKELLING / DIVING / DOWNHILL_SKIING / OUTDOOR_TRAINING),
activity templates, gear items, gear maintenance, and the PDF logbook export.

Where the original outdoor logbook specification defined the foundations, this specification adds
the **review, surfacing, and reporting** layer on top: a way to find activities that are missing
detail, a richer PDF logbook, a logbook overview/dashboard page, and a durable template reference
on every abseiling activity.

This specification assumes the original Outdoor Logbook specification is fully delivered, and that
the SnipeIT gear integration (gear sync including checkout state) is in place.

## Reference and Alignment

This specification evolves and refines behaviour described in:

- `docs/product-specifications/outdoor-logbook-product-specification.md`
- `docs/product-specifications/snipe-it-integration-product-specification.md`
- `docs/product-specifications/immich-integration-product-specification.md`
- `docs/journal-system-specification.md`

Where earlier documents assume narrower behaviour, this specification should be treated as the
product-level refinement.

## Product Goals

The improvements should help the user:

1. Quickly find outdoor activities that are missing important detail, and fix them.
2. See, on every abseiling activity, which canyon/cave/climb template it was based on — even after
   the pitches have been edited — so the logbook is a reliable record of what has been done.
3. Produce a polished, navigable PDF logbook suitable for sharing and long-term record keeping.
4. Get an at-a-glance picture of upcoming trips, gear that is out, recent activity volume, and the
   canyons/caves/climbs they have logged.
5. Access every one of these capabilities through MCP as well as the web UI.

## Product Principles

1. **Surface gaps, don't enforce them:** Incompleteness is advisory. The system highlights
   activities that are likely missing detail; it never blocks saving an activity.
2. **The record is durable:** A template reference, once chosen, stays attached to the activity even
   when the copied pitch data is edited. The logbook reflects what was actually done.
3. **Build on what exists:** Reuse the existing journal subtype data model, template entity, gear
   items, contact relationships, GPX routes, Immich links, and the existing PDF export pipeline.
   This is an extension, not a parallel system.
4. **AI-first parity:** Every capability available in the UI is available through MCP, including the
   incomplete-activities review and the dashboard data.
5. **Outdoor-focused:** The dashboard and incomplete review concern outdoor activities specifically,
   not general fitness journals such as plain jogging.

## In Scope

- A combined **Outdoor Logbook overview page** containing:
  - An **incomplete outdoor activities** review list (with dismiss).
  - A **dashboard** (upcoming activities, checked-out gear, recent activity totals, abseil templates done).
- A durable **template reference on every abseiling-derived activity**, displayed even when modified.
- Consolidating the durable `template_id` reference onto the **ABSEILING_TRIP (`abseiling_data`)
  level** — where the abseil pitches already live — by adding it to `abseiling_data`, backfilling the
  existing canyoning/climbing/caving references, and retiring the per-subtype columns, plus adding an
  `abseiling` template type.
- **PDF logbook output improvements**: summary first, table of contents, linked participant and
  activity-type indexes, per-type icons, Immich album links, GPX track-log images, and a PDF outline.
- **MCP parity** for the incomplete review, the dashboard data, and template-on-journal retrieval.

## Out of Scope

- Changing the outdoor activity type hierarchy or dependency resolution.
- Changing how GPX routes are captured or parsed (only their rendering into the PDF is added).
- Building a SnipeIT integration (assumed already delivered); only consuming its checkout state.
- Automated/scheduled PDF generation — export remains user-initiated.
- General (non-outdoor) fitness dashboards.

---

## 1. Incomplete Outdoor Activities Review

### Purpose

Give the user a single place to find outdoor activity journals that are likely missing important
detail, so they can be completed shortly after the trip while memory is fresh.

### Where it lives

The incomplete review is a section of the **Outdoor Logbook overview page** (see Section 4), reached
as a **dedicated route** within the journals experience (a new page with its own sidebar entry under
Journals — not a calendar/list view-mode toggle). It is **not** part of the existing generic
review-items queue; it is its own outdoor-specific surface.

### Incompleteness rules

An outdoor activity journal is **incomplete** if it matches **any** of the following rules. Each
matched rule is shown as a distinct reason on the entry.

1. **No attributes set** — the journal has an outdoor activity subtype (BUSHWALKING, ABSEILING_TRIP,
   CANYONING, CLIMBING, KAYAKING, CROSS_COUNTRY_SKIING, CAVING, CANOEING) but the **subtype's own
   type-specific fields are all empty**. Only the subtype-specific attributes count — the shared
   OUTDOOR_ACTIVITY fields (weather, role, leadership, participant notes) do not satisfy this rule.
   For a journal with multiple subtypes, the rule is evaluated per subtype; the entry is flagged if
   any subtype has no attributes set.

   **Exemption:** subtypes that have **no type-specific attributes to fill** are exempt from this
   rule, because they could never satisfy it. Today these are **SNORKELLING, DIVING, and
   DOWNHILL_SKIING** (their data carries no subtype-specific fields). Such activities can still be
   flagged by the other rules (missing template / no participants).

2. **Abseiling activity missing a template** — the journal has abseiling data (i.e. ABSEILING_TRIP is
   in its dependency chain: ABSEILING_TRIP, CANYONING, CLIMBING, CAVING) and has **no associated
   template** (the consolidated `abseiling_data.template_id` is null). See Section 2 for the
   template-reference changes that make this rule a single-column check across all abseiling-derived
   types.

3. **No participants (except hiking)** — the journal is an outdoor activity **other than BUSHWALKING**
   (hiking) and has **no contacts in the PARTICIPANT relationship**. Bushwalking is exempt because
   solo hikes are common and expected.

### Behaviour

- The list shows each incomplete journal with its title, date, type icon(s), and the specific
  reason(s) it is flagged.
- Each entry links to the journal detail/edit screen so the user can fill in the missing data.
- The list updates as data is filled in — an entry stops matching a rule once the underlying gap is
  resolved.
- **Dismiss:** The user can dismiss an entire entry from the incomplete review (for example a genuine
  solo trip with no participants, or an activity that legitimately has minimal attributes). A
  dismissed entry no longer appears in the incomplete review regardless of which rules it matches.
  Dismissal is reversible (the user can un-dismiss), and is recorded against the journal.
- Scope: only the user's own outdoor activity journals are considered.

---

## 2. Durable Template Reference on Abseiling Activities

### Purpose

The user wants the logbook to show **which canyon/cave/climb template an abseiling activity was based
on** — even after the copied pitches have been edited for that specific trip — so the logbook is a
reliable record of canyons, caves, and climbs that have been done.

### Behaviour

- Every abseiling-derived activity stores a **durable reference to the template it was created from**
  (`template_id`). The reference belongs at the **ABSEILING_TRIP (`abseiling_data`) level**: the
  abseil **pitches already live there**, and because CANYONING, CLIMBING, and CAVING all have
  ABSEILING_TRIP in their dependency chain, every abseiling-derived journal already has an
  `abseiling_data` row. This specification therefore **consolidates `template_id` onto
  `abseiling_data`**, co-locating it with the pitch data it populated:

  | Type | Template reference today | After this spec |
  |------|--------------------------|-----------------|
  | CANYONING | on `canyoning_data` | on `abseiling_data` |
  | CLIMBING | on `climbing_data` | on `abseiling_data` |
  | CAVING | on `caving_data` | on `abseiling_data` |
  | ABSEILING_TRIP | none | on `abseiling_data` |

  The existing per-subtype `template_id` columns (canyoning/climbing/caving) are **backfilled into
  `abseiling_data` and then retired**, leaving a single source of truth. Because a journal has one set
  of abseil pitches regardless of how many subtypes it carries, a single `template_id` at this level
  is the natural fit, and the "missing template" incomplete rule (Section 1) and the templates-done
  dashboard widget (Section 4) each query one column.

- An **abseiling** template type is added so a plain abseiling trip can reference an appropriately
  typed template. The canyoning, caving, and climbing template types already exist. (An abseiling
  template uses the common template fields — name, region, description, and standard pitches — with no
  additional type-specific fields.) The consolidated `abseiling_data.template_id` may reference a
  template of any of these types, matching the journal's most specific abseiling-derived activity.

- **The reference persists independently of the pitch data.** When a template is selected, its
  standard pitches are copied into the journal as editable defaults (existing behaviour). Editing
  those pitches — or any other field — does **not** clear or change the `template_id`. The activity
  continues to display the template it came from.

- **Display:** The journal detail view shows the template name (linking to the template) for any
  abseiling activity that has a `template_id`, even when the journal's pitches differ from the
  template's. This is shown prominently as part of the activity's identity ("based on: Claustral
  Canyon").

- **PDF:** The template name is included in the PDF entry for the activity (the original spec already
  includes "template reference name where applicable"; this guarantees it is present for all
  abseiling-derived types).

- **MCP:** The template referenced by an abseiling activity is retrievable through MCP for any
  abseiling-derived journal (see Section 5).

---

## 3. PDF Logbook Output Improvements

The existing PDF logbook export (cover page, hierarchical entries, yearly summaries placed at the end,
a participant index, and an Immich shared link per entry) is improved as follows. There is **no**
table of contents, activity-type index, per-type icon, GPX map, or document outline today — those are
added here. All other existing export behaviour (scope, chronological ordering by topmost parent,
hierarchy, per-entry content, filters) is unchanged.

### 3.1 Summary first

The **yearly summary pages move to the start** of the document, immediately after the cover page and
before the journal entries. The summary gives the reader the high-level picture (totals per year,
leadership counts, abseil metres, abseils, setups, rescues) before the detail.

### 3.2 Table of contents

A **table of contents** follows the summary, listing the major sections (summary, each year of
entries / each top-level trip, indexes) with internal links to each.

### 3.3 Linked participant and activity-type indexes

The existing **participant index** is upgraded with internal links, and a **new activity-type index**
is added. Both list the relevant **activities by journal name**, with each name being an **internal
hyperlink** that jumps to that entry in the PDF.

- **Participant index:** keeps the existing threshold — contacts appearing as PARTICIPANT or INVITEE
  in **three or more** journal entries within the export scope (the current `min_appearances = 3`
  behaviour; "three or more", i.e. `>= 3`, not "more than three"). Each listed contact now shows the
  linked list of the journals they appear in (in addition to, or in place of, a bare count).
- **Activity-type index:** for each activity type, lists the journals of that type as linked names.

### 3.4 Per-type icons

Each journal type is shown with an **icon glyph matching the UI's journal-type iconography**, using
simple emoji/unicode glyphs (one distinct glyph per outdoor subtype). Icons appear next to type
labels on entries and in the indexes, giving the PDF the same visual type cues as the app without
embedding image assets.

### 3.5 Immich album links

When a journal has one or more associated **Immich albums**, the PDF includes the album link(s) for
that entry as clickable hyperlinks ("when present"). This formalises and guarantees the existing
shared-link rendering; entries without an album simply omit the link.

### 3.6 GPX track-log images

When a journal has an associated **GPX track log** (Route), the PDF includes a rendered **map image
of the track over a basemap** for that entry ("when present"). The map shows the track shape on real
map tiles. Entries without a GPX track omit the image.

Tiles come from **OpenStreetMap standard tiles**, reusing the source the in-app map already uses
(`frontend/src/components/journals/GPXTrackMap.tsx`), behind a **swappable tile-source adapter** so a
keyed topo provider can be substituted later. Because export is a **batch** operation that may render
many tracks at once, the adapter must respect OSM's tile-usage policy: an on-disk **tile cache**
(deduplicating tiles shared across entries/zooms), a polite **throttle** (≈2 tiles/second), and a
valid **User-Agent**. If tiles cannot be fetched at export time, the entry **falls back to plotting
the track on a plain background** rather than failing the export. OSM attribution is rendered on the
map image.

### 3.7 PDF document outline

The PDF includes a **document outline (bookmarks)** so readers can navigate via their PDF viewer's
outline panel. The outline mirrors the table of contents: summary, years/top-level trips (with nested
child activities reflecting the journal hierarchy), and the indexes.

---

## 4. Outdoor Logbook Overview Page (Dashboard)

### Purpose and placement

A single **Outdoor Logbook overview page** is the home for outdoor logbook review and reporting. It
contains the incomplete-activities review (Section 1) and a dashboard with the widgets below. It is
reachable as a **dedicated route** within the journals experience, with its own sidebar entry under
Journals (not a calendar/list view-mode toggle).

All dashboard stats and lists concern **outdoor activities only** (the OUTDOOR_ACTIVITY subtypes and
the supporting outdoor types), not general fitness journals such as plain jogging.

### Dashboard widgets

1. **Upcoming Activities** — the next month's upcoming outdoor activities, capped at **10**. This
   includes:
   - Future-dated OUTDOOR_ACTIVITY journals (journal date between today and one month ahead), and
   - OUTDOOR_PLANNING events whose start_time falls in the next month.

   Shown most-imminent first, each with its date, title, and type icon, linking to the journal.

2. **Gear currently checked out** — gear items whose state is **checked out** (sourced from the
   SnipeIT gear integration's checkout state). Each shows the gear item and, where available, when it
   was checked out. If nothing is checked out, an empty state is shown.

3. **Activity totals (recent)** — counts of outdoor activities **by journal type**, over two rolling
   windows shown together: the **last 30 days** and the **last 365 days**. This gives a quick sense
   of recent activity volume per type.

4. **Abseil templates done (by subtype)** — the list of **unique templates actually referenced by the
   user's abseiling activities** (the canyons / caves / climbs that have been done), **grouped by
   template type** (canyoning / caving / climbing / abseiling). This draws on the durable template
   references from Section 2. Each template links to the template and **shows a per-template
   done-count** — how many of the user's abseiling activities reference it — so the user can see not
   just which canyons/caves/climbs they have done but how many times.

---

## 5. MCP and AI-Agent Parity

All of the above must be available through MCP, following the existing journal/activity MCP patterns.
Specifically:

- **List incomplete outdoor activities** — an MCP tool returning the incomplete activities with the
  specific reason(s) flagged per entry (no attributes / missing template / no participants),
  mirroring the UI review, and respecting dismissals.
- **Dismiss / un-dismiss** an incomplete entry through MCP, consistent with the UI.
- **Outdoor dashboard data** — an MCP tool returning the dashboard contents: upcoming activities,
  checked-out gear, recent activity totals (last 30 days / last 365 days by type), and the unique
  abseil templates done by subtype.
- **Template-on-journal retrieval** — given an abseiling-derived journal, MCP can retrieve the
  referenced template (including its standard pitches), even when the journal's pitches have been
  modified.
- **Template references on create/update** — the generic `create_journal_entry` / `update_journal_entry`
  flow accepts and preserves the consolidated `abseiling_data.template_id` for any abseiling-derived
  journal (ABSEILING_TRIP, CANYONING, CLIMBING, CAVING).

The **PDF logbook export remains user-initiated in the UI** (consistent with the original outdoor
logbook specification); the data it is built from is retrievable through the existing and above MCP
tools.

---

## Success Criteria

This work is successful when the user can:

1. Open the Outdoor Logbook overview page and see every outdoor activity that is missing attributes,
   missing an abseiling template, or (non-hiking) missing participants — with the reason shown — and
   dismiss any entry that is genuinely fine.
2. See, on any abseiling activity and in the PDF, the template it was based on, even after editing the
   pitches for that trip.
3. Export a PDF logbook that opens with the summary, has a table of contents and a navigable outline,
   uses per-type icons, links participant and activity-type index entries to the activities, and
   includes Immich album links and GPX track maps where present.
4. See, on the dashboard, the next month's upcoming activities (max 10), the gear currently checked
   out, recent activity totals by type (last 30 days and last 365 days), and the unique abseil
   templates they have done grouped by type.
5. Do all of the above through MCP as well as the web UI.

## Delivery Notes

This specification defines target product behaviour. Delivery should be phased to preserve coherence;
each phase should deliver working, testable functionality with full UI and MCP support before moving
on.

Suggested phasing:

1. **Durable template reference:** consolidate `template_id` onto `abseiling_data` (backfill the
   existing canyoning/climbing/caving columns, then retire them) plus an `abseiling` template type,
   ensure it is preserved on edit, and display it on the journal and in MCP. This unblocks the
   "missing template" incomplete rule and the templates-done dashboard widget.
2. **Incomplete review:** the incomplete-activities list with the three rules, dismiss/un-dismiss, UI
   surface, and MCP tool.
3. **Dashboard:** the overview page widgets (upcoming, checked-out gear, recent totals, templates
   done) and the dashboard MCP tool.
4. **PDF improvements:** summary-first, table of contents, linked indexes, per-type icons, Immich
   links, GPX track maps, and document outline.

An incomplete phase (for example a template reference that is cleared when pitches are edited, an
incomplete review without dismiss, or a dashboard available in the UI but not MCP) would be incomplete
from a product perspective.
