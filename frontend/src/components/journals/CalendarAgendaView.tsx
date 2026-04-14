/**
 * CalendarAgendaView — chronological event list grouped by day.
 *
 * Displays events in a vertical list with date headings, time ranges,
 * calendar colour dots, and type icons. Clicking an event navigates
 * to the journal detail page.
 */

'use client';

import Link from 'next/link';
import type { Route } from 'next';
import { format, parseISO } from 'date-fns';
import { enAU } from 'date-fns/locale';
import {
  FileText,
  Calendar as CalendarIcon,
  Heart,
  ClipboardList,
  Plane,
  Image,
  Activity,
  Mountain,
} from 'lucide-react';
import { CalendarEvent, groupEventsByDate } from '@/lib/calendarEventHelpers';
import { JournalType } from '@/types/journals';
import { cn } from '@/lib/utils';

// Simplified type icon mapping (subset for compact display)
const TYPE_ICON_MAP: Partial<
  Record<JournalType, React.ComponentType<{ className?: string }>>
> = {
  [JournalType.NOTE]: FileText,
  [JournalType.EVENT]: CalendarIcon,
  [JournalType.MOOD_RATING]: Heart,
  [JournalType.PLAN]: ClipboardList,
  [JournalType.TRAVEL]: Plane,
  [JournalType.PHOTO_ALBUM]: Image,
  [JournalType.FITNESS]: Activity,
  [JournalType.OUTDOOR_ACTIVITY]: Mountain,
};

interface CalendarAgendaViewProps {
  /** Calendar events to display */
  readonly events: CalendarEvent[];

  /** Loading state */
  readonly isLoading?: boolean;
  readonly className?: string;
}

/**
 * Format the time display for an event.
 * Returns "All day" for all-day events, or "HH:MM – HH:MM" for timed events.
 */
function formatEventTime(event: CalendarEvent): string {
  if (event.isAllDay || (!event.startTime && !event.endTime)) {
    return 'All day';
  }
  if (event.startTime && event.endTime) {
    return `${event.startTime} – ${event.endTime}`;
  }
  if (event.startTime) {
    return event.startTime;
  }
  return 'All day';
}

export function CalendarAgendaView({
  events,
  isLoading = false,
  className,
}: CalendarAgendaViewProps) {
  if (isLoading) {
    return (
      <div className='flex items-center justify-center py-12'>
        <div className='text-muted-foreground'>Loading agenda...</div>
      </div>
    );
  }

  const eventsByDate = groupEventsByDate(events);

  // Sort date keys ascending
  const sortedDates = Object.keys(eventsByDate).sort((a, b) =>
    a.localeCompare(b)
  );

  if (sortedDates.length === 0) {
    return (
      <div className={cn('py-12 text-center', className)}>
        <CalendarIcon className='text-muted-foreground mx-auto h-12 w-12' />
        <p className='text-muted-foreground mt-4 text-sm'>
          No events in this date range
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn('space-y-6', className)}
      data-testid='calendar-agenda-view'
    >
      {sortedDates.map(dateKey => {
        const dayEvents = [...eventsByDate[dateKey]].sort((a, b) => {
          // All day events come first
          if (a.isAllDay && !b.isAllDay) return -1;
          if (!a.isAllDay && b.isAllDay) return 1;

          // Otherwise sort chronologically
          const timeA = a.startTime || '00:00';
          const timeB = b.startTime || '00:00';
          return timeA.localeCompare(timeB);
        });
        const date = parseISO(dateKey);
        const heading = format(date, 'EEEE, MMMM d, yyyy', { locale: enAU });

        return (
          <section key={dateKey} aria-label={heading}>
            {/* Day heading */}
            <h3 className='bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-10 border-b py-2 text-lg font-semibold backdrop-blur'>
              {heading}
            </h3>

            {/* Event list */}
            <ul role='list' className='divide-border divide-y'>
              {dayEvents.map(event => (
                <li
                  key={event.id}
                  role='listitem'
                  className='hover:bg-muted/50 transition-colors'
                >
                  <Link
                    href={`/journals/${event.id}` as Route}
                    className='flex items-center gap-3 px-4 py-3'
                  >
                    {/* Calendar colour dot */}
                    <div
                      className='h-3 w-3 flex-shrink-0 rounded-full'
                      style={{ backgroundColor: event.calendarColor }}
                      aria-hidden='true'
                      data-testid={`calendar-dot-${event.id}`}
                    />

                    {/* Time */}
                    <div className='text-muted-foreground w-28 flex-shrink-0 text-sm'>
                      {formatEventTime(event)}
                    </div>

                    {/* Type icons */}
                    <div className='flex flex-shrink-0 gap-1'>
                      {event.journalTypes.map(type => {
                        const Icon = TYPE_ICON_MAP[type];
                        return Icon ? (
                          <Icon
                            key={type}
                            className='text-muted-foreground h-4 w-4'
                            aria-label={type}
                          />
                        ) : null;
                      })}
                    </div>

                    {/* Title */}
                    <span
                      className={cn(
                        'flex-1 truncate font-medium',
                        event.isCancelled &&
                          'text-muted-foreground line-through'
                      )}
                    >
                      {event.title}
                    </span>

                    {/* Calendar name */}
                    {event.calendarName && (
                      <span className='text-muted-foreground flex-shrink-0 text-xs'>
                        {event.calendarName}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
