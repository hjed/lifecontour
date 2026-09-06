/**
 * Inline edit component for date ranges.
 *
 * Provides click-to-edit functionality for date ranges with a calendar popover.
 * Follows the same pattern as InlineEditField but specialized for date range selection.
 */

'use client';

import { useState, useCallback, useMemo } from 'react';
import { Calendar as CalendarIcon, Check, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  formatDateRange,
  zonedCalendarDay,
  zonedMidnight,
} from '@/lib/date-utils';
import { useJournalTimezone } from '@/lib/api/settings';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import type { EventDateRange } from '@/types/journals';
import type { DateRange } from 'react-day-picker';

export interface InlineEditDateRangeProps {
  /** Current date range value */
  readonly value: EventDateRange;
  /**
   * The zone this journal records for itself, if it is an event that does.
   *
   * Its bounds are read back through it by the backend and the Google sync, so
   * it is the zone they must be written in — see `journalTimezone`. A journal
   * that records none is anchored on the user's own zone instead.
   */
  readonly eventTimezone?: string | null;
  /** Callback when date range is saved */
  readonly onSave: (value: EventDateRange) => Promise<void>;
  /** Whether the field is disabled */
  readonly disabled?: boolean;
  /** Additional CSS classes */
  readonly className?: string;
  /** Test ID for testing */
  readonly 'data-testid'?: string;
  /** ARIA label for accessibility */
  readonly 'aria-label'?: string;
}

/**
 * Inline edit component for date ranges with calendar picker.
 */
export function InlineEditDateRange({
  value,
  eventTimezone,
  onSave,
  disabled = false,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
}: InlineEditDateRangeProps) {
  // Every day this component resolves, shows or writes is anchored on the same
  // zone: the journal's own if it records one, else the user's configured one.
  // They only have to agree with *each other* for an untouched range to round-
  // trip, and the browser's zone cannot play that part — it changes when the
  // user travels, and it is simply not what an event imported from a
  // foreign-zone calendar is anchored in (issue #1401).
  const { timezone, userTimezone } = useJournalTimezone(eventTimezone);

  // A date shown in a zone the user does not read dates in is ambiguous — the
  // event's 15 January is not necessarily theirs — so the zone is named rather
  // than left to be inferred. When it is their own zone there is nothing to
  // disclose.
  const foreignZone = timezone === userTimezone ? null : timezone;

  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The stored bounds as calendar days in the current zone. Derived rather
  // than held in state, because `timezone` changes underneath this component:
  // the settings read has not landed on the first render, so the editor starts
  // on the browser's zone and switches when it does. State seeded once would
  // keep the days the *old* zone resolved and then let the save anchor them
  // with the new one — a mismatch between read and write zone, which is the
  // whole defect this component was changed to remove.
  const opened = useMemo(
    () => ({
      from: zonedCalendarDay(value.start, timezone),
      to: zonedCalendarDay(value.end, timezone),
    }),
    [value.start, value.end, timezone]
  );

  // Only the user's own selection is state, and it wins while it exists. A day
  // they picked is a day they picked: it needs no re-resolving when the zone
  // arrives, it just gets written in that zone.
  const [selected, setSelected] = useState<DateRange | undefined>(undefined);
  const dateRange = selected ?? opened;

  // Labelled from the resolved days rather than the raw bounds, so the button
  // names the day the picker will open on and the day a save will write.
  const displayValue = formatDateRange(opened.from, opened.to);

  const startEdit = useCallback(() => {
    if (disabled) return;
    setIsEditing(true);
    setError(null);
    setSelected(undefined);
  }, [disabled]);

  const cancelEdit = useCallback(() => {
    setIsEditing(false);
    setError(null);
    setSelected(undefined);
  }, []);

  const saveEdit = useCallback(async () => {
    if (!dateRange?.from || !dateRange?.to) {
      setError('Please select both start and end dates');
      return;
    }

    // Validate that start is before or equal to end
    if (dateRange.from > dateRange.to) {
      setError('Start date must be before or equal to end date');
      return;
    }

    setIsLoading(true);
    setError(null);

    // The backend stores each bound as the UTC instant of midnight on its day
    // in the user's zone, and the end is the last day inclusive — the same
    // thing JournalCreateForm sends. `zonedMidnight` is the inverse of the
    // `zonedCalendarDay` the picker was opened with, so a range nobody touched
    // is written back as the instant it arrived as.
    const newValue: EventDateRange = {
      start: zonedMidnight(dateRange.from, timezone).toISOString(),
      end: zonedMidnight(dateRange.to, timezone).toISOString(),
    };

    try {
      await onSave(newValue);
      setIsEditing(false);
    } catch (saveError) {
      const errorMessage =
        saveError instanceof Error
          ? saveError.message
          : 'Failed to save date range';
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  }, [dateRange, onSave, timezone]);

  // Named the same way in both modes, and carried inside the control rather
  // than beside it so it travels with the date it qualifies.
  const timezoneLabel = foreignZone && (
    <span
      className='text-muted-foreground text-xs'
      data-testid='date-range-timezone'
    >
      {foreignZone}
    </span>
  );

  // View mode - clickable display
  if (!isEditing) {
    return (
      <button
        type='button'
        className={cn(
          'inline-flex items-center gap-2 rounded-md px-2 py-1 text-sm transition-colors',
          'hover:bg-muted focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none',
          disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
          className
        )}
        disabled={disabled}
        onClick={startEdit}
        aria-label={
          ariaLabel ||
          `Click to edit date range: ${displayValue}${
            foreignZone ? ` (${foreignZone})` : ''
          }`
        }
        data-testid={testId}
      >
        <CalendarIcon
          className='text-muted-foreground h-4 w-4'
          aria-hidden='true'
        />
        <span>{displayValue}</span>
        {timezoneLabel}
      </button>
    );
  }

  // Edit mode - calendar popover
  return (
    <div
      className={cn('inline-flex items-center gap-2', className)}
      data-testid={testId}
    >
      <Popover open={isEditing} modal={false}>
        <PopoverTrigger asChild>
          <Button
            variant='outline'
            className={cn(
              'justify-start text-left font-normal',
              !dateRange && 'text-muted-foreground'
            )}
            disabled={isLoading}
          >
            <CalendarIcon className='mr-2 h-4 w-4' />
            {dateRange?.from && dateRange?.to
              ? formatDateRange(dateRange.from, dateRange.to)
              : 'Select date range'}
            {timezoneLabel && <span className='ml-2'>{timezoneLabel}</span>}
          </Button>
        </PopoverTrigger>
        <PopoverContent className='w-auto p-0' align='start'>
          <Calendar
            mode='range'
            selected={dateRange}
            onSelect={setSelected}
            numberOfMonths={2}
            disabled={isLoading}
          />
        </PopoverContent>
      </Popover>

      {/* Action buttons */}
      <Button
        size='sm'
        variant='ghost'
        onClick={saveEdit}
        disabled={isLoading || !dateRange?.from || !dateRange?.to}
        aria-label='Save date range'
        data-testid={`${testId}-save`}
      >
        <Check className='h-4 w-4' />
      </Button>
      <Button
        size='sm'
        variant='ghost'
        onClick={cancelEdit}
        disabled={isLoading}
        aria-label='Cancel editing'
        data-testid={`${testId}-cancel`}
      >
        <X className='h-4 w-4' />
      </Button>

      {/* Error message */}
      {error && (
        <span className='text-destructive text-sm' role='alert'>
          {error}
        </span>
      )}
    </div>
  );
}
