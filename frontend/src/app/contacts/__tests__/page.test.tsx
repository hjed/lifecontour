/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import ContactsPage from '../page';
import { ContactListResponse } from '@/types/contacts';
import {
  renderWithProviders,
  userEvent,
  contactTestUtils,
  setupMocks,
} from '@/test-utils';

jest.mock('@/lib/api/contacts', () => {
  const { createMockGetContactPaginationMeta } =
    jest.requireActual('@/test-utils');

  return {
    useInfiniteContacts: jest.fn(),
    useInfiniteSearchContacts: jest.fn(),
    useToggleContactFavourite: jest.fn(),
    useTags: jest.fn(),
    getContactPaginationMeta: jest.fn(createMockGetContactPaginationMeta),
  };
});

jest.mock('@/hooks/useDebounce', () => ({
  useDebounce: jest.fn(value => value),
}));

// Mock useTagFilter hook — defaults to no active tag
const mockClearTag = jest.fn();
const mockSetTag = jest.fn();
jest.mock('@/hooks/useTagFilter', () => ({
  useTagFilter: jest.fn(() => ({
    tagId: null,
    setTag: mockSetTag,
    clearTag: mockClearTag,
  })),
}));

// Note: Next.js navigation is mocked globally in jest.setup.ts

const mockUseTagFilter = jest.mocked(
  jest.requireMock('@/hooks/useTagFilter').useTagFilter
);

const mockUseInfiniteContacts = jest.mocked(
  jest.requireMock('@/lib/api/contacts').useInfiniteContacts
);
const mockUseInfiniteSearchContacts = jest.mocked(
  jest.requireMock('@/lib/api/contacts').useInfiniteSearchContacts
);

// Get the mocked function from the module
const mockUseToggleContactFavourite = jest.mocked(
  jest.requireMock('@/lib/api/contacts').useToggleContactFavourite
);
const mockUseTags = jest.mocked(jest.requireMock('@/lib/api/contacts').useTags);

type ContactsQueryState = {
  data?: ContactListResponse;
  pages?: ContactListResponse[];
  isLoading?: boolean;
  error?: Error | null;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  fetchNextPage?: jest.Mock<Promise<unknown>>;
};

type MockIntersectionObserverInstance = {
  callback: IntersectionObserverCallback;
  observe: jest.Mock;
  unobserve: jest.Mock;
  disconnect: jest.Mock;
  observedElements: Element[];
};

const mockIntersectionObserverInstances: MockIntersectionObserverInstance[] =
  [];

function getQueryStatus(
  state: ContactsQueryState
): 'pending' | 'error' | 'success' {
  if (state.isLoading) {
    return 'pending';
  }

  if (state.error) {
    return 'error';
  }

  return 'success';
}

function createPaginatedResponse(
  contacts: ContactListResponse['data'] = [
    contactTestUtils.createMockContact(),
  ],
  options: {
    totalCount?: number;
    currentPage?: number;
    pageCount?: number;
    processingTimeMs?: number;
  } = {}
): ContactListResponse {
  const totalCount = options.totalCount ?? contacts.length;
  const currentPage = options.currentPage ?? 1;
  const pageCount = options.pageCount ?? Math.max(1, currentPage);

  return {
    data: contacts,
    meta: {
      total_count: totalCount,
      page_count: pageCount,
      current_page: currentPage,
      per_page: 20,
      processing_time_ms: options.processingTimeMs,
      total: totalCount,
      page: currentPage,
      total_pages: pageCount,
    },
  };
}

function createInfiniteQueryResult(
  state: ContactsQueryState = {}
): Record<string, unknown> {
  const pages = state.pages ?? (state.data ? [state.data] : undefined);

  return {
    data:
      pages === undefined
        ? undefined
        : {
            pages,
            pageParams: pages.map((_, index) => index + 1),
          },
    isLoading: state.isLoading ?? false,
    error: state.error ?? null,
    isError: !!state.error,
    isPending: state.isLoading ?? false,
    isSuccess: !state.isLoading && !state.error,
    status: getQueryStatus(state),
    hasNextPage: state.hasNextPage ?? false,
    isFetchingNextPage: state.isFetchingNextPage ?? false,
    fetchNextPage:
      state.fetchNextPage ?? jest.fn().mockResolvedValue(undefined),
    refetch: jest.fn(),
  };
}

