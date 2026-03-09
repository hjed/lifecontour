/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import ContactsPage from '../page';
import {
  useInfiniteContacts,
  useInfiniteSearchContacts,
  useToggleContactFavourite,
} from '@/lib/api/contacts';
import { ContactListResponse } from '@/types/contacts';
import {
  renderWithProviders,
  setupMocks,
  contactTestUtils,
} from '@/test-utils';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    replace: jest.fn(),
  })),
  usePathname: jest.fn(() => '/contacts'),
}));

// Mock constants
jest.mock('@/lib/constants', () => ({
  TIMEOUTS: {
    DEBOUNCE_SEARCH: 300,
  },
  ERROR_MESSAGES: {
    SESSION_EXPIRED: 'Session expired',
    NETWORK_ERROR: 'Network error',
    GENERIC_ERROR: 'An error occurred',
  },
  API_ENDPOINTS: {
    AUTH: {
      SESSION: '/api/auth/session',
    },
  },
  DATE_FORMATS: {
    SHORT: 'dd/MM/yyyy',
    LONG: 'dd MMMM yyyy',
    WITH_TIME: 'dd/MM/yyyy HH:mm',
    TIME_ONLY: 'HH:mm',
    ISO: 'yyyy-MM-dd',
  },
}));

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useInfiniteContacts: jest.fn(),
  useInfiniteSearchContacts: jest.fn(),
  useToggleContactFavourite: jest.fn(),
  getContactPaginationMeta: jest.fn((meta?: Record<string, unknown>) => ({
    totalCount:
      typeof meta?.total_count === 'number'
        ? meta.total_count
        : typeof meta?.total === 'number'
          ? meta.total
          : undefined,
    currentPage:
      typeof meta?.current_page === 'number'
        ? meta.current_page
        : typeof meta?.page === 'number'
          ? meta.page
          : undefined,
    pageCount:
      typeof meta?.page_count === 'number'
        ? meta.page_count
        : typeof meta?.total_pages === 'number'
          ? meta.total_pages
          : typeof meta?.totalPages === 'number'
            ? meta.totalPages
            : undefined,
    perPage:
      typeof meta?.per_page === 'number'
        ? meta.per_page
        : typeof meta?.limit === 'number'
          ? meta.limit
          : undefined,
  })),
}));

// Mock the FavouriteToggle component
jest.mock('@/components/contacts/FavouriteToggle', () => ({
  FavouriteToggle: ({ contactId, isFavourite, contactName }: any) => (
    <button data-testid={`favourite-toggle-${contactId}`}>
      {isFavourite ? 'Remove from favourites' : 'Add to favourites'} -{' '}
      {contactName}
    </button>
  ),
}));

const mockUseInfiniteContacts = useInfiniteContacts as jest.MockedFunction<
  typeof useInfiniteContacts
>;
const mockUseInfiniteSearchContacts =
  useInfiniteSearchContacts as jest.MockedFunction<
    typeof useInfiniteSearchContacts
  >;
const mockUseToggleContactFavourite =
  useToggleContactFavourite as jest.MockedFunction<
    typeof useToggleContactFavourite
  >;

function createInfiniteQueryResult(data?: ContactListResponse) {
  return {
    data: data
      ? {
          pages: [data],
          pageParams: [1],
        }
      : undefined,
    isLoading: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: jest.fn(),
    isPending: false,
    isError: false,
    isSuccess: true,
    status: 'success',
    fetchStatus: 'idle',
    refetch: jest.fn(),
  } as const;
}

describe('ContactsPage - Favourites', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
    setupMocks.clearMocks();
    setupMocks.fetch();

    // Mock authenticated session
    (fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        user: { id: '1', name: 'Test User' },
      }),
    });

    mockUseInfiniteSearchContacts.mockReturnValue(
      createInfiniteQueryResult() as any
    );

    // Set up default mock for useToggleContactFavourite
    mockUseToggleContactFavourite.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as any);
  });

  it('should display favourite toggle for each contact', async () => {
    const mockData: ContactListResponse = {
      data: [
        {
          type: 'contacts',
          id: '1',
          attributes: {
            first_name: 'John',
            last_name: 'Doe',
            is_favourite: true,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
            relationships: [],
          },
        },
        {
          type: 'contacts',
          id: '2',
          attributes: {
            first_name: 'Jane',
            last_name: 'Smith',
            is_favourite: false,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
            relationships: [],
          },
        },
      ],
      meta: { total: 2, page: 1, limit: 20 },
    };

    mockUseInfiniteContacts.mockReturnValue(
      createInfiniteQueryResult(mockData) as any
    );

    renderWithProviders(<ContactsPage />);

    // Wait for authentication to complete and page to load
    await screen.findByText('Contacts');

    // Check that favourite toggles are rendered for both contacts
    expect(screen.getByTestId('favourite-toggle-1')).toBeInTheDocument();
    expect(screen.getByTestId('favourite-toggle-2')).toBeInTheDocument();

    // Check the correct favourite status is displayed
    expect(screen.getByTestId('favourite-toggle-1')).toHaveTextContent(
      'Remove from favourites - John Doe'
    );
    expect(screen.getByTestId('favourite-toggle-2')).toHaveTextContent(
      'Add to favourites - Jane Smith'
    );
  });

  it('should handle contacts without is_favourite field', async () => {
    const mockData: ContactListResponse = {
      data: [
        {
          type: 'contacts',
          id: '1',
          attributes: {
            first_name: 'John',
            last_name: 'Doe',
            // is_favourite field missing - should default to false
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
            relationships: [],
          },
        },
      ],
      meta: { total: 1, page: 1, limit: 20 },
    };

    mockUseInfiniteContacts.mockReturnValue(
      createInfiniteQueryResult(mockData) as any
    );

    renderWithProviders(<ContactsPage />);

    // Wait for authentication to complete and page to load
    await screen.findByText('Contacts');

    const favouriteToggle = screen.getByTestId('favourite-toggle-1');
    expect(favouriteToggle).toHaveTextContent('Add to favourites - John Doe');
  });
});
