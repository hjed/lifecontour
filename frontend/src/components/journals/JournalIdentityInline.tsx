/**
 * Journal identity component with inline editing capabilities.
 *
 * Allows users to edit journal title and date range directly inline
 * with optimistic updates and proper error handling.
 */

'use client';

import { useCallback } from 'react';
import { validateRequired } from '@/lib/validation';
import { useUpdateJournalField } from '@/lib/api/journals';
import { InlineEditField } from '@/components/contacts/InlineEditField';
import { InlineEditDateRange } from './InlineEditDateRange';
import type { JournalResource, EventDateRange } from '@/types/journals';

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
  const updateFieldMutation = useUpdateJournalField();

  // Handle title update
  const handleTitleSave = useCallback(
    async (value: string) => {
      await updateFieldMutation.mutateAsync({
        journalId: journal.id,
        fieldName: 'title',
        value,
      });
    },
    [journal.id, updateFieldMutation]
  );

  // Handle date range update
  const handleDateRangeSave = useCallback(
    async (value: EventDateRange) => {
      await updateFieldMutation.mutateAsync({
        journalId: journal.id,
        fieldName: 'event_date_range',
        value,
      });
    },
    [journal.id, updateFieldMutation]
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
            onSave={handleDateRangeSave}
            aria-label='Event date range'
            data-testid='journal-date-range-field'
          />
        </div>
      </div>
    </div>
  );
}
