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

import { useId } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { lapseWording, statusWording } from '@/lib/task-display';
import { TaskStatus, type JournalTaskResource } from '@/types/tasks';
import { JournalTaskActions } from './JournalTaskActions';

interface JournalTaskRowProps {
  /** The task, as the journal's listing returned it. */
  readonly task: JournalTaskResource;
  /** The journal being viewed, which decides whether to name the due journal. */
  readonly journalId: string;
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

/**
 * Split a display name for the avatar's initials.
 *
 * Contacts reach a task as a single `display_name`; `ContactAvatar` wants the
 * parts. Everything after the first space is the surname, which is wrong for
 * some names and right for the initials in all of them.
 */
function nameParts(displayName: string): { first: string; last: string } {
  const [first = '', ...rest] = displayName.trim().split(/\s+/);
  return { first, last: rest.join(' ') };
}

export function JournalTaskRow({ task, journalId }: JournalTaskRowProps) {
  const { text, status, lapsed, lapse_reason, due_journal, contacts } =
    task.attributes;
  // The actions are named the same on every row, so they are described by the
  // text of the commitment they act on rather than by a label of their own.
  const textId = useId();

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

          <JournalTaskActions task={task} describedById={textId} />
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
    </li>
  );
}
