/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import ContactsPage from '../page';
import { useContacts, useSearchContacts } from '@/lib/api/contacts';
import { ContactListResponse } from '@/types/contacts';
import {
  renderWithProviders,
  userEvent,
  contactTestUtils,
  setupMocks,
} from '@/test-utils';

jest.mock('@/lib/api/contacts', () => ({
  useContacts: jest.fn(),
  useSearchContacts: jest.fn(),
  useToggleContactFavourite: jest.fn(),
}));

jest.mock('@/hooks/useDebounce', () => ({
  useDebounce: jest.fn(value => value),
}));

// Note: Next.js navigation is mocked globally in jest.setup.ts

const mockUseContacts = useContacts as jest.MockedFunction<typeof useContacts>;
const mockUseSearchContacts = useSearchContacts as jest.MockedFunction<
  typeof useSearchContacts
>;

// Get the mocked function from the module
const mockUseToggleContactFavourite = jest.mocked(
  jest.requireMock('@/lib/api/contacts').useToggleContactFavourite
);

describe('ContactsPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
    setupMocks.clearMocks();
    setupMocks.fetch();

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
  });

  // Test helpers
  const renderContactsPage = () => {
    return renderWithProviders(<ContactsPage />);
  };

  const setupContactMocks = (
    contactsState: {
      data?: ContactListResponse;
      isLoading?: boolean;
      error?: Error | null;
    } = {},
    searchState: {
      data?: ContactListResponse;
      isLoading?: boolean;
      error?: Error | null;
    } = {}
  ) => {
    mockUseContacts.mockReturnValue({
      data: contactsState.data,
      isLoading: contactsState.isLoading ?? false,
      error: contactsState.error ?? null,
      isError: !!contactsState.error,
      isPending: contactsState.isLoading ?? false,
      isSuccess: !contactsState.isLoading && !contactsState.error,
      status: contactsState.isLoading
        ? 'pending'
        : contactsState.error
          ? 'error'
          : 'success',
      refetch: jest.fn(),
    } as any);

    mockUseSearchContacts.mockReturnValue({
      data: searchState.data,
      isLoading: searchState.isLoading ?? false,
      error: searchState.error ?? null,
      isError: !!searchState.error,
      isPending: searchState.isLoading ?? false,
      isSuccess: !searchState.isLoading && !searchState.error,
      status: searchState.isLoading
        ? 'pending'
        : searchState.error
          ? 'error'
          : 'success',
      refetch: jest.fn(),
    } as any);
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
});
