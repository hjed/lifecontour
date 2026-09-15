# Contacts Product Specification

## Overview

This document defines the target product behaviour for the next major improvement to Contacts. It is a product specification rather than a technical design. It describes the intended user experience across the web interface, sync behaviour, search, and AI-facing workflows.

This specification builds on the current product rather than replacing it. Contacts, tags, favourites, search infrastructure, Google Contacts sync foundations, activity history, and MCP support already exist in part. The work described here completes and extends those capabilities into a coherent contact management experience.

## Product Goals

The Contacts experience should help the user:

1. Organise people in a way that feels natural and flexible.
2. Keep Google Contacts and local contact organisation aligned.
3. Quickly understand who a contact is, what matters about them, and what follow-up may be needed.
4. Find relevant contacts and related journals quickly from a single top-level search experience.
5. Use the same core capabilities through the web UI and through AI agents via MCP.

## Product Principles

1. **AI-first:** Any meaningful contact capability available in the UI should also be available to AI agents through MCP.
2. **Build on existing behaviour:** The product should evolve current contact, sync, search, and activity functionality rather than restart it.
3. **Reduce friction:** Common contact tasks should require fewer clicks and less scrolling.
4. **Meaningful organisation:** Tags, relationships, dates, journals, and summaries should work together rather than as isolated features.
5. **Conservative AI behaviour:** AI-generated content should be useful, grounded, and cautious in its inferences.

## Scope Priority

This specification describes the full target behaviour, even if delivery happens in phases.

Priority order:

1. Google Contacts group sync for tags
2. Tag management across UI and MCP
3. Contact layout improvements
4. AI interaction summary, including search influence
5. Global search experience
6. Sync activity in contact activity feed

## Current Product Context

The current product already supports core contacts, tags, favourites, a contact details view, activity history, MCP contact tools, Google Contacts integration foundations, and MeiliSearch-backed search services. However, these capabilities are incomplete and inconsistent from a product perspective. The main gaps are around editable tag management, correct group-to-tag behaviour, search UX in the header, richer sync visibility, and AI-generated contact understanding.

## In Scope

This specification covers:

- contact tag management and hierarchy
- Google Contacts group sync rules for tags
- relationship modelling as part of the existing relationships concept
- AI-generated interaction summary and follow-up suggestions
- important dates on contacts
- contact detail layout improvements
- activity feed provenance and sync visibility
- unified top-level search across contacts and journals
- MCP parity for the above behaviours

## Contact Tags

Tags are a first-class way to organise contacts.

### Required behaviour

- Tags must be visible on contact cards and on the contact details page.
- Users must be able to add and remove tags while editing a contact.
- Users must be able to create new tags during contact editing when the desired tag does not already exist.
- Tags must be manageable from the contacts sidebar.
- The minimum editable tag fields are **name** and **colour**.
- Deleting a tag removes it from all contacts.

### Hierarchy

- Tags are hierarchical now, not deferred.
- A tag can have one parent.
- The sidebar must display tags in a nested structure.
- Deeper levels should be expandable rather than always fully expanded.
- Viewing a parent tag must include contacts assigned to its child tags.
- A contact with only a child tag must still appear when viewing the parent tag.

### Tag management experience

- Contact cards should support quick tag editing.
- Unknown tag values entered during contact editing should trigger a create flow.
- Sidebar tag editing should use a compact context menu and modal flow rather than forcing navigation away.
- Clicking a tag in the sidebar should open the same contact list experience as **All**, filtered to that tag.

## Relationships

Relationship-like classification should be handled through the existing relationships concept, not by creating special relationship tags.

### Required behaviour

- Contacts must be able to hold multiple relationships.
- Relationships must be able to point to the user as well as to other contacts.
- Relationship information should influence AI context and contact prioritisation.
- Relationship information should be available in MCP wherever contact context is exposed.

## Google Contacts Sync for Tags

Tag and group behaviour must feel predictable and trustworthy.

### Required behaviour

- Ordinary tags must sync bidirectionally with Google Contact Groups.
- Reserved relationship data must not sync as Google groups.
- Google group changes must update local tags.
- Local tag changes must update Google group membership where supported.
- Creating a relevant group in Google should create or match a local tag.
- Local changes win in conflicts.

### Google-specific rules

- `My Contacts` is ignored.
- `Starred` maps to favourites.
- Other reserved groups should be configurable.
- Hierarchical local tags should be flattened for Google using `/` in the synced name.

## AI Interaction Summary

The current static-style summary should be replaced by an AI-generated summary that helps the user reconnect effectively.

