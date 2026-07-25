/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { usePathname } from 'next/navigation';
import { Sidebar, DesktopSidebar, MobileSidebar } from '../Sidebar';
import { useTags } from '@/lib/api/contacts';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  usePathname: jest.fn(),
  useSearchParams: jest.fn(() => new URLSearchParams()),
}));

// Mock the API hooks
jest.mock('@/lib/api/contacts', () => ({
  useTags: jest.fn(),
  useUpdateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useDeleteTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useCreateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useMergeTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
}));

// The sidebar also renders the journal tag tree; these tests are about contact
// navigation, so journal tags stay empty. See Sidebar-journal-tags.test.tsx.
jest.mock('@/lib/api/journals', () => ({
  useJournalTags: jest.fn(() => ({
    data: { data: [] },
    isLoading: false,
    error: null,
  })),
  useCreateJournalTag: jest.fn(() => ({
    mutateAsync: jest.fn(),
    isPending: false,
  })),
  useUpdateJournalTag: jest.fn(() => ({
    mutateAsync: jest.fn(),
    isPending: false,
  })),
}));

const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;
const mockUseTags = useTags as jest.MockedFunction<typeof useTags>;

describe('Sidebar Components', () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue('/contacts');

    // Mock tags data to match the expected test data
    mockUseTags.mockReturnValue({
      data: {
        data: [
          {
            type: 'tags',
            id: '1',
            attributes: {
              name: 'Group 1',
              color: '#ff0000',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
            },
          },
          {
            type: 'tags',
            id: '2',
            attributes: {
              name: 'Group 2',
              color: '#00ff00',
              created_at: '2024-01-01T00:00:00Z',
              updated_at: '2024-01-01T00:00:00Z',
            },
          },
        ],
      },
      isLoading: false,
      isError: false,
      isPending: false,
      isLoadingError: false,
      isRefetchError: false,
      error: null,
      status: 'success',
      fetchStatus: 'idle',
      isSuccess: true,
      isPlaceholderData: false,
      isPaused: false,
      isRefetching: false,
      isStale: false,
      dataUpdatedAt: Date.now(),
      errorUpdatedAt: 0,
      failureCount: 0,
      failureReason: null,
      errorUpdateCount: 0,
      isFetched: true,
      isFetchedAfterMount: true,
      isFetching: false,
      isInitialLoading: false,
      refetch: jest.fn(),
    } as never);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('DesktopSidebar', () => {
    it('renders desktop sidebar with navigation sections', () => {
      render(<DesktopSidebar />);

      // Check that main navigation sections are present
      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('Journals')).toBeInTheDocument();

      // Check that the sidebar has proper ARIA label
      expect(
        screen.getByLabelText('Desktop navigation sidebar')
      ).toBeInTheDocument();
    });

    it('shows contacts section expanded by default', () => {
      render(<DesktopSidebar />);

      // Contacts section should be expanded by default
      const contactsButton = screen.getByRole('button', { name: /contacts/i });
      expect(contactsButton).toHaveAttribute('aria-expanded', 'true');

      // Contact items should be visible
      expect(screen.getByText('All')).toBeInTheDocument();
      expect(screen.getByText('Favourites')).toBeInTheDocument();
      expect(screen.getByText('Group 1')).toBeInTheDocument();
      expect(screen.getByText('Group 2')).toBeInTheDocument();
    });

    it('shows journals section collapsed by default', () => {
      render(<DesktopSidebar />);

      // Journals section should be collapsed by default
      const journalsButton = screen.getByRole('button', { name: /journals/i });
      expect(journalsButton).toHaveAttribute('aria-expanded', 'false');

      // Journal items should not be visible initially
      expect(screen.queryByText('Etc')).not.toBeInTheDocument();
    });

    it('toggles section expansion when clicked', async () => {
      render(<DesktopSidebar />);

      const journalsButton = screen.getByRole('button', { name: /journals/i });

      // Initially collapsed
      expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
      expect(screen.queryByText('Etc')).not.toBeInTheDocument();

      // Click to expand
      fireEvent.click(journalsButton);

      await waitFor(() => {
        expect(journalsButton).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByText('All Journals')).toBeInTheDocument();
        expect(
          screen.getByRole('link', { name: 'Outdoor Logbook' })
        ).toHaveAttribute('href', '/journals/outdoor-logbook');
      });

      // Click to collapse
      fireEvent.click(journalsButton);

      await waitFor(() => {
        expect(journalsButton).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByText('Etc')).not.toBeInTheDocument();
      });
    });

    it('highlights active navigation item', () => {
      mockUsePathname.mockReturnValue('/contacts/favourites');
      render(<DesktopSidebar />);

      const favouritesLink = screen.getByRole('link', { name: /favourites/i });
      expect(favouritesLink).toHaveAttribute('aria-current', 'page');
      expect(favouritesLink).toHaveClass(
        'bg-accent',
        'text-accent-foreground',
        'font-medium'
      );
    });

    it('handles contacts root path correctly', () => {
      mockUsePathname.mockReturnValue('/contacts');
      render(<DesktopSidebar />);

      const allLink = screen.getByRole('link', { name: 'All' });
      expect(allLink).toHaveAttribute('aria-current', 'page');
    });

    it('has proper accessibility attributes', () => {
      render(<DesktopSidebar />);

      // Main navigation has proper role and label
      const nav = screen.getByRole('navigation', { name: 'Main navigation' });
      expect(nav).toBeInTheDocument();

      // Section buttons have proper ARIA attributes
      const contactsButton = screen.getByRole('button', { name: /contacts/i });
      expect(contactsButton).toHaveAttribute('aria-expanded');
      expect(contactsButton).toHaveAttribute(
        'aria-controls',
        'section-contacts'
      );

      // Section groups have proper roles (use getAllByRole since tag tree also adds groups)
      const groups = screen.getAllByRole('group');
      const contactsGroup = groups.find(
        g => g.getAttribute('aria-labelledby') === 'section-contacts-header'
      );
      expect(contactsGroup).toBeDefined();
      expect(contactsGroup).toHaveAttribute(
        'aria-labelledby',
        'section-contacts-header'
      );
    });

    it('has proper keyboard navigation support', () => {
      render(<DesktopSidebar />);

      const contactsButton = screen.getByRole('button', { name: /contacts/i });

      // Button should be focusable
      contactsButton.focus();
      expect(contactsButton).toHaveFocus();

      // Should have focus-visible styles
      expect(contactsButton).toHaveClass('focus-visible:ring-2');
    });
  });

  describe('MobileSidebar', () => {
    it('renders mobile sidebar trigger button', () => {
      render(<MobileSidebar />);

      const triggerButton = screen.getByRole('button', {
        name: 'Open navigation menu',
      });
      expect(triggerButton).toBeInTheDocument();
      expect(triggerButton).toHaveClass('md:hidden'); // Hidden on desktop
    });

    it('opens sheet when trigger is clicked', async () => {
      render(<MobileSidebar />);

      const triggerButton = screen.getByRole('button', {
        name: 'Open navigation menu',
      });
      fireEvent.click(triggerButton);

      await waitFor(() => {
        expect(screen.getByText('Navigation')).toBeInTheDocument();
        expect(screen.getByText('Contacts')).toBeInTheDocument();
        expect(screen.getByText('Journals')).toBeInTheDocument();
      });
    });

    it('closes sheet when navigation item is clicked', async () => {
      render(<MobileSidebar />);

      // Open the sheet
      const triggerButton = screen.getByRole('button', {
        name: 'Open navigation menu',
      });
      fireEvent.click(triggerButton);

      await waitFor(() => {
        expect(screen.getByText('Navigation')).toBeInTheDocument();
      });

      // Click on a navigation item
      const allLink = screen.getByRole('link', { name: 'All' });
      fireEvent.click(allLink);

      // Sheet should close (Navigation title should not be visible)
      await waitFor(() => {
        expect(screen.queryByText('Navigation')).not.toBeInTheDocument();
      });
    });
  });

  describe('Main Sidebar Component', () => {
    it('renders both desktop and mobile sidebars', () => {
      render(<Sidebar />);

      // Should render mobile trigger (visible on mobile)
      expect(
        screen.getByRole('button', { name: 'Open navigation menu' })
      ).toBeInTheDocument();

      // Should render desktop sidebar (visible on desktop)
      expect(
        screen.getByLabelText('Desktop navigation sidebar')
      ).toBeInTheDocument();
    });

    it('applies custom className', () => {
      render(<Sidebar className='custom-class' />);

      const desktopSidebar = screen.getByLabelText(
        'Desktop navigation sidebar'
      );
      expect(desktopSidebar).toHaveClass('custom-class');
    });
  });

  describe('Navigation Logic', () => {
    it('correctly identifies active links for different paths', () => {
      const { useSearchParams: mockUseSearchParamsFn } =
        jest.requireMock('next/navigation');
      const mockSearchParams = mockUseSearchParamsFn as jest.Mock;

      const testCases = [
        {
          pathname: '/contacts',
          searchParams: '',
          expectedActive: 'All',
        },
        {
          pathname: '/contacts/',
          searchParams: '',
          expectedActive: 'All',
        },
        {
          pathname: '/contacts/favourites',
          searchParams: '',
          expectedActive: 'Favourites',
        },
        {
          pathname: '/contacts',
          searchParams: 'tag=1',
          expectedActive: 'Group 1',
        },
        {
          pathname: '/contacts',
          searchParams: 'tag=2',
          expectedActive: 'Group 2',
        },
        {
          pathname: '/journals',
          searchParams: '',
          expectedActive: null, // Journals section collapsed by default
        },
      ];

      testCases.forEach(({ pathname, searchParams, expectedActive }) => {
        mockUsePathname.mockReturnValue(pathname);
        mockSearchParams.mockReturnValue(new URLSearchParams(searchParams));
        const { unmount } = render(<DesktopSidebar />);

        if (expectedActive) {
          const activeLink = screen.getByRole('link', { name: expectedActive });
          expect(activeLink).toHaveAttribute('aria-current', 'page');
        }

        unmount();
      });
    });

    it('handles section state persistence', async () => {
      render(<DesktopSidebar />);

      // Expand journals section
      const journalsButton = screen.getByRole('button', { name: /journals/i });
      fireEvent.click(journalsButton);

      await waitFor(() => {
        expect(screen.getByText('All Journals')).toBeInTheDocument();
      });

      // Collapse contacts section
      const contactsButton = screen.getByRole('button', { name: /contacts/i });
      fireEvent.click(contactsButton);

      await waitFor(() => {
        expect(screen.queryByText('All')).not.toBeInTheDocument();
      });

      // Journals should still be expanded
      expect(screen.getByText('All Journals')).toBeInTheDocument();
    });
  });
});
