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
 */

'use client';

import { useId } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useJournalTasks } from '@/lib/api/tasks';
import type { JournalTaskGroupIds, JournalTaskResource } from '@/types/tasks';
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
}> = [
  { key: 'due', heading: 'Due in this journal' },
  { key: 'created', heading: 'Created in this journal' },
  { key: 'mentioned', heading: 'Mentioned in this journal' },
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
  if (isError) {
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

  // Nothing rather than an empty container, and an empty group is omitted
  // rather than shown as a heading with nothing under it.
  if (groups.length === 0) return null;

  return (
    <Card data-testid='journal-tasks-section'>
      <CardHeader>
        <CardTitle className='text-lg'>Tasks</CardTitle>
      </CardHeader>
      <CardContent className='space-y-6'>
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
                />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}
