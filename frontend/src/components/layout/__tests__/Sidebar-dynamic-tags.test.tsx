/**
 * @jest-environment jsdom
 */

import { screen } from '@testing-library/react';
import { userEvent } from '@testing-library/user-event';
import { Sidebar } from '../Sidebar';
import { useTags } from '@/lib/api/contacts';
import { TagListResponse } from '@/types/contacts';
import { renderWithProviders } from '@/test-utils';

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useTags: jest.fn(),
  useUpdateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useDeleteTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useCreateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useMergeTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
}));

// Mock Next.js router
jest.mock('next/navigation', () => ({
  usePathname: jest.fn(() => '/contacts'),
  useSearchParams: jest.fn(() => new URLSearchParams()),
}));

const mockUseTags = useTags as jest.MockedFunction<typeof useTags>;

describe('Sidebar - Dynamic Tags', () => {
  it('should display flat tags as navigation items', () => {
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
    } as never);

    renderWithProviders(<Sidebar />);

    // Check that tag names appear as navigation items (alphabetically sorted)
    expect(screen.getByText('Family')).toBeInTheDocument();
    expect(screen.getByText('Work')).toBeInTheDocument();

    // Check that they have the correct links
    const familyLink = screen.getByText('Family').closest('a');
    const workLink = screen.getByText('Work').closest('a');

    expect(familyLink).toHaveAttribute('href', '/contacts?tag=2');
    expect(workLink).toHaveAttribute('href', '/contacts?tag=1');
  });

  it('should render hierarchical tags nested under parent', () => {
    const mockTagsData: TagListResponse = {
      data: [
        {
          type: 'tags',
          id: '1',
          attributes: {
            name: 'Work',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
        {
          type: 'tags',
          id: '2',
          attributes: {
            name: 'Engineering',
            parent_id: 1,
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
        {
          type: 'tags',
          id: '3',
          attributes: {
            name: 'Design',
            parent_id: 1,
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
    } as never);

    renderWithProviders(<Sidebar />);

    // Parent tag should be visible
    expect(screen.getByText('Work')).toBeInTheDocument();

    // Parent tag should have expand toggle
    const expandButton = screen.getByTestId('tag-toggle-1');
    expect(expandButton).toBeInTheDocument();
    expect(expandButton).toHaveAttribute('aria-expanded', 'false');

    // Children should NOT be visible initially (collapsed)
    expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    expect(screen.queryByText('Design')).not.toBeInTheDocument();
  });

  it('should expand and collapse tag tree children on click', async () => {
    const user = userEvent.setup();

    const mockTagsData: TagListResponse = {
      data: [
        {
          type: 'tags',
          id: '1',
          attributes: {
            name: 'Work',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
          },
        },
        {
          type: 'tags',
          id: '2',
          attributes: {
            name: 'Engineering',
            parent_id: 1,
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
    } as never);

    renderWithProviders(<Sidebar />);

    // Click expand toggle
    const expandButton = screen.getByTestId('tag-toggle-1');
    await user.click(expandButton);

    // Child should now be visible
    expect(screen.getByText('Engineering')).toBeInTheDocument();
    expect(expandButton).toHaveAttribute('aria-expanded', 'true');

    // Click again to collapse
    await user.click(expandButton);
    expect(screen.queryByText('Engineering')).not.toBeInTheDocument();
    expect(expandButton).toHaveAttribute('aria-expanded', 'false');
  });

  it('should not show expand toggle for leaf tags', () => {
    const mockTagsData: TagListResponse = {
      data: [
        {
          type: 'tags',
          id: '1',
          attributes: {
            name: 'Simple',
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
    } as never);

    renderWithProviders(<Sidebar />);

    expect(screen.getByText('Simple')).toBeInTheDocument();
    expect(screen.queryByTestId('tag-toggle-simple')).not.toBeInTheDocument();
  });

  it('should show loading state when tags are loading', () => {
    mockUseTags.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as never);

    renderWithProviders(<Sidebar />);

    // Should show loading placeholder or skeleton
    expect(screen.getByText('Loading tags...')).toBeInTheDocument();
  });

  it('should handle empty tags list', () => {
    mockUseTags.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    } as never);

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
    } as never);

    renderWithProviders(<Sidebar />);

    // Should still show basic navigation
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Favourites')).toBeInTheDocument();

    // Should not crash or show error in sidebar
    expect(screen.queryByText('Failed to load tags')).not.toBeInTheDocument();
  });

  it('should render scroll area for tag tree', () => {
    const mockTagsData: TagListResponse = {
      data: [
        {
          type: 'tags',
          id: '1',
          attributes: {
            name: 'Tag1',
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
    } as never);

    renderWithProviders(<Sidebar />);

    expect(screen.getByTestId('tag-tree-container')).toBeInTheDocument();
  });
});
