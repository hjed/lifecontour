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

  it('renders task empty-state copy when entity is task', () => {
    const useHistory = stubHook({
      data: { data: [], meta: undefined },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='7' entity='task' useHistory={useHistory} />);

    expect(
      screen.getByText(/Changes to this task will appear here/i)
    ).toBeInTheDocument();
  });

  it('tells each entry which feed it is being read on', async () => {
    // A contact-membership row reads one way on a task's own history and
    // another on the person's, so the feed has to pass its entity down or the
    // row cannot know which it is.
    const useHistory = stubHook({
      data: {
        data: [
          {
            // As the contact endpoint stamps it: the resource type follows the
            // aggregate that was read, `entity_type` the row that was written.
            type: 'contact_history',
            id: 'link-1',
            attributes: {
              entity_type: 'task',
              entity_id: 42,
              field_name: 'contact:12',
              old_value: null,
              new_value: '12',
              changed_by: 'ui',
              source: 'ui',
              created_at: '2024-01-15T10:30:00Z',
            },
          },
        ],
        meta: undefined,
      },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(
      <ActivityFeed entityId='12' entity='contact' useHistory={useHistory} />
    );

    expect(await screen.findByText('Linked to a task')).toBeInTheDocument();
  });

  it('renders no header when title is null', () => {
    // The journal's task row embeds this feed inside a list on a page that
    // already has an "Activity" heading; one h3 per open row would be a run of
    // identical headings to anyone navigating by heading.
    const useHistory = stubHook({
      data: { data: [], meta: undefined },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(
      <ActivityFeed
        entityId='7'
        entity='task'
        title={null}
        useHistory={useHistory}
      />
    );

    expect(screen.getByTestId('activity-feed')).toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
  });

  it('renders the default Activity heading otherwise', () => {
    const useHistory = stubHook({
      data: { data: [], meta: undefined },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed entityId='7' useHistory={useHistory} />);

    expect(
      screen.getByRole('heading', { name: /Activity/i })
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
