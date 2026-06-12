/**
 * Tests for the journal ActivityFeed wrapper.
 *
 * The wrapper renders the shared, entity-agnostic feed wired to
 * `useJournalHistory` with `entity="journal"`. These tests confirm the journal
 * id is threaded through to the hook and that the shared feed's render,
 * provenance, pagination, empty, loading, and error behaviours hold for the
 * journal surface.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ActivityFeed } from '../ActivityFeed';
import type { HistoryListResponse } from '@/types/history';

// Mock the journal history API hook the wrapper injects into the shared feed.
const mockUseJournalHistory = jest.fn();
jest.mock('@/lib/api/journals', () => ({
  useJournalHistory: (...args: unknown[]) => mockUseJournalHistory(...args),
}));

const mockHistoryData: HistoryListResponse = {
  data: [
    {
      type: 'journal_history',
      id: '1',
      attributes: {
        entity_type: 'journal',
        entity_id: 42,
        field_name: 'title',
        old_value: 'Old title',
        new_value: 'New title',
        changed_by: 'user@example.com',
        source: 'ui',
        created_at: '2024-01-15T10:30:00Z',
      },
    },
    {
      type: 'journal_history',
      id: '2',
      attributes: {
        entity_type: 'journal',
        entity_id: 42,
        field_name: 'content',
        old_value: null,
        new_value: 'Some content',
        changed_by: 'assistant',
        source: 'mcp',
        created_at: '2024-01-15T10:00:00Z',
      },
    },
  ],
  meta: {
    total_count: 2,
    page_count: 1,
    current_page: 1,
    per_page: 10,
  },
};

describe('ActivityFeed (journal wrapper)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('passes the journal id through to useJournalHistory', () => {
    mockUseJournalHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' pageSize={5} />);

    expect(mockUseJournalHistory).toHaveBeenCalledWith(
      '42',
      expect.objectContaining({ page: 1, limit: 5 })
    );
  });

  it('renders journal-specific empty-state copy', () => {
    mockUseJournalHistory.mockReturnValue({
      data: { data: [], meta: { total_count: 0 } },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' />);

    expect(screen.getByText(/No activity yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Changes to this journal will appear here/i)
    ).toBeInTheDocument();
  });

  it('renders journal history entries with provenance', async () => {
    mockUseJournalHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' />);

    expect(screen.getByTestId('activity-feed')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('activity-item-2')).toBeInTheDocument();
    // Provenance triggers reflect each entry's source (ui + mcp).
    expect(screen.getByTestId('provenance-trigger-ui')).toBeInTheDocument();
    expect(screen.getByTestId('provenance-trigger-mcp')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    mockUseJournalHistory.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' />);

    expect(screen.getByText(/Loading activity/i)).toBeInTheDocument();
  });

  it('renders error state', () => {
    mockUseJournalHistory.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load history'),
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' />);

    expect(screen.getByText(/Error loading activity/i)).toBeInTheDocument();
    expect(screen.getByText(/Failed to load history/i)).toBeInTheDocument();
  });

  it('shows a Load More button and advances the page when more pages exist', async () => {
    mockUseJournalHistory.mockReturnValue({
      data: {
        data: mockHistoryData.data,
        meta: { total_count: 20, page_count: 2, current_page: 1, per_page: 10 },
      },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' />);

    const loadMore = await screen.findByRole('button', { name: /Load More/i });
    await userEvent.click(loadMore);

    // Clicking Load More re-queries the next page via the hook.
    await waitFor(() => {
      expect(mockUseJournalHistory).toHaveBeenCalledWith(
        '42',
        expect.objectContaining({ page: 2 })
      );
    });
  });

  it('applies custom className', () => {
    mockUseJournalHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed journalId='42' className='custom-class' />);

    expect(screen.getByTestId('activity-feed')).toHaveClass('custom-class');
  });
});
