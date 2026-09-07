/**
 * DashboardTaskRow — one task due this week as the dashboard draws it
 * (**W22**–**W27**).
 *
 * A bordered rounded row with a left accent bar and a hover shadow (**W22**),
 * holding the commitment as a prominent non-link line (**W23**), a
 * colour-coded due chip (**W25**), the *"Due in ‹journal›"* link (**W26**) and
 * each linked contact as an avatar beside their name (**W27**). The same row
 * idiom `AgendaEntryRow` and `JournalTaskRow` already use, so the three read
 * alike.
 *
 * **A pure function of the payload row, with no query and no clock.** That is
 * load-bearing rather than convenient: `days_away` counts from the window's
 * first day and `due_journal.date` is a calendar day, both resolved by the
 * server in the user's configured zone, so both are rendered as given. Working
 * either out here would consult the *browser's* zone, which near midnight can
 * answer a day out — pinned in `DashboardTaskRow.timezone.test.tsx`.
 *
 * **The action arrives as a slot** rather than being mounted here. It is the
 * one thing on this row that writes, so keeping it outside is what lets the
 * row stay pure and be asserted without a query client; the card supplies it,
 * and `taskTextId` is how the two ends agree on the id the action group is
 * described by without either handing it to the other.
 *
 * **W23** says the text is not a link, and there is nowhere for it to go: the
 * specification gives a task no detail route, because the dashboard is where a
 * commitment is *reminded of* and a journal is where it is worked with.
 */

import type { ReactNode } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { CalendarClock } from 'lucide-react';
import { ContactAvatar } from '@/components/contacts/ContactAvatar';
import type { HomeDashboardTask } from '@/lib/api/home-dashboard';
import { nameParts } from '@/lib/contact-names';
import {
  dueAccentClassName,
  dueChipClassName,
  dueChipLabel,
  taskTextId,
} from '@/lib/dashboard-tasks-display';
import { cn } from '@/lib/utils';

interface DashboardTaskRowProps {
  /** The task, as the dashboard payload sent it. */
  readonly task: HomeDashboardTask;
  /**
   * The inline action group (**W24**), mounted top-right of the text row.
   *
   * Optional so the row can be rendered — and asserted — without a mutation
   * behind it.
   */
  readonly actions?: ReactNode;
}

export function DashboardTaskRow({ task, actions }: DashboardTaskRowProps) {
  const { task_id, text, due_journal, contacts } = task;

  return (
    <li
      data-testid={`dashboard-task-${task_id}`}
      className='border-border relative overflow-hidden rounded-lg border py-3 pr-3 pl-4 transition-shadow hover:shadow-sm'
    >
      <span
        aria-hidden='true'
        data-testid='dashboard-task-accent'
        className={cn(
          'absolute inset-y-0 left-0 w-1',
          dueAccentClassName(due_journal.id)
        )}
      />

      {/* W24 puts the action top-right of the text row and lets it wrap under
          the text when the column is narrow, which is what this shared
          `flex-wrap` does: the chip and the action travel together. */}
      <div className='flex flex-wrap items-start justify-between gap-x-3 gap-y-1'>
        <p
          id={taskTextId(task_id)}
          data-testid='dashboard-task-text'
          className='min-w-0 font-medium'
        >
          {text}
        </p>

        <div className='flex flex-wrap items-center justify-end gap-x-2 gap-y-1'>
          {/* A `<time>`, and the `dateTime` is the point rather than tidiness.
              The specification asks a row to show "the due journal's title and
              date", while W25 makes the visible label **relative** for the
              first two days — so on those rows the date is in the markup even
              though the words are `Today`. The two are not in conflict for a
              reader either: the page header (W2) names today in full. */}
          <time
            dateTime={due_journal.date}
            data-testid='dashboard-task-chip'
            className={cn(
              'flex shrink-0 items-center gap-1 rounded-md border px-2 py-0.5 text-xs',
              dueChipClassName(due_journal.id)
            )}
          >
            <CalendarClock className='h-3 w-3' aria-hidden='true' />
            {dueChipLabel(task)}
          </time>
          {actions}
        </div>
      </div>

      <p
        data-testid='dashboard-task-due'
        className='text-muted-foreground mt-1 text-sm'
      >
        Due in{' '}
        <Link
          href={`/journals/${due_journal.id}` as Route}
          className='underline-offset-4 hover:underline'
        >
          {due_journal.title}
        </Link>
      </p>

      {contacts.length > 0 && (
        <ul
          data-testid='dashboard-task-contacts'
          className='mt-2 flex flex-wrap items-center gap-x-3 gap-y-1'
        >
          {contacts.map(contact => {
            const { first, last } = nameParts(contact.name);
            return (
              <li
                key={contact.contact_id}
                className='flex min-w-0 items-center gap-1.5'
              >
                {/* Hidden from assistive tech, because the name it is
                    labelled with is *already* beside it in text (W27).
                    `ContactAvatar` carries `role="img"` with the contact's
                    name, so without this a screen reader reads every contact
                    twice. The avatar is the decorative half of the pair here;
                    the text is what a sighted reader is reading too. */}
                <span aria-hidden='true' className='flex shrink-0'>
                  <ContactAvatar
                    firstName={first}
                    lastName={last}
                    {...(contact.photo_url
                      ? { imageUrl: contact.photo_url }
                      : {})}
                    size='sm'
                    className='h-6 w-6 text-[10px]'
                  />
                </span>
                <span className='text-muted-foreground min-w-0 text-sm'>
                  {contact.name}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}
