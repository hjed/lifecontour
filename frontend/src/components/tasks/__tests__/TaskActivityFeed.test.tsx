/**
 * Tests for the task ActivityFeed wrapper.
 *
 * The wrapper renders the shared, entity-agnostic feed wired to
 * `useTaskHistory` with `entity="task"`, mirroring the contact and journal
 * wrappers beside it. The specification asks for one component, one layout and
 * one pagination behaviour across the surfaces, so the useful assertions here
 * are that the task id reaches the hook and that the shared feed is what
 * renders — not a second list that happens to look like it.
 */

import { render, screen } from '@testing-library/react';
import { TaskActivityFeed } from '../TaskActivityFeed';
import type { HistoryListResponse } from '@/types/history';

const mockUseTaskHistory = jest.fn();
jest.mock('@/lib/api/tasks', () => ({
  useTaskHistory: (...args: unknown[]) => mockUseTaskHistory(...args),
}));

const mockHistoryData: HistoryListResponse = {
  data: [
    {
      type: 'task_history',
      id: '1',
      attributes: {
        entity_type: 'task',
        entity_id: 42,
        field_name: '__created__',
        old_value: null,
        new_value: 'Book the venue',
        changed_by: 'ui',
        source: 'ui',
        created_at: '2024-01-15T10:30:00Z',
      },
    },
  ],
  meta: { total_count: 1, page_count: 1, current_page: 1, per_page: 10 },
};

describe('TaskActivityFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('passes the task id and page size through to useTaskHistory', () => {
    mockUseTaskHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<TaskActivityFeed taskId='42' pageSize={5} />);

    expect(mockUseTaskHistory).toHaveBeenCalledWith(
      '42',
      expect.objectContaining({ page: 1, limit: 5 })
    );
  });

  it('renders the shared feed with task-specific empty-state copy', () => {
    mockUseTaskHistory.mockReturnValue({
      data: { data: [], meta: { total_count: 0 } },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<TaskActivityFeed taskId='42' />);

    expect(screen.getByTestId('activity-feed')).toBeInTheDocument();
    expect(
      screen.getByText(/Changes to this task will appear here/i)
    ).toBeInTheDocument();
  });

  it('renders a task entry in the task’s own wording, with provenance', async () => {
    mockUseTaskHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<TaskActivityFeed taskId='42' />);

    expect(
      await screen.findByText(/Task created: “Book the venue”/)
    ).toBeInTheDocument();
    expect(screen.getByTestId('provenance-trigger-ui')).toBeInTheDocument();
  });

  it('passes the hook straight through, like the other two wrappers', () => {
    // Not an `enabled`-flag wrapper: what keeps a collapsed row off the
    // network is that the journal does not mount this component at all, which
    // `JournalTaskRow.test.tsx` asserts. Pinned here so the flag is not
    // reintroduced as "the way it is done".
    mockUseTaskHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<TaskActivityFeed taskId='42' />);

    // Every call carries the id and the filters and nothing else: no options
    // argument, because there is no flag for a caller to set.
    expect(mockUseTaskHistory).toHaveBeenCalled();
    for (const call of mockUseTaskHistory.mock.calls) {
      expect(call).toHaveLength(2);
    }
  });
});
