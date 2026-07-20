/**
 * Journals page - displays journal entries with filtering
 *
 * Integrates JournalList, JournalFilters, and calendar view components
 * to provide a comprehensive journal browsing experience.
 * Supports List (default), Month, and Agenda view modes.
 * Supports URL-based tag filtering via `?tag=<id>` so that tag links open the
 * same list experience, matching `/contacts?tag=<id>`.
 */

'use client';

import { Suspense, useState, useMemo, useEffect, useCallback } from 'react';
import Link from 'next/link';
import type { Route } from 'next';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { DayGroupedJournalList } from '@/components/journals/DayGroupedJournalList';
import { JournalFilters } from '@/components/journals/JournalFilters';
import { LogbookExportDialog } from '@/components/journals/LogbookExportDialog';
import {
  CalendarViewToggle,
  CalendarViewMode,
} from '@/components/journals/CalendarViewToggle';
import { CalendarMonthView } from '@/components/journals/CalendarMonthView';
import { CalendarAgendaView } from '@/components/journals/CalendarAgendaView';
import { CalendarWeekView } from '@/components/journals/CalendarWeekView';
import { CalendarDayView } from '@/components/journals/CalendarDayView';
import { CalendarQuickCreateDialog } from '@/components/journals/CalendarQuickCreateDialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  useInfiniteJournals,
  useJournals,
  useJournalTags,
  useSearchJournals,
  useReviewItems,
} from '@/lib/api/journals';
import { useDebounce } from '@/hooks/useDebounce';
import { useTagFilter } from '@/hooks/useTagFilter';
import { useDisplayJournals } from '@/hooks/useDisplayJournals';
import { JournalFilters as JournalFiltersType } from '@/types/journals';
import {
  toCalendarEvents,
  getMonthDateRange,
  getAgendaDateRange,
  getWeekDateRange,
  getDayDateRange,
} from '@/lib/calendarEventHelpers';
import {
  BookOpen,
  Filter,
  Plus,
  Search,
  FileText,
  CalendarIcon,
  Download,
  Tag,
  X,
} from 'lucide-react';
import { format, parseISO } from 'date-fns';
import { Calendar } from '@/components/ui/calendar';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { TIMEOUTS } from '@/lib/constants';
import { InfiniteData } from '@tanstack/react-query';
import { ReviewQueueSidebar } from '@/components/journals/ReviewQueueSidebar';

function getDateBounds(
  infiniteData: InfiniteData<unknown, unknown> | undefined
) {
  if (!infiniteData?.pageParams?.length) return undefined;

  const validParams = infiniteData.pageParams.filter(
    (p): p is { date_from: string; date_to: string } =>
      Boolean(p && typeof p === 'object' && 'date_from' in p && 'date_to' in p)
  );

  if (validParams.length === 0) return undefined;

  const minDate = validParams
    .map(p => p.date_from)
    .sort((a, b) => a.localeCompare(b))[0];
  const maxDate = validParams
    .map(p => p.date_to)
    .sort((a, b) => b.localeCompare(a))[0];

  return { start: minDate, end: maxDate };
}

function getEmptyStateMessage(searchQuery: string, hasFilters: boolean) {
  if (searchQuery) return `No journals match "${searchQuery}"`;
  if (hasFilters) return 'Try adjusting your filters or create a new journal.';
  return 'Get started by creating your first journal entry.';
}

/**
 * Strip keys whose value is `undefined`.
 *
 * `JournalFilters` clears a filter by setting its key to `undefined` rather
 * than deleting it, so the key survives the spread. Any check of the form
 * `Object.keys(filters).length > 0` would then read a cleared filter as an
 * active one.
 */
function withoutClearedFilters(
  filters: JournalFiltersType
): JournalFiltersType {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined)
  ) as JournalFiltersType;
}

export default function JournalsPage() {
  return (
    <AuthGuard>
      <Suspense>
        <JournalsPageContent />
      </Suspense>
    </AuthGuard>
  );
}

