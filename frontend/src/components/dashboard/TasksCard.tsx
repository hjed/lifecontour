/**
 * TasksCard — what is due in the coming week (**W21**–**W27**).
 *
 * Read from the dashboard payload the page already fetched: the card calls
 * `useHomeDashboard()` itself, the arrangement the summary, agenda and
 * upcoming-dates cards established, so it owns its own loading and unavailable
 * renderings and still costs the page nothing — every caller shares one query
 * key and dedupes into a single request.
 *
 * **The card draws the list it is given and does not re-sort it.** Due-journal
 * date ascending, ties broken by task id, is the server's rule (ITER18-001
 * Phase 14's listing, reused whole by Phase 13) and is pinned there.
 *
 * **The cap lives here, and only here** (**W22**): the server sends the *whole*
 * seven-day window with its `total` — it caps nothing — so five rows are drawn
 * and the show-more (**W28**) reveals the remainder **in place** from data
 * already held, without a second request. That is what makes the reveal free,
 * and it is asserted against the request count rather than only the DOM,
 * because a card that refetched would still look right on screen.
 *
 * **Expansion is component state, and there is deliberately no way back.** It
 * is neither persisted nor put in the URL, which is what makes the next load
 * five rows again rather than something to be cleaned up; and the button
 * withdraws once everything is shown rather than becoming a *Show less*, as
 * **W28** describes one control and the upcoming-dates show-more settled the
 * same way.
 *
 * Three things the list can hold nothing for, kept apart on purpose: **nothing
 * due this week** is a real answer and gets the single **W29** line the
 * wireframe does draw for this section; the query still being **in flight**
 * gets the pulsing row skeleton and the section coming back **unavailable**
 * its own centred line, because "nothing due in the next seven days" would be
 * a false claim about either. Both are `DashboardSectionPlaceholder`'s; this
 * card supplies only their wording.
 *
 * **The card mounts each row's inline done action** (**W24**) rather than the
 * row doing it: the action is the one thing here that writes, and keeping it
 * out of the row is what lets the row be a pure function of the payload with
 * no query behind it.
 */

'use client';

import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, ClipboardList } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DashboardSectionBoundary } from './DashboardSectionBoundary';
import { DashboardSectionCard } from './DashboardSectionCard';
import {
  DashboardSectionPlaceholder,
  DashboardUnavailableSection,
} from './DashboardSectionPlaceholder';
import { DashboardTaskActions } from './DashboardTaskActions';
import { DashboardTaskRow } from './DashboardTaskRow';
import {
  DashboardSectionStatus,
  useHomeDashboard,
} from '@/lib/api/home-dashboard';
import type { HomeDashboardTask } from '@/lib/api/home-dashboard';
import { focusRevealedRow } from '@/lib/dashboard-focus';
import { showAllDueLabel, taskTextId } from '@/lib/dashboard-tasks-display';

/** The section's wireframe copy, in one place so the page and its tests agree. */
export const TASKS_SECTION = {
  icon: ClipboardList,
  iconChipClassName: 'bg-chart-2 text-white',
  title: 'Tasks',
  description: 'Due in the next seven days, soonest first. Tick them off here.',
  listLabel: 'Tasks due in the next seven days',
  emptyIcon: CheckCircle2,
  emptyMessage: 'Nothing due in the next seven days.',
} as const;

/** What the card says while it has no list to draw. Not shell props. */
const TASKS_PLACEHOLDER_COPY = {
  loading: 'Loading tasks...',
  unavailable: 'Tasks are unavailable.',
} as const;

/**
 * How many tasks are drawn before the show-more (**W22**).
 *
 * Five, which the specification fixes rather than leaves open: *"If the user
 * has more than five things due in the next week, the dashboard's job is to
 * show them the next five, not all of them."*
 */
export const VISIBLE_TASKS = 5;

/**
 * The section as the page mounts it: the card itself behind the boundary that
 * keeps the week's tasks from taking the rest of the page with them.
 *
 * The body's own guards stay in front of it and handle the shapes they were
 * written for; this catches what they could not foresee — a malformed entry
 * *inside* the list, which no field check at the top of the card can see — and
 * degrades this one section to unavailable while its neighbours carry on.
 */
export function TasksCard() {
  return (
    <DashboardSectionBoundary
      fallback={
        <DashboardUnavailableSection
          section={TASKS_SECTION}
          copy={TASKS_PLACEHOLDER_COPY}
          testIdPrefix='tasks'
        />
      }
    >
      <TasksCardBody />
    </DashboardSectionBoundary>
  );
}

function TasksCardBody() {
  const { data, isPending } = useHomeDashboard();
  const [expanded, setExpanded] = useState(false);
  const listRef = useRef<HTMLUListElement>(null);

  // The show-more unmounts itself when pressed (W28 describes one control), and
  // an unmounted focused element drops focus to `<body>`. See
  // `focusRevealedRow` for where it goes instead and why.
  useEffect(() => {
    if (expanded) {
      focusRevealedRow(listRef.current, VISIBLE_TASKS);
    }
  }, [expanded]);

  const section = data?.data.attributes.tasks;
  const ready =
    section?.status === DashboardSectionStatus.READY ? section.data : null;

  // Guarded rather than trusted, for the reason the agenda card guards its
  // tomorrow and the dates card its dates: the type promises an array on every
  // ready section, but a payload that broke that used to throw out of render
  // and take the *whole page* with it. "Sections render independently" has to
  // survive a section that breaks its contract, not only one that reports
  // itself unavailable. What this cannot see — a
  // malformed entry *inside* the list — is `DashboardSectionBoundary`'s,
  // which the card now sits behind.
  const tasks: HomeDashboardTask[] | null = Array.isArray(ready?.tasks)
    ? ready.tasks
    : null;

  const shown = expanded ? tasks : tasks?.slice(0, VISIBLE_TASKS);

  // Counted off the **list** rather than read from the section's `total`. The
  // wire says the two are equal — the server caps nothing, so the whole window
  // travels — and the optimistic removal in `useUpdateTask` already re-derives
  // `total` from the list's length for that same reason. The button names what
  // pressing it reveals, so it is read off the thing it acts on: were the two
  // ever to disagree, `total` is the half that is not true here.
  const total = tasks?.length ?? 0;
  const hasMore = !expanded && total > VISIBLE_TASKS;

  return (
    <DashboardSectionCard
      {...TASKS_SECTION}
      testId='tasks-card'
      listRef={listRef}
      placeholder={
        tasks ? undefined : (
          <DashboardSectionPlaceholder
            pending={isPending}
            copy={TASKS_PLACEHOLDER_COPY}
            testIdPrefix='tasks'
          />
        )
      }
      footer={
        hasMore ? (
          <div className='mt-3 flex justify-center'>
            <Button
              variant='link'
              size='sm'
              className='text-muted-foreground'
              data-testid='tasks-show-more'
              onClick={() => setExpanded(true)}
            >
              {showAllDueLabel(total)}
            </Button>
          </div>
        ) : undefined
      }
    >
      {shown?.map(task => (
        <DashboardTaskRow
          key={task.task_id}
          task={task}
          // Mounted by the card rather than by the row so the row stays a pure
          // rendering of the payload; `taskTextId` is how the two ends agree
          // on the id the action group is described by.
          actions={
            <DashboardTaskActions
              taskId={task.task_id}
              describedById={taskTextId(task.task_id)}
            />
          }
        />
      ))}
    </DashboardSectionCard>
  );
}
