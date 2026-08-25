/**
 * Tests for the contact ActivityFeed wrapper.
 *
 * The wrapper is the behavioural-parity guard: it must render the shared feed
 * wired to `useContactHistory`, preserving the contact-specific empty-state
 * copy and rendering contact history entries unchanged.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { ActivityFeed } from '../ActivityFeed';
import type { ContactHistoryListResponse } from '@/types/contacts';

// Mock the contact history API hook the wrapper injects into the shared feed.
const mockUseContactHistory = jest.fn();
jest.mock('@/lib/api/contacts', () => ({
  useContactHistory: (...args: unknown[]) => mockUseContactHistory(...args),
}));

const mockHistoryData: ContactHistoryListResponse = {
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
  ],
  meta: {
    total_count: 1,
    page_count: 1,
    current_page: 1,
    per_page: 10,
  },
};

describe('ActivityFeed (contact wrapper)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('passes the contact id through to useContactHistory', () => {
    mockUseContactHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' pageSize={5} />);

    expect(mockUseContactHistory).toHaveBeenCalledWith(
      '123',
      expect.objectContaining({ page: 1, limit: 5 })
    );
  });

  it('renders contact-specific empty-state copy', () => {
    mockUseContactHistory.mockReturnValue({
      data: { data: [], meta: { total_count: 0 } },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />);

    expect(screen.getByText(/No activity yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Changes to this contact will appear here/i)
    ).toBeInTheDocument();
  });

  it('renders contact history entries', async () => {
    mockUseContactHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />);

    expect(screen.getByTestId('activity-feed')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    });
  });

  it('applies custom className', () => {
    mockUseContactHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' className='custom-class' />);

    expect(screen.getByTestId('activity-feed')).toHaveClass('custom-class');
  });
});

/**
 * A task's record on the person's page.
 *
 * The specification's *Contacts on tasks* asks for the task to surface here as
 * a read-only record; *Where tasks appear* says the entry "is not actionable
 * from there" and that the feed cannot be filtered down to "everything still
 * outstanding". Both are assertions this file can make and the backend cannot.
 */
describe('ActivityFeed (contact wrapper) — task records', () => {
  const taskRecord = {
    data: [
      {
        // The contact endpoint stamps `contact_history` on every row it
        // returns, including the task ones — `entity_type` is what says which
        // kind of row it is.
        type: 'contact_history',
        id: 'task-1',
        attributes: {
          entity_type: 'task',
          entity_id: 42,
          field_name: 'contact:123',
          old_value: null,
          new_value: '123',
          changed_by: 'ui',
          source: 'ui',
          created_at: '2024-01-15T10:30:00Z',
          entity_label: 'Return the borrowed harness',
        },
      },
    ],
    meta: { total_count: 1, page_count: 1, current_page: 1, per_page: 10 },
  } as unknown as ContactHistoryListResponse;

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseContactHistory.mockReturnValue({
      data: taskRecord,
      isLoading: false,
      error: null,
      isFetching: false,
    });
  });

  it('reads the record from the contact’s point of view, naming the task', async () => {
    render(<ActivityFeed contactId='123' />);

    expect(
      await screen.findByText('Linked to a task: “Return the borrowed harness”')
    ).toBeInTheDocument();
  });

  it('offers nothing to act on', async () => {
    render(<ActivityFeed contactId='123' />);

    await screen.findByText(/Linked to a task/);

    const actionable = screen
      .queryAllByRole('button')
      .filter(
        button =>
          !(button.getAttribute('data-testid') ?? '').startsWith(
            'provenance-trigger-'
          )
      );
    expect(actionable).toHaveLength(0);
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });

  it('offers no way to filter the feed down to outstanding work', async () => {
    render(<ActivityFeed contactId='123' />);

    await screen.findByText(/Linked to a task/);

    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.queryAllByRole('searchbox')).toHaveLength(0);
  });
});
