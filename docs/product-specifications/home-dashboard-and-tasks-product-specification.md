# Home Dashboard and Tasks Product Specification

## Overview

This document defines the target product behaviour for two intertwined pieces of work: the introduction of **Tasks** as a new core entity, and the completion of the **Home Dashboard**, which today is a non-functional placeholder.

It is a product specification rather than a technical design. It describes the intended user experience across the web interface, the AI daily summary, and AI-facing workflows through MCP.

The two pieces are specified together because neither is complete without the other. The dashboard is the reason tasks are worth having — it is where they surface — and tasks are a large part of what makes the dashboard worth opening. Both exist to tie together the AI elements of the system: the daily summary stops being a retrospective note on the journals page and becomes the user's forward-looking briefing for the day.

## Reference and Alignment

This specification builds on and refines behaviour described in:

- `docs/product-specifications/journals-product-specification.md`
- `docs/product-specifications/contacts-product-specification.md`
- `docs/product-specifications/activity-history-product-specification.md`
- `docs/journal-system-specification.md`
- `docs/architecture.md`
- `docs/architecture/domain-architecture.md`
- `docs/architecture/frontend-design.md`

In particular, the AI daily summary described in the Journals specification (*AI Daily Summary and Key Stats*) is extended rather than duplicated by this work. The contact importance signals described here are the same signals already used to rank contacts in search, described in the Contacts specification.

## Product Goals

The Home Dashboard should help the user:

1. Open one page in the morning and understand the day ahead without navigating anywhere else.
2. See what is already committed — the day's agenda — alongside what still needs doing.
3. Be reminded of the small number of things coming up in the next few days that are easy to forget, particularly important dates for the people who matter most to them.
4. Track short, concrete commitments as tasks, without accumulating a task list that becomes a source of guilt rather than help.
5. Receive a single AI-written summary that draws all of the above together.

The Tasks entity should help the user:

1. Capture a commitment at the moment it arises, in the journal where it arose.
2. Attach that commitment to the future moment where it actually matters.
3. Be reminded of it exactly then, and not before or endlessly after.

## Product Principles

1. **AI-first:** Any meaningful capability available in the UI should also be available to AI agents through MCP.
2. **Tasks are anchored, not free-floating:** A task exists in relation to two journals. This is a deliberate constraint, not an implementation detail.
3. **The system does not nag:** A task the user has let lapse goes quiet. It is not deleted, but it stops asking for attention.
4. **No accumulating backlog:** There is deliberately no place in the product where every open task can be listed together. Tasks are visible where they are relevant and nowhere else.
5. **Cancel over delete:** Consistent with the journals specification, the product prefers a cancelled state to destructive deletion.
6. **The dashboard is a projection, not a workspace:** It shows and links; it is not where journals are written or edited at length.
7. **Importance is inferred, not configured:** Contact prioritisation reuses the existing behavioural signals rather than asking the user to rank people.
8. **One summary, richer inputs:** The daily summary remains a single per-day artefact shared by the journals view and the dashboard.

## Scope Priority

This specification describes the full target behaviour, even if delivery happens in phases.

Priority order:

1. The Tasks domain model, lifecycle, journal anchoring, and journal-facing UI
2. Tasks over MCP
3. The Home Dashboard: daily summary, agenda, tasks, and upcoming contact dates
4. Extension of the daily summary inputs and eligibility rules
5. Task domain events and history projection

## Current Product Context

The home page (`/`) currently renders six static cards describing product areas. It fetches no data and performs no function beyond authentication gating. It is a placeholder and should be replaced.

The supporting capabilities largely exist already:

- **Daily summaries** are generated per day, cached, and exposed through both REST and MCP. They are eligible only for days with two or more journals, and their inputs are drawn from journals, journal-contact relationships, mood ratings, and series membership, scoped to the user's local day.
- **Journals** carry an event date range and are grouped by day in the journal list. Event journals carry times, locations, calendars, and participants — everything an agenda needs.
- **Contacts** carry important dates with a type and a precision, including recurring day-and-month dates such as birthdays and anniversaries.
- **Contact importance** is not stored as a field. Search already ranks contacts using favourite status and recent journal and activity counts, and those signals are the ones this specification reuses.
- **Domain events** flow through a transactional outbox into a stream, from which search indexing and field history projection are driven. A new entity can join this pipeline without new infrastructure.
- **The outdoor logbook dashboard** is an existing precedent for a read-only, singleton dashboard projection assembled server-side and rendered as widgets.

