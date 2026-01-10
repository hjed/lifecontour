/**
 * Journals page - displays journal entries with filtering
 *
 * Integrates JournalList and JournalFilters components to provide
 * a comprehensive journal browsing experience.
 */

'use client';

import { useState } from 'react';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { JournalList } from '@/components/journals/JournalList';
import { JournalFilters } from '@/components/journals/JournalFilters';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useJournals } from '@/lib/api/journals';
import { JournalFilters as JournalFiltersType } from '@/types/journals';
import { BookOpen, Filter, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function JournalsPage() {
  const [filters, setFilters] = useState<JournalFiltersType>({});
  const [showFilters, setShowFilters] = useState(true);

  // Fetch journals with filters
  const { data, isLoading, error } = useJournals(filters);
  const journals = data?.data || [];

  return (
    <AuthGuard>
      <div className='mb-6 flex items-center justify-between'>
        <div>
          <h1 className='text-3xl font-bold tracking-tight'>Journals</h1>
          <p className='text-muted-foreground'>
            Your journal entries and memories.
          </p>
        </div>
        <div className='flex gap-2'>
          <Button
            variant='outline'
            size='sm'
            onClick={() => setShowFilters(!showFilters)}
            className='gap-2'
          >
            <Filter className='h-4 w-4' />
            {showFilters ? 'Hide' : 'Show'} Filters
          </Button>
          <Button size='sm' className='gap-2' disabled title='Coming soon'>
            <Plus className='h-4 w-4' />
            New Journal
          </Button>
        </div>
      </div>

      <div className='flex gap-6'>
        {/* Filters Sidebar */}
        {showFilters && (
          <aside className='w-64 flex-shrink-0'>
            <Card>
              <CardContent className='pt-6'>
                <JournalFilters
                  filters={filters}
                  onFiltersChange={setFilters}
                />
              </CardContent>
            </Card>
          </aside>
        )}

        {/* Main Content */}
        <main className={cn('flex-1', !showFilters && 'w-full')}>
          {isLoading && (
            <div className='flex items-center justify-center py-12'>
              <div className='text-muted-foreground'>Loading journals...</div>
            </div>
          )}
          {!isLoading && error && (
            <Card>
              <CardContent className='py-12 text-center'>
                <p className='text-destructive'>
                  Failed to load journals. Please try again.
                </p>
              </CardContent>
            </Card>
          )}
          {!isLoading && !error && (
            <JournalList
              journals={journals}
              emptyState={
                <Card>
                  <CardContent className='py-12 text-center'>
                    <BookOpen className='text-muted-foreground mx-auto h-12 w-12' />
                    <h3 className='mt-4 text-lg font-semibold'>
                      No journals found
                    </h3>
                    <p className='text-muted-foreground mt-2 text-sm'>
                      {Object.keys(filters).length > 0
                        ? 'Try adjusting your filters or create a new journal.'
                        : 'Get started by creating your first journal entry.'}
                    </p>
                    <Button className='mt-4 gap-2' disabled title='Coming soon'>
                      <Plus className='h-4 w-4' />
                      Create Journal
                    </Button>
                  </CardContent>
                </Card>
              }
            />
          )}
        </main>
      </div>
    </AuthGuard>
  );
}
