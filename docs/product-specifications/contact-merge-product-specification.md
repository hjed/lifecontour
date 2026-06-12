# Contact Merge Product Specification

## Overview

This document defines the target product behaviour for merging contacts. It is a product
specification rather than a technical design. It describes the intended user experience across the
web interface, AI-facing workflows, and integration sync behaviour.

Contacts accumulate duplicates over time: the same person can be entered manually, imported from
Google Contacts, linked from Immich, and auto-linked by name matching. There is currently no way to
combine two contacts into one. This specification fills that gap.

The journaling experience already provides a mature merge workflow — manual merge, field-by-field
conflict resolution, and MCP parity — described in the
[Journals Product Specification](journals-product-specification.md#journal-merge). Contact merge
deliberately mirrors that workflow's **UI and conflict-handling capabilities** so the two domains
feel consistent. It does **not** include AI-assisted duplicate detection or a review queue at this
stage; finding the pair to merge is a manual action.

## Product Goals

The contact merge experience should help the user:

1. Consolidate duplicate contacts into a single record without losing any relationships, journal
   links, history, or sync connections.
2. Resolve conflicting details deliberately rather than having data silently overwritten or
   duplicated.
3. Keep external services (Google Contacts, Immich) consistent with the merged result.
4. Perform the same merge through the web UI and through AI agents via MCP.

## Product Principles

1. **AI-first:** Merging contacts and resolving merge conflicts must be available to AI agents
   through MCP, not only in the UI.
2. **Build on existing behaviour:** Reuse the journal merge product patterns (survivor model,
   field-by-field resolution, conflict-aware UI) rather than inventing a new vocabulary.
3. **Collapse, don't duplicate:** Merged data must dedupe. The surviving contact gains everything
   meaningful from the source without accumulating duplicate methods, tags, relationships, or
   links.
4. **Non-destructive history:** A merge must preserve the full audit trail of both contacts and
   record the merge itself as an auditable event.
5. **Keep external systems consistent:** A merge that changes which local contact is canonical must
   reconcile the corresponding remote records, not leave them orphaned.
6. **Conservative and reviewable:** The user always chooses the survivor and confirms how conflicts
   resolve before the merge is applied.

## Scope Priority

This specification describes the full target behaviour, even if delivery happens in phases.

Priority order:

1. Core local merge: full-aggregate dedupe, field-by-field conflict resolution, and MCP parity.
2. External sync reconciliation: carry over links from different services; consolidate same-service
   collisions.
3. History re-pointing and an explicit merge event.

## Current Product Context

Contacts already support scalar identity fields (name parts, company, job title, photo, favourite)
and a rich aggregate: contact methods (email/phone), addresses, notes, tags, important dates,
contact-to-contact relationships, an AI-generated interaction summary, journal links, field-level
history, and external references to Google Contacts and Immich. The journal domain already ships a
working merge feature that this specification treats as the established pattern. No contact merge
capability exists today, and there is no merge-specific domain event for contacts.

## In Scope

This specification covers:

- merging two contacts into one user-chosen surviving contact
- merging and deduplicating the full contact aggregate: relationships, journal links, contact
  methods, addresses, notes, tags, and important dates
- field-by-field conflict resolution for scalar contact fields
- reconciling external sync references across and within services
- merging contact history and recording the merge as an auditable event
- MCP parity for the above behaviours

## Out of Scope

This specification explicitly excludes, for now:

- AI-assisted duplicate detection
- a dedicated "Needs Review" queue for contacts
- an on-demand duplicate-finder helper (exact email/phone/name suggestions)
- automatic or bulk merging

Finding the pair of contacts to merge is a manual action in both the UI and MCP. These exclusions
may be revisited later, reusing the journal domain's detection and review-queue patterns.

## Contact Merge

Merge combines two contacts that represent the same real-world person into a single record.

### Product model

A merge always has:

- one surviving contact, chosen by the user, which keeps its identity and ID
- one source contact that is absorbed
- one resulting unified contact record

The user explicitly selects which of the two contacts survives. The source contact is deleted once
the merge completes.

### Required behaviour

- The user must be able to merge two contacts and choose which one survives.
- The surviving contact must preserve, deduplicated:
  - all relevant scalar identity fields
  - all non-duplicate contact methods
  - all non-duplicate addresses
  - all non-duplicate notes
  - all non-duplicate tags
  - all non-duplicate important dates
  - all non-duplicate contact-to-contact relationships
  - all journal links
  - external references
  - audit and history relevance
- Duplicates must collapse rather than being duplicated on the surviving contact.
- The source contact must be deleted after a successful merge.
- The surviving contact's AI interaction summary is **not** merged field-by-field; it must be
  regenerated after the merge so it reflects the consolidated contact.

### Field conflict resolution

Scalar identity fields include the name parts, company, job title, photo, and favourite flag.

- When only one contact has a value for a field, the surviving contact takes that value
  (prefer non-empty over empty).
- When both contacts have differing non-empty values, the user must be shown a field-by-field
  resolution UI offering, per field:
  - keep the surviving contact's value
  - take the source contact's value
  - provide a custom value
- This must mirror the journal merge resolution behaviour so the two experiences are consistent.
- AI agents must be able to express the same per-field choices through MCP overrides.

### Sub-entity merge rules

Each aggregate collection collapses according to its own identity rules:

- **Relationships:** Re-point both directions of the source contact's relationships
  (where it is the source and where it is the target) onto the surviving contact. Any relationship
  that would become a self-loop between the two merged contacts must be dropped. Remaining
  relationships must dedupe so the surviving contact holds at most one relationship per
  (other contact, relationship type) and per (relationship to the user, relationship type).
- **Journal links:** Re-point the source contact's journal links onto the surviving contact and
  dedupe so each (journal, contact, relationship type) combination appears once.
- **Contact methods:** Carry over and collapse exact duplicates. Global email uniqueness and the
  one-primary-per-type rule must continue to hold on the merged contact.
- **Addresses, notes, important dates:** Carry over and collapse exact duplicates.
- **Tags:** Take the union of both contacts' tags, collapsing duplicates.

## External Sync Reconciliation

A merge must keep external services consistent with the surviving contact.

### Different services

When the two contacts are linked to **different** services (for example, one to Google Contacts and
the other to Immich), the surviving contact must keep both links.

### Same-service collision

When **both** contacts are linked to the **same** service — each mapping to a separate remote record
— the surviving contact must end up with a single, consolidated remote record:

- Consolidate the merged data onto the surviving contact's remote record.
- Then delete the source contact's remote record where the service supports deletion (Google
  Contacts).