Tasks do not exist in any form today.

## In Scope

- The Tasks entity: model, invariants, lifecycle, status, and text
- Journal anchoring: creating journal, due journal, intermediate journals, and retargeting
- Lapsed tasks and resurrection
- Contacts on tasks
- Task domain events and field history
- Journal anchor integrity across journal delete, merge, and cancellation
- Task presentation on the journal detail and journal list experiences
- The Home Dashboard: daily summary, agenda, upcoming tasks, upcoming contact dates
- Contact importance ranking for dashboard purposes
- Extension of the daily summary's inputs, eligibility, and refresh behaviour
- MCP parity for all of the above

## Out of Scope

- A global tasks list, tasks page, or task browsing experience
- Task assignment to other people, or any multi-user notion of a task
- Sub-tasks, task hierarchy, or task dependencies
- Task priorities, effort estimates, or scheduling
- Recurring tasks
- Task reminders, notifications, or push of any kind
- Tasks in global search
- External task-system integrations such as Todoist, Jira, or Reminders
- Rich text, attachments, or checklists inside a task
- Dashboard customisation, widget reordering, or user-configurable layout
- Editing the AI daily summary

The product should remain compatible with future integrations consuming task events, which is why tasks are full domain-event citizens from the outset.

## Tasks

### Product model

A task is a short piece of text describing something the user needs to do, such as *"print out the permit before the meeting"* or *"return Sarah's book"*.

Every task is anchored to exactly two journals:

- a **creating journal** — where the commitment arose
- a **due journal** — the future moment where it matters

A task may additionally be linked to any number of **intermediate journals**, which are journals where the task was discussed, revisited, or previously due.

A task may reference any number of **contacts**.

The task's own content is deliberately minimal: short text, a status, its journal links, and its contact links. There is no description field, no priority, no effort, no checklist, and no attachments. Anything richer belongs in a journal.

### Core invariants

These are absolute and should be enforced at every entry point, including MCP:

1. A task **must** have a creating journal.
2. A task **must** have a due journal.
3. A task can never exist with only one of them, at any point in its life.
4. At the moment a due journal is set — on creation or on retargeting — that journal's date must be in the future relative to today in the user's timezone.
5. The due journal must be an **existing** journal. The product must not offer a bare date picker, and must not silently create a journal to hold a task.
6. The creating journal and the due journal may be the same journal, provided invariant 4 holds when it is set.

A journal's date, for the purposes of these rules, is the date of the start of its event date range interpreted in the user's timezone — the same date the journal list groups it under.

Invariant 4 is checked when a due journal is **set**, not continuously. A task whose due journal has since moved into the past is lapsed, not invalid — see *Lapsed tasks* below.

Invariant 5 is the heart of the model. Task lists become overwhelming because tasks are cheap to create and free-floating. Requiring the user to name a real future journal — a meeting, a trip, a day they have already planned — means every task is attached to a moment they have already committed to thinking about. If there is no such journal, the user creates one first, and that act is itself a small useful piece of planning.

### Creating a task

Tasks are created from a journal. The journal the user creates the task from becomes its creating journal; it is never chosen separately.

The create interaction requires:

- the task text
- a due journal, chosen from the user's future journals

The create interaction optionally accepts:

- one or more contacts

If the user has no future journals, the product should say so plainly and offer to create one, rather than presenting an empty picker.

The due journal picker should make selection easy without becoming a journal browser: recent and near-future journals first, with search across future journals by title and date.

### Status and lifecycle

A task has exactly one of three statuses:

- **Not done** — the default on creation
- **Done** — the commitment was met
- **Cancelled** — the commitment is no longer relevant

Rules:

