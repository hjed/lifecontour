/**
 * CalendarDayView — day calendar for journal events.
 *
 * Renders a single-day column with event pills.
 */

'use client';

import { format, isToday } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CalendarEvent, groupEventsByDate } from '@/lib/calendarEventHelpers';
import { cn } from '@/lib/utils';
import { ScrollArea } from '@/components/ui/scroll-area';
import { CalendarEventPill } from './CalendarEventPill';

interface CalendarDayViewProps {
  /** The anchor date to determine which day to show */
  readonly anchorDate: Date;
  /** Calendar events to display */
  readonly events: CalendarEvent[];
  /** Callback when day navigation is triggered */
  readonly onDayChange: (newAnchorDate: Date) => void;
  /** Callback when an empty slot is clicked (e.g. to create a new event) */
  readonly onSlotClick?: (date: string) => void;
  /** Loading state */
  readonly isLoading?: boolean;
  readonly className?: string;
}

export function CalendarDayView({
  anchorDate,
  events,
  onDayChange,
  onSlotClick,
  isLoading = false,
  className,
}: CalendarDayViewProps) {
  // Group events by date for fast lookup
  const eventsByDate = groupEventsByDate(events);
  const dateKey = format(anchorDate, 'yyyy-MM-dd');
  const dayEvents = eventsByDate[dateKey] || [];
  const isTodayDate = isToday(anchorDate);

  // Day heading
  const dayLabel = format(anchorDate, 'EEEE, MMMM d, yyyy', { locale: enAU });

  const handlePrevDay = () => {
    const prevDay = new Date(anchorDate);
    prevDay.setDate(prevDay.getDate() - 1);
    onDayChange(prevDay);
  };

  const handleNextDay = () => {
    const nextDay = new Date(anchorDate);
    nextDay.setDate(nextDay.getDate() + 1);
    onDayChange(nextDay);
  };

  return (
    <div className={cn('space-y-4', className)} data-testid='calendar-day-view'>
      {/* Day header with navigation */}
      <div className='flex items-center justify-between'>
        <Button
          variant='ghost'
          size='icon'
          onClick={handlePrevDay}
          aria-label='Previous day'
        >
          <ChevronLeft className='h-5 w-5' />
        </Button>

        <h2 className='flex items-center gap-2 text-lg font-semibold'>
          {dayLabel}
          {isTodayDate && (
            <span className='bg-primary text-primary-foreground rounded-full px-2 py-0.5 text-xs font-bold uppercase'>
              Today
            </span>
          )}
        </h2>

        <Button
          variant='ghost'
          size='icon'
          onClick={handleNextDay}
          aria-label='Next day'
        >
          <ChevronRight className='h-5 w-5' />
        </Button>
      </div>

      {isLoading ? (
        <div className='flex flex-col items-center justify-center py-12'>
          <div className='text-muted-foreground'>Loading day...</div>
        </div>
      ) : (
        <ScrollArea className='w-full'>
          <div
            className={cn(
              'group bg-background relative min-h-[500px] rounded-md border p-6 transition-colors',
              onSlotClick && 'hover:bg-muted/10 cursor-pointer'
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
            role='gridcell'
            aria-label={`${dayLabel}, ${dayEvents.length} events`}
            data-testid={`day-view-container`}
          >
            {/* Add Event Button overlay (visible on hover/focus inside the empty area) */}
            {onSlotClick && (
              <div className='absolute top-6 right-6 hidden group-focus-within:block group-hover:block'>
                <Button
                  type='button'
                  variant='secondary'
                  className='shadow-sm'
                  onClick={e => {
                    e.stopPropagation();
                    onSlotClick(dateKey);
                  }}
                  aria-label={`Add event on ${format(anchorDate, 'MMM d')}`}
                >
                  <Plus className='mr-2 h-4 w-4' /> Add Event
                </Button>
              </div>
            )}

            {dayEvents.length === 0 ? (
              <div className='text-muted-foreground pointer-events-none flex h-full items-center justify-center'>
                No events scheduled for this day
              </div>
            ) : (
              <div className='relative z-10 flex max-w-4xl flex-col gap-3 pt-12 sm:pt-0'>
                {dayEvents.map(event => (
                  <CalendarEventPill
                    key={event.id}
                    event={event}
                    variant='day'
                  />
                ))}
              </div>
            )}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
