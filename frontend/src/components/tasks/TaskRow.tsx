import { useId } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { CalendarDays } from 'lucide-react';
import { ContactAvatarStack } from '@/components/contacts/ContactAvatarStack';
import { Badge } from '@/components/ui/badge';
import { formatIsoShortWeekdayDate } from '@/lib/date-utils';
import { overdueWording } from '@/lib/task-display';
import { cn } from '@/lib/utils';
import {
  TaskStatus,
  type ListTaskReadResource,
  type TaskJournalRef,
} from '@/types/tasks';
import { TaskFlagMarker } from './TaskFlagMarker';
import { TaskIconMarker } from './TaskIconMarker';
import { TaskStatusCheckbox } from './TaskStatusCheckbox';

const CONTACT_NOUN = { one: 'contact', many: 'contacts' } as const;

interface TaskRowProps {
  readonly task: ListTaskReadResource;
}

function DueJournalLink({ journal }: { readonly journal: TaskJournalRef }) {
  return (
    <Link
      href={`/journals/${journal.id}` as Route}
      data-testid='task-row-due-journal'
      className='text-foreground inline-flex max-w-full min-w-0 items-center gap-1 underline-offset-4 hover:underline max-sm:min-h-11'
    >
      <CalendarDays aria-hidden='true' className='size-3.5 shrink-0' />
      <span className='min-w-0 wrap-anywhere'>
        {journal.title} ·{' '}
        {journal.cancelled ? (
          'journal cancelled'
        ) : (
          <time dateTime={journal.date}>
            {formatIsoShortWeekdayDate(journal.date)}
          </time>
        )}
      </span>
    </Link>
  );
}

export function TaskRow({ task }: TaskRowProps) {
  const {
    text,
    status,
    icon,
    flagged,
    due_date,
    due_journal,
    overdue,
    contacts,
  } = task.attributes;
  const cancelledId = useId();
  const closed = status !== TaskStatus.NOT_DONE;
  const cancelled = status === TaskStatus.CANCELLED;
  const overdueMarker =
    overdue && status === TaskStatus.NOT_DONE
      ? overdueWording(task.attributes)
      : null;
  const dueDate = overdueMarker ? null : due_date;

  return (
    <li
      data-testid={`task-row-${task.id}`}
      data-task-id={task.id}
      className='border-border flex min-h-14 items-center gap-3 border-b py-2'
    >
      <span className='flex size-11 shrink-0 items-center justify-center'>
        <TaskStatusCheckbox
          task={task}
          {...(cancelled ? { describedById: cancelledId } : {})}
        />
      </span>
      {icon && <TaskIconMarker icon={icon} testId='task-row-icon' />}
      <div className='min-w-0 flex-1'>
        <p
          data-testid='task-row-text'
          className={cn(
            'wrap-anywhere',
            closed && 'text-muted-foreground line-through'
          )}
        >
          {text}
        </p>
        <div className='text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-xs empty:hidden'>
          {overdueMarker && (
            <Badge
              data-testid='task-row-overdue'
              variant='destructive'
              title={overdueMarker.description}
            >
              {overdueMarker.label}
            </Badge>
          )}
          {dueDate && (
            <Badge data-testid='task-row-due-date' variant='outline'>
              <time dateTime={dueDate}>
                {formatIsoShortWeekdayDate(dueDate)}
              </time>
            </Badge>
          )}
          {due_journal && <DueJournalLink journal={due_journal} />}
          {cancelled && (
            <Badge id={cancelledId} variant='secondary'>
              Cancelled
            </Badge>
          )}
        </div>
      </div>
      {flagged && <TaskFlagMarker />}
      <ContactAvatarStack
        people={contacts.map(contact => ({
          id: contact.id,
          name: contact.display_name,
          photoUrl: contact.photo_url ?? null,
        }))}
        label='Contacts'
        noun={CONTACT_NOUN}
        testId='task-row-contacts'
      />
    </li>
  );
}
