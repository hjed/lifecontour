/**
 * @jest-environment jsdom
 */

import { render, screen, waitFor } from '@testing-library/react';
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
  relationshipType: string
) => ({
  id,
  type: 'journals',
  attributes: {
    title,
    content: 'Test content for journal ' + id,
    event_date_range: {
      start: '2024-01-01',
      end: '2024-01-01',
    },
    types: [JournalType.NOTE],
    tags: [],
    contacts: [
      {
        id: 123,
        name: 'Test Contact',
        relationship_type: relationshipType,
      },
    ],
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
});
