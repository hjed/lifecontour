/**
 * A journal's tasks, grouped by the nature of each link.
 *
 * The specification gives a journal exactly three groups — tasks **due** in it,
 * tasks **created** in it, and tasks it merely **mentions** — and this is one of
 * only two surfaces where tasks are worked with at all. It is read-only in
 * ITER18-001 Phase 16; creating, actioning and retargeting arrive in Phases
 * 17–20.
 *
 * Every linked task appears here in every status, lapsed ones included. A
 * lapsed task leaves the dashboard silently and its journals are where the user
 * is meant to meet it again, so this listing must never filter one out.
 *
 * **A journal with no tasks still renders the card**, which narrows a decision
 * Phase 16 made. That decision's reason was a skeleton flashing on nearly every
 * journal detail view, and it still holds — the *loading* pass renders nothing.
 * What changed is that Phase 19 gives the card an affordance of its own, and
 * the journal most likely to want "attach an existing task" is exactly the one
 * with nothing on it yet; a card that hid itself would put the control out of
 * reach precisely where it is wanted.
 */

'use client';

import { useId } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useJournalTasks } from '@/lib/api/tasks';
import { AttachTaskDialog } from './AttachTaskDialog';
import {
  TaskLinkRole,
  type JournalTaskGroupIds,
  type JournalTaskResource,
} from '@/types/tasks';
import { JournalTaskRow } from './JournalTaskRow';

interface JournalTasksSectionProps {
  /** The journal being viewed. */
  readonly journalId: string;
}

/**
 * The three groups, in the order the specification lists them.
 *
 * `key` indexes `meta.groups`, whose values are **ordered id lists** — the
 * listing decides the order server-side, and this component does not re-sort.
 */
const GROUPS: ReadonlyArray<{
  readonly key: keyof JournalTaskGroupIds;
  readonly heading: string;
  /**
   * The link role the group's rows hold in this journal, which is what decides
   * whether a row offers to remove its link. Carried by the group rather than
   * read off a task's `link_roles`, because a task holding two roles is
   * rendered once per group and `link_roles` cannot tell the two rows apart.
   */
  readonly role: TaskLinkRole;
}> = [
  { key: 'due', heading: 'Due in this journal', role: TaskLinkRole.DUE },
  {
    key: 'created',
    heading: 'Created in this journal',
    role: TaskLinkRole.CREATED,
  },
  {
    key: 'mentioned',
    heading: 'Mentioned in this journal',
    role: TaskLinkRole.MENTIONED,
  },
];

export function JournalTasksSection({ journalId }: JournalTasksSectionProps) {
  // A prefix rather than an id: each group's heading needs one of its own for
  // its region to be labelled by it, and two sections on one page must not
  // collide.
  const idPrefix = useId();
  const { data, isLoading, isError } = useJournalTasks(journalId);

  // Nothing while the listing loads. Most journals hold no tasks, so a skeleton
  // would flash on nearly every journal detail view for a section that is
  // usually about to render nothing anyway.
  if (isLoading) return null;

  // A failure is *not* silent. Hiding the section here would be
  // indistinguishable from "this journal has no tasks", and a journal whose
  // lapsed tasks failed to load would read as clean — the one outcome the
  // lapsed design exists to prevent.
  //
  // It carries no attach affordance, though: the dialog excludes tasks already
  // linked here, and it reads that set from this listing. Offering it over a
  // listing that failed would be offering a picker that cannot keep the
  // server's two refusals off the screen.
  //
  // `&& !data` is the whole of the difference between a listing that failed and
  // a *refresh* that failed. A refetch error — a window refocus while the
  // network is down, say — leaves the previous `data` in place and only sets
  // the status, so without this the card would be replaced by an error line
  // while it had perfectly good tasks to show, taking any open attach dialog
  // down with it and closing over a request that had already left.
  if (isError && !data) {
    return (
      <Card data-testid='journal-tasks-section'>
        <CardHeader>
          <CardTitle className='text-lg'>Tasks</CardTitle>
        </CardHeader>
        <CardContent>
          <p role='status' className='text-muted-foreground text-sm'>
            This journal&rsquo;s tasks could not be loaded.
          </p>
        </CardContent>
      </Card>
    );
  }

  if (!data) return null;

  // A task holding more than one role in this journal is returned **once** in
  // `data` — JSON:API forbids the same resource twice — and named in each of
  // its groups, so the grouping is read from `meta.groups` and the resource
  // looked up by id. It is rendered under every group it belongs to.
  const byId = new Map<string, JournalTaskResource>(
    data.data.map(resource => [resource.id, resource])
  );
  const groups = GROUPS.map(group => ({
    ...group,
    tasks: data.meta.groups[group.key]
      .map(id => byId.get(String(id)))
      .filter((task): task is JournalTaskResource => task !== undefined),
  })).filter(group => group.tasks.length > 0);

  // Every task the journal holds in any role, which is what the attach dialog
  // has to exclude: one already mentioned here would be a no-op, and one
  // anchored here is a 409. Read from the listing already in hand rather than
  // fetched again.
  const linkedTaskIds = data.data.map(resource => resource.id);

  return (
    <Card data-testid='journal-tasks-section'>
      <CardHeader className='flex flex-row items-center justify-between gap-3 space-y-0'>
        <CardTitle className='text-lg'>Tasks</CardTitle>
        <AttachTaskDialog journalId={journalId} linkedTaskIds={linkedTaskIds} />
      </CardHeader>
      <CardContent className='space-y-6'>
        {groups.length === 0 && (
          <p className='text-muted-foreground text-sm'>
            No tasks are linked to this journal yet.
          </p>
        )}
        {groups.map(group => (
          <section
            key={group.key}
            aria-labelledby={`${idPrefix}-${group.key}`}
            data-testid={`journal-tasks-group-${group.key}`}
          >
            <h4
              id={`${idPrefix}-${group.key}`}
              className='text-muted-foreground text-sm font-medium'
            >
              {group.heading}
            </h4>
            <ul className='mt-2 space-y-2'>
              {group.tasks.map(task => (
                <JournalTaskRow
                  key={task.id}
                  task={task}
                  journalId={journalId}
                  role={group.role}
                />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
