/**
 * @jest-environment jsdom
 *
 * The dashboard's primary-navigation entry (ITER18-004 Phase 3).
 *
 * The specification asks for the home page to be reachable from the primary
 * navigation as the post-sign-in default; the wireframe's sidebar shows only
 * Contacts / Journals / Integrations, so this is a deliberate addition to it
 * (wireframe gap 4).
 *
 * Home is a top-level link rather than a section, because every other sidebar
 * entry is a collapsible section and one that collapsed to hide its own single
 * item would be a worse affordance than a plain link — for keyboard and screen
 * reader users most of all.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { usePathname } from 'next/navigation';
import { DesktopSidebar, MobileSidebar } from '../Sidebar';
import { useTags } from '@/lib/api/contacts';

jest.mock('next/navigation', () => ({
  usePathname: jest.fn(),
  useSearchParams: jest.fn(() => new URLSearchParams()),
}));

jest.mock('@/lib/api/contacts', () => ({
  useTags: jest.fn(),
  useUpdateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useDeleteTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useCreateTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
  useMergeTag: jest.fn(() => ({ mutateAsync: jest.fn(), isPending: false })),
}));

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

describe('Sidebar — the home dashboard entry', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUsePathname.mockReturnValue('/');
    mockUseTags.mockReturnValue({
      data: { data: [] },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useTags>);
  });

  function homeLink() {
    return screen.getByTestId('nav-link-home');
  }

  it('offers Home as a link to the dashboard', () => {
    render(<DesktopSidebar />);

    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute(
      'href',
      '/'
    );
  });

  it('sits at the top of the navigation, ahead of the sections', () => {
    render(<DesktopSidebar />);

    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    const contactsSection = screen.getByRole('button', { name: /contacts/i });

    expect(
      homeLink().compareDocumentPosition(contactsSection) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(nav).toContainElement(homeLink());
  });

  it('is not inside a collapsible section, so it cannot be hidden', () => {
    render(<DesktopSidebar />);

    expect(homeLink().closest('[role="group"]')).toBeNull();
  });

  it('marks itself the current page on the dashboard', () => {
    mockUsePathname.mockReturnValue('/');
    render(<DesktopSidebar />);

    expect(homeLink()).toHaveAttribute('aria-current', 'page');
    expect(homeLink()).toHaveClass(
      'bg-accent',
      'text-accent-foreground',
      'font-medium'
    );
  });

  /**
   * The trap this entry walks into: the shared predicate ends in
   * `pathname.startsWith(href)`, and **every** path starts with `/`. Without an
   * exact-match branch for the root, Home would read as the current page
   * everywhere in the app.
   */
  it.each(['/contacts', '/contacts/favourites', '/journals', '/integrations'])(
    'is not the current page on %s',
    pathname => {
      mockUsePathname.mockReturnValue(pathname);
      render(<DesktopSidebar />);

      expect(homeLink()).not.toHaveAttribute('aria-current');
      expect(homeLink()).not.toHaveClass('bg-accent');
    }
  );

  it('does not steal the current-page marker from the route that owns it', () => {
    mockUsePathname.mockReturnValue('/contacts');
    render(<DesktopSidebar />);

    expect(screen.getByRole('link', { name: 'All' })).toHaveAttribute(
      'aria-current',
      'page'
    );
  });

  it('is reachable from the mobile navigation and closes it on use', async () => {
    mockUsePathname.mockReturnValue('/contacts');
    render(<MobileSidebar />);

    fireEvent.click(screen.getByTestId('mobile-nav-trigger'));

    await waitFor(() => {
      expect(screen.getByTestId('nav-link-home')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('nav-link-home'));

    await waitFor(() => {
      expect(screen.queryByTestId('nav-link-home')).not.toBeInTheDocument();
    });
  });
});
