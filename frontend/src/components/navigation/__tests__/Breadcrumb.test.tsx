/**
 * @jest-environment jsdom
 */

import { render, screen } from '@testing-library/react';
import { usePathname } from 'next/navigation';
import { Breadcrumb, BreadcrumbSeparator, BreadcrumbItem } from '../Breadcrumb';

// Mock Next.js navigation
jest.mock('next/navigation', () => ({
  usePathname: jest.fn(),
}));

const mockUsePathname = usePathname as jest.MockedFunction<typeof usePathname>;

describe('Breadcrumb', () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue('/contacts');
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('basic rendering', () => {
    it('renders breadcrumb navigation', () => {
      mockUsePathname.mockReturnValue('/contacts/favourites');
      render(<Breadcrumb />);

      expect(
        screen.getByRole('navigation', { name: 'Breadcrumb navigation' })
      ).toBeInTheDocument();
      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('Favourites')).toBeInTheDocument();
    });

    it('does not render on home page', () => {
      mockUsePathname.mockReturnValue('/');
      render(<Breadcrumb />);

      expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    });

    it('does not render when no breadcrumb items', () => {
      mockUsePathname.mockReturnValue('');
      render(<Breadcrumb />);

      expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    });

    it('applies custom className', () => {
      mockUsePathname.mockReturnValue('/contacts');
      render(<Breadcrumb className='custom-class' />);

      const nav = screen.getByRole('navigation');
      expect(nav).toHaveClass('custom-class');
    });
  });

  describe('home icon', () => {
    it('shows home icon by default', () => {
      mockUsePathname.mockReturnValue('/contacts');
      render(<Breadcrumb />);

      const homeLink = screen.getByLabelText('Go to home page');
      expect(homeLink).toBeInTheDocument();
      expect(homeLink).toHaveAttribute('href', '/');
    });

    it('hides home icon when showHome is false', () => {
      mockUsePathname.mockReturnValue('/contacts');
      render(<Breadcrumb showHome={false} />);

      expect(
        screen.queryByLabelText('Go to home page')
      ).not.toBeInTheDocument();
    });
  });

  describe('breadcrumb generation', () => {
    it('generates breadcrumbs for simple path', () => {
      mockUsePathname.mockReturnValue('/contacts');
      render(<Breadcrumb />);

      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('Contacts')).toHaveAttribute(
        'aria-current',
        'page'
      );
    });

    it('generates breadcrumbs for nested path', () => {
      mockUsePathname.mockReturnValue('/contacts/favourites');
      render(<Breadcrumb />);

      const contactsLink = screen.getByRole('link', { name: 'Contacts' });
      expect(contactsLink).toHaveAttribute('href', '/contacts');
      expect(contactsLink).not.toHaveAttribute('aria-current');

      const favouritesText = screen.getByText('Favourites');
      expect(favouritesText).toHaveAttribute('aria-current', 'page');
      expect(favouritesText.tagName).toBe('SPAN');
    });

    it('generates breadcrumbs for dynamic routes', () => {
      mockUsePathname.mockReturnValue('/contacts/groups/1');
      render(<Breadcrumb />);

      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('Groups')).toBeInTheDocument();
      expect(screen.getByText('Group 1')).toBeInTheDocument();
    });

    it('handles contact detail pages', () => {
      mockUsePathname.mockReturnValue('/contacts/123');
      render(<Breadcrumb />);

      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('Contact Details')).toBeInTheDocument();
    });

    it('handles unknown dynamic routes', () => {
      mockUsePathname.mockReturnValue('/unknown/456');
      render(<Breadcrumb />);

      expect(screen.getByText('unknown')).toBeInTheDocument();
      expect(screen.getByText('#456')).toBeInTheDocument();
    });

    it('handles journals path', () => {
      mockUsePathname.mockReturnValue('/journals');
      render(<Breadcrumb />);

      expect(screen.getByText('Journals')).toBeInTheDocument();
    });

    it('handles new/edit pages', () => {
      mockUsePathname.mockReturnValue('/contacts/new');
      render(<Breadcrumb />);

      expect(screen.getByText('Contacts')).toBeInTheDocument();
      expect(screen.getByText('New')).toBeInTheDocument();
    });
  });

  describe('custom items', () => {
    it('uses custom items when provided', () => {
      const customItems = [
        { label: 'Custom', href: '/custom', isActive: false },
        { label: 'Page', href: '/custom/page', isActive: true },
      ];

      render(<Breadcrumb customItems={customItems} />);

      const customLink = screen.getByRole('link', { name: 'Custom' });
      expect(customLink).toHaveAttribute('href', '/custom');

      const pageText = screen.getByText('Page');
      expect(pageText).toHaveAttribute('aria-current', 'page');
    });

    it('shows home icon with custom items', () => {
      const customItems = [
        { label: 'Custom', href: '/custom', isActive: true },
      ];

      render(<Breadcrumb customItems={customItems} />);

      expect(screen.getByLabelText('Go to home page')).toBeInTheDocument();
      expect(screen.getByText('Custom')).toBeInTheDocument();
    });
  });

  describe('separators', () => {
    it('shows separators between items', () => {
      mockUsePathname.mockReturnValue('/contacts/favourites');
      const { container } = render(<Breadcrumb />);

      // Should have separators between home -> contacts -> favourites
      // Look specifically for ChevronRight icons, not all SVGs with aria-hidden
      const separators = container.querySelectorAll(
        'svg[aria-hidden="true"] path[d="m9 18 6-6-6-6"]'
      );
      expect(separators).toHaveLength(2); // One after home, one after contacts
    });

    it('does not show separator before first item when no home', () => {
      mockUsePathname.mockReturnValue('/contacts');
      const { container } = render(<Breadcrumb showHome={false} />);

      const separators = container.querySelectorAll(
        'svg[aria-hidden="true"] path[d="m9 18 6-6-6-6"]'
      );
      expect(separators).toHaveLength(0);
    });
  });

  describe('accessibility', () => {
    it('has proper ARIA attributes', () => {
      mockUsePathname.mockReturnValue('/contacts/favourites');
      render(<Breadcrumb />);

      const nav = screen.getByRole('navigation', {
        name: 'Breadcrumb navigation',
      });
      expect(nav).toBeInTheDocument();

      const list = screen.getByRole('list');
      expect(list).toBeInTheDocument();

      const activeItem = screen.getByText('Favourites');
      expect(activeItem).toHaveAttribute('aria-current', 'page');
    });

    it('has screen reader text for home icon', () => {
      mockUsePathname.mockReturnValue('/contacts');
      render(<Breadcrumb />);

      expect(screen.getByText('Home')).toHaveClass('sr-only');
    });

    it('marks separators as hidden from screen readers', () => {
      mockUsePathname.mockReturnValue('/contacts/favourites');
      const { container } = render(<Breadcrumb />);

      const separators = container.querySelectorAll(
        'svg[aria-hidden="true"] path[d="m9 18 6-6-6-6"]'
      );
      separators.forEach(separator => {
        const svgElement = separator.parentElement;
        expect(svgElement).toHaveAttribute('aria-hidden', 'true');
      });
    });
  });
});

