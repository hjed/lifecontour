/**
 * Tests for JournalBreadcrumb component.
 *
 * Tests breadcrumb navigation for parent journal hierarchy.
 */

import { render, screen } from '@testing-library/react';
import { JournalBreadcrumb } from '../JournalBreadcrumb';
import type { ParentJournalSummary } from '@/types/journals';

// Mock next/link
jest.mock('next/link', () => {
  const MockLink = ({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) => <a href={href}>{children}</a>;
  MockLink.displayName = 'MockLink';
  return MockLink;
});

describe('JournalBreadcrumb', () => {
  const mockParent: ParentJournalSummary = {
    id: 'parent-1',
    title: 'Parent Journal',
  };

  describe('Rendering', () => {
    it('renders journals link when no parent', () => {
      render(
        <JournalBreadcrumb parent={null} currentTitle='Current Journal' />
      );

      expect(screen.getByText('Journals')).toBeInTheDocument();
      expect(screen.getByText('Current Journal')).toBeInTheDocument();
    });

    it('renders parent link when parent exists', () => {
      render(
        <JournalBreadcrumb parent={mockParent} currentTitle='Current Journal' />
      );

      expect(screen.getByText('Journals')).toBeInTheDocument();
      expect(screen.getByText('Parent Journal')).toBeInTheDocument();
      expect(screen.getByText('Current Journal')).toBeInTheDocument();
    });

    it('renders breadcrumb separators', () => {
      render(
        <JournalBreadcrumb parent={mockParent} currentTitle='Current Journal' />
      );

      const breadcrumb = screen.getByRole('navigation');
      expect(breadcrumb).toBeInTheDocument();
    });

    it('applies custom className', () => {
      const { container } = render(
        <JournalBreadcrumb
          parent={null}
          currentTitle='Current Journal'
          className='custom-class'
        />
      );

      expect(container.firstChild).toHaveClass('custom-class');
    });
  });

  describe('Links', () => {
    it('journals link points to journals list', () => {
      render(
        <JournalBreadcrumb parent={null} currentTitle='Current Journal' />
      );

      const journalsLink = screen.getByText('Journals').closest('a');
      expect(journalsLink).toHaveAttribute('href', '/journals');
    });

    it('parent link points to parent journal', () => {
      render(
        <JournalBreadcrumb parent={mockParent} currentTitle='Current Journal' />
      );

      const parentLink = screen.getByText('Parent Journal').closest('a');
      expect(parentLink).toHaveAttribute('href', '/journals/parent-1');
    });

    it('current title is not a link', () => {
      render(
        <JournalBreadcrumb parent={null} currentTitle='Current Journal' />
      );

      const currentText = screen.getByText('Current Journal');
      expect(currentText.closest('a')).toBeNull();
    });
  });

  describe('Accessibility', () => {
    it('has navigation role', () => {
      render(
        <JournalBreadcrumb parent={null} currentTitle='Current Journal' />
      );

      expect(screen.getByRole('navigation')).toBeInTheDocument();
    });

    it('has aria-label', () => {
      render(
        <JournalBreadcrumb parent={null} currentTitle='Current Journal' />
      );

      expect(screen.getByLabelText('Breadcrumb')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('handles empty current title', () => {
      render(<JournalBreadcrumb parent={null} currentTitle='' />);

      expect(screen.getByText('Journals')).toBeInTheDocument();
      expect(screen.getByTestId('current-title')).toBeInTheDocument();
    });

    it('handles long parent title', () => {
      const longParent: ParentJournalSummary = {
        id: 'parent-1',
        title: 'This is a very long parent journal title that might wrap',
      };

      render(<JournalBreadcrumb parent={longParent} currentTitle='Current' />);

      expect(
        screen.getByText(
          'This is a very long parent journal title that might wrap'
        )
      ).toBeInTheDocument();
    });
  });
});
