/**
 * JournalFilters component for filtering journal entries.
 *
 * Provides comprehensive filtering options including date range, types,
 * contacts, tags, and calendar selection.
 */

'use client';

import { useState } from 'react';
import { Calendar as CalendarIcon, X } from 'lucide-react';
import { format } from 'date-fns';
import { enAU } from 'date-fns/locale';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
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
import { ContactSearchCombobox } from '@/components/contacts/ContactSearchCombobox';
import {
  JournalFilters as JournalFiltersType,
  JournalType,
} from '@/types/journals';
import { ContactResource } from '@/types/contacts';
import { useJournalTags, useCalendars } from '@/lib/api/journals';
import { cn } from '@/lib/utils';
import type { DateRange } from 'react-day-picker';

interface JournalFiltersProps {
  readonly filters: JournalFiltersType;
  readonly onFiltersChange: (filters: JournalFiltersType) => void;
  readonly className?: string;
}

// Journal type labels
const JOURNAL_TYPE_LABELS: Record<JournalType, string> = {
  [JournalType.NOTE]: 'Note',
  [JournalType.EVENT]: 'Event',
  [JournalType.MOOD_RATING]: 'Mood Rating',
  [JournalType.PLAN]: 'Plan',
  [JournalType.TRAVEL]: 'Travel',
  [JournalType.PHOTO_ALBUM]: 'Photo Album',
  [JournalType.FITNESS]: 'Fitness',
  [JournalType.OUTDOOR_ACTIVITY]: 'Outdoor Activity',
  [JournalType.BUSHWALKING]: 'Bushwalking',
  [JournalType.JOGGING]: 'Jogging',
  [JournalType.ABSEILING_TRIP]: 'Abseiling Trip',
  [JournalType.CANYONING]: 'Canyoning',
  [JournalType.CAVING]: 'Caving',
  [JournalType.CANOEING]: 'Canoeing',
  [JournalType.CLIMBING]: 'Climbing',
  [JournalType.KAYAKING]: 'Kayaking',
  [JournalType.CROSS_COUNTRY_SKIING]: 'Cross-Country Skiing',
  [JournalType.SNORKELLING]: 'Snorkelling',
  [JournalType.DIVING]: 'Diving',
  [JournalType.DOWNHILL_SKIING]: 'Downhill Skiing',
  [JournalType.OUTDOOR_PLANNING]: 'Outdoor Planning',
  [JournalType.OUTDOOR_TRAINING]: 'Outdoor Training',
  [JournalType.GEAR_MAINTENANCE]: 'Gear Maintenance',
  [JournalType.GEAR_USAGE]: 'Gear Usage',
};

/**
 * JournalFilters component provides a comprehensive filter panel
 */
