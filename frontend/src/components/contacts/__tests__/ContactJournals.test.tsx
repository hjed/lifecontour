/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ContactJournals } from '../ContactJournals';
import * as journalsApi from '@/lib/api/journals';
import { JournalType } from '@/types/journals';

// Mock the API functions
jest.mock('@/lib/api/journals', () => ({
  useContactJournals: jest.fn(),
}));

// Mock Next.js router
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

const createMockJournal = (
  id: string,
  title: string,
  relationshipType: string | null,
  eventDate: string = '2024-01-01',
  parentId?: number,
  order?: number
) => ({
  id,
  type: 'journals',
  attributes: {
    title,
    content: 'Test content for journal ' + id,
    event_date_range: {
      start: eventDate,
      end: eventDate,
    },
    types: [JournalType.NOTE],
    tags: [],
    parent_id: parentId ?? null,
    order: order ?? null,
    contacts: relationshipType
      ? [
          {
            id: '123', // Contact IDs are strings in the API
            name: 'Test Contact',
            relationship_type: relationshipType,
          },
        ]
      : [],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
});

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

describe('ContactJournals', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('should render loading state', () => {
    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('should render error state', () => {
    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('Failed to fetch journals'),
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByText(/error/i)).toBeInTheDocument();
  });

  it('should render empty state when no journals', () => {
    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: { data: [], meta: { total: 0 } },
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    expect(screen.getByText(/no journals/i)).toBeInTheDocument();
  });

  it('should group journals by relationship type', async () => {
    const mockData = {
      data: [
        createMockJournal('1', 'Journal 1', 'PARTICIPANT'),
        createMockJournal('2', 'Journal 2', 'PARTICIPANT'),
        createMockJournal('3', 'Journal 3', 'INVITEE'),
        createMockJournal('4', 'Journal 4', 'ABOUT'),
      ],
      meta: { total: 4 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/participant/i)).toBeInTheDocument();
      expect(screen.getByText(/invitee/i)).toBeInTheDocument();
      expect(screen.getByText(/about/i)).toBeInTheDocument();
    });
  });

  it('should display journal cards with correct information', async () => {
    const mockData = {
      data: [createMockJournal('1', 'Test Journal', 'PARTICIPANT')],
      meta: { total: 1 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Test Journal')).toBeInTheDocument();
      expect(
        screen.getByText(/test content for journal 1/i)
      ).toBeInTheDocument();
    });
  });

  it('should display warning when there are more journals than shown', async () => {
    // Mock 5 journals but total is 150 (more than the 100 limit)
    const mockData = {
      data: [
        createMockJournal('1', 'Journal 1', 'PARTICIPANT'),
        createMockJournal('2', 'Journal 2', 'PARTICIPANT'),
        createMockJournal('3', 'Journal 3', 'PARTICIPANT'),
        createMockJournal('4', 'Journal 4', 'PARTICIPANT'),
        createMockJournal('5', 'Journal 5', 'PARTICIPANT'),
      ],
      meta: { total: 150 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(/showing 5 of 150 related journals/i)
      ).toBeInTheDocument();
      expect(screen.getByText(/journals page/i)).toBeInTheDocument();
    });
  });

  it('should not display warning when all journals are shown', async () => {
    const mockData = {
      data: [
        createMockJournal('1', 'Journal 1', 'PARTICIPANT'),
        createMockJournal('2', 'Journal 2', 'PARTICIPANT'),
      ],
      meta: { total: 2 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Journal 1')).toBeInTheDocument();
    });

    // Warning should not be present
    expect(
      screen.queryByText(/showing.*of.*related journals/i)
    ).not.toBeInTheDocument();
  });

  it('should sort journals by event date (most recent first)', async () => {
    const mockData = {
      data: [
        createMockJournal('1', 'Oldest Journal', 'PARTICIPANT', '2024-01-01'),
        createMockJournal('2', 'Newest Journal', 'PARTICIPANT', '2024-03-01'),
        createMockJournal('3', 'Middle Journal', 'PARTICIPANT', '2024-02-01'),
      ],
      meta: { total: 3 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      // Get their positions in the DOM
      const cards = screen.getAllByTestId(/^journal-\d+$/);
      const positions = cards.map(card => card.getAttribute('data-testid'));

      // Should be sorted: Newest (2), Middle (3), Oldest (1)
      expect(positions[0]).toBe('journal-2');
      expect(positions[1]).toBe('journal-3');
      expect(positions[2]).toBe('journal-1');
    });
  });

  it('should nest child journals under their parent within a relationship section', async () => {
    const mockData = {
      data: [
        createMockJournal('1', 'Parent Journal', 'PARTICIPANT', '2024-03-01'),
        createMockJournal('2', 'Child Journal', null, '2024-03-02', 1),
        createMockJournal(
          '3',
          'Other Root Journal',
          'PARTICIPANT',
          '2024-02-01'
        ),
      ],
      meta: { total: 3 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText('Parent Journal')).toBeInTheDocument();
      expect(screen.getByText('Child Journal')).toBeInTheDocument();
    });

    const childrenContainer = screen.getByTestId('journalChildrenContainer-1');
    expect(
      within(childrenContainer).getByTestId('journal-2')
    ).toBeInTheDocument();
    expect(
      within(childrenContainer).queryByTestId('journal-3')
    ).not.toBeInTheDocument();
  });

  it('should allow collapsing and expanding child journals', async () => {
    const user = userEvent.setup();
    const mockData = {
      data: [
        createMockJournal('1', 'Parent Journal', 'PARTICIPANT', '2024-03-01'),
        createMockJournal('2', 'Child Journal', null, '2024-03-02', 1),
      ],
      meta: { total: 2 },
    };

    (journalsApi.useContactJournals as jest.Mock).mockReturnValue({
      data: mockData,
      isLoading: false,
      isError: false,
    });

    render(<ContactJournals contactId='123' />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByTestId('journal-2')).toBeInTheDocument();
    });

    const toggle = screen.getByTestId('journalChildrenToggle-1');

    await user.click(toggle);
    expect(screen.queryByTestId('journal-2')).not.toBeInTheDocument();

    await user.click(toggle);
    expect(screen.getByTestId('journal-2')).toBeInTheDocument();
  });
});
