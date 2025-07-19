/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import ContactGroupPage from '../page';
import { useContacts, useTags } from '@/lib/api/contacts';
import { TagListResponse } from '@/types/contacts';
import {
  renderWithProviders,
  setupMocks,
  contactTestUtils,
} from '@/test-utils';

// Mock Next.js router
jest.mock('next/navigation', () => ({
  useParams: jest.fn(() => ({ id: '1' })),
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    refresh: jest.fn(),
    replace: jest.fn(),
  })),
  usePathname: jest.fn(() => '/contacts/tags/1'),
}));

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useContacts: jest.fn(),
  useTags: jest.fn(),
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
const mockUseTags = useTags as jest.MockedFunction<typeof useTags>;

describe('ContactGroupPage', () => {
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

  it('should call useContacts with tag filter', async () => {
    const mockTagsData: TagListResponse = {
      data: [
        {
          type: 'tags',
          id: '1',
          attributes: {
            name: 'Work',
            color: '#3182CE',
            description: 'Work contacts',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
      ],
    };

    mockUseTags.mockReturnValue({
      data: mockTagsData,
      isLoading: false,
      error: null,
    } as any);

    mockUseContacts.mockReturnValue({
      data: { data: [], meta: { total: 0, page: 1, limit: 20 } },
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<ContactGroupPage />);

    // Wait for authentication to complete and page to load
    await screen.findByText('Work Contacts');

    expect(mockUseContacts).toHaveBeenCalledWith({ tags: ['1'] });
  });

  it('should show empty state when no contacts in tag', async () => {
    const mockTagsData: TagListResponse = {
      data: [
        {
          type: 'tags',
          id: '1',
          attributes: {
            name: 'Work',
            color: '#3182CE',
            description: 'Work contacts',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
      ],
    };

    mockUseTags.mockReturnValue({
      data: mockTagsData,
      isLoading: false,
      error: null,
    } as any);

    mockUseContacts.mockReturnValue({
      data: { data: [], meta: { total: 0, page: 1, limit: 20 } },
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<ContactGroupPage />);

    expect(
      await screen.findByText('No contacts found in this tag')
    ).toBeInTheDocument();
    expect(
      screen.getByText('Add some contacts to the "Work" tag to see them here')
    ).toBeInTheDocument();
  });

  it('should handle tag not found', async () => {
    mockUseTags.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    } as any);

    mockUseContacts.mockReturnValue({
      data: { data: [], meta: { total: 0, page: 1, limit: 20 } },
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<ContactGroupPage />);

    expect(
      await screen.findByRole('heading', { name: 'Tag Not Found', level: 1 })
    ).toBeInTheDocument();
    expect(
      screen.getByText('The requested tag could not be found.')
    ).toBeInTheDocument();
  });
});