export function JournalFilters({
  filters,
  onFiltersChange,
  className,
}: JournalFiltersProps) {
  const { data: tagsData } = useJournalTags();
  const tags = tagsData?.data || [];

  const { data: calendarsData } = useCalendars();
  const calendars = calendarsData?.data || [];

  // Date range state
  const [dateRange, setDateRange] = useState<DateRange | undefined>(() => {
    if (filters.date_from && filters.date_to) {
      return {
        from: new Date(filters.date_from),
        to: new Date(filters.date_to),
      };
    }
    return undefined;
  });

  // Handle type toggle
  const handleTypeToggle = (type: JournalType) => {
    const currentTypes = filters.types || [];
    const newTypes = currentTypes.includes(type)
      ? currentTypes.filter(t => t !== type)
      : [...currentTypes, type];

    onFiltersChange({
      ...filters,
      types: newTypes.length > 0 ? newTypes : undefined,
    });
  };

  // Handle tag toggle
  const handleTagToggle = (tagId: string) => {
    const currentTags = filters.tag_ids || [];
    const newTags = currentTags.includes(tagId)
      ? currentTags.filter(t => t !== tagId)
      : [...currentTags, tagId];

    onFiltersChange({
      ...filters,
      tag_ids: newTags.length > 0 ? newTags : undefined,
    });
  };

  // Handle contact selection
  const handleContactSelect = (contact: ContactResource) => {
    onFiltersChange({
      ...filters,
      contact_id: contact.id,
    });
  };

  // Handle contact clear
  const handleContactClear = () => {
    onFiltersChange({
      ...filters,
      contact_id: undefined,
    });
  };

  // Handle date range change
  const handleDateRangeChange = (range: DateRange | undefined) => {
    setDateRange(range);
    if (range?.from && range?.to) {
      onFiltersChange({
        ...filters,
        date_from: format(range.from, 'yyyy-MM-dd'),
        date_to: format(range.to, 'yyyy-MM-dd'),
      });
    } else {
      onFiltersChange({
        ...filters,
        date_from: undefined,
        date_to: undefined,
      });
    }
  };

  // Handle calendar selection
  const handleCalendarChange = (calendarId: string) => {
    onFiltersChange({
      ...filters,
      calendar_id: calendarId === 'all' ? undefined : calendarId,
    });
  };

  // Clear all filters
  const handleClearAll = () => {
    setDateRange(undefined);
    onFiltersChange({});
  };

  // Format date range for display
  const getDateRangeDisplay = () => {
    if (!dateRange?.from) {
      return <span>Pick a date range</span>;
    }

    if (dateRange.to) {
      return (
        <>
          {format(dateRange.from, 'dd MMM yyyy', { locale: enAU })} -{' '}
          {format(dateRange.to, 'dd MMM yyyy', { locale: enAU })}
        </>
      );
    }

    return format(dateRange.from, 'dd MMM yyyy', { locale: enAU });
  };

  const hasActiveFilters =
    (filters.types && filters.types.length > 0) ||
    (filters.tag_ids && filters.tag_ids.length > 0) ||
    filters.contact_id ||
    filters.date_from ||
    filters.date_to ||
    filters.calendar_id;

  return (
    <div className={cn('space-y-4', className)} data-testid='journal-filters'>
      {/* Date Range Filter */}
      <div className='space-y-2'>
        <Label>Date Range</Label>
        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant='outline'
              className={cn(
                'w-full justify-start text-left font-normal',
                !dateRange && 'text-muted-foreground'
              )}
              data-testid='journal-date-range-trigger'
            >
              <CalendarIcon className='mr-2 h-4 w-4' />
              {getDateRangeDisplay()}
            </Button>
          </PopoverTrigger>
          <PopoverContent className='w-auto p-0' align='start'>
            <Calendar
              mode='range'
              selected={dateRange}
              onSelect={handleDateRangeChange}
              numberOfMonths={2}
              locale={enAU}
            />
          </PopoverContent>
        </Popover>
      </div>

      {/* Journal Types Filter */}
      <div className='space-y-2'>
        <Label>Journal Types</Label>
        <div className='space-y-2'>
          {Object.values(JournalType).map(type => (
            <div key={type} className='flex items-center space-x-2'>
              <Checkbox
                id={`type-${type}`}
                checked={filters.types?.includes(type) || false}
                onCheckedChange={() => handleTypeToggle(type)}
              />
              <label
                htmlFor={`type-${type}`}
                className='text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
              >
                {JOURNAL_TYPE_LABELS[type]}
              </label>
            </div>
          ))}
        </div>
      </div>

      {/* Contact Filter */}
      <div className='space-y-2'>
        <Label>Contact</Label>
        {filters.contact_id ? (
          <div className='flex items-center gap-2'>
            <span className='text-sm'>Contact selected</span>
            <Button
              variant='ghost'
              size='sm'
              onClick={handleContactClear}
              aria-label='Clear contact filter'
            >
              <X className='h-4 w-4' />
            </Button>
          </div>
        ) : (
          <ContactSearchCombobox
            onSelect={handleContactSelect}
            placeholder='Search for a contact...'
          />
        )}
      </div>

      {/* Tags Filter */}
      {tags.length > 0 && (
        <div className='space-y-2'>
          <Label>Tags</Label>
          <div className='max-h-48 space-y-2 overflow-y-auto'>
            {tags.map(tag => (
              <div key={tag.id} className='flex items-center space-x-2'>
                <Checkbox
                  id={`tag-${tag.id}`}
                  checked={filters.tag_ids?.includes(tag.id) || false}
                  onCheckedChange={() => handleTagToggle(tag.id)}
                />
                <label
                  htmlFor={`tag-${tag.id}`}
                  className='text-sm leading-none font-medium peer-disabled:cursor-not-allowed peer-disabled:opacity-70'
                >
                  {tag.name}
                </label>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Calendar Filter */}
      <div className='space-y-2'>
        <Label htmlFor='calendar-filter'>Calendar</Label>
        <Select
          value={filters.calendar_id || 'all'}
          onValueChange={handleCalendarChange}
        >
          <SelectTrigger id='calendar-filter' aria-label='Calendar filter'>
            <SelectValue placeholder='All calendars' />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>All calendars</SelectItem>
            {calendars.map(calendar => (
              <SelectItem key={calendar.id} value={calendar.id}>
                {calendar.attributes.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Clear Filters Button */}
      {hasActiveFilters && (
        <Button
          variant='outline'
          onClick={handleClearAll}
          className='w-full'
          data-testid='clear-filters'
        >
          Clear All Filters
        </Button>
      )}
    </div>
  );
}
