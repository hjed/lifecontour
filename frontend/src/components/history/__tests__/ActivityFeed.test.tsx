/**
 * Tests for the shared (entity-agnostic) ActivityFeed component.
 *
 * The feed depends on an injected `useHistory` hook, so these tests supply a
 * mock hook directly via props rather than mocking an entity-specific module.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { ActivityFeed, type UseHistoryHook } from '../ActivityFeed';
import type { HistoryListResponse } from '@/types/history';

type HistoryResult = ReturnType<UseHistoryHook>;

const mockHistoryData: HistoryListResponse = {
  data: [
    {
      type: 'contact_history',
      id: '1',
      attributes: {
        entity_type: 'contact',
        entity_id: 123,
        field_name: 'first_name',
        old_value: 'John',
        new_value: 'Jane',
        changed_by: 'user@example.com',
        source: 'ui',
        created_at: '2024-01-15T10:30:00Z',
      },
    },
    {
      type: 'contact_history',
      id: '2',
      attributes: {
        entity_type: 'contact',
        entity_id: 123,
        field_name: 'last_name',
        old_value: null,
        new_value: 'Doe',
        changed_by: 'user@example.com',
        source: 'ui',
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

/** Build a stub `useHistory` hook that always returns the given result. */
function stubHook(result: HistoryResult): UseHistoryHook {
  return () => result;
}

describe('ActivityFeed (shared)', () => {
  it('renders loading state', () => {
    const useHistory = stubHook({
      data: undefined,
      isLoading: true,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    expect(screen.getByText(/Loading activity/i)).toBeInTheDocument();
  });

  it('renders empty state with contact copy by default', () => {
    const useHistory = stubHook({
      data: { data: [], meta: undefined },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    expect(screen.getByText(/No activity yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Changes to this contact will appear here/i)
    ).toBeInTheDocument();
  });

  it('renders journal empty-state copy when entity is journal', () => {
    const useHistory = stubHook({
      data: { data: [], meta: undefined },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(
      <ActivityFeed entityId='42' entity='journal' useHistory={useHistory} />
    );

    expect(
      screen.getByText(/Changes to this journal will appear here/i)
    ).toBeInTheDocument();
  });

  it('renders activity items', async () => {
    const useHistory = stubHook({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    expect(screen.getByTestId('activity-feed')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('activity-item-2')).toBeInTheDocument();
  });

  it('renders a provenance trigger per entry', async () => {
    const useHistory = stubHook({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    // Both entries use the 'ui' source, so two provenance triggers render.
    await waitFor(() => {
      expect(screen.getAllByTestId('provenance-trigger-ui')).toHaveLength(2);
    });
  });

  it('renders error state', () => {
    const useHistory = stubHook({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load history'),
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    expect(screen.getByText(/Error loading activity/i)).toBeInTheDocument();
    expect(screen.getByText(/Failed to load history/i)).toBeInTheDocument();
  });

  it('shows Load More button when there are more items', async () => {
    const useHistory = stubHook({
      data: {
        data: mockHistoryData.data,
        meta: { total_count: 20, page_count: 2, current_page: 1, per_page: 10 },
      },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Load More/i })
      ).toBeInTheDocument();
    });
  });

  it('does not show Load More button when all items are loaded', async () => {
    const useHistory = stubHook({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='123' useHistory={useHistory} />);

    await waitFor(() => {
      expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    });

    expect(
      screen.queryByRole('button', { name: /Load More/i })
    ).not.toBeInTheDocument();
  });

  it('applies custom className', () => {
    const useHistory = stubHook({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(
      <ActivityFeed
        entityId='123'
        useHistory={useHistory}
        className='custom-class'
      />
    );

    expect(screen.getByTestId('activity-feed')).toHaveClass('custom-class');
  });
});
