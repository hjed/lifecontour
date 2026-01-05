/**
 * Tests for JournalList component.
 */

import { render, screen } from '@testing-library/react';
import { JournalList } from '../JournalList';
import { JournalResource, JournalType } from '@/types/journals';

// Mock JournalListItem component
jest.mock('../JournalListItem', () => ({
  JournalListItem: ({ journal }: { journal: JournalResource }) => (
    <div data-testid={`journal-item-${journal.id}`}>
      {journal.attributes.title}
    </div>
  ),
}));

describe('JournalList', () => {
  const mockJournals: JournalResource[] = [
    {
      type: 'journals',
      id: '1',
      attributes: {
        title: 'Journal 1',
        content: 'Content 1',
        event_date_range: {
          start: '2024-01-01',
          end: '2024-01-01',
        },
        types: [JournalType.NOTE],
        tags: [],
        contacts: [],
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      },
    },
    {
      type: 'journals',
      id: '2',
      attributes: {
        title: 'Journal 2',
        content: 'Content 2',
        event_date_range: {
          start: '2024-01-02',
          end: '2024-01-02',
        },
        types: [JournalType.EVENT],
        tags: [],
        contacts: [],
        created_at: '2024-01-02T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
      },
    },
    {
      type: 'journals',
      id: '3',
      attributes: {
        title: 'Journal 3',
        content: 'Content 3',
        event_date_range: {
          start: '2024-01-03',
          end: '2024-01-03',
        },
        types: [JournalType.MOOD_RATING],
        tags: [],
        contacts: [],
        created_at: '2024-01-03T00:00:00Z',
        updated_at: '2024-01-03T00:00:00Z',
      },
    },
  ];

  it('renders all journals', () => {
    render(<JournalList journals={mockJournals} />);

    expect(screen.getByTestId('journal-item-1')).toBeInTheDocument();
    expect(screen.getByTestId('journal-item-2')).toBeInTheDocument();
    expect(screen.getByTestId('journal-item-3')).toBeInTheDocument();
  });

  it('renders empty state when no journals and emptyState provided', () => {
    const emptyState = <div data-testid='empty-state'>No journals found</div>;

    render(<JournalList journals={[]} emptyState={emptyState} />);

    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('No journals found')).toBeInTheDocument();
  });

  it('renders nothing when no journals and no emptyState provided', () => {
    const { container } = render(<JournalList journals={[]} />);

    expect(container.firstChild).toBeEmptyDOMElement();
  });

  it('applies default grid className', () => {
    const { container } = render(<JournalList journals={mockJournals} />);

    const gridElement = container.firstChild as HTMLElement;
    expect(gridElement).toHaveClass('grid');
    expect(gridElement).toHaveClass('gap-4');
    expect(gridElement).toHaveClass('md:grid-cols-2');
    expect(gridElement).toHaveClass('lg:grid-cols-3');
  });

  it('applies custom className', () => {
    const { container } = render(
      <JournalList journals={mockJournals} className='custom-grid' />
    );

    const gridElement = container.firstChild as HTMLElement;
    expect(gridElement).toHaveClass('custom-grid');
  });

  it('renders single journal', () => {
    render(<JournalList journals={[mockJournals[0]]} />);

    expect(screen.getByTestId('journal-item-1')).toBeInTheDocument();
    expect(screen.queryByTestId('journal-item-2')).not.toBeInTheDocument();
  });

  it('maintains journal order', () => {
    const { container } = render(<JournalList journals={mockJournals} />);

    const items = container.querySelectorAll('[data-testid^="journal-item-"]');
    expect(items[0]).toHaveAttribute('data-testid', 'journal-item-1');
    expect(items[1]).toHaveAttribute('data-testid', 'journal-item-2');
    expect(items[2]).toHaveAttribute('data-testid', 'journal-item-3');
  });
});
