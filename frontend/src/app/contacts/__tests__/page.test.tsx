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
  API_ENDPOINTS: {
    AUTH: {
      LOGIN: '/api/auth/login',
      LOGOUT: '/api/auth/logout',
      SESSION: '/api/auth/session',
      CALLBACK: '/api/auth/callback',
      PROVIDERS: '/api/auth/providers',
    },
    CONTACTS: {
      BASE: '/api/contacts',
      SEARCH: '/api/contacts/search',
    },
  },
  HTTP_HEADERS: {
    CONTENT_TYPE: 'Content-Type',
    APPLICATION_JSON: 'application/json',
    AUTHORIZATION: 'Authorization',
  },
  ERROR_MESSAGES: {
    LOGIN_FAILED: 'Login failed',
    LOGOUT_FAILED: 'Logout failed',
    AUTH_FAILED: 'Authentication failed',
    SESSION_EXPIRED: 'Your session has expired. Please sign in again.',
    OAUTH_ERROR: 'OAuth error',
    MISSING_OAUTH_PARAMS: 'Missing required OAuth parameters',
    NETWORK_ERROR: 'Network error occurred',
    UNKNOWN_ERROR: 'An unknown error occurred',
    FETCH_FAILED: 'Failed to fetch data. Please try again.',
  },
  SUCCESS_MESSAGES: {
    SIGNED_IN: 'Successfully signed in',
    SIGNED_OUT: 'Successfully signed out',
    CONTACT_CREATED: 'Contact created successfully',
    CONTACT_UPDATED: 'Contact updated successfully',
    CONTACT_DELETED: 'Contact deleted successfully',
  },
  OAUTH_PROVIDER_NAMES: {
    GITHUB: 'GitHub',
    MICROSOFT: 'Microsoft',
    DISCORD: 'Discord',
    GENERIC: 'Generic',
  },
  OAUTH_PROVIDER_ICONS: {
    GITHUB: 'github',
    MICROSOFT: 'microsoft',
    DISCORD: 'discord',
    GENERIC: 'generic',
  },
  OAUTH_PROVIDER_COLORS: {
    GITHUB: '#333',
    MICROSOFT: '#0078d4',
    DISCORD: '#5865f2',
    GENERIC: '#666',
  },
  AUTH_STORAGE_KEYS: {
    SESSION: 'auth_session',
    CSRF_TOKEN: 'csrf_token',
  },
  TIMEOUTS: {
    DEBOUNCE_SEARCH: 300,
  },
  UI_TEXT: {
    WELCOME_BACK: 'Welcome Back',
    SIGN_IN_DESCRIPTION: 'Sign in to your Personal Management System',
    CONTINUE_WITH: 'Continue with',
    CONNECTING_TO: 'Connecting to',
    PRIVACY_NOTICE:
      'By signing in, you agree to our terms of service and privacy policy.',
    PRIVATE_APP_NOTICE: 'This is a private application for personal use only.',
    LOADING: 'Loading',
    CHECKING_AUTH: 'Checking your authentication status',
    PLEASE_WAIT: 'Please wait...',
    COMPLETING_SIGN_IN: 'Completing Sign In',
    FINISH_SESSION_SETUP: 'Please wait while we finish setting up your session',
    SHOULD_TAKE_MOMENT: 'This should only take a moment...',
    AUTH_FAILED: 'Authentication Failed',
    PROBLEM_SIGNING_IN: 'There was a problem signing you in',
    TRY_AGAIN: 'Try signing in again',
  },
}));

// Note: Next.js navigation is mocked globally in jest.setup.ts

const mockUseContacts = useContacts as jest.MockedFunction<typeof useContacts>;
const mockUseSearchContacts = useSearchContacts as jest.MockedFunction<
  typeof useSearchContacts
>;

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