describe('BreadcrumbSeparator', () => {
  it('renders separator with default styling', () => {
    const { container } = render(<BreadcrumbSeparator />);

    const separator = container.querySelector('svg') as SVGElement;
    expect(separator).toHaveClass('h-4', 'w-4', 'text-muted-foreground');
    expect(separator).toHaveAttribute('aria-hidden', 'true');
  });

  it('applies custom className', () => {
    const { container } = render(
      <BreadcrumbSeparator className='custom-separator' />
    );

    const separator = container.querySelector('svg') as SVGElement;
    expect(separator).toHaveClass('custom-separator');
  });
});

describe('BreadcrumbItem', () => {
  it('renders inactive item', () => {
    render(<BreadcrumbItem>Test Item</BreadcrumbItem>);

    const item = screen.getByText('Test Item');
    expect(item).toHaveClass('text-muted-foreground');
    expect(item).not.toHaveAttribute('aria-current');
  });

  it('renders active item', () => {
    render(<BreadcrumbItem isActive>Active Item</BreadcrumbItem>);

    const item = screen.getByText('Active Item');
    expect(item).toHaveClass('font-medium', 'text-foreground');
    expect(item).toHaveAttribute('aria-current', 'page');
  });

  it('applies custom className', () => {
    render(<BreadcrumbItem className='custom-item'>Custom</BreadcrumbItem>);

    const item = screen.getByText('Custom');
    expect(item).toHaveClass('custom-item');
  });
});
