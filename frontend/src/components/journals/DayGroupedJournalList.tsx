'use client';

import { ReactNode, useEffect, useRef, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { Loader2 } from 'lucide-react';
import { JournalListItem } from '@/components/journals/JournalListItem';
import { DisplayJournal } from '@/hooks/useDisplayJournals';
import { groupJournalsByDay } from '@/lib/journal-grouping';
import { Button } from '@/components/ui/button';
import Link from 'next/link';

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
  readonly onJumpToDate?: (date: string) => void;
  readonly focusDate?: string;
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
  onJumpToDate,
  focusDate,
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

  const [hasScrolled, setHasScrolled] = useState(false);

  // Initial scroll to today before enabling observers
  useEffect(() => {
    if (hasScrolled) return;
    if (isLoadingNext || isLoadingPrevious) return;

    const todayStr = format(new Date(), 'yyyy-MM-dd');
    const todayElement = document.querySelector(
      `[data-testid="journal-day-group-${todayStr}"]`
    );

    let scrollTimer: NodeJS.Timeout;
    let stateTimer: NodeJS.Timeout;

    if (todayElement) {
      scrollTimer = setTimeout(() => {
        todayElement.scrollIntoView({ block: 'center' });
        // Allow a brief moment for the scroll to settle before enabling observers
        stateTimer = setTimeout(() => setHasScrolled(true), 100);
      }, 50);
    } else if (journals.length > 0 || (!isLoadingNext && !isLoadingPrevious)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Needed to gate intersection observers
      setHasScrolled(true);
    }

    return () => {
      clearTimeout(scrollTimer);
      clearTimeout(stateTimer);
    };
  }, [journals, isLoadingNext, isLoadingPrevious, hasScrolled]);

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
    if (!hasScrolled) return;

    const observer = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) return;
          const state = fetchStateRef.current;

          if (entry.target === topSentinelRef.current) {
            // Scrolling up -> fetch previous (PAST items)
            if (
              state.hasPreviousPage &&
              !state.isLoadingPrevious &&
              state.fetchPreviousPage
            ) {
              state.fetchPreviousPage();
            }
          } else if (entry.target === bottomSentinelRef.current) {
            // Scrolling down -> fetch next (FUTURE items)
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
  }, [hasScrolled]);

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
        .filter(n => !Number.isNaN(n) && n > 0);
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

  const isTotallyEmpty =
    journals.length === 0 && !isLoadingNext && !isLoadingPrevious;

  return (
    <div
      className={`space-y-6 ${className}`}
      data-testid={
        hasScrolled ? 'journals-list-ready' : 'journals-list-loading'
      }
    >
      {/* Top Sentinel (Past) */}
      <div
        ref={topSentinelRef}
        className='flex h-4 w-full items-center justify-center'
        data-testid='journal-top-sentinel'
      >
        {isLoadingPrevious && (
          <Loader2 className='text-muted-foreground h-6 w-6 animate-spin' />
        )}
      </div>

      {isTotallyEmpty && (
        <div className='py-8'>
          {emptyState || (
            <div className='text-muted-foreground text-center'>
              No journals match the selected filters.
            </div>
          )}
        </div>
      )}

      {dayGroups.map(group => {
        if (group.type === 'collapsed-empty') {
          const displayStartDate = format(parseISO(group.startDate), 'MMM do');
          const displayEndDate = format(
            parseISO(group.endDate),
            'MMM do, yyyy'
          );
          return (
            <div
              key={`collapsed-${group.startDate}`}
              className='flex flex-col items-center justify-between gap-4 py-8 opacity-70 transition-opacity hover:opacity-100 sm:flex-row'
              data-testid={`journal-collapsed-group-${group.startDate}`}
            >
              <div className='text-muted-foreground flex w-full items-center gap-4 text-sm italic sm:w-auto'>
                <div className='bg-border h-px w-8 flex-grow sm:flex-grow-0' />
                <span className='whitespace-nowrap'>
                  {displayStartDate} - {displayEndDate} ({group.daysCount} days
                  without entries)
                </span>
                <div className='bg-border h-px w-8 flex-grow sm:flex-grow-0' />
              </div>
              <div className='flex w-full justify-center gap-2 sm:w-auto'>
                {onJumpToDate && (
                  <Button
                    variant='outline'
                    size='sm'
                    onClick={() => onJumpToDate(group.startDate)}
                  >
                    Jump to date
                  </Button>
                )}
                <Button variant='outline' size='sm' asChild>
                  <Link href={`/journals/new?date=${group.startDate}`}>
                    Add Journal
                  </Link>
                </Button>
              </div>
            </div>
          );
        }

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
                    focusDate={focusDate}
                    className='w-full'
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {/* Bottom Sentinel (Future) */}
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
