/**
 * Tests for JournalChildrenList component.
 *
 * Tests child journals list display and navigation.
 */

import { render, screen } from '@testing-library/react';
import { JournalChildrenList } from '../JournalChildrenList';
import { JournalType, type ChildJournalSummary } from '@/types/journals';

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

describe('JournalChildrenList', () => {
  const mockChildren: ChildJournalSummary[] = [
    {
      id: 'child-1',
      title: 'Child Journal 1',
      types: [JournalType.NOTE],
      date: '2025-01-15T00:00:00Z',
    },
    {
      id: 'child-2',
      title: 'Child Journal 2',
      types: [JournalType.EVENT, JournalType.PLAN],
      date: '2025-01-16T00:00:00Z',
    },
  ];

  describe('Rendering', () => {
    it('renders children list with title', () => {
      render(<JournalChildrenList childJournals={mockChildren} />);

      expect(screen.getByText('Child Journals')).toBeInTheDocument();
      expect(screen.getByTestId('children-list')).toBeInTheDocument();
    });

    it('renders all child journals', () => {
      render(<JournalChildrenList childJournals={mockChildren} />);

      expect(screen.getByText('Child Journal 1')).toBeInTheDocument();
      expect(screen.getByText('Child Journal 2')).toBeInTheDocument();
    });

    it('renders nothing when children array is empty', () => {
      const { container } = render(<JournalChildrenList childJournals={[]} />);

      expect(container.firstChild).toBeNull();
    });

    it('displays dates for each child', () => {
      render(<JournalChildrenList childJournals={mockChildren} />);

      expect(screen.getByText('Jan 15, 2025')).toBeInTheDocument();
      expect(screen.getByText('Jan 16, 2025')).toBeInTheDocument();
    });

    it('displays type badges for each child', () => {
      render(<JournalChildrenList childJournals={mockChildren} />);

      expect(screen.getByText('Note')).toBeInTheDocument();
      expect(screen.getByText('Event')).toBeInTheDocument();
      expect(screen.getByText('Plan')).toBeInTheDocument();
    });
  });

  describe('Navigation', () => {
    it('renders links to child journals', () => {
      render(<JournalChildrenList childJournals={mockChildren} />);

      const link1 = screen.getByText('Child Journal 1').closest('a');
      expect(link1).toHaveAttribute('href', '/journals/child-1');

      const link2 = screen.getByText('Child Journal 2').closest('a');
      expect(link2).toHaveAttribute('href', '/journals/child-2');
    });
  });

  describe('Accessibility', () => {
    it('applies custom className', () => {
      render(
        <JournalChildrenList
          childJournals={mockChildren}
          className='custom-class'
        />
      );

      expect(screen.getByTestId('children-list')).toHaveClass('custom-class');
    });

    it('has proper test ids', () => {
      render(<JournalChildrenList childJournals={mockChildren} />);

      expect(screen.getByTestId('children-list')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('handles child without date', () => {
      const childWithoutDate: ChildJournalSummary = {
        id: 'child-3',
        title: 'Child Without Date',
        types: [JournalType.NOTE],
        date: null,
      };

      render(<JournalChildrenList childJournals={[childWithoutDate]} />);

      expect(screen.getByText('Child Without Date')).toBeInTheDocument();
    });

    it('handles child with multiple types', () => {
      const childWithManyTypes: ChildJournalSummary = {
        id: 'child-4',
        title: 'Multi-type Child',
        types: [
          JournalType.NOTE,
          JournalType.EVENT,
          JournalType.MOOD_RATING,
          JournalType.PLAN,
        ],
        date: null,
      };

      render(<JournalChildrenList childJournals={[childWithManyTypes]} />);

      expect(screen.getByText('Multi-type Child')).toBeInTheDocument();
      expect(screen.getByText('Note')).toBeInTheDocument();
      expect(screen.getByText('Event')).toBeInTheDocument();
      expect(screen.getByText('Mood Rating')).toBeInTheDocument();
      expect(screen.getByText('Plan')).toBeInTheDocument();
    });
  });
});
