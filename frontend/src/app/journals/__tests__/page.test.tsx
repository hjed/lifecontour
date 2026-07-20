/**
 * @jest-environment jsdom
 */

import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import JournalsPage from '../page';
import { renderWithQueryClient } from '@/components/journals/test-helpers';
import { useInfiniteJournals } from '@/lib/api/journals';
import type { JournalFilters as JournalFiltersType } from '@/types/journals';

// Mock next/navigation
const mockPush = jest.fn();
let mockSearchParams = new URLSearchParams();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
  }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => '/journals',
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
      data: {
        data: [
          { id: 'tag-1', name: 'Holidays', color: '#FF0000' },
          { id: 'tag-2', name: 'Work', color: '#00FF00' },
        ],
      },
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
    mockSearchParams = new URLSearchParams();
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

  describe('tag deep link (/journals?tag=<id>)', () => {
    const getLatestInfiniteFilters = () => {
      const calls = (useInfiniteJournals as jest.Mock).mock.calls;
      return calls[calls.length - 1][0] as JournalFiltersType;
    };

    it('applies the URL tag to the journals query', () => {
      mockSearchParams = new URLSearchParams('tag=tag-1');
      renderWithQueryClient(<JournalsPage />);

      expect(getLatestInfiniteFilters().tag_ids).toEqual(['tag-1']);
    });

    it('reflects the URL tag in the filter panel', () => {
      mockSearchParams = new URLSearchParams('tag=tag-1');
      renderWithQueryClient(<JournalsPage />);

      expect(screen.getByLabelText('Holidays')).toHaveAttribute(
        'aria-checked',
        'true'
      );
      expect(screen.getByLabelText('Work')).toHaveAttribute(
        'aria-checked',
        'false'
      );
    });

    it('names the active tag in the page heading', () => {
      mockSearchParams = new URLSearchParams('tag=tag-1');
      renderWithQueryClient(<JournalsPage />);

      expect(
        screen.getByRole('heading', { name: /holidays journals/i })
      ).toBeInTheDocument();
    });

    it('clears the tag param when the URL tag is unchecked', async () => {
      const user = userEvent.setup();
      mockSearchParams = new URLSearchParams('tag=tag-1');
      renderWithQueryClient(<JournalsPage />);

      await user.click(screen.getByLabelText('Holidays'));

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/journals');
      });
    });

    it('queries the union of the URL tag and an additionally selected tag', async () => {
      const user = userEvent.setup();
      mockSearchParams = new URLSearchParams('tag=tag-1');
      renderWithQueryClient(<JournalsPage />);

      await user.click(screen.getByLabelText('Work'));

      await waitFor(() => {
        expect(getLatestInfiniteFilters().tag_ids).toEqual(['tag-2', 'tag-1']);
      });
    });

    it('offers a dismissible badge so the tag stays clearable with filters hidden', async () => {
      const user = userEvent.setup();
      mockSearchParams = new URLSearchParams('tag=tag-1');
      renderWithQueryClient(<JournalsPage />);

      // Hide the filters sidebar — the badge must remain the escape hatch.
      await user.click(screen.getByRole('button', { name: /hide filters/i }));

      const badge = screen.getByTestId('active-tag-filter');
      expect(badge).toBeInTheDocument();

      await user.click(
        screen.getByRole('button', { name: 'Remove Holidays filter' })
      );

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith('/journals');
      });
    });

    it('does not leave a phantom tag_ids key after the last tag is unchecked', async () => {
      const user = userEvent.setup();
      renderWithQueryClient(<JournalsPage />);

      const workCheckbox = screen.getByLabelText('Work');
      await user.click(workCheckbox);
      await waitFor(() => {
        expect(getLatestInfiniteFilters().tag_ids).toEqual(['tag-2']);
      });

      await user.click(workCheckbox);

      // Must be genuinely empty, not `{tag_ids: undefined}` — a phantom key
      // reads as an active filter to the empty-state and Clear-button checks.
      await waitFor(() => {
        expect(Object.keys(getLatestInfiniteFilters())).not.toContain(
          'tag_ids'
        );
      });
      expect(screen.queryByTestId('clear-filters')).not.toBeInTheDocument();
    });

    it('applies no tag filter and a plain heading without a tag param', () => {
      renderWithQueryClient(<JournalsPage />);

      expect(getLatestInfiniteFilters().tag_ids).toBeUndefined();
      expect(
        screen.getByRole('heading', { name: 'Journals' })
      ).toBeInTheDocument();
    });
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
