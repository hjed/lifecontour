/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import { Sidebar } from '../Sidebar';
import { useTags } from '@/lib/api/contacts';
import { TagListResponse } from '@/types/contacts';
import { renderWithProviders } from '@/test-utils';

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useTags: jest.fn(),
}));

// Mock Next.js router
jest.mock('next/navigation', () => ({
  usePathname: jest.fn(() => '/contacts'),
}));

const mockUseTags = useTags as jest.MockedFunction<typeof useTags>;

describe('Sidebar - Dynamic Tags', () => {
  it('should display tags as navigation items', () => {
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
        {
          type: 'tags',
          id: '2',
          attributes: {
            name: 'Family',
            color: '#38A169',
            description: 'Family contacts',
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

    renderWithProviders(<Sidebar />);

    // Check that tag names appear as navigation items
    expect(screen.getByText('Work')).toBeInTheDocument();
    expect(screen.getByText('Family')).toBeInTheDocument();

    // Check that they have the correct links
    const workLink = screen.getByText('Work').closest('a');
    const familyLink = screen.getByText('Family').closest('a');

    expect(workLink).toHaveAttribute('href', '/contacts/tags/1');
    expect(familyLink).toHaveAttribute('href', '/contacts/tags/2');
  });

  it('should show loading state when tags are loading', () => {
    mockUseTags.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as any);

    renderWithProviders(<Sidebar />);

    // Should show loading placeholder or skeleton
    expect(screen.getByText('Loading tags...')).toBeInTheDocument();
  });

  it('should handle empty tags list', () => {
    mockUseTags.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    } as any);

    renderWithProviders(<Sidebar />);

    // Should still show All and Favourites
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Favourites')).toBeInTheDocument();

    // Should not show any tag items
    expect(screen.queryByText('Work')).not.toBeInTheDocument();
    expect(screen.queryByText('Family')).not.toBeInTheDocument();
  });

  it('should handle tags API error gracefully', () => {
    mockUseTags.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Failed to load tags'),
    } as any);

    renderWithProviders(<Sidebar />);

    // Should still show basic navigation
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Favourites')).toBeInTheDocument();

    // Should not crash or show error in sidebar
    expect(screen.queryByText('Failed to load tags')).not.toBeInTheDocument();
  });
});
