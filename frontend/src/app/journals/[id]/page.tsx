/**
 * Journal detail page
 *
 * Displays a single journal entry with inline editing capabilities.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { JournalDetail } from '@/components/journals/JournalDetail';
import { useJournal } from '@/lib/api/journals';

interface JournalDetailPageProps {
  params: {
    id: string;
  };
}

export default function JournalDetailPage({ params }: JournalDetailPageProps) {
  const { data, isLoading, error } = useJournal(params.id);

  // Create a placeholder journal for loading/error states
  const placeholderJournal = {
    type: 'journals' as const,
    id: params.id,
    attributes: {
      title: '',
      content: '',
      event_date_range: { start: '', end: '' },
      types: [],
      type_data: {},
      contacts: [],
      tags: [],
      calendar: null,
      parent: null,
      children_count: 0,
      created_at: null,
      updated_at: null,
    },
  };

  return (
    <AuthGuard>
      <div className='container mx-auto max-w-4xl py-6'>
        {data?.data && (
          <JournalDetail
            journal={data.data}
            isLoading={isLoading}
            // Only show error if there's no cached data to display
            error={null}
          />
        )}
        {isLoading && !data && (
          <JournalDetail journal={placeholderJournal} isLoading={true} />
        )}
        {error && !data && (
          <JournalDetail journal={placeholderJournal} error={error} />
        )}
      </div>
    </AuthGuard>
  );
}