- Done is reversible. A task marked done may be returned to not done.
- Cancelled is the terminal soft state, but it is not irreversible: a cancelled task can be reopened by giving it a new future due journal, which returns it to not done.
- Marking a task done or cancelled does not require a journal and does not create a journal link.
- Task text and contact links can be edited at any time, in any status.
- Hard deletion exists for genuine mistakes, but the UI should treat cancelling as the normal action and deletion as the exception. This mirrors the stance the journals specification takes on event journals.

### Journal links and retargeting

The creating journal is set once and never changes.

The due journal may be **retargeted** to a different future journal at any time, in any status. This is how a user extends a deadline, and it is also how a lapsed or cancelled task is brought back.

Retargeting always leaves the task **not done**:

- a task that was already not done stays not done
- a **cancelled** task is reopened — this is the reopening rule described under *Status and lifecycle*
- a **done** task is likewise reopened, and the UI must say so before it happens, because reopening a completed task is rarely what the user meant by moving a date

The new due journal must satisfy the future-dated invariant at the moment it is set, whatever the task's previous status.

When a due journal is retargeted:

- the new journal becomes the due journal
- the **previous due journal is automatically retained as an intermediate journal**

This is the one automatic link in the model, and it exists so the history of a repeatedly-deferred task stays visible on the journals it passed through.

Intermediate journals are otherwise **explicit only**. Nothing is inferred from where the user happened to be when they edited a task. A link is created when the user deliberately:

- attaches an existing task to the journal they are viewing, or
- links a journal to a task from the task itself

Intermediate links can be removed. The creating and due links cannot be removed, only replaced in the case of the due journal.

Updating a task never requires a journal. The journal links describe where the task is relevant and where it should be visible — they are not an edit ceremony.

### Lapsed tasks

A task is **lapsed** when its due journal's date has passed and it is still not done. A task whose due journal has been cancelled is also treated as lapsed.

Lapsed tasks behave as follows:

- They **disappear from the dashboard entirely and silently.** There is no overdue section, no counter, no badge, and no notification.
- They **remain visible on every journal they are linked to** — creating, due, and intermediate — clearly marked as lapsed.
- They are not automatically cancelled, and they are never automatically rolled forward to another journal.

The user encounters a lapsed task when they next look at one of its journals. At that point they can:

- **resurrect** it, by retargeting it onto a new future journal, which returns it to the dashboard in due course
- **cancel** it
- **mark it done**, if it turns out they did it

This is intentional. A commitment the user has let slide has already told them something. The product's response is to stop asking, not to accumulate a list of reproaches.

### Contacts on tasks

A task may reference zero or more contacts through explicit structured links, in the same spirit as journal-contact relationships. Contacts are not parsed out of the task text.

Contact links are used to:

- show the contact on the task wherever it is displayed
- surface the task on the contact's activity history, as a read-only record alongside their journals and other activity
- give the daily summary the ability to connect a task to a person

Task-contact links do not carry a relationship type, a role, or an attendance status. They are a plain reference.

### Events and history

Tasks are first-class domain entities. They emit domain events through the same transactional outbox and stream that contacts and journals use, and those events project into field history exactly as contact and journal events do.

Events should cover, at minimum:

- task created
- task text updated
- task status changed
- due journal retargeted
- journal linked or unlinked
- contact linked or unlinked
- task deleted

Each event carries provenance and the actor, consistent with the activity history specification, so a task's change history is available and future integrations can consume task activity without new plumbing.

### Tasks and search

Tasks are **not** indexed and do not appear in global search. There is no tasks index, and a global search never returns a task.

The search indexer should ignore task events rather than failing on them.

This follows from the no-accumulating-backlog principle: a searchable task corpus is a backlog by another name.

### Where tasks appear

There are exactly two places where tasks are *worked with* — where the user reads them, actions them, and browses them as tasks.

**On journals.** A journal's detail view shows the tasks it is linked to, grouped by the nature of the link:

- tasks **due** in this journal
- tasks **created** in this journal
- tasks **mentioned** in this journal (intermediate links)

Each entry shows the task text, its status, its linked contacts, and — for lapsed tasks — a clear lapsed marker with the resurrect, cancel, and done actions available inline. The journal list may show a lightweight indicator that a journal has tasks due in it, consistent with the other list-level indicators described in the journals specification.

