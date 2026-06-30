# Iteration 16: Outdoor Logbook Improvements

**Status:** 🔵 PLANNED — sub-iterations and PR-sized phases defined; ready to implement.
**Dependencies:** Iteration 9 (Outdoor Logbook — activity subtypes, abseil pitches, activity templates, gear items, PDF export), Iteration 10 (SnipeIT integration — gear checkout state), Iteration 11 (Immich integration — album links), Iteration 12 (Activity History — provenance, used for dismissal/auditing). Assumes the outdoor logbook and SnipeIT gear-checkout sync are delivered.
**Goal:** Add the **review, surfacing, and reporting** layer on top of the existing outdoor logbook: find activities missing important detail, make every abseiling activity carry a durable template reference, add an outdoor logbook overview/dashboard page, and produce a polished, navigable PDF logbook — all with full UI and MCP parity.

## Overview

The outdoor logbook (Iteration 9) established the activity type hierarchy, abseil pitch model, activity templates, gear items, and a first PDF export. This iteration builds the layer that makes the logbook *useful as a record*: it surfaces incomplete activities so they can be completed while memory is fresh, guarantees every abseiling activity remembers which canyon/cave/climb template it was based on (even after the pitches are edited for that trip), gives the user an at-a-glance dashboard of upcoming trips / checked-out gear / recent volume / canyons-done, and upgrades the PDF into a navigable, shareable document.

This iteration realises the [Outdoor Logbook Improvements Product Specification](../product-specifications/outdoor-logbook-improvements-product-specification.md). It does **not** change the activity type hierarchy or dependency resolution, the way GPX routes are captured, or the SnipeIT integration — it consumes and reports on what those already produce.

The work is split into four independently shippable **sub-iterations**, each a coherent, user-facing deliverable with full UI + MCP support, and each broken into **PR-sized phases** (≤500-line diffs, green and deployable `main` per phase), mirroring the phase breakdown in [Iteration 14](./iteration-14-worker-standardisation.md). A phase need not expose a user-facing change on its own — the sub-iteration is the shippable unit — but every phase must leave `main` green with no broken or half-wired runtime path (shared/data layer lands additive-first, then service/MCP, then UI).

## Reference Documents

- **[Outdoor Logbook Improvements Product Specification](../product-specifications/outdoor-logbook-improvements-product-specification.md)** — approved product behaviour for this iteration (the spec this document delivers)
- **[Outdoor Logbook Product Specification](../product-specifications/outdoor-logbook-product-specification.md)** — the foundation this builds on (type hierarchy, abseil pitches, templates, gear, PDF export)
- **[SnipeIT Integration Product Specification](../product-specifications/snipe-it-integration-product-specification.md)** — gear checkout state consumed by the dashboard
- **[Immich Integration Product Specification](../product-specifications/immich-integration-product-specification.md)** — album links consumed by the PDF
- **[Activity History Product Specification](../product-specifications/activity-history-product-specification.md)** — provenance model; dismissals are recorded against the journal
- **[Domain Architecture](../architecture/domain-architecture.md)** — domain-driven patterns, ports & adapters, enum patterns
- **[API Design](../architecture/api-design.md)** — REST + FastMCP patterns, JSON API compliance
- **[Database Design](../architecture/database-design.md)** — transaction management (`@transactional` / `unit_of_work`), schema standards
- **[Frontend Design](../architecture/frontend-design.md)** — Next.js, shadcn/ui, forms, responsive design
- **[Testing Strategy](../architecture/testing-strategy.md)** — backend unit/integration (conftest), frontend RTL, Playwright e2e
- **[Code Quality Standards](../code-quality-standards.md)** — ruff/mypy/pytest, frontend `quality:check`

### External Documentation

- **ReportLab** — https://docs.reportlab.com/ (platypus flowables, `<a>`/`linkURL` internal anchors, `outlineEntry`/bookmarks, drawing images)
- **gpxpy** — https://github.com/tkrajina/gpxpy (already used in `gpx_parser.py` for track coordinates/stats)
- **FastMCP** — https://gofastmcp.com/llms.txt (tool registration, error handling) — context7 `websites/gofastmcp`
- **Alembic** — https://alembic.sqlalchemy.org/en/latest/ (use the `creating-migrations` skill for sequential numbering) — context7 `sqlalchemy/alembic`
- **SQLAlchemy Core** — https://docs.sqlalchemy.org/en/20/ (use the `writing-sql` skill before authoring queries)

