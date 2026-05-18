/**
 * @jest-environment jsdom
 */

import { screen, waitFor } from '@testing-library/react';
import NewContactPage from '../page';
import { useCreateContact } from '@/lib/api/contacts';
import {
  renderWithProviders,
  userEvent,
  contactTestUtils,
  setupMocks,
} from '@/test-utils';

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useCreateContact: jest.fn(),
}));

// Create trackable mock for router
const mockRouterPush = jest.fn();
const mockRouter = {
  push: mockRouterPush,
  replace: jest.fn(),
  prefetch: jest.fn(),
  back: jest.fn(),
  forward: jest.fn(),
  refresh: jest.fn(),
};

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: () => mockRouter,
  usePathname: () => '/contacts/new',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

// Mock constants
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
  VALIDATION_MESSAGES: {
    REQUIRED_FIELD: 'This field is required',
  },
  DATE_FORMATS: {
    SHORT: 'dd/MM/yyyy',
    LONG: 'dd MMMM yyyy',
    WITH_TIME: 'dd/MM/yyyy HH:mm',
    TIME_ONLY: 'HH:mm',
    ISO: 'yyyy-MM-dd',
  },
}));

const mockUseCreateContact = useCreateContact as jest.MockedFunction<
  typeof useCreateContact
>;

describe('NewContactPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
    setupMocks.clearMocks();
    setupMocks.fetch();
    mockRouterPush.mockClear();

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

  const renderNewContactPage = () => {
    return renderWithProviders(<NewContactPage />);
  };

  it('renders the new contact page', async () => {
    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and page to load
    expect(await screen.findByText('Add New Contact')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Create a new contact with their information and details'
      )
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /back to contacts/i })
    ).toBeInTheDocument();
  });

  it('renders the contact form', async () => {
    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and form to load
    expect(await screen.findByLabelText(/first name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/last name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/middle name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/nickname/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /save contact/i })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it('handles back navigation', async () => {
    const user = userEvent.setup();

    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and page to load
    const backButton = await screen.findByRole('button', {
      name: /back to contacts/i,
    });
    await user.click(backButton);

    expect(mockRouterPush).toHaveBeenCalledWith('/contacts');
  });

  it('handles cancel navigation', async () => {
    const user = userEvent.setup();

    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and page to load
    const cancelButton = await screen.findByRole('button', { name: /cancel/i });
    await user.click(cancelButton);

    expect(mockRouterPush).toHaveBeenCalledWith('/contacts');
  });

  it('handles form submission', async () => {
    const user = userEvent.setup();
    const mockCreateMutation = jest.fn().mockResolvedValue({
      data: { id: '123' },
    });

    mockUseCreateContact.mockReturnValue({
      mutateAsync: mockCreateMutation,
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and form to load
    // Fill in the form
    const firstNameInput = await screen.findByLabelText(/first name/i);
    const lastNameInput = screen.getByLabelText(/last name/i);

    await user.type(firstNameInput, 'John');
    await user.type(lastNameInput, 'Doe');

    // Submit the form
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutation).toHaveBeenCalledWith({
        first_name: 'John',
        last_name: 'Doe',
        middle_name: '',
        nick_name: '',
        contact_methods: [],
        addresses: [],
        notes: [],
        important_dates: [],
      });
    });

    // Should navigate to the created contact
    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/contacts/123');
    });
  });

  it('handles form submission with all fields', async () => {
    const user = userEvent.setup();
    const mockCreateMutation = jest.fn().mockResolvedValue({
      data: { id: '456' },
    });

    mockUseCreateContact.mockReturnValue({
      mutateAsync: mockCreateMutation,
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and form to load
    // Fill in all form fields
    await user.type(await screen.findByLabelText(/first name/i), 'Jane');
    await user.type(screen.getByLabelText(/last name/i), 'Smith');
    await user.type(screen.getByLabelText(/middle name/i), 'Marie');
    await user.type(screen.getByLabelText(/nickname/i), 'Janie');

    // Submit the form
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutation).toHaveBeenCalledWith({
        first_name: 'Jane',
        last_name: 'Smith',
        middle_name: 'Marie',
        nick_name: 'Janie',
        contact_methods: [],
        addresses: [],
        notes: [],
        important_dates: [],
      });
    });

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith('/contacts/456');
    });
  });

  it('handles form submission error', async () => {
    const user = userEvent.setup();
    const mockCreateMutation = jest
      .fn()
      .mockRejectedValue(new Error('Creation failed'));

    // Suppress console.error for this test since we expect an error
    const consoleSpy = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    mockUseCreateContact.mockReturnValue({
      mutateAsync: mockCreateMutation,
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and form to load
    // Fill in the form
    await user.type(await screen.findByLabelText(/first name/i), 'John');

    // Submit the form
    const saveButton = screen.getByRole('button', { name: /save contact/i });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutation).toHaveBeenCalled();
    });

    // Form should still be visible after error
    expect(screen.getByLabelText(/first name/i)).toBeInTheDocument();

    // Restore console.error
    consoleSpy.mockRestore();
  });

  it('shows loading state during submission', async () => {
    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: true,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and page to load
    expect(
      await screen.findByRole('button', { name: /saving/i })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled();
  });

  it('validates required fields', async () => {
    const user = userEvent.setup();

    mockUseCreateContact.mockReturnValue({
      mutateAsync: jest.fn(),
      isPending: false,
    } as never);

    renderNewContactPage();

    // Wait for authentication to complete and page to load
    // Try to submit without filling required fields
    const saveButton = await screen.findByRole('button', {
      name: /save contact/i,
    });
    await user.click(saveButton);

    // Should show validation error
    await waitFor(() => {
      expect(screen.getByText(/this field is required/i)).toBeInTheDocument();
    });
  });
});