**On the dashboard.** As described below.

There is deliberately no third working surface. No `/tasks` route, no global list, no filters-by-status browser.

A task does also appear as an entry in a linked contact's activity history, and its own changes appear in field history. Neither is a third working surface: both are read-only records of what happened, entries are not actionable from there, and neither can be filtered down to "everything still outstanding". The distinction that matters is between a record of the past, which tasks belong in like any other entity, and a place to go and work through tasks, of which there are only two.

## Journal Anchor Integrity

Because a task can never exist without both anchors, journal operations must respect those anchors.

### Deletion

Deleting a journal that is the creating journal or the due journal of **any** task is **blocked**.

The failure must be explanatory rather than opaque: it should name each task that blocks the deletion and link to a journal where that task can be actioned. Because tasks have no route of their own, that link always targets a journal detail view — the task's due journal, or its creating journal when the due journal is the one being deleted. From there the user can cancel, delete, or retarget the task and then retry the deletion. This applies regardless of task status — a done task's link to the journal it was created in is part of the record.

Over the API and MCP the same failure identifies the blocking tasks and the journals that surface them, so an agent can resolve them without going through the UI.

Deleting a journal that is only an **intermediate** link is permitted. The intermediate link is removed and the task is unaffected.

Because deletion is blocked rather than cascading, and because cancellation is always available as an alternative, the product should continue to steer users toward cancelling journals rather than deleting them.

### Merge

Journal merge is **not** blocked. Merge is core to making calendar sync usable, as the journals specification sets out, and blocking it would make sync workflows unusable.

When two journals are merged:

- task links pointing at the absorbed journal are re-pointed at the surviving journal
- a task cannot end up linked twice to the same journal in the same role; duplicate links collapse
- if the surviving journal ends up as both the creating and the due journal of a task, that is permitted and the task is unaffected

Merge never changes a task's status.

### Cancellation

Cancelling a journal is permitted and does not affect a task's links.

A not-done task whose **due** journal has been cancelled is treated as lapsed: it leaves the dashboard and remains visible on its journals, where the user can retarget it. The journal listing on the task should make it obvious that the reason is cancellation rather than the passage of time.

## The Home Dashboard

### Purpose

The home page becomes the user's daily briefing. It answers, in one screen: what is today, what have I got coming that I might forget, and what did I say I would do.

It replaces the placeholder card grid entirely.

### Composition

The dashboard has four sections:

1. **Today's summary** — the AI daily summary for today
2. **Agenda** — today's schedule, with tomorrow available beneath it
3. **Tasks** — what is due in the coming week
4. **Upcoming dates** — important contact dates in the coming week

The summary is the headline. The other three are the evidence behind it, and the place the user goes to act.

All four are windowed on the user's configured timezone, anchored on "today" server-side. The dashboard takes no date parameters — it is always about now.

### Today's summary

The dashboard shows the AI daily summary for today, in full.

- It is the **same** summary entity the journals view shows for today. There is no separate dashboard briefing.
- It is read-only, consistent with the journals specification.
- The user can request a regeneration.
- If a summary cannot be produced — AI is not configured, or generation failed — the dashboard says so quietly in place, and the rest of the page still works.

Its extended inputs and refresh behaviour are described under *Extending the Daily Summary* below.

### Agenda

The agenda shows today's schedule as a time-ordered list.

Required behaviour:

- Today's event journals are listed in time order.
- All-day items are pinned above timed items.
- Each entry shows its title, its time, its location where present, and its participants where present.
- Each entry links to the journal.
- Cancelled events are either shown clearly marked as cancelled or omitted; they must never appear as if they are still happening.

**Tomorrow** appears beneath today, collapsed by default, expandable in place. This makes the dashboard useful in the evening as well as the morning, without turning it into a calendar. It shows the same information in the same form.

When there is nothing scheduled, the agenda should say so in a single line rather than rendering an empty container.

The agenda is not a calendar view. Month, week, and day calendar views belong to the journals experience as described in the journals specification.

### Tasks

The tasks section shows not-done tasks whose due journal falls between **today and seven days ahead**, inclusive.

Required behaviour:

