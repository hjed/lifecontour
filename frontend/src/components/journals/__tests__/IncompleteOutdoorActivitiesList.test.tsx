/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { IncompleteOutdoorActivitiesList } from '../IncompleteOutdoorActivitiesList';
import { JournalType } from '@/types/journals';
import * as incompleteApi from '@/lib/api/incomplete-outdoor-activities';
import type { IncompleteOutdoorActivityResource } from '@/lib/api/incomplete-outdoor-activities';

// Mock the API hooks module
jest.mock('@/lib/api/incomplete-outdoor-activities', () => ({
  useIncompleteOutdoorActivities: jest.fn(),
  useDismissIncompleteOutdoorActivity: jest.fn(),
  useUndismissIncompleteOutdoorActivity: jest.fn(),
}));

// Mock toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

const mockUseIncomplete =
  incompleteApi.useIncompleteOutdoorActivities as jest.Mock;
const mockUseDismiss =
  incompleteApi.useDismissIncompleteOutdoorActivity as jest.Mock;
const mockUseUndismiss =
  incompleteApi.useUndismissIncompleteOutdoorActivity as jest.Mock;

function makeEntry(
  overrides: Partial<IncompleteOutdoorActivityResource['attributes']> & {
    id?: string;
  } = {}
): IncompleteOutdoorActivityResource {
  const { id = '42', ...attributes } = overrides;
  return {
    type: 'incomplete-outdoor-activities',
    id,
    attributes: {
      title: 'Empty canyon',
      // Noon UTC keeps the local calendar date stable across timezones
      event_date_range: {
        start: '2026-06-01T12:00:00Z',
        end: '2026-06-01T12:00:00Z',
      },
      subtypes: [JournalType.CANYONING],
      reasons: ['no_attributes', 'missing_template', 'no_participants'],
      dismissed: false,
      ...attributes,
    },
  };
}

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const TestWrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  TestWrapper.displayName = 'TestWrapper';
  return TestWrapper;
};

describe('IncompleteOutdoorActivitiesList', () => {
  const mockDismiss = jest.fn();
  const mockUndismiss = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    mockUseIncomplete.mockReturnValue({
      data: { data: [makeEntry()] },
      isLoading: false,
      error: null,
    });
    mockUseDismiss.mockReturnValue({ mutate: mockDismiss, isPending: false });
    mockUseUndismiss.mockReturnValue({
      mutate: mockUndismiss,
      isPending: false,
    });
  });

  it('renders an entry with title link, date, type icon and reason badges', () => {
    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    const item = screen.getByTestId('incomplete-activity-item-42');
    expect(item).toBeInTheDocument();

    const titleLink = screen.getByRole('link', { name: 'Empty canyon' });
    expect(titleLink).toHaveAttribute('href', '/journals/42');

    expect(item).toHaveTextContent('1 Jun 2026');
    expect(screen.getByTestId('type-badge-canyoning')).toBeInTheDocument();

    expect(screen.getByTestId('reason-badge-no_attributes')).toHaveTextContent(
      'No attributes set'
    );
    expect(
      screen.getByTestId('reason-badge-missing_template')
    ).toHaveTextContent('Missing template');
    expect(
      screen.getByTestId('reason-badge-no_participants')
    ).toHaveTextContent('No participants');
  });

  it('only renders badges for the matched reasons', () => {
    mockUseIncomplete.mockReturnValue({
      data: { data: [makeEntry({ reasons: ['no_participants'] })] },
      isLoading: false,
      error: null,
    });

    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    expect(
      screen.getByTestId('reason-badge-no_participants')
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('reason-badge-no_attributes')
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('reason-badge-missing_template')
    ).not.toBeInTheDocument();
  });

  it('dismisses an entry and removes the row once the list updates', () => {
    const { rerender } = render(<IncompleteOutdoorActivitiesList />, {
      wrapper: createWrapper(),
    });

    const dismissButton = screen.getByTestId('incomplete-dismiss-btn-42');
    expect(dismissButton).toHaveAccessibleName(
      'Dismiss "Empty canyon" from the incomplete review'
    );
    fireEvent.click(dismissButton);
    expect(mockDismiss).toHaveBeenCalledWith('42');

    // The mutation's optimistic update removes the entry from the cached list.
    mockUseIncomplete.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    });
    rerender(<IncompleteOutdoorActivitiesList />);

    expect(
      screen.queryByTestId('incomplete-activity-item-42')
    ).not.toBeInTheDocument();
    expect(screen.getByTestId('incomplete-empty-state')).toBeInTheDocument();
  });

  it('shows an empty state when there are no incomplete activities', () => {
    mockUseIncomplete.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    });

    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    expect(screen.getByTestId('incomplete-empty-state')).toHaveTextContent(
      'No incomplete activities'
    );
  });

  it('requests dismissed entries when the show-dismissed switch is toggled', () => {
    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    expect(mockUseIncomplete).toHaveBeenLastCalledWith(false);

    fireEvent.click(screen.getByRole('switch', { name: 'Show dismissed' }));

    expect(mockUseIncomplete).toHaveBeenLastCalledWith(true);
  });

  it('renders a dismissed entry muted with an un-dismiss control', () => {
    mockUseIncomplete.mockReturnValue({
      data: {
        data: [
          makeEntry({ id: '7', title: 'Dismissed canyon', dismissed: true }),
        ],
      },
      isLoading: false,
      error: null,
    });

    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    const item = screen.getByTestId('incomplete-activity-item-7');
    expect(item).toHaveAttribute('data-dismissed', 'true');
    expect(
      screen.queryByTestId('incomplete-dismiss-btn-7')
    ).not.toBeInTheDocument();

    const undismissButton = screen.getByTestId('incomplete-undismiss-btn-7');
    expect(undismissButton).toHaveAccessibleName(
      'Restore "Dismissed canyon" to the incomplete review'
    );
    fireEvent.click(undismissButton);
    expect(mockUndismiss).toHaveBeenCalledWith('7');
  });

  it('renders loading skeletons while fetching', () => {
    mockUseIncomplete.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    });

    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    expect(screen.getByTestId('incomplete-list-loading')).toBeInTheDocument();
    expect(
      screen.queryByTestId('incomplete-list-ready')
    ).not.toBeInTheDocument();
  });

  it('renders an error message when the fetch fails', () => {
    mockUseIncomplete.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to fetch data'),
    });

    render(<IncompleteOutdoorActivitiesList />, { wrapper: createWrapper() });

    expect(screen.getByTestId('incomplete-list-error')).toHaveTextContent(
      'Failed to fetch data'
    );
  });
});
