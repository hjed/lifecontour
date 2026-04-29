import { render, screen } from '@testing-library/react';
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
});
