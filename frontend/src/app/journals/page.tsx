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
import { Input } from '@/components/ui/input';
import { useJournals, useSearchJournals } from '@/lib/api/journals';
import { useDebounce } from '@/hooks/useDebounce';
import { useDisplayJournals } from '@/hooks/useDisplayJournals';
import { JournalFilters as JournalFiltersType } from '@/types/journals';
import { BookOpen, Filter, Plus, Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { TIMEOUTS } from '@/lib/constants';

export default function JournalsPage() {
  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useState<JournalFiltersType>({});
  const [showFilters, setShowFilters] = useState(true);

  // Debounce search query to avoid excessive API calls
  const debouncedSearchQuery = useDebounce(
    searchQuery,
    TIMEOUTS.DEBOUNCE_SEARCH
  );

  // Use search query if present, otherwise use regular journal list
  const shouldUseSearch = debouncedSearchQuery.length > 0;

  const {
    data: journalsData,
    isLoading: isLoadingJournals,
    error: journalsError,
  } = useJournals(filters, { enabled: !shouldUseSearch });

  const {
    data: searchData,
    isLoading: isLoadingSearch,
    error: searchError,
  } = useSearchJournals(
    debouncedSearchQuery,
    { types: filters.types },
    { enabled: shouldUseSearch }
  );

  const data = shouldUseSearch ? searchData : journalsData;
  const isLoading = shouldUseSearch ? isLoadingSearch : isLoadingJournals;
  const error = shouldUseSearch ? searchError : journalsError;

  const totalJournals = data?.meta?.total_count || 0;

  // Use the centralized display journals hook with search highlighting support
  const displayJournals = useDisplayJournals(data?.data, shouldUseSearch);

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
  };

  const clearSearch = () => {
    setSearchQuery('');
    setFilters({});
  };

  // Generate results summary text
  const getResultsSummary = () => {
    if (isLoading) {
      return 'Loading journals...';
    }

    const journalCount = `${totalJournals} journal${totalJournals !== 1 ? 's' : ''}`;

    if (shouldUseSearch) {
      const processingTime = data?.meta?.processing_time_ms
        ? ` (${data.meta.processing_time_ms}ms)`
        : '';
      return `${journalCount} found for "${debouncedSearchQuery}"${processingTime}`;
    }

    return `${journalCount} found`;
  };

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

      {/* Search Bar */}
      <Card className='mb-6'>
        <CardContent className='pt-6'>
          <div className='flex flex-col gap-4 md:flex-row'>
            <div className='relative flex-1'>
              <Search className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2' />
              <Input
                placeholder='Search journals...'
                value={searchQuery}
                onChange={e => handleSearchChange(e.target.value)}
                className='pl-10'
                data-testid='search-input'
              />
            </div>
            {(searchQuery || Object.keys(filters).length > 0) && (
              <Button
                variant='outline'
                onClick={clearSearch}
                data-testid='clear-filters'
              >
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results Summary */}
      <div className='mb-4 flex items-center gap-2'>
        <BookOpen className='text-muted-foreground h-4 w-4' />
        <span className='text-muted-foreground text-sm'>
          {getResultsSummary()}
        </span>
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
              journals={displayJournals}
              emptyState={
                <Card>
                  <CardContent className='py-12 text-center'>
                    <BookOpen className='text-muted-foreground mx-auto h-12 w-12' />
                    <h3 className='mt-4 text-lg font-semibold'>
                      No journals found
                    </h3>
                    <p className='text-muted-foreground mt-2 text-sm'>
                      {searchQuery
                        ? `No journals match "${searchQuery}"`
                        : Object.keys(filters).length > 0
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
