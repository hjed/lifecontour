import Link from 'next/link';
import type { Route } from 'next';
import { Cloud, AlertCircle } from 'lucide-react';
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
          <div className='flex items-center gap-2'>
            <div className='truncate text-base'>{event.title}</div>
            {event.isSyncedToGoogle && (
              <Cloud
                className='h-4 w-4 shrink-0 opacity-80'
                data-testid='sync-indicator'
                aria-label='Synced to Google Calendar'
              />
            )}
            {event.hasPendingReviews && (
              <div
                className='flex flex-row items-center gap-1 rounded bg-black/20 px-1.5 py-0.5 text-[10px] font-bold text-red-200 uppercase'
                data-testid='needs-review-badge'
                role='img'
                aria-label='Needs Review'
              >
                <AlertCircle className='h-3 w-3' aria-hidden='true' />
                Review
              </div>
            )}
          </div>
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
        <div className='flex items-center gap-1'>
          {event.startTime && !event.isAllDay && (
            <span className='truncate font-semibold opacity-90'>
              {event.startTime}
            </span>
          )}
          {event.isSyncedToGoogle && (
            <Cloud
              className='h-3 w-3 shrink-0 opacity-80'
              data-testid='sync-indicator'
              aria-label='Synced to Google Calendar'
            />
          )}
          <span className='truncate'>{event.title}</span>
          {event.hasPendingReviews && (
            <div
              className='h-2 w-2 shrink-0 rounded-full bg-red-400 shadow-sm'
              data-testid='needs-review-badge'
              role='img'
              aria-label='Needs Review'
            />
          )}
        </div>
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
      <div className='flex items-center gap-1'>
        {event.isSyncedToGoogle && (
          <Cloud
            className='h-3 w-3 shrink-0 opacity-80'
            data-testid='sync-indicator'
            aria-label='Synced to Google Calendar'
          />
        )}
        <span className='truncate'>{event.title}</span>
        {event.hasPendingReviews && (
          <div
            className='h-2 w-2 shrink-0 rounded-full bg-red-400 shadow-sm'
            data-testid='needs-review-badge'
            role='img'
            aria-label='Needs Review'
          />
        )}
      </div>
    </Link>
  );
}
