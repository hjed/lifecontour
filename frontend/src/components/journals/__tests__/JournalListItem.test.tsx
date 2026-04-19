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
import { toDisplayJournal } from '../test-helpers';

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
    const displayJournal = toDisplayJournal(baseJournal);
    render(<JournalListItem journal={displayJournal} />);

    expect(screen.getByTestId('journal-1')).toBeInTheDocument();
    expect(screen.getByText('Test Journal')).toBeInTheDocument();
    expect(screen.getByText('01 Jan 2024')).toBeInTheDocument();
  });

  it('displays journal title as a link', () => {
    const displayJournal = toDisplayJournal(baseJournal);
    render(<JournalListItem journal={displayJournal} />);

    const link = screen.getByRole('link', { name: 'Test Journal' });
    expect(link).toHaveAttribute('href', '/journals/1');
  });

  it('displays type icons', () => {
    const displayJournal = toDisplayJournal(baseJournal);
    render(<JournalListItem journal={displayJournal} />);

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

    const displayJournal = toDisplayJournal(multiTypeJournal);
    render(<JournalListItem journal={displayJournal} />);

    const typeIcons = screen.getByLabelText('Journal types');
    expect(typeIcons.children).toHaveLength(3);
  });

  it('displays tags', () => {
    const journalWithTags: JournalResource = {
      ...baseJournal,
      attributes: {
        ...baseJournal.attributes,
        tags: [
          { id: '1', name: 'Personal', color: '#FF0000' },
          { id: '2', name: 'Work', color: '#00FF00' },
        ],
      },
    };

    const displayJournal = toDisplayJournal(journalWithTags);
    render(<JournalListItem journal={displayJournal} />);

    expect(screen.getByTestId('tag-Personal')).toBeInTheDocument();
    expect(screen.getByTestId('tag-Work')).toBeInTheDocument();
  });

  describe('Contact Avatar Stack', () => {
    it('does not render contact stack if 0 contacts', () => {
      const displayJournal = toDisplayJournal(baseJournal);
      render(<JournalListItem journal={displayJournal} />);

      expect(
        screen.queryByTestId('journal-contacts-stack')
      ).not.toBeInTheDocument();
    });

    it('renders exactly 1 contact avatar with a link', () => {
      const journalWithContacts: JournalResource = {
        ...baseJournal,
        attributes: {
          ...baseJournal.attributes,
          contacts: [
            {
              id: '1',
              name: 'John Doe',
              first_name: 'John',
              last_name: 'Doe',
              relationship_type: JournalContactRelationshipType.PARTICIPANT,
            },
          ],
        },
      };

      const displayJournal = toDisplayJournal(journalWithContacts);
      render(<JournalListItem journal={displayJournal} />);

      expect(screen.getByTestId('journal-contacts-stack')).toBeInTheDocument();

      const link = screen.getByRole('link', { name: 'View John Doe' });
      expect(link).toHaveAttribute('href', '/contacts/1');
      expect(link).toBeInTheDocument();
      expect(
        screen.queryByTestId('journal-contacts-overflow')
      ).not.toBeInTheDocument();
    });

    it('renders 3 contact avatars without overflow', () => {
      const generateContact = (id: string, name: string) => ({
        id,
        name,
        relationship_type: JournalContactRelationshipType.PARTICIPANT,
      });

      const journalWithContacts: JournalResource = {
        ...baseJournal,
        attributes: {
          ...baseJournal.attributes,
          contacts: [
            generateContact('1', 'Alpha'),
            generateContact('2', 'Beta'),
            generateContact('3', 'Charlie'),
          ],
        },
      };

      const displayJournal = toDisplayJournal(journalWithContacts);
      render(<JournalListItem journal={displayJournal} />);

      expect(screen.getByTestId('journal-contacts-stack')).toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: 'View Alpha' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: 'View Beta' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: 'View Charlie' })
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId('journal-contacts-overflow')
      ).not.toBeInTheDocument();
    });

    it('renders 3 contact avatars with +2 overflow text for 5 contacts', () => {
      const generateContact = (id: string, name: string) => ({
        id,
        name,
        relationship_type: JournalContactRelationshipType.PARTICIPANT,
      });

      const journalWithContacts: JournalResource = {
        ...baseJournal,
        attributes: {
          ...baseJournal.attributes,
          contacts: [
            generateContact('1', 'Alpha'),
            generateContact('2', 'Beta'),
            generateContact('3', 'Charlie'),
            generateContact('4', 'Delta'),
            generateContact('5', 'Echo'),
          ],
        },
      };

      const displayJournal = toDisplayJournal(journalWithContacts);
      render(<JournalListItem journal={displayJournal} />);

      expect(screen.getByTestId('journal-contacts-stack')).toBeInTheDocument();

      // Top 3 render
      expect(
        screen.getByRole('link', { name: 'View Alpha' })
      ).toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: 'View Charlie' })
      ).toBeInTheDocument();

      // Overflows don't render native avatars
      expect(
        screen.queryByRole('link', { name: 'View Delta' })
      ).not.toBeInTheDocument();

      // Indicator test
      const overflow = screen.getByTestId('journal-contacts-overflow');
      expect(overflow).toBeInTheDocument();
      expect(overflow).toHaveTextContent('+2');
    });
  });

  it('displays content excerpt', () => {
    const displayJournal = toDisplayJournal(baseJournal);
    render(<JournalListItem journal={displayJournal} />);

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

    const displayJournal = toDisplayJournal(journalWithLongContent);
    render(<JournalListItem journal={displayJournal} />);

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

    const displayJournal = toDisplayJournal(journalWithCalendar);
    render(<JournalListItem journal={displayJournal} />);

    const colorBar = screen.getByTestId('journal-1').querySelector('.absolute');
    expect(colorBar).toHaveStyle({ backgroundColor: '#FF0000' });
  });

  it('applies custom className', () => {
    const displayJournal = toDisplayJournal(baseJournal);
    render(
      <JournalListItem journal={displayJournal} className='custom-class' />
    );

    const item = screen.getByTestId('journal-1');
    expect(item).toHaveClass('custom-class');
  });
});
