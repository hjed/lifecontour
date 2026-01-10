/**
 * Tests for JournalListItem component.
 */

import { render, screen } from '@testing-library/react';
import { JournalListItem } from '../JournalListItem';
import {
  JournalResource,
  JournalType,
  JournalContactRelationshipType,
} from '@/types/journals';

// Mock date-fns
jest.mock('date-fns', () => ({
  format: jest.fn(() => '01 Jan 2024'),
}));

jest.mock('date-fns/locale', () => ({
  enAU: {},
}));

describe('JournalListItem', () => {
  const baseJournal: JournalResource = {
    type: 'journals',
    id: '1',
    attributes: {
      title: 'Test Journal',
      content: 'This is a test journal entry with some content.',
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
  };

  it('renders journal item with correct structure', () => {
    render(<JournalListItem journal={baseJournal} />);

    expect(screen.getByTestId('journal-1')).toBeInTheDocument();
    expect(screen.getByText('Test Journal')).toBeInTheDocument();
    expect(screen.getByText('01 Jan 2024')).toBeInTheDocument();
  });

  it('displays journal title as a link', () => {
    render(<JournalListItem journal={baseJournal} />);

    const link = screen.getByRole('link', { name: 'Test Journal' });
    expect(link).toHaveAttribute('href', '/journals/1');
  });

  it('displays type icons', () => {
    render(<JournalListItem journal={baseJournal} />);

    const typeIcons = screen.getByLabelText('Journal types');
    expect(typeIcons).toBeInTheDocument();
  });

  it('displays multiple type icons', () => {
    const multiTypeJournal: JournalResource = {
      ...baseJournal,
      attributes: {
        ...baseJournal.attributes,
        types: [JournalType.NOTE, JournalType.EVENT, JournalType.MOOD_RATING],
      },
    };

    render(<JournalListItem journal={multiTypeJournal} />);

    const typeIcons = screen.getByLabelText('Journal types');
    expect(typeIcons.children).toHaveLength(3);
  });

  it('displays tags', () => {
    const journalWithTags: JournalResource = {
      ...baseJournal,
      attributes: {
        ...baseJournal.attributes,
        tags: [
          { id: 1, name: 'Personal', color: '#FF0000' },
          { id: 2, name: 'Work', color: '#00FF00' },
        ],
      },
    };

    render(<JournalListItem journal={journalWithTags} />);

    expect(screen.getByTestId('tag-Personal')).toBeInTheDocument();
    expect(screen.getByTestId('tag-Work')).toBeInTheDocument();
  });

  it('displays contacts', () => {
    const journalWithContacts: JournalResource = {
      ...baseJournal,
      attributes: {
        ...baseJournal.attributes,
        contacts: [
          {
            id: 1,
            name: 'John Doe',
            relationship_type: JournalContactRelationshipType.PARTICIPANT,
          },
          {
            id: 2,
            name: 'Jane Smith',
            relationship_type: JournalContactRelationshipType.INVITEE,
          },
        ],
      },
    };

    render(<JournalListItem journal={journalWithContacts} />);

    expect(screen.getByTestId('contact-1')).toBeInTheDocument();
    expect(screen.getByText('John Doe')).toBeInTheDocument();
    expect(screen.getByTestId('contact-2')).toBeInTheDocument();
    expect(screen.getByText('Jane Smith')).toBeInTheDocument();
  });

  it('displays content excerpt', () => {
    render(<JournalListItem journal={baseJournal} />);

    expect(
      screen.getByText('This is a test journal entry with some content.')
    ).toBeInTheDocument();
  });

  it('truncates long content', () => {
    const longContent = 'A'.repeat(250);
    const journalWithLongContent: JournalResource = {
      ...baseJournal,
      attributes: {
        ...baseJournal.attributes,
        content: longContent,
      },
    };

    render(<JournalListItem journal={journalWithLongContent} />);

    const displayedContent = screen.getByText(/A+\.\.\./);
    expect(displayedContent.textContent?.length).toBeLessThan(
      longContent.length
    );
  });

  it('displays calendar color bar', () => {
    const journalWithCalendar: JournalResource = {
      ...baseJournal,
      attributes: {
        ...baseJournal.attributes,
        calendar: {
          id: 'cal-1',
          name: 'Personal',
          color: '#FF0000',
        },
      },
    };

    render(<JournalListItem journal={journalWithCalendar} />);

    const colorBar = screen.getByTestId('journal-1').querySelector('.absolute');
    expect(colorBar).toHaveStyle({ backgroundColor: '#FF0000' });
  });

  it('applies custom className', () => {
    render(<JournalListItem journal={baseJournal} className='custom-class' />);

    const item = screen.getByTestId('journal-1');
    expect(item).toHaveClass('custom-class');
  });
});
