# Frontend Design - Personal CRM & Journal System

This document provides comprehensive frontend design patterns and component guidelines using shadcn/ui.

## Frontend Component Guidelines

### shadcn/ui Component Structure

- Use shadcn/ui components for consistent design system and AI assistant support
- Import components from `@/components/ui/` path with clear structure
- Use Lucide React icons for consistent iconography across the application
- Implement proper TypeScript interfaces for all component props
- Include accessibility attributes (`sr-only`, `aria-label`) for screen readers
- Use Tailwind CSS classes for styling with semantic color tokens
- Implement responsive design with mobile-first approach using Tailwind breakpoints

### Form Validation Guidelines

- Use React Hook Form with Zod for validation
- Import `zodResolver` for schema integration
- Define Zod schemas with clear error messages
- Use `FormField` components for consistent form structure
- Include `FormLabel`, `FormControl`, and `FormMessage`
- Add `FormDescription` for helpful field guidance
- Use Australian English terminology ("Organisation" not "Company")
- Provide realistic Australian placeholders (0400 000 000)

### Responsive Layout Guidelines

- Use CSS Grid with responsive breakpoints
- Start with single column on mobile (`grid-cols-1`)
- Scale up for larger screens (`sm:grid-cols-2`, `lg:grid-cols-3`)
- Adjust gaps proportionally with screen size
- Use consistent spacing patterns across components

### Tailwind Configuration Guidelines

