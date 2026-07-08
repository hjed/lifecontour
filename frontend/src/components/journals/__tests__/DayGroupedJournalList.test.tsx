import { act, render, screen } from '@testing-library/react';
import { DayGroupedJournalList } from '../DayGroupedJournalList';
import { DisplayJournal } from '@/hooks/useDisplayJournals';
import { JournalType } from '@/types/journals';

// Mock the DailySummaryView component
jest.mock('@/components/journals/DailySummaryView', () => ({
  DailySummaryView: ({ date }: { date: string }) => (
    <div data-testid={`mock-daily-summary-${date}`}>
      Daily Summary for {date}
    </div>
  ),
}));

// Mock intersection observer
const mockIntersectionObserver = jest.fn();
mockIntersectionObserver.mockReturnValue({
  observe: () => null,
  unobserve: () => null,
  disconnect: () => null,
});
window.IntersectionObserver = mockIntersectionObserver;

// Helper to create mock journals
const createMockJournal = (id: string, date: string): DisplayJournal =>
  ({
    id,
    title: `Journal ${id}`,
    content: 'Test content',
    event_date_range: { start: date, end: date },
    types: [JournalType.NOTE],
    contacts: [],
    tags: [],
  }) as DisplayJournal;

describe('DayGroupedJournalList', () => {
  beforeEach(() => {
    // Mock scrollIntoView
    window.HTMLElement.prototype.scrollIntoView = jest.fn();
  });

  it('renders DailySummaryView when a day has 2 or more journals', () => {
    const journals = [
      createMockJournal('1', '2026-04-29T10:00:00Z'),
      createMockJournal('2', '2026-04-29T11:00:00Z'),
    ];

    render(
      <DayGroupedJournalList journals={journals} collapseEmptyDays={false} />
    );

    // The group date will be '2026-04-29'
    expect(
      screen.getByTestId('mock-daily-summary-2026-04-29')
    ).toBeInTheDocument();
  });

  it('does not render DailySummaryView when a day has less than 2 journals', () => {
    const journals = [createMockJournal('1', '2026-04-29T10:00:00Z')];

    render(
      <DayGroupedJournalList journals={journals} collapseEmptyDays={false} />
    );

    expect(
      screen.queryByTestId('mock-daily-summary-2026-04-29')
    ).not.toBeInTheDocument();
  });

  it('renders multiple DailySummaryViews for multiple populated days', () => {
    const journals = [
      createMockJournal('1', '2026-04-28T10:00:00Z'),
      createMockJournal('2', '2026-04-28T11:00:00Z'),
      createMockJournal('3', '2026-04-29T10:00:00Z'),
      createMockJournal('4', '2026-04-29T11:00:00Z'),
      createMockJournal('5', '2026-04-30T10:00:00Z'), // Only 1 on this day
    ];

    render(
      <DayGroupedJournalList journals={journals} collapseEmptyDays={false} />
    );

    expect(
      screen.getByTestId('mock-daily-summary-2026-04-28')
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('mock-daily-summary-2026-04-29')
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('mock-daily-summary-2026-04-30')
    ).not.toBeInTheDocument();
  });

  describe('sentinel-driven fetching', () => {
    // Captures the observer callback so tests can simulate sentinels
    // entering/leaving the viewport.
    let observerCallback: IntersectionObserverCallback;

    beforeEach(() => {
      window.IntersectionObserver = jest.fn(
        (callback: IntersectionObserverCallback) => {
          observerCallback = callback;
          return {
            observe: jest.fn(),
            unobserve: jest.fn(),
            disconnect: jest.fn(),
          };
        }
      ) as unknown as typeof IntersectionObserver;
    });

    const journals = [createMockJournal('1', '2026-04-29T10:00:00Z')];

    function intersect(testId: string, isIntersecting: boolean) {
      const target = screen.getByTestId(testId);
      act(() => {
        observerCallback(
          [{ target, isIntersecting } as unknown as IntersectionObserverEntry],
          {} as IntersectionObserver
        );
      });
    }

    it('fetches the previous page when the top sentinel intersects while idle', () => {
      const fetchPreviousPage = jest.fn();
      render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      intersect('journal-top-sentinel', true);

      expect(fetchPreviousPage).toHaveBeenCalled();
    });

    it('fetches the next page when the bottom sentinel intersects while idle', () => {
      const fetchNextPage = jest.fn();
      render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasNextPage
          fetchNextPage={fetchNextPage}
        />
      );

      intersect('journal-bottom-sentinel', true);

      expect(fetchNextPage).toHaveBeenCalled();
    });

    it('does not fetch while a fetch is already in flight', () => {
      const fetchPreviousPage = jest.fn();
      const { rerender } = render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
          isLoadingNext
        />
      );

      intersect('journal-top-sentinel', true);

      expect(fetchPreviousPage).not.toHaveBeenCalled();
    });

    it('fetches once the in-flight fetch settles while the sentinel is still intersecting', () => {
      // Regression: the observer only fires on intersection *changes*, so a
      // sentinel that comes into view during a fetch must still trigger its
      // own fetch once loading settles — otherwise pagination stalls until
      // the user scrolls away and back.
      const fetchPreviousPage = jest.fn();
      const { rerender } = render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
          isLoadingNext
        />
      );

      intersect('journal-top-sentinel', true);
      expect(fetchPreviousPage).not.toHaveBeenCalled();

      // The in-flight fetch settles; the sentinel never left the viewport.
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      expect(fetchPreviousPage).toHaveBeenCalled();
    });

    it('fetches only once per sentinel visit, not on every idle settle', () => {
      // Regression: on lists too short to push the sentinel out of view
      // (empty or heavily filtered lists), re-fetching every time loading
      // settles would loop forever — date-chunk pagination never runs out of
      // pages. One fetch per continuous intersection is the correct bound.
      const fetchPreviousPage = jest.fn();
      const { rerender } = render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      intersect('journal-top-sentinel', true);
      expect(fetchPreviousPage).toHaveBeenCalledTimes(1);

      // The fetch runs and settles while the sentinel never left the viewport.
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
          isLoadingPrevious
        />
      );
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      expect(fetchPreviousPage).toHaveBeenCalledTimes(1);
    });

    it('fetches again after the sentinel leaves and re-enters the viewport', () => {
      const fetchPreviousPage = jest.fn();
      render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      intersect('journal-top-sentinel', true);
      intersect('journal-top-sentinel', false);
      intersect('journal-top-sentinel', true);

      expect(fetchPreviousPage).toHaveBeenCalledTimes(2);
    });

    it('does not fetch after the sentinel leaves the viewport', () => {
      const fetchPreviousPage = jest.fn();
      const { rerender } = render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
          isLoadingNext
        />
      );

      intersect('journal-top-sentinel', true);
      intersect('journal-top-sentinel', false);

      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      expect(fetchPreviousPage).not.toHaveBeenCalled();
    });
  });
});