function JournalsPageContent() {
  const [searchQuery, setSearchQuery] = useState('');
  const [filters, setFilters] = useState<JournalFiltersType>({});
  const [showFilters, setShowFilters] = useState(true);
  const [queueOpen, setQueueOpen] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [anchorDate, setAnchorDate] = useState<string | undefined>();
  const [viewMode, setViewModeState] = useState<CalendarViewMode>('list');

  // Load saved view mode on first client render to avoid hydration mismatch
  useEffect(() => {
    const stored = window.sessionStorage.getItem(
      'pms_view_mode'
    ) as CalendarViewMode;
    if (['list', 'month', 'agenda', 'week', 'day'].includes(stored)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setViewModeState(stored);
    }
  }, []);

  const setViewMode = (mode: CalendarViewMode) => {
    setViewModeState(mode);
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem('pms_view_mode', mode);
    }
  };

  const [calendarMonth, setCalendarMonth] = useState(() => ({
    year: new Date().getFullYear(),
    month: new Date().getMonth(),
  }));

  const [isJumpDateOpen, setIsJumpDateOpen] = useState(false);

  const { data: reviewItemsData } = useReviewItems('pending', 1, 1);
  const reviewQueueCount = (reviewItemsData?.meta?.total_count as number) || 0;

  // Debounce search query to avoid excessive API calls
  const debouncedSearchQuery = useDebounce(
    searchQuery,
    TIMEOUTS.DEBOUNCE_SEARCH
  );

  // Use search query if present, otherwise use regular journal list
  const shouldUseSearch = debouncedSearchQuery.length > 0;

  // Tag filter from URL search params (?tag=<id>). The URL is the source of
  // truth for this tag; `filters.tag_ids` holds only the panel-selected tags.
  const { tagId: activeTagId, clearTag } = useTagFilter('/journals');

  const { data: tagsData } = useJournalTags();
  const activeTagName = useMemo(() => {
    if (!activeTagId || !tagsData?.data) return null;
    return tagsData.data.find(t => t.id === activeTagId)?.name ?? null;
  }, [activeTagId, tagsData]);

  // Merge the URL tag into the active filters for querying and for the panel.
  const effectiveFilters = useMemo<JournalFiltersType>(() => {
    if (!activeTagId) return filters;
    const tagIds = filters.tag_ids ?? [];
    return {
      ...filters,
      tag_ids: tagIds.includes(activeTagId) ? tagIds : [...tagIds, activeTagId],
    };
  }, [filters, activeTagId]);

  // Unchecking the URL-derived tag clears the param; everything else is stored
  // as panel state with the URL tag stripped back out.
  const handleFiltersChange = useCallback(
    (next: JournalFiltersType) => {
      const nextTagIds = next.tag_ids ?? [];
      if (activeTagId && !nextTagIds.includes(activeTagId)) {
        clearTag();
      }
      const remaining = activeTagId
        ? nextTagIds.filter(id => id !== activeTagId)
        : nextTagIds;
      // Drop cleared keys rather than storing `undefined`: `hasActiveFilters`
      // and the empty-state message count keys, so a phantom key from any
      // filter — not just tags — would read as an active filter.
      const stored: JournalFiltersType = { ...next };
      if (remaining.length > 0) {
        stored.tag_ids = remaining;
      } else {
        delete stored.tag_ids;
      }
      setFilters(withoutClearedFilters(stored));
    },
    [activeTagId, clearTag]
  );

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
  } = useInfiniteJournals(effectiveFilters, {
    enabled: !shouldUseSearch,
    anchorDate,
  });

  const {
    data: searchData,
    isLoading: isLoadingSearch,
    error: searchError,
  } = useSearchJournals(
    debouncedSearchQuery,
    { types: filters.types },
    { enabled: shouldUseSearch }
  );

  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [quickCreateDate, setQuickCreateDate] = useState<string | undefined>();

  // Calendar view data: fetch journals for the displayed month or agenda window
  const monthDateRange = useMemo(
    () => getMonthDateRange(calendarMonth.year, calendarMonth.month),
    [calendarMonth.year, calendarMonth.month]
  );
  const weekDateRange = useMemo(
    () => getWeekDateRange(anchorDate ? parseISO(anchorDate) : new Date()),
    [anchorDate]
  );
  const dayDateRange = useMemo(
    () => getDayDateRange(anchorDate ? parseISO(anchorDate) : new Date()),
    [anchorDate]
  );
  const agendaDateRange = useMemo(
    () =>
      getAgendaDateRange(
        anchorDate ? parseISO(anchorDate) : new Date(),
        30,
        14
      ),
    [anchorDate]
  );

  const calendarFilters: JournalFiltersType = useMemo(() => {
    const baseFilters = { ...effectiveFilters };
    if (viewMode === 'month') {
      return {
        ...baseFilters,
        date_from: monthDateRange.start,
        date_to: monthDateRange.end,
        limit: 100,
      };
    }
    if (viewMode === 'week') {
      return {
        ...baseFilters,
        date_from: weekDateRange.start,
        date_to: weekDateRange.end,
        limit: 100,
      };
    }
    if (viewMode === 'day') {
      return {
        ...baseFilters,
        date_from: dayDateRange.start,
        date_to: dayDateRange.end,
        limit: 100,
      };
    }
    if (viewMode === 'agenda') {
      return {
        ...baseFilters,
        date_from: agendaDateRange.start,
        date_to: agendaDateRange.end,
        limit: 100,
      };
    }
    return baseFilters;
  }, [
    effectiveFilters,
    viewMode,
    monthDateRange,
    weekDateRange,
    dayDateRange,
    agendaDateRange,
  ]);

  const { data: calendarData, isLoading: isCalendarLoading } = useJournals(
    calendarFilters,
    {
      enabled: !shouldUseSearch && viewMode !== 'list',
    }
  );

  const calendarJournals = useDisplayJournals(calendarData?.data, false);
  const calendarEvents = useMemo(
    () => toCalendarEvents(calendarJournals),
    [calendarJournals]
  );

  const isLoading = shouldUseSearch ? isLoadingSearch : isInfiniteLoading;
  const error = shouldUseSearch ? searchError : infiniteError;

  let journalsToDisplay: import('@/types/journals').JournalResource[] = [];
  if (shouldUseSearch) {
    journalsToDisplay = searchData?.data || [];
  } else {
    journalsToDisplay =
      (
        infiniteData as InfiniteData<
          import('@/types/journals').JournalListResponse
        >
      )?.pages?.flatMap(page => page.data) || [];
  }

  const totalJournals = shouldUseSearch
    ? searchData?.meta?.total_count || 0
    : journalsToDisplay.length;

  // Use the centralized display journals hook with search highlighting support
  const displayJournals = useDisplayJournals(
    journalsToDisplay,
    shouldUseSearch
  );

  const dateBounds = shouldUseSearch ? undefined : getDateBounds(infiniteData);

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

  const hasActiveFilters =
    searchQuery.length > 0 ||
    Object.keys(filters).length > 0 ||
    activeTagId !== null;

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
      // Journal search has no tag parameter, so tag filters do not narrow
      // search results — whether they came from the URL or the filter panel.
      // Say so rather than letting the UI imply a narrowing that is not applied.
      const selectedTagCount = effectiveFilters.tag_ids?.length ?? 0;
      const tagCaveat =
        selectedTagCount > 0
          ? ` — search covers all tags, not just the ${selectedTagCount === 1 ? 'selected one' : 'selected ones'}`
          : '';
      return `${journalCount} found for "${debouncedSearchQuery}"${processingTime}${tagCaveat}`;
    }

    return `${journalCount} found`;
  };

  return (
    <>
      <div className='mb-6'>
        <h1 className='flex items-center gap-2 text-3xl font-bold tracking-tight'>
          {activeTagName ? (
            <>
              <Tag className='h-7 w-7' aria-hidden='true' />
              {activeTagName} Journals
            </>
          ) : (
            'Journals'
          )}
        </h1>
        <p className='text-muted-foreground'>
          {activeTagName
            ? `Journals tagged with "${activeTagName}"`
            : 'Your journal entries and memories.'}
        </p>
      </div>

      {/* Floating Action / Search Bar */}
      <div className='bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-14 z-40 mb-6 py-2 backdrop-blur'>
        <Card>
          <CardContent className='pt-4 pb-4'>
            <div className='flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between'>
              <div className='flex flex-1 flex-wrap items-center gap-2'>
                <div className='relative max-w-sm min-w-[200px] flex-1'>
                  <Search className='text-muted-foreground absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2' />
                  <Input
                    placeholder='Search journals...'
                    value={searchQuery}
                    onChange={e => handleSearchChange(e.target.value)}
                    className='h-9 pl-10'
                    data-testid='search-input'
                  />
                </div>

                <CalendarViewToggle value={viewMode} onChange={setViewMode} />
                <Popover open={isJumpDateOpen} onOpenChange={setIsJumpDateOpen}>
                  <PopoverTrigger asChild>
                    <Button
                      variant='outline'
                      size='sm'
                      className={cn(
                        'h-9 justify-start text-left font-normal',
                        !anchorDate && 'text-muted-foreground'
                      )}
                      data-testid='jump-date-button'
                    >
                      <CalendarIcon className='mr-2 h-4 w-4' />
                      {anchorDate ? (
                        format(parseISO(anchorDate), 'PPP')
                      ) : (
                        <span>Jump to date...</span>
                      )}
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className='w-auto p-0' align='start'>
                    <Calendar
                      mode='single'
                      selected={anchorDate ? parseISO(anchorDate) : undefined}
                      onSelect={d => {
                        if (d) {
                          setAnchorDate(format(d, 'yyyy-MM-dd'));
                          if (viewMode === 'month') {
                            setCalendarMonth({
                              year: d.getFullYear(),
                              month: d.getMonth(),
                            });
                          }
                          setIsJumpDateOpen(false);
                        }
                      }}
                    />
                  </PopoverContent>
                </Popover>

                {(hasActiveFilters || anchorDate) && (
                  <Button
                    variant='outline'
                    size='sm'
                    className='h-9'
                    onClick={() => {
                      clearSearch();
                      setAnchorDate(undefined);
                    }}
                    data-testid='clear-filters'
                  >
                    Clear
                  </Button>
                )}
              </div>

              <div className='flex flex-wrap items-center gap-2'>
                {reviewQueueCount > 0 && (
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={() => setQueueOpen(true)}
                    className='text-destructive hover:text-destructive hover:bg-destructive/10 h-9 gap-2'
                  >
                    <FileText className='h-4 w-4' />
                    Review Queue ({reviewQueueCount})
                  </Button>
                )}
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setExportDialogOpen(true)}
                  className='h-9 gap-2'
                  data-testid='export-logbook'
                >
                  <Download className='h-4 w-4' />
                  Export Logbook
                </Button>
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setShowFilters(!showFilters)}
                  className='h-9 gap-2'
                  data-testid='toggle-filters'
                >
                  <Filter className='h-4 w-4' />
                  {showFilters ? 'Hide' : 'Show'} Filters
                </Button>
                <Button
                  asChild
                  size='sm'
                  className='h-9 gap-2'
                  data-testid='new-journal'
                >
                  <Link href={'/journals/new' as Route}>
                    <Plus className='h-4 w-4' />
                    New Journal
                  </Link>
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Active Tag Filter Badge — always visible, so the tag filter stays
          dismissible even when the filters sidebar is hidden. */}
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
        <BookOpen className='text-muted-foreground h-4 w-4' />
        <span className='text-muted-foreground text-sm'>
          {getResultsSummary()}
        </span>
      </div>

      <div className='flex flex-col gap-6 md:flex-row'>
        {/* Filters Sidebar */}
        {showFilters && (
          <aside className='w-full flex-shrink-0 md:w-64'>
            <div className='sticky top-40'>
              <Card>
                <CardContent className='pt-6'>
                  <JournalFilters
                    filters={effectiveFilters}
                    onFiltersChange={handleFiltersChange}
                  />
                </CardContent>
              </Card>
            </div>
          </aside>
        )}

        {/* Main Content */}
        <main className={cn('flex-1', !showFilters && 'w-full')}>
          {/* List View (default) */}
          {viewMode === 'list' && (
            <>
              {isLoading && (
                <div className='flex items-center justify-center py-12'>
                  <div className='text-muted-foreground'>
                    Loading journals...
                  </div>
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
                  collapseEmptyDays={shouldUseSearch || hasActiveFilters}
                  onJumpToDate={date => setAnchorDate(date)}
                  focusDate={anchorDate || format(new Date(), 'yyyy-MM-dd')}
                  emptyState={
                    <Card>
                      <CardContent className='py-12 text-center'>
                        <BookOpen className='text-muted-foreground mx-auto h-12 w-12' />
                        <h3 className='mt-4 text-lg font-semibold'>
                          No journals found
                        </h3>
                        <p className='text-muted-foreground mt-2 text-sm'>
                          {getEmptyStateMessage(searchQuery, hasActiveFilters)}
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
            </>
          )}

          {/* Month View */}
          {viewMode === 'month' && (
            <Card>
              <CardContent className='pt-6'>
                <CalendarMonthView
                  year={calendarMonth.year}
                  month={calendarMonth.month}
                  events={calendarEvents}
                  onMonthChange={(year, month) =>
                    setCalendarMonth({ year, month })
                  }
                  onDayClick={date => {
                    setAnchorDate(date);
                    setViewMode('agenda');
                  }}
                  onSlotClick={date => {
                    setQuickCreateDate(date);
                    setQuickCreateOpen(true);
                  }}
                  isLoading={isCalendarLoading}
                />
              </CardContent>
            </Card>
          )}

          {/* Week View */}
          {viewMode === 'week' && (
            <Card>
              <CardContent className='pt-6'>
                <CalendarWeekView
                  anchorDate={anchorDate ? parseISO(anchorDate) : new Date()}
                  events={calendarEvents}
                  onWeekChange={date =>
                    setAnchorDate(format(date, 'yyyy-MM-dd'))
                  }
                  onSlotClick={date => {
                    setQuickCreateDate(date);
                    setQuickCreateOpen(true);
                  }}
                  isLoading={isCalendarLoading}
                />
              </CardContent>
            </Card>
          )}

          {/* Day View */}
          {viewMode === 'day' && (
            <Card>
              <CardContent className='pt-6'>
                <CalendarDayView
                  anchorDate={anchorDate ? parseISO(anchorDate) : new Date()}
                  events={calendarEvents}
                  onDayChange={date =>
                    setAnchorDate(format(date, 'yyyy-MM-dd'))
                  }
                  onSlotClick={date => {
                    setQuickCreateDate(date);
                    setQuickCreateOpen(true);
                  }}
                  isLoading={isCalendarLoading}
                />
              </CardContent>
            </Card>
          )}

          {/* Agenda View */}
          {viewMode === 'agenda' && (
            <CalendarAgendaView
              events={calendarEvents}
              isLoading={isCalendarLoading}
            />
          )}

          {/* Quick Create Dialog */}
          <CalendarQuickCreateDialog
            open={quickCreateOpen}
            onOpenChange={setQuickCreateOpen}
            initialDate={quickCreateDate}
            onSuccess={() => {
              // Optionally do something on success if needed
            }}
          />
        </main>
      </div>

      <ReviewQueueSidebar open={queueOpen} onOpenChange={setQueueOpen} />
      <LogbookExportDialog
        open={exportDialogOpen}
        onOpenChange={setExportDialogOpen}
      />
    </>
  );
}
