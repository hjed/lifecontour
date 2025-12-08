/**
 * Tests for ActivityFeed component.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ActivityFeed } from '../ActivityFeed';
import type { ContactHistoryListResponse } from '@/types/contacts';

// Mock the API hook
const mockUseContactHistory = jest.fn();
jest.mock('@/lib/api/contacts', () => ({
  useContactHistory: (...args: unknown[]) => mockUseContactHistory(...args),
}));

// Create test wrapper with React Query
function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

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

describe('ActivityFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state', () => {
    mockUseContactHistory.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByText(/Loading activity/i)).toBeInTheDocument();
  });

  it('renders empty state when no activities', () => {
    mockUseContactHistory.mockReturnValue({
      data: { data: [], meta: { total_count: 0 } },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByText(/No activity yet/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Changes to this contact will appear here/i)
    ).toBeInTheDocument();
  });

  it('renders activity items', async () => {
    mockUseContactHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByTestId('activity-feed')).toBeInTheDocument();

    // Wait for useEffect to populate allActivities
    await waitFor(() => {
      expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('activity-item-2')).toBeInTheDocument();
  });

  it('renders error state', () => {
    mockUseContactHistory.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load history'),
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByText(/Error loading activity/i)).toBeInTheDocument();
    expect(screen.getByText(/Failed to load history/i)).toBeInTheDocument();
  });

  it('shows Load More button when there are more items', async () => {
    mockUseContactHistory.mockReturnValue({
      data: {
        data: mockHistoryData.data,
        meta: { total_count: 20, page_count: 2, current_page: 1, per_page: 10 },
      },
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />, { wrapper: createWrapper() });

    // Wait for useEffect to populate allActivities
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /Load More/i })
      ).toBeInTheDocument();
    });
  });

  it('does not show Load More button when all items are loaded', async () => {
    mockUseContactHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' />, { wrapper: createWrapper() });

    // Wait for useEffect to populate allActivities
    await waitFor(() => {
      expect(screen.getByTestId('activity-item-1')).toBeInTheDocument();
    });

    expect(
      screen.queryByRole('button', { name: /Load More/i })
    ).not.toBeInTheDocument();
  });

  it('applies custom className', () => {
    mockUseContactHistory.mockReturnValue({
      data: mockHistoryData,
      isLoading: false,
      error: null,
      isFetching: false,
    });

    render(<ActivityFeed contactId='123' className='custom-class' />, {
      wrapper: createWrapper(),
    });

    expect(screen.getByTestId('activity-feed')).toHaveClass('custom-class');
  });
});
