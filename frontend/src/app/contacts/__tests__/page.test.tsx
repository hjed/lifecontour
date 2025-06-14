/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import ContactsPage from '../page';
import { useContacts, useSearchContacts } from '@/lib/api/contacts';
import { ContactListResponse } from '@/types/contacts';
import { renderWithProviders, userEvent, contactTestUtils } from '@/test-utils';

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useContacts: jest.fn(),
  useSearchContacts: jest.fn(),
}));

// Mock the debounce hook
jest.mock('@/hooks/useDebounce', () => ({
  useDebounce: jest.fn(value => value),
}));

// Mock the constants
jest.mock('@/lib/constants', () => ({
  TIMEOUTS: {
    DEBOUNCE_SEARCH: 300,
  },
}));

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
  useSearchParams: () => ({
    get: jest.fn(),
  }),
}));

const mockUseContacts = useContacts as jest.MockedFunction<typeof useContacts>;
const mockUseSearchContacts = useSearchContacts as jest.MockedFunction<
  typeof useSearchContacts
>;

describe('ContactsPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
  });

  // Test helpers
  const renderContactsPage = () => {
    return renderWithProviders(<ContactsPage />);
  };

  const setupMocks = (
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
    } as any);

    mockUseSearchContacts.mockReturnValue({
      data: searchState.data,
      isLoading: searchState.isLoading ?? false,
      error: searchState.error ?? null,
    } as any);
  };

  const mockContactsData = contactTestUtils.createMockContactsResponse();

  it('renders the contacts page with header', () => {
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    expect(screen.getByText('Contacts')).toBeInTheDocument();
    expect(
      screen.getByText('Manage your personal and professional contacts')
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: /add contact/i })
    ).toBeInTheDocument();
  });

  it('displays loading state', () => {
    setupMocks({ isLoading: true });
    renderContactsPage();

    expect(screen.getByText('Loading contacts...')).toBeInTheDocument();
    // Check for skeleton loading cards - they should be present
    const skeletonCards = screen.getAllByRole('generic');
    expect(skeletonCards.length).toBeGreaterThan(0);
  });

  it('displays error state', () => {
    setupMocks({ error: new Error('Failed to load contacts') });
    renderContactsPage();

    expect(screen.getByText('Failed to load contacts')).toBeInTheDocument();
  });

  it('displays contacts list', () => {
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByText('john@example.com')).toBeInTheDocument();
    expect(screen.getByText('1 contact found')).toBeInTheDocument();
  });

  it('displays empty state when no contacts', () => {
    setupMocks({ data: contactTestUtils.createEmptyContactsResponse() });
    renderContactsPage();

    expect(screen.getByText('No contacts found')).toBeInTheDocument();
    expect(
      screen.getByText('Get started by adding your first contact')
    ).toBeInTheDocument();
  });

  it('handles search input', async () => {
    const user = userEvent.setup();
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    const searchInput = screen.getByPlaceholderText('Search contacts...');
    await user.type(searchInput, 'John');

    expect(searchInput).toHaveValue('John');
  });

  it('shows and hides filter panel', async () => {
    const user = userEvent.setup();
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    const filtersButton = screen.getByRole('button', { name: /filters/i });

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
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    const searchInput = screen.getByPlaceholderText('Search contacts...');

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
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    const searchInput = screen.getByPlaceholderText('Search contacts...');

    // Type in search
    await user.type(searchInput, 'John');
    expect(searchInput).toHaveValue('John');

    // Click clear
    const clearButton = screen.getByRole('button', { name: /clear/i });
    await user.click(clearButton);

    expect(searchInput).toHaveValue('');
  });

  it('displays search results count correctly', () => {
    setupMocks({ data: mockContactsData });
    renderContactsPage();

    expect(screen.getByText('1 contact found')).toBeInTheDocument();
  });

  it('handles plural contacts count', () => {
    const multipleContactsData = contactTestUtils.createMockContactsResponse(
      [
        contactTestUtils.createMockContact(),
        contactTestUtils.createMockContact({ id: '2' }),
      ],
      2
    );

    setupMocks({ data: multipleContactsData });
    renderContactsPage();

    expect(screen.getByText('2 contacts found')).toBeInTheDocument();
  });
});