function triggerLastIntersection(isIntersecting = true) {
  const observer =
    mockIntersectionObserverInstances.length > 0
      ? mockIntersectionObserverInstances[
          mockIntersectionObserverInstances.length - 1
        ]
      : undefined;

  if (!observer) {
    throw new Error('No IntersectionObserver instance found');
  }

  const target = observer.observedElements[0] ?? document.createElement('div');

  observer.callback(
    [{ isIntersecting, target } as IntersectionObserverEntry],
    observer as unknown as IntersectionObserver
  );
}

describe('ContactsPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
    setupMocks.clearMocks();
    setupMocks.fetch();
    mockIntersectionObserverInstances.length = 0;

    globalThis.IntersectionObserver = jest.fn(
      (callback: IntersectionObserverCallback) => {
        const instance: MockIntersectionObserverInstance = {
          callback,
          observe: jest.fn((element: Element) => {
            instance.observedElements.push(element);
          }),
          unobserve: jest.fn(),
          disconnect: jest.fn(),
          observedElements: [],
        };

        mockIntersectionObserverInstances.push(instance);

        return instance;
      }
    ) as unknown as typeof IntersectionObserver;

    // Mock authenticated session for all tests
    (fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        user: {
          id: '1',
          email: 'test@example.com',
          name: 'Test User',
        },
      }),
    });

    mockUseToggleContactFavourite.mockReturnValue({
      mutate: jest.fn(),
      isPending: false,
      isError: false,
      error: null,
    });

    // Default: no tags API data
    mockUseTags.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: null,
    } as never);

    // Default: no active tag filter
    mockUseTagFilter.mockReturnValue({
      tagId: null,
      setTag: mockSetTag,
      clearTag: mockClearTag,
    });
  });

  // Test helpers
  const renderContactsPage = () => {
    return renderWithProviders(<ContactsPage />);
  };

  const setupContactMocks = (
    contactsState: ContactsQueryState = {},
    searchState: ContactsQueryState = {}
  ) => {
    const contactPages =
      contactsState.pages ??
      (contactsState.data ? [contactsState.data] : undefined);
    const searchPages =
      searchState.pages ?? (searchState.data ? [searchState.data] : undefined);

    mockUseInfiniteContacts.mockReturnValue(
      createInfiniteQueryResult({
        ...contactsState,
        pages: contactPages,
      }) as never
    );

    mockUseInfiniteSearchContacts.mockReturnValue(
      createInfiniteQueryResult({
        ...searchState,
        pages: searchPages,
      }) as never
    );
  };

  const mockContactsData = contactTestUtils.createMockContactsResponse();

  it('renders the contacts page with header', async () => {
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    // Wait for authentication to complete and page to load
    expect(await screen.findByText('Contacts')).toBeInTheDocument();
    expect(
      screen.getByText('Manage your personal and professional contacts')
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /add contact/i })
    ).toBeInTheDocument();
  });

  it('displays loading state', async () => {
    setupContactMocks({ isLoading: true });
    renderContactsPage();

    // Wait for authentication to complete first
    await screen.findByText('Loading contacts...');
    expect(screen.getByText('Loading contacts...')).toBeInTheDocument();
    // Check for skeleton loading cards - they should be present
    const skeletonCards = screen.getAllByRole('generic');
    expect(skeletonCards.length).toBeGreaterThan(0);
  });

  it('displays error state', async () => {
    setupContactMocks({ error: new Error('Failed to load contacts') });
    renderContactsPage();

    expect(
      await screen.findByText('Failed to load contacts')
    ).toBeInTheDocument();
  });

  it('displays contacts list', async () => {
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    expect(await screen.findByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('john@example.com')).toBeInTheDocument();
    expect(screen.getByText('1 contact found')).toBeInTheDocument();
  });

  it('displays empty state when no contacts', async () => {
    setupContactMocks({ data: contactTestUtils.createEmptyContactsResponse() });
    renderContactsPage();

    expect(await screen.findByText('No contacts found')).toBeInTheDocument();
    expect(
      screen.getByText('Get started by adding your first contact')
    ).toBeInTheDocument();
  });

  it('handles search input', async () => {
    const user = userEvent.setup();
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    const searchInput =
      await screen.findByPlaceholderText('Search contacts...');
    await user.type(searchInput, 'John');

    expect(searchInput).toHaveValue('John');
  });

  it('shows and hides filter panel', async () => {
    const user = userEvent.setup();
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    const filtersButton = await screen.findByRole('button', {
      name: /filters/i,
    });

    // Filter panel should not be visible initially
    expect(
      screen.queryByText('Filter by tags (coming soon)')
    ).not.toBeInTheDocument();

    // Click to show filters
    await user.click(filtersButton);
    expect(
      screen.getByText('Filter by tags (coming soon)')
    ).toBeInTheDocument();

    // Click again to hide filters
    await user.click(filtersButton);
    expect(
      screen.queryByText('Filter by tags (coming soon)')
    ).not.toBeInTheDocument();
  });

  describe('tag filtering', () => {
    /** Set up mocks for an active tag filter with a known tag. */
    const setupActiveTagMocks = (tagId = '42', tagName = 'Work') => {
      mockUseTagFilter.mockReturnValue({
        tagId,
        setTag: mockSetTag,
        clearTag: mockClearTag,
      });

      mockUseTags.mockReturnValue({
        data: {
          data: [
            {
              type: 'tags' as const,
              id: tagId,
              attributes: {
                name: tagName,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
              },
            },
          ],
        },
        isLoading: false,
        error: null,
      } as never);
    };

    it('passes tag filter to useInfiniteContacts when tag is active', async () => {
      setupActiveTagMocks();
      setupContactMocks({ data: mockContactsData });
      renderContactsPage();

      await screen.findByText('Work Contacts');

      expect(mockUseInfiniteContacts).toHaveBeenCalledWith(
        expect.objectContaining({ tags: ['42'] }),
        expect.anything()
      );
    });

    it('shows tag name in header when tag is active', async () => {
      setupActiveTagMocks();
      setupContactMocks({ data: mockContactsData });
      renderContactsPage();

      expect(await screen.findByText('Work Contacts')).toBeInTheDocument();
      expect(
        screen.getByText('Contacts tagged with "Work"')
      ).toBeInTheDocument();
    });

    it('shows active tag badge with clear button', async () => {
      setupActiveTagMocks();
      setupContactMocks({ data: mockContactsData });
      renderContactsPage();

      // Tag badge should be visible
      const tagBadge = await screen.findByTestId('active-tag-filter');
      expect(tagBadge).toBeInTheDocument();

      // Clear button
      const clearButton = screen.getByTestId('clear-tag-filter');
      expect(clearButton).toBeInTheDocument();
    });

    it('calls clearTag when tag badge clear button is clicked', async () => {
      const user = userEvent.setup();
      setupActiveTagMocks();
      setupContactMocks({ data: mockContactsData });
      renderContactsPage();

      const clearButton = await screen.findByTestId('clear-tag-filter');
      await user.click(clearButton);

      expect(mockClearTag).toHaveBeenCalledTimes(1);
    });

    it('does not show tag badge when no tag is active', async () => {
      setupContactMocks({ data: mockContactsData });
      renderContactsPage();

      await screen.findByText('Contacts');
      expect(screen.queryByTestId('active-tag-filter')).not.toBeInTheDocument();
    });

    it('shows tag badge with ID fallback when tag name is not resolved', async () => {
      mockUseTagFilter.mockReturnValue({
        tagId: '999',
        setTag: mockSetTag,
        clearTag: mockClearTag,
      });

      // Tags API returns data that does NOT include tag 999
      mockUseTags.mockReturnValue({
        data: { data: [] },
        isLoading: false,
        error: null,
      } as never);

      setupContactMocks({ data: mockContactsData });
      renderContactsPage();

      // Badge should still be visible with ID fallback
      const tagBadge = await screen.findByTestId('active-tag-filter');
      expect(tagBadge).toBeInTheDocument();
      expect(tagBadge).toHaveTextContent('Tag 999');

      // Clear button should still work
      const clearButton = screen.getByTestId('clear-tag-filter');
      expect(clearButton).toBeInTheDocument();
    });
  });

  it('shows clear button when search is active', async () => {
    const user = userEvent.setup();
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    const searchInput =
      await screen.findByPlaceholderText('Search contacts...');

    // No clear button initially
    expect(
      screen.queryByRole('button', { name: /clear/i })
    ).not.toBeInTheDocument();

    // Type in search
    await user.type(searchInput, 'John');

    // Clear button should appear
    expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
  });

  it('clears search when clear button is clicked', async () => {
    const user = userEvent.setup();
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    const searchInput =
      await screen.findByPlaceholderText('Search contacts...');

    // Type in search
    await user.type(searchInput, 'John');
    expect(searchInput).toHaveValue('John');

    // Click clear
    const clearButton = screen.getByRole('button', { name: /clear/i });
    await user.click(clearButton);

    expect(searchInput).toHaveValue('');
  });

  it('displays search results count correctly', async () => {
    setupContactMocks({ data: mockContactsData });
    renderContactsPage();

    expect(await screen.findByText('1 contact found')).toBeInTheDocument();
  });

  it('handles plural contacts count', async () => {
    const multipleContactsData = contactTestUtils.createMockContactsResponse(
      [
        contactTestUtils.createMockContact(),
        contactTestUtils.createMockContact({ id: '2' }),
      ],
      2
    );

    setupContactMocks({ data: multipleContactsData });
    renderContactsPage();

    expect(await screen.findByText('2 contacts found')).toBeInTheDocument();
  });

  it('falls back to loaded contact count when pagination meta total is zero', async () => {
    const visibleContacts = [
      contactTestUtils.createMockContact(),
      contactTestUtils.createMockContact({
        id: '2',
        attributes: {
          first_name: 'Jane',
          last_name: 'Smith',
          middle_name: '',
          nick_name: '',
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
          contact_methods: [],
          addresses: [],
          notes: [],
          relationships: [],
        },
      }),
    ];

    setupContactMocks({
      data: createPaginatedResponse(visibleContacts, { totalCount: 0 }),
    });
    renderContactsPage();

    expect(await screen.findByText('Jane Smith')).toBeInTheDocument();
    expect(screen.getByText('2 contacts found')).toBeInTheDocument();
    expect(screen.queryByText('0 contacts found')).not.toBeInTheDocument();
  });

  it('renders contacts from all loaded infinite-query pages', async () => {
    const firstPage = createPaginatedResponse(
      [contactTestUtils.createMockContact()],
      { totalCount: 2, currentPage: 1, pageCount: 2 }
    );
    const secondPage = createPaginatedResponse(
      [
        contactTestUtils.createMockContact({
          id: '2',
          attributes: {
            first_name: 'Jane',
            last_name: 'Smith',
            middle_name: '',
            nick_name: '',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            contact_methods: [],
            addresses: [],
            notes: [],
            relationships: [],
          },
        }),
      ],
      { totalCount: 2, currentPage: 2, pageCount: 2 }
    );

    setupContactMocks({
      pages: [firstPage, secondPage],
      hasNextPage: true,
    });
    renderContactsPage();

    expect(await screen.findByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('Jane Smith')).toBeInTheDocument();
  });

  it('fetches the next page when the infinite scroll trigger intersects', async () => {
    const fetchNextPage = jest.fn().mockResolvedValue(undefined);

    setupContactMocks({
      pages: [
        createPaginatedResponse([contactTestUtils.createMockContact()], {
          totalCount: 2,
          currentPage: 1,
          pageCount: 2,
        }),
      ],
      hasNextPage: true,
      fetchNextPage,
    });
    renderContactsPage();

    await screen.findByTestId('contacts-infinite-scroll-trigger');

    triggerLastIntersection(true);

    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });
});