Tailwind v4 is configured **entirely from CSS**, in `frontend/src/app/globals.css`.
There is no `tailwind.config.js`/`.cjs` — v4 only loads one via an explicit
`@config` directive, and we deliberately do not use it (see #1186).

- **Theme tokens**: define them in the `@theme inline` block. Token values are
  self-contained colours (oklch) consumed as `var(--token)` — **never**
  `hsl(var(--token))`, which is a v3 contract that compiles to an invalid colour
  (see #1178). Light values live in `:root`, dark overrides in `.dark`.
- **Plugins**: register with `@plugin '<pkg>';` (e.g. `@tailwindcss/typography`).
  A v3 `plugins: [...]` array does nothing.
- **Animations**: `animate-in` / `animate-out` and friends come from
  `@import 'tw-animate-css';`. The v3-only `tailwindcss-animate` plugin is not
  compatible with v4.
- **Source detection**: automatic. There is no `content` array to maintain.
- Prefer the semantic token classes (`bg-background`, `text-muted-foreground`,
  `border-border`) over raw colours so light and dark both work.

A missing `@import` or `@plugin` does **not** fail the build — the affected
utilities just emit no CSS and the UI renders silently unstyled. Utilities the UI
depends on are therefore asserted in
`frontend/src/app/__tests__/globals-css.test.ts`; extend it when adding a plugin.

### Accessibility Guidelines

- Include `aria-label` attributes for screen readers
- Use `sr-only` class for screen reader only content
- Implement proper focus management with visible focus rings
- Ensure keyboard navigation works for all interactive elements
- Use semantic HTML elements and ARIA roles
- Test with screen readers and keyboard-only navigation

### Loading State Guidelines

- Use shadcn/ui `Skeleton` component for loading states
- Match skeleton dimensions to actual content layout
- Provide skeletons for all major content areas
- Use consistent spacing and proportions
- Implement smooth transitions between loading and loaded states

## Component Architecture

### Component Organization

- Organize components by feature/domain
- Use barrel exports for clean imports
- Separate UI components from business logic
- Create reusable compound components
- Follow single responsibility principle

### State Management

- Use React hooks for local component state management
- Implement custom hooks for shared logic and reusable patterns
- Use Zustand for global state management with simple, AI-friendly patterns
- Use TanStack Query for server state management and API caching
- Use React Hook Form with Zod validation for form state
- Keep state as close to usage as possible for maintainability

### Invalidating After a Mutation

Mutation handlers must refresh the cache through
`invalidateAfterMutation(queryClient, ...filters)`
(`frontend/src/lib/api/invalidate-after-mutation.ts`) rather than calling
`queryClient.invalidateQueries` directly.

- **Why:** `invalidateQueries` only cancels an in-flight request when the query
  *already has data*. A list loading for the first time — a fresh mount, or a new
  query key from a filter change — keeps the request that started before the
  mutation; when it settles, React Query caches its pre-mutation rows, clears
  `isInvalidated` and stamps a fresh `dataUpdatedAt`, so the app-wide five-minute
  `staleTime` suppresses any refetch and the user keeps seeing data they just
  changed ([#1203](https://github.com/hjed/personal-management-system/issues/1203)).
  The helper cancels first, which has no such guard.
- **Pass every key set in one call** — `invalidateAfterMutation(queryClient, { queryKey: a }, { queryKey: b })`
  — not one call per key. All the key sets must be cancelled before any of them
  is invalidated, or the later ones stay exposed to the same race.
- Optimistic handlers keep their existing `cancelQueries` in `onMutate`; their
  `onSuccess`/`onSettled` still invalidates through the helper.
- A filter asking for `refetchType: 'none'` cancels only the queries that
  already hold data. Cancelling a first-load query nothing is going to refetch
  would strand its observer on a spinner, so its request is allowed to land.
- Call it fire-and-forget (`void invalidateAfterMutation(...)`) as the old
  `invalidateQueries` calls were; `await` it only where the handler already
  awaited the refresh.

### Task Query Keys

`taskKeys` (`frontend/src/lib/api/tasks.ts`) hangs three namespaces off
`['tasks']` as **siblings**, never nesting one inside another:

| Factory | Key | Feeds |
| --- | --- | --- |
| `detail(taskId)` | `['tasks', 'detail', id]` | a single task read whole |
| `journalList(journalId, role?)` | `['tasks', 'journal', id, role \| null]` | a journal's task section |
| `upcomingWindow(days)` | `['tasks', 'upcoming', days]` | the home dashboard's task section — **reserved, with no hook yet**: the listing endpoint landed in ITER18-001 Phase 14, but nothing reads it until the dashboard is built (ITER18-004) |

- **The sibling arrangement is the contract**, not an accident of naming: a
  journal's task list and the dashboard's task section must be invalidatable
  independently, and nesting either under the other would silently remove that.
  Two tests assert it in both directions. The `upcoming` namespace was reserved
  before anything read it for exactly that reason — adding a sibling later is the
  change most likely to end up nesting it.
- **A mutation names only the namespaces its change can reach.** Attaching or
  detaching an intermediate ("mentioned") journal leaves `upcoming()` alone —
  that listing selects on the *due* journal, so a mention cannot move a task in
  or out of a forward date window.
- **The role is part of the journal-list key.** A filtered listing narrows
  `link_roles` as well as the rows, so it is a different answer rather than a
  subset of the unfiltered one.
- **A task's history is not under `taskKeys` at all.** `taskHistoryKeys` is
  `['task-history']`, following `journalHistoryKeys` rather than becoming a
  fourth namespace here, and the arrangement that reads as tidy is the wrong
  one. `useUpdateTask.onMutate` cancels and optimistically patches *every* query
  under `taskKeys.all`: a history page underneath it would have its in-flight
  fetch cancelled by a status click — leaving an open feed on "No activity yet"
  with nothing to refetch it — and `patchResource` matches on id alone, so a
  `field_history` row id colliding with a task id would have `status` and `text`
  merged into it. Every journal and contact mutation invalidates `taskKeys.all`
  too, which would discard the history for a change that cannot affect it.
  `refreshTask` names `taskHistoryKeys.list(taskId)` **explicitly**, which is
  the point: a task's own write does make its history stale, and nothing else
  should be able to throw it away by accident. Pinned in both directions by
  `task-cache-freshness.test.ts`.
- Task failures throw `TaskApiError`, whose `message` is `errors[0].detail` as
  every other client's is, **plus** the JSON:API `status`, `code` and `meta`
  beside it. Surfaces branch on the code — `TASK_REOPEN_NOT_ACKNOWLEDGED` is a
  confirmation to ask for, not an error to report, and `useRetargetTask` raises
  no toast for it.
- **Task mutations opt out of the app-wide `retry: 1`** (`lib/providers.tsx`).
  Creating a task is not idempotent, so a retried `POST` whose first response was
  merely lost records the commitment twice; and a refusal here is often the
  answer rather than a failure, so retrying it delays the confirmation the caller
  should be showing and logs a second refusal for every one the user resolves.
  Reads keep the default retry. Any client that builds product behaviour on a
  mutation's *error* needs the same opt-out.
- A deleted task's detail is **removed** from the cache, not invalidated:
  invalidating would refetch it into a 404, and leaving it would let a later
  `useTask` render a deleted task from cache for the whole `staleTime`.
- Invalidation is **not** delayed behind a `setTimeout`. The write commits in
  the service layer before the response is sent, so there is no read-after-write
  race to wait out (the same reasoning as the journal-tag client, #1204).

### The Journal Task Surface

`JournalTasksSection` (`components/journals/JournalTasksSection.tsx`) renders a
journal's tasks in the three groups the specification names — due, created and
mentioned — with `JournalTaskRow` for each entry. It is one of only two surfaces
where tasks are worked with; there is no `/tasks` route.

- **The grouping comes from `meta.groups`, never from `link_roles`.** A task
  holding two roles in the same journal (both anchors, or a due journal it
  already mentioned) appears **once** in `data` — JSON:API forbids the same
  resource twice — and is named in each of its groups. The section indexes
  `data` by id and walks each group's **ordered** id list, so it renders such a
  task under both headings and never re-sorts an order the listing already
  decided server-side.
- **Every status is shown, lapsed included.** A lapsed task leaves the dashboard
  silently, and its journals are where the user is meant to meet it again, so
  this listing must never filter one out. Done and cancelled rows are
  de-emphasised (muted, struck through) but never hidden — the stance the
  wireframe takes on cancelled journals.
- **Nothing renders while the listing loads**: most journals hold no tasks, so
  a skeleton would flash on nearly every journal detail view for a section
  usually about to render nothing. An empty group is omitted rather than shown
  as a heading with nothing under it. A listing that has *loaded* and found
  nothing still renders the card, with one line saying so — narrowed from the
  original "nothing renders when there is nothing to show" when the card gained
  an affordance of its own, because the journal most likely to want *attach an
  existing task* is exactly the one with no tasks on it yet.
- **A failed listing is the one case that does render.** One quiet line, because
  hiding the section on error is indistinguishable from "this journal has no
  tasks" — a journal whose lapsed tasks failed to load would read as clean,
  which is the outcome the lapsed design exists to prevent. It carries the
  **create** affordance but not the **attach** one, and the difference is the
  rule rather than an inconsistency: attach needs the set of tasks already
  linked here and reads it from this listing, and create needs nothing from it.
- **Lapse wording lives in `lib/task-display.ts`, not in the components.** The
  backend ships `LapseReason` as structured data so surfaces can word it
  differently, and the specification requires a journal to make clear that a
  task lapsed because its due journal was *cancelled* rather than because the
  date went by. `lapseWording` keeps the two distinguishable, and pure so a test
  can assert it without rendering.
- **The row's left accent bar diverges from wireframe W22**, which keys it to
  the due journal's type/calendar colour: a task's journal references carry only
  id, title, date and cancelled, so the bar is keyed to whether the commitment
  is still live. Revisit if the read model ever carries a colour.
- Accessibility: each group is a `<section aria-labelledby>` with an `h4` and a
  list, under the card's own `h3`, so a group is announced by name with its item
  count rather than as a flat run of text.

#### The task's own change history

A task has no route, so ITER18-003 Phase 8 made its history a task-scoped read
and Phase 9 renders it here: a disclosure on `JournalTaskRow` that expands into
`TaskActivityFeed` (`components/tasks/TaskActivityFeed.tsx`).

- **It is the shared feed, not a bespoke list.** `TaskActivityFeed` is a thin
  wrapper over `components/history/ActivityFeed` supplying `useTaskHistory`,
  mirroring the contact and journal wrappers, so all three surfaces share one
  layout, one set of provenance icons and one pagination behaviour — which is
  what the activity-history specification asks for.
- **The row does not mount the feed until it is opened**, rather than mounting
  it with a disabled query: a journal can hold many tasks, and a flag would
  leave a hidden card and empty state in the DOM on every row to achieve less.
- **It is the row's last child, and the feed renders no heading.** Both follow
  from where it sits. Putting it above the contacts would push the people a
  commitment involves below an activity card when it opened, against the
  specification's "show the contact on the task wherever it is displayed"; and
  the journal page already has an "Activity" `h3`, so a feed header per open row
  would be a run of identically-named headings inside a list. `ActivityFeed`
  therefore takes `title`, and `null` suppresses the header.
- Accessibility: the trigger is a real button carrying `aria-expanded` and
  `aria-controls`, and its accessible name **names the commitment** — every
  row's would otherwise be "Show history", which is what a screen-reader user
  hears tabbing through a journal's tasks. The panel is a `role="region"`
  labelled by that trigger, which is what replaces the heading it no longer
  renders.
- **Entries are inert.** Nothing inside the feed is actionable on either surface
  it appears on; the only button is the provenance icon, which carries the
  tooltip. That is a product rule, not a styling choice — the specification's
  *Where tasks appear* allows two working surfaces and says a record of the past
  is not a third.

#### Wording a history entry

`taskEntryDescription` (`lib/history-display.ts`) words a task's history rows,
falling through to the generic wording for everything it has nothing better to
say about. It is a pure function for the reason `lapseWording` is: what an entry
says is a product rule a test should be able to assert without rendering.

- **It is gated on `entity_type`, never on the field name alone.** The marker
  vocabulary is shared: a journal writes `__created__`, and a contact records
  its own creation as `field_name="status"` carrying `"created"`. Wording by
  field name would relabel other domains' rows — the contact one silently.
- **The same row reads differently on each feed it can appear on.** A task's
  contact membership is projected once, onto the task, and read from both ends:
  *Linked a contact* on the task's own history, *Linked to a task* on the
  person's. `ActivityFeed` therefore passes its `entity` down to `ActivityItem`.
- **No entry names an id the reader cannot use.** A retarget's values are
  journal ids and a contact-link row's values are the contact's own id, so both
  are worded without them. What a contact-feed entry names instead is the
  **task**, from `entity_label` on the row — *Linked to a task: "Return the
  borrowed harness"* — falling back to the unnamed wording while projection
  catches up, because an absent name is not the same as a task without one. The
  label is not repeated on a task's own feed, where the reader is looking at the
  task.

#### Inline status actions

`JournalTaskActions` (`components/journals/JournalTaskActions.tsx`) carries the
row's done / return-to-not-done / cancel buttons and its confirmed delete. It is
a component of its own rather than markup inside `JournalTaskRow` because it
holds mutations and an offer table, while the row is a pure rendering of the
listing's payload.

- **What a row offers is a table, not a condition**, and it lives in
  `lib/task-display.ts` beside the lapse wording: `statusActions(status)`
  returns `done + cancel` for a not-done task, `not-done + cancel` for a done
  one, and **nothing at all for a cancelled one**. That last entry is the rule
  the table exists to state — the service gives cancelled exactly one exit,
  retargeting onto a new future journal, and refuses `cancelled → done` and
  `cancelled → not done` alike, so either button could do nothing but draw a
  409. A test guards the table against drifting from that matrix. A **lapsed**
  task is still not done and keeps the full offer: lapsing is a marker on a live
  commitment, never a disabled state.
- **Cancel is the ordinary action and delete is the exception**, which the
  specification states twice. Delete is last, icon-only, `ghost` and
  `text-muted-foreground` — never a `destructive` button sitting beside the
  ordinary ones — and is gated by an `AlertDialog` whose body says what
  cancelling would keep instead.
- **The optimistic update belongs to `useUpdateTask`, not to the component.**
  `onMutate` cancels `taskKeys.all`, snapshots it with `getQueriesData` and
  patches it with `setQueriesData`; `onError` restores every snapshot;
  `onSettled` invalidates through `invalidateAfterMutation`. Keeping it in the
  hook is what lets the retarget dialog and the dashboard inherit it, and it is
  the shape this document already sanctions under *Invalidating After a
  Mutation*.
- **The patch is shape-aware because the attributes are embedded in two
  shapes** — the single-resource detail read and the array-shaped journal
  listing and upcoming window. Patching one and not the other would leave a
  namespace showing the status the user just changed.
- **Leaving `not_done` clears `lapsed`/`lapse_reason`; returning to it does
  not.** Lapse is derived from "still not done and the due journal is no longer
  ahead of it", so a task that has just been ticked off cannot be lapsed and its
  marker must go at once — otherwise completing a lapsed task leaves it reading
  `Done · Lapsed` until the refetch. The reverse is not knowable client-side, as
  it needs the day boundary in the user's timezone, so it is left to the
  invalidation a beat later.
- **The toast is the announcement.** `useUpdateTask` words its success message
  from what changed — "Task marked done" / "Task returned to not done" / "Task
  cancelled", from `statusChangeWording` — rather than the generic "Task updated
  successfully", which a text-only update still uses. Sonner's `Toaster` is
  already a polite live region, so a second `role="status"` node on the row
  would make a screen reader say the same thing twice.
- **`aria-busy` sits on the group, not on the button that was pressed.** The
  optimistic patch rewrites the cached status before the request settles, so the
  listing rerenders and the row comes back offering the *new* status's actions —
  press *Done* and a moment later the screen shows *Not done* and *Cancel*. A
  busy flag matched to the pending action is then false on everything visible.
  The group is what is mid-write, and the group is what says so.
- **The in-flight guard is scoped to the task, not to the hook instance.**
  `useTaskWriteInFlight(taskId)` reads the mutation cache through
  `useMutationState`, because a journal renders a task holding two roles **once
  per group** — one commitment, two `JournalTaskActions`, two independent
  mutations. A guard reading its own `isPending` locks only the copy that was
  clicked; the optimistic patch then rerenders the twin offering the opposite
  move, one click from racing the write already in flight. Any surface showing
  that task locks with it, which is also what should happen when a retarget is
  open elsewhere on the page.
- **The rollback is per task *and* per cache entry.** Per task, because two rows
  share a cache entry and restoring the whole entry would undo a row the user
  had just ticked because an unrelated one failed. Per entry, because the detail
  read and the journal listing are fetched independently and can legitimately
  disagree — writing one entry's captured value into all of them would replace a
  fresher cached value with a staler one. Both were got wrong once, in the same
  six lines, in opposite directions: a rollback coarser than the thing it undoes.
- Accessibility: real buttons, so keyboard reach is structural; each accessible
  name **contains** its visible label (WCAG 2.5.3 — "Done" inside "Mark done");
  every action is disabled while any write against that task is in flight; and
  the group is `role="group"`
  `aria-describedby` the row's task text, because every row's buttons are named
  the same and the text is what tells them apart.

#### Retarget and resurrect

`RetargetTaskDialog` (`components/journals/RetargetTaskDialog.tsx`) is one
dialog doing four things, because the specification treats them as four
different acts against one endpoint: extending a deadline, meeting a **lapsed**
commitment again, bringing a **cancelled** one back — its only exit, since the
service refuses both status calls out of cancelled — and reopening a **done**
task, which the UI must warn about before it happens. The trigger's label, the
heading and the explanation are chosen per case by `retargetAction(status,
lapsed)` in `lib/task-display.ts`: **Resurrect**, **Reschedule**, **Reopen**.

- **The retarget affordance is not in the status offer table**, and that is a
  statement rather than an oversight. `statusActions` is the *transitions* a row
  offers; a retarget writes a journal link, forces the status to *not done*
  whatever it was, and is refused on grounds the status matrix knows nothing
  about. It is offered in **every** status, including cancelled, where it is the
  only thing on the row besides delete.
- **The reopen confirmation is the server's refusal, not a client-side
  prediction.** A done task's retarget is sent *without* the acknowledgement,
  refused with `TASK_REOPEN_NOT_ACKNOWLEDGED` — a 409 that writes nothing, and
  which `useRetargetTask` deliberately does not toast — and only then confirmed
  and re-sent with `acknowledge_reopen: true`. Predicting it in the browser
  would be a second copy of the service's rule, free to drift; worse, it would
  sit *ahead* of the future-date check, so a done task retargeted onto a past
  journal would be asked to confirm a request that was never going to succeed.
  The service checks the acknowledgement **last** for exactly that reason, and
  Phase 8 pins that ordering at both of its surfaces.
- **A rejected journal lands on the field, and the toast stays.**
  `TASK_DUE_JOURNAL_NOT_FUTURE` is mapped through `form.setError` onto the
  due-journal field and focus returns to it, which is what the criterion asks
  for. The toast the hook already raises is *not* suppressed: Phase 15 asserts
  that every retarget failure but the acknowledgement toasts, "so the exception
  cannot widen by accident", and a user who has scrolled away from the field
  would otherwise get no report at all. The criterion says "rather than as a
  toast-**only** failure", which this satisfies by adding rather than replacing.
- **Focus is moved in an effect, not in the handler that causes the move.** The
  moments that decide where focus belongs — the reopen gate appearing, the gate
  being declined — swap which half of the dialog is mounted, so a `focus()` call
  inside the click handler reaches for an element React has not rendered yet.
  This was found by a failing test, not by reading. Focus **on open** is
  `DialogContent`'s `onOpenAutoFocus` rather than the effect: Radix's default
  lands on the first tabbable node, which happens to be the search box today,
  and saying so explicitly stops a control added above the picker from moving
  focus silently — and stops Radix and the effect racing for the same element.
- **Nothing moves while the write is in flight, and the dialog will not close
  over it.** The picker is disabled and Cancel and Escape are refused until the
  request settles. Both matter for the same reason: the request has already
  left. A selection that changed mid-flight would put the server's rejection
  against a journal the request never named — and would let the reopen
  confirmation, which reads the current choice, describe a refusal that was
  about a different journal. A dialog that vanished on Cancel and then toasted
  *"Task moved"* a second later would report the opposite of what the user had
  just asked for. **Aborting the request instead was considered and rejected**:
  a `POST` that has reached the server may already have committed, so
  cancelling it client-side would make the UI's claim less true rather than
  more. The success path closes directly rather than through the guard, since
  there is nothing left to protect and `isPending` may not have settled in that
  closure.
- **The in-flight guard is not read twice.** `JournalTaskActions` already
  computes it from the mutation cache and passes it as `disabled`; the dialog
  gates its submit on that plus its own `isPending`, rather than opening a
  second `useMutationState` subscription per row saying the same thing.
- The picker is not wrapped in `FormControl`. That clones `id`,
  `aria-describedby` and `aria-invalid` onto the child's **root** element, which
  here is the picker's container rather than its input; the three are passed to
  the input explicitly instead, which is what the picker's props exist for.

#### The future-journal picker

`FutureJournalPicker` (`components/journals/FutureJournalPicker.tsx`) is what
makes the fifth invariant workable: a due journal must be an **existing**
journal dated after today, so there is no bare date picker anywhere and nothing
creates a journal as a side effect of holding a task. It is deliberately narrow,
which is what lets the retarget dialog and the create-a-task form mount the same
component unchanged.

- **The ordering is assembled in the browser because the endpoint cannot be
  asked for it, and the naive way round is worse than no ordering at all.** `GET
  /api/journals` answers `ORDER BY event_date_range_start DESC` and takes no
  `sort` parameter, so within any window the *nearest* journals sort **last** —
  and a first page of 100 is the hundred furthest away, dropping exactly the
  ones a picker exists for. **Bounding the window does not fix that**: it caps
  how far the far end reaches while the end that gets cut is still the near one,
  and an ordinary calendar-synced user fills ninety days with more than a
  hundred journals. `fetchNearestFutureJournals` therefore reads `page_count`
  off the response and fetches the **last** page — one extra round trip, only
  for a listing that overflows one — taking the page before it as well when the
  last page is short, or a total just past a page boundary would offer two
  journals where a hundred exist. The window is still bounded, but for a
  different reason: ninety days is what an unsearched picker should *offer*, and
  a search drops the far bound because one that could not reach past ninety days
  would be worse than no search. **A `sort` parameter on the journal list would
  retire all of this**, and is the change worth making if this grows again.
- **The far bound is asked for a day wide.** `end_date` is a bare date and the
  backend reads a bare date as the end of that day in **UTC**, so for a user
  behind UTC the later hours of their own day-90 fall past the cutoff and would
  be dropped from a window advertised as ninety days. The largest offset in use
  is UTC-12, so one day covers every zone, and overshooting the far edge costs
  nothing — nothing downstream trims by it.
- **`start_date` is today, not tomorrow.** It drives
  `event_date_range_end >= :start_date`, so it is generous by construction — a
  journal already under way still matches — and asking for tomorrow would risk
  dropping a journal starting at local midnight in a zone ahead of UTC, whose
  stored instant still reads as today. The strictly-after rule —
  `option.date > today`, mirroring `is_future_dated` — is applied client-side
  where the zone is known.
- **The zone is the user's *configured* one**, read through `useUserSettings`,
  with the localStorage value the settings UI caches standing in while that read
  is in flight. The two can still disagree with the backend, which is why the
  field-level rejection above is the authority and this is only the convenience
  that keeps a doomed choice off the screen.
- **Two kinds of journal are shown and cannot be chosen**, both for reasons the
  server will not supply, and both stated by one `refusalFor` table so the rule
  is in one place. A **cancelled** journal satisfies the write rule — only the
  date is checked — yet a task made due in one is lapsed the instant it is read
  back (`DUE_JOURNAL_CANCELLED`): a resurrection that resurrects nothing. The
  journal the task is **already due in** is worse: `retarget_due_journal` treats
  naming it as a *no-op*, validating nothing, writing nothing and asking for no
  reopen acknowledgement — so a **done** task retargeted onto its own due
  journal answers 200, stays done, and would be reported as moved with the
  confirmation never shown. Hiding either would send the user hunting for a
  journal they can see on every other surface, so both are rendered with a
  marker, `aria-disabled`, and one line saying why.
- **The search is by title, not by date, and the wording says so.** The
  specification asks for "search across future journals by title and date", but
  the listing endpoint's filter is
  `(j.title ILIKE :search OR j.content ILIKE :search)` — it does not touch
  either event-date column, so a date query cannot match. Matching dates against
  the *loaded* window client-side was considered and rejected: it would leave
  one control searching everything by title and only ninety days by date, which
  fails silently at exactly the range a date search is for. Advertising only
  what works is the honest half; extending the endpoint is a follow-up beside
  the `sort` parameter it would sit next to.
- **A failed read offers nothing, rather than the last list that worked.**
  `keepPreviousData` holds the previous key's `data` across a search, so a
  failed refetch arrives with `data` populated *and* `isError` set. Without
  clearing the options the picker would say the journals could not be loaded
  while still offering a usable list from a search the user had moved on from,
  with `aria-expanded` claiming a listbox that contradicts the message beside
  it.
- **`JournalSearchCombobox` was not extended.** It searches *all* journals,
  shows nothing until typed into, and has no date filter, and the merge dialog
  and the parent-journal field depend on all three. Four new branches under two
  existing consumers is a worse trade than one narrow component.
- **The previous list stays on screen while a search loads** — every debounced
  keystroke is a new query key, and without `keepPreviousData` the options are
  replaced by a loading line on each letter, which is the one thing a
  search-as-you-type control must not do.
- The list is **inline rather than a popover**, and populated before the user
  types. The common case is a journal already planned for next week, and a
  combobox revealing nothing until searched makes that the hardest case. Being
  inline also leaves `Escape` to the dialog, where a keyboard user expects it.
- Accessibility: a WAI-ARIA combobox — `role="combobox"` with `aria-expanded`,
  `aria-controls` and `aria-activedescendant`, over a `role="listbox"` whose
  options carry `aria-selected` and, when refused, `aria-disabled`. Arrow keys
  move the active option (landing on a refused one so it is announced, while
  `Enter` declines to take it), the result count is announced through a polite
  live region, and the chosen option carries a check glyph as well as a
  background so the choice is not made by colour alone (WCAG 1.4.1).
  **`aria-expanded` follows whether the listbox actually holds anything**: it is
  hidden while empty, loading or failed, and a combobox claiming to be expanded
  would be pointing assistive technology at an element that is not displayed.
- **An empty window offers to create a journal**, which is the specification's
  "say so plainly and offer to create one, rather than presenting an empty
  picker". It lives in the picker so both dialogs have it — the retarget dialog
  was a dead end here until it landed — and it appears only where it is the
  honest answer: with nothing in the window and **no search** narrowing it,
  because an empty search says something about the search rather than about the
  user's calendar, and never while the listing is loading or has failed. The
  wording keeps saying the journals are not in the next ninety days and keeps
  offering search for a later one; the offer is added, not substituted.
- **"No search" means the live query *and* the debounced one.** The two
  disagree for the length of the debounce in each direction, and a gate reading
  either alone is wrong in one of them: keyed to the debounced term, the offer
  goes on being shown to somebody who has just started searching for the very
  journal it is offering to create; keyed to the live query, it reappears
  beside "No future journals match …" the moment the box is cleared, while the
  results on screen are still the search's. The *message* stays keyed to the
  debounced term, because its subject is what the last completed read found
  rather than what the user is doing — keying it to the live query would have
  it name a result nothing has fetched yet.
- **The offer opens in a new tab, and the label says so.** This control sits
  inside dialogs that are mid-write, so navigating away in place would throw
  away the task being composed and land the user on the journal they had just
  made rather than back on the one they were writing in — with no route back to
  finish. In a new tab the dialog survives, and returning re-reads this list.
  A link that opens a tab without saying so is its own small betrayal, so the
  label carries it.
- **`useFutureJournals` asks for `refetchOnWindowFocus: 'always'`, and that is
  what makes the new tab a recovery rather than a dead end.** The app-wide
  default is `true`, which refetches only queries React Query considers
  *stale*, and this one has a five-minute `staleTime`; a journal created in
  another tab cannot invalidate this tab's cache. Without the opt-out, a user
  who took the offer, made the journal and came back inside five minutes would
  find the picker still empty and the submit still disabled, having done
  exactly what they were asked. It costs one listing request per refocus, and
  only while a picker is mounted — which is only while one of the two dialogs
  is open.
- **`DueJournalFormField`, exported from the same module**, is the picker wired
  to a react-hook-form field, and it exists because *neither* dialog can wrap
  the picker in `FormControl`: that clones `id`, `aria-describedby` and
  `aria-invalid` onto the child's **root**, which here is the picker's
  container rather than its input. Writing that workaround twice is how the two
  dialogs would drift — one growing a description id or a focus target without
  the other.
- The filter, the ordering and the cancelled flag live in the pure
  `lib/future-journals.ts`, not in the component, so the boundary cases — a
  journal dated *today*, a listing arriving newest-first, an `invited` event
  that is not a cancellation — are asserted without rendering anything.
- **Known duplication, recorded rather than fixed here.** "Is this a cancelled
  event journal?" is now read in three places — `lib/future-journals.ts`,
  `components/journals/JournalListItem.tsx` and `lib/calendarEventHelpers.ts` —
  each over a different input type (`JournalResource`, and `DisplayJournal`
  twice). Unifying them means changing signatures across files this phase has no
  other business in, so it is named here as a follow-up rather than done under
  cover of an unrelated change.

#### Creating a task

`CreateTaskDialog` (`components/journals/CreateTaskDialog.tsx`) is the
specification's *Creating a task*, which is four sentences and four rules. It is
triggered from the `Tasks` card header beside *Attach task*, as the primary
action to that one's outline.

- **The creating journal is not a field, because it is not a field on the wire
  either.** `POST /api/journals/{id}/tasks` takes it from the path, so the
  dialog receives `journalId` as a prop and the rule — "the journal the user
  creates the task from becomes its creating journal; it is never chosen
  separately" — can only be checked on the **request**. Its tests assert the
  URL, and that the dialog holds exactly three inputs, so a fourth fails.
- **Offered even when the tasks listing has failed**, unlike the attach
  affordance beside it. Attach is withheld there because it must exclude tasks
  already linked here and reads that set from the listing; creating depends on
  nothing from it. Withholding it would be a restriction with no reason behind
  it, and a journal whose tasks could not be loaded is not a journal a user
  should be unable to write a commitment down in.
- **"No contacts" is the absence of the field, not an empty list.** The create
  attributes forbid extras, so `contact_ids: []` would be a second way of saying
  the same thing. The dialog omits the key and `createTask` drops an empty list
  again on its way to the wire — the rule is guarded twice, which is worth
  knowing before trusting either layer's tests alone.
- **A refusal lands on the field that caused it, and the toast stays.**
  `TASK_DUE_JOURNAL_NOT_FUTURE` has a code of its own and goes to the
  due-journal field with focus; everything else the domain refuses arrives as
  one `TASK_VALIDATION_ERROR` naming its field in `meta.field`, read by
  `taskValidationField` in `lib/api/tasks.ts`. **A refusal naming a field this
  form has no input for is left to the toast** rather than pinned somewhere at
  random, which is the difference between reporting a failure and mislabelling
  one.
- **The text is refused by the schema; the journal gates the button.** Two ways
  of saying "not ready" in one form, deliberately: an empty text has something
  to *say* — a `FormMessage` naming the field — while a missing due journal has
  the picker under it saying so already, and a submit button that stayed enabled
  would offer a request that was never going to be sent.
- **Neither the picker nor the contact combobox is wrapped in `FormControl`.**
  It clones `id`, `aria-describedby` and `aria-invalid` onto the child's *root*,
  which for both is a container rather than an input. Each takes the three as
  explicit props instead — the picker through the shared `DueJournalFormField`,
  and the contacts field assembling description **and** message ids itself,
  because `FormControl` is what would otherwise have paired them.
  `ContactSearchCombobox` grew `describedById`, `invalid` and an `aria-label` on
  its results listbox for this — the last because this dialog is the first place
  it is mounted beside a second listbox.
- **Every field refusal moves focus, and that is accessibility rather than
  polish.** `FormMessage` is a plain paragraph, not a live region, so a message
  nobody is moved to is one a screen-reader user never hears. All three branches
  go through one `reject` helper that sets the error and moves focus together,
  so the next branch cannot be written without it.
- **The field lookup is a `Map`.** `meta.field` is a string the *server* chose,
  and an object literal answers `['constructor']` through its prototype with
  something truthy — which `form.setError` would then take as a field name.
- **Every close resets, and nothing closes over the write.** Both are the
  retarget dialog's rules, adopted deliberately rather than rediscovered: Radix
  fires `onOpenChange` for Escape, the overlay and the close button but not for
  a controlled `open` set false from inside, which is how Cancel and a
  successful create both work.

#### Attaching a mention

`AttachTaskDialog` (`components/journals/AttachTaskDialog.tsx`) is one of the
two deliberate acts the specification names — "a link is created when the user
deliberately attaches an existing task to the journal they are viewing, or links
a journal to a task from the task itself". Only the first has a surface, because
tasks have no route of their own. It is triggered from the `Tasks` card header,
so it is reachable on a journal holding no tasks at all.

- **The picker names a journal before it names a task, and the scoping is
  structural rather than a policy.** The criterion is that it be "scoped and
  searchable rather than listing every task ... this affordance must not become
  one", and there is no endpoint that lists or searches tasks across journals —
  `GET /api/journals/{id}/tasks` and `GET /api/tasks/upcoming` are the whole
  surface. So the user finds the journal the task is on with the existing
  `JournalSearchCombobox`, and picks out of that journal's own listing. The
  reverse shape — a task search narrowed by journal — would be the global task
  list the specification refuses, wearing a filter, and it would need an
  endpoint built to be one.
- **Two exclusions keep the server's refusals off the screen.** The journal
  being viewed cannot be its own source (`excludeJournalId`), and a task already
  linked here in any role is not offered: one already mentioned here is a no-op,
  and one anchored here is a 409. The linked set is the listing
  `JournalTasksSection` is already rendering, passed down rather than fetched
  again.
- **Typing over the chosen journal puts it down**, along with the task picked
  out of it. `JournalSearchCombobox` reports `onClear` only when its input goes
  fully *empty*, so editing "Trip planning" into another query would leave the
  field showing one journal while the list underneath still held the other
  one's tasks. `onSearchChange` fires on user input alone and never on a
  selection, which is what makes comparing against the chosen title safe.
- **The search box's contents are the dialog's own state, not derived from the
  chosen journal.** The combobox re-syncs its input whenever its `value` prop
  changes, so a `value` of `source?.title ?? ''` throws away the very keystroke
  that puts the journal down — typing `Beach` over a chosen journal searches for
  `each`, and a whole-value replacement comes back empty. Tracking what was
  actually typed keeps the prop and the input in agreement, so the sync is a
  no-op rather than a rewind. **A caution worth carrying past this component:
  deriving a controlled child's value from state that the child's own callback
  clears makes the callback eat its own input.**
- **The 409 is still rendered against the field**, because that exclusion is
  computed from a cache and a cache can be stale — a task retargeted onto this
  journal from somewhere else is an anchor here by the time the request lands.
  `TASK_JOURNAL_IS_ANCHOR` is mapped through `form.setError` onto the task
  field, and the hook's toast is left in place: the same rule, and the same
  reason, as `TASK_DUE_JOURNAL_NOT_FUTURE` on the retarget dialog.
- **The filter is client-side, over one journal's tasks.** The set is bounded by
  the journal, so narrowing it is not a second request; and narrowing past the
  chosen task *clears the choice*, since leaving it selected would arm the
  submit button over a task no longer on screen.
- **No attach affordance on a failed listing.** The dialog cannot compute its
  exclusions without the set of tasks already linked here, so a failed listing
  would mean offering a picker that could not keep either refusal off the
  screen. The failure line stays exactly as it was.
- **Nothing closes over the write**, as on the retarget dialog and for the same
  reason: Cancel is disabled and Escape refused until the request settles,
  because a `POST` that has reached the server may already have committed and a
  dialog that vanished on Cancel and then toasted "Journal linked" would report
  the opposite of what the user had just asked for. **The parent counts as a way
  of closing it**, which is why `JournalTasksSection` renders its failure line
  only when it has no data: React Query keeps the previous `data` on a refetch
  error and sets the status alone, so a refresh that failed under an open dialog
  would otherwise replace the card and take the dialog with it — a close the
  guard cannot refuse because it never sees it.
- **Escape belongs to whichever thing is open.** `JournalSearchCombobox` closes
  its own dropdown on Escape and lets the key carry on, and Radix's dismissable
  layer listens on `document` in the *capture* phase — so one press would dismiss
  a dropdown and throw the dialog away with it, losing the journal, the filter
  and the chosen task. A React handler cannot get in front of a capture listener
  on `document`, so the interception is Radix's own `onEscapeKeyDown`, gated on
  the `aria-expanded` the combobox already publishes. A second press, with no
  dropdown open, still closes the dialog.
- Accessibility: the options are a real `RadioGroup`, so arrow-key navigation
  and a roving tabindex come from Radix rather than from a hand-rolled listbox —
  which is why this surface needs no `jsx-a11y` suppression. The group is named
  through `aria-labelledby` pointing at a `<span>`, because a `<label>` cannot
  name a `radiogroup` and a `<fieldset>`/`<legend>` would wrap it in a *second*
  group carrying the same name, which a screen reader reads out twice. Focus on
  open is set explicitly with `onOpenAutoFocus` rather than left to Radix's
  first-tabbable default; and one `role="status"` line states what the picker
  currently holds in *every* state — including the ordinary one, so a list that
  changes under a filter does not change silently.
- **The field stays mounted while a journal is named**, not only while there are
  options, because the server's refusal is written onto it: if the list emptied
  between the submit and the 409 arriving, `FormMessage` would not be in the
  document to receive it and only the toast would survive.

#### Removing a mention

`DetachMentionButton` (`components/journals/DetachMentionButton.tsx`) is the
other half: "intermediate links can be removed. The creating and due links
cannot be removed, only replaced in the case of the due journal."

- **The affordance belongs to the row's *group*, not to the task.** A task can
  be due in this journal *and* mentioned in it — a retarget onto a journal it
  already mentioned produces exactly that — and the listing renders it once per
  group. So the section passes each group's role down through `JournalTaskRow`
  to `JournalTaskActions`, and one commitment shows a remove under *Mentioned*
  and none under *Due*. Reading `link_roles` instead could not tell the two rows
  apart, because it says the task is both.
- **The rule is a table, `linkRemovable(role)` in `lib/task-display.ts`**, not
  an inline comparison — the idiom the status offer table and the lapse wording
  already follow, and what lets one test assert it exhaustively over the role
  enum without rendering anything.
- **Mounted inside the actions group**, so it shares the group's `aria-busy` and
  the per-task in-flight lock — a detach is a write against the same task as
  everything else there. It does **not** inherit the group's
  `aria-describedby`: that names the commitment when the group is *entered*, so
  a user tabbing straight to one button hears its name without the task. True of
  every button in that group since Phase 17, and not this phase's to change for
  one control.
- **No confirmation.** Deletion is gated because it is permanent and takes the
  task off every journal it is linked to; a mention is one link, and the way
  back is the attach affordance in the same card. What it borrows from delete is
  the presentation — icon-only, `ghost`, muted, never the destructive variant —
  because it is still not one of the ordinary status moves. It is placed before
  delete, which stays last.
- **It stays locked once the write has *succeeded*, not only while it is in
  flight.** The row leaves the listing when the invalidated refetch returns,
  which is a round trip after the `DELETE` resolves, and the shared in-flight
  guard goes false the moment it does. A second press in that window is refused
  — a journal holding an anchor role keeps its intermediate link removable, and
  the service raises rather than answering idempotently the second time — so the
  user would see "Journal unlinked successfully" followed by an error naming the
  anchor, reading as though the removal had failed. A *failed* detach unlocks:
  the link is still there, so the way to try again must not be locked away with
  it.

#### Journal and contact writes invalidate `taskKeys.all`

A task's read shapes **embed** the entities they reference rather than pointing
at them: `due_journal.title`, `due_journal.date`, `due_journal.cancelled`, the
derived `lapsed` / `lapse_reason`, and each contact's `display_name` and
`photo_url` all arrive inside the task payload. So `useUpdateJournal`,
`useUpdateJournalField`, `useDeleteJournal`, `useMergeJournal`,
`useUpdateContact`, `useUpdateContactField`, `useDeleteContact` and
`useMergeContact` name `taskKeys.all` alongside their own key sets.

The **lifecycle** hooks are in that list for a reason of their own, not merely by
symmetry: a merge re-points the absorbed journal's task links at the survivor
and deletes the source contact outright, and deleting a journal that is only an
*intermediate* link is permitted and removes that link. Each changes the
membership of a task listing rather than just the values inside it. The `create`
hooks are deliberately absent — a new journal or contact cannot be attached to an
existing task yet — as is `useToggleContactFavourite`, since a task's contact ref
carries only id, display name and photo.

- **This is the "names only the namespaces its change can reach" rule pointing
  the other way.** The rule constrains a *task* mutation from over-invalidating;
  it equally obliges a journal or contact mutation to name the task namespace,
  because that is a namespace its change genuinely reaches.
- **`all` rather than `journalLists()`**, because all three sibling namespaces —
  `detail`, `journalList` and `upcoming` — carry the same embedded refs. That is
  the reachable set exactly, not an over-broad sweep.
- **The lapse marker is why this is not cosmetic.** Moving a journal's date into
  the past, or cancelling it, is what *lapses* the tasks due in it — and the
  journal's own detail view is displaying those tasks. Without the refresh the
  user edits the date and the task section below goes on claiming the task is
  fine for the whole five-minute `staleTime`.

#### Task writes invalidate `journalKeys.lists()`

The mirror of the rule above, and it arrived with the journal list's tasks-due
badge: the list row now embeds a fact derived from tasks, so a task write
reaches a journal namespace and has to name it. `useCreateTask`,
`useUpdateTask`, `useRetargetTask` and `useDeleteTask` name
`journalKeys.lists()`; without it a user who ticks a task done on a journal and
returns to the list is told it is still waiting on one, for the whole
five-minute `staleTime`.

- **`lists()` is the reachable set exactly**, not `journalKeys.all`. Only the
  list endpoint computes the count — search and a contact's journals leave it
  null and render no badge — so invalidating those would refetch pages whose
  answer cannot have changed. `lists()` covers the infinite lists too, since
  their key is built from it.
- **Two task mutations are deliberately excluded**, and that is what makes the
  rule a rule rather than a sweep: linking a **contact** and attaching a
  **mention** both leave `journalKeys.lists()` alone, because the count reads
  the *due* anchor only. Each is asserted by name, beside the exhaustive
  key-set match that would already have caught it.
- `useUpdateTask` names it even though a **text-only** edit cannot move a count:
  the same PATCH carries the status, and the hook would have to read its
  variables back to tell the two apart. One redundant refetch is the right side
  to err on against a badge that lies for five minutes.
- **A timezone change invalidates it too.** The count's lapse verdict is
  reached in the user's *configured* zone, so `useUpdateTimezone` names
  `journalKeys.lists()` and `taskKeys.all` alongside its own namespace —
  otherwise correcting your timezone leaves you looking at badges and lapse
  markers decided in the old one for five minutes. The task half of that was a
  pre-existing gap; the journal half arrived with this badge. `journal-keys.ts`
  is what makes it expressible: `journals.ts` imports `settings.ts`, so naming
  the key from there would close the same cycle again.
- **Crossing local midnight is *not* handled, deliberately.** A journals page
  left open and focused across midnight can keep rendering a badge for a task
  that has just lapsed, until the next refetch. Nothing fires at midnight, so
  there is no mutation to hang an invalidation off, and the alternative — a
  `today` term in `journalKeys.list()` — would rewrite the key every journal
  list query is built on to fix a staleness the whole app shares: the lapse
  marker on task rows and the dashboard's upcoming window have the same
  property, for the same reason. The server stays the authority and the view
  self-corrects on the next refetch. **Recorded as a follow-up**, to be solved
  once for every date-derived read rather than piecemeal for this badge.
- **`journalKeys` moved to `lib/api/journal-keys.ts`**, re-exported from
  `journals.ts` so no call site changed. The obvious version of this — having
  `tasks.ts` import `journalKeys` straight from `journals.ts`, which already
  imports `taskKeys` back — closes a **runtime import cycle**, and it does not
  survive contact with the suite: a test that partially mocks the journal client
  through `jest.requireActual` re-enters `journals.ts` while its own top-level
  `const`s are in the temporal dead zone, and the whole file fails to run with
  `Cannot access 'calendarKeys' before initialization`. The reasoning that the
  cycle was safe "because both directions are only used inside functions" was
  wrong: what matters is when the *modules* are evaluated, not when the
  functions are called. Keys have no dependencies of their own, so lifting them
  out removes the cycle instead of arguing about it.

#### The journal list's tasks-due indicator

`JournalListItem` renders a `tasks-due-badge` beside the row's existing
list-level indicators, from the `tasks_due_count` the list endpoint carries. It
is the specification's "lightweight indicator that a journal has tasks due in
it, consistent with the other list-level indicators".

- **Consistent means the same vocabulary, not a new one.** Same `Badge`, same
  `ml-2 px-1 py-0 text-[10px] leading-none font-bold uppercase` as the cancelled
  and needs-review markers beside it, and the same slot in the `CardTitle`.
  `variant='secondary'` rather than `destructive`: a journal with commitments in
  it is information, not a problem — `destructive` is what *needs review* means,
  and a row wearing both should not say the same thing twice.
- **Not computed is not zero, and the schema has to say so.** `tasks_due_count`
  is **nullable** on the wire and the transform passes `null` and `undefined`
  through rather than defaulting them. This is load-bearing rather than
  fastidious: only `list_journals` runs the count, so a non-nullable field
  defaulting to `0` would have the *search* payload state that a journal with
  two tasks genuinely due in it has none — an affirmative false claim, not a
  missing one, on the very surface the `/journals` page switches to when the
  user types. Both `null` and `0` render nothing, so the distinction costs the
  viewer nothing; it exists so the payload never asserts something no query
  checked. An integration test reads a journal with two tasks due back through
  the detail endpoint and requires `null`.
- **The short form is for the eye and the long one for the ear.** The badge
  reads `2 due`, which is unambiguous *because the journal it sits on is visible
  beside it* — exactly what a screen reader meeting the badge on its own does
  not have. So the visible span is `aria-hidden` and an `sr-only` sibling
  carries `tasksDueWording(count)`: `2 tasks due in this journal`. A shadcn
  `Badge` is a plain `div` with no role, so what this changes is its announced
  **text content**, not an accessible *name* — and it is why an `aria-label` on
  the span was rejected rather than used: `aria-label` needs a role to attach
  to. A test asserts the `aria-hidden` itself, because without it the badge
  announces "2 due 2 tasks due in this journal" and every other assertion here
  goes on passing. **Recorded as a follow-up:** this row's hierarchy and sync
  indicators put `aria-label` on the lucide `<svg>` itself and have the same
  weakness.
- **The wording lives in `lib/task-display.ts`**, beside `lapseWording` and
  `statusWording`, so the singular and the plural are asserted without rendering
  a row — and so the one module that decides how a task is worded goes on being
  the only one.
- **Four surfaces show a journal row and only one carries a computed count.**
  Only `list_journals` *passes* the counts, so a row from
  `GET /api/journals/search` (the `/journals` page in search mode) or from a
  contact's journals shows **no** indicator — and neither does a journal nested
  under its parent, which `JournalChildrenList` renders from
  `attributes.children`, a `ChildJournalSummary` that carries no count at all.
  The contact endpoint is worth naming because it is **the same helper**:
  `_build_journal_list_resources` is imported by
  `app/api/contacts/controllers.py` and called without the mapping, so it is a
  live caller relying on the nullable guard to leave its rows uncomputed rather
  than stamp a zero on each. Without that guard the contact view would be a
  second surface making the false claim.
  So one journal can show the badge as a top-level row and not as a child. That
  is not an oversight: *Needs Review* is missing from those same rows for the
  same reason, so the **rows** are consistent with the sibling indicator. The
  **payloads** deliberately are not — `has_pending_reviews` is a non-nullable
  `bool` defaulting to `false`, so it tells those same clients that a journal
  has no pending review when nothing ever checked, which is precisely what the
  nullable rule above stops `tasks_due_count` doing. **Two follow-ups
  recorded:** widening the count to those endpoints needs the same batched read
  there, and `has_pending_reviews` wants the same nullable treatment; neither
  is done here, where it would double the surface under test.
- **Lapsed tasks are excluded server-side, and must be.** The specification is
  explicit that a lapsed task produces "no overdue section, no counter, no badge
  and no notification": the user is meant to meet it on the journal, not be
  chased by the listing. The row therefore renders whatever count it is given
  and makes no lapse judgement of its own — the browser's clock is not the zone
  the verdict was reached in, and a second opinion here could only disagree.

### TypeScript Integration

- Define interfaces for all component props
- Use generic types for reusable components
- Implement proper type guards for data validation
- Use discriminated unions for variant props
- Ensure type safety across component boundaries

## Design System

### Color Palette

- Use semantic color tokens from shadcn/ui
- Implement proper dark mode support
- Use CSS custom properties for theming
- Maintain consistent color usage across components
- Test color contrast for accessibility compliance

### Typography

- Use consistent font scales and weights
- Implement proper heading hierarchy
- Use semantic text classes for different contexts
- Ensure readable line heights and spacing
- Support responsive typography scaling

### Spacing and Layout

- Use consistent spacing scale (4px, 8px, 16px, etc.)
- Implement proper component spacing
- Use flexbox and grid for layout patterns
- Maintain consistent component proportions
- Support responsive layout adjustments

## Performance Optimization

### Code Splitting

- Implement route-based code splitting
- Use dynamic imports for heavy components
- Lazy load non-critical components
- Optimize bundle sizes with tree shaking
- Monitor bundle analysis regularly

### Image Optimization

- Use Next.js Image component for optimization
- Implement proper image lazy loading
- Use appropriate image formats (WebP, AVIF)
- Provide responsive image sizes
- Optimize images for different screen densities

### Rendering Optimization

- Use React.memo for expensive components
- Implement proper key props for lists
- Avoid unnecessary re-renders
- Use useMemo and useCallback appropriately
- Profile component performance regularly

## Testing Patterns

### Component Testing

- Test component rendering with various props
- Verify user interactions and event handling
- Test accessibility features and keyboard navigation
- Mock external dependencies and API calls
- Use realistic test data and scenarios

### Integration Testing

- Test component integration with forms
- Verify data flow between components
- Test error handling and edge cases
- Ensure proper loading and error states
- Test responsive behavior across breakpoints

## Australian Localization

### Date and Time Formatting

- Use DD/MM/YYYY date format
- Implement proper timezone handling (AEST/AEDT)
- Use Australian English date terminology

### Language and Terminology

- Use Australian English spelling and terminology
- Implement proper currency formatting (AUD)
- Use Australian business terminology
- Support metric units and measurements
- Provide Australian-specific help text and examples

## Home Dashboard Page

The home page (`src/app/page.tsx`) is the user's daily briefing, replacing the
placeholder card grid it used to render. Its layout contract is the
[Home Dashboard Wireframe](../design/home-dashboard-wireframe.md), whose
elements are numbered **W1**–**W33**.

- **API adapter**: `src/lib/api/home-dashboard.ts` — a single TanStack Query
  hook (`useHomeDashboard`) over the singleton `GET /api/home-dashboard`
  resource, typing the whole payload: the four sections in their
  `{status, data}` envelopes, and `meta.anchor`. The specification requires the
  four sections to be retrievable together, one round trip rather than four.
  Everything the hook returns comes from **one** query key, so any number of
  concurrent callers dedupe into a single fetch — asserted directly, with four
  simultaneous mounts issuing one request.

  `page.tsx` calls it for the header's day — the header takes that day as a
  prop, which keeps it a pure function of the anchor and testable without a
  query — and **the summary card calls it itself**. The three section cards
  will as their phases land, rather than being handed props from the page,
  because a card that owns its own read owns its own loading and unavailable
  states: the per-section resilience the specification asks for. The dedupe
  guarantee is what makes that free, and it is asserted with the card mounted.
- **Section availability**: a section reports `ready` (an empty payload is a
  real answer — nothing scheduled, nothing due) or `unavailable`, where `data`
  is `null`. *Unavailable* covers both "could not be read" and "there is none",
  a distinction deliberately absent from the wire, so surfaces render it as
  "nothing to show here" rather than as an error. One section failing never
  fails the request or the others.
- **The date comes from the server, never the browser.** Every window is
  anchored on today in the user's *configured* timezone, server-side, and
  `meta.anchor.date` is what the header labels the page with
  (`DashboardPageHeader`, **W2**). The browser's today can differ from it, and
  labelling server-gathered evidence with a client-derived day would put the
  wrong date on the whole page. Until the anchor arrives the header shows no
  date at all — a wrong date is worse than none. `formatIsoDateLong` in
  `src/lib/date-utils.ts` writes it (`EEEE, d MMMM yyyy`, en-AU), parsing the
  anchor as a *local calendar date* so an already-resolved day is never shifted
  again.
- **Page frame**: the page adds no chrome and no container of its own (**W1**).
  The root layout already supplies `main.md:pl-64 > .container.mx-auto.px-4.py-6`,
  and a container nested inside that one is the likeliest source of horizontal
  overflow at mobile widths.
- **Section grid**: `grid-cols-1 lg:grid-cols-3 items-start gap-4` beneath the
  summary (**W3**). `items-start` lets the columns size independently, so a
  short Upcoming-dates card does not stretch to match a tall Agenda; below `lg`
  the three stack in DOM order — Agenda → Tasks → Upcoming dates.
- **Summary card**: `DashboardSummaryCard` is the page's headline (**W5**–**W10**),
  full width between the header and the grid, drawn apart from the evidence
  cards with `bg-primary/5 border-primary/20` and a primary accent bar down its
  left edge. It is a `<section aria-labelledby>` named by a **visible** `h2`
  ("AI Daily Summary"), so the outline runs `h1` → the card's `h2` → the
  sections' `sr-only` `h2`s → the card headings.
  - It reads the summary from the **dashboard payload**, not from
    `useDailySummary`. The journals view's hook goes through
    `DailySummaryService.get_or_generate`, which writes and can hold an AI call
    open for seconds; the dashboard is a read-only projection, so it takes the
    same row through the section envelope instead. "The same entity the
    journals view shows" is satisfied by the entity, not by the code path.
  - **Three declared states**: generated (**W7**), generating (a `secondary`
    "Generating..." badge beside the label and one muted line — **W8**), and
    unavailable (one quiet line — **W9**), which a failed dashboard request
    degrades to as well. A fourth *rendering* — a quiet line while the page's
    query is in flight — is not a state the wire produces; it is the
    placeholder wireframe gap 9 anticipates until Phase 16 builds the
    skeletons.
  - The generated body splits the summary on blank lines into real `<p>`
    elements (**W7**'s "one or more prose paragraphs"), with
    `whitespace-pre-line` for the single newlines inside one. Never clamped,
    never truncated.
  - The key-stats footer (`SummaryKeyStats`, a `dl` of four `dt`/`dd` pairs)
    renders in the generated state only (**W10**), showing a count of zero
    rather than dropping a column and an em dash for an unrated day. It is
    `grid-cols-2 sm:grid-cols-4` — the wireframe's single row from `sm` up, a
    2×2 block below it, because four columns in a card at 375 px is what
    **W3**'s overflow rule exists to prevent (wireframe gap 14).
  - **W9's wording drops its cause clause.** The wireframe reads "No summary
    today — AI summaries are not configured", but *unavailable* also covers a
    day that simply has no summary yet, which is the ordinary case; the card
    names no cause it cannot know and keeps the reassurance verbatim
    (wireframe gap 13).
  - **Regenerate (W6) sits outside all three state branches** and stays enabled
    in every one of them, including *generating* — nothing currently moves a
    journal daily summary out of `pending`, so that control is the only way out
    of the state. The card never fires it automatically: the page every sign-in
    lands on must not start a multi-second AI write on load, and the
    specification allows exactly two mutations here, the inline task action and
    a user-requested regeneration. It is disabled only while the mutation is in
    flight — where it carries `aria-busy` — and while there is no anchor day to
    post to. That second case is the page's first load **and** a dashboard
    request that failed, where **W9** is drawn beside a control that cannot be
    used: the day to regenerate is the server's today in the user's configured
    zone, and posting the browser's would regenerate the wrong day for anyone
    whose zone differs. Recovering a failed request is a *retry*, not a
    regeneration, and belongs to Phase 16.
  - **It also refuses a day the anchor has outlived.** The query has one fixed
    key, the app-wide five-minute `staleTime`, and no refetch scheduled at the
    day boundary, so a dashboard left open and focused across local midnight
    keeps yesterday's anchor. A stale *label* is Phase 16's to fix; a **write**
    keyed on a stale anchor is not something to leave until then, because it
    would rewrite yesterday's summary under a page headed "Today". The card
    compares the anchor against the wall clock in the zone the payload itself
    names and declines rather than guessing — leaving the control disabled
    until the query refetches, exactly as before the first load arrives. An
    unparseable zone trusts the anchor: the server resolved that day and the
    browser cannot second-guess it.

    Two details of that check are worth knowing, because both are easy to get
    subtly wrong. `localDateIn` builds `YYYY-MM-DD` from
    `Intl.DateTimeFormat().formatToParts`, **not** from `format`: which
    separator a locale renders is CLDR data rather than a guarantee, so relying
    on `en-CA` to yield dashes would disable the control on a current anchor
    wherever it does not. And the check runs **inside the click handler** as
    well as during render — the disabled state is computed while React renders,
    and a dashboard left mounted across midnight need never render again, so
    the render-time check alone would leave an enabled button closing over
    yesterday's date.
  - **The body is deliberately not an `aria-live` region.** Its first content
    change is "loading" giving way to prose, so marking it live would read the
    whole AI summary aloud unbidden on the post-sign-in default page. The
    change worth announcing — the regeneration the reader asked for — already
    announces itself through the toast, which is a live region.
  - **Writes that change the summary invalidate `homeDashboardKeys.all`.** The
    invalidation belongs to the mutation, not to the card: regenerating from the
    journals view leaves the dashboard just as stale as regenerating from the
    dashboard does. `useRegenerateDailySummary` does it, and so does **every**
    journal writer through the shared `REFRESH_HOME_DASHBOARD` filter — the
    summary's counters are counts of the day's journals and events, and the
    agenda reads the same day's event journals with their tags and
    participants. It is every writer rather than a chosen few because deciding
    per mutation which payload fields it touches would need redoing each time a
    section lands, and the list is enumerated by a table-driven test so the
    contract cannot quietly lose one. Task and contact writes do not yet, and
    are owned by the phases whose sections read them.
  - **What that invalidation does not fix.** The backend marks a summary stale
    *asynchronously*, through the outbox and `SearchIndexerConsumer`. The
    dashboard is not mounted while a journal is edited, so its query is
    inactive: it is marked stale and re-read on the next mount, by which time
    the consumer has normally run. Underneath that sit two backend defects no
    client invalidation can close — moving a journal off a day never marks that
    day's summary stale (the consumer reloads the journal after the write and
    sees only its new date), and deleting a journal marks nothing stale at all
    (the `JournalDeleted` payload carries no date). Both are recorded as
    follow-ups in the iteration document.
- **Section semantics**: `DashboardSection` wraps each card in a
  `<section aria-labelledby>` whose `h2` is `sr-only`, with the visible title
  supplied by the card header (**W4**). Hiding the heading rather than dropping
  it gives the page real landmarks to jump between without drawing the title
  twice.
- **Section cards**: `AgendaCard`, `TasksCard` and `UpcomingDatesCard`
  (**W11**, **W21**, **W30**) each supply their wireframe copy to the shared
  `DashboardSectionCard` shell, which draws the icon chip, title, description,
  a labelled `<ul>` for the entries and the empty state. The list is rendered
  whether or not it has entries, and deliberately **not** `empty:hidden`: a
  `display:none` list is out of the accessibility tree, and **W4** asks for a
  labelled list per section regardless. Empty states reuse `WidgetEmptyState`,
  which is already **W29**'s idiom — a centred muted icon over one line that
  reads as a good outcome rather than an error. The shell also takes an
  optional `placeholder`, drawn *instead of* the empty line while a section
  holds no entries for some reason other than there being none — the query is
  still in flight, or the section is `unavailable` — so "nothing scheduled" is
  never a false claim. It is ignored once there are entries.
- **Agenda card**: `AgendaCard` (**W11**–**W18**) reads `useHomeDashboard()`
  itself and maps `agenda.data.entries` to one `AgendaEntryRow` each, **in the
  server's order** — all-day first, then timed ascending by start instant is
  the backend's rule (`order_agenda_entries`) and is pinned there, so the card
  does not re-sort. Ready-and-empty draws the **W29** line (wireframe gap 1);
  pending and unavailable each draw a quiet line of their own in **W9**'s
  idiom (`agenda-loading`, `agenda-unavailable`) as placeholders until Phase
  16's skeletons, so the three cannot be confused. A dashboard request that
  fails outright has no envelope at all and reads as unavailable.
  - **`AgendaEntryRow`** is a pure function of one payload entry, the same row
    the tomorrow disclosure reuses: a bordered row with a left accent bar keyed
    to `calendar_color` by inline style (a runtime hex value Tailwind cannot
    class), `bg-chart-1` when the calendar has none (**W17**); the title as a
    `Link` to `/journals/{id}` behind a calendar glyph (**W14** — the second,
    type glyph is not drawn: the payload carries no journal types, wireframe
    gap 16); `formatClockRange` in `src/lib/agenda-display.ts` writes the
    clock values as `HH:MM – HH:MM` in `tabular-nums`, the event's own wall
    time as the calendar views render it, with `· location` beside it
    (**W13**), or an uppercase **ALL DAY** marker in its place (**W12**); tags
    as `outline` badges with the tag's colour on border and text (**W15**);
    and `AgendaParticipantStack` — up to three `ContactAvatar`s ringed in the
    background colour, then a `+N` whose accessible label names the hidden
    participants (**W16**, gap 18). A cancelled entry is dimmed, its accent
    muted, its title struck through and badged **CANCELLED** in visible text
    (**W18**), so it never reads as still happening and assistive technology
    gets the same signal without extra ARIA. `nameParts` in
    `src/lib/contact-names.ts` splits a display name for the avatar's initials
    and is shared with `JournalTaskRow`.
- **Navigation**: the sidebar carries a top-level **Home** link to `/`
  (`nav-link-home`), a deliberate addition to the wireframe, which shows only
  the header logo link (wireframe gap 4). It is a plain link rather than a
  collapsible section because the specification makes the dashboard the
  post-sign-in default, and a section that folded away its only item would be a
  worse affordance. `isActiveLink` matches `/` **exactly**: every path starts
  with `/`, so the shared prefix rule would otherwise mark Home current on
  every page in the app.

## Outdoor Logbook Overview Page

The Outdoor Logbook overview page (`src/app/journals/outdoor-logbook/page.tsx`)
is a dedicated route under the journals experience with its own sidebar entry
under Journals (not a calendar/list view-mode toggle). It is the shared shell
for outdoor logbook review and reporting: it hosts the incomplete outdoor
activities review, and the dashboard widgets (upcoming activities, checked-out
gear, recent totals, templates done) slot in alongside it (ITER16-003).

### Incomplete Outdoor Activities Review

- **Component**: `src/components/journals/IncompleteOutdoorActivitiesList.tsx`
  — a card listing each flagged journal with its title (linking to the journal
  detail), date range, type icon badges (reusing `JournalTypeBadges`), one
  reason badge per matched rule, and a dismiss/un-dismiss control.
- **API adapter**: `src/lib/api/incomplete-outdoor-activities.ts` — TanStack
  Query hooks over `GET /api/journals/incomplete-outdoor-activities` and the
  dismiss/undismiss action POSTs. Dismissing optimistically removes the entry
  from the default list and offers an Undo toast action.
- **Show dismissed**: a labelled switch refetches with
  `include_dismissed=true`; dismissed rows render muted with an Un-dismiss
  button, giving a durable un-dismiss affordance (dismissed entries are
  otherwise excluded from the review).
- **Accessibility**: semantic `ul`/`li` list, per-row `aria-label`s on the
  dismiss/un-dismiss buttons (including the journal title), a `Label`-linked
  switch, and semantic colour tokens throughout.

### Dashboard Widgets

- **API adapter**: `src/lib/api/outdoor-dashboard.ts` — a single TanStack
  Query hook (`useOutdoorDashboard`) over the singleton
  `GET /api/journals/outdoor-dashboard` resource. All dashboard widgets call
  the same hook and share one query key, so concurrent mounts dedupe into one
  fetch; the adapter types all four dashboard sections (upcoming activities,
  checked-out gear, activity totals, templates done).
- **Upcoming activities**: `src/components/journals/UpcomingActivitiesList.tsx`
  — a card listing the next 30 days of outdoor activities and planning events
  (soonest first, capped at 10 server-side), each with its title (linking to
  the journal), date range, and type icon badges. Planning entries show the
  Outdoor Planning badge; activity entries show their raw subtype badges
  (dependency-added rows included, matching the incomplete review), falling
  back to the generic Outdoor Activity badge for subtype-less journals.
- **Recent activity totals**: `src/components/journals/ActivityTotalsTable.tsx`
  — a card with an accessible table of outdoor activity counts by effective
  journal type over the rolling last-30-day and last-365-day windows shown
  together (sr-only caption, `scope='col'`/`scope='row'` headers, missing
  window counts rendered as an explicit `0`).
- **Checked-out gear**: `src/components/journals/CheckedOutGearList.tsx` — a
  card listing the gear the user has out right now (longest out first, the
  backend's ordering), each with its name and a "Checked out since {date}"
  line. Rows are **informational text with no link**: there is no per-gear-item
  page, and the spec only requires the item and its checkout date. See
  [Database Design](./database-design.md) for the "checked out" definition.
- **Templates done**: `src/components/journals/TemplatesDoneList.tsx` — a card
  grouping the templates referenced by the user's abseiling activities by
  template type (type-sorted `h4` headings, each labelling its own list), with
  a per-template done-count rendered as readable text ("Done 2 times"). Each
  template links to `/settings#templates`, matching the durable template
  reference on journal detail (`TemplateReference.tsx`) — there is no
  per-template route. Template types reuse `TYPE_LABELS` where they overlap the
  journal type enum, falling back to a capitalised raw value for `abseiling`.
- **States**: every widget owns its loading skeletons, destructive error
  alerts, and empty states, mirroring the incomplete review.

## Related Documents

- [Architecture Overview](../architecture.md) - High-level system architecture and frontend principles
- [AI Guidelines](../ai-guidelines.md) - Frontend development standards and guidelines
- [Technology Stack](./technology-stack.md) - Frontend technology choices and frameworks
- [Domain Architecture](./domain-architecture.md) - Domain patterns for frontend integration
- [API Design](./api-design.md) - API integration patterns for frontend
- [Testing Strategy](./testing-strategy.md) - Component testing patterns and accessibility testing
- [Deployment Guide](./deployment-guide.md) - Frontend deployment configuration and Docker setup
