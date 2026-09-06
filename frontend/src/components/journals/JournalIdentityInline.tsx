/**
 * Journal identity component with inline editing capabilities.
 *
 * Allows users to edit journal title and date range directly inline
 * with optimistic updates and proper error handling.
 */

'use client';

import { useCallback } from 'react';
import { validateRequired } from '@/lib/validation';
import { useUpdateJournal } from '@/lib/api/journals';
import { InlineEditField } from '@/components/contacts/InlineEditField';
import { InlineEditDateRange } from './InlineEditDateRange';
import { JournalType } from '@/types/journals';
import type {
  CalendarInfoData,
  JournalResource,
  EventDateRange,
} from '@/types/journals';

interface JournalIdentityInlineProps {
  readonly journal: JournalResource;
  readonly className?: string;
}

/**
 * Journal identity component with inline editing for title and date range.
 * Displays the journal's title and event date range with click-to-edit functionality.
 */
export function JournalIdentityInline({
  journal,
  className,
}: JournalIdentityInlineProps) {
  const updateJournal = useUpdateJournal();

  // The zone the journal's own bounds are anchored in, when it is an event
  // that records one. The editor needs it to read and write the same days the
  // backend does — see `journalTimezone`.
  const eventTimezone = (
    journal.attributes.type_data?.[JournalType.EVENT] as
      CalendarInfoData | undefined
  )?.timezone;

  // Handle title update
  const handleTitleSave = useCallback(
    async (value: string) => {
      await updateJournal.mutateAsync({
        id: journal.id,
        data: {
          title: value,
        },
      });
    },
    [journal.id, updateJournal]
  );

  // Handle date range update
  const handleDateRangeSave = useCallback(
    async (value: EventDateRange) => {
      await updateJournal.mutateAsync({
        id: journal.id,
        data: {
          event_date_range: value,
        },
      });
    },
    [journal.id, updateJournal]
  );

  return (
    <div className={className}>
      <div className='space-y-3'>
        {/* Title Field */}
        <div>
          <InlineEditField
            value={journal.attributes.title}
            onSave={handleTitleSave}
            validation={validateRequired}
            placeholder='Journal title'
            className='text-3xl font-bold tracking-tight'
            aria-label='Journal title'
            data-testid='journal-title-field'
          />
        </div>

        {/* Date Range Field */}
        <div>
          <InlineEditDateRange
            value={journal.attributes.event_date_range}
            eventTimezone={eventTimezone}
            onSave={handleDateRangeSave}
            aria-label='Event date range'
            data-testid='journal-date-range-field'
          />
        </div>
      </div>
    </div>
  );
}
