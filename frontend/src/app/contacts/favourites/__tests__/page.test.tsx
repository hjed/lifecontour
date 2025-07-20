/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import FavouritesPage from '../page';
import { useContacts } from '@/lib/api/contacts';
import { ContactListResponse } from '@/types/contacts';
import {
  renderWithProviders,
  setupMocks,
  contactTestUtils,
} from '@/test-utils';
import { useAuth } from '@/lib/auth/AuthProvider';
import { AuthState, SessionUser, OAuthProvider } from '@/types/auth';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    replace: jest.fn(),
  })),
  usePathname: jest.fn(() => '/contacts/favourites'),
}));

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useContacts: jest.fn(),
}));

// Mock the auth provider
jest.mock('@/lib/auth/AuthProvider', () => ({
  useAuth: jest.fn(),
  AuthProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

// Mock the constants
jest.mock('@/lib/constants', () => ({
  DATE_FORMATS: {
    SHORT: 'dd/MM/yyyy',
    LONG: 'dd MMMM yyyy',
    WITH_TIME: 'dd/MM/yyyy HH:mm',
    TIME_ONLY: 'HH:mm',
    ISO: 'yyyy-MM-dd',
  },
  ERROR_MESSAGES: {
    SESSION_EXPIRED: 'Your session has expired. Please log in again.',
    NETWORK_ERROR: 'Network error. Please check your connection.',
    UNAUTHORIZED: 'You are not authorized to access this resource.',
    FORBIDDEN: 'Access to this resource is forbidden.',
    NOT_FOUND: 'The requested resource was not found.',
    SERVER_ERROR: 'An internal server error occurred.',
    VALIDATION_ERROR: 'Please check your input and try again.',
    UNKNOWN_ERROR: 'An unknown error occurred.',
  },
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

const mockUseContacts = useContacts as jest.MockedFunction<typeof useContacts>;
const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

// Test helper to create mock SessionUser
const createMockUser = (overrides: Partial<SessionUser> = {}): SessionUser => ({
  id: '1',
  email: 'test@example.com',
  name: 'Test User',
  provider: 'github' as OAuthProvider,
  provider_id: 'github_123',
  created_at: '2023-01-01T00:00:00Z',
  last_login: '2023-01-01T00:00:00Z',
  ...overrides,
});

describe('FavouritesPage', () => {
  beforeEach(() => {
    contactTestUtils.setupContactTest();
    setupMocks.clearMocks();
    setupMocks.fetch();

    // Mock authenticated user using useAuth hook
    mockUseAuth.mockReturnValue({
      state: {
        isLoading: false,
        isAuthenticated: true,
        user: createMockUser(),
        error: undefined,
      } as AuthState,
      login: jest.fn(),
      logout: jest.fn(),
      refreshSession: jest.fn(),
      clearError: jest.fn(),
    });
  });

  it('should display only favourite contacts', async () => {
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
          },
        },
      ],
      meta: { total: 1, page: 1, limit: 20 },
    };

    mockUseContacts.mockReturnValue({
      data: mockData,
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<FavouritesPage />);

    // Check page title
    expect(await screen.findByText('Favourite Contacts')).toBeInTheDocument();

    // Check that contact is displayed
    expect(screen.getByText('John Doe')).toBeInTheDocument();
  });

  it('should call useContacts with favourite filter', async () => {
    mockUseContacts.mockReturnValue({
      data: { data: [], meta: { total: 0, page: 1, limit: 20 } },
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<FavouritesPage />);

    // Wait for authentication to complete
    await screen.findByText('Favourite Contacts');

    expect(mockUseContacts).toHaveBeenCalledWith({ favourite: true });
  });

  it('should show empty state when no favourites', async () => {
    mockUseContacts.mockReturnValue({
      data: { data: [], meta: { total: 0, page: 1, limit: 20 } },
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<FavouritesPage />);

    expect(
      await screen.findByText('No favourite contacts found')
    ).toBeInTheDocument();
    expect(
      screen.getByText('Star some contacts to see them here')
    ).toBeInTheDocument();
  });
});