- Ordered by due journal date, soonest first.
- Capped at **five** items, with a show-more that reveals the remainder of the seven-day window.
- Each entry shows the task text, the due journal's title and date, and any linked contacts.
- Each entry links to its due journal.
- Each entry offers marking done inline, without leaving the dashboard.
- Done and cancelled tasks do not appear.
- Lapsed tasks do not appear.

When the window is empty, the section says so in one line. An empty task section is a good outcome, and should not read as an error or an omission.

The cap is deliberate. If the user has more than five things due in the next week, the dashboard's job is to show them the next five, not all of them.

### Upcoming dates

This section shows important contact dates falling in the next **seven days**, matching the tasks window so the whole dashboard looks the same distance ahead.

Required behaviour:

- Recurring dates such as birthdays and anniversaries are resolved to their occurrence within the window; the underlying date's precision is respected, so a date with no year still produces an occurrence and a date with a year can show an age or a count of years where meaningful.
- Each entry shows the contact, the date type, and how many days away it is.
- Each entry links to the contact.
- Ordered by date ascending, then by contact importance descending (see below).
- Capped, with a show-more revealing the rest of the window.

When nothing falls in the window, the section says so in one line.

### Contact importance for dashboard ranking

When two contacts have important dates on the same day, the more important contact is shown first. Importance is inferred from the same behavioural signals that already rank contacts in global search:

- whether the contact is marked as a favourite
- how many journals the contact has appeared in recently
- how much activity the contact has had recently

These signals are applied in the same order of precedence search uses, so that a contact who ranks highly in search also ranks highly on the dashboard. The product must not introduce a separate, user-configured importance field — importance stays inferred, and stays consistent across the system.

### Loading, freshness, and errors

- The dashboard is a read-only projection. Nothing on it mutates data except the inline task actions.
- Sections should render independently: a failure to produce a summary must not prevent the agenda, tasks, and dates from displaying, and vice versa.
- The four sections should be retrievable together so the page is one round trip rather than four.
- Acting on a task from the dashboard updates the dashboard in place.

### Navigation

The home page becomes a genuine destination rather than a landing page, and should be reachable from the primary navigation as the default view after sign-in.

## Extending the Daily Summary

The daily summary described in the journals specification is extended by this work. It remains one summary per day, shared by the journals view and the dashboard.

### Extended inputs

For the **current day**, the summary's inputs are augmented with:

- the day's agenda — today's event journals with their times, locations, and participants
- tasks due between today and seven days ahead
- important contact dates falling in the next seven days

For **past days**, the inputs are augmented with:

- tasks that were due in that day's journals, and how they resolved — done, cancelled, or left undone

"How they resolved" means each task's status **at the moment the summary is generated**, not a reconstruction of what it was at the end of that day. The product does not replay field history to rebuild point-in-time status. The consequence is that a past-day summary regenerated after a lapsed task was finally completed will describe that task as done — which is the honest answer to "what became of this", and matches the status the user sees on the journal itself.

The forward-looking material — upcoming contact dates and next-week tasks — belongs to the current day only. A summary of last Tuesday should describe last Tuesday, not what was coming up after it.

### Eligibility

The current eligibility rule requires two or more journals on the day. That rule is changed as follows:

- **Today is always eligible.** A summary is generated for the current day regardless of how many journals it has, because a day with no journals but three tasks and a friend's birthday is exactly the day the user most needs a briefing for.
- **Past days keep the existing rule.** A past day with fewer than two journals remains ineligible and continues to produce no summary.

### Freshness

Today's summary must reflect today. It is regenerated when it is read if it was not generated **today in the user's timezone** — a summary produced yesterday evening is stale by the morning and must not be served.

Beyond that staleness rule, the existing caching behaviour is unchanged: a summary generated today is served from cache, and concurrent generation is prevented.

Invalidation must follow the summary's **inputs**, not only its journals. Now that tasks and contact dates feed the summary, a day's summary is invalidated by:

- changes to that day's journals, as today
- changes to the tasks that feed it — created, retargeted into or out of the window, status changed, or contact links changed
- changes to important contact dates falling in the window, for the current day

Without this, a summary generated earlier today could still be describing a task the user has already ticked off.

