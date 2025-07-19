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

describe('FavouritesPage', () => {
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
