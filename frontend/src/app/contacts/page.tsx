/**
 * Contact list page with search and filtering capabilities.
 *
 * Displays a paginated list of contacts with search functionality,
 * tag filtering, and responsive design. Supports URL-based tag filtering
 * via `?tag=<id>` so that sidebar tag clicks open the same list experience.
 */

'use client';

import { Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { Plus, Search, Filter, Users, Tag, X } from 'lucide-react';
import Link from 'next/link';
import {
  getContactPaginationMeta,
  useInfiniteContacts,
  useInfiniteSearchContacts,
  useTags,
} from '@/lib/api/contacts';
import { ContactFilters } from '@/types/contacts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { AuthGuard } from '@/components/auth/AuthGuard';

import { ContactList } from '@/components/contacts/ContactList';
import { useDebounce } from '@/hooks/useDebounce';
import { useDisplayContacts } from '@/hooks/useDisplayContacts';
import { useTagFilter } from '@/hooks/useTagFilter';
import { TIMEOUTS } from '@/lib/constants';

export default function ContactsPage() {
  return (
    <AuthGuard>
      <Suspense>
        <ContactsPageContent />
      </Suspense>
    </AuthGuard>
  );
}

function ContactsPageContent() {
  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useState<ContactFilters>({});
  const [showFilters, setShowFilters] = useState(false);
  const infiniteScrollTriggerRef = useRef<HTMLDivElement | null>(null);

  // Tag filter from URL search params (?tag=<id>)
  const { tagId: activeTagId, clearTag } = useTagFilter();

  // Fetch tags for name resolution when a tag filter is active
  const { data: tagsData } = useTags();
  const activeTagName = useMemo(() => {
    if (!activeTagId || !tagsData?.data) return null;
    const tag = tagsData.data.find(t => t.id === activeTagId);
    return tag?.attributes.name ?? null;
  }, [activeTagId, tagsData]);

  // Debounce search query to avoid excessive API calls
  const debouncedSearchQuery = useDebounce(
    searchQuery,
    TIMEOUTS.DEBOUNCE_SEARCH
  );

  // Merge tag filter from URL into the active filters
  const effectiveFilters = useMemo<ContactFilters>(() => {
    if (activeTagId) {
      return { ...filters, tags: [activeTagId] };
    }
    return filters;
  }, [filters, activeTagId]);

  // Use search query if present, otherwise use regular contact list
  const shouldUseSearch = debouncedSearchQuery.length > 0;

  const {
    data: contactsData,
    isLoading: isLoadingContacts,
    error: contactsError,
    hasNextPage: hasNextContactsPage,
    isFetchingNextPage: isFetchingNextContactsPage,
    fetchNextPage: fetchNextContactsPage,
  } = useInfiniteContacts(effectiveFilters, { enabled: !shouldUseSearch });

  const {
    data: searchData,
    isLoading: isLoadingSearch,
    error: searchError,
    hasNextPage: hasNextSearchPage,
    isFetchingNextPage: isFetchingNextSearchPage,
    fetchNextPage: fetchNextSearchPage,
  } = useInfiniteSearchContacts(
    debouncedSearchQuery,
    // Thread the active tag into the search path so search + tag filtering
    // work together (the search API accepts tag names, not IDs).
    activeTagName ? { tags: [activeTagName] } : {},
    { enabled: shouldUseSearch }
  );

  const data = shouldUseSearch ? searchData : contactsData;
  const isLoading = shouldUseSearch ? isLoadingSearch : isLoadingContacts;
  const error = shouldUseSearch ? searchError : contactsError;
  const hasNextPage = shouldUseSearch ? hasNextSearchPage : hasNextContactsPage;
  const isFetchingNextPage = shouldUseSearch
    ? isFetchingNextSearchPage
    : isFetchingNextContactsPage;
  const fetchNextPage = shouldUseSearch
    ? fetchNextSearchPage
    : fetchNextContactsPage;

  const loadedPages = useMemo(() => data?.pages ?? [], [data]);
  const loadedContacts = useMemo(
    () => loadedPages.flatMap(page => page.data),
    [loadedPages]
  );
  const latestPage =
    loadedPages.length > 0 ? loadedPages[loadedPages.length - 1] : undefined;
  const latestMeta = latestPage?.meta;
  const { totalCount } = getContactPaginationMeta(latestMeta);
  const processingTimeMs =
    typeof latestMeta?.processing_time_ms === 'number'
      ? latestMeta.processing_time_ms
      : undefined;

  const totalContacts =
    totalCount === undefined
      ? loadedContacts.length
      : Math.max(totalCount, loadedContacts.length);
  const contactLabel = totalContacts === 1 ? 'contact' : 'contacts';
  const processingTimeSuffix =
    processingTimeMs === undefined ? '' : ` (${processingTimeMs}ms)`;
  let resultsSummary = `${totalContacts} ${contactLabel} found`;

  if (isLoading) {
    resultsSummary = 'Loading contacts...';
  } else if (shouldUseSearch) {
    resultsSummary = `${resultsSummary} for "${debouncedSearchQuery}"${processingTimeSuffix}`;
  }

  // Use the centralized display contacts hook with search highlighting support
  const displayContacts = useDisplayContacts(loadedContacts, shouldUseSearch);

  useEffect(() => {
    const trigger = infiniteScrollTriggerRef.current;

    if (!trigger || !hasNextPage || isLoading || isFetchingNextPage) {
      return;
    }

    const observer = new IntersectionObserver(entries => {
      const [entry] = entries;

      if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
        fetchNextPage().catch(() => undefined);
      }
    });

    observer.observe(trigger);

    return () => {
      observer.disconnect();
    };
  }, [
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    loadedContacts.length,
  ]);

  const handleSearchChange = (value: string) => {
    setSearchQuery(value);
  };

  const clearSearch = () => {
    setSearchQuery('');
    setFilters({});
    if (activeTagId) {
      clearTag();
    }
  };

  const toggleFavouritesFilter = () => {
    setFilters(prev => ({ ...prev, favourite: !(prev.favourite === true) }));
  };

  const hasActiveFilters =
    searchQuery.length > 0 ||
    Object.keys(filters).length > 0 ||
    activeTagId !== null;

  if (error) {
    return (
      <Alert variant='destructive' data-testid='error-message'>
        <AlertDescription>
          {error instanceof Error ? error.message : 'Failed to load contacts'}
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className='mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between'>
        <div>
          <h1 className='flex items-center gap-2 text-3xl font-bold tracking-tight'>
            {activeTagName ? (
              <>
                <Tag className='h-7 w-7' aria-hidden='true' />
                {activeTagName} Contacts
              </>
            ) : (
              'Contacts'
            )}
          </h1>
          <p className='text-muted-foreground'>
            {activeTagName
              ? `Contacts tagged with "${activeTagName}"`
              : 'Manage your personal and professional contacts'}
          </p>
        </div>
        <Button asChild>
          <Link href='/contacts/new'>
            <Plus className='mr-2 h-4 w-4' />
            Add Contact
          </Link>
        </Button>
      </div>

      {/* Search and Filters */}
      <Card className='mb-6'>
        <CardContent className='pt-6'>
          <div className='flex flex-col gap-4 md:flex-row'>
            <div className='relative flex-1'>
              <Search className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2' />
              <Input
                placeholder='Search contacts...'
                value={searchQuery}
                onChange={e => handleSearchChange(e.target.value)}
                className='pl-10'
                data-testid='search-input'
              />
            </div>
            <div className='flex gap-2'>
              <Button
                variant='outline'
                onClick={() => setShowFilters(!showFilters)}
                className='shrink-0'
              >
                <Filter className='mr-2 h-4 w-4' />
                Filters
              </Button>
              <Button
                variant={filters.favourite ? 'default' : 'outline'}
                onClick={toggleFavouritesFilter}
                className='shrink-0'
                data-testid='favourites-filter'
              >
                Favourites
              </Button>
              {hasActiveFilters && (
                <Button
                  variant='outline'
                  onClick={clearSearch}
                  data-testid='clear-filters'
                >
                  Clear
                </Button>
              )}
            </div>
          </div>

          {showFilters && (
            <div className='mt-4 border-t pt-4'>
              <div className='grid gap-4 md:grid-cols-2'>
                {/* Tag filter would go here */}
                <div>
                  <span className='text-sm font-medium'>Tags</span>
                  <p className='text-muted-foreground text-xs'>
                    Filter by tags (coming soon)
                  </p>
                </div>
                {/* Date filter would go here */}
                <div>
                  <span className='text-sm font-medium'>Date Range</span>
                  <p className='text-muted-foreground text-xs'>
                    Filter by date (coming soon)
                  </p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Active Tag Filter Badge */}
      {activeTagId && (
        <div
          className='mb-4 flex items-center gap-2'
          data-testid='active-tag-filter'
        >
          <Badge
            variant='secondary'
            className='flex items-center gap-1 px-3 py-1'
          >
            <Tag className='h-3 w-3' aria-hidden='true' />
            {activeTagName ?? `Tag ${activeTagId}`}
            <button
              onClick={clearTag}
              className='hover:bg-muted ml-1 rounded-full p-0.5'
              aria-label={`Remove ${activeTagName ?? 'tag'} filter`}
              data-testid='clear-tag-filter'
            >
              <X className='h-3 w-3' />
            </button>
          </Badge>
        </div>
      )}

      {/* Results Summary */}
      <div className='mb-4 flex items-center gap-2'>
        <Users className='text-muted-foreground h-4 w-4' />
        <span className='text-muted-foreground text-sm'>{resultsSummary}</span>
      </div>

      {/* Contact List */}
      {isLoading ? (
        <div className='grid gap-4 md:grid-cols-2 lg:grid-cols-3'>
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className='h-6 w-3/4' />
                <Skeleton className='h-4 w-1/2' />
              </CardHeader>
              <CardContent>
                <div className='space-y-2'>
                  <Skeleton className='h-4 w-full' />
                  <Skeleton className='h-4 w-2/3' />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <>
          <ContactList
            contacts={displayContacts}
            emptyState={
              <Card>
                <CardContent className='pt-6'>
                  <div className='py-8 text-center' data-testid='empty-state'>
                    <Users className='text-muted-foreground mx-auto mb-4 h-12 w-12' />
                    <h3 className='mb-2 text-lg font-semibold'>
                      No contacts found
                    </h3>
                    <p className='text-muted-foreground mb-4'>
                      {searchQuery
                        ? `No contacts match "${searchQuery}"`
                        : 'Get started by adding your first contact'}
                    </p>
                    <Button asChild data-testid='add-contact-button'>
                      <Link href='/contacts/new'>
                        <Plus className='mr-2 h-4 w-4' />
                        Add Contact
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            }
          />

          {(hasNextPage || isFetchingNextPage) &&
            displayContacts.length > 0 && (
              <div
                ref={infiniteScrollTriggerRef}
                className='py-6 text-center'
                data-testid='contacts-infinite-scroll-trigger'
              >
                <span className='text-muted-foreground text-sm'>
                  {isFetchingNextPage
                    ? 'Loading more contacts...'
                    : 'Load more contacts'}
                </span>
              </div>
            )}
        </>
      )}
    </div>
  );
}
