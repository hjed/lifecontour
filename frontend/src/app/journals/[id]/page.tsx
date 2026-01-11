/**
 * Journal detail page
 *
 * Displays a single journal entry with comprehensive detail view
 * including breadcrumb, metadata, content, and children.
 */

'use client';

import { AuthGuard } from '@/components/auth/AuthGuard';
import { JournalDetailView } from '@/components/journals/JournalDetailView';
import { useJournal } from '@/lib/api/journals';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useRouter, useParams } from 'next/navigation';

export default function JournalDetailPage() {
  const router = useRouter();
  const params = useParams();
  const journalId = params.id as string;
  const { data, isLoading, error } = useJournal(journalId);

  // Convert JournalResource to Journal format for JournalDetailView
  const journal = data?.data
    ? {
        id: data.data.id,
        ...data.data.attributes,
      }
    : null;

  return (
    <AuthGuard>
      <div className='container mx-auto max-w-4xl py-6'>
        {/* Back button */}
        <div className='mb-6'>
          <Button
            variant='ghost'
            size='sm'
            onClick={() => router.push('/journals')}
            className='gap-2'
          >
            <ArrowLeft className='h-4 w-4' />
            Back to Journals
          </Button>
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className='space-y-6'>
            <Skeleton className='h-10 w-full' />
            <Skeleton className='h-32 w-full' />
            <Skeleton className='h-64 w-full' />
          </div>
        )}

        {/* Error state */}
        {error && !journal && (
          <Alert variant='destructive'>
            <p>Failed to load journal: {error.message}</p>
          </Alert>
        )}

        {/* Journal detail view */}
        {journal && <JournalDetailView journal={journal} />}
      </div>
    </AuthGuard>
  );
}