## Delivery Rules

These apply to every sub-iteration (and every phase once broken out):

1. **Tests first:** write the failing tests for the slice before implementation (TDD red → green → refactor), per CLAUDE.md.
2. **Green main:** do not merge unless relevant backend tests, `ruff`, `mypy`, and frontend `pnpm quality:check` pass.
3. **PR size ≤ 500 lines:** keep each phase within a ~500-line diff (implementation + tests); split further if it grows. Every phase leaves `main` green and deployable — additive shared/data-layer code lands behind no runtime path until a later phase wires it in; migrate-and-delete any duplicate in the same phase.
4. **UI + MCP parity per sub-iteration:** no sub-iteration is "done" until the capability exists in both the web UI and MCP (except PDF export, which remains UI-initiated with its data MCP-retrievable, consistent with the original spec).
5. **Build on what exists:** reuse the existing subtype data models, `ActivityTemplate`, gear items, `JournalContactRelationship`, GPX `Route`, the `sync_metadata` Immich/SnipeIT link store, the activity-stats helpers, and the existing PDF pipeline. This is an extension, not a parallel system.
6. **Surface, don't enforce:** incompleteness is advisory and never blocks saving an activity.
7. **The record is durable:** a chosen `template_id` is never cleared by editing the copied pitch data.
8. **Transactions in the service layer:** writes (dismissals, `template_id` persistence) commit via `@transactional` / `unit_of_work`; controllers and MCP tools never open transactions.
9. **Reads through repositories:** no SQL in controllers or MCP tools.

## Grounding Findings (shaped the sub-iteration boundaries)

Established by reviewing the current code; these drive the scope and acceptance criteria below.

