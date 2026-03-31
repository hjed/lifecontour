/**
 * Journal creation page.
 *
 * Provides a form for creating new journal entries.
 * Supports pre-filling parent via ?parentId= query parameter.
 * Protected by authentication guard.
 */

import { Metadata } from 'next';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { JournalCreateForm } from '@/components/journals/JournalCreateForm';

export const metadata: Metadata = {
  title: 'New Journal | Personal Management System',
  description: 'Create a new journal entry',
};

interface NewJournalPageProps {
  searchParams: Promise<{ parentId?: string }>;
}

export default async function NewJournalPage({
  searchParams,
}: NewJournalPageProps) {
  const params = await searchParams;
  const defaultParentId = params.parentId
    ? Number.parseInt(params.parentId, 10)
    : undefined;

  return (
    <AuthGuard>
      <div className='container mx-auto max-w-4xl px-4 py-8'>
        <div className='mb-8'>
          <h1 className='text-3xl font-bold tracking-tight'>
            Create New Journal
          </h1>
          <p className='text-muted-foreground mt-2'>
            Create a new journal entry to record your thoughts, events, and
            memories.
          </p>
        </div>

        <div className='bg-card rounded-lg border p-6'>
          <JournalCreateForm defaultParentId={defaultParentId} />
        </div>
      </div>
    </AuthGuard>
  );
}
