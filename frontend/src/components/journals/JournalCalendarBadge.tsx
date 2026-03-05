/**
 * JournalCalendarBadge component for displaying and editing calendar assignment.
 *
 * Shows the calendar name with a color indicator. For EVENT type journals,
 * allows inline editing to change the calendar assignment.
 */

'use client';

import { useState } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Settings } from 'lucide-react';
import Link from 'next/link';
import type { Route } from 'next';
import { cn } from '@/lib/utils';
import { JournalType, type JournalCalendar } from '@/types/journals';

interface JournalCalendarBadgeProps {
  readonly calendar?: JournalCalendar | null;
  readonly journalTypes: JournalType[];
  readonly onCalendarChange?: (calendarId: string) => Promise<void>;
  readonly availableCalendars?: JournalCalendar[];
  readonly disabled?: boolean;
  readonly className?: string;
}

/**
 * Renders a calendar select dropdown with color indicators.
 */
function CalendarSelect({
  value,
  availableCalendars,
  onValueChange,
  disabled,
  placeholder,
  selectId,
}: {
  readonly value?: string;
  readonly availableCalendars: JournalCalendar[];
  readonly onValueChange: (value: string) => void;
  readonly disabled: boolean;
  readonly placeholder?: string;
  readonly selectId: string;
}) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger id={selectId} data-testid='calendar-select'>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {availableCalendars.map(cal => (
          <SelectItem key={cal.id} value={cal.id}>
            <div className='flex items-center gap-2'>
              <div
                className='h-3 w-3 rounded-full'
                style={{ backgroundColor: cal.color || '#6b7280' }}
                aria-hidden='true'
              />
              <span>{cal.name}</span>
            </div>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Calendar badge component with inline editing for EVENT type journals.
 * Displays calendar name with color indicator.
 */
export function JournalCalendarBadge({
  calendar,
  journalTypes,
  onCalendarChange,
  availableCalendars = [],
  disabled = false,
  className,
}: JournalCalendarBadgeProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Only allow editing for EVENT type journals
  const isEventJournal = journalTypes.includes(JournalType.EVENT);
  const canEdit = isEventJournal && !disabled && onCalendarChange;

  const handleCalendarChange = async (calendarId: string) => {
    if (!onCalendarChange) return;

    setIsLoading(true);
    try {
      await onCalendarChange(calendarId);
      setIsOpen(false);
    } catch (error) {
      console.error('Failed to update calendar:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // If no calendar assigned
  if (!calendar) {
    if (!canEdit) {
      return null; // Don't show anything if no calendar and can't edit
    }

    return (
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <PopoverTrigger asChild>
          <Button
            variant='outline'
            size='sm'
            className={cn('h-6 gap-1 text-xs', className)}
            disabled={disabled}
            data-testid='add-calendar-button'
          >
            <CalendarIcon className='h-3 w-3' />
            Add Calendar
          </Button>
        </PopoverTrigger>
        <PopoverContent className='w-64 p-3' align='start'>
          <div className='space-y-2'>
            <label htmlFor='calendar-select' className='text-sm font-medium'>
              Select Calendar
            </label>
            <CalendarSelect
              availableCalendars={availableCalendars}
              onValueChange={handleCalendarChange}
              disabled={isLoading}
              placeholder='Choose a calendar'
              selectId='calendar-select'
            />
            <div className='mt-2 border-t pt-2'>
              <Link
                href={'/settings' as Route}
                className='text-muted-foreground hover:text-foreground flex items-center text-xs'
              >
                <Settings className='mr-1 h-3 w-3' />
                Manage Calendars
              </Link>
            </div>
          </div>
        </PopoverContent>
      </Popover>
    );
  }

  // Calendar is assigned
  const badgeContent = (
    <Badge
      variant='secondary'
      className={cn('gap-1.5 text-xs', className)}
      data-testid='calendar-badge'
    >
      <div
        className='h-2.5 w-2.5 rounded-full'
        style={{ backgroundColor: calendar.color || '#6b7280' }}
        aria-hidden='true'
      />
      <CalendarIcon className='h-3 w-3' />
      <span>{calendar.name}</span>
    </Badge>
  );

  // If can't edit, just show the badge
  if (!canEdit) {
    return badgeContent;
  }

  // Editable badge with popover
  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          type='button'
          className='cursor-pointer transition-opacity hover:opacity-80'
          disabled={disabled}
          data-testid='calendar-badge-trigger'
        >
          {badgeContent}
        </button>
      </PopoverTrigger>
      <PopoverContent className='w-64 p-3' align='start'>
        <div className='space-y-2'>
          <label htmlFor='calendar-select-edit' className='text-sm font-medium'>
            Change Calendar
          </label>
          <CalendarSelect
            value={calendar.id}
            availableCalendars={availableCalendars}
            onValueChange={handleCalendarChange}
            disabled={isLoading}
            selectId='calendar-select-edit'
          />
          <div className='mt-2 border-t pt-2'>
            <Link
              href={'/settings' as Route}
              className='text-muted-foreground hover:text-foreground flex items-center text-xs'
            >
              <Settings className='mr-1 h-3 w-3' />
              Manage Calendars
            </Link>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
