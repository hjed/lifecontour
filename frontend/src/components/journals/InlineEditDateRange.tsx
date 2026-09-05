/**
 * Inline edit component for date ranges.
 *
 * Provides click-to-edit functionality for date ranges with a calendar popover.
 * Follows the same pattern as InlineEditField but specialized for date range selection.
 */

'use client';

import { useState, useCallback } from 'react';
import { Calendar as CalendarIcon, Check, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatDateRange, localMidnight } from '@/lib/date-utils';
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
  onSave,
  disabled = false,
  className,
  'data-testid': testId,
  'aria-label': ariaLabel,
}: InlineEditDateRangeProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<DateRange | undefined>(() => ({
    from: new Date(value.start),
    to: new Date(value.end),
  }));

  const displayValue = formatDateRange(value.start, value.end);

  const startEdit = useCallback(() => {
    if (disabled) return;
    setIsEditing(true);
    setError(null);
    setDateRange({
      from: new Date(value.start),
      to: new Date(value.end),
    });
  }, [disabled, value]);

  const cancelEdit = useCallback(() => {
    setIsEditing(false);
    setError(null);
    setDateRange({
      from: new Date(value.start),
      to: new Date(value.end),
    });
  }, [value]);

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

    // The backend stores each bound as the UTC instant of *local* midnight, and
    // the end is the last day inclusive — the same thing JournalCreateForm
    // sends. Zeroing the UTC clock instead would write a different instant from
    // a created journal's, one that reads back a day early behind UTC.
    const newValue: EventDateRange = {
      start: localMidnight(dateRange.from).toISOString(),
      end: localMidnight(dateRange.to).toISOString(),
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
  }, [dateRange, onSave]);

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
        aria-label={ariaLabel || `Click to edit date range: ${displayValue}`}
        data-testid={testId}
      >
        <CalendarIcon
          className='text-muted-foreground h-4 w-4'
          aria-hidden='true'
        />
        <span>{displayValue}</span>
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
          </Button>
        </PopoverTrigger>
        <PopoverContent className='w-auto p-0' align='start'>
          <Calendar
            mode='range'
            selected={dateRange}
            onSelect={setDateRange}
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
