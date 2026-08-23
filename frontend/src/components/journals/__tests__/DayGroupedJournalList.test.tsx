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

    /** The user reaching for older entries — what unlocks backward paging. */
    function scrollThePage() {
      act(() => {
        window.dispatchEvent(new Event('scroll'));
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

      scrollThePage();
      intersect('journal-top-sentinel', true);

      expect(fetchPreviousPage).toHaveBeenCalled();
    });

    it('does not expand into the past until the user scrolls', () => {
      // Older days are inserted above everything on screen. A short list leaves
      // the top sentinel inside the observer's 200px margin on arrival, so
      // without this gate the list would drop a week of empty days on top of
      // whatever the reader is already looking at — moving controls out from
      // under the pointer mid-click.
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
      expect(fetchPreviousPage).not.toHaveBeenCalled();

      scrollThePage();

      expect(fetchPreviousPage).toHaveBeenCalled();
    });

    it('expands into the past without a scroll when the list is empty', () => {
      // Nothing is rendered yet, so there is no reading position to protect —
      // and expanding is how the user finds their entries.
      const fetchPreviousPage = jest.fn();
      render(
        <DayGroupedJournalList
          journals={[]}
          collapseEmptyDays={false}
          hasPreviousPage
          fetchPreviousPage={fetchPreviousPage}
        />
      );

      intersect('journal-top-sentinel', true);

      expect(fetchPreviousPage).toHaveBeenCalled();
    });

    it('still expands into the future without a scroll', () => {
      // Appending happens below the fold and disturbs nothing on screen, so
      // forward paging stays eager.
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

      scrollThePage();
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

      scrollThePage();
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

    it('does not fetch while the list is being refetched', () => {
      // Regression (#1203): `fetchNextPage`/`fetchPreviousPage` default to
      // `cancelRefetch: true`, so paginating during a post-mutation refetch
      // cancels it — React Query reverts to the pre-mutation pages, appends the
      // new one, and marks the result fresh. A deleted tag's chip then survives
      // on the list for the whole staleTime. `isLoadingNext`/`isLoadingPrevious`
      // do not cover this: neither is set during a plain refetch.
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
          isRefetching
        />
      );

      scrollThePage();
      intersect('journal-top-sentinel', true);

      expect(fetchPreviousPage).not.toHaveBeenCalled();
    });

    it('fetches once the refetch settles while the sentinel is still intersecting', () => {
      const fetchNextPage = jest.fn();
      const { rerender } = render(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasNextPage
          fetchNextPage={fetchNextPage}
        />
      );
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasNextPage
          fetchNextPage={fetchNextPage}
          isRefetching
        />
      );

      intersect('journal-bottom-sentinel', true);
      expect(fetchNextPage).not.toHaveBeenCalled();

      // Pausing must not cost the fetch: the refetch settles and the sentinel
      // is still in view, so pagination resumes rather than stalling.
      rerender(
        <DayGroupedJournalList
          journals={journals}
          collapseEmptyDays={false}
          hasNextPage
          fetchNextPage={fetchNextPage}
        />
      );

      expect(fetchNextPage).toHaveBeenCalled();
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

      scrollThePage();
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

      scrollThePage();
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

      scrollThePage();
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

  describe('scroll anchoring when older days are prepended', () => {
    // A previous-page fetch inserts older days *above* whatever the user is
    // looking at. Without compensation the whole list jumps down by the height
    // of the inserted content, moving buttons out from under the pointer
    // mid-click and losing the reader's place.
    const today = [createMockJournal('3', '2026-04-29T10:00:00Z')];
    const withOlderDays = [
      createMockJournal('1', '2026-04-20T10:00:00Z'),
      ...today,
    ];

    let scrollBy: jest.Mock;

    beforeEach(() => {
      scrollBy = jest.fn();
      window.scrollBy = scrollBy as unknown as typeof window.scrollBy;
    });

    /** Pin an element's viewport offset, as jsdom reports 0 for everything. */
    function setViewportTop(element: Element, top: number) {
      element.getBoundingClientRect = () =>
        ({ top, y: top, bottom: top, height: 0 }) as DOMRect;
    }

    function anchorElement() {
      return screen.getByTestId('journal-day-group-2026-04-29');
    }

    it('restores the anchor element to its original viewport offset', () => {
      const { rerender } = render(
        <DayGroupedJournalList journals={today} collapseEmptyDays={false} />
      );

      const anchor = anchorElement();
      setViewportTop(anchor, 100);

      // The previous-page fetch starts: the anchor's offset is captured here.
      rerender(
        <DayGroupedJournalList
          journals={today}
          collapseEmptyDays={false}
          isLoadingPrevious
        />
      );

      // Older days land above the anchor, pushing it down 120px.
      setViewportTop(anchor, 220);
      rerender(
        <DayGroupedJournalList
          journals={withOlderDays}
          collapseEmptyDays={false}
        />
      );

      expect(scrollBy).toHaveBeenCalledWith(0, 120);
    });

    it('does not scroll when the prepend did not move the anchor', () => {
      // The browser's own scroll anchoring may already have compensated;
      // measuring a real element rather than a height delta keeps this
      // self-correcting instead of double-correcting.
      const { rerender } = render(
        <DayGroupedJournalList journals={today} collapseEmptyDays={false} />
      );

      setViewportTop(anchorElement(), 100);

      rerender(
        <DayGroupedJournalList
          journals={today}
          collapseEmptyDays={false}
          isLoadingPrevious
        />
      );
      rerender(
        <DayGroupedJournalList
          journals={withOlderDays}
          collapseEmptyDays={false}
        />
      );

      expect(scrollBy).not.toHaveBeenCalled();
    });

    it('does not scroll when a next-page fetch appends newer days', () => {
      // Appending happens below the viewport: nothing the user is looking at
      // moves, so the scroll position must be left alone.
      const { rerender } = render(
        <DayGroupedJournalList journals={today} collapseEmptyDays={false} />
      );

      const anchor = anchorElement();
      setViewportTop(anchor, 100);

      rerender(
        <DayGroupedJournalList
          journals={today}
          collapseEmptyDays={false}
          isLoadingNext
        />
      );

      setViewportTop(anchor, 220);
      rerender(
        <DayGroupedJournalList
          journals={[...today, createMockJournal('9', '2026-05-08T10:00:00Z')]}
          collapseEmptyDays={false}
        />
      );

      expect(scrollBy).not.toHaveBeenCalled();
    });
  });
});