- **`template_id` is currently split across three subtype tables and should be consolidated to the abseiling level.** `CanyoningData` (mig `0056`), `ClimbingData` (mig `0058`), and `CavingData` (mig `0060`) each carry their own `template_id`; `AbseilingData` (`core_shared/core_shared/models/journals/abseiling_data.py`) has none. But the abseil **pitches already live on `abseiling_data`** (the `abseil_pitches` child table), and CANYONING/CLIMBING/CAVING all have ABSEILING_TRIP in their dependency chain — so every abseiling-derived journal already has an `abseiling_data` row. **Decision (product owner, PR #1075):** consolidate `template_id` onto `abseiling_data`, co-locating it with the pitch data it populated — backfill the three existing columns into `abseiling_data`, then retire them. This gives a single source of truth, so the "missing template" rule and the templates-done widget each query one column. (Corrects the earlier "add to ABSEILING_TRIP and CAVING" framing in §2 of the spec.)
- **`ActivityTemplateType` is `canyoning | caving | climbing`** (`core_shared/core_shared/models/journals/activity_template.py`). A plain `ABSEILING_TRIP` journal has no matching template type, so ITER16-001 adds an **`abseiling`** template type so abseiling trips can reference a template.
- **Template pitch-copy is frontend-only today.** On template selection, the frontend (`JournalCreateForm.tsx` ~595–623, `JournalDetailView.tsx` ~316–343) copies `template.pitches` into `ABSEILING_TRIP.pitches` and recomputes totals; the backend just stores whatever `type_data` it receives. So "reference persists when pitches are edited" is mostly already true (editing pitches never touched `template_id`) — the work is to (a) add the field for `ABSEILING_TRIP`, (b) ensure the update path never silently drops it, and (c) surface it.
- **Three subtypes have no type-specific fields at all.** `SnorkellingData`, `DivingData`, `DownhillSkiingData` store only `journal_id` + timestamps. Under a literal "type-specific fields all empty" reading, they would be **flagged as incomplete forever**. **Resolved (product decision):** subtypes with no type-specific attributes are **exempt from rule 1** (SNORKELLING, DIVING, DOWNHILL_SKIING today); they can still be flagged by rules 2/3. The exemption is defined by the absence of fillable fields, not a hard-coded list, so it self-maintains if such a subtype later gains fields.
- **No dismissal store fits the new review.** The existing `journal_review_items` table + `ReviewItemService.dismiss()` (`backend/app/core/journal/services/review_item_service.py`) is for **merge candidates** (source/candidate journal pairs), not per-journal "this is fine" dismissals. ITER16-002 needs its **own** journal-scoped dismissal persistence; it should not overload the merge review queue.
- **Incompleteness is derived, not stored.** The three rules are computable from existing tables (subtype data presence, `template_id` null-ness, `JournalContactRelationship` PARTICIPANT count). The review is a **query/projection** over the user's outdoor journals plus a dismissal table — no new "incomplete" state on the journal.
- **Activity-stats helpers already aggregate by type over date windows.** `_fetch_activity_type_stats_rows()` / `_fetch_activity_trend_rows()` (`backend/app/mcp/domains/journals/tools.py`) build a CTE joining the subtype tables with `user_id` + `start_date`/`end_date` filters. The dashboard's "totals by type over rolling 30/365-day windows" reuses these rather than new SQL.
- **`browse_journals_by_date_window` already exists** (`tools.py` ~4043) with `anchor_date` / `days_forward` / `types` filters — the basis for "upcoming activities" (future outdoor journals + `OUTDOOR_PLANNING` events, capped at 10).
- **Checked-out gear is queryable but has no tool yet.** A gear item is checked out when a `GEAR_USAGE` journal references it with `checkin_date IS NULL` (`core_shared/.../gear_usage_data.py`); SnipeIT checkout is mirrored in `sync_metadata` (`integration_source='snipeit_checkout'`). No MCP tool returns "currently checked out" — ITER16-003 adds the query + tool.
- **The journals experience has no tab/sub-page structure** — only calendar/list **view modes** (`CalendarViewToggle.tsx`). The Outdoor Logbook overview page is a **new surface** (recommended: a dedicated route `frontend/src/app/journals/outdoor-logbook/page.tsx` with a sidebar entry under Journals — `Sidebar.tsx` ~126), not a new view-mode toggle. Whichever of ITER16-002 / -003 lands first introduces the page shell.
- **PDF pipeline is mature and well-tested but missing the new features.** `LogbookPdfRenderer` (`backend/app/core/journal/services/logbook_pdf_renderer.py`, ReportLab) renders cover → entries → summaries (at the **end**) → participant index. It has **no** TOC, no activity-type index, no internal hyperlinks, no per-type glyphs (text labels only), no GPX map, and no document outline. Album links render today via `entry.album_shared_link`. Frontend type icons live in `JournalTypeBadges.tsx` (lucide-react) — the PDF will mirror these as emoji/unicode glyphs.

## Dependency and Parallelisation Notes

- **ITER16-001 (Durable Template Reference)** has no dependencies and lands first — it unblocks the "missing template" incomplete rule (ITER16-002) and the "templates done" dashboard widget (ITER16-003).
- **ITER16-002 (Incomplete Review)** depends on ITER16-001 for the missing-template rule to be meaningful across all abseiling-derived types; it introduces the overview page shell.
- **ITER16-003 (Dashboard)** depends on ITER16-001 for the templates-done widget; soft-depends on ITER16-002 for the shared overview page shell (ships the shell itself if it lands first).
- **ITER16-004 (PDF Improvements)** is largely independent; it benefits from ITER16-001 so the template-reference name is guaranteed present for abseiling entries, but its other improvements stand alone.

| Sub-iteration | Depends on | Can parallelise with |
|---|---|---|
| ITER16-001 Durable Template Reference | — | ITER16-004 |
| ITER16-002 Incomplete Review | ITER16-001 | ITER16-004 |
| ITER16-003 Outdoor Dashboard | ITER16-001 (soft: -002 page shell) | ITER16-004 |
| ITER16-004 PDF Improvements | — (soft: ITER16-001) | all others |

---

## Task Breakdown

Each sub-iteration defines its objective, the specification section it realises, its dependencies, the user-facing deliverable, the outcomes its phases must collectively satisfy, and a **phase breakdown**. Each phase carries a PR-size estimate, acceptance/scope, and its test coverage and documentation updates. Phases are sized to merge to a green, deployable `main` independently within a **≤500-line diff** (implementation + tests).

### ITER16-001: Durable Template Reference on Abseiling Activities

**Objective:** Make every abseiling-derived activity carry a durable reference to the canyon/cave/climb template it was based on — preserved even after the copied pitches are edited — and surface that reference in the journal UI, the PDF, and MCP.

**Specification Reference:**
- [§2 Durable Template Reference on Abseiling Activities](../product-specifications/outdoor-logbook-improvements-product-specification.md#2-durable-template-reference-on-abseiling-activities)
- [§5 MCP and AI-Agent Parity](../product-specifications/outdoor-logbook-improvements-product-specification.md#5-mcp-and-ai-agent-parity) (template-on-journal retrieval; `template_id` on create/update)

**Dependencies:** None.

**Deliverable:** An abseiling activity (ABSEILING_TRIP, and by extension canyoning/climbing/caving which already store it) shows "based on: <template name>" in the UI and PDF, persists that link across pitch edits, and exposes it through MCP.

**Outcomes the phases must satisfy:**
- `template_id` is consolidated onto `AbseilingData` / `journal_abseiling_data` (nullable UUID FK to `activity_templates.id`, `ON DELETE SET NULL`); the existing canyoning/climbing/caving `template_id` columns are backfilled into it and retired.
- `ActivityTemplateType` gains `abseiling`; template create/update/search accept it.
- `template_id` is **never cleared** by editing pitches or other fields (UI path and `update_journal_entry`).
- Journal detail and the PDF show the referenced template name for any abseiling-derived journal that has one.
- MCP create/update accept and preserve the consolidated `template_id` for any abseiling-derived journal; the referenced template (incl. pitches) is retrievable.

**Phase Breakdown:**

**Phase 1 — Data layer: `abseiling` template type + consolidated `template_id` column + backfill (additive).** PR ~350 lines. ✅ DONE — migration `0094` adds `journal_abseiling_data.template_id` (FK `ON DELETE SET NULL`) + backfills from canyoning/climbing/caving, extends the `activity_templates` type CHECK with `abseiling`, adds `template_id` to `AbseilingData` + repo, with unit + integration (migration up/down + backfill) coverage. Old subtype columns retained; write-service wiring deferred to Phase 2.
- Add `ActivityTemplateType.abseiling` and extend the template-type CHECK constraint. Add `template_id` to `AbseilingData` / `journal_abseiling_data` (nullable UUID FK, `ON DELETE SET NULL`). Alembic migration (`0094` at time of writing, per the `creating-migrations` skill) adds the column and **backfills it from the existing `canyoning_data` / `climbing_data` / `caving_data` `template_id` values** (each maps to the journal's `abseiling_data` row); the old columns are **left in place** for now (additive — both coexist). The abseiling repository reads/writes `template_id`. Not yet processed by the journal write-service, so it merges green.
- **Tests:** unit — `AbseilingData` accepts/validates `template_id`, `abseiling` enum round-trips; integration — migration up/down with `async_connection`/`clean_database`, backfill copies existing subtype `template_id`s onto `abseiling_data`, repo persists/reads `template_id`.
- **Docs:** `docs/architecture/database-design.md` — new column + `abseiling` template type + the consolidation/backfill plan.

**Phase 2 — Service + MCP wiring (write/read at the abseiling level).** PR ~400 lines.
- The journal write-service reads/writes the consolidated `abseiling_data.template_id` for **all** abseiling-derived types on create and composite update, preserving it when only pitches change; the canyoning/climbing/caving write paths stop writing their own `template_id` (now unused). Add the template-on-journal retrieval path (returns the referenced template incl. standard pitches). `create_journal_entry`/`update_journal_entry` accept and preserve `template_id` for any abseiling-derived journal.
- **Tests:** unit — write-service preserves `template_id` on a pitch-only edit (canyoning/climbing/caving/abseiling); integration — create-with-template then edit a pitch keeps it; MCP create/update preserve it; retrieval returns the template + pitches despite modified journal pitches.

**Phase 3 — Frontend display + selection.** PR ~350 lines.
- Journal detail shows "based on: <template>" (linking to the template) for any abseiling-derived journal with a `template_id`. The create/edit form persists the selected template onto the consolidated field for abseiling-derived journals (reusing the existing pitch-copy behaviour), including plain `ABSEILING_TRIP`.
- **Tests:** RTL — detail renders/omits the link by presence of `template_id`; e2e (Playwright) — create an abseiling trip from a template, edit a pitch height, reload, confirm the reference is still shown.

**Phase 4 — Template name in the PDF.** PR ~120 lines.
- The PDF entry renders the template-reference name when present for abseiling-derived types — small and additive, independent of the ITER16-004 rework.
- **Tests:** unit (renderer shows the name when present) + integration (export includes it).

**Phase 5 — Retire the per-subtype `template_id` columns (cleanup migration).** PR ~200 lines.
- Once Phases 2–3 have moved all reads/writes to `abseiling_data.template_id`, drop the now-unused `template_id` columns (and their FKs) from `canyoning_data`, `climbing_data`, and `caving_data`. Separate phase so the read/write switch deploys and is verified before the columns are removed (additive-first, then drop).
- **Tests:** integration — migration up/down; no code path references the dropped columns (grep/asserted); existing abseiling-derived journal suites stay green.
- **Docs:** `database-design.md` — mark the old columns retired.

---

### ITER16-002: Incomplete Outdoor Activities Review

**Objective:** Give the user a single outdoor-specific surface listing activities that are likely missing important detail, with the reason(s) shown and a reversible whole-entry dismiss, available in the UI and MCP.

**Specification Reference:**
- [§1 Incomplete Outdoor Activities Review](../product-specifications/outdoor-logbook-improvements-product-specification.md#1-incomplete-outdoor-activities-review)
- [§5 MCP and AI-Agent Parity](../product-specifications/outdoor-logbook-improvements-product-specification.md#5-mcp-and-ai-agent-parity) (list + dismiss/un-dismiss)

**Dependencies:** ITER16-001 (so the missing-template rule applies uniformly across abseiling-derived types). Introduces the Outdoor Logbook overview page shell if it lands before ITER16-003.

**Deliverable:** An "incomplete" list on the Outdoor Logbook overview page showing each flagged journal with its reasons, linking to the journal to fix it, with a dismiss/un-dismiss action — mirrored by an MCP tool.

**Incompleteness rules** (each matched rule shown as a distinct reason):
1. **No attributes set** — the subtype's own type-specific fields are all empty (shared OUTDOOR_ACTIVITY fields don't count); evaluated per subtype for multi-subtype journals.
2. **Abseiling activity missing a template** — `ABSEILING_TRIP` is in the dependency chain (ABSEILING_TRIP / CANYONING / CLIMBING / CAVING) and the consolidated `abseiling_data.template_id` is null (single-column check, per ITER16-001).
3. **No participants (except hiking)** — a non-`BUSHWALKING` outdoor activity with no PARTICIPANT contacts.

**Outcomes the phases must satisfy:**
- A read projection computes the incomplete list over the user's own outdoor activity journals with per-entry reason(s), derived from existing tables (subtype data presence, `template_id`, PARTICIPANT count).
- Rule 1 exempts fieldless subtypes; rule 3 exempts BUSHWALKING.
- Whole-entry **dismiss** (reversible, journal-scoped, recorded with provenance) via a store separate from `journal_review_items`; a dismissed entry is excluded regardless of matched rules.
- The list updates as gaps are filled; scoped to outdoor activity journals only.
- Full UI (on the overview page) and MCP parity (list + dismiss/un-dismiss).

**Phase Breakdown:**

**Phase 1 — Journal-scoped dismissal store (additive).** PR ~380 lines.
- New dismissal table + model + Alembic migration; repository (dismiss, un-dismiss, list dismissed journal ids for a user); a `@transactional` service recording provenance (per Activity History). Distinct from the merge `journal_review_items` queue. Not yet consumed, so it merges green.
- **Tests:** unit — service dismiss/un-dismiss; integration — migration up/down, repo, idempotent re-dismiss/un-dismiss.
- **Docs:** `database-design.md` (new table); `domain-architecture.md` (distinct from merge review items).

**Phase 2 — Incompleteness detection projection.** PR ~450 lines.
- A read service computes the incomplete list with per-entry reasons: rule 1 (type-specific fields empty, with the fieldless-subtype exemption derived from the absence of fillable fields), rule 2 (abseiling chain has null `template_id`), rule 3 (no PARTICIPANT, except BUSHWALKING) — filtered by the dismissal store. Derived only from existing tables; no new journal state. Not yet exposed.
- **Tests:** unit — each rule isolated + combined (multi-reason), rule-1 fieldless exemption, rule-3 bushwalking exemption, dismissal filtering; integration — seed per rule against `clean_database`, assert list + reasons, fill a gap → entry drops out.
- **Docs:** `domain-architecture.md` — the incomplete-review projection.

**Phase 3 — REST endpoint + MCP tools.** PR ~400 lines.
- REST: list incomplete + dismiss/un-dismiss (for the UI). MCP: list incomplete (reasons, respecting dismissals) + dismiss/un-dismiss.
- **Tests:** integration via `authenticated_client` (REST list/dismiss/un-dismiss); MCP list/dismiss/un-dismiss end-to-end.
- **Docs:** `api-design.md`; `mcp-setup.md`.

**Phase 4 — Overview page shell + incomplete list UI.** PR ~450 lines.
- Dedicated route `frontend/src/app/journals/outdoor-logbook/page.tsx` + sidebar entry under Journals (the shared overview page shell). The incomplete list renders title, date, type icon(s), reason badge(s), a link to the journal, and a dismiss/un-dismiss control.
- **Tests:** RTL — renders reasons + dismiss removes the row (deterministic seed, no conditional/multi-outcome assertions per CLAUDE.md); e2e — seed an incomplete activity → flagged with reason → dismiss → gone → un-dismiss → returns.
- **Docs:** `frontend-design.md` — overview route + incomplete-review component.
- *If this exceeds ~500 lines, split into 4a (route + page shell + sidebar) and 4b (incomplete list + dismiss controls).*

---

### ITER16-003: Outdoor Logbook Overview Dashboard

**Objective:** Provide an at-a-glance Outdoor Logbook overview page (outdoor activities only) with upcoming activities, checked-out gear, recent activity volume by type, and the abseil templates done — in the UI and via an MCP dashboard-data tool.

**Specification Reference:**
- [§4 Outdoor Logbook Overview Page (Dashboard)](../product-specifications/outdoor-logbook-improvements-product-specification.md#4-outdoor-logbook-overview-page-dashboard)
- [§5 MCP and AI-Agent Parity](../product-specifications/outdoor-logbook-improvements-product-specification.md#5-mcp-and-ai-agent-parity) (outdoor dashboard data)

**Dependencies:** ITER16-001 (templates-done widget needs the durable references). Soft-depends on ITER16-002 for the shared overview page shell (ships the shell if -002 hasn't).

**Deliverable:** A dashboard on the Outdoor Logbook overview page with four widgets, and an MCP tool returning the same data.

**Dashboard widgets:**
1. **Upcoming Activities** — next month, capped at 10: future-dated OUTDOOR_ACTIVITY journals + `OUTDOOR_PLANNING` events, most-imminent first.
2. **Gear currently checked out** — gear with checkout state open (SnipeIT-sourced), with checkout date where available; empty state when none.
3. **Activity totals (recent)** — counts by journal type over rolling **last 30 days** and **last 365 days**, shown together.
4. **Abseil templates done (by type)** — unique templates referenced by the user's abseiling activities, grouped by template type, each linking to the template with a per-template done-count.

**Outcomes the phases must satisfy:**
- Upcoming (outdoor + `OUTDOOR_PLANNING`, ~30 days, soonest-first, ≤10); checked-out gear (open `GEAR_USAGE` / SnipeIT, documented definition, empty state); totals by journal type over rolling 30/365-day windows; templates-done distinct + grouped by type with per-template done-count.
- All data is **outdoor activities only**.
- Full UI (four widgets on the overview page) and MCP parity (single dashboard-data tool returning all four sections).

**Phase Breakdown:**

**Phase 1 — Upcoming + totals services (reuse existing infra).** PR ~350 lines.
- Upcoming-activities query (reusing `browse_journals_by_date_window` semantics: anchor today, ~30 days forward, types = outdoor + `OUTDOOR_PLANNING`, soonest-first, cap 10). Totals query (reusing the activity-stats type/window helpers) by journal type over rolling 30/365-day windows, outdoor only. Read-only, not yet exposed.
- **Tests:** unit — cap/date-bounds/type filter for upcoming; per-window grouping for totals; integration — seed and assert.

**Phase 2 — Checked-out gear + templates-done services (net-new queries).** PR ~400 lines.
- Checked-out gear (open `GEAR_USAGE` where `checkin_date IS NULL` / SnipeIT `sync_metadata`), user-scoped, with a documented "checked out" definition and empty state. Templates-done: distinct templates referenced by the user's abseiling-derived journals, grouped by template type, with a per-template done-count. Read-only.
- **Tests:** unit — checked-out determination; templates-done dedup/group/count; integration — seed open+closed checkouts and abseiling journals with refs, assert each.
- **Docs:** `database-design.md` — the "checked out" definition.

**Phase 3 — REST endpoint + MCP dashboard tool.** PR ~350 lines.
- A REST dashboard endpoint and a single MCP dashboard-data tool returning all four sections (aggregating Phases 1–2).
- **Tests:** integration via `authenticated_client` (REST) + MCP end-to-end.
- **Docs:** `api-design.md`; `mcp-setup.md`.

**Phase 4 — Frontend: upcoming + totals widgets.** PR ~350 lines.
- Render the upcoming-activities and totals widgets on the overview page (shadcn/ui, RSC-first where possible), items linking to their journals; empty states. Reuses the ITER16-002 page shell, or introduces it here if ITER16-003 ships before ITER16-002.
- **Tests:** RTL — each widget renders seeded data and its empty state.

**Phase 5 — Frontend: checked-out gear + templates-done widgets.** PR ~350 lines.
- Render the checked-out-gear and templates-done widgets (items linking to gear/template; per-template count shown); empty states.
- **Tests:** RTL — each widget + empty state; e2e — seed representative data, open the overview page, verify all four widgets show the expected items and links.
- **Docs:** `frontend-design.md` — the overview page widgets.

---

### ITER16-004: PDF Logbook Output Improvements

**Objective:** Upgrade the outdoor logbook PDF into a polished, navigable, shareable document: summary first, table of contents, internally-linked participant and activity-type indexes, per-type icon glyphs, Immich album links, GPX track maps, and a document outline.

**Specification Reference:**
- [§3 PDF Logbook Output Improvements](../product-specifications/outdoor-logbook-improvements-product-specification.md#3-pdf-logbook-output-improvements)

**Dependencies:** None hard. Soft: ITER16-001 (guarantees the template-reference name is present for abseiling entries).

**Deliverable:** A regenerated `LogbookPdfRenderer` output with the seven improvements below; export remains UI-initiated (the original spec keeps PDF export out of MCP), with its source data MCP-retrievable.

**Outcomes the phases must satisfy:**
- Summary moves to the front; a TOC and a viewer-navigable outline mirror the sections/hierarchy.
- Participant index (keep ≥3 threshold) and a new activity-type index list journals as **internal hyperlinks**.
- Per-type emoji/unicode glyphs (mirroring `JournalTypeBadges.tsx`, no image assets); Immich album link(s) when present; GPX track maps over OSM tiles when present (cached, throttled, attributed, plain-background fallback).
- All other export behaviour unchanged; export stays UI-initiated.

**Phase Breakdown** (intra-iteration order: Phase 1 precedes Phases 2–3; Phase 5 precedes Phase 6; Phase 4 is independent):

**Phase 1 — Navigation: section anchors + summary-first + table of contents.** PR ~400 lines.
- Give each entry/section a stable internal anchor. Move the yearly summary to immediately after the cover, before entries. Add a TOC listing major sections (summary, each year/top-level trip, indexes) with internal links.
- **Tests:** unit (`test_logbook_pdf_renderer.py`) — summary precedes entries; TOC present with working internal anchors.

**Phase 2 — PDF document outline (bookmarks).** PR ~250 lines.
- A viewer-navigable outline mirroring the TOC and journal hierarchy (summary, years/top-level trips with nested child activities, indexes), reusing Phase 1 anchors.
- **Tests:** unit — outline/bookmark entries created mirroring the hierarchy.

**Phase 3 — Linked participant + activity-type indexes.** PR ~450 lines.
- Convert the participant index (keep `min_appearances=3`) to list each contact's journals as internal hyperlinks; add a new activity-type index listing each type's journals as linked names.
- **Tests:** unit — participant entries carry internal-link anchors; activity-type index present and linked; integration (`test_logbook_export_api.py`) — seed a contact appearing in ≥3 entries (the `min_appearances=3` boundary, e.g. exactly 3) and multiple types, assert both indexes link to entries.

**Phase 4 — Per-type icon glyphs + Immich album links.** PR ~300 lines.
- Render an emoji/unicode glyph per journal type (mirroring `JournalTypeBadges.tsx`) next to type labels on entries and in the indexes, no image assets. Guarantee Immich album link(s) render when present (multiple albums supported), omitted otherwise.
- **Tests:** unit — glyph appears for representative subtypes; album link rendered when present / absent otherwise; integration — seed a journal with an Immich album.

**Phase 5 — GPX tile-source adapter (additive infra).** PR ~400 lines.
- A swappable tile-source adapter fetching OSM standard tiles, with an on-disk cache (dedup across entries/zooms), a ≈2 tiles/second throttle, a valid User-Agent, and a clean failure mode. Not yet wired into the PDF, so it merges green.
- **Tests:** unit — cache hit avoids a second fetch; throttle + User-Agent applied; failure surfaces cleanly (network stubbed — no live OSM calls).
- **Docs:** `api-design.md` / the improvements spec — basemap-tile source decision (OSM, swappable).

**Phase 6 — GPX map rendering in the PDF.** PR ~400 lines.
- Compose the track over fetched tiles into a per-entry map image (fit bbox + padding; OSM attribution drawn on the image) wired into the renderer; plain-background fallback when the adapter fails. Entries without a GPX `Route` omit the image.
- **Tests:** unit — map flowable included when a route is present (adapter stubbed); fallback renders a plain background when the adapter raises; integration — export with a GPX route asserts a non-empty image flowable; the suite never hits live tiles.

---

## Resolved Decisions

Confirmed with the product owner (2026-06-29):

1. **Rule-1 fieldless subtypes (ITER16-002):** **exempt** subtypes with no type-specific attributes from "no attributes set" (SNORKELLING / DIVING / DOWNHILL_SKIING today). The exemption is derived from the absence of fillable fields, not a hard-coded list.
2. **Basemap tile source (ITER16-004):** **reuse OpenStreetMap standard tiles**, the same source as the in-app `GPXTrackMap.tsx`, behind a swappable tile-source adapter. Batch-safe by design: on-disk tile cache, ≈2 tiles/second throttle, valid User-Agent, OSM attribution drawn on the image, and a plain-background fallback if fetching fails. A keyed topo provider can be substituted later via the adapter.
3. **Templates-done count (ITER16-003):** **required** — show a per-template done-count, not just the unique list.
4. **Overview page placement (ITER16-002/-003):** **dedicated route** (`frontend/src/app/journals/outdoor-logbook/page.tsx`) with its own sidebar entry under Journals — not a view-mode toggle.

### Remaining design choices (decide during implementation, no product input required)

- Dismissal store shape for ITER16-002 (new journal-scoped table vs. a status column) — a build-time choice; the requirement (reversible, journal-scoped, recorded with provenance, separate from merge review items) is fixed.
- Exact zoom/sizing heuristic for the GPX map image (fit track bounding box with padding).
- Whether the abseiling template type needs any UI affordances beyond the existing template create/edit form (expected: none — it reuses the common fields).

## Sub-Iteration Summary

| Sub-iteration | Deliverable | UI | MCP | Depends on |
|---|---|---|---|---|
| ITER16-001: Durable Template Reference | `template_id` consolidated onto `abseiling_data` + `abseiling` template type, preserved on edit, shown in journal/PDF/MCP | ✅ | ✅ | — |
| ITER16-002: Incomplete Review | Outdoor-specific incomplete list (3 rules) with reversible dismiss | ✅ | ✅ | -001 |
| ITER16-003: Outdoor Dashboard | Overview page: upcoming, checked-out gear, recent totals, templates done | ✅ | ✅ | -001 (soft -002) |
| ITER16-004: PDF Improvements | Summary-first, TOC, linked indexes, icons, Immich links, GPX maps, outline | ✅ (export) | n/a (data MCP-retrievable) | — (soft -001) |

### Phase Summary

| Sub-iteration | Phases | Est. PRs |
|---|---|---|
| ITER16-001: Durable Template Reference | 5 | 5 |
| ITER16-002: Incomplete Review | 4 | 4 |
| ITER16-003: Outdoor Dashboard | 5 | 5 |
| ITER16-004: PDF Improvements | 6 | 6 |
| **Total** | **20** | **20** |

**Suggested delivery order:** ITER16-001 (unblocks the missing-template rule and templates-done widget) → ITER16-002 (introduces the overview page shell) → ITER16-003 (adds dashboard widgets to the shell). ITER16-004 is independent and can run in parallel from the start, landing whenever capacity allows. Within ITER16-004, Phase 1 precedes Phases 2–3, and Phase 5 precedes Phase 6; Phase 4 is independent.
