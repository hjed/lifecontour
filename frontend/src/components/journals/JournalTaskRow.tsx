/**
 * One task as a journal shows it.
 *
 * The presentation follows the dashboard's task-row idiom so the two surfaces
 * read alike — a bordered rounded row with a left accent bar and a hover shadow
 * (**W22**), the task text as a prominent non-link line (**W23**), the inline
 * status actions top-right of the text row (**W24**), and each linked contact
 * as an avatar beside their name in muted text (**W27**).
 *
 * The actions are a component of their own (`JournalTaskActions`) because they
 * carry a mutation and an offer table, while everything else here is a pure
 * rendering of the listing's payload. The resurrect affordance a lapsed row
 * also wants arrives with the retarget dialog.
 */

'use client';

import { useId, useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { TaskActivityFeed } from '@/components/tasks/TaskActivityFeed';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { nameParts } from '@/lib/contact-names';
import { cn } from '@/lib/utils';
import { lapseWording, statusWording } from '@/lib/task-display';
import {
  TaskStatus,
  type JournalTaskResource,
  type TaskLinkRole,
} from '@/types/tasks';
import { JournalTaskActions } from './JournalTaskActions';

interface JournalTaskRowProps {
  /** The task, as the journal's listing returned it. */
  readonly task: JournalTaskResource;
  /** The journal being viewed, which decides whether to name the due journal. */
  readonly journalId: string;
  /**
   * The role this row's link holds in the journal being viewed.
   *
   * Passed down rather than read off `link_roles`, because the listing renders
   * a task holding two roles **once per group** and the two rows differ only
   * by which group they are in — `link_roles` says the task is both and cannot
   * tell one row from the other.
   */
  readonly role: TaskLinkRole;
}

/**
 * The left accent bar's colour (**W22**).
 *
 * A divergence from the wireframe, recorded rather than fudged: W22 keys the
 * bar to the due journal's type/calendar colour, and a task's journal
 * references carry no colour. Keyed to what the row actually knows — whether
 * the commitment is still live — until the read model carries more.
 */
function accentClass(status: TaskStatus, lapsed: boolean): string {
  if (lapsed) return 'bg-destructive';
  return status === TaskStatus.NOT_DONE
    ? 'bg-primary'
    : 'bg-muted-foreground/40';
}

export function JournalTaskRow({ task, journalId, role }: JournalTaskRowProps) {
  const { text, status, lapsed, lapse_reason, due_journal, contacts } =
    task.attributes;
  // The actions are named the same on every row, so they are described by the
  // text of the commitment they act on rather than by a label of their own.
  const textId = useId();
  // The history disclosure is closed to begin with and does not fetch until it
  // is opened — a journal can hold many tasks, and each history is a request.
  const historyId = useId();
  const triggerId = useId();
  const [historyOpen, setHistoryOpen] = useState(false);

  // Terminal statuses are shown, not hidden, and never as if still live — the
  // stance the wireframe takes on cancelled journals (W18).
  const isTerminal = status !== TaskStatus.NOT_DONE;
  const lapse = lapsed ? lapseWording(lapse_reason) : null;
  // Naming the due journal on a row that *is* the due journal would only say
  // "due in this journal"; elsewhere it is the missing half of a lapse marker.
  const showDueJournal = String(due_journal.id) !== journalId;

  return (
    <li
      data-testid={`journal-task-${task.id}`}
      className='border-border relative overflow-hidden rounded-lg border py-3 pr-3 pl-4 transition-shadow hover:shadow-sm'
    >
      <span
        aria-hidden='true'
        className={cn(
          'absolute inset-y-0 left-0 w-1',
          accentClass(status, lapsed)
        )}
      />

      <div className='flex flex-wrap items-start justify-between gap-x-3 gap-y-1'>
        <p
          id={textId}
          data-testid='journal-task-text'
          className={cn(
            'font-medium',
            isTerminal && 'text-muted-foreground line-through'
          )}
        >
          {text}
        </p>

        {/* W24 puts the actions top-right of the text row and lets them wrap
            under it when the column is narrow, which is what this cluster
            does: it shares the text row's `flex-wrap` and carries the status
            badges alongside. */}
        <div className='flex flex-wrap items-center justify-end gap-x-3 gap-y-1'>
          <div className='flex flex-wrap items-center gap-1.5'>
            <Badge variant={isTerminal ? 'secondary' : 'outline'}>
              {statusWording(status)}
            </Badge>
            {lapse && (
              <Badge
                data-testid='journal-task-lapsed'
                variant='outline'
                className='border-destructive/50 text-destructive'
                title={lapse.description}
              >
                {lapse.label}
              </Badge>
            )}
          </div>

          <JournalTaskActions
            task={task}
            journalId={journalId}
            role={role}
            describedById={textId}
          />
        </div>
      </div>

      {showDueJournal && (
        <p className='text-muted-foreground mt-1 text-sm'>
          Due in{' '}
          <Link
            href={`/journals/${due_journal.id}` as Route}
            className='underline-offset-4 hover:underline'
          >
            {due_journal.title}
          </Link>
        </p>
      )}

      {contacts.length > 0 && (
        <ul
          data-testid='journal-task-contacts'
          className='mt-2 flex flex-wrap items-center gap-x-3 gap-y-1'
        >
          {contacts.map(contact => {
            const { first, last } = nameParts(contact.display_name);
            return (
              <li key={contact.id} className='flex items-center gap-1.5'>
                <ContactAvatar
                  firstName={first}
                  lastName={last}
                  {...(contact.photo_url
                    ? { imageUrl: contact.photo_url }
                    : {})}
                  size='sm'
                  className='h-6 w-6 text-[10px]'
                />
                <span className='text-muted-foreground text-sm'>
                  {contact.display_name}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {/* Last in the row, deliberately: expanding it must not push the task's
          contacts away from the commitment they belong to. */}
      <div className='mt-2'>
        {/* The trigger names the commitment, not just "history": every row's
            would otherwise have the same accessible name, which is what a
            screen-reader user hears tabbing through a journal's tasks. */}
        <Button
          type='button'
          variant='ghost'
          size='sm'
          className='text-muted-foreground h-7 px-1.5 text-xs'
          onClick={() => setHistoryOpen(open => !open)}
          id={triggerId}
          aria-expanded={historyOpen}
          aria-controls={historyId}
          aria-label={`${historyOpen ? 'Hide' : 'Show'} history for “${text}”`}
        >
          {historyOpen ? (
            <ChevronDown className='mr-1 h-3.5 w-3.5' aria-hidden='true' />
          ) : (
            <ChevronRight className='mr-1 h-3.5 w-3.5' aria-hidden='true' />
          )}
          History
        </Button>
        {/* The panel takes its name from the trigger rather than from a heading
            of its own: the journal page already has an "Activity" heading, and
            one per open row would be a run of identical h3s inside a list. */}
        <div
          id={historyId}
          hidden={!historyOpen}
          role='region'
          aria-labelledby={triggerId}
        >
          {historyOpen && (
            <TaskActivityFeed
              taskId={task.id}
              className='mt-2 border-none shadow-none'
              pageSize={5}
              title={null}
            />
          )}
        </div>
      </div>
    </li>
  );
}
