/**
 * Journals page - displays journal entries with filtering
 *
 * Integrates JournalList and JournalFilters components to provide
 * a comprehensive journal browsing experience.
 */

'use client';

import { useState } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DayGroupedJournalList } from '@/components/journals/DayGroupedJournalList';
import { JournalFilters } from '@/components/journals/JournalFilters';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useInfiniteJournals, useSearchJournals } from '@/lib/api/journals';
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
    data: infiniteData,
    isLoading: isInfiniteLoading,
    error: infiniteError,
    fetchNextPage,
    fetchPreviousPage,
    hasNextPage,
    hasPreviousPage,
    isFetchingNextPage,
    isFetchingPreviousPage,
  } = useInfiniteJournals(filters, { enabled: !shouldUseSearch });

  const {
    data: searchData,
    isLoading: isLoadingSearch,
    error: searchError,
  } = useSearchJournals(
    debouncedSearchQuery,
    { types: filters.types },
    { enabled: shouldUseSearch }
  );

  const isLoading = shouldUseSearch ? isLoadingSearch : isInfiniteLoading;
  const error = shouldUseSearch ? searchError : infiniteError;

  let journalsToDisplay = [];
  if (shouldUseSearch) {
    journalsToDisplay = searchData?.data || [];
  } else {
    journalsToDisplay = infiniteData?.pages?.flatMap(page => page.data) || [];
  }

  const totalJournals = shouldUseSearch
    ? searchData?.meta?.total_count || 0
    : journalsToDisplay.length;

  // Use the centralized display journals hook with search highlighting support
  const displayJournals = useDisplayJournals(
    journalsToDisplay,
    shouldUseSearch
  );

  let dateBounds = undefined;
  if (!shouldUseSearch && infiniteData?.pageParams?.length) {
    const validParams = infiniteData.pageParams.filter(Boolean) as {
      date_from: string;
      date_to: string;
    }[];
    if (validParams.length > 0) {
      const minDate = validParams.map(p => p.date_from).sort()[0];
      const maxDate = validParams
        .map(p => p.date_to)
        .sort()
        .reverse()[0];
      dateBounds = { start: minDate, end: maxDate };
    }
  }

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

    const journalCount = `${totalJournals} journal${totalJournals === 1 ? '' : 's'}`;

    if (shouldUseSearch && searchData?.meta) {
      const processingTime = searchData.meta.processing_time_ms
        ? ` (${searchData.meta.processing_time_ms}ms)`
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
          <Button asChild size='sm' className='gap-2'>
            <Link href={'/journals/new' as Route}>
              <Plus className='h-4 w-4' />
              New Journal
            </Link>
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

      <div className='flex flex-col gap-6 md:flex-row'>
        {/* Filters Sidebar */}
        {showFilters && (
          <aside className='w-full flex-shrink-0 md:w-64'>
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
            <DayGroupedJournalList
              journals={displayJournals}
              isLoadingNext={shouldUseSearch ? false : isFetchingNextPage}
              isLoadingPrevious={
                shouldUseSearch ? false : isFetchingPreviousPage
              }
              hasNextPage={shouldUseSearch ? false : hasNextPage}
              hasPreviousPage={shouldUseSearch ? false : hasPreviousPage}
              fetchNextPage={shouldUseSearch ? undefined : fetchNextPage}
              fetchPreviousPage={
                shouldUseSearch ? undefined : fetchPreviousPage
              }
              dateBounds={dateBounds}
              collapseEmptyDays={
                shouldUseSearch || Object.keys(filters).length > 0
              }
              emptyState={
                <Card>
                  <CardContent className='py-12 text-center'>
                    <BookOpen className='text-muted-foreground mx-auto h-12 w-12' />
                    <h3 className='mt-4 text-lg font-semibold'>
                      No journals found
                    </h3>
                    <p className='text-muted-foreground mt-2 text-sm'>
                      {(() => {
                        if (searchQuery)
                          return `No journals match "${searchQuery}"`;
                        if (Object.keys(filters).length > 0)
                          return 'Try adjusting your filters or create a new journal.';
                        return 'Get started by creating your first journal entry.';
                      })()}
                    </p>
                    <Button asChild className='mt-4 gap-2'>
                      <Link href={'/journals/new' as Route}>
                        <Plus className='h-4 w-4' />
                        Create Journal
                      </Link>
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
