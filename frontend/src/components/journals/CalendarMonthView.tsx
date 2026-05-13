/**
 * CalendarMonthView — month-grid calendar for journal events.
 *
 * Renders a 7-column grid (Mon–Sun) with event pills colour-coded by calendar.
 * Clicking an event navigates to the journal detail page.
 * Clicking a day cell triggers the onDayClick callback (e.g. to switch to agenda).
 * Month navigation is handled via onMonthChange.
 */

'use client';

import {
  format,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  eachDayOfInterval,
  isSameMonth,
  isToday,
} from 'date-fns';
import { enAU } from 'date-fns/locale';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CalendarEvent, groupEventsByDate } from '@/lib/calendarEventHelpers';
import { cn } from '@/lib/utils';
import { CalendarEventPill } from './CalendarEventPill';

const MAX_VISIBLE_EVENTS = 3;
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

interface CalendarMonthViewProps {
  /** Full year (e.g. 2026) */
  readonly year: number;
  /** 0-indexed month (0 = January) */
  readonly month: number;
  /** Calendar events to display */
  readonly events: CalendarEvent[];
  /** Callback when month navigation is triggered */
  readonly onMonthChange: (year: number, month: number) => void;
  /** Callback when a day cell is clicked */
  readonly onDayClick?: (date: string) => void;
  /** Callback when the empty slot/add button is clicked to create an event */
  readonly onSlotClick?: (date: string) => void;
  /** Loading state */
  readonly isLoading?: boolean;
  readonly className?: string;
}

export function CalendarMonthView({
  year,
  month,
  events,
  onMonthChange,
  onDayClick,
  onSlotClick,
  isLoading = false,
  className,
}: CalendarMonthViewProps) {
  const monthDate = new Date(year, month, 1);
  const monthStart = startOfMonth(monthDate);
  const monthEnd = endOfMonth(monthDate);

  // Get the full grid range (start from Monday of the week containing month start)
  const gridStart = startOfWeek(monthStart, { weekStartsOn: 1 }); // Monday
  const gridEnd = endOfWeek(monthEnd, { weekStartsOn: 1 });
  const allDays = eachDayOfInterval({ start: gridStart, end: gridEnd });

  // Group events by date for fast lookup
  const eventsByDate = groupEventsByDate(events);

  // Month heading
  const monthLabel = format(monthDate, 'MMMM yyyy', { locale: enAU });

  const handlePrevMonth = () => {
    if (month === 0) {
      onMonthChange(year - 1, 11);
    } else {
      onMonthChange(year, month - 1);
    }
  };

  const handleNextMonth = () => {
    if (month === 11) {
      onMonthChange(year + 1, 0);
    } else {
      onMonthChange(year, month + 1);
    }
  };

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid='calendar-month-view'
    >
      {/* Month header with navigation */}
      <div className='flex items-center justify-between'>
        <Button
          variant='ghost'
          size='icon'
          onClick={handlePrevMonth}
          aria-label='Previous month'
        >
          <ChevronLeft className='h-5 w-5' />
        </Button>

        <h2 className='text-lg font-semibold'>{monthLabel}</h2>

        <Button
          variant='ghost'
          size='icon'
          onClick={handleNextMonth}
          aria-label='Next month'
        >
          <ChevronRight className='h-5 w-5' />
        </Button>
      </div>

      {isLoading ? (
        <div className='flex items-center justify-center py-12'>
          <div className='text-muted-foreground'>Loading calendar...</div>
        </div>
      ) : (
        <div role='grid' aria-label={`Calendar for ${monthLabel}`}>
          {/* Weekday headers */}
          <div className='border-border grid grid-cols-7 border-b' role='row'>
            {WEEKDAYS.map(day => (
              <div
                key={day}
                role='columnheader'
                className='text-muted-foreground py-2 text-center text-sm font-medium'
              >
                {day}
              </div>
            ))}
          </div>

          {/* Day cells in weekly rows */}
          {chunk(allDays, 7).map((week, weekIndex) => (
            <div key={weekIndex} className='grid grid-cols-7' role='row'>
              {week.map(day => {
                const dateKey = format(day, 'yyyy-MM-dd');
                const dayEvents = eventsByDate[dateKey] || [];
                const isCurrentMonth = isSameMonth(day, monthDate);
                const isTodayDate = isToday(day);

                return (
                  <div
                    key={dateKey}
                    role='gridcell'
                    data-testid={`day-cell-${dateKey}`}
                    data-today={isTodayDate || undefined}
                    className={cn(
                      'border-border group focus-visible:bg-muted/30 ring-offset-background focus-visible:ring-ring relative min-h-24 border-r border-b p-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
                      !isCurrentMonth ? 'bg-muted/30' : 'hover:bg-muted/10',
                      isTodayDate && 'bg-primary/5'
                    )}
                    onClick={() => onDayClick?.(dateKey)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        if (e.target === e.currentTarget) {
                          e.preventDefault();
                          onDayClick?.(dateKey);
                        }
                      }
                    }}
                    tabIndex={isCurrentMonth ? 0 : -1}
                    aria-label={`${format(day, 'EEEE, MMMM d, yyyy', { locale: enAU })}${dayEvents.length > 0 ? `, ${dayEvents.length} event${dayEvents.length > 1 ? 's' : ''}` : ''}`}
                  >
                    {/* Day number */}
                    <div
                      className={cn(
                        'mb-1 text-right text-sm',
                        !isCurrentMonth && 'text-muted-foreground/60',
                        isTodayDate &&
                          'bg-primary text-primary-foreground float-right inline-flex h-6 w-6 items-center justify-center rounded-full font-semibold'
                      )}
                    >
                      {day.getDate()}
                    </div>

                    {/* Add Event Button overlay — visible on hover/focus or always on touch devices */}
                    {onSlotClick && isCurrentMonth && (
                      <div className='absolute top-1 left-1 hidden group-focus-within:block group-hover:block group-focus:block'>
                        <button
                          type='button'
                          className='bg-secondary text-secondary-foreground rounded p-1 shadow-sm hover:opacity-80'
                          onClick={e => {
                            e.stopPropagation();
                            onSlotClick(dateKey);
                          }}
                          aria-label={`Add event on ${format(day, 'MMM d')}`}
                        >
                          <Plus className='h-3 w-3' />
                        </button>
                      </div>
                    )}

                    {/* Event pills */}
                    <div className='clear-both mt-4 space-y-0.5'>
                      {dayEvents.slice(0, MAX_VISIBLE_EVENTS).map(event => (
                        <CalendarEventPill
                          key={event.id}
                          event={event}
                          variant='month'
                        />
                      ))}

                      {dayEvents.length > MAX_VISIBLE_EVENTS && (
                        <button
                          className='text-muted-foreground hover:text-foreground w-full text-center text-[10px]'
                          onClick={e => {
                            e.stopPropagation();
                            onDayClick?.(dateKey);
                          }}
                        >
                          +{dayEvents.length - MAX_VISIBLE_EVENTS} more
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Split an array into chunks of a given size.
 */
function chunk<T>(array: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size));
  }
  return chunks;
}
