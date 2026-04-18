/**
 * CalendarWeekView — week-grid calendar for journal events.
 *
 * Renders a 7-column grid (Mon–Sun) with event pills.
 */

'use client';

import {
  format,
  eachDayOfInterval,
  startOfWeek,
  endOfWeek,
  isToday,
} from 'date-fns';
import { enAU } from 'date-fns/locale';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CalendarEvent, groupEventsByDate } from '@/lib/calendarEventHelpers';
import { cn } from '@/lib/utils';
import { CalendarEventPill } from './CalendarEventPill';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';

const MAX_VISIBLE_EVENTS = 20;
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

interface CalendarWeekViewProps {
  /** The anchor date to determine which week to show */
  readonly anchorDate: Date;
  /** Calendar events to display */
  readonly events: CalendarEvent[];
  /** Callback when week navigation is triggered */
  readonly onWeekChange: (newAnchorDate: Date) => void;
  /** Callback when an empty slot is clicked (e.g. to create a new event) */
  readonly onSlotClick?: (date: string) => void;
  /** Loading state */
  readonly isLoading?: boolean;
  readonly className?: string;
}

export function CalendarWeekView({
  anchorDate,
  events,
  onWeekChange,
  onSlotClick,
  isLoading = false,
  className,
}: CalendarWeekViewProps) {
  // Get the full grid range (start from Monday of the week containing the anchor date)
  const gridStart = startOfWeek(anchorDate, { weekStartsOn: 1 }); // Monday
  const gridEnd = endOfWeek(anchorDate, { weekStartsOn: 1 });
  const allDays = eachDayOfInterval({ start: gridStart, end: gridEnd });

  // Group events by date for fast lookup
  const eventsByDate = groupEventsByDate(events);

  // Week heading
  const weekLabel = `${format(gridStart, 'MMM d, yyyy')} - ${format(gridEnd, 'MMM d, yyyy')}`;

  const handlePrevWeek = () => {
    const prevWeek = new Date(anchorDate);
    prevWeek.setDate(prevWeek.getDate() - 7);
    onWeekChange(prevWeek);
  };

  const handleNextWeek = () => {
    const nextWeek = new Date(anchorDate);
    nextWeek.setDate(nextWeek.getDate() + 7);
    onWeekChange(nextWeek);
  };

  return (
    <div
      className={cn('space-y-4', className)}
      data-testid='calendar-week-view'
    >
      {/* Week header with navigation */}
      <div className='flex items-center justify-between'>
        <Button
          variant='ghost'
          size='icon'
          onClick={handlePrevWeek}
          aria-label='Previous week'
        >
          <ChevronLeft className='h-5 w-5' />
        </Button>

        <h2 className='text-lg font-semibold'>{weekLabel}</h2>

        <Button
          variant='ghost'
          size='icon'
          onClick={handleNextWeek}
          aria-label='Next week'
        >
          <ChevronRight className='h-5 w-5' />
        </Button>
      </div>

      {isLoading ? (
        <div className='flex flex-col items-center justify-center py-12'>
          <div className='text-muted-foreground'>Loading week...</div>
        </div>
      ) : (
        <ScrollArea className='w-full'>
          <div
            className='min-w-[800px]'
            role='grid'
            aria-label={`Calendar for ${weekLabel}`}
          >
            {/* Weekday headers */}
            <div className='border-border grid grid-cols-7 border-b' role='row'>
              {allDays.map((day, i) => {
                const isTodayDate = isToday(day);
                return (
                  <div
                    key={day.toISOString()}
                    role='columnheader'
                    className='text-muted-foreground p-2 text-center text-sm font-medium'
                    data-today={isTodayDate || undefined}
                  >
                    <div
                      className={cn(
                        'text-xs uppercase',
                        isTodayDate && 'text-primary font-bold'
                      )}
                    >
                      {WEEKDAYS[i]}
                    </div>
                    <div
                      className={cn(
                        'mx-auto mt-1 flex h-8 w-8 items-center justify-center rounded-full text-lg',
                        isTodayDate
                          ? 'bg-primary text-primary-foreground font-bold'
                          : 'text-foreground'
                      )}
                    >
                      {day.getDate()}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Event Columns */}
            <div className='grid min-h-[500px] grid-cols-7' role='row'>
              {allDays.map(day => {
                const dateKey = format(day, 'yyyy-MM-dd');
                const dayEvents = eventsByDate[dateKey] || [];
                const isTodayDate = isToday(day);

                return (
                  <div
                    key={dateKey}
                    role='gridcell'
                    data-testid={`day-col-${dateKey}`}
                    className={cn(
                      'border-border group relative flex flex-col border-r border-b p-2',
                      isTodayDate && 'bg-primary/5',
                      'hover:bg-muted/30 focus-visible:bg-muted/30 transition-colors'
                    )}
                    onClick={e => {
                      if (!onSlotClick) {
                        return;
                      }

                      const target = e.target as HTMLElement | null;
                      if (target?.closest('a,button')) {
                        return;
                      }

                      onSlotClick(dateKey);
                    }}
                    onKeyDown={e => {
                      if (e.key !== 'Enter' && e.key !== ' ') {
                        return;
                      }

                      if (!onSlotClick) {
                        return;
                      }

                      const target = e.target as HTMLElement | null;
                      if (target?.closest('a,button')) {
                        return;
                      }

                      e.preventDefault();
                      onSlotClick(dateKey);
                    }}
                    tabIndex={0}
                    aria-label={`${format(day, 'EEEE, MMMM d, yyyy', { locale: enAU })}${dayEvents.length > 0 ? `, ${dayEvents.length} event${dayEvents.length > 1 ? 's' : ''}` : ''}`}
                  >
                    {/* Add Event Button overlay (visible on hover/focus) */}
                    {onSlotClick && (
                      <div className='absolute inset-x-0 top-0 hidden p-1 group-focus-within:block group-hover:block'>
                        <Button
                          type='button'
                          variant='secondary'
                          size='sm'
                          className='h-7 w-full text-xs opacity-80 hover:opacity-100'
                          onClick={e => {
                            e.stopPropagation();
                            onSlotClick(dateKey);
                          }}
                          aria-label={`Add event on ${format(day, 'MMM d')}`}
                        >
                          <Plus className='mr-1 h-3 w-3' /> Add
                        </Button>
                      </div>
                    )}

                    {/* Event pills container */}
                    <div
                      className={cn(
                        'flex flex-1 flex-col gap-1.5',
                        onSlotClick && 'group-hover:pt-8'
                      )}
                    >
                      {dayEvents.slice(0, MAX_VISIBLE_EVENTS).map(event => (
                        <CalendarEventPill
                          key={event.id}
                          event={event}
                          variant='week'
                        />
                      ))}

                      {dayEvents.length > MAX_VISIBLE_EVENTS && (
                        <div className='text-muted-foreground w-full py-1 text-center text-xs'>
                          +{dayEvents.length - MAX_VISIBLE_EVENTS} more
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          <ScrollBar orientation='horizontal' />
        </ScrollArea>
      )}
    </div>
  );
}
