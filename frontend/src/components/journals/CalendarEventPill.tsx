import Link from 'next/link';
import type { Route } from 'next';
import { cn } from '@/lib/utils';
import { CalendarEvent } from '@/lib/calendarEventHelpers';

interface CalendarEventPillProps {
  readonly event: CalendarEvent;
  readonly variant: 'month' | 'week' | 'day';
}

export function CalendarEventPill({ event, variant }: CalendarEventPillProps) {
  if (variant === 'day') {
    return (
      <Link
        href={`/journals/${event.id}` as Route}
        className={cn(
          'flex w-full items-center gap-4 rounded-lg px-4 py-3 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90',
          event.isCancelled && 'line-through opacity-60'
        )}
        style={{ backgroundColor: event.calendarColor }}
        onClick={e => e.stopPropagation()}
      >
        <div className='w-20 flex-shrink-0 text-right font-semibold text-white/90'>
          {event.isAllDay || (!event.startTime && !event.endTime) ? (
            'All Day'
          ) : (
            <span>
              {event.startTime || '??:??'}
              <br />
              <span className='text-xs font-normal opacity-80'>
                {event.endTime || ''}
              </span>
            </span>
          )}
        </div>
        <div className='min-w-0 flex-1 border-l border-white/20 pl-4'>
          <div className='truncate text-base'>{event.title}</div>
          {event.calendarName && (
            <div className='mt-0.5 text-xs text-white/70'>
              {event.calendarName}
            </div>
          )}
        </div>
      </Link>
    );
  }

  if (variant === 'week') {
    return (
      <Link
        href={`/journals/${event.id}` as Route}
        className={cn(
          'block w-full truncate overflow-hidden rounded px-2 py-1.5 text-xs font-medium text-white shadow-sm transition-opacity hover:opacity-90',
          event.isCancelled && 'line-through opacity-60'
        )}
        style={{ backgroundColor: event.calendarColor }}
        title={event.title}
        onClick={e => e.stopPropagation()}
      >
        {event.startTime && !event.isAllDay && (
          <span className='mr-1 font-semibold opacity-90'>
            {event.startTime}
          </span>
        )}
        {event.title}
      </Link>
    );
  }

  // Month variant
  return (
    <Link
      href={`/journals/${event.id}` as Route}
      className={cn(
        'block truncate rounded px-1 py-0.5 text-[11px] leading-tight text-white transition-opacity hover:opacity-90',
        event.isCancelled && 'line-through opacity-60'
      )}
      style={{ backgroundColor: event.calendarColor }}
      title={event.title}
      onClick={e => e.stopPropagation()}
    >
      {event.title}
    </Link>
  );
}