### Purpose

The summary should help the user understand:

- unresolved follow-ups
- recent interactions
- suggested conversation prompts
- notable life context where relevant
- current relationship context where relevant

### Required behaviour

- The summary must appear on the contact details page.
- The summary must be returned through MCP when retrieving a contact.
- The summary should include follow-up suggestions as well as a concise summary.
- The summary should be regenerated asynchronously after relevant contact activity.
- The summary should show when it was last generated.
- The user should be able to manually refresh it.
- The system should be able to auto-disable summary generation for low-activity contacts, with user override.
- The user should be able to turn AI summary generation off and back on from the contact details page. Turning it back on queues a new summary immediately.
- An automatic low-activity disable is a pause, not a permanent state: it is re-evaluated whenever a summary refresh is triggered (by contact activity or a manual refresh), and generation resumes once there is enough recent activity and at least one linked journal to summarise. Only the user's own choice to turn generation off is sticky.

### Inputs

The summary should draw from the contact's broader relationship history, including:

- contact changes
- notes
- relationships
- linked journals
- related journal context such as missed replies or unresolved actions

The summary should be weighted toward recent activity while remaining bounded to a recent history window rather than attempting to consider everything indefinitely.

### Tone and safety

- The summary should be lightly inferential but conservative.
- It should stay grounded in available evidence.
- It should avoid overstating certainty or making intrusive assumptions.

## Important Dates

Contacts should support important personal dates as a core part of relationship context.

### Required date types

- birthday
- marriage anniversary
- work anniversary
- first met
- globally defined custom date types

### Required behaviour

- Dates should support full date, day-and-month, or year-only precision.
- Dates should be editable inline on the contact details page.
- Dates should be displayed in a richer contact details card rather than a plain field list.
- Birthday should receive stronger visual emphasis unless the relationship context suggests another date matters more.
- Important dates should contribute to AI follow-up context.
- Upcoming dates on contact cards are desirable and may be phased after the detail-page experience.

### Google sync

- Google-supported date fields should sync bidirectionally.
- Unsupported date types remain local only.

## Contact Layout Improvements

The contact details experience should remain spacious, but it should use desktop space more effectively.

### Required behaviour

- The page should reduce excessive blank space on desktop.
- Important contact information should appear higher on the page.
- Contact methods and tags should move higher in visual priority.
- The sidebar should remain part of the layout.
- The overall effect should be better visual polish and less scrolling without making the page feel cramped.

## Activity Feed

The activity feed should show meaningful changes to a contact regardless of where they originated.

### Required behaviour

- Meaningful edits made through the UI, MCP, or sync should appear in the activity feed.
- Sync-originated changes should be visible when they changed the contact.
- Exports that do not result in a contact change should not appear as activity.
- Provenance should be shown with compact icons and hover text.
- AI summary regeneration should appear in the same activity stream in abbreviated, collapsible form.
- The initial experience does not require activity filtering.

## Global Search

The top search box should become a real product feature rather than a placeholder entry point.

### Required behaviour

- Typing in the top search should show direct result suggestions and recent searches.
- Pressing Enter should open a dedicated search results page.
- Search results should include both Contacts and Journals.
- Results should be grouped by type rather than shown as a single mixed list.

### Ranking expectations

Contact ranking should consider a combination of:

- text relevance
- favourites
- tags and relationships
- recent contact activity
- linked journal activity
- amount of recent journals associated with the contact
- AI summary relevance where useful

Linked journals are an intentional signal of relationship importance. Search should use them to make frequently relevant people easier to rediscover.

Search ranking explanation is desirable if it can be introduced without adding major complexity.

## MCP and AI-Agent Parity

This product must preserve parity between the web interface and AI-facing workflows.

### Required behaviour

- AI agents must be able to retrieve the same important contact context available to the user.
- Contact update flows exposed to AI should support tag changes as part of normal contact updates.
- Search capabilities exposed to AI should reflect the same broad behaviour as user-facing global search.
- AI-facing contact retrieval should include relationship context, important dates where available, and the AI-generated interaction summary.

## Success Criteria

This work will be successful when the user can:

1. organise contacts with editable hierarchical tags and reliable Google group sync
2. understand key relationship context quickly from the contact page
3. see meaningful activity, including sync-driven changes
4. rely on the top search to find both people and journals
5. access the same core contact intelligence through AI tools and MCP

## Delivery Notes

This specification defines target product behaviour. Delivery may be phased, but phases should preserve coherence. For example, tag editing without correct sync behaviour, or AI summaries without MCP exposure, would be incomplete from a product perspective.