- For services without a delete capability (Immich, whose persons cannot be deleted via the API),
  keep the surviving contact's link and unlink the orphaned source record so it is no longer
  associated with a local contact.

This is a best-effort reconciliation bounded by each service's capabilities.

### Mechanism

Reconciliation is driven by a new `ContactMerged` domain event carrying the source and surviving
contact IDs and the external references to reconcile. Integration workers consume this event and
apply the per-service behaviour above. This section describes the intended product behaviour; the
event shape and worker implementation belong to the technical design and reuse the existing
event-bus and integration-worker patterns described in the
[Integration Architecture specification](integration-architecture-and-strava-product-specification.md).

## History and Audit

A merge must not lose the history of either contact.

- The source contact's field history must be re-pointed onto the surviving contact so the unified
  record carries the complete audit trail of both.
- The merge itself must be recorded as an explicit, auditable event on the surviving contact,
  capturing the source contact ID, the surviving contact ID, and the field-level choices made
  during conflict resolution.
- The merge event must carry provenance (`ui` or `mcp`) consistent with the
  [Activity History specification](activity-history-product-specification.md).

## MCP and AI-Agent Parity

Any contact-merge capability available in the UI must be available to AI agents through MCP.

- A `merge_contacts` tool must accept an explicit surviving contact ID and source contact ID, plus
  optional field-level overrides for conflict resolution, mirroring the journal `merge_journals`
  tool.
- The tool must return the unified surviving contact.
- All conflict resolution available in the UI must be expressible through the tool's overrides.
- Consistent with the out-of-scope section, no duplicate-detection or candidate-listing tool is
  provided at this stage; the agent supplies the two contact IDs directly.

## Web Experience

The merge experience should mirror the journal merge UI.

### Required behaviour

- The contact detail experience must offer an entry point to merge the contact with another.
- The user must be able to find the other contact through a search selector, mirroring the journal
  merge dialog's search combobox.
- The user must be able to choose which of the two contacts survives.
- When conflicts exist, the user must be shown a field-by-field resolution dialog (survivor /
  source / custom) before the merge is applied.
- The user must be able to review and confirm the merge before it takes effect, and see a clear
  success state afterward.
- The experience should reuse existing shadcn/ui components consistent with the journal merge
  dialogs.

## Alignment with Journals and Contacts

Contact merge intentionally shares the survivor model, conflict-resolution vocabulary, and dialog
UX of [Journal Merge](journals-product-specification.md#journal-merge), so users and agents
encounter one consistent merge concept across the product. The deliberate difference is the absence
of AI-assisted detection and a review queue: contact merge is a manual action until those
capabilities are introduced.

## Success Criteria

The user will be able to:

1. Merge two contacts and explicitly choose which one survives.
2. Keep all relationships, journal links, and history from both contacts on the surviving contact,
   with duplicates collapsed.
3. Resolve conflicting scalar fields field-by-field, choosing the surviving value, the source
   value, or a custom value.
4. Trust that contact methods, addresses, notes, tags, and important dates carry over without
   duplication.
5. Have external links reconciled so different services are preserved and same-service duplicates
   are consolidated.
6. See the surviving contact's AI summary regenerated to reflect the merged record.
7. Perform the entire merge, including conflict resolution, through MCP as well as the web UI.

## Delivery Notes

- The phases must ship coherently. In particular, a local merge that deletes the source contact
  without reconciling its remote links would silently orphan Google or Immich records; external
  sync reconciliation should not lag far behind the core merge.
- The surviving contact's AI summary must be regenerated after every merge so it does not present
  stale, pre-merge understanding.
- History must be treated as non-destructive: re-point the source contact's history and record the
  merge event so the full audit trail survives the merge.
