/**
 * @jest-environment jsdom
 */

import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import JournalsPage from '../page';
import { renderWithQueryClient } from '@/components/journals/test-helpers';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

// mock removed

jest.mock('@/lib/api/journals', () => {
  const originalModule = jest.requireActual('@/lib/api/journals');
  return {
    __esModule: true,
    ...originalModule,
    useInfiniteJournals: jest.fn(() => ({
      data: {
        pages: [
          {
            data: [
              {
                type: 'journals',
                id: '1',
                attributes: {
                  title: 'Test Journal 1',
                  content: 'Test content 1',
                  event_date_range: { start: '2024-01-01', end: '2024-01-01' },
                  types: [],
                  type_data: {},
                  contacts: [],
                  tags: [],
                  calendar: null,
                  parent: null,
                  children_count: 0,
                  created_at: '2024-01-01T00:00:00Z',
                  updated_at: '2024-01-01T00:00:00Z',
                },
              },
            ],
          },
        ],
        pageParams: [{ date_from: '2024-01-01', date_to: '2024-01-01' }],
      },
      isLoading: false,
      error: null,
      hasNextPage: false,
      hasPreviousPage: false,
      isFetchingNextPage: false,
      isFetchingPreviousPage: false,
    })),
    useJournals: jest.fn(() => ({
      data: {
        data: [
          {
            type: 'journals',
            id: '1',
            attributes: {
              title: 'Test Journal 1',
              content: 'Test content 1',
              event_date_range: { start: '2024-01-01', end: '2024-01-01' },
              types: [],
              type_data: {},
              contacts: [],
              tags: [],
              calendar: null,
              parent: null,
              children_count: 0,
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
            },
          },
        ],
      },
      isLoading: false,
      error: null,
    })),
    useSearchJournals: jest.fn(() => ({
      data: null,
      isLoading: false,
      error: null,
    })),
    useJournalTags: jest.fn(() => ({
      data: { data: [] },
      isLoading: false,
    })),
    useCalendars: jest.fn(() => ({
      data: { data: [] },
      isLoading: false,
    })),
  };
});

// Mock AuthGuard
jest.mock('@/components/auth/AuthGuard', () => ({
  AuthGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock IntersectionObserver
const mockIntersectionObserver = jest.fn();
mockIntersectionObserver.mockReturnValue({
  observe: () => null,
  unobserve: () => null,
  disconnect: () => null,
});
global.IntersectionObserver = mockIntersectionObserver;

describe('JournalsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders the page title and description', () => {
    renderWithQueryClient(<JournalsPage />);

    expect(screen.getByText('Journals')).toBeInTheDocument();
    expect(
      screen.getByText('Your journal entries and memories.')
    ).toBeInTheDocument();
  });

  it('renders filter toggle button', () => {
    renderWithQueryClient(<JournalsPage />);

    expect(
      screen.getByRole('button', { name: /hide filters/i })
    ).toBeInTheDocument();
  });

  it('renders new journal link', () => {
    renderWithQueryClient(<JournalsPage />);

    expect(
      screen.getByRole('link', { name: /new journal/i })
    ).toBeInTheDocument();
  });

  it('renders journal list when data is available', () => {
    renderWithQueryClient(<JournalsPage />);

    expect(screen.getByText('Test Journal 1')).toBeInTheDocument();
  });

  it('toggles filter visibility', async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<JournalsPage />);

    const filterButton = screen.getByRole('button', { name: /hide filters/i });
    await user.click(filterButton);

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /show filters/i })
      ).toBeInTheDocument();
    });
  });
});