Invalidation is **lazy**: it marks the cached summary stale, and the next read regenerates it. Ticking off four tasks in a row therefore costs one regeneration, not four. A summary is never regenerated underneath a user who is acting on the dashboard — the sections beneath it update in place, and the summary refreshes on the next load.

Users can still explicitly request a regeneration.

### Tone and safety

The existing constraints from the journals specification continue to apply, and matter more now that the summary is the first thing the user reads:

- The summary is short and practical.
- It is grounded in the actual journals, agenda, tasks, and dates it was given.
- It is descriptive rather than speculative, and must not invent commitments the user did not make.
- It is read-only and must never silently rewrite the record.
- It must not restate the sections beneath it item by item. Its value is in connecting them — noticing that a task is due before a meeting that a contact with a birthday this week is attending.

## MCP and AI-Agent Parity

There must be no meaningful UI-only behaviour in this work.

### Tasks over MCP

MCP must support the ability to:

- create a task, specifying the creating journal, the due journal, the text, and any contacts
- update a task's text
- set a task's status to done, not done, or cancelled
- retarget a task's due journal
- attach and detach intermediate journals
- link and unlink contacts
- retrieve a single task with its journals and contacts
- list the tasks linked to a given journal, by link role
- list not-done tasks due within a forward window, defaulting to seven days
- delete a task

Deletion was absent from this list while every other operation appeared on it, which left it ambiguous rather than excluded. "There must be no meaningful UI-only behaviour in this work" settles it: an agent that can create a task by mistake must be able to undo that mistake, or the user is left cleaning up after their assistant by hand. The stance that cancelling is ordinary and deleting is the exception is preserved where it belongs — in what the tool's description tells the agent — not by withholding the tool.

Every invariant in this specification applies identically to MCP. In particular, an agent must not be able to create a task without both anchors, must not be able to set a due journal that is not an existing future journal, and must receive a clear, actionable error when it tries.

Task tools are controller-equivalent: they call services that own their own transaction boundary and do not open transactions themselves.

### The dashboard over MCP

There is deliberately **no** composite dashboard tool in this phase. Agents compose the equivalent view from the existing pieces: the daily summary tool for today, journal browsing for the agenda, the task listing tools, and the contacts tools for upcoming dates.

The tradeoff is accepted knowingly: an agent never sees exactly the arrangement the user sees, and assembling it costs several calls rather than one. Every underlying capability is available, so nothing is unreachable. If agent workflows later show that the composition itself is the valuable part, a single dashboard tool can be added without revisiting anything else in this specification.

### The daily summary over MCP

The existing daily summary tool continues to serve the summary for a given date, and picks up the extended inputs, the always-eligible-today rule, and the staleness-based refresh automatically, since they are properties of the summary rather than of the surface requesting it.

## Success Criteria

This work will be successful when the user can:

1. Open the home page and know what their day looks like without navigating anywhere else.
2. Capture a commitment in the journal where it came up, attach it to the future journal where it matters, and be reminded of it exactly then.
3. Extend a deadline by moving a task to a later journal, and still see the trail of journals it passed through.
4. Let a task lapse without the system ever nagging them about it, and still find and resurrect it from the journal it was due in.
5. Never encounter a screen that lists all their outstanding tasks together.
6. See the birthdays and anniversaries that matter, for the people who matter, with enough notice to act.
7. Read one daily summary that draws their journals, their schedule, their tasks, and their people together.
8. Do all of the above through an AI agent as well as through the interface.

## Delivery Notes

This specification defines target product behaviour. Delivery may be phased, but phases should preserve coherence.

Examples of incoherent phases:

- Tasks in the domain model without task display on journals leaves tasks uncreatable and invisible.
- Tasks without the anchor-integrity rules allows journal deletion to violate the model's core invariant.
- A dashboard tasks section without the inline done action makes the dashboard a dead end.
- The extended summary inputs without the always-eligible-today rule leaves the dashboard's headline blank on exactly the quiet days it is most useful.
- Tasks in the UI without MCP task tools breaks the AI-first principle this work exists to serve.

A wireframe of the home dashboard should be produced from this specification before implementation begins.
