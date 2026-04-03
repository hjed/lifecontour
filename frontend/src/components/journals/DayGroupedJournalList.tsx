'use client';

import { ReactNode, useEffect, useRef } from 'react';
import { format, parseISO } from 'date-fns';
import { Loader2 } from 'lucide-react';
import { JournalListItem } from '@/components/journals/JournalListItem';
import { DisplayJournal } from '@/hooks/useDisplayJournals';
import { groupJournalsByDay } from '@/lib/journal-grouping';

export interface DayGroupedJournalListProps {
  readonly journals: DisplayJournal[];
  readonly isLoadingNext?: boolean;
  readonly isLoadingPrevious?: boolean;
  readonly hasNextPage?: boolean;
  readonly hasPreviousPage?: boolean;
  readonly fetchNextPage?: () => void;
  readonly fetchPreviousPage?: () => void;
  readonly dateBounds?: { start: string; end: string };
  readonly collapseEmptyDays: boolean;
  readonly emptyState?: ReactNode;
  readonly className?: string;
}

export function DayGroupedJournalList({
  journals,
  isLoadingNext = false,
  isLoadingPrevious = false,
  hasNextPage = false,
  hasPreviousPage = false,
  fetchNextPage,
  fetchPreviousPage,
  dateBounds,
  collapseEmptyDays,
  emptyState,
  className = '',
}: DayGroupedJournalListProps) {
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const bottomSentinelRef = useRef<HTMLDivElement>(null);

  const fetchStateRef = useRef({
    hasNextPage,
    hasPreviousPage,
    isLoadingNext,
    isLoadingPrevious,
    fetchNextPage,
    fetchPreviousPage,
  });

  useEffect(() => {
    fetchStateRef.current = {
      hasNextPage,
      hasPreviousPage,
      isLoadingNext,
      isLoadingPrevious,
      fetchNextPage,
      fetchPreviousPage,
    };
  }, [
    hasNextPage,
    hasPreviousPage,
    isLoadingNext,
    isLoadingPrevious,
    fetchNextPage,
    fetchPreviousPage,
  ]);

  // Set up intersection observers for bi-directional scroll fetching
  useEffect(() => {
    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) return;
          const state = fetchStateRef.current;

          if (entry.target === topSentinelRef.current) {
            // Scrolling up -> fetch previous (FUTURE items)
            if (
              state.hasPreviousPage &&
              !state.isLoadingPrevious &&
              state.fetchPreviousPage
            ) {
              state.fetchPreviousPage();
            }
          } else if (entry.target === bottomSentinelRef.current) {
            // Scrolling down -> fetch next (PAST items)
            if (
              state.hasNextPage &&
              !state.isLoadingNext &&
              state.fetchNextPage
            ) {
              state.fetchNextPage();
            }
          }
        });
      },
      { rootMargin: '200px' }
    );

    const topTarget = topSentinelRef.current;
    const bottomTarget = bottomSentinelRef.current;

    if (topTarget) observer.observe(topTarget);
    if (bottomTarget) observer.observe(bottomTarget);

    return () => observer.disconnect();
  }, []);

  if (journals.length === 0 && !hasNextPage && !hasPreviousPage && emptyState) {
    return <>{emptyState}</>;
  }

  // Derive date bounds
  let effectiveStartDate = dateBounds?.start;
  let effectiveEndDate = dateBounds?.end;

  if (!effectiveStartDate || !effectiveEndDate) {
    if (journals.length > 0) {
      const dates = journals
        .map(j => {
          try {
            return parseISO(j.event_date_range.start).getTime();
          } catch {
            return 0;
          }
        })
        .filter(n => !isNaN(n) && n > 0);
      if (dates.length > 0) {
        effectiveStartDate = format(new Date(Math.min(...dates)), 'yyyy-MM-dd');
        effectiveEndDate = format(new Date(Math.max(...dates)), 'yyyy-MM-dd');
      } else {
        effectiveStartDate = '1970-01-01';
        effectiveEndDate = '1970-01-01';
      }
    } else {
      effectiveStartDate = '1970-01-01';
      effectiveEndDate = '1970-01-01';
    }
  }

  const dayGroups = groupJournalsByDay({
    journals,
    startDate: effectiveStartDate,
    endDate: effectiveEndDate,
    collapseEmpty: collapseEmptyDays,
  });

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Top Sentinel (Future) */}
      <div
        ref={topSentinelRef}
        className='flex h-4 w-full items-center justify-center'
        data-testid='journal-top-sentinel'
      >
        {isLoadingPrevious && (
          <Loader2 className='text-muted-foreground h-6 w-6 animate-spin' />
        )}
      </div>

      {dayGroups.length === 0 && !isLoadingNext && !isLoadingPrevious && (
        <div className='py-8'>
          {emptyState || (
            <div className='text-muted-foreground text-center'>
              No journals match the selected filters.
            </div>
          )}
        </div>
      )}

      {dayGroups.map(group => {
        const displayDate = format(parseISO(group.date), 'EEEE, MMMM do, yyyy');

        return (
          <div
            key={group.date}
            className='space-y-3'
            data-testid={`journal-day-group-${group.date}`}
          >
            <h3 className='bg-background/95 supports-[backdrop-filter]:bg-background/60 sticky top-0 z-10 border-b py-2 text-lg font-semibold backdrop-blur'>
              {displayDate}
            </h3>

            {group.isEmpty ? (
              <div className='text-muted-foreground border-l-2 border-transparent py-2 pl-4 text-sm italic'>
                No entries
              </div>
            ) : (
              <div className='border-border/40 space-y-3 border-l-2 pl-4'>
                {group.journals.map(journal => (
                  <JournalListItem
                    key={journal.id}
                    journal={journal}
                    className='w-full'
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Bottom Sentinel (Past) */}
      <div
        ref={bottomSentinelRef}
        className='flex h-4 w-full items-center justify-center'
        data-testid='journal-bottom-sentinel'
      >
        {isLoadingNext && (
          <Loader2 className='text-muted-foreground h-6 w-6 animate-spin' />
        )}
      </div>
    </div>
  );
}